"""WS2 action definitions, assumption loading, strategy identity and uncertainty hooks.

Every action value is the fraction of the *remaining eligible opportunity* implemented in
month 1 and held for the horizon (docs/ACTION_MODEL.md §1). The vector order is fixed by
:data:`src.contracts.ACTION_NAMES`.
"""

from __future__ import annotations

import dataclasses
import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, Sequence

import numpy as np

from src.contracts import (
    ACTION_NAMES,
    ActionAssumptions,
    ActionConfig,
    ActionCost,
    ActionCosts,
    ContractValidationError,
)
from src.contracts._scalars import require_nonnegative, require_str, require_unit_interval
from src.contracts.serialization import action_assumptions_from_dict, canonical_json, load_json

REPO_ROOT = Path(__file__).resolve().parents[2]
#: Versioned illustrative (uncalibrated) assumptions owned by WS2.
DEFAULT_ASSUMPTIONS_PATH = REPO_ROOT / "config" / "action_assumptions.json"


@dataclass(frozen=True)
class ActionDefinition:
    """Human-readable semantics of one decision variable (for UI labels and documentation)."""

    name: str
    label: str
    eligible_opportunity: str
    effect: str
    effect_coefficient: str


ACTION_DEFINITIONS: tuple[ActionDefinition, ...] = (
    ActionDefinition(
        "renewable_energy",
        "Renewable electricity",
        "Non-renewable share (1 - r) of the resulting electricity demand",
        "r_new = r + (1 - r) * x * renewable_effectiveness; scales existing and EV-added scope2",
        "renewable_effectiveness",
    ),
    ActionDefinition(
        "ev_adoption",
        "Fleet electrification",
        "Remaining ICE fleet km: fleet_km * (1 - ev_share)",
        "Removes x * ev_effectiveness of the ICE-fleet scope1 bucket; adds ev_kwh_per_km per converted km",
        "ev_effectiveness",
    ),
    ActionDefinition(
        "building_efficiency",
        "Building efficiency",
        "Baseline building electricity and gas (not added EV load)",
        "Cuts building electricity and gas by building_max_reduction * x",
        "building_max_reduction",
    ),
    ActionDefinition(
        "travel_reduction",
        "Business travel reduction",
        "Scope3 travel bucket and business_travel_km",
        "Cuts travel emissions and km by x * travel_effectiveness",
        "travel_effectiveness",
    ),
    ActionDefinition(
        "cloud_efficiency",
        "Cloud efficiency",
        "Scope3 cloud bucket and cloud_compute_hours",
        "Cuts cloud emissions and hours by cloud_max_reduction * x",
        "cloud_max_reduction",
    ),
    ActionDefinition(
        "supplier_transition",
        "Supplier transition",
        "Scope3 supplier bucket",
        "Cuts supplier emissions by supplier_max_reduction * x; saves supplier_monthly_savings_at_full_gbp * x",
        "supplier_max_reduction",
    ),
)


def load_action_assumptions(path: str | Path | None = None) -> ActionAssumptions:
    """Load and strictly validate a versioned assumption file (default: config/action_assumptions.json)."""
    return action_assumptions_from_dict(load_json(DEFAULT_ASSUMPTIONS_PATH if path is None else path))


def config_to_vector(config: ActionConfig) -> np.ndarray:
    """Decision vector in canonical order (full precision)."""
    return np.array(config.to_tuple(), dtype=np.float64)


def config_from_vector(values: Sequence[float] | np.ndarray) -> ActionConfig:
    """Validated ActionConfig from a canonical-order vector; out-of-range values are rejected."""
    return ActionConfig.from_sequence([float(v) for v in np.asarray(values, dtype=np.float64).ravel()])


# ---------------------------------------------------------------------------
# Strategy identity (ACTION_MODEL.md §6)
# ---------------------------------------------------------------------------

STRATEGY_ID_PREFIX = "strategy-"
STRATEGY_ID_HEX_LENGTH = 16


def strategy_identity(
    baseline_id: str, config: ActionConfig, *, assumptions_id: str, assumptions_version: str
) -> str:
    """Canonical identity: sorted-key compact JSON of baseline, full-precision config, assumptions."""
    if not isinstance(config, ActionConfig):
        raise ContractValidationError("config", f"expected ActionConfig; got {type(config).__name__}")
    return canonical_json(
        {
            "baseline_id": require_str("baseline_id", baseline_id),
            "config": {name: float(value) for name, value in config.to_dict().items()},
            "assumptions_id": require_str("assumptions_id", assumptions_id),
            "assumptions_version": require_str("assumptions_version", assumptions_version),
        }
    )


def strategy_id_from_identity(identity: str, *, hex_length: int = STRATEGY_ID_HEX_LENGTH) -> str:
    return STRATEGY_ID_PREFIX + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:hex_length]


def compute_strategy_id(baseline_id: str, config: ActionConfig, assumptions: ActionAssumptions) -> str:
    """Stable 16-hex strategy ID for (baseline, exact config, immutable assumption ID/version)."""
    identity = strategy_identity(
        baseline_id, config, assumptions_id=assumptions.assumptions_id, assumptions_version=assumptions.version
    )
    return strategy_id_from_identity(identity)


def assign_strategy_id(
    identity: str,
    taken: Mapping[str, str],
    *,
    id_fn: Callable[..., str] = strategy_id_from_identity,
) -> str:
    """Shortest ID (16, 24, ... 64 hex chars) not already bound to a *different* identity.

    ``taken`` maps already-issued IDs to their full identity, so a truncated-hash collision
    is detected by comparing full identities and resolved by extending the new ID.
    """
    for hex_length in range(STRATEGY_ID_HEX_LENGTH, 65, 8):
        candidate = id_fn(identity, hex_length=hex_length)
        bound = taken.get(candidate)
        if bound is None or bound == identity:
            return candidate
    raise ContractValidationError("strategy_id", "SHA-256 collision on the full digest")


# ---------------------------------------------------------------------------
# P1 uncertainty hook (RISK_AND_BENCHMARK_SPEC.md §1). Sampling itself belongs to WS3.
# ---------------------------------------------------------------------------

_REPLACED_EFFECTIVENESS = {
    "renewable_energy": "renewable_effectiveness",
    "ev_adoption": "ev_effectiveness",
    "travel_reduction": "travel_effectiveness",
}
_SCALED_EFFECTIVENESS = {
    "building_efficiency": "building_max_reduction",
    "cloud_efficiency": "cloud_max_reduction",
    "supplier_transition": "supplier_max_reduction",
}


def _multipliers(field: str, values: Mapping[str, float] | None, validate: Callable[[str, float], float]) -> dict[str, float]:
    if values is None:
        return {}
    if not isinstance(values, Mapping):
        raise ContractValidationError(field, "must be a mapping keyed by action name")
    unknown = sorted(set(values) - set(ACTION_NAMES))
    if unknown:
        raise ContractValidationError(field, f"unknown action names {unknown}")
    return {name: validate(f"{field}.{name}", value) for name, value in values.items()}


def apply_uncertainty_sample(
    assumptions: ActionAssumptions,
    *,
    sample_id: str,
    effectiveness_multipliers: Mapping[str, float] | None = None,
    capex_multipliers: Mapping[str, float] | None = None,
    opex_multipliers: Mapping[str, float] | None = None,
) -> ActionAssumptions:
    """Return an immutable sampled copy of ``assumptions`` for one Monte Carlo trial.

    Mapping (RISK_AND_BENCHMARK_SPEC.md §1): renewable/EV/travel multipliers *replace*
    their effectiveness; building/cloud/supplier multipliers scale their maximum-reduction
    coefficients, and the supplier multiplier also scales supplier savings. Capex/opex
    multipliers scale the per-action cost coefficients, so ineffective investments still
    cost money. Missing actions keep their deterministic values. ``sample_id`` becomes the
    copy's ``assumptions_id`` and must differ from the parent's, so sampled parameters never
    share a deterministic strategy identity. The deterministic accounting is unchanged.
    """
    if not isinstance(assumptions, ActionAssumptions):
        raise ContractValidationError("assumptions", f"expected ActionAssumptions; got {type(assumptions).__name__}")
    sample_id = require_str("sample_id", sample_id)
    if sample_id == assumptions.assumptions_id:
        raise ContractValidationError("sample_id", "must differ from the parent assumptions_id")
    effectiveness = _multipliers("effectiveness_multipliers", effectiveness_multipliers, require_unit_interval)
    capex = _multipliers("capex_multipliers", capex_multipliers, require_nonnegative)
    opex = _multipliers("opex_multipliers", opex_multipliers, require_nonnegative)

    updates: dict[str, float] = {}
    for name, multiplier in effectiveness.items():
        if name in _REPLACED_EFFECTIVENESS:
            updates[_REPLACED_EFFECTIVENESS[name]] = multiplier
        else:
            field = _SCALED_EFFECTIVENESS[name]
            updates[field] = getattr(assumptions, field) * multiplier
        if name == "supplier_transition":
            updates["supplier_monthly_savings_at_full_gbp"] = assumptions.supplier_monthly_savings_at_full_gbp * multiplier
    costs = {
        name: ActionCost(
            capex_at_full_gbp=cost.capex_at_full_gbp * capex.get(name, 1.0),
            monthly_opex_at_full_gbp=cost.monthly_opex_at_full_gbp * opex.get(name, 1.0),
            asset_life_months=cost.asset_life_months,
        )
        for name, cost in assumptions.costs.items()
    }
    return dataclasses.replace(assumptions, assumptions_id=sample_id, costs=ActionCosts(**costs), **updates)
