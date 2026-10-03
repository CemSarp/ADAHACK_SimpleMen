"""JSON conversion for contract 1.0.0 objects (shared C0 file; flag for WS4 review).

Rules (SHARED_CONTRACTS.md §1): dates serialize as ISO calendar dates, numbers as built-in
int/float with full ``repr`` precision, missing optional values as ``null``; NaN/Infinity
are prohibited. Result payloads tolerate unknown additive fields within major version 1;
configuration payloads reject unknown fields so typos cannot fall back to defaults.
"""

from __future__ import annotations

import contextlib
import dataclasses
import datetime as dt
import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any, Iterable, Mapping

import numpy as np
import pandas as pd

from src.contracts._scalars import (
    field_prefix,
    require_bool,
    require_finite,
    require_int,
    require_str,
    require_whole_number,
)
from src.contracts.errors import ContractValidationError
from src.contracts.types import (
    ACTION_NAMES,
    ASSUMPTION_SCALAR_FIELDS,
    BASELINE_MONTHLY_COLUMNS,
    CANDIDATE_COLUMNS,
    METRIC_FIELDS,
    OPTIMIZATION_STATUSES,
    RISK_STATUSES,
    RISK_SUMMARY_FIELDS,
    RISK_TOLERANCES,
    SIMULATION_MONTHLY_COLUMNS,
    ActionAssumptions,
    ActionConfig,
    ActionCost,
    ActionCosts,
    BaselineBundle,
    BaselineTotals,
    ColumnSpec,
    ConstraintConfig,
    ConstraintEvaluation,
    ConstraintSatisfaction,
    OptimizationResult,
    OptimizerConfig,
    Provenance,
    RawViolations,
    RecommendationResult,
    RiskResult,
    RiskSummary,
    SimulationMetrics,
    SimulationResult,
)
from src.contracts.validation import (
    normalize_candidate_frame,
    validate_baseline_bundle,
    validate_risk_result,
    validate_schema_version,
    validate_simulation_result,
)

_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_EFFECTIVENESS_FIELDS = ("renewable_effectiveness", "ev_effectiveness", "travel_effectiveness")
_COST_FIELDS = ("capex_at_full_gbp", "monthly_opex_at_full_gbp", "asset_life_months")
_DTYPES = {"date": "datetime64[ns]", "str": object, "float": np.float64, "nullable_float": np.float64,
           "int": np.int64, "bool": bool}


# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------


def canonical_json(value: Any) -> str:
    """Sorted-key compact JSON with full float precision; NaN/Infinity rejected."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def iso_date(value: Any) -> str:
    return pd.Timestamp(value).strftime("%Y-%m-%d")


def parse_iso_date(field: str, value: Any) -> dt.date:
    text = require_str(field, value)
    if not _ISO_DATE.match(text):
        raise ContractValidationError(field, f"must be an ISO calendar date YYYY-MM-DD; got {text!r}")
    try:
        return dt.date.fromisoformat(text)
    except ValueError:
        raise ContractValidationError(field, f"invalid calendar date {text!r}") from None


def to_jsonable(value: Any, field: str = "value") -> Any:
    """Convert nested diagnostics to JSON-safe built-ins (NumPy scalars, dates, tuples)."""
    if value is None or isinstance(value, (str, bool)):
        return value
    if isinstance(value, np.bool_):
        return bool(value)
    if isinstance(value, (int, np.integer)):
        return int(value)
    if isinstance(value, (float, np.floating)):
        number = float(value)
        if not math.isfinite(number):
            raise ContractValidationError(field, "NaN/Infinity cannot be serialized; use null")
        return number
    if isinstance(value, (dt.date, pd.Timestamp)):
        return iso_date(value)
    if isinstance(value, Mapping):
        out = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise ContractValidationError(field, f"object keys must be strings; got {type(key).__name__}")
            out[key] = to_jsonable(item, f"{field}.{key}")
        return out
    if isinstance(value, (list, tuple)):
        return [to_jsonable(item, f"{field}[{i}]") for i, item in enumerate(value)]
    raise ContractValidationError(field, f"unsupported type {type(value).__name__} for JSON")


def _require_mapping(field: str, data: Any) -> Mapping[str, Any]:
    if not isinstance(data, Mapping):
        raise ContractValidationError(field, f"must be an object; got {type(data).__name__}")
    return data


def _require_keys(field: str, data: Mapping[str, Any], keys: Iterable[str]) -> None:
    missing = [key for key in keys if key not in data]
    if missing:
        raise ContractValidationError(f"{field}.{missing[0]}", f"missing required fields {missing}")


def _reject_unknown(field: str, data: Mapping[str, Any], allowed: Iterable[str]) -> None:
    unknown = sorted(set(data) - set(allowed))
    if unknown:
        raise ContractValidationError(field, f"unknown fields {unknown}")


def _nullable_float(field: str, value: Any) -> float | None:
    return None if value is None else require_finite(field, value)


def empty_frame(columns: ColumnSpec) -> pd.DataFrame:
    """Zero-row frame that keeps the documented columns and dtypes."""
    return pd.DataFrame({name: pd.Series(dtype=_DTYPES[kind]) for name, kind in columns})


def frame_from_records(field: str, records: Any, columns: ColumnSpec) -> pd.DataFrame:
    """Build a typed DataFrame from JSON records; extra record keys are ignored."""
    if not isinstance(records, list):
        raise ContractValidationError(field, f"must be an array of records; got {type(records).__name__}")
    if not records:
        return empty_frame(columns)
    for i, record in enumerate(records):
        _require_mapping(f"{field}[{i}]", record)
        _require_keys(f"{field}[{i}]", record, (name for name, _ in columns))
    data: dict[str, Any] = {}
    for name, kind in columns:
        raw = [record[name] for record in records]
        path = f"{field}.{name}"
        if kind == "date":
            data[name] = np.array([parse_iso_date(path, v) for v in raw], dtype="datetime64[ns]")
        elif kind == "str":
            data[name] = pd.Series([require_str(path, v) for v in raw], dtype=object)
        elif kind == "float":
            data[name] = np.array([require_finite(path, v) for v in raw], dtype=np.float64)
        elif kind == "nullable_float":
            data[name] = np.array([np.nan if v is None else require_finite(path, v) for v in raw], dtype=np.float64)
        elif kind == "int":
            data[name] = np.array([require_whole_number(path, v) for v in raw], dtype=np.int64)
        elif kind == "bool":
            data[name] = np.array([require_bool(path, v) for v in raw], dtype=bool)
        else:  # pragma: no cover - specs are static
            raise ValueError(kind)
    return pd.DataFrame(data)


def frame_to_records(frame: pd.DataFrame, columns: ColumnSpec, field: str = "frame") -> list[dict[str, Any]]:
    """Serialize the documented columns of ``frame`` (extra columns are not emitted)."""
    lists: list[list[Any]] = []
    for name, kind in columns:
        series = frame[name]
        if kind == "date":
            lists.append([iso_date(v) for v in series.to_numpy(dtype="datetime64[ns]")])
        elif kind == "str":
            lists.append([str(v) for v in series.to_numpy(dtype=object)])
        elif kind in ("float", "nullable_float"):
            values = series.to_numpy(dtype=np.float64)
            if kind == "float" and not np.isfinite(values).all():
                raise ContractValidationError(f"{field}.{name}", "NaN/Infinity cannot be serialized")
            if np.isinf(values).any():
                raise ContractValidationError(f"{field}.{name}", "Infinity cannot be serialized")
            lists.append([None if math.isnan(v) else v for v in values.tolist()])
        elif kind == "int":
            lists.append(series.to_numpy(dtype=np.int64).tolist())
        elif kind == "bool":
            lists.append([bool(v) for v in series.to_numpy(dtype=bool)])
    names = [name for name, _ in columns]
    return [dict(zip(names, row)) for row in zip(*lists)] if len(frame) else []


def load_json(path: str | Path) -> Any:
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


# ---------------------------------------------------------------------------
# Provenance and configuration
# ---------------------------------------------------------------------------

_PROVENANCE_FIELDS = ("provider", "is_mock", "seed", "input_hash", "config_id", "assumptions_id")


def provenance_to_dict(provenance: Provenance) -> dict[str, Any]:
    return {name: getattr(provenance, name) for name in _PROVENANCE_FIELDS}


def provenance_from_dict(data: Any, field: str = "provenance") -> Provenance:
    data = _require_mapping(field, data)
    _require_keys(field, data, _PROVENANCE_FIELDS)
    # Provenance errors already start with "provenance."; prefix the enclosing object path.
    prefix = field.rsplit(".", 1)[0] if "." in field else None
    with field_prefix(prefix) if prefix else contextlib.nullcontext():
        return Provenance(**{name: data[name] for name in _PROVENANCE_FIELDS})


def action_config_to_dict(config: ActionConfig) -> dict[str, float]:
    return config.to_dict()


def action_config_from_dict(data: Any) -> ActionConfig:
    return ActionConfig.from_mapping(data)


_CONSTRAINT_FIELDS = ("budget_gbp", "min_total_profit_gbp", "min_co2_reduction_ratio")
_OPTIMIZER_FIELDS = ("seed", "population_size", "generations", "max_evaluations")


def constraint_config_to_dict(constraints: ConstraintConfig) -> dict[str, float]:
    return {name: getattr(constraints, name) for name in _CONSTRAINT_FIELDS}


def constraint_config_from_dict(data: Any) -> ConstraintConfig:
    data = _require_mapping("constraints", data)
    _require_keys("constraints", data, _CONSTRAINT_FIELDS)
    _reject_unknown("constraints", data, _CONSTRAINT_FIELDS)
    return ConstraintConfig(**{name: data[name] for name in _CONSTRAINT_FIELDS})


def optimizer_config_to_dict(config: OptimizerConfig) -> dict[str, int]:
    return {name: getattr(config, name) for name in _OPTIMIZER_FIELDS}


def optimizer_config_from_dict(data: Any) -> OptimizerConfig:
    data = _require_mapping("optimizer_config", data)
    _reject_unknown("optimizer_config", data, _OPTIMIZER_FIELDS)
    return OptimizerConfig(**{name: data[name] for name in _OPTIMIZER_FIELDS if name in data})


# ---------------------------------------------------------------------------
# ActionAssumptions
# ---------------------------------------------------------------------------

_ASSUMPTION_IDENTITY_FIELDS = ("assumptions_id", "version", "is_calibrated", "description")
_ASSUMPTION_KEYS = _ASSUMPTION_IDENTITY_FIELDS + ASSUMPTION_SCALAR_FIELDS + ("costs",)


def action_assumptions_to_dict(assumptions: ActionAssumptions) -> dict[str, Any]:
    out: dict[str, Any] = {name: getattr(assumptions, name) for name in _ASSUMPTION_IDENTITY_FIELDS}
    out.update({name: getattr(assumptions, name) for name in ASSUMPTION_SCALAR_FIELDS})
    out["costs"] = {name: {key: getattr(cost, key) for key in _COST_FIELDS} for name, cost in assumptions.costs.items()}
    return out


def action_assumptions_from_dict(data: Any) -> ActionAssumptions:
    """Strict parser for the versioned assumption object (unknown fields are rejected)."""
    data = _require_mapping("assumptions", data)
    _reject_unknown("assumptions", data, _ASSUMPTION_KEYS)
    _require_keys("assumptions", data, (key for key in _ASSUMPTION_KEYS if key not in _EFFECTIVENESS_FIELDS))
    costs_data = _require_mapping("assumptions.costs", data["costs"])
    _require_keys("assumptions.costs", costs_data, ACTION_NAMES)
    _reject_unknown("assumptions.costs", costs_data, ACTION_NAMES)
    costs = {}
    for name in ACTION_NAMES:
        path = f"assumptions.costs.{name}"
        entry = _require_mapping(path, costs_data[name])
        _require_keys(path, entry, _COST_FIELDS)
        _reject_unknown(path, entry, _COST_FIELDS)
        with field_prefix(path):
            costs[name] = ActionCost(**{key: entry[key] for key in _COST_FIELDS})
    scalars = {key: data[key] for key in _ASSUMPTION_IDENTITY_FIELDS + ASSUMPTION_SCALAR_FIELDS if key in data}
    return ActionAssumptions(**scalars, costs=ActionCosts(**costs))


# ---------------------------------------------------------------------------
# BaselineBundle
# ---------------------------------------------------------------------------

_BASELINE_FIELDS = (
    "schema_version",
    "run_id",
    "provenance",
    "baseline_id",
    "company_id",
    "history_end",
    "horizon_months",
    "model_id",
    "driver_policy_id",
    "data_kind",
    "scope2_method",
    "currency",
    "monthly",
    "totals",
)
_TOTAL_FIELDS = ("revenue_gbp", "operating_profit_gbp", "total_co2e_tco2e")


def baseline_to_dict(baseline: BaselineBundle) -> dict[str, Any]:
    validate_baseline_bundle(baseline)
    return {
        "schema_version": baseline.schema_version,
        "run_id": baseline.run_id,
        "provenance": provenance_to_dict(baseline.provenance),
        "baseline_id": baseline.baseline_id,
        "company_id": baseline.company_id,
        "history_end": iso_date(baseline.history_end),
        "horizon_months": baseline.horizon_months,
        "model_id": baseline.model_id,
        "driver_policy_id": baseline.driver_policy_id,
        "data_kind": baseline.data_kind,
        "scope2_method": baseline.scope2_method,
        "currency": baseline.currency,
        "monthly": frame_to_records(baseline.monthly, BASELINE_MONTHLY_COLUMNS, "baseline.monthly"),
        "totals": {name: getattr(baseline.totals, name) for name in _TOTAL_FIELDS},
    }


def baseline_from_dict(data: Any) -> BaselineBundle:
    data = _require_mapping("baseline", data)
    _require_keys("baseline", data, _BASELINE_FIELDS)
    validate_schema_version("baseline.schema_version", data["schema_version"])
    totals = _require_mapping("baseline.totals", data["totals"])
    _require_keys("baseline.totals", totals, _TOTAL_FIELDS)
    bundle = BaselineBundle(
        schema_version=data["schema_version"],
        run_id=data["run_id"],
        provenance=provenance_from_dict(data["provenance"], "baseline.provenance"),
        baseline_id=data["baseline_id"],
        company_id=data["company_id"],
        history_end=parse_iso_date("baseline.history_end", data["history_end"]),
        horizon_months=require_int("baseline.horizon_months", data["horizon_months"]),
        model_id=data["model_id"],
        driver_policy_id=data["driver_policy_id"],
        data_kind=data["data_kind"],
        scope2_method=data["scope2_method"],
        currency=data["currency"],
        monthly=frame_from_records("baseline.monthly", data["monthly"], BASELINE_MONTHLY_COLUMNS),
        totals=BaselineTotals(**{name: totals[name] for name in _TOTAL_FIELDS}),
    )
    return validate_baseline_bundle(bundle)


# ---------------------------------------------------------------------------
# SimulationResult and ConstraintEvaluation
# ---------------------------------------------------------------------------

_RESULT_HEADER = ("schema_version", "run_id", "provenance")


def simulation_result_to_dict(result: SimulationResult) -> dict[str, Any]:
    validate_simulation_result(result)
    return {
        "schema_version": result.schema_version,
        "run_id": result.run_id,
        "provenance": provenance_to_dict(result.provenance),
        "baseline_id": result.baseline_id,
        "strategy_id": result.strategy_id,
        "config": result.config.to_dict(),
        "monthly": frame_to_records(result.monthly, SIMULATION_MONTHLY_COLUMNS, "simulation.monthly"),
        "metrics": {name: getattr(result.metrics, name) for name in METRIC_FIELDS},
    }


def simulation_result_from_dict(data: Any, field: str = "simulation") -> SimulationResult:
    data = _require_mapping(field, data)
    _require_keys(field, data, _RESULT_HEADER + ("baseline_id", "strategy_id", "config", "monthly", "metrics"))
    validate_schema_version(f"{field}.schema_version", data["schema_version"])
    metrics = _require_mapping(f"{field}.metrics", data["metrics"])
    _require_keys(f"{field}.metrics", metrics, METRIC_FIELDS)
    with field_prefix(field):
        config = ActionConfig.from_mapping(data["config"])
        metric_values = SimulationMetrics(**{name: metrics[name] for name in METRIC_FIELDS})
    result = SimulationResult(
        schema_version=data["schema_version"],
        run_id=require_str(f"{field}.run_id", data["run_id"]),
        provenance=provenance_from_dict(data["provenance"], f"{field}.provenance"),
        baseline_id=require_str(f"{field}.baseline_id", data["baseline_id"]),
        strategy_id=require_str(f"{field}.strategy_id", data["strategy_id"]),
        config=config,
        monthly=frame_from_records(f"{field}.monthly", data["monthly"], SIMULATION_MONTHLY_COLUMNS),
        metrics=metric_values,
    )
    return validate_simulation_result(result)


def constraint_evaluation_to_dict(evaluation: ConstraintEvaluation) -> dict[str, Any]:
    return {
        "g_budget": evaluation.g_budget,
        "g_profit": evaluation.g_profit,
        "g_target": evaluation.g_target,
        "feasible": evaluation.feasible,
        "raw_violations": dataclasses.asdict(evaluation.raw_violations),
        "satisfied": dataclasses.asdict(evaluation.satisfied),
    }


def constraint_evaluation_from_dict(data: Any) -> ConstraintEvaluation:
    data = _require_mapping("constraint_evaluation", data)
    _require_keys("constraint_evaluation", data, ("g_budget", "g_profit", "g_target", "feasible", "raw_violations"))
    raw = _require_mapping("constraint_evaluation.raw_violations", data["raw_violations"])
    _require_keys("constraint_evaluation.raw_violations", raw, ("budget_gbp", "profit_gbp", "reduction_ratio"))
    raw_violations = RawViolations(budget_gbp=raw["budget_gbp"], profit_gbp=raw["profit_gbp"],
                                   reduction_ratio=raw["reduction_ratio"])
    if "satisfied" in data:
        flags = _require_mapping("constraint_evaluation.satisfied", data["satisfied"])
        _require_keys("constraint_evaluation.satisfied", flags, ("budget", "profit", "target"))
        satisfied = ConstraintSatisfaction(budget=flags["budget"], profit=flags["profit"], target=flags["target"])
    else:  # payloads from producers that predate the additive field
        feasible = require_bool("constraint_evaluation.feasible", data["feasible"])
        satisfied = ConstraintSatisfaction(budget=feasible, profit=feasible, target=feasible)
    return ConstraintEvaluation(
        g_budget=data["g_budget"],
        g_profit=data["g_profit"],
        g_target=data["g_target"],
        feasible=data["feasible"],
        raw_violations=raw_violations,
        satisfied=satisfied,
    )


# ---------------------------------------------------------------------------
# OptimizationResult
# ---------------------------------------------------------------------------


def optimization_result_to_dict(result: OptimizationResult, *, strategies: str = "all") -> dict[str, Any]:
    """Serialize an optimization result.

    ``strategies="all"`` (default) is lossless. ``strategies="frontier"`` keeps only the
    Pareto strategies and the tested no-op in the ``strategies`` map (candidate summary rows
    are always complete) and records that choice in the additive ``strategies_included``
    field, for compact saved bundles.
    """
    if result.status not in OPTIMIZATION_STATUSES:
        raise ContractValidationError("optimization.status", f"must be one of {list(OPTIMIZATION_STATUSES)}")
    if strategies == "all":
        selected = dict(result.strategies)
    elif strategies == "frontier":
        keep = set(result.pareto["strategy_id"]) | {result.diagnostics.get("tested_noop_strategy_id")}
        selected = {sid: sim for sid, sim in result.strategies.items() if sid in keep}
    else:
        raise ContractValidationError("strategies", "must be 'all' or 'frontier'")
    return {
        "schema_version": result.schema_version,
        "run_id": result.run_id,
        "provenance": provenance_to_dict(result.provenance),
        "baseline_id": result.baseline_id,
        "status": result.status,
        "constraints": constraint_config_to_dict(result.constraints),
        "strategies_included": strategies,
        "strategies": {sid: simulation_result_to_dict(sim) for sid, sim in selected.items()},
        "candidates": frame_to_records(normalize_candidate_frame(result.candidates), CANDIDATE_COLUMNS, "candidates"),
        "pareto": frame_to_records(normalize_candidate_frame(result.pareto, "pareto"), CANDIDATE_COLUMNS, "pareto"),
        "diagnostics": to_jsonable(dict(result.diagnostics), "optimization.diagnostics"),
    }


def optimization_result_from_dict(data: Any) -> OptimizationResult:
    data = _require_mapping("optimization", data)
    _require_keys(
        "optimization",
        data,
        _RESULT_HEADER + ("baseline_id", "status", "constraints", "strategies", "candidates", "pareto", "diagnostics"),
    )
    validate_schema_version("optimization.schema_version", data["schema_version"])
    status = data["status"]
    if status not in OPTIMIZATION_STATUSES:
        raise ContractValidationError("optimization.status", f"must be one of {list(OPTIMIZATION_STATUSES)}; got {status!r}")
    strategies_data = _require_mapping("optimization.strategies", data["strategies"])
    strategies = {}
    for sid, payload in strategies_data.items():
        sim = simulation_result_from_dict(payload, f"optimization.strategies.{sid}")
        if sim.strategy_id != sid:
            raise ContractValidationError(f"optimization.strategies.{sid}", "key must equal its strategy_id")
        strategies[sid] = sim
    candidates = normalize_candidate_frame(frame_from_records("optimization.candidates", data["candidates"], CANDIDATE_COLUMNS))
    pareto = normalize_candidate_frame(frame_from_records("optimization.pareto", data["pareto"], CANDIDATE_COLUMNS), "pareto")
    diagnostics = _require_mapping("optimization.diagnostics", data["diagnostics"])
    return OptimizationResult(
        schema_version=data["schema_version"],
        run_id=require_str("optimization.run_id", data["run_id"]),
        provenance=provenance_from_dict(data["provenance"], "optimization.provenance"),
        status=status,
        baseline_id=require_str("optimization.baseline_id", data["baseline_id"]),
        constraints=constraint_config_from_dict(data["constraints"]),
        strategies=strategies,
        candidates=candidates,
        pareto=pareto,
        diagnostics=dict(diagnostics),
    )


# ---------------------------------------------------------------------------
# RiskResult and RecommendationResult
# ---------------------------------------------------------------------------


def risk_result_to_dict(result: RiskResult) -> dict[str, Any]:
    validate_risk_result(result)
    samples = None
    if result.samples is not None:
        samples = to_jsonable(result.samples.to_dict(orient="records"), "risk_result.samples")
    return {
        "schema_version": result.schema_version,
        "run_id": result.run_id,
        "provenance": provenance_to_dict(result.provenance),
        "baseline_id": result.baseline_id,
        "strategy_id": result.strategy_id,
        "n_simulations": result.n_simulations,
        "uncertainty_id": result.uncertainty_id,
        "summary": {name: getattr(result.summary, name) for name in RISK_SUMMARY_FIELDS},
        "samples": samples,
    }


def risk_result_from_dict(data: Any) -> RiskResult:
    data = _require_mapping("risk_result", data)
    _require_keys(
        "risk_result",
        data,
        _RESULT_HEADER + ("baseline_id", "strategy_id", "n_simulations", "uncertainty_id", "summary"),
    )
    validate_schema_version("risk_result.schema_version", data["schema_version"])
    summary = _require_mapping("risk_result.summary", data["summary"])
    _require_keys("risk_result.summary", summary, RISK_SUMMARY_FIELDS)
    samples = data.get("samples")
    if samples is not None:
        if not isinstance(samples, list):
            raise ContractValidationError("risk_result.samples", "must be an array of records or null")
        samples = pd.DataFrame(samples)
    result = RiskResult(
        schema_version=data["schema_version"],
        run_id=data["run_id"],
        provenance=provenance_from_dict(data["provenance"], "risk_result.provenance"),
        strategy_id=data["strategy_id"],
        baseline_id=data["baseline_id"],
        summary=RiskSummary(**{name: summary[name] for name in RISK_SUMMARY_FIELDS}),
        n_simulations=require_int("risk_result.n_simulations", data["n_simulations"], minimum=1),
        uncertainty_id=data["uncertainty_id"],
        samples=samples,
    )
    return validate_risk_result(result)


_RECOMMENDATION_FIELDS = ("strategy_id", "policy", "tolerance", "score", "risk_status", "reason")


def recommendation_to_dict(result: RecommendationResult) -> dict[str, Any]:
    return {
        "schema_version": result.schema_version,
        "run_id": result.run_id,
        "provenance": provenance_to_dict(result.provenance),
        **{name: getattr(result, name) for name in _RECOMMENDATION_FIELDS},
        "diagnostics": to_jsonable(dict(result.diagnostics), "recommendation.diagnostics"),
    }


def recommendation_from_dict(data: Any) -> RecommendationResult:
    data = _require_mapping("recommendation", data)
    _require_keys("recommendation", data, _RESULT_HEADER + _RECOMMENDATION_FIELDS)
    validate_schema_version("recommendation.schema_version", data["schema_version"])
    if data["tolerance"] not in RISK_TOLERANCES:
        raise ContractValidationError("recommendation.tolerance", f"must be one of {list(RISK_TOLERANCES)}")
    if data["risk_status"] not in RISK_STATUSES:
        raise ContractValidationError("recommendation.risk_status", f"must be one of {list(RISK_STATUSES)}")
    strategy_id = data["strategy_id"]
    if strategy_id is not None:
        require_str("recommendation.strategy_id", strategy_id)
    return RecommendationResult(
        schema_version=data["schema_version"],
        run_id=require_str("recommendation.run_id", data["run_id"]),
        provenance=provenance_from_dict(data["provenance"], "recommendation.provenance"),
        strategy_id=strategy_id,
        policy=require_str("recommendation.policy", data["policy"]),
        tolerance=data["tolerance"],
        score=_nullable_float("recommendation.score", data["score"]),
        risk_status=data["risk_status"],
        reason=require_str("recommendation.reason", data["reason"], allow_empty=True),
        diagnostics=dict(_require_mapping("recommendation.diagnostics", data.get("diagnostics", {}))),
    )


# ---------------------------------------------------------------------------
# Dispatch and fingerprints
# ---------------------------------------------------------------------------

_TO_DICT = (
    (BaselineBundle, baseline_to_dict),
    (SimulationResult, simulation_result_to_dict),
    (OptimizationResult, optimization_result_to_dict),
    (RecommendationResult, recommendation_to_dict),
    (RiskResult, risk_result_to_dict),
    (ConstraintEvaluation, constraint_evaluation_to_dict),
    (ActionAssumptions, action_assumptions_to_dict),
    (ActionConfig, action_config_to_dict),
    (ConstraintConfig, constraint_config_to_dict),
    (OptimizerConfig, optimizer_config_to_dict),
)


def to_dict(obj: Any) -> dict[str, Any]:
    for cls, convert in _TO_DICT:
        if isinstance(obj, cls):
            return convert(obj)
    raise ContractValidationError("value", f"no contract serializer for {type(obj).__name__}")


def to_json(obj: Any, *, indent: int | None = None) -> str:
    """Serialize a contract object to JSON text (NaN/Infinity rejected)."""
    return json.dumps(to_dict(obj), indent=indent, ensure_ascii=False, allow_nan=False)


def baseline_fingerprint(baseline: BaselineBundle) -> str:
    """SHA-256 over baseline metadata and the exact monthly values (provenance input hash)."""
    header = {
        name: getattr(baseline, name)
        for name in ("schema_version", "run_id", "baseline_id", "company_id", "horizon_months", "model_id",
                     "driver_policy_id", "data_kind", "scope2_method", "currency")
    }
    header["history_end"] = iso_date(baseline.history_end)
    header["provenance"] = provenance_to_dict(baseline.provenance)
    header["totals"] = {name: getattr(baseline.totals, name) for name in _TOTAL_FIELDS}
    digest = hashlib.sha256(canonical_json(header).encode("utf-8"))
    monthly = baseline.monthly
    digest.update(monthly["timestamp"].to_numpy(dtype="datetime64[ns]").astype("<i8").tobytes())
    numeric = [name for name, kind in BASELINE_MONTHLY_COLUMNS if kind in ("float", "int")]
    digest.update(np.ascontiguousarray(monthly[numeric].to_numpy(dtype="<f8")).tobytes())
    digest.update("\x1f".join(str(v) for v in monthly["company_id"].tolist()).encode("utf-8"))
    return digest.hexdigest()


def assumptions_fingerprint(assumptions: ActionAssumptions) -> str:
    return sha256_hex(canonical_json(action_assumptions_to_dict(assumptions)))


__all__ = [
    "action_assumptions_from_dict",
    "action_assumptions_to_dict",
    "action_config_from_dict",
    "action_config_to_dict",
    "assumptions_fingerprint",
    "baseline_fingerprint",
    "baseline_from_dict",
    "baseline_to_dict",
    "canonical_json",
    "constraint_config_from_dict",
    "constraint_config_to_dict",
    "constraint_evaluation_from_dict",
    "constraint_evaluation_to_dict",
    "empty_frame",
    "frame_from_records",
    "frame_to_records",
    "iso_date",
    "load_json",
    "optimization_result_from_dict",
    "optimization_result_to_dict",
    "optimizer_config_from_dict",
    "optimizer_config_to_dict",
    "parse_iso_date",
    "provenance_from_dict",
    "provenance_to_dict",
    "recommendation_from_dict",
    "recommendation_to_dict",
    "risk_result_from_dict",
    "risk_result_to_dict",
    "sha256_hex",
    "simulation_result_from_dict",
    "simulation_result_to_dict",
    "to_dict",
    "to_json",
    "to_jsonable",
]
