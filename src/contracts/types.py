"""Contract 1.0.0 domain types (docs/SHARED_CONTRACTS.md §2, docs/DATA_SCHEMAS.md).

Shared C0 file, flagged for WS4 review: this is the minimal subset WS2 needs to publish
and consume its boundary objects. Types owned by other workstreams that WS2 does not touch
(ModelBundle, BacktestReport, UncertaintySpec, RiskConfig, BenchmarkResult, ...) are left
to their producers.

Configuration-like types validate and normalise themselves on construction, so an
instance always satisfies its documented invariants. Types that carry DataFrames are
checked by :mod:`src.contracts.validation` at every public boundary instead.
"""

from __future__ import annotations

import datetime as dt
import math
from dataclasses import dataclass, field
from typing import Any, Iterator, Literal, Mapping, Sequence

import pandas as pd

from src.contracts._scalars import (
    require_bool,
    require_finite,
    require_int,
    require_nonnegative,
    require_str,
    require_unit_interval,
    require_whole_number,
)
from src.contracts.errors import ContractValidationError

SCHEMA_VERSION = "1.0.0"
SUPPORTED_SCHEMA_MAJOR = 1

#: Canonical ActionConfig / optimizer decision-vector order (DATA_SCHEMAS.md §5).
ACTION_NAMES: tuple[str, ...] = (
    "renewable_energy",
    "ev_adoption",
    "building_efficiency",
    "travel_reduction",
    "cloud_efficiency",
    "supplier_transition",
)

SUPPORTED_BASELINE_HORIZONS: tuple[int, ...] = (12, 36, 60)
DATA_KINDS: tuple[str, ...] = ("synthetic", "reported", "interpolated")

OptimizationStatus = Literal["ok", "infeasible"]
RiskTolerance = Literal["conservative", "balanced", "aggressive"]
RiskStatus = Literal["not_requested", "unavailable", "partial", "evaluated", "threshold_unmet"]
OPTIMIZATION_STATUSES: tuple[str, ...] = ("ok", "infeasible")
RISK_TOLERANCES: tuple[str, ...] = ("conservative", "balanced", "aggressive")
RISK_STATUSES: tuple[str, ...] = ("not_requested", "unavailable", "partial", "evaluated", "threshold_unmet")

# Column specifications: (name, kind). Kinds map to in-memory dtypes as
# date -> datetime64[ns], str -> object, float/nullable_float -> float64, int -> int64, bool -> bool.
ColumnSpec = tuple[tuple[str, str], ...]

BASELINE_MONTHLY_COLUMNS: ColumnSpec = (
    ("company_id", "str"),
    ("timestamp", "date"),
    ("revenue_gbp", "float"),
    ("operating_profit_gbp", "float"),
    ("employees", "int"),
    ("electricity_kwh", "float"),
    ("gas_kwh", "float"),
    ("renewable_energy_share", "float"),
    ("ev_share", "float"),
    ("fleet_size", "int"),
    ("fleet_km", "float"),
    ("business_travel_km", "float"),
    ("cloud_compute_hours", "float"),
    ("scope1_tco2e", "float"),
    ("scope2_tco2e", "float"),
    ("scope3_tco2e", "float"),
    ("total_co2e_tco2e", "float"),
)

SIMULATION_MONTHLY_COLUMNS: ColumnSpec = (
    ("timestamp", "date"),
    ("revenue_gbp", "float"),
    ("operating_profit_gbp", "float"),
    ("scope1_tco2e", "float"),
    ("scope2_tco2e", "float"),
    ("scope3_tco2e", "float"),
    ("total_co2e_tco2e", "float"),
    ("capex_gbp", "float"),
    ("incremental_opex_gbp", "float"),
    ("operating_savings_gbp", "float"),
    ("depreciation_gbp", "float"),
    ("budget_cost_gbp", "float"),
    ("net_cash_impact_gbp", "float"),
)

#: Shared schema of OptimizationResult.candidates and OptimizationResult.pareto (§7).
CANDIDATE_COLUMNS: ColumnSpec = (
    ("strategy_id", "str"),
    *((name, "float") for name in ACTION_NAMES),
    ("total_co2e_tco2e", "float"),
    ("total_profit_gbp", "float"),
    ("total_cost_gbp", "float"),
    ("co2_reduction_ratio", "nullable_float"),
    ("g_budget", "float"),
    ("g_profit", "float"),
    ("g_target", "float"),
    ("feasible", "bool"),
    ("pareto_rank", "int"),
)

_set = object.__setattr__


# ---------------------------------------------------------------------------
# Configuration objects
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ActionConfig:
    """Implementation fractions of remaining eligible opportunity, in canonical order.

    Each value is a float in [0, 1]; out-of-range values are rejected, never clamped.
    ``-0.0`` is normalised to ``0.0`` so equal configurations share one identity.
    """

    renewable_energy: float
    ev_adoption: float
    building_efficiency: float
    travel_reduction: float
    cloud_efficiency: float
    supplier_transition: float

    def __post_init__(self) -> None:
        for name in ACTION_NAMES:
            _set(self, name, require_unit_interval(f"config.{name}", getattr(self, name)))

    @classmethod
    def zeros(cls) -> "ActionConfig":
        """The exact no-op configuration."""
        return cls(0.0, 0.0, 0.0, 0.0, 0.0, 0.0)

    @classmethod
    def from_sequence(cls, values: Sequence[float]) -> "ActionConfig":
        """Build from a decision vector in canonical ACTION_NAMES order."""
        values = list(values)
        if len(values) != len(ACTION_NAMES):
            raise ContractValidationError(
                "config", f"expected {len(ACTION_NAMES)} values in canonical order; got {len(values)}"
            )
        return cls(*values)

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "ActionConfig":
        """Build from a field mapping; all six names are required and no others are allowed."""
        if not isinstance(data, Mapping):
            raise ContractValidationError("config", f"must be an object; got {type(data).__name__}")
        missing = [name for name in ACTION_NAMES if name not in data]
        unknown = sorted(set(data) - set(ACTION_NAMES))
        if missing:
            raise ContractValidationError("config", f"missing action fields {missing}")
        if unknown:
            raise ContractValidationError("config", f"unknown action fields {unknown}")
        return cls(*(data[name] for name in ACTION_NAMES))

    def to_tuple(self) -> tuple[float, ...]:
        return tuple(getattr(self, name) for name in ACTION_NAMES)

    def to_dict(self) -> dict[str, float]:
        return {name: getattr(self, name) for name in ACTION_NAMES}

    def is_noop(self) -> bool:
        return all(value == 0.0 for value in self.to_tuple())


@dataclass(frozen=True)
class ConstraintConfig:
    """Horizon-total constraints: gross outlay budget, cumulative profit floor, reduction target."""

    budget_gbp: float
    min_total_profit_gbp: float
    min_co2_reduction_ratio: float

    def __post_init__(self) -> None:
        _set(self, "budget_gbp", require_nonnegative("constraints.budget_gbp", self.budget_gbp))
        _set(
            self,
            "min_total_profit_gbp",
            require_finite("constraints.min_total_profit_gbp", self.min_total_profit_gbp),
        )
        _set(
            self,
            "min_co2_reduction_ratio",
            require_unit_interval("constraints.min_co2_reduction_ratio", self.min_co2_reduction_ratio),
        )


@dataclass(frozen=True)
class OptimizerConfig:
    """NSGA-II settings. ``max_evaluations`` bounds every search evaluation, including initialization."""

    seed: int = 42
    population_size: int = 64
    generations: int = 32
    max_evaluations: int = 2048

    def __post_init__(self) -> None:
        _set(self, "seed", require_int("optimizer_config.seed", self.seed, minimum=0, maximum=2**32 - 1))
        for name in ("population_size", "generations", "max_evaluations"):
            _set(self, name, require_int(f"optimizer_config.{name}", getattr(self, name), minimum=1))


# ---------------------------------------------------------------------------
# Provenance and baseline
# ---------------------------------------------------------------------------


@dataclass(frozen=True, kw_only=True)
class Provenance:
    """Common provenance carried by every serialized result (SHARED_CONTRACTS.md §1)."""

    provider: str
    is_mock: bool
    seed: int | None
    input_hash: str
    config_id: str
    assumptions_id: str | None

    def __post_init__(self) -> None:
        require_str("provenance.provider", self.provider)
        _set(self, "is_mock", require_bool("provenance.is_mock", self.is_mock))
        if self.seed is not None:
            _set(self, "seed", require_int("provenance.seed", self.seed))
        require_str("provenance.input_hash", self.input_hash)
        require_str("provenance.config_id", self.config_id)
        if self.assumptions_id is not None:
            require_str("provenance.assumptions_id", self.assumptions_id)


@dataclass(frozen=True, kw_only=True)
class BaselineTotals:
    revenue_gbp: float
    operating_profit_gbp: float
    total_co2e_tco2e: float

    def __post_init__(self) -> None:
        for name in ("revenue_gbp", "operating_profit_gbp", "total_co2e_tco2e"):
            _set(self, name, require_finite(f"baseline.totals.{name}", getattr(self, name)))


@dataclass(frozen=True, kw_only=True, eq=False)
class BaselineBundle:
    """Forecast baseline: canonical ``monthly`` frame (history schema) plus metadata (§4).

    Treat ``monthly`` as read-only; consumers must not add or modify columns in place.
    """

    schema_version: str
    run_id: str
    provenance: Provenance
    baseline_id: str
    company_id: str
    history_end: dt.date
    horizon_months: int
    model_id: str
    driver_policy_id: str
    data_kind: str
    scope2_method: str
    currency: str
    monthly: pd.DataFrame
    totals: BaselineTotals


# ---------------------------------------------------------------------------
# Action assumptions (values owned by WS2; see config/action_assumptions.json)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, kw_only=True)
class ActionCost:
    """Per-action cost coefficients at full implementation of the remaining opportunity."""

    capex_at_full_gbp: float
    monthly_opex_at_full_gbp: float
    asset_life_months: int

    def __post_init__(self) -> None:
        _set(self, "capex_at_full_gbp", require_nonnegative("capex_at_full_gbp", self.capex_at_full_gbp))
        _set(
            self,
            "monthly_opex_at_full_gbp",
            require_nonnegative("monthly_opex_at_full_gbp", self.monthly_opex_at_full_gbp),
        )
        _set(
            self,
            "asset_life_months",
            require_whole_number("asset_life_months", self.asset_life_months, minimum=1),
        )


@dataclass(frozen=True, kw_only=True)
class ActionCosts:
    """Cost coefficients keyed by the six canonical action names (serialized as ``costs``)."""

    renewable_energy: ActionCost
    ev_adoption: ActionCost
    building_efficiency: ActionCost
    travel_reduction: ActionCost
    cloud_efficiency: ActionCost
    supplier_transition: ActionCost

    def __post_init__(self) -> None:
        for name in ACTION_NAMES:
            if not isinstance(getattr(self, name), ActionCost):
                raise ContractValidationError(f"assumptions.costs.{name}", "must be an ActionCost")

    def __getitem__(self, name: str) -> ActionCost:
        if name not in ACTION_NAMES:
            raise KeyError(name)
        return getattr(self, name)

    def items(self) -> Iterator[tuple[str, ActionCost]]:
        return ((name, getattr(self, name)) for name in ACTION_NAMES)


#: Allowed absolute deviation of a bucket partition sum from 1.
PARTITION_SUM_TOLERANCE = 1e-9

_ASSUMPTION_FRACTION_FIELDS: tuple[str, ...] = (
    "gas_share",
    "ice_fleet_share",
    "travel_share",
    "cloud_share",
    "supplier_share",
    "other_share",
    "building_electricity_share",
    "building_gas_share",
    "building_max_reduction",
    "cloud_max_reduction",
    "supplier_max_reduction",
    "renewable_effectiveness",
    "ev_effectiveness",
    "travel_effectiveness",
)
_ASSUMPTION_NONNEGATIVE_FIELDS: tuple[str, ...] = (
    "ev_kwh_per_km",
    "grid_tco2e_per_kwh",
    "renewable_premium_gbp_per_kwh",
    "electricity_gbp_per_kwh",
    "gas_gbp_per_kwh",
    "ice_fuel_gbp_per_km",
    "travel_gbp_per_km",
    "cloud_gbp_per_hour",
    "supplier_monthly_savings_at_full_gbp",
)
ASSUMPTION_SCALAR_FIELDS: tuple[str, ...] = _ASSUMPTION_FRACTION_FIELDS + _ASSUMPTION_NONNEGATIVE_FIELDS


@dataclass(frozen=True, kw_only=True)
class ActionAssumptions:
    """Immutable, versioned deterministic action coefficients (ACTION_MODEL.md §2).

    Changing any value requires a new ``assumptions_id``/``version``: strategy identities
    depend on them. Renewable/EV/travel effectiveness default to 1.0 and are the P1
    uncertainty hooks (RISK_AND_BENCHMARK_SPEC.md §1).
    """

    assumptions_id: str
    version: str
    is_calibrated: bool
    description: str
    gas_share: float
    ice_fleet_share: float
    travel_share: float
    cloud_share: float
    supplier_share: float
    other_share: float
    building_electricity_share: float
    building_gas_share: float
    building_max_reduction: float
    cloud_max_reduction: float
    supplier_max_reduction: float
    renewable_effectiveness: float = 1.0
    ev_effectiveness: float = 1.0
    travel_effectiveness: float = 1.0
    ev_kwh_per_km: float
    grid_tco2e_per_kwh: float
    renewable_premium_gbp_per_kwh: float
    electricity_gbp_per_kwh: float
    gas_gbp_per_kwh: float
    ice_fuel_gbp_per_km: float
    travel_gbp_per_km: float
    cloud_gbp_per_hour: float
    supplier_monthly_savings_at_full_gbp: float
    costs: ActionCosts

    def __post_init__(self) -> None:
        require_str("assumptions.assumptions_id", self.assumptions_id)
        require_str("assumptions.version", self.version)
        _set(self, "is_calibrated", require_bool("assumptions.is_calibrated", self.is_calibrated))
        require_str("assumptions.description", self.description, allow_empty=True)
        for name in _ASSUMPTION_FRACTION_FIELDS:
            _set(self, name, require_unit_interval(f"assumptions.{name}", getattr(self, name)))
        for name in _ASSUMPTION_NONNEGATIVE_FIELDS:
            _set(self, name, require_nonnegative(f"assumptions.{name}", getattr(self, name)))
        scope1_sum = math.fsum((self.gas_share, self.ice_fleet_share))
        if abs(scope1_sum - 1.0) > PARTITION_SUM_TOLERANCE:
            raise ContractValidationError(
                "assumptions.gas_share",
                f"scope1 partition gas_share + ice_fleet_share must equal 1; got {scope1_sum!r}",
            )
        scope3_sum = math.fsum((self.travel_share, self.cloud_share, self.supplier_share, self.other_share))
        if abs(scope3_sum - 1.0) > PARTITION_SUM_TOLERANCE:
            raise ContractValidationError(
                "assumptions.travel_share",
                "scope3 partition travel_share + cloud_share + supplier_share + other_share "
                f"must equal 1; got {scope3_sum!r}",
            )
        if not isinstance(self.costs, ActionCosts):
            raise ContractValidationError("assumptions.costs", "must be an ActionCosts mapping of the six actions")


# ---------------------------------------------------------------------------
# Simulation and constraint results
# ---------------------------------------------------------------------------

_METRIC_FLOAT_FIELDS: tuple[str, ...] = (
    "baseline_total_co2e_tco2e",
    "total_co2e_tco2e",
    "co2_reduction_tco2e",
    "baseline_total_profit_gbp",
    "total_profit_gbp",
    "profit_change_gbp",
    "total_cost_gbp",
    "total_capex_gbp",
    "total_incremental_opex_gbp",
    "total_operating_savings_gbp",
    "net_cash_impact_gbp",
)
_METRIC_NULLABLE_FIELDS: tuple[str, ...] = ("co2_reduction_ratio", "profit_change_ratio")
METRIC_FIELDS: tuple[str, ...] = (
    "baseline_total_co2e_tco2e",
    "total_co2e_tco2e",
    "co2_reduction_tco2e",
    "co2_reduction_ratio",
    "baseline_total_profit_gbp",
    "total_profit_gbp",
    "profit_change_gbp",
    "profit_change_ratio",
    "total_cost_gbp",
    "total_capex_gbp",
    "total_incremental_opex_gbp",
    "total_operating_savings_gbp",
    "net_cash_impact_gbp",
)


@dataclass(frozen=True, kw_only=True)
class SimulationMetrics:
    """Horizon totals reconciled with the monthly frame (DATA_SCHEMAS.md §6).

    ``co2_reduction_ratio`` is ``None`` when baseline CO2e is zero; ``profit_change_ratio``
    is ``None`` when baseline profit is zero. Negative reductions/changes are legitimate.
    """

    baseline_total_co2e_tco2e: float
    total_co2e_tco2e: float
    co2_reduction_tco2e: float
    co2_reduction_ratio: float | None
    baseline_total_profit_gbp: float
    total_profit_gbp: float
    profit_change_gbp: float
    profit_change_ratio: float | None
    total_cost_gbp: float
    total_capex_gbp: float
    total_incremental_opex_gbp: float
    total_operating_savings_gbp: float
    net_cash_impact_gbp: float

    def __post_init__(self) -> None:
        for name in _METRIC_FLOAT_FIELDS:
            _set(self, name, require_finite(f"metrics.{name}", getattr(self, name)))
        for name in _METRIC_NULLABLE_FIELDS:
            value = getattr(self, name)
            if value is not None:
                _set(self, name, require_finite(f"metrics.{name}", value))


@dataclass(frozen=True, kw_only=True, eq=False)
class SimulationResult:
    """Deterministic outcome of one strategy: monthly frame plus reconciled metrics."""

    schema_version: str
    run_id: str
    provenance: Provenance
    baseline_id: str
    strategy_id: str
    config: ActionConfig
    monthly: pd.DataFrame
    metrics: SimulationMetrics


@dataclass(frozen=True, kw_only=True)
class RawViolations:
    """``max(0, raw violation)`` per constraint in its natural unit."""

    budget_gbp: float
    profit_gbp: float
    reduction_ratio: float

    def __post_init__(self) -> None:
        for name in ("budget_gbp", "profit_gbp", "reduction_ratio"):
            _set(self, name, require_nonnegative(f"raw_violations.{name}", getattr(self, name)))


@dataclass(frozen=True, kw_only=True)
class ConstraintSatisfaction:
    """Per-constraint pass/fail used by UI badges (additive field, contract 1.0.x)."""

    budget: bool
    profit: bool
    target: bool

    def __post_init__(self) -> None:
        for name in ("budget", "profit", "target"):
            _set(self, name, require_bool(f"satisfied.{name}", getattr(self, name)))


@dataclass(frozen=True, kw_only=True)
class ConstraintEvaluation:
    """Normalized solver constraints (feasible when <= tolerance) plus raw-boundary checks."""

    g_budget: float
    g_profit: float
    g_target: float
    feasible: bool
    raw_violations: RawViolations
    satisfied: ConstraintSatisfaction

    def __post_init__(self) -> None:
        for name in ("g_budget", "g_profit", "g_target"):
            _set(self, name, require_finite(f"constraint_evaluation.{name}", getattr(self, name)))
        _set(self, "feasible", require_bool("constraint_evaluation.feasible", self.feasible))


# ---------------------------------------------------------------------------
# Optimization, risk and recommendation results
# ---------------------------------------------------------------------------


@dataclass(frozen=True, kw_only=True, eq=False)
class OptimizationResult:
    """Constrained search result. ``candidates`` holds every unique evaluated strategy for
    audit; ``pareto`` holds feasible nondominated rows only; ``strategies`` maps every
    candidate ``strategy_id`` to its full SimulationResult. Treat members as read-only.
    """

    schema_version: str
    run_id: str
    provenance: Provenance
    status: OptimizationStatus
    baseline_id: str
    constraints: ConstraintConfig
    strategies: Mapping[str, SimulationResult]
    candidates: pd.DataFrame
    pareto: pd.DataFrame
    diagnostics: Mapping[str, Any]


RISK_SUMMARY_FIELDS: tuple[str, ...] = (
    "co2_mean_tco2e",
    "co2_p05_tco2e",
    "co2_p95_tco2e",
    "profit_mean_gbp",
    "profit_p05_gbp",
    "profit_p95_gbp",
    "cost_mean_gbp",
    "cost_p95_gbp",
    "target_probability",
    "profit_floor_probability",
    "budget_probability",
    "joint_feasibility_probability",
    "target_probability_mc_standard_error",
)
_RISK_PROBABILITY_FIELDS = (
    "target_probability",
    "profit_floor_probability",
    "budget_probability",
    "joint_feasibility_probability",
)
#: Only probabilities tied to an undefined reduction ratio may be null (DATA_SCHEMAS.md §9).
RISK_NULLABLE_FIELDS: tuple[str, ...] = (
    "target_probability",
    "joint_feasibility_probability",
    "target_probability_mc_standard_error",
)


@dataclass(frozen=True, kw_only=True)
class RiskSummary:
    """Empirical trial summary from WS3 (field names fixed by DATA_SCHEMAS.md §9)."""

    co2_mean_tco2e: float
    co2_p05_tco2e: float
    co2_p95_tco2e: float
    profit_mean_gbp: float
    profit_p05_gbp: float
    profit_p95_gbp: float
    cost_mean_gbp: float
    cost_p95_gbp: float
    target_probability: float | None
    profit_floor_probability: float
    budget_probability: float
    joint_feasibility_probability: float | None
    target_probability_mc_standard_error: float | None

    def __post_init__(self) -> None:
        for name in RISK_SUMMARY_FIELDS:
            value = getattr(self, name)
            path = f"risk.summary.{name}"
            if value is None:
                if name not in RISK_NULLABLE_FIELDS:
                    raise ContractValidationError(path, "must not be null")
                continue
            if name in _RISK_PROBABILITY_FIELDS:
                _set(self, name, require_unit_interval(path, value))
            elif name == "target_probability_mc_standard_error":
                _set(self, name, require_nonnegative(path, value))
            else:
                _set(self, name, require_finite(path, value))


@dataclass(frozen=True, kw_only=True, eq=False)
class RiskResult:
    """WS3 Monte Carlo result for one deterministic strategy (consumed by recommendation)."""

    schema_version: str
    run_id: str
    provenance: Provenance
    strategy_id: str
    baseline_id: str
    summary: RiskSummary
    n_simulations: int
    uncertainty_id: str
    samples: pd.DataFrame | None = None


@dataclass(frozen=True, kw_only=True)
class RecommendationResult:
    """Selected strategy (or ``None``) with the policy actually applied.

    ``diagnostics`` is an additive optional field carrying pool coverage, thresholds and
    shortfalls so the UI never needs to recompute selection logic.
    """

    schema_version: str
    run_id: str
    provenance: Provenance
    strategy_id: str | None
    policy: str
    tolerance: RiskTolerance
    score: float | None
    risk_status: RiskStatus
    reason: str
    diagnostics: Mapping[str, Any] = field(default_factory=dict)
