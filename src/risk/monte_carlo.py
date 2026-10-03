"""WS3 Monte Carlo risk over the injected shared simulator.

Each trial multiplies the parent ActionAssumptions by independent uniform draws
(action-major ``(effectiveness, capex, fixed_opex)``, 18 channels) and calls the
injected SimulationFn. No action or accounting formula is duplicated here.

Provisional policies (boundary draft, pending WS2 review): effect multipliers
apply to renewable/EV/travel effectiveness, building/cloud maximum reduction and
supplier maximum reduction AND monthly savings; capex and fixed monthly opex are
sampled per action; tariffs, grid factors and asset lives stay fixed. Trial flags
use raw tolerances (cost <= budget + 0.01 GBP, profit >= floor - 0.01 GBP,
reduction >= target - 1e-8).
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd

from src.contracts.errors import CarbonOptError, ContractValidationError, RiskError
from src.contracts.identity import canonical_hash, compute_strategy_id
from src.contracts.protocols import SimulationFn
from src.contracts.serialization import RISK_SAMPLE_SPEC, assumptions_to_dict
from src.contracts.types import (
    ACTION_NAMES,
    SCHEMA_VERSION,
    ActionAssumptions,
    ActionConfig,
    ActionCost,
    BaselineBundle,
    ConstraintConfig,
    Provenance,
    RiskConfig,
    RiskResult,
)
from src.contracts.validation import (
    CURRENCY_ATOL_GBP,
    RATIO_ATOL,
    require_finite,
    require_nonempty_str,
    validate_action_config,
    validate_assumptions,
    validate_baseline,
    validate_constraints_for_baseline,
    validate_risk_config,
    validate_risk_result,
)

CHANNELS: tuple[str, ...] = ("effectiveness", "capex", "fixed_opex")
N_CHANNELS = len(ACTION_NAMES) * len(CHANNELS)  # 18
DEFAULT_UNCERTAINTY_PATH = Path(__file__).resolve().parents[2] / "config" / "uncertainty.json"
PROVIDER_NAME = "ws3-monte-carlo"

# Parent effect fields scaled by each action's effectiveness multiplier.
EFFECT_FIELDS: Mapping[str, tuple[str, ...]] = {
    "renewable_energy": ("renewable_effectiveness",),
    "ev_adoption": ("ev_effectiveness",),
    "building_efficiency": ("building_max_reduction",),
    "travel_reduction": ("travel_effectiveness",),
    "cloud_efficiency": ("cloud_max_reduction",),
    "supplier_transition": ("supplier_max_reduction", "supplier_monthly_savings_at_full_gbp"),
}


@dataclass(frozen=True)
class UncertaintySpec:
    """Independent uniform multiplier bounds per action and channel."""

    uncertainty_id: str
    sampler_version: str
    calibration_note: str
    bounds: Mapping[str, Mapping[str, tuple[float, float]]]

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "UncertaintySpec":
        if data.get("distribution", "uniform") != "uniform":
            raise ContractValidationError("uncertainty.distribution", "only 'uniform' is supported")
        if data.get("correlation") is not None:
            raise ContractValidationError("uncertainty.correlation", "correlated sampling is not supported")
        actions = data.get("actions")
        if not isinstance(actions, Mapping) or set(actions) != set(ACTION_NAMES):
            raise ContractValidationError("uncertainty.actions", f"must contain exactly {list(ACTION_NAMES)}")
        bounds: dict[str, dict[str, tuple[float, float]]] = {}
        for name in ACTION_NAMES:
            entry = actions[name]
            if not isinstance(entry, Mapping) or set(entry) != set(CHANNELS):
                raise ContractValidationError(f"uncertainty.actions.{name}", f"must contain exactly {list(CHANNELS)}")
            bounds[name] = {}
            for ch in CHANNELS:
                f = f"uncertainty.actions.{name}.{ch}"
                pair = entry[ch]
                if not isinstance(pair, (list, tuple)) or len(pair) != 2:
                    raise ContractValidationError(f, "must be [low, high]")
                lo, hi = require_finite(f, pair[0]), require_finite(f, pair[1])
                if lo > hi:
                    raise ContractValidationError(f, "low must be <= high")
                if ch == "effectiveness" and not (0.0 <= lo and hi <= 1.0):
                    raise ContractValidationError(f, "effect multipliers must be within [0, 1]")
                if lo < 0:
                    raise ContractValidationError(f, "cost multipliers must be >= 0")
                bounds[name][ch] = (lo, hi)
        return cls(
            uncertainty_id=require_nonempty_str("uncertainty.uncertainty_id", data.get("uncertainty_id")),
            sampler_version=require_nonempty_str("uncertainty.sampler_version", data.get("sampler_version")),
            calibration_note=str(data.get("calibration_note", "")),
            bounds=bounds,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "uncertainty_id": self.uncertainty_id,
            "sampler_version": self.sampler_version,
            "distribution": "uniform",
            "correlation": None,
            "calibration_note": self.calibration_note,
            "actions": {n: {ch: list(self.bounds[n][ch]) for ch in CHANNELS} for n in ACTION_NAMES},
        }

    def content_hash(self) -> str:
        return canonical_hash(self.to_dict())

    @classmethod
    def neutral(cls) -> "UncertaintySpec":
        return cls.from_dict({
            "uncertainty_id": "neutral-test",
            "sampler_version": "uniform-independent-v1",
            "calibration_note": "All multipliers fixed at 1 (parity tests).",
            "actions": {n: {ch: [1.0, 1.0] for ch in CHANNELS} for n in ACTION_NAMES},
        })


def load_uncertainty(path: str | Path = DEFAULT_UNCERTAINTY_PATH) -> UncertaintySpec:
    return UncertaintySpec.from_dict(json.loads(Path(path).read_text()))


def sample_multipliers(spec: UncertaintySpec, seed: int, n: int) -> np.ndarray:
    """n x 18 multipliers; column = action_index * 3 + channel_index. All channels drawn."""
    u = np.random.default_rng(seed).random((n, N_CHANNELS))
    lo = np.array([spec.bounds[a][c][0] for a in ACTION_NAMES for c in CHANNELS])
    hi = np.array([spec.bounds[a][c][1] for a in ACTION_NAMES for c in CHANNELS])
    return lo + u * (hi - lo)


def apply_multipliers(parent: ActionAssumptions, row: np.ndarray, assumptions_id: str) -> ActionAssumptions:
    """New ActionAssumptions for one trial; the parent is never mutated."""
    updates: dict[str, Any] = {}
    costs: dict[str, ActionCost] = {}
    for i, name in enumerate(ACTION_NAMES):
        eff, capex, opex = row[3 * i : 3 * i + 3]
        for f in EFFECT_FIELDS[name]:
            updates[f] = float(getattr(parent, f)) * float(eff)
        c = parent.costs[name]
        costs[name] = ActionCost(
            capex_at_full_gbp=float(c.capex_at_full_gbp) * float(capex),
            monthly_opex_at_full_gbp=float(c.monthly_opex_at_full_gbp) * float(opex),
            asset_life_months=c.asset_life_months,
        )
    return replace(parent, assumptions_id=assumptions_id, costs=costs, **updates)


def _metric(metrics: Mapping[str, Any], key: str, trial: int) -> float:
    value = metrics.get(key)
    if value is None or not math.isfinite(float(value)):
        raise RiskError(f"trial {trial}: simulator metric {key!r} is missing or nonfinite")
    return float(value)


def evaluate_strategy_risk(
    baseline: BaselineBundle,
    action_config: ActionConfig,
    *,
    constraints: ConstraintConfig,
    assumptions: ActionAssumptions,
    uncertainty: UncertaintySpec,
    config: RiskConfig,
    simulator: SimulationFn,
) -> RiskResult:
    validate_baseline(baseline)
    validate_action_config(action_config)
    validate_constraints_for_baseline(constraints, baseline)
    validate_assumptions(assumptions)
    validate_risk_config(config)
    if config.seed < 0:
        raise ContractValidationError("risk_config.seed", "must be >= 0")

    n = config.n_simulations
    parent_hash = canonical_hash(assumptions_to_dict(assumptions))
    spec_hash = uncertainty.content_hash()
    id_stem = f"{assumptions.assumptions_id}-mc-{canonical_hash([parent_hash, spec_hash, config.seed])[:12]}"
    draws = sample_multipliers(uncertainty, config.seed, n)

    co2, profit, cost = np.empty(n), np.empty(n), np.empty(n)
    target_met = np.empty(n, dtype=bool)
    is_mock = False
    for t in range(n):
        trial_assumptions = apply_multipliers(assumptions, draws[t], f"{id_stem}-{t}")
        try:
            result = simulator(baseline, action_config, assumptions=trial_assumptions)
        except CarbonOptError as exc:  # defined boundary failures only; bugs propagate
            raise RiskError(f"trial {t}: simulator failed: {exc}") from exc
        is_mock = is_mock or result.provenance.is_mock
        m = result.metrics
        co2[t] = _metric(m, "total_co2e_tco2e", t)
        profit[t] = _metric(m, "total_profit_gbp", t)
        cost[t] = _metric(m, "total_cost_gbp", t)
        ratio = m.get("co2_reduction_ratio")
        if ratio is None:
            if constraints.min_co2_reduction_ratio > 0:
                raise RiskError(f"trial {t}: reduction ratio undefined (zero baseline CO2) with positive target")
            target_met[t] = True
        else:
            target_met[t] = _metric(m, "co2_reduction_ratio", t) >= constraints.min_co2_reduction_ratio - RATIO_ATOL

    budget_met = cost <= constraints.budget_gbp + CURRENCY_ATOL_GBP
    profit_met = profit >= constraints.min_total_profit_gbp - CURRENCY_ATOL_GBP
    p_target = float(target_met.mean())
    summary = {
        "co2_mean_tco2e": float(co2.mean()),
        "co2_p05_tco2e": float(np.quantile(co2, 0.05)),
        "co2_p95_tco2e": float(np.quantile(co2, 0.95)),
        "profit_mean_gbp": float(profit.mean()),
        "profit_p05_gbp": float(np.quantile(profit, 0.05)),
        "profit_p95_gbp": float(np.quantile(profit, 0.95)),
        "cost_mean_gbp": float(cost.mean()),
        "cost_p95_gbp": float(np.quantile(cost, 0.95)),
        "target_probability": p_target,
        "profit_floor_probability": float(profit_met.mean()),
        "budget_probability": float(budget_met.mean()),
        "joint_feasibility_probability": float((target_met & profit_met & budget_met).mean()),
        "target_probability_mc_standard_error": math.sqrt(p_target * (1 - p_target) / n),
    }
    samples = None
    if config.retain_samples:
        samples = pd.DataFrame({
            "trial_id": np.arange(n, dtype="int64"),
            "total_co2e_tco2e": co2,
            "total_profit_gbp": profit,
            "total_cost_gbp": cost,
            "target_met": target_met,
            "profit_met": profit_met,
            "budget_met": budget_met,
        }, columns=list(RISK_SAMPLE_SPEC))

    input_hash = canonical_hash([
        baseline.baseline_id, baseline.provenance.input_hash, action_config.as_dict(),
        constraints.__dict__, parent_hash, spec_hash, config.seed, n,
    ])
    return validate_risk_result(RiskResult(
        schema_version=SCHEMA_VERSION,
        run_id=f"risk-{input_hash[:12]}",
        provenance=Provenance(
            provider=PROVIDER_NAME,
            is_mock=is_mock,
            seed=config.seed,
            input_hash=input_hash,
            config_id=f"{uncertainty.sampler_version}@{spec_hash[:12]}",
            assumptions_id=assumptions.assumptions_id,
        ),
        baseline_id=baseline.baseline_id,
        strategy_id=compute_strategy_id(baseline.baseline_id, action_config, assumptions.assumptions_id, assumptions.version),
        n_simulations=n,
        uncertainty_id=uncertainty.uncertainty_id,
        summary=summary,
        samples=samples,
    ))
