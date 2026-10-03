"""Boundary validators for contract 1.0.0 objects (shared C0 file; flag for WS4 review).

Every validator raises :class:`ContractValidationError` with a dotted field path and a
reason, and returns its (unchanged) argument on success. Inputs are never mutated.
"""

from __future__ import annotations

import datetime as dt
import math
import re
from typing import Any

import numpy as np
import pandas as pd

from src.contracts._scalars import require_int, require_str
from src.contracts.errors import ContractValidationError
from src.contracts.types import (
    ACTION_NAMES,
    BASELINE_MONTHLY_COLUMNS,
    CANDIDATE_COLUMNS,
    DATA_KINDS,
    SIMULATION_MONTHLY_COLUMNS,
    SUPPORTED_BASELINE_HORIZONS,
    SUPPORTED_SCHEMA_MAJOR,
    ActionAssumptions,
    ActionConfig,
    BaselineBundle,
    BaselineTotals,
    ColumnSpec,
    ConstraintConfig,
    OptimizerConfig,
    Provenance,
    RiskResult,
    RiskSummary,
    SimulationMetrics,
    SimulationResult,
)

#: Scope/total identities: relative 1e-8 plus absolute 1e-6 tonnes (DATA_SCHEMAS.md §1).
EMISSIONS_RTOL = 1e-8
EMISSIONS_ATOL_TCO2E = 1e-6
#: Currency reconciliation: absolute 0.01 GBP (DATA_SCHEMAS.md §1).
CURRENCY_ATOL_GBP = 0.01

_SEMVER = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")
_EMPTY_DTYPES = {"str": object, "float": np.float64, "nullable_float": np.float64, "int": np.int64, "bool": bool}

_BASELINE_NUMERIC = tuple(name for name, kind in BASELINE_MONTHLY_COLUMNS if kind in ("float", "int"))
_BASELINE_INDEX = {name: i for i, name in enumerate(_BASELINE_NUMERIC)}
_SIMULATION_NUMERIC = tuple(name for name, kind in SIMULATION_MONTHLY_COLUMNS if kind == "float")
_SIMULATION_INDEX = {name: i for i, name in enumerate(_SIMULATION_NUMERIC)}


def emissions_tolerance(reference: float) -> float:
    """Absolute tolerance for comparing emission quantities of magnitude ``reference``."""
    return EMISSIONS_ATOL_TCO2E + EMISSIONS_RTOL * abs(reference)


def validate_schema_version(field: str, value: Any) -> str:
    text = require_str(field, value)
    match = _SEMVER.match(text)
    if match is None:
        raise ContractValidationError(field, f"must be MAJOR.MINOR.PATCH; got {text!r}")
    if int(match.group(1)) != SUPPORTED_SCHEMA_MAJOR:
        raise ContractValidationError(
            field, f"unsupported major version {text!r}; this build supports {SUPPORTED_SCHEMA_MAJOR}.x.y"
        )
    return text


def _require_instance(field: str, value: Any, expected: type) -> None:
    if not isinstance(value, expected):
        raise ContractValidationError(field, f"expected {expected.__name__}; got {type(value).__name__}")


# Configuration objects validate themselves on construction; boundary checks confirm the type.


def validate_action_config(config: Any, field: str = "config") -> ActionConfig:
    _require_instance(field, config, ActionConfig)
    return config


def validate_constraint_config(constraints: Any, field: str = "constraints") -> ConstraintConfig:
    _require_instance(field, constraints, ConstraintConfig)
    return constraints


def validate_optimizer_config(config: Any, field: str = "optimizer_config") -> OptimizerConfig:
    _require_instance(field, config, OptimizerConfig)
    return config


def validate_action_assumptions(assumptions: Any, field: str = "assumptions") -> ActionAssumptions:
    _require_instance(field, assumptions, ActionAssumptions)
    return assumptions


def validate_provenance(provenance: Any, field: str = "provenance") -> Provenance:
    _require_instance(field, provenance, Provenance)
    return provenance


# ---------------------------------------------------------------------------
# DataFrame helpers
# ---------------------------------------------------------------------------


def _require_columns(field: str, frame: Any, columns: ColumnSpec) -> None:
    _require_instance(field, frame, pd.DataFrame)
    if frame.columns.duplicated().any():
        raise ContractValidationError(field, "duplicate column names")
    missing = [name for name, _ in columns if name not in frame.columns]
    if missing:
        raise ContractValidationError(field, f"missing required columns {missing}")


def _numeric_block(field: str, frame: pd.DataFrame, names: tuple[str, ...]) -> np.ndarray:
    """Return the named columns as a float64 2-D copy after dtype and finiteness checks."""
    for name in names:
        dtype = frame[name].dtype
        if not pd.api.types.is_numeric_dtype(dtype) or pd.api.types.is_bool_dtype(dtype):
            raise ContractValidationError(f"{field}.{name}", f"must be numeric; got dtype {dtype}")
    try:
        block = frame.loc[:, list(names)].to_numpy(dtype=np.float64, copy=True)
    except (TypeError, ValueError) as exc:  # e.g. pandas NA in nullable dtypes
        raise ContractValidationError(field, f"numeric columns must not contain missing values ({exc})") from None
    finite = np.isfinite(block)
    if not finite.all():
        row, col = np.argwhere(~finite)[0]
        raise ContractValidationError(f"{field}.{names[col]}", f"row {row} must be finite; got {block[row, col]!r}")
    return block


def _month_starts(field: str, series: pd.Series) -> np.ndarray:
    """Validate a timezone-naive calendar month-start column; return datetime64[M] values."""
    dtype = series.dtype
    if isinstance(dtype, pd.DatetimeTZDtype) or not pd.api.types.is_datetime64_dtype(dtype):
        raise ContractValidationError(field, f"must be timezone-naive datetime64; got dtype {dtype}")
    values = series.to_numpy(dtype="datetime64[ns]")
    if np.isnat(values).any():
        raise ContractValidationError(field, "must not contain missing dates")
    months = values.astype("datetime64[M]")
    if not (months.astype("datetime64[ns]") == values).all():
        raise ContractValidationError(field, "must be calendar month starts (YYYY-MM-01 00:00)")
    return months


def require_month_start_date(field: str, value: Any) -> dt.date:
    """Accept a ``datetime.date`` (or midnight ``datetime``) on the first day of a month."""
    if isinstance(value, dt.datetime):
        if value.tzinfo is not None or value.time() != dt.time(0, 0):
            raise ContractValidationError(field, "must be a timezone-naive calendar date")
        value = value.date()
    if not isinstance(value, dt.date):
        raise ContractValidationError(field, f"must be a calendar date; got {type(value).__name__}")
    if value.day != 1:
        raise ContractValidationError(field, f"must be a month start (YYYY-MM-01); got {value.isoformat()}")
    return value


def _first_bad(field: str, months: np.ndarray, mask: np.ndarray, reason: str) -> None:
    if mask.any():
        index = int(np.flatnonzero(mask)[0])
        raise ContractValidationError(field, f"{reason} (first at {months[index]})")


# ---------------------------------------------------------------------------
# BaselineBundle
# ---------------------------------------------------------------------------


def validate_baseline_bundle(baseline: Any) -> BaselineBundle:
    """Validate metadata, monthly schema, date continuity, ranges and identities (§2, §4)."""
    _require_instance("baseline", baseline, BaselineBundle)
    validate_schema_version("baseline.schema_version", baseline.schema_version)
    require_str("baseline.run_id", baseline.run_id)
    validate_provenance(baseline.provenance, "baseline.provenance")
    for name in ("baseline_id", "company_id", "model_id", "driver_policy_id", "scope2_method"):
        require_str(f"baseline.{name}", getattr(baseline, name))
    if baseline.data_kind not in DATA_KINDS:
        raise ContractValidationError("baseline.data_kind", f"must be one of {list(DATA_KINDS)}; got {baseline.data_kind!r}")
    if baseline.currency != "GBP":
        raise ContractValidationError("baseline.currency", f"must be 'GBP'; got {baseline.currency!r}")
    horizon = require_int("baseline.horizon_months", baseline.horizon_months, minimum=1)
    if horizon not in SUPPORTED_BASELINE_HORIZONS:
        raise ContractValidationError(
            "baseline.horizon_months", f"must be one of {list(SUPPORTED_BASELINE_HORIZONS)}; got {horizon}"
        )
    history_end = require_month_start_date("baseline.history_end", baseline.history_end)
    _require_instance("baseline.totals", baseline.totals, BaselineTotals)

    monthly = baseline.monthly
    _require_columns("baseline.monthly", monthly, BASELINE_MONTHLY_COLUMNS)
    if len(monthly) != horizon:
        raise ContractValidationError("baseline.monthly", f"expected {horizon} rows (horizon_months); got {len(monthly)}")

    months = _month_starts("baseline.monthly.timestamp", monthly["timestamp"])
    expected = np.datetime64(history_end, "M") + 1 + np.arange(horizon)
    if not (months == expected).all():
        raise ContractValidationError(
            "baseline.monthly.timestamp",
            f"must be {horizon} unique, ascending, contiguous months starting {expected[0]}-01 "
            "(one month after history_end)",
        )

    company = monthly["company_id"].to_numpy(dtype=object)
    if not all(isinstance(value, str) for value in company) or not (company == baseline.company_id).all():
        raise ContractValidationError("baseline.monthly.company_id", "every row must equal baseline.company_id (one company)")

    block = _numeric_block("baseline.monthly", monthly, _BASELINE_NUMERIC)

    def col(name: str) -> np.ndarray:
        return block[:, _BASELINE_INDEX[name]]

    field = "baseline.monthly"
    _first_bad(f"{field}.revenue_gbp", months, col("revenue_gbp") <= 0.0, "must be > 0")
    for name in ("employees", "fleet_size"):
        values = col(name)
        _first_bad(f"{field}.{name}", months, (values < 0.0) | (values != np.floor(values)), "must be a nonnegative integer")
    for name in (
        "electricity_kwh",
        "gas_kwh",
        "fleet_km",
        "business_travel_km",
        "cloud_compute_hours",
        "scope1_tco2e",
        "scope2_tco2e",
        "scope3_tco2e",
        "total_co2e_tco2e",
    ):
        _first_bad(f"{field}.{name}", months, col(name) < 0.0, "must be >= 0")
    for name in ("renewable_energy_share", "ev_share"):
        values = col(name)
        _first_bad(
            f"{field}.{name}",
            months,
            (values < 0.0) | (values > 1.0),
            "must be a fraction within [0, 1] (0-100 percentages are not accepted)",
        )

    total = col("total_co2e_tco2e")
    scope_sum = col("scope1_tco2e") + col("scope2_tco2e") + col("scope3_tco2e")
    _first_bad(
        f"{field}.total_co2e_tco2e",
        months,
        np.abs(total - scope_sum) > EMISSIONS_ATOL_TCO2E + EMISSIONS_RTOL * np.abs(total),
        "must equal scope1 + scope2 + scope3 within tolerance",
    )

    totals = baseline.totals
    if abs(math.fsum(col("revenue_gbp")) - totals.revenue_gbp) > CURRENCY_ATOL_GBP:
        raise ContractValidationError("baseline.totals.revenue_gbp", "must equal the sum of monthly revenue_gbp")
    if abs(math.fsum(col("operating_profit_gbp")) - totals.operating_profit_gbp) > CURRENCY_ATOL_GBP:
        raise ContractValidationError(
            "baseline.totals.operating_profit_gbp", "must equal the sum of monthly operating_profit_gbp"
        )
    if abs(math.fsum(total) - totals.total_co2e_tco2e) > emissions_tolerance(totals.total_co2e_tco2e):
        raise ContractValidationError("baseline.totals.total_co2e_tco2e", "must equal the sum of monthly total_co2e_tco2e")
    return baseline


# ---------------------------------------------------------------------------
# SimulationResult
# ---------------------------------------------------------------------------

_NONNEGATIVE_SIMULATION_COLUMNS = (
    "scope1_tco2e",
    "scope2_tco2e",
    "scope3_tco2e",
    "total_co2e_tco2e",
    "capex_gbp",
    "incremental_opex_gbp",
    "operating_savings_gbp",
    "depreciation_gbp",
    "budget_cost_gbp",
)


def validate_simulation_result(result: Any, *, expected_months: int | None = None) -> SimulationResult:
    """Validate schema, nonnegativity and metric/monthly reconciliation of a SimulationResult."""
    _require_instance("simulation", result, SimulationResult)
    validate_schema_version("simulation.schema_version", result.schema_version)
    require_str("simulation.run_id", result.run_id)
    validate_provenance(result.provenance, "simulation.provenance")
    require_str("simulation.baseline_id", result.baseline_id)
    strategy_id = require_str("simulation.strategy_id", result.strategy_id)
    if not strategy_id.startswith("strategy-"):
        raise ContractValidationError("simulation.strategy_id", f"must start with 'strategy-'; got {strategy_id!r}")
    validate_action_config(result.config, "simulation.config")
    _require_instance("simulation.metrics", result.metrics, SimulationMetrics)

    monthly = result.monthly
    _require_columns("simulation.monthly", monthly, SIMULATION_MONTHLY_COLUMNS)
    if expected_months is not None and len(monthly) != expected_months:
        raise ContractValidationError("simulation.monthly", f"expected {expected_months} rows; got {len(monthly)}")
    if len(monthly) == 0:
        raise ContractValidationError("simulation.monthly", "must contain at least one month")
    months = _month_starts("simulation.monthly.timestamp", monthly["timestamp"])
    block = _numeric_block("simulation.monthly", monthly, _SIMULATION_NUMERIC)

    def col(name: str) -> np.ndarray:
        return block[:, _SIMULATION_INDEX[name]]

    for name in _NONNEGATIVE_SIMULATION_COLUMNS:
        _first_bad(f"simulation.monthly.{name}", months, col(name) < 0.0, "must be >= 0")

    metrics = result.metrics
    checks = (
        ("total_co2e_tco2e", "total_co2e_tco2e", None),
        ("total_profit_gbp", "operating_profit_gbp", CURRENCY_ATOL_GBP),
        ("total_cost_gbp", "budget_cost_gbp", CURRENCY_ATOL_GBP),
        ("total_capex_gbp", "capex_gbp", CURRENCY_ATOL_GBP),
        ("total_incremental_opex_gbp", "incremental_opex_gbp", CURRENCY_ATOL_GBP),
        ("total_operating_savings_gbp", "operating_savings_gbp", CURRENCY_ATOL_GBP),
        ("net_cash_impact_gbp", "net_cash_impact_gbp", CURRENCY_ATOL_GBP),
    )
    for metric_name, column, tolerance in checks:
        metric = getattr(metrics, metric_name)
        tol = emissions_tolerance(metric) if tolerance is None else tolerance
        if abs(math.fsum(col(column)) - metric) > tol:
            raise ContractValidationError(f"simulation.metrics.{metric_name}", f"must equal the sum of monthly {column}")
    baseline_co2 = metrics.baseline_total_co2e_tco2e
    if abs(baseline_co2 - metrics.total_co2e_tco2e - metrics.co2_reduction_tco2e) > emissions_tolerance(baseline_co2):
        raise ContractValidationError("simulation.metrics.co2_reduction_tco2e", "must equal baseline minus scenario CO2e")
    if (baseline_co2 == 0.0) != (metrics.co2_reduction_ratio is None):
        raise ContractValidationError(
            "simulation.metrics.co2_reduction_ratio", "must be null exactly when baseline CO2e is zero"
        )
    if (metrics.baseline_total_profit_gbp == 0.0) != (metrics.profit_change_ratio is None):
        raise ContractValidationError(
            "simulation.metrics.profit_change_ratio", "must be null exactly when baseline profit is zero"
        )
    return result


# ---------------------------------------------------------------------------
# Candidate / Pareto tables
# ---------------------------------------------------------------------------


def normalize_candidate_frame(frame: Any, field: str = "candidates", *, require_rank: bool = True) -> pd.DataFrame:
    """Validate a candidates/Pareto table and return a typed copy in canonical column order.

    ``pareto_rank`` may be omitted when ``require_rank`` is false (it is an output column).
    """
    columns = CANDIDATE_COLUMNS if require_rank else tuple(c for c in CANDIDATE_COLUMNS if c[0] != "pareto_rank")
    _require_columns(field, frame, columns)
    if len(frame) == 0:  # nothing to validate; always hand back the typed empty schema
        return pd.DataFrame({name: pd.Series(dtype=_EMPTY_DTYPES[kind]) for name, kind in CANDIDATE_COLUMNS})
    data: dict[str, Any] = {}

    ids = frame["strategy_id"].to_numpy(dtype=object)
    if not all(isinstance(value, str) and value.strip() for value in ids):
        raise ContractValidationError(f"{field}.strategy_id", "must contain nonempty strings")
    data["strategy_id"] = pd.Series(ids, dtype=object, copy=True)

    float_names = tuple(name for name, kind in columns if kind == "float")
    block = _numeric_block(field, frame, float_names)
    for i, name in enumerate(float_names):
        data[name] = block[:, i]
    actions = block[:, : len(ACTION_NAMES)]
    if ((actions < 0.0) | (actions > 1.0)).any():
        raise ContractValidationError(field, "action columns must be fractions within [0, 1]")
    if (data["total_cost_gbp"] < 0.0).any():
        raise ContractValidationError(f"{field}.total_cost_gbp", "must be >= 0")

    ratio_series = frame["co2_reduction_ratio"]
    numeric_dtype = pd.api.types.is_numeric_dtype(ratio_series.dtype) and not pd.api.types.is_bool_dtype(
        ratio_series.dtype
    )
    if not numeric_dtype and not all(
        value is None or (isinstance(value, (int, float, np.number)) and not isinstance(value, (bool, np.bool_)))
        for value in ratio_series.to_numpy(dtype=object)
    ):
        raise ContractValidationError(f"{field}.co2_reduction_ratio", "must be numeric or null")
    ratio = pd.to_numeric(ratio_series, errors="raise").to_numpy(dtype=np.float64, na_value=np.nan)
    if np.isinf(ratio).any():
        raise ContractValidationError(f"{field}.co2_reduction_ratio", "must be finite or null")
    data["co2_reduction_ratio"] = ratio

    feasible = frame["feasible"]
    if not pd.api.types.is_bool_dtype(feasible.dtype):
        raise ContractValidationError(f"{field}.feasible", f"must be boolean; got dtype {feasible.dtype}")
    data["feasible"] = feasible.to_numpy(dtype=bool, copy=True)

    if require_rank:
        rank = frame["pareto_rank"]
        if not pd.api.types.is_integer_dtype(rank.dtype) or pd.api.types.is_bool_dtype(rank.dtype):
            raise ContractValidationError(f"{field}.pareto_rank", f"must be integer; got dtype {rank.dtype}")
        data["pareto_rank"] = rank.to_numpy(dtype=np.int64, copy=True)
    else:
        data["pareto_rank"] = np.full(len(frame), -1, dtype=np.int64)

    ordered = {name: data[name] for name, _ in CANDIDATE_COLUMNS}
    return pd.DataFrame(ordered).reset_index(drop=True)


# ---------------------------------------------------------------------------
# RiskResult (produced by WS3, consumed by WS2 recommendation)
# ---------------------------------------------------------------------------


def validate_risk_result(result: Any, field: str = "risk_result") -> RiskResult:
    _require_instance(field, result, RiskResult)
    validate_schema_version(f"{field}.schema_version", result.schema_version)
    require_str(f"{field}.run_id", result.run_id)
    validate_provenance(result.provenance, f"{field}.provenance")
    require_str(f"{field}.strategy_id", result.strategy_id)
    require_str(f"{field}.baseline_id", result.baseline_id)
    require_str(f"{field}.uncertainty_id", result.uncertainty_id)
    require_int(f"{field}.n_simulations", result.n_simulations, minimum=1)
    summary = result.summary
    _require_instance(f"{field}.summary", summary, RiskSummary)
    if summary.co2_p05_tco2e > summary.co2_p95_tco2e:
        raise ContractValidationError(f"{field}.summary.co2_p05_tco2e", "must be <= co2_p95_tco2e")
    if summary.profit_p05_gbp > summary.profit_p95_gbp:
        raise ContractValidationError(f"{field}.summary.profit_p05_gbp", "must be <= profit_p95_gbp")
    if result.samples is not None:
        _require_instance(f"{field}.samples", result.samples, pd.DataFrame)
    return result
