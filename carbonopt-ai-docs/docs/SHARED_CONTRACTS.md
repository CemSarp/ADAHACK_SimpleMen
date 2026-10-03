# Shared Contracts and Python Interfaces

Contract `1.0.0` is the integration authority. [DATA_SCHEMAS.md](DATA_SCHEMAS.md) defines storage/JSON fields; this document defines Python boundaries. Domain types live in `src/contracts/types.py`, protocols in `src/contracts/protocols.py`, validation in `src/contracts/validation.py`, and serialization in `src/contracts/serialization.py`.

## 1. Common rules

All public functions are synchronous Python calls. No public domain function reads Streamlit state, accesses a global random generator, silently changes units, or mutates input objects. Optional network and model work is explicit at its provider boundary. Inputs are validated before expensive work.

Python result types are dataclasses. Tabular members are Pandas DataFrames in memory and JSON record arrays on the wire. Configuration objects are frozen dataclasses; tuple/list order is documented. Dates serialize as ISO calendar dates, timestamps as UTC ISO strings, numbers as built-in Python int/float, and missing optional values as JSON `null`. NaN/Infinity are prohibited in JSON.

Every serialized result has `schema_version`, `run_id`, and `provenance`. Provenance includes `provider`, `is_mock`, `seed` (nullable), `input_hash`, `config_id`, and `assumptions_id` (nullable). A seed alone is insufficient for reproducibility: record data/configuration hashes and model version. Determinism excludes generated IDs and wall-clock metadata; compare numerical results and stable strategy IDs.

## 2. Core type definitions

Implement the complete fields from the schema document. The following public names and ownership are fixed:

~~~python
# src/contracts/types.py
# pd.DataFrame refers to the canonical schemas, never arbitrary columns.
from dataclasses import dataclass
from typing import Literal, Mapping, Protocol, Sequence
import pandas as pd

@dataclass(frozen=True)
class ActionConfig:
    renewable_energy: float
    ev_adoption: float
    building_efficiency: float
    travel_reduction: float
    cloud_efficiency: float
    supplier_transition: float

@dataclass(frozen=True)
class ConstraintConfig:
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

class SimulationFn(Protocol):
    def __call__(
        self, baseline: "BaselineBundle", config: ActionConfig, *,
        assumptions: "ActionAssumptions"
    ) -> "SimulationResult": ...
~~~

`BaselineBundle` contains a canonical `monthly` DataFrame and baseline metadata. `ActionAssumptions` contains action coefficients, bucket allocations, energy/emission factors, assumption ID and version; WS2 owns values. `UncertaintySpec` contains distributions and correlation metadata; WS3 owns values. All have JSON serializers and validators in contracts.

`SimulationResult` contains `strategy_id`, `config`, `monthly`, `metrics`, `baseline_id` and common metadata. `OptimizationResult` contains `status`, `baseline_id`, `constraints`, `strategies` (ID → SimulationResult), `candidates` and `pareto` DataFrames, `diagnostics` and metadata. Candidates contain all unique evaluated results retained for audit; Pareto contains feasible nondominated rows only.

`ConstraintEvaluation` contains float `g_budget`, `g_profit`, `g_target`, bool `feasible`, and `raw_violations` with `budget_gbp`, `profit_gbp`, `reduction_ratio` (each max(0, raw violation)). Thresholds and sign conventions are in ACTION_MODEL.md. Config objects serialize as plain field dictionaries inside versioned results; standalone config files are validated against the selected contract version.

`RiskResult` contains `strategy_id`, `baseline_id`, `summary`, `n_simulations`, `uncertainty_id`, optional `samples`, and metadata. `BenchmarkResult` contains its status, compatible peer statistics and provenance. `BacktestReport` and `ExplanationResult` have their structures defined in the schema document. `ModelBundle` contains target estimators, feature order, training cutoff, residual scope shares, driver policy, metadata and model ID; serialization stores metadata separately from trusted local model binaries.

## 3. Public signatures

### WS1 — data, forecasting, backtest, SHAP

~~~python
# src/data/generate.py
def generate_company_timeseries(
    *, company_id: str, start: str, periods: int, seed: int,
    config: DataGenerationConfig
) -> pd.DataFrame: ...

# src/data/features.py
def build_supervised_dataset(
    history: pd.DataFrame, *, feature_spec: FeatureSpec
) -> SupervisedDataset: ...

# src/forecasting/train.py
def train_models(
    history: pd.DataFrame, *, feature_spec: FeatureSpec,
    config: TrainingConfig, seed: int
) -> ModelBundle: ...

# src/data/drivers.py
def project_future_drivers(
    history: pd.DataFrame, *, horizon_months: int,
    policy: DriverPolicy
) -> pd.DataFrame: ...

# src/forecasting/predict.py
def forecast_baseline(
    history: pd.DataFrame, models: ModelBundle, *,
    horizon_months: int, future_drivers: pd.DataFrame
) -> BaselineBundle: ...

# src/forecasting/backtest.py
def backtest_models(
    history: pd.DataFrame, *, feature_spec: FeatureSpec,
    training_config: TrainingConfig, config: BacktestConfig,
    driver_policy: DriverPolicy, seed: int
) -> BacktestReport: ...

# src/explainability/shap_analysis.py
def explain_forecast(
    models: ModelBundle, baseline: BaselineBundle, *,
    history: pd.DataFrame, max_rows: int = 12
) -> ExplanationResult: ...
~~~

Config field specifications are in [FORECASTING_SPEC.md](FORECASTING_SPEC.md). `future_drivers` excludes emission/profit targets and has exact dates matching the forecast horizon. WS1 generates it; other workstreams consume the completed baseline.

### WS2 — simulation and optimization

~~~python
# src/actions/engine.py
def simulate_strategy(
    baseline: BaselineBundle, config: ActionConfig, *,
    assumptions: ActionAssumptions
) -> SimulationResult: ...

# src/optimization/constraints.py
def evaluate_constraints(
    result: SimulationResult, constraints: ConstraintConfig
) -> ConstraintEvaluation: ...

# src/optimization/optimizer.py
def optimize_strategies(
    baseline: BaselineBundle, constraints: ConstraintConfig, *,
    assumptions: ActionAssumptions, config: OptimizerConfig,
    simulator: SimulationFn
) -> OptimizationResult: ...

# src/optimization/pareto.py
def compute_pareto_frontier(candidates: pd.DataFrame) -> pd.DataFrame: ...

# src/optimization/recommendation.py
def recommend_strategy(
    optimization: OptimizationResult, *,
    risk_results: Mapping[str, RiskResult] | None = None,
    tolerance: Literal["conservative", "balanced", "aggressive"] = "balanced"
) -> RecommendationResult: ...
~~~

Optimizer injection allows WS2 to test on a toy problem; production binds the shared simulator. Constraints are evaluated by the same function in search, manual what-if, and UI badges. Recommendation chooses from validated feasible strategies, never manufactures a config between Pareto points.

### WS3 — risk and benchmarking

~~~python
# src/risk/monte_carlo.py
def evaluate_strategy_risk(
    baseline: BaselineBundle, action_config: ActionConfig, *,
    constraints: ConstraintConfig, assumptions: ActionAssumptions,
    uncertainty: UncertaintySpec, config: RiskConfig,
    simulator: SimulationFn
) -> RiskResult: ...

# src/benchmarking/adapters.py
def load_benchmark_data(
    *, source: BenchmarkSource, timeout_seconds: float = 5.0,
    offline: bool = False
) -> BenchmarkDataset: ...

# src/benchmarking/benchmark.py
def benchmark_company(
    baseline: BaselineBundle, peers: BenchmarkDataset, *,
    config: BenchmarkConfig
) -> BenchmarkResult: ...
~~~

External adapters normalize data before it reaches `benchmark_company`. Benchmarking runs on the baseline 12-month totals, never reads forecast model artifacts, and cannot alter prediction or optimizer state.

### WS4 — orchestration and optional explanation

~~~python
# src/integration/services.py
def create_services(
    *, mode: Literal["mock", "real", "hybrid"],
    provider_overrides: Mapping[str, object] | None = None
) -> Services: ...

# src/integration/pipeline.py
def run_analysis(
    request: AnalysisRequest, *, services: Services
) -> AnalysisBundle: ...

# src/llm/assistant.py
def explain_analysis(
    analysis: AnalysisBundle, *, provider: ExplanationProvider | None
) -> NarrativeResult: ...

# src/llm/tools.py
def execute_tool(
    name: str, arguments: dict, *,
    context: AnalysisContext, services: Services
) -> ToolResult: ...
~~~

`AnalysisRequest` fields: company ID, horizon, constraints, optimizer config, risk enabled, risk config, tolerance, benchmark enabled, explanation enabled. `AnalysisBundle` fields: baseline, backtest report, optimization, recommendation, optional risk results, optional SHAP/benchmark, warnings, common metadata. Manual what-if calls the simulator directly through services; it does not rerun training or optimization.

Services contains forecast, simulator, optimizer, risk, benchmark, SHAP and narrative providers plus capability flags. Optional capability absence yields a disabled panel, not an import error in P0.

Capabilities include `supported_horizons`, `risk_available`, `shap_available_targets`, `benchmark_available`, `narrative_available` and per-provider `is_mock`. Forecast provider binds the trusted model/history/driver policy but returns the public BaselineBundle. Shared consumer code never loads a model artifact directly.

### Chatbot additions (contract 1.x, additive; require producer/consumer review)

`ToolResult(status, tool_name, validated_arguments, data, error)` and `NarrativeResult(status, text, source_run_id, provider, is_template)` are defined in `src/contracts/types.py` with the fields listed in the Tool/Narrative paragraph of DATA_SCHEMAS.md. `status` for tools is `ok`, `error` or `unavailable`; `data` is a plain JSON-safe mapping built from serialized public results. The model-provider boundary (`ChatModelProvider`: `chat(messages, tools) -> ModelResponse`, `check_connection()`) lives in `src/llm/providers.py`, not in contracts, because it is WS4-internal. `execute_tool(name, arguments, *, context, services)` binds `AnalysisContext` on the server side; `explain_analysis(analysis, *, provider=None)` has a deterministic template implementation. No existing field changed. See [docs/CHATBOT_IMPLEMENTATION.md](../../docs/CHATBOT_IMPLEMENTATION.md). Review status: not reviewed by WS1-WS3.

## 4. Errors and status results

| Condition | Defined behavior |
|---|---|
| Invalid column/type/range/unit/config | `ContractValidationError` with field and reason |
| Unsupported 36/60-month P0 request | `UnsupportedHorizon` before computation |
| Invalid/leaking feature configuration | `ForecastConfigurationError` |
| Failed model training/prediction | `ForecastError`; no silent mock substitution |
| No feasible optimization candidate | `OptimizationResult(status="infeasible")`, empty Pareto, diagnostics |
| Unexpected solver failure | `OptimizationError`; visible UI error and retry |
| Zero baseline CO₂ with positive reduction target | `ContractValidationError`: ratio target undefined |
| No compatible or too few benchmark peers | `BenchmarkResult(status="unavailable")` with reason |
| Network timeout/API failure | Explicit cached snapshot status or `BenchmarkResult(status="unavailable")` |
| Missing optional dependency | Provider advertises unavailable capability |
| Invalid or unavailable chatbot tool | `ToolResult(status="error")`; no invocation |

Catch only defined boundary failures in orchestration. Unexpected programming errors surface to logs/tests; do not relabel them as valid business results. Logs include request IDs and relative artifact IDs, not secrets.

## 5. Dependency and schema-change policy

Public consumers import types/protocols from `src.contracts`. Domain producers may use helpers within their own module but cannot require consumers to import private estimators, solver objects, HTTP responses, or notebook state.

Shared JSON schemas, serializers, and fixture transformations are written once under contract stewardship. Unknown required enums and missing fields fail early. P0 tolerates documented additive optional fields within version 1, rejects unsupported major versions, and never silently interprets a 0–100 percentage as a 0–1 fraction.
