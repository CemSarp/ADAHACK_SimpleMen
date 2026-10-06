"""Contract validators (version 1.0.0).

Every validator raises ContractValidationError(field, reason) and returns the
validated object unchanged, so it can be used inline. Validators check shape,
units, ranges and documented identities; they never recompute domain outcomes
such as emissions, feasibility or Pareto ranking.
"""

from __future__ import annotations

import math
from datetime import date
from typing import Any, Iterable, Mapping

import numpy as np
import pandas as pd

from .errors import ContractValidationError, UnsupportedHorizon
from .identity import STRATEGY_ID_PREFIX
from .types import (
    ACTION_NAMES,
    ASSUMPTION_SCALAR_FIELDS,
    BACKTEST_FOLD_COLUMNS,
    BACKTEST_OOF_COLUMNS,
    BENCHMARK_STATUSES,
    FORECAST_TARGETS,
    HISTORY_COLUMNS,
    HISTORY_FLOAT_COLUMNS,
    HISTORY_INT_COLUMNS,
    NULLABLE_METRIC_FIELDS,
    OPTIMIZATION_STATUSES,
    OPTIMIZATION_TABLE_COLUMNS,
    RISK_STATUSES,
    RISK_SUMMARY_FIELDS,
    SCOPE_COLUMNS,
    SHAP_COLUMNS,
    SIMULATION_METRIC_FIELDS,
    SIMULATION_MONTHLY_COLUMNS,
    SUPPORTED_SCHEMA_MAJOR,
    TOLERANCES,
    ActionAssumptions,
    ActionConfig,
    AnalysisRequest,
    BacktestReport,
    BaselineBundle,
    BenchmarkResult,
    ConstraintConfig,
    ExplanationResult,
    OptimizationResult,
    OptimizerConfig,
    Provenance,
    RecommendationResult,
    RiskConfig,
    RiskResult,
    SimulationResult,
)

# Numerical tolerances (DATA_SCHEMAS.md section 1, ACTION_MODEL.md section 5).
SCOPE_RTOL = 1e-8
SCOPE_ATOL_TCO2E = 1e-6
CURRENCY_ATOL_GBP = 0.01
RATIO_ATOL = 1e-8
SOLVER_FEASIBILITY_TOL = 1e-8
ALLOWED_HORIZONS: tuple[int, ...] = (12, 36, 60)
MAX_RISK_SIMULATIONS = 5000


def _fail(field: str, reason: str) -> None:
    raise ContractValidationError(field, reason)


def _is_real_number(value: Any) -> bool:
    return isinstance(value, (int, float, np.integer, np.floating)) and not isinstance(
        value, (bool, np.bool_)
    )


def require_finite(field: str, value: Any) -> float:
    if not _is_real_number(value):
        _fail(field, f"expected a number, got {type(value).__name__}")
    if not math.isfinite(float(value)):
        _fail(field, "must be finite")
    return float(value)


def require_ratio(field: str, value: Any) -> float:
    v = require_finite(field, value)
    if not 0.0 <= v <= 1.0:
        hint = " (0-100 percentages are not accepted; use a 0-1 ratio)" if 1.0 < v <= 100.0 else ""
        _fail(field, f"must be within [0, 1], got {v!r}{hint}")
    return v


def require_nonempty_str(field: str, value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        _fail(field, "must be a nonempty string")
    return value


def require_positive_int(field: str, value: Any) -> int:
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, (int, np.integer)):
        _fail(field, f"expected a positive integer, got {type(value).__name__}")
    if int(value) <= 0:
        _fail(field, "must be a positive integer")
    return int(value)


def validate_schema_version(version: Any, field: str = "schema_version") -> str:
    require_nonempty_str(field, version)
    parts = version.split(".")
    if len(parts) != 3 or not all(p.isdigit() for p in parts):
        _fail(field, f"must be MAJOR.MINOR.PATCH, got {version!r}")
    if int(parts[0]) != SUPPORTED_SCHEMA_MAJOR:
        _fail(field, f"unsupported major version {version!r}; supported major is {SUPPORTED_SCHEMA_MAJOR}")
    return version


def validate_provenance(p: Provenance, field: str = "provenance") -> Provenance:
    if not isinstance(p, Provenance):
        _fail(field, "must be a Provenance object")
    require_nonempty_str(f"{field}.provider", p.provider)
    if not isinstance(p.is_mock, bool):
        _fail(f"{field}.is_mock", "must be a bool")
    if p.seed is not None and (isinstance(p.seed, bool) or not isinstance(p.seed, int)):
        _fail(f"{field}.seed", "must be an int or null")
    require_nonempty_str(f"{field}.input_hash", p.input_hash)
    require_nonempty_str(f"{field}.config_id", p.config_id)
    if p.assumptions_id is not None:
        require_nonempty_str(f"{field}.assumptions_id", p.assumptions_id)
    return p


def _validate_common(obj: Any, name: str) -> None:
    validate_schema_version(obj.schema_version, f"{name}.schema_version")
    require_nonempty_str(f"{name}.run_id", obj.run_id)
    validate_provenance(obj.provenance, f"{name}.provenance")


def _require_columns(frame: Any, required: Iterable[str], field: str) -> pd.DataFrame:
    if not isinstance(frame, pd.DataFrame):
        _fail(field, "must be a pandas DataFrame")
    missing = [c for c in required if c not in frame.columns]
    if missing:
        _fail(field, f"missing required columns {missing}")
    return frame


def _require_finite_columns(frame: pd.DataFrame, columns: Iterable[str], field: str) -> None:
    for col in columns:
        series = frame[col]
        if not pd.api.types.is_numeric_dtype(series) or pd.api.types.is_bool_dtype(series):
            _fail(f"{field}.{col}", f"must be numeric, got dtype {series.dtype}")
        values = series.to_numpy(dtype="float64")
        if not np.all(np.isfinite(values)):
            _fail(f"{field}.{col}", "contains missing or non-finite values")


def _require_monthly_dates(frame: pd.DataFrame, field: str) -> pd.Series:
    ts = frame["timestamp"]
    if not pd.api.types.is_datetime64_dtype(ts):
        _fail(f"{field}.timestamp", f"must be timezone-naive datetime64, got {ts.dtype}")
    if ts.isna().any():
        _fail(f"{field}.timestamp", "contains missing dates")
    if not (ts.dt.day == 1).all() or not (ts.dt.normalize() == ts).all():
        _fail(f"{field}.timestamp", "must be calendar month starts (YYYY-MM-01)")
    if ts.duplicated().any():
        _fail(f"{field}.timestamp", "contains duplicate months")
    if len(ts) > 1:
        periods = ts.dt.year * 12 + ts.dt.month
        if not (periods.diff().iloc[1:] == 1).all():
            _fail(f"{field}.timestamp", "months must be unique, ascending and contiguous")
    return ts


def validate_history_frame(frame: pd.DataFrame, field: str = "history") -> pd.DataFrame:
    """Company history / baseline monthly schema (DATA_SCHEMAS.md section 2)."""
    _require_columns(frame, HISTORY_COLUMNS, field)
    if len(frame) == 0:
        _fail(field, "must contain at least one month")
    companies = frame["company_id"].dropna().unique()
    if frame["company_id"].isna().any() or len(companies) != 1:
        _fail(f"{field}.company_id", "must contain exactly one nonempty company ID")
    require_nonempty_str(f"{field}.company_id", str(companies[0]))
    _require_monthly_dates(frame, field)
    _require_finite_columns(frame, HISTORY_FLOAT_COLUMNS + HISTORY_INT_COLUMNS, field)
    for col in HISTORY_INT_COLUMNS:
        if not pd.api.types.is_integer_dtype(frame[col]):
            _fail(f"{field}.{col}", f"must be an integer count, got dtype {frame[col].dtype}")
    if (frame["revenue_gbp"] <= 0).any():
        _fail(f"{field}.revenue_gbp", "must be > 0")
    nonneg = [
        "employees", "electricity_kwh", "gas_kwh", "fleet_size", "fleet_km",
        "business_travel_km", "cloud_compute_hours", *SCOPE_COLUMNS, "total_co2e_tco2e",
    ]
    for col in nonneg:
        if (frame[col] < 0).any():
            _fail(f"{field}.{col}", "must be >= 0")
    for col in ("renewable_energy_share", "ev_share"):
        if ((frame[col] < 0) | (frame[col] > 1)).any():
            _fail(f"{field}.{col}", "must be a ratio within [0, 1] (not a 0-100 percentage)")
    scope_sum = frame[list(SCOPE_COLUMNS)].sum(axis=1).to_numpy()
    if not np.allclose(scope_sum, frame["total_co2e_tco2e"].to_numpy(), rtol=SCOPE_RTOL, atol=SCOPE_ATOL_TCO2E):
        _fail(f"{field}.total_co2e_tco2e", "must equal scope1 + scope2 + scope3 within tolerance")
    return frame


def validate_horizon(horizon_months: Any, supported: tuple[int, ...] | None = None) -> int:
    h = require_positive_int("horizon_months", horizon_months)
    if h not in ALLOWED_HORIZONS:
        _fail("horizon_months", f"must be one of {list(ALLOWED_HORIZONS)}")
    if supported is not None and h not in supported:
        raise UnsupportedHorizon(h, supported)
    return h


def _months_after(d: date, n: int) -> date:
    idx = d.year * 12 + (d.month - 1) + n
    return date(idx // 12, idx % 12 + 1, 1)


def validate_baseline(b: BaselineBundle) -> BaselineBundle:
    if not isinstance(b, BaselineBundle):
        _fail("baseline", "must be a BaselineBundle")
    _validate_common(b, "baseline")
    require_nonempty_str("baseline.baseline_id", b.baseline_id)
    require_nonempty_str("baseline.company_id", b.company_id)
    validate_horizon(b.horizon_months)
    require_nonempty_str("baseline.model_id", b.model_id)
    require_nonempty_str("baseline.driver_policy_id", b.driver_policy_id)
    if b.data_kind not in ("synthetic", "reported", "interpolated"):
        _fail("baseline.data_kind", "must be synthetic, reported or interpolated")
    if b.currency != "GBP":
        _fail("baseline.currency", "must be GBP")
    if not isinstance(b.history_end, date) or b.history_end.day != 1:
        _fail("baseline.history_end", "must be a month-start date")
    monthly = validate_history_frame(b.monthly, "baseline.monthly")
    if len(monthly) != b.horizon_months:
        _fail("baseline.monthly", f"must have exactly {b.horizon_months} rows, got {len(monthly)}")
    if (monthly["company_id"] != b.company_id).any():
        _fail("baseline.monthly.company_id", "must match baseline.company_id")
    first = monthly["timestamp"].iloc[0].date()
    if first != _months_after(b.history_end, 1):
        _fail("baseline.monthly.timestamp", "must start one month after history_end")
    for key, col in (
        ("revenue_gbp", "revenue_gbp"),
        ("operating_profit_gbp", "operating_profit_gbp"),
        ("total_co2e_tco2e", "total_co2e_tco2e"),
    ):
        if key not in b.totals:
            _fail(f"baseline.totals.{key}", "is required")
        total = require_finite(f"baseline.totals.{key}", b.totals[key])
        atol = SCOPE_ATOL_TCO2E if key.endswith("tco2e") else CURRENCY_ATOL_GBP
        if not math.isclose(total, float(monthly[col].sum()), rel_tol=SCOPE_RTOL, abs_tol=atol):
            _fail(f"baseline.totals.{key}", "must equal the sum of monthly values")
    return b


def validate_action_config(config: ActionConfig, field: str = "config") -> ActionConfig:
    if not isinstance(config, ActionConfig):
        _fail(field, "must be an ActionConfig")
    for name in ACTION_NAMES:
        require_ratio(f"{field}.{name}", getattr(config, name))
    return config


def validate_constraints(c: ConstraintConfig) -> ConstraintConfig:
    if not isinstance(c, ConstraintConfig):
        _fail("constraints", "must be a ConstraintConfig")
    if require_finite("constraints.budget_gbp", c.budget_gbp) < 0:
        _fail("constraints.budget_gbp", "must be >= 0")
    require_finite("constraints.min_total_profit_gbp", c.min_total_profit_gbp)
    require_ratio("constraints.min_co2_reduction_ratio", c.min_co2_reduction_ratio)
    return c


def validate_constraints_for_baseline(c: ConstraintConfig, baseline: BaselineBundle) -> ConstraintConfig:
    """Zero baseline CO2 with a positive ratio target is undefined (SHARED_CONTRACTS.md s4)."""
    validate_constraints(c)
    if float(baseline.totals["total_co2e_tco2e"]) == 0.0 and c.min_co2_reduction_ratio > 0:
        _fail(
            "constraints.min_co2_reduction_ratio",
            "ratio target is undefined because baseline horizon CO2 is zero",
        )
    return c


def validate_optimizer_config(c: OptimizerConfig) -> OptimizerConfig:
    if not isinstance(c, OptimizerConfig):
        _fail("optimizer_config", "must be an OptimizerConfig")
    if isinstance(c.seed, bool) or not isinstance(c.seed, (int, np.integer)):
        _fail("optimizer_config.seed", "must be an int")
    if c.seed < 0:
        _fail("optimizer_config.seed", "must be >= 0 (NumPy/pymoo seeds are nonnegative)")
    require_positive_int("optimizer_config.population_size", c.population_size)
    require_positive_int("optimizer_config.generations", c.generations)
    require_positive_int("optimizer_config.max_evaluations", c.max_evaluations)
    return c


def validate_risk_config(c: RiskConfig) -> RiskConfig:
    if isinstance(c.seed, bool) or not isinstance(c.seed, int):
        _fail("risk_config.seed", "must be an int")
    n = require_positive_int("risk_config.n_simulations", c.n_simulations)
    if n > MAX_RISK_SIMULATIONS:
        _fail("risk_config.n_simulations", f"must be <= {MAX_RISK_SIMULATIONS}")
    if not isinstance(c.retain_samples, bool):
        _fail("risk_config.retain_samples", "must be a bool")
    return c


def validate_assumptions(a: ActionAssumptions) -> ActionAssumptions:
    if not isinstance(a, ActionAssumptions):
        _fail("assumptions", "must be ActionAssumptions")
    require_nonempty_str("assumptions.assumptions_id", a.assumptions_id)
    require_nonempty_str("assumptions.version", a.version)
    if not isinstance(a.is_calibrated, bool):
        _fail("assumptions.is_calibrated", "must be a bool")
    for name in ASSUMPTION_SCALAR_FIELDS:
        if require_finite(f"assumptions.{name}", getattr(a, name)) < 0:
            _fail(f"assumptions.{name}", "must be >= 0")
    ratio_fields = (
        "gas_share", "ice_fleet_share", "travel_share", "cloud_share", "supplier_share",
        "other_share", "building_electricity_share", "building_gas_share",
        "building_max_reduction", "cloud_max_reduction", "supplier_max_reduction",
        "renewable_effectiveness", "ev_effectiveness", "travel_effectiveness",
    )
    for name in ratio_fields:
        require_ratio(f"assumptions.{name}", getattr(a, name))
    if a.gas_share + a.ice_fleet_share > 1.0 + 1e-9:  # any remainder is other scope 1, untouched by actions
        _fail("assumptions.gas_share", "scope1 partition gas_share + ice_fleet_share must not exceed 1")
    s3 = a.travel_share + a.cloud_share + a.supplier_share + a.other_share
    if not math.isclose(s3, 1.0, abs_tol=1e-9):
        _fail("assumptions.travel_share", "scope3 partition shares must sum to 1")
    if set(a.costs) != set(ACTION_NAMES):
        _fail("assumptions.costs", f"must contain exactly the six actions {list(ACTION_NAMES)}")
    for name, cost in a.costs.items():
        for f in ("capex_at_full_gbp", "monthly_opex_at_full_gbp"):
            if require_finite(f"assumptions.costs.{name}.{f}", getattr(cost, f)) < 0:
                _fail(f"assumptions.costs.{name}.{f}", "must be >= 0")
        require_positive_int(f"assumptions.costs.{name}.asset_life_months", cost.asset_life_months)
    return a


def _validate_metrics(metrics: Mapping[str, Any], field: str) -> None:
    for name in SIMULATION_METRIC_FIELDS:
        if name not in metrics:
            _fail(f"{field}.{name}", "is required")
        value = metrics[name]
        if value is None:
            if name not in NULLABLE_METRIC_FIELDS:
                _fail(f"{field}.{name}", "must not be null")
            continue
        require_finite(f"{field}.{name}", value)


def validate_simulation_result(r: SimulationResult, baseline: BaselineBundle | None = None) -> SimulationResult:
    if not isinstance(r, SimulationResult):
        _fail("simulation", "must be a SimulationResult")
    _validate_common(r, "simulation")
    require_nonempty_str("simulation.baseline_id", r.baseline_id)
    if not str(r.strategy_id).startswith(STRATEGY_ID_PREFIX):
        _fail("simulation.strategy_id", f"must start with {STRATEGY_ID_PREFIX!r}")
    validate_action_config(r.config, "simulation.config")
    monthly = _require_columns(r.monthly, SIMULATION_MONTHLY_COLUMNS, "simulation.monthly")
    _require_monthly_dates(monthly, "simulation.monthly")
    _require_finite_columns(monthly, SIMULATION_MONTHLY_COLUMNS[1:], "simulation.monthly")
    for col in (*SCOPE_COLUMNS, "total_co2e_tco2e", "capex_gbp", "incremental_opex_gbp",
                "operating_savings_gbp", "depreciation_gbp", "budget_cost_gbp"):
        if (monthly[col] < -SCOPE_ATOL_TCO2E).any():
            _fail(f"simulation.monthly.{col}", "must be >= 0")
    scope_sum = monthly[list(SCOPE_COLUMNS)].sum(axis=1).to_numpy()
    if not np.allclose(scope_sum, monthly["total_co2e_tco2e"].to_numpy(), rtol=SCOPE_RTOL, atol=SCOPE_ATOL_TCO2E):
        _fail("simulation.monthly.total_co2e_tco2e", "must equal the sum of scopes")
    _validate_metrics(r.metrics, "simulation.metrics")
    sums = {
        "total_co2e_tco2e": ("total_co2e_tco2e", SCOPE_ATOL_TCO2E),
        "total_profit_gbp": ("operating_profit_gbp", CURRENCY_ATOL_GBP),
        "total_cost_gbp": ("budget_cost_gbp", CURRENCY_ATOL_GBP),
        "total_capex_gbp": ("capex_gbp", CURRENCY_ATOL_GBP),
    }
    for metric, (col, atol) in sums.items():
        if not math.isclose(float(r.metrics[metric]), float(monthly[col].sum()), rel_tol=SCOPE_RTOL, abs_tol=atol):
            _fail(f"simulation.metrics.{metric}", f"must equal the horizon sum of monthly {col}")
    if baseline is not None:
        if r.baseline_id != baseline.baseline_id:
            _fail("simulation.baseline_id", "does not match the baseline")
        if len(monthly) != len(baseline.monthly) or not (
            monthly["timestamp"].to_numpy() == baseline.monthly["timestamp"].to_numpy()
        ).all():
            _fail("simulation.monthly.timestamp", "must equal the baseline dates in the same order")
    return r


def _validate_table(frame: pd.DataFrame, field: str) -> None:
    _require_columns(frame, OPTIMIZATION_TABLE_COLUMNS, field)
    if len(frame) == 0:
        return
    _require_finite_columns(
        frame,
        [*ACTION_NAMES, "total_co2e_tco2e", "total_profit_gbp", "total_cost_gbp", "g_budget", "g_profit", "g_target"],
        field,
    )
    if not pd.api.types.is_bool_dtype(frame["feasible"]):
        _fail(f"{field}.feasible", f"must be bool, got {frame['feasible'].dtype}")
    if not pd.api.types.is_integer_dtype(frame["pareto_rank"]):
        _fail(f"{field}.pareto_rank", f"must be int, got {frame['pareto_rank'].dtype}")
    if frame["strategy_id"].duplicated().any():
        _fail(f"{field}.strategy_id", "must be unique")


def validate_optimization_result(r: OptimizationResult) -> OptimizationResult:
    if not isinstance(r, OptimizationResult):
        _fail("optimization", "must be an OptimizationResult")
    _validate_common(r, "optimization")
    if r.status not in OPTIMIZATION_STATUSES:
        _fail("optimization.status", f"must be one of {list(OPTIMIZATION_STATUSES)}")
    validate_constraints(r.constraints)
    _validate_table(r.candidates, "optimization.candidates")
    _validate_table(r.pareto, "optimization.pareto")
    if r.status == "ok" and len(r.pareto) == 0:
        _fail("optimization.pareto", "status 'ok' requires at least one feasible Pareto point")
    if r.status == "infeasible" and len(r.pareto) > 0:
        _fail("optimization.pareto", "status 'infeasible' requires an empty Pareto frontier")
    if len(r.pareto):
        if not r.pareto["feasible"].all():
            _fail("optimization.pareto.feasible", "every Pareto point must be feasible")
        if not (r.pareto["pareto_rank"] == 0).all():
            _fail("optimization.pareto.pareto_rank", "every Pareto point must have rank 0")
    for table_name, table in (("candidates", r.candidates), ("pareto", r.pareto)):
        for _, row in table.iterrows():
            sid = row["strategy_id"]
            if sid not in r.strategies:
                _fail(f"optimization.{table_name}.strategy_id", f"{sid!r} has no entry in strategies")
            stored = r.strategies[sid]
            if stored.strategy_id != sid:
                _fail("optimization.strategies", f"key {sid!r} maps to result {stored.strategy_id!r}")
            for name in ACTION_NAMES:
                if float(row[name]) != float(getattr(stored.config, name)):
                    _fail(f"optimization.{table_name}.{name}", f"row for {sid!r} differs from the stored exact config")
    for sid, sim in r.strategies.items():
        validate_simulation_result(sim)
        if sim.baseline_id != r.baseline_id:
            _fail("optimization.strategies", f"{sid!r} has a different baseline_id")
    return r


def validate_recommendation(rec: RecommendationResult, optimization: OptimizationResult | None = None) -> RecommendationResult:
    if not isinstance(rec, RecommendationResult):
        _fail("recommendation", "must be a RecommendationResult")
    _validate_common(rec, "recommendation")
    if rec.tolerance not in TOLERANCES:
        _fail("recommendation.tolerance", f"must be one of {list(TOLERANCES)}")
    if rec.risk_status not in RISK_STATUSES:
        _fail("recommendation.risk_status", f"must be one of {list(RISK_STATUSES)}")
    if rec.score is not None:
        require_finite("recommendation.score", rec.score)
    if optimization is not None:
        if optimization.status == "infeasible" and rec.strategy_id is not None:
            _fail("recommendation.strategy_id", "must be null when optimization is infeasible")
        if optimization.status == "ok":
            if rec.strategy_id is None:
                _fail("recommendation.strategy_id", "must be set when a feasible frontier exists")
            if rec.strategy_id not in set(optimization.pareto["strategy_id"]):
                _fail("recommendation.strategy_id", "must be a validated feasible Pareto strategy")
    return rec


def validate_risk_result(r: RiskResult) -> RiskResult:
    _validate_common(r, "risk")
    require_nonempty_str("risk.strategy_id", r.strategy_id)
    require_positive_int("risk.n_simulations", r.n_simulations)
    require_nonempty_str("risk.uncertainty_id", r.uncertainty_id)
    for name in RISK_SUMMARY_FIELDS:
        if name not in r.summary:
            _fail(f"risk.summary.{name}", "is required")
        value = r.summary[name]
        if value is None:
            # Only probabilities tied to an undefined ratio may be null, and the target
            # probability's standard error with it (no zero-filled errors, DATA_SCHEMAS.md s9).
            se_of_undefined_target = name == "target_probability_mc_standard_error" and r.summary["target_probability"] is None
            if not (name.endswith("probability") or se_of_undefined_target):
                _fail(f"risk.summary.{name}", "must not be null")
            continue
        v = require_finite(f"risk.summary.{name}", value)
        if name.endswith("probability") and not 0 <= v <= 1:
            _fail(f"risk.summary.{name}", "probability must be within [0, 1]")
    s = r.summary
    for lo, hi in (("co2_p05_tco2e", "co2_p95_tco2e"), ("profit_p05_gbp", "profit_p95_gbp")):
        if s[lo] > s[hi]:
            _fail(f"risk.summary.{lo}", f"must be <= {hi}")
    return r


def validate_benchmark_result(b: BenchmarkResult) -> BenchmarkResult:
    _validate_common(b, "benchmark")
    if b.status not in BENCHMARK_STATUSES:
        _fail("benchmark.status", f"must be one of {list(BENCHMARK_STATUSES)}")
    if b.status == "unavailable":
        require_nonempty_str("benchmark.reason", b.reason)
        return b
    for name in ("company_intensity_tco2e_per_million_gbp", "industry_median", "percentile", "better_than_pct"):
        require_finite(f"benchmark.{name}", getattr(b, name))
    for name in ("percentile", "better_than_pct"):
        if not 0 <= getattr(b, name) <= 100:
            _fail(f"benchmark.{name}", "must be within [0, 100]")
    if not math.isclose(b.percentile + b.better_than_pct, 100.0, abs_tol=1e-9):
        _fail("benchmark.better_than_pct", "must equal 100 - percentile")
    require_positive_int("benchmark.peer_count", b.peer_count)
    return b


def validate_backtest_report(r: BacktestReport) -> BacktestReport:
    _validate_common(r, "backtest")
    require_nonempty_str("backtest.model_family", r.model_family)
    _require_columns(r.folds, BACKTEST_FOLD_COLUMNS, "backtest.folds")
    oof = _require_columns(r.oof_predictions, BACKTEST_OOF_COLUMNS, "backtest.oof_predictions")
    if len(oof):
        _require_finite_columns(oof, ["actual", "predicted", "naive_predicted"], "backtest.oof_predictions")
        if not set(oof["target"]).issubset(FORECAST_TARGETS):
            _fail("backtest.oof_predictions.target", f"must be one of {list(FORECAST_TARGETS)}")
    for target, metrics in r.aggregate_metrics.items():
        if target not in FORECAST_TARGETS:
            _fail("backtest.aggregate_metrics", f"unknown target {target!r}")
        for name in ("mae", "rmse", "naive_mae", "naive_rmse"):
            if name not in metrics:
                _fail(f"backtest.aggregate_metrics.{target}.{name}", "is required")
            if require_finite(f"backtest.aggregate_metrics.{target}.{name}", metrics[name]) < 0:
                _fail(f"backtest.aggregate_metrics.{target}.{name}", "must be >= 0")
        if metrics.get("r2") is not None:
            require_finite(f"backtest.aggregate_metrics.{target}.r2", metrics["r2"])
    return r


def validate_explanation(e: ExplanationResult) -> ExplanationResult:
    _validate_common(e, "explanation")
    if e.output_space != "raw_model":
        _fail("explanation.output_space", "must be 'raw_model'")
    frame = _require_columns(e.contributions, SHAP_COLUMNS, "explanation.contributions")
    if len(frame):
        _require_finite_columns(frame, ["shap_value", "base_value", "model_prediction"], "explanation.contributions")
    for target in set(frame["target"]):
        if target not in e.units:
            _fail("explanation.units", f"missing unit for target {target!r}")
    return e


def validate_analysis_request(req: AnalysisRequest, supported_horizons: tuple[int, ...] | None = None) -> AnalysisRequest:
    if not isinstance(req, AnalysisRequest):
        _fail("request", "must be an AnalysisRequest")
    require_nonempty_str("request.company_id", req.company_id)
    validate_horizon(req.horizon_months, supported_horizons)
    validate_constraints(req.constraints)
    validate_optimizer_config(req.optimizer_config)
    validate_risk_config(req.risk_config)
    if req.tolerance not in TOLERANCES:
        _fail("request.tolerance", f"must be one of {list(TOLERANCES)}")
    for name in ("risk_enabled", "benchmark_enabled", "explanation_enabled"):
        if not isinstance(getattr(req, name), bool):
            _fail(f"request.{name}", "must be a bool")
    return req
