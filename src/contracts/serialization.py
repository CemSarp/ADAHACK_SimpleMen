"""JSON serialization for contract 1.0.0.

Dates serialize as ISO calendar dates, frames as record arrays, numbers as
built-in int/float, missing optional values as null. NaN/Infinity are rejected.
Decoders restore canonical dtypes (datetime64[ns], float64, int64, bool) and
retain documented additive columns/fields they do not know about.
"""

from __future__ import annotations

import json
import math
from dataclasses import fields, is_dataclass
from datetime import date, datetime
from typing import Any, Callable, Mapping

import numpy as np
import pandas as pd

from .errors import ContractValidationError
from .types import (
    ACTION_NAMES,
    BACKTEST_FOLD_COLUMNS,
    BACKTEST_OOF_COLUMNS,
    HISTORY_COLUMNS,
    HISTORY_INT_COLUMNS,
    OPTIMIZATION_TABLE_COLUMNS,
    RISK_SAMPLE_COLUMNS,
    SHAP_COLUMNS,
    SIMULATION_MONTHLY_COLUMNS,
    ActionAssumptions,
    ActionConfig,
    ActionCost,
    AnalysisBundle,
    AnalysisRequest,
    BacktestReport,
    BaselineBundle,
    BenchmarkResult,
    ConstraintConfig,
    ExplanationResult,
    OptimizationResult,
    OptimizerConfig,
    Provenance,
    ProviderInfo,
    RecommendationResult,
    RiskConfig,
    RiskResult,
    SimulationResult,
)
from .validation import validate_schema_version

# --------------------------------------------------------------------------- #
# Frame specifications: column -> kind
# --------------------------------------------------------------------------- #

FrameSpec = Mapping[str, str]

HISTORY_SPEC: FrameSpec = {
    c: ("str" if c == "company_id" else "date" if c == "timestamp" else "int" if c in HISTORY_INT_COLUMNS else "float")
    for c in HISTORY_COLUMNS
}
SIMULATION_MONTHLY_SPEC: FrameSpec = {c: ("date" if c == "timestamp" else "float") for c in SIMULATION_MONTHLY_COLUMNS}
OPTIMIZATION_TABLE_SPEC: FrameSpec = {
    "strategy_id": "str",
    **{name: "float" for name in ACTION_NAMES},
    "total_co2e_tco2e": "float",
    "total_profit_gbp": "float",
    "total_cost_gbp": "float",
    "co2_reduction_ratio": "nullable_float",
    "g_budget": "float",
    "g_profit": "float",
    "g_target": "float",
    "feasible": "bool",
    "pareto_rank": "int",
}
assert tuple(OPTIMIZATION_TABLE_SPEC) == OPTIMIZATION_TABLE_COLUMNS
BACKTEST_FOLD_SPEC: FrameSpec = {
    "fold_id": "raw",
    "train_cutoff": "date",
    "test_start": "date",
    "test_end": "date",
    "target": "str",
    "mae": "float",
    "rmse": "float",
    "r2": "nullable_float",
    "naive_mae": "float",
    "naive_rmse": "float",
    "effective_train_size": "int",
    "adjustment_count": "int",
}
assert tuple(BACKTEST_FOLD_SPEC) == BACKTEST_FOLD_COLUMNS
BACKTEST_OOF_SPEC: FrameSpec = {
    "fold_id": "raw",
    "timestamp": "date",
    "target": "str",
    "actual": "float",
    "predicted": "float",
    "naive_predicted": "float",
}
assert tuple(BACKTEST_OOF_SPEC) == BACKTEST_OOF_COLUMNS
SHAP_SPEC: FrameSpec = {
    "timestamp": "date",
    "target": "str",
    "feature": "str",
    "feature_value": "nullable_float",
    "shap_value": "float",
    "base_value": "float",
    "model_prediction": "float",
}
assert tuple(SHAP_SPEC) == SHAP_COLUMNS
RISK_SAMPLE_SPEC: FrameSpec = {
    "trial_id": "int",
    "total_co2e_tco2e": "float",
    "total_profit_gbp": "float",
    "total_cost_gbp": "float",
    "target_met": "bool",
    "profit_met": "bool",
    "budget_met": "bool",
}
assert tuple(RISK_SAMPLE_SPEC) == RISK_SAMPLE_COLUMNS

_DTYPES = {"float": "float64", "nullable_float": "float64", "int": "int64", "bool": "bool", "date": "datetime64[ns]"}


def empty_frame(spec: FrameSpec) -> pd.DataFrame:
    """Empty frame that keeps canonical columns and dtypes."""
    return pd.DataFrame({c: pd.Series([], dtype=_DTYPES.get(kind, "object")) for c, kind in spec.items()})


def _plain(value: Any) -> Any:
    """Convert a scalar to a JSON-safe built-in value."""
    if value is None:
        return None
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if isinstance(value, (int, np.integer)):
        return int(value)
    if isinstance(value, (float, np.floating)):
        v = float(value)
        if math.isnan(v):
            return None
        if math.isinf(v):
            raise ContractValidationError("json", "Infinity is not permitted in JSON")
        return v
    if isinstance(value, pd.Timestamp):
        if pd.isna(value):
            return None
        return value.date().isoformat()
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if value is pd.NaT:
        return None
    return value


def frame_to_records(frame: pd.DataFrame | None) -> list[dict[str, Any]] | None:
    if frame is None:
        return None
    columns = list(frame.columns)
    return [{c: _plain(v) for c, v in zip(columns, row)} for row in frame.itertuples(index=False, name=None)]


def frame_from_records(records: list[Mapping[str, Any]] | None, spec: FrameSpec, field: str) -> pd.DataFrame:
    if records is None:
        raise ContractValidationError(field, "is required")
    if not isinstance(records, list):
        raise ContractValidationError(field, "must be a JSON record array")
    if len(records) == 0:
        return empty_frame(spec)
    extra = [c for c in records[0] if c not in spec]
    frame = pd.DataFrame.from_records(records, columns=[*spec, *extra])
    for col, kind in spec.items():
        if frame[col].isna().any() and kind not in ("nullable_float", "raw"):
            raise ContractValidationError(f"{field}.{col}", "contains null values")
        try:
            if kind == "date":
                frame[col] = pd.to_datetime(frame[col], format="%Y-%m-%d").astype("datetime64[ns]")
            elif kind in ("float", "nullable_float"):
                if frame[col].map(lambda v: isinstance(v, bool)).any():
                    raise ValueError("booleans are not numbers")
                frame[col] = frame[col].astype("float64")
            elif kind == "int":
                values = frame[col].astype("float64")
                if not np.all(np.mod(values, 1) == 0):
                    raise ValueError("expected integer values")
                frame[col] = values.astype("int64")
            elif kind == "bool":
                if not frame[col].map(lambda v: isinstance(v, bool)).all():
                    raise ValueError("expected JSON booleans")
                frame[col] = frame[col].astype("bool")
            elif kind == "str":
                frame[col] = frame[col].astype(str)
        except (TypeError, ValueError) as exc:
            raise ContractValidationError(f"{field}.{col}", f"cannot convert to {kind}: {exc}") from exc
    return frame


# --------------------------------------------------------------------------- #
# Small dataclass helpers
# --------------------------------------------------------------------------- #


def _simple_to_dict(obj: Any) -> dict[str, Any]:
    return {f.name: _plain(getattr(obj, f.name)) for f in fields(obj)}


def _require(data: Mapping[str, Any], key: str, field: str) -> Any:
    if not isinstance(data, Mapping):
        raise ContractValidationError(field, "must be a JSON object")
    if key not in data:
        raise ContractValidationError(f"{field}.{key}", "is required")
    return data[key]


def provenance_to_dict(p: Provenance) -> dict[str, Any]:
    return _simple_to_dict(p)


def provenance_from_dict(data: Mapping[str, Any], field: str = "provenance") -> Provenance:
    keys = ("provider", "is_mock", "seed", "input_hash", "config_id", "assumptions_id")
    return Provenance(**{k: _require(data, k, field) for k in keys})


def _common_to_dict(obj: Any) -> dict[str, Any]:
    return {"schema_version": obj.schema_version, "run_id": obj.run_id, "provenance": provenance_to_dict(obj.provenance)}


def _common_from_dict(data: Mapping[str, Any], field: str) -> dict[str, Any]:
    version = validate_schema_version(_require(data, "schema_version", field), f"{field}.schema_version")
    return {
        "schema_version": version,
        "run_id": _require(data, "run_id", field),
        "provenance": provenance_from_dict(_require(data, "provenance", field), f"{field}.provenance"),
    }


def action_config_to_dict(c: ActionConfig) -> dict[str, float]:
    return c.as_dict()


def action_config_from_dict(data: Mapping[str, Any], field: str = "config") -> ActionConfig:
    values = {}
    for name in ACTION_NAMES:
        v = _require(data, name, field)
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise ContractValidationError(f"{field}.{name}", "must be a number")
        values[name] = float(v)
    unknown = set(data) - set(ACTION_NAMES)
    if unknown:
        raise ContractValidationError(field, f"unknown action fields {sorted(unknown)}")
    return ActionConfig(**values)


def constraints_from_dict(data: Mapping[str, Any], field: str = "constraints") -> ConstraintConfig:
    return ConstraintConfig(
        budget_gbp=float(_require(data, "budget_gbp", field)),
        min_total_profit_gbp=float(_require(data, "min_total_profit_gbp", field)),
        min_co2_reduction_ratio=float(_require(data, "min_co2_reduction_ratio", field)),
    )


def assumptions_to_dict(a: ActionAssumptions) -> dict[str, Any]:
    out = {f.name: _plain(getattr(a, f.name)) for f in fields(a) if f.name != "costs"}
    out["costs"] = {name: _simple_to_dict(a.costs[name]) for name in ACTION_NAMES if name in a.costs}
    return out


_ASSUMPTION_FIELDS = tuple(f.name for f in fields(ActionAssumptions))
_COST_FIELDS = ("capex_at_full_gbp", "monthly_opex_at_full_gbp", "asset_life_months")


def _number(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ContractValidationError(field, f"must be a number, got {type(value).__name__}")
    return float(value)


def _whole_months(value: Any, field: str) -> int:
    number = _number(value, field)
    if not number.is_integer():
        raise ContractValidationError(field, f"must be a whole number of months, got {value!r}")
    return int(number)


def _reject_unknown(data: Mapping[str, Any], allowed: tuple[str, ...], field: str) -> None:
    # Versioned config files are strict: a misspelled field must not be ignored.
    unknown = sorted(set(data) - set(allowed))
    if unknown:
        raise ContractValidationError(field, f"unknown fields {unknown}")


def assumptions_from_dict(data: Mapping[str, Any], field: str = "assumptions") -> ActionAssumptions:
    if not isinstance(data, Mapping):
        raise ContractValidationError(field, "must be a JSON object")
    _reject_unknown(data, _ASSUMPTION_FIELDS, field)
    kwargs: dict[str, Any] = {}
    for f in fields(ActionAssumptions):
        if f.name == "costs":
            continue
        value = _require(data, f.name, field)
        if f.name in ("assumptions_id", "version", "description", "is_calibrated"):
            kwargs[f.name] = value
        else:
            kwargs[f.name] = _number(value, f"{field}.{f.name}")
    costs_raw = _require(data, "costs", field)
    if not isinstance(costs_raw, Mapping):
        raise ContractValidationError(f"{field}.costs", "must be a JSON object keyed by action")
    _reject_unknown(costs_raw, ACTION_NAMES, f"{field}.costs")
    costs = {}
    for name, c in costs_raw.items():
        path = f"{field}.costs.{name}"
        if not isinstance(c, Mapping):
            raise ContractValidationError(path, "must be a JSON object")
        _reject_unknown(c, _COST_FIELDS, path)
        costs[name] = ActionCost(
            capex_at_full_gbp=_number(_require(c, "capex_at_full_gbp", path), f"{path}.capex_at_full_gbp"),
            monthly_opex_at_full_gbp=_number(_require(c, "monthly_opex_at_full_gbp", path), f"{path}.monthly_opex_at_full_gbp"),
            asset_life_months=_whole_months(_require(c, "asset_life_months", path), f"{path}.asset_life_months"),
        )
    kwargs["costs"] = costs
    return ActionAssumptions(**kwargs)


# --------------------------------------------------------------------------- #
# Domain results
# --------------------------------------------------------------------------- #


def baseline_to_dict(b: BaselineBundle) -> dict[str, Any]:
    return {
        **_common_to_dict(b),
        "baseline_id": b.baseline_id,
        "company_id": b.company_id,
        "history_end": b.history_end.isoformat(),
        "horizon_months": int(b.horizon_months),
        "model_id": b.model_id,
        "driver_policy_id": b.driver_policy_id,
        "data_kind": b.data_kind,
        "scope2_method": b.scope2_method,
        "currency": b.currency,
        "monthly": frame_to_records(b.monthly[list(HISTORY_COLUMNS)]),
        "totals": {k: _plain(v) for k, v in b.totals.items()},
    }


def baseline_from_dict(data: Mapping[str, Any]) -> BaselineBundle:
    f = "baseline"
    return BaselineBundle(
        **_common_from_dict(data, f),
        baseline_id=_require(data, "baseline_id", f),
        company_id=_require(data, "company_id", f),
        history_end=date.fromisoformat(_require(data, "history_end", f)),
        horizon_months=int(_require(data, "horizon_months", f)),
        model_id=_require(data, "model_id", f),
        driver_policy_id=_require(data, "driver_policy_id", f),
        data_kind=_require(data, "data_kind", f),
        scope2_method=_require(data, "scope2_method", f),
        currency=_require(data, "currency", f),
        monthly=frame_from_records(_require(data, "monthly", f), HISTORY_SPEC, f"{f}.monthly"),
        totals={k: float(v) for k, v in _require(data, "totals", f).items()},
    )


def history_from_records(records: list[Mapping[str, Any]]) -> pd.DataFrame:
    return frame_from_records(records, HISTORY_SPEC, "history")


def _metrics_from(data: Mapping[str, Any]) -> dict[str, float | None]:
    return {k: (None if v is None else float(v)) for k, v in data.items()}


def simulation_to_dict(r: SimulationResult) -> dict[str, Any]:
    return {
        **_common_to_dict(r),
        "baseline_id": r.baseline_id,
        "strategy_id": r.strategy_id,
        "config": action_config_to_dict(r.config),
        "monthly": frame_to_records(r.monthly),
        "metrics": {k: _plain(v) for k, v in r.metrics.items()},
    }


def simulation_from_dict(data: Mapping[str, Any], field: str = "simulation") -> SimulationResult:
    return SimulationResult(
        **_common_from_dict(data, field),
        baseline_id=_require(data, "baseline_id", field),
        strategy_id=_require(data, "strategy_id", field),
        config=action_config_from_dict(_require(data, "config", field), f"{field}.config"),
        monthly=frame_from_records(_require(data, "monthly", field), SIMULATION_MONTHLY_SPEC, f"{field}.monthly"),
        metrics=_metrics_from(_require(data, "metrics", field)),
    )


def optimization_to_dict(r: OptimizationResult) -> dict[str, Any]:
    return {
        **_common_to_dict(r),
        "baseline_id": r.baseline_id,
        "status": r.status,
        "constraints": _simple_to_dict(r.constraints),
        "strategies": {sid: simulation_to_dict(s) for sid, s in r.strategies.items()},
        "candidates": frame_to_records(r.candidates),
        "pareto": frame_to_records(r.pareto),
        "diagnostics": _json_safe(r.diagnostics),
    }


def optimization_from_dict(data: Mapping[str, Any]) -> OptimizationResult:
    f = "optimization"
    return OptimizationResult(
        **_common_from_dict(data, f),
        baseline_id=_require(data, "baseline_id", f),
        status=_require(data, "status", f),
        constraints=constraints_from_dict(_require(data, "constraints", f), f"{f}.constraints"),
        strategies={
            sid: simulation_from_dict(s, f"{f}.strategies[{sid}]") for sid, s in _require(data, "strategies", f).items()
        },
        candidates=frame_from_records(_require(data, "candidates", f), OPTIMIZATION_TABLE_SPEC, f"{f}.candidates"),
        pareto=frame_from_records(_require(data, "pareto", f), OPTIMIZATION_TABLE_SPEC, f"{f}.pareto"),
        diagnostics=dict(_require(data, "diagnostics", f)),
    )


def recommendation_to_dict(r: RecommendationResult) -> dict[str, Any]:
    out = _common_to_dict(r)
    out.update({k: _plain(getattr(r, k)) for k in ("strategy_id", "policy", "tolerance", "score", "risk_status", "reason")})
    out["diagnostics"] = _json_safe(r.diagnostics)
    return out


def recommendation_from_dict(data: Mapping[str, Any]) -> RecommendationResult:
    f = "recommendation"
    score = _require(data, "score", f)
    return RecommendationResult(
        **_common_from_dict(data, f),
        strategy_id=_require(data, "strategy_id", f),
        policy=_require(data, "policy", f),
        tolerance=_require(data, "tolerance", f),
        score=None if score is None else float(score),
        risk_status=_require(data, "risk_status", f),
        reason=_require(data, "reason", f),
        diagnostics=dict(data.get("diagnostics") or {}),  # additive optional field
    )


def risk_to_dict(r: RiskResult) -> dict[str, Any]:
    return {
        **_common_to_dict(r),
        "baseline_id": r.baseline_id,
        "strategy_id": r.strategy_id,
        "n_simulations": int(r.n_simulations),
        "uncertainty_id": r.uncertainty_id,
        "summary": {k: _plain(v) for k, v in r.summary.items()},
        "samples": frame_to_records(r.samples),
    }


def risk_from_dict(data: Mapping[str, Any]) -> RiskResult:
    f = "risk"
    samples = data.get("samples")
    return RiskResult(
        **_common_from_dict(data, f),
        baseline_id=_require(data, "baseline_id", f),
        strategy_id=_require(data, "strategy_id", f),
        n_simulations=int(_require(data, "n_simulations", f)),
        uncertainty_id=_require(data, "uncertainty_id", f),
        summary=_metrics_from(_require(data, "summary", f)),
        samples=None if samples is None else frame_from_records(samples, RISK_SAMPLE_SPEC, f"{f}.samples"),
    )


_BENCHMARK_FIELDS = tuple(f.name for f in fields(BenchmarkResult) if f.name not in ("schema_version", "run_id", "provenance"))


def benchmark_to_dict(b: BenchmarkResult) -> dict[str, Any]:
    out = _common_to_dict(b)
    out.update({k: _plain(getattr(b, k)) for k in _BENCHMARK_FIELDS})
    return out


def benchmark_from_dict(data: Mapping[str, Any]) -> BenchmarkResult:
    f = "benchmark"
    values = {k: _require(data, k, f) for k in _BENCHMARK_FIELDS}
    for k in ("company_intensity_tco2e_per_million_gbp", "industry_median", "percentile", "better_than_pct"):
        values[k] = None if values[k] is None else float(values[k])
    values["peer_count"] = int(values["peer_count"])
    return BenchmarkResult(**_common_from_dict(data, f), **values)


def backtest_to_dict(r: BacktestReport) -> dict[str, Any]:
    return {
        **_common_to_dict(r),
        "model_family": r.model_family,
        "feature_spec_id": r.feature_spec_id,
        "driver_policy_id": r.driver_policy_id,
        "selected_models": dict(r.selected_models),
        "folds": frame_to_records(r.folds),
        "aggregate_metrics": {t: {k: _plain(v) for k, v in m.items()} for t, m in r.aggregate_metrics.items()},
        "oof_predictions": frame_to_records(r.oof_predictions),
    }


def backtest_from_dict(data: Mapping[str, Any]) -> BacktestReport:
    f = "backtest"
    return BacktestReport(
        **_common_from_dict(data, f),
        model_family=_require(data, "model_family", f),
        feature_spec_id=_require(data, "feature_spec_id", f),
        driver_policy_id=_require(data, "driver_policy_id", f),
        selected_models=dict(data.get("selected_models") or {}),
        folds=frame_from_records(_require(data, "folds", f), BACKTEST_FOLD_SPEC, f"{f}.folds"),
        aggregate_metrics={t: _metrics_from(m) for t, m in _require(data, "aggregate_metrics", f).items()},
        oof_predictions=frame_from_records(_require(data, "oof_predictions", f), BACKTEST_OOF_SPEC, f"{f}.oof_predictions"),
    )


def explanation_to_dict(e: ExplanationResult) -> dict[str, Any]:
    return {
        **_common_to_dict(e),
        "model_id": e.model_id,
        "baseline_id": e.baseline_id,
        "driver_policy_id": e.driver_policy_id,
        "output_space": e.output_space,
        "units": dict(e.units),
        "explained_rows": int(e.explained_rows),
        "contributions": frame_to_records(e.contributions),
    }


def explanation_from_dict(data: Mapping[str, Any]) -> ExplanationResult:
    f = "explanation"
    return ExplanationResult(
        **_common_from_dict(data, f),
        model_id=_require(data, "model_id", f),
        baseline_id=_require(data, "baseline_id", f),
        driver_policy_id=_require(data, "driver_policy_id", f),
        output_space=_require(data, "output_space", f),
        units=dict(_require(data, "units", f)),
        explained_rows=int(_require(data, "explained_rows", f)),
        contributions=frame_from_records(_require(data, "contributions", f), SHAP_SPEC, f"{f}.contributions"),
    )


def request_to_dict(r: AnalysisRequest) -> dict[str, Any]:
    return {
        "company_id": r.company_id,
        "horizon_months": r.horizon_months,
        "constraints": _simple_to_dict(r.constraints),
        "optimizer_config": _simple_to_dict(r.optimizer_config),
        "risk_enabled": r.risk_enabled,
        "risk_config": _simple_to_dict(r.risk_config),
        "tolerance": r.tolerance,
        "benchmark_enabled": r.benchmark_enabled,
        "explanation_enabled": r.explanation_enabled,
    }


def request_from_dict(data: Mapping[str, Any]) -> AnalysisRequest:
    f = "request"
    return AnalysisRequest(
        company_id=_require(data, "company_id", f),
        horizon_months=int(_require(data, "horizon_months", f)),
        constraints=constraints_from_dict(_require(data, "constraints", f)),
        optimizer_config=OptimizerConfig(**_require(data, "optimizer_config", f)),
        risk_enabled=bool(_require(data, "risk_enabled", f)),
        risk_config=RiskConfig(**_require(data, "risk_config", f)),
        tolerance=_require(data, "tolerance", f),
        benchmark_enabled=bool(_require(data, "benchmark_enabled", f)),
        explanation_enabled=bool(_require(data, "explanation_enabled", f)),
    )


def analysis_to_dict(a: AnalysisBundle) -> dict[str, Any]:
    return {
        **_common_to_dict(a),
        "request": None if a.request is None else request_to_dict(a.request),
        "providers": {slot: _simple_to_dict(info) for slot, info in a.providers.items()},
        "baseline": baseline_to_dict(a.baseline),
        "backtest": None if a.backtest is None else backtest_to_dict(a.backtest),
        "optimization": optimization_to_dict(a.optimization),
        "recommendation": recommendation_to_dict(a.recommendation),
        "risk_results": {sid: risk_to_dict(r) for sid, r in a.risk_results.items()},
        "explanation": None if a.explanation is None else explanation_to_dict(a.explanation),
        "benchmark": None if a.benchmark is None else benchmark_to_dict(a.benchmark),
        "warnings": list(a.warnings),
    }


def analysis_from_dict(data: Mapping[str, Any]) -> AnalysisBundle:
    f = "analysis"
    req = data.get("request")
    return AnalysisBundle(
        **_common_from_dict(data, f),
        request=None if req is None else request_from_dict(req),
        providers={slot: ProviderInfo(**info) for slot, info in (data.get("providers") or {}).items()},
        baseline=baseline_from_dict(_require(data, "baseline", f)),
        backtest=None if data.get("backtest") is None else backtest_from_dict(data["backtest"]),
        optimization=optimization_from_dict(_require(data, "optimization", f)),
        recommendation=recommendation_from_dict(_require(data, "recommendation", f)),
        risk_results={sid: risk_from_dict(r) for sid, r in (data.get("risk_results") or {}).items()},
        explanation=None if data.get("explanation") is None else explanation_from_dict(data["explanation"]),
        benchmark=None if data.get("benchmark") is None else benchmark_from_dict(data["benchmark"]),
        warnings=tuple(_require(data, "warnings", f)),
    )


def _json_safe(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if is_dataclass(value) and not isinstance(value, type):
        return _simple_to_dict(value)
    return _plain(value)


# --------------------------------------------------------------------------- #
# Generic entry points
# --------------------------------------------------------------------------- #

_ENCODERS: dict[type, Callable[[Any], dict[str, Any]]] = {
    BaselineBundle: baseline_to_dict,
    SimulationResult: simulation_to_dict,
    OptimizationResult: optimization_to_dict,
    RecommendationResult: recommendation_to_dict,
    RiskResult: risk_to_dict,
    BenchmarkResult: benchmark_to_dict,
    BacktestReport: backtest_to_dict,
    ExplanationResult: explanation_to_dict,
    AnalysisBundle: analysis_to_dict,
    AnalysisRequest: request_to_dict,
    ActionAssumptions: assumptions_to_dict,
    ActionConfig: action_config_to_dict,
    ConstraintConfig: _simple_to_dict,
}
_DECODERS: dict[type, Callable[[Mapping[str, Any]], Any]] = {
    BaselineBundle: baseline_from_dict,
    SimulationResult: simulation_from_dict,
    OptimizationResult: optimization_from_dict,
    RecommendationResult: recommendation_from_dict,
    RiskResult: risk_from_dict,
    BenchmarkResult: benchmark_from_dict,
    BacktestReport: backtest_from_dict,
    ExplanationResult: explanation_from_dict,
    AnalysisBundle: analysis_from_dict,
    AnalysisRequest: request_from_dict,
    ActionAssumptions: assumptions_from_dict,
    ActionConfig: action_config_from_dict,
    ConstraintConfig: constraints_from_dict,
}


def to_dict(obj: Any) -> dict[str, Any]:
    try:
        encoder = _ENCODERS[type(obj)]
    except KeyError:
        raise TypeError(f"no contract encoder for {type(obj).__name__}") from None
    return encoder(obj)


def from_dict(cls: type, data: Mapping[str, Any]) -> Any:
    try:
        decoder = _DECODERS[cls]
    except KeyError:
        raise TypeError(f"no contract decoder for {cls.__name__}") from None
    return decoder(data)


def to_json(obj: Any, *, indent: int | None = None) -> str:
    try:
        return json.dumps(to_dict(obj), allow_nan=False, indent=indent)
    except ValueError as exc:
        raise ContractValidationError("json", str(exc)) from exc


def _reject_constant(token: str) -> Any:
    raise ContractValidationError("json", f"{token} is not permitted in JSON")


def from_json(cls: type, text: str) -> Any:
    try:
        data = json.loads(text, parse_constant=_reject_constant)
    except json.JSONDecodeError as exc:
        raise ContractValidationError("json", f"malformed JSON: {exc}") from exc
    return from_dict(cls, data)
