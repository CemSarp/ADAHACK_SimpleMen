"""Public contract types, version 1.0.0.

Field names, units and semantics follow docs/DATA_SCHEMAS.md and
docs/SHARED_CONTRACTS.md (currently under carbonopt-ai-docs/). Frames refer to
canonical schemas, never arbitrary columns. Result objects never compute domain
outcomes; they only carry them.
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from datetime import date
from typing import Any, Literal, Mapping

import pandas as pd

SCHEMA_VERSION = "1.0.0"
SUPPORTED_SCHEMA_MAJOR = 1

# Fixed optimizer vector order (DATA_SCHEMAS.md section 5).
ACTION_NAMES: tuple[str, ...] = (
    "renewable_energy",
    "ev_adoption",
    "building_efficiency",
    "travel_reduction",
    "cloud_efficiency",
    "supplier_transition",
)

# Company history / baseline monthly schema, in CSV export order.
HISTORY_COLUMNS: tuple[str, ...] = (
    "company_id",
    "timestamp",
    "revenue_gbp",
    "operating_profit_gbp",
    "employees",
    "electricity_kwh",
    "gas_kwh",
    "renewable_energy_share",
    "ev_share",
    "fleet_size",
    "fleet_km",
    "business_travel_km",
    "cloud_compute_hours",
    "scope1_tco2e",
    "scope2_tco2e",
    "scope3_tco2e",
    "total_co2e_tco2e",
)
HISTORY_INT_COLUMNS: tuple[str, ...] = ("employees", "fleet_size")
HISTORY_FLOAT_COLUMNS: tuple[str, ...] = tuple(
    c for c in HISTORY_COLUMNS if c not in ("company_id", "timestamp", *HISTORY_INT_COLUMNS)
)
SCOPE_COLUMNS: tuple[str, ...] = ("scope1_tco2e", "scope2_tco2e", "scope3_tco2e")

SIMULATION_MONTHLY_COLUMNS: tuple[str, ...] = (
    "timestamp",
    "revenue_gbp",
    "operating_profit_gbp",
    "scope1_tco2e",
    "scope2_tco2e",
    "scope3_tco2e",
    "total_co2e_tco2e",
    "capex_gbp",
    "incremental_opex_gbp",
    "operating_savings_gbp",
    "depreciation_gbp",
    "budget_cost_gbp",
    "net_cash_impact_gbp",
)
SIMULATION_METRIC_FIELDS: tuple[str, ...] = (
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
NULLABLE_METRIC_FIELDS: tuple[str, ...] = ("co2_reduction_ratio", "profit_change_ratio")

OPTIMIZATION_TABLE_COLUMNS: tuple[str, ...] = (
    "strategy_id",
    *ACTION_NAMES,
    "total_co2e_tco2e",
    "total_profit_gbp",
    "total_cost_gbp",
    "co2_reduction_ratio",
    "g_budget",
    "g_profit",
    "g_target",
    "feasible",
    "pareto_rank",
)
OPTIMIZATION_STATUSES: tuple[str, ...] = ("ok", "infeasible")

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
RISK_SAMPLE_COLUMNS: tuple[str, ...] = (
    "trial_id",
    "total_co2e_tco2e",
    "total_profit_gbp",
    "total_cost_gbp",
    "target_met",
    "profit_met",
    "budget_met",
)
RISK_STATUSES: tuple[str, ...] = (
    "not_requested",
    "unavailable",
    "partial",
    "evaluated",
    "threshold_unmet",
)
TOLERANCES: tuple[str, ...] = ("conservative", "balanced", "aggressive")

FORECAST_TARGETS: tuple[str, ...] = ("total_co2e_tco2e", "operating_profit_gbp")
BACKTEST_FOLD_COLUMNS: tuple[str, ...] = (
    "fold_id",
    "train_cutoff",
    "test_start",
    "test_end",
    "target",
    "mae",
    "rmse",
    "r2",
    "naive_mae",
    "naive_rmse",
    "effective_train_size",
    "adjustment_count",
)
BACKTEST_OOF_COLUMNS: tuple[str, ...] = (
    "fold_id",
    "timestamp",
    "target",
    "actual",
    "predicted",
    "naive_predicted",
)
BACKTEST_AGGREGATE_FIELDS: tuple[str, ...] = ("mae", "rmse", "r2", "naive_mae", "naive_rmse")
SHAP_COLUMNS: tuple[str, ...] = (
    "timestamp",
    "target",
    "feature",
    "feature_value",
    "shap_value",
    "base_value",
    "model_prediction",
)
BENCHMARK_STATUSES: tuple[str, ...] = ("ok", "unavailable")

ProviderMode = Literal["mock", "real", "hybrid"]
Tolerance = Literal["conservative", "balanced", "aggressive"]


# --------------------------------------------------------------------------- #
# Metadata
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Provenance:
    provider: str
    is_mock: bool
    seed: int | None
    input_hash: str
    config_id: str
    assumptions_id: str | None


# --------------------------------------------------------------------------- #
# Configuration objects
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class ActionConfig:
    """Fractions of remaining eligible opportunity, implemented at month 1."""

    renewable_energy: float
    ev_adoption: float
    building_efficiency: float
    travel_reduction: float
    cloud_efficiency: float
    supplier_transition: float

    def as_dict(self) -> dict[str, float]:
        return {name: float(getattr(self, name)) for name in ACTION_NAMES}

    def as_vector(self) -> tuple[float, ...]:
        return tuple(float(getattr(self, name)) for name in ACTION_NAMES)

    @classmethod
    def from_mapping(cls, values: Mapping[str, Any]) -> "ActionConfig":
        return cls(**{name: values[name] for name in ACTION_NAMES})

    @classmethod
    def noop(cls) -> "ActionConfig":
        return cls(**{name: 0.0 for name in ACTION_NAMES})


@dataclass(frozen=True)
class ConstraintConfig:
    """Horizon totals: gross outlay budget, cumulative profit floor, CO2 target ratio."""

    budget_gbp: float
    min_total_profit_gbp: float
    min_co2_reduction_ratio: float


@dataclass(frozen=True)
class OptimizerConfig:
    seed: int = 42
    population_size: int = 64
    generations: int = 32
    max_evaluations: int = 2048


@dataclass(frozen=True)
class RiskConfig:
    seed: int = 42
    n_simulations: int = 1000
    retain_samples: bool = False


@dataclass(frozen=True)
class ActionCost:
    capex_at_full_gbp: float
    monthly_opex_at_full_gbp: float
    asset_life_months: int


@dataclass(frozen=True)
class ActionAssumptions:
    """Versioned deterministic action parameters. WS2 owns the values."""

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
    renewable_effectiveness: float
    ev_effectiveness: float
    travel_effectiveness: float
    ev_kwh_per_km: float
    grid_tco2e_per_kwh: float
    renewable_premium_gbp_per_kwh: float
    electricity_gbp_per_kwh: float
    gas_gbp_per_kwh: float
    ice_fuel_gbp_per_km: float
    travel_gbp_per_km: float
    cloud_gbp_per_hour: float
    supplier_monthly_savings_at_full_gbp: float
    costs: Mapping[str, ActionCost]


ASSUMPTION_SCALAR_FIELDS: tuple[str, ...] = tuple(
    f.name
    for f in fields(ActionAssumptions)
    if f.name not in ("assumptions_id", "version", "is_calibrated", "description", "costs")
)


# --------------------------------------------------------------------------- #
# Domain results (frames make these unhashable; eq=False avoids frame __eq__)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, eq=False)
class BaselineBundle:
    schema_version: str
    run_id: str
    provenance: Provenance
    baseline_id: str
    company_id: str
    history_end: date
    horizon_months: int
    model_id: str
    driver_policy_id: str
    data_kind: str
    scope2_method: str
    currency: str
    monthly: pd.DataFrame
    totals: Mapping[str, float]


@dataclass(frozen=True, eq=False)
class SimulationResult:
    schema_version: str
    run_id: str
    provenance: Provenance
    baseline_id: str
    strategy_id: str
    config: ActionConfig
    monthly: pd.DataFrame
    metrics: Mapping[str, float | None]


@dataclass(frozen=True)
class ConstraintEvaluation:
    """Normalized constraints (feasible when g <= 1e-8) plus raw-boundary checks.

    `satisfied` is an additive optional field (contract 1.x): per-constraint pass/fail
    keyed `budget`, `profit`, `target`, combining the normalized and raw tests exactly
    as `feasible` does, so UI badges never re-derive feasibility. Empty when a
    provider does not supply it.
    """

    g_budget: float
    g_profit: float
    g_target: float
    feasible: bool
    raw_violations: Mapping[str, float]
    satisfied: Mapping[str, bool] = field(default_factory=dict)


@dataclass(frozen=True, eq=False)
class OptimizationResult:
    schema_version: str
    run_id: str
    provenance: Provenance
    baseline_id: str
    status: str
    constraints: ConstraintConfig
    strategies: Mapping[str, SimulationResult]
    candidates: pd.DataFrame
    pareto: pd.DataFrame
    diagnostics: Mapping[str, Any]


@dataclass(frozen=True)
class RecommendationResult:
    """`diagnostics` is an additive optional field (contract 1.x) carrying the
    selection pool, risk coverage, thresholds and shortfalls behind the choice."""

    schema_version: str
    run_id: str
    provenance: Provenance
    strategy_id: str | None
    policy: str
    tolerance: str
    score: float | None
    risk_status: str
    reason: str | None
    diagnostics: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, eq=False)
class RiskResult:
    schema_version: str
    run_id: str
    provenance: Provenance
    baseline_id: str
    strategy_id: str
    n_simulations: int
    uncertainty_id: str
    summary: Mapping[str, float | None]
    samples: pd.DataFrame | None = None


@dataclass(frozen=True)
class BenchmarkResult:
    schema_version: str
    run_id: str
    provenance: Provenance
    status: str
    company_intensity_tco2e_per_million_gbp: float | None
    industry_median: float | None
    percentile: float | None
    better_than_pct: float | None
    peer_count: int
    source_id: str | None
    source_url: str | None
    retrieved_at: str | None
    snapshot_id: str | None
    is_synthetic: bool
    period_start: str | None
    period_end: str | None
    scope_coverage: str | None
    scope2_method: str | None
    comparison_basis: str | None
    reason: str | None


@dataclass(frozen=True, eq=False)
class BacktestReport:
    """Temporal evaluation. Fold field names `test_start`/`test_end` and
    `selected_models` await WS1 review (see WS4 handoff)."""

    schema_version: str
    run_id: str
    provenance: Provenance
    model_family: str
    feature_spec_id: str
    driver_policy_id: str
    folds: pd.DataFrame
    aggregate_metrics: Mapping[str, Mapping[str, float | None]]
    oof_predictions: pd.DataFrame
    selected_models: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True, eq=False)
class ExplanationResult:
    """Forecast SHAP contributions in raw model output space."""

    schema_version: str
    run_id: str
    provenance: Provenance
    model_id: str
    baseline_id: str
    driver_policy_id: str
    output_space: str
    units: Mapping[str, str]
    explained_rows: int
    contributions: pd.DataFrame


# --------------------------------------------------------------------------- #
# Orchestration objects (WS4)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class ProviderInfo:
    """Identity of a bound provider. `kind` is one of fixture, behavioral-mock,
    real or custom; `version` must change whenever outputs can change."""

    slot: str
    name: str
    version: str
    is_mock: bool
    kind: str


@dataclass(frozen=True)
class Capabilities:
    supported_horizons: tuple[int, ...]
    risk_available: bool
    shap_available_targets: tuple[str, ...]
    benchmark_available: bool
    narrative_available: bool
    scenario_compare_available: bool
    is_mock: Mapping[str, bool]


@dataclass(frozen=True)
class AnalysisRequest:
    company_id: str
    horizon_months: int
    constraints: ConstraintConfig
    optimizer_config: OptimizerConfig = OptimizerConfig()
    risk_enabled: bool = False
    risk_config: RiskConfig = RiskConfig()
    tolerance: Tolerance = "balanced"
    benchmark_enabled: bool = False
    explanation_enabled: bool = False


@dataclass(frozen=True, eq=False)
class AnalysisBundle:
    """End-to-end result. `request` and `providers` are additive optional
    fields (contract 1.x) that make provenance auditable per provider."""

    schema_version: str
    run_id: str
    provenance: Provenance
    baseline: BaselineBundle
    backtest: BacktestReport | None
    optimization: OptimizationResult
    recommendation: RecommendationResult
    risk_results: Mapping[str, RiskResult]
    explanation: ExplanationResult | None
    benchmark: BenchmarkResult | None
    warnings: tuple[str, ...]
    request: AnalysisRequest | None = None
    providers: Mapping[str, ProviderInfo] = field(default_factory=dict)
