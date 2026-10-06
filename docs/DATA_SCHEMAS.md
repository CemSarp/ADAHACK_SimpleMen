# Canonical Data and JSON Schemas

All contracts use version `1.0.0`. This document is authoritative for field names, units, nullability and aggregation. No external API payload or legacy column name may bypass normalization.

## 1. Universal conventions

| Concept | Representation |
|---|---|
| Company/strategy/model IDs | Nonempty strings; company IDs are not usernames |
| Month | ISO `YYYY-MM-01`; unique ascending month starts |
| DataFrame dates | `datetime64[ns]`, timezone-naive calendar month starts |
| Emissions | Tonnes CO₂e, suffix `_tco2e` |
| Money | GBP, suffix `_gbp`; monthly flows unless labelled total |
| Energy/activity | kWh, km, compute hours; suffix gives unit |
| Fractions | Float in [0, 1], suffix `_share` or `_ratio` |
| Percent display | UI alone converts ratio × 100 |
| Numeric types | float64 for continuous columns; int64 for counts |
| Missing values | No missing required domain values; nullable derived ratios only |
| Schema validation | Date continuity, one company, ranges, finiteness, identities |

Relative tolerance for scope/total numerical identities is `1e-8` with absolute tolerance `1e-6` tonnes. Currency reconciliation uses absolute tolerance `0.01` GBP. Constraint epsilon is documented separately and is not permission to exceed budget materially.

Monthly revenue/profit/emissions are flows and sum across months. Employees/fleet/renewable share/EV share are states and never sum. Annualized figures must carry their period and must not be stored in monthly flow columns.

## 2. Company history DataFrame

One row per company-month for one company, at least 24 months. The demo company (`data/synthetic_data.csv`) has 300 synthetic months (January 2001–December 2025); an uploaded table has whatever months it reports. Do not imply a synthetic month is a reported observation.

| Column | Type | Rule / meaning |
|---|---|---|
| `company_id` | string | Same nonempty ID for all rows |
| `timestamp` | datetime | Monthly key |
| `revenue_gbp` | float | > 0, monthly revenue |
| `operating_profit_gbp` | float | Finite; losses permitted |
| `employees` | int | ≥ 0 |
| `electricity_kwh` | float | ≥ 0, includes existing electric vehicles |
| `gas_kwh` | float | ≥ 0 |
| `renewable_energy_share` | float | [0,1], baseline supply share |
| `ev_share` | float | [0,1], baseline electric fleet share |
| `fleet_size` | int | ≥ 0 |
| `fleet_km` | float | ≥ 0, all fleet km |
| `business_travel_km` | float | ≥ 0 |
| `cloud_compute_hours` | float | ≥ 0 |
| `scope1_tco2e` | float | ≥ 0 |
| `scope2_tco2e` | float | ≥ 0; chosen accounting method |
| `scope3_tco2e` | float | ≥ 0 |
| `total_co2e_tco2e` | float | Exact sum of three scopes within tolerance |

Required history columns are those listed above, in this order for CSV exports. Inputs validate by name, not positional order. Any other names or units (`renewable_energy_pct`, `Net Sales (USD)`, `total_co2e`) enter only through the import adapter below, which converts units, renames fields and records every change.

### 2a. Import configuration

`src/forecasting/history.py` turns a raw monthly table into this history using an import configuration. The demo company's is `config/company_import.json`; for uploads the dashboard builds one from the columns the user confirms (`src/forecasting/mapping.py`, `import_mapping`).

~~~json
{
  "import_id": "upload-acme-manufacturing",
  "version": "1.0.0",
  "company_id": "acme-manufacturing",
  "date_column": "Month",
  "currency": {"source": "USD", "target": "GBP", "gbp_per_unit": 0.79, "fx_note": "(user-entered rate)"},
  "columns": {
    "revenue_gbp": {"from": "Net Sales (USD)", "convert": "to_gbp"},
    "operating_profit_gbp": {"revenue_minus": "Operating Expenses (USD)", "convert": "to_gbp"},
    "scope1_tco2e": {"from": "Scope 1 (tCO2e)"},
    "scope2_tco2e": {"from": "Scope 2 market-based (tCO2e)"},
    "electricity_kwh": {"from": "Electricity kWh"},
    "renewable_energy_share": {"from": "Renewable %"}
  },
  "scope2_method": "market_based"
}
~~~

| Field | Meaning |
|---|---|
| `columns.<history column>.from` | Source column for that history field |
| `columns.<money field>.convert` | `to_gbp` multiplies by `currency.gbp_per_unit` (`eur_to_gbp` with `gbp_per_eur` is the legacy form) |
| `columns.operating_profit_gbp.revenue_minus` | Derives profit as revenue minus this cost column |
| `not_reported` | Optional reasons for fields the data lacks; they are stored as 0 and listed |

Required: a date column, revenue, profit (or `revenue_minus`), and emissions (a total, any scopes, or both).

Import steps, each recorded in `ImportedHistory.transforms` and shown on the page:

1. Dates are parsed in any common format and reduced to month starts; rows are sorted. A month appearing twice or an unreadable date is rejected.
2. Mapped columns are coerced to numbers; a column with no numbers is rejected. Missing months and empty cells are interpolated from neighbouring months. Fewer than 24 months is rejected.
3. Money is converted to GBP; shares above 1 are read as percentages and divided by 100.
4. Emissions: with only scopes, the total is their sum (unreported scopes are 0); with a total, unreported scopes take the remainder (Scope 3 first, or all of it as unclassified Scope 3 when no scope is given). A total below the reported scopes is rejected; the identity `total = scope1 + scope2 + scope3` is then checked.
5. Unreported history fields are 0 with a reason. Missing electricity is estimated from Scope 2 at 0.207 kgCO₂e/kWh (adjusted for the renewable share). 100% renewable supply in a month with Scope 2 emissions is rejected (market-based assumption).
6. The result is validated as the history frame above.

P0 monthly effective scope2 emissions must be zero when renewable share is 1 under the demonstration assumption; real datasets with nonzero renewable life-cycle factors need a new calibrated assumption/model definition. Positive fleet allocation with `fleet_km=0`, positive gas allocation with `gas_kwh=0`, and positive electricity emissions with `electricity_kwh=0` are invalid inputs for the simulator.

`data/provenance.json` records the demo data's kind (`synthetic`/`reported`/`interpolated`), source description, reporting frequency, accounting scope/method, generator config ID, seed, units, and transforms; uploads are `reported` and carry their file checksum and transforms. Raw yearly reported data must not be described as independent monthly observations after interpolation.

## 3. Feature training objects and future drivers

`SupervisedDataset` contains `X` (finite numeric features), `y` (columns `total_co2e_tco2e` and `operating_profit_gbp`), `target_timestamps`, `feature_names`, and `feature_spec_id`. Rows removed by lag warm-up are recorded.

Future driver frame columns are the history columns except the four emissions columns and `operating_profit_gbp`. Required keys are company/date. Activity projections are explicit inputs. Future emissions or profit values are prohibited in the driver frame; [FORECASTING_SPEC.md](FORECASTING_SPEC.md) defines the supervised indexing and recursion.

## 4. BaselineBundle

The baseline monthly frame has exactly the history schema and forecast dates. Predicted total emissions are reconciled to three nonnegative scope shares. Activity/currency fields use the disclosed future driver policy. The simulator can always obtain all scopes and activities without importing ML internals.

~~~json
{
  "schema_version": "1.0.0",
  "run_id": "example-baseline-run",
  "provenance": {
    "provider": "fixture",
    "is_mock": true,
    "seed": 42,
    "input_hash": "fixture-v1",
    "config_id": "demo-v1",
    "assumptions_id": null
  },
  "baseline_id": "baseline-demo-v1",
  "company_id": "demo-company",
  "history_end": "2026-12-01",
  "horizon_months": 12,
  "model_id": "fixture-model-v1",
  "driver_policy_id": "flat-demo-v1",
  "data_kind": "synthetic",
  "scope2_method": "market_based_demo",
  "currency": "GBP",
  "monthly": [],
  "totals": {
    "revenue_gbp": 12000000.0,
    "operating_profit_gbp": 1200000.0,
    "total_co2e_tco2e": 1200.0
  }
}
~~~

The empty `monthly` above is structural shorthand, not a valid complete baseline. [The baseline example](../tests/fixtures/v1/baseline_12m.json) provides all 12 rows. The full object must have exactly `horizon_months` contiguous rows starting one month after `history_end`, one company, and totals equal to sums.

## 5. Action and constraint configuration

All six action values are required, in the optimizer vector order below. A value is the fraction of remaining eligible opportunity implemented at month 1 and held throughout the horizon.

~~~json
{
  "renewable_energy": 0.7,
  "ev_adoption": 0.4,
  "building_efficiency": 0.2,
  "travel_reduction": 0.3,
  "cloud_efficiency": 0.25,
  "supplier_transition": 0.1
}
~~~

Example: baseline renewable share 0.2 and action 0.7 gives `0.2 + (1-0.2)*0.7 = 0.76`. It does not mean a 70% final renewable target. Display both implementation fraction and final share.

~~~json
{
  "budget_gbp": 500000.0,
  "min_total_profit_gbp": 1000000.0,
  "min_co2_reduction_ratio": 0.2
}
~~~

Budget is the entire horizon's gross implementation cash outlay defined in [ACTION_MODEL.md](ACTION_MODEL.md). Profit threshold is cumulative horizon operating profit, never an annual threshold applied to a multi-year sum. Target compares strategy horizon emissions with baseline horizon emissions.

## 6. SimulationResult

Top-level fields: common metadata, `baseline_id`, `strategy_id`, normalized `config`, `monthly`, `metrics`. Strategy ID hashes baseline ID, full-precision validated config, and assumption ID/version using canonical sorted JSON; retain actual values. Do not round configs for identity, feasibility or evaluation.

Monthly columns:

| Field | Meaning |
|---|---|
| `timestamp` | Baseline dates, same order |
| `revenue_gbp` | Baseline revenue, unchanged in P0 |
| `operating_profit_gbp` | Scenario operating profit |
| `scope1_tco2e`, `scope2_tco2e`, `scope3_tco2e` | Scenario scopes |
| `total_co2e_tco2e` | Sum of scenario scopes |
| `capex_gbp` | Month-1 implementation capex; zero thereafter |
| `incremental_opex_gbp` | New monthly operating costs, ≥ 0 |
| `operating_savings_gbp` | Avoided monthly costs, ≥ 0 |
| `depreciation_gbp` | Straight-line monthly charge during asset life |
| `budget_cost_gbp` | Capex + incremental opex; savings excluded |
| `net_cash_impact_gbp` | Savings − incremental opex − capex |

Metrics:

~~~json
{
  "baseline_total_co2e_tco2e": 1200.0,
  "total_co2e_tco2e": 1200.0,
  "co2_reduction_tco2e": 0.0,
  "co2_reduction_ratio": 0.0,
  "baseline_total_profit_gbp": 1200000.0,
  "total_profit_gbp": 1200000.0,
  "profit_change_gbp": 0.0,
  "profit_change_ratio": 0.0,
  "total_cost_gbp": 0.0,
  "total_capex_gbp": 0.0,
  "total_incremental_opex_gbp": 0.0,
  "total_operating_savings_gbp": 0.0,
  "net_cash_impact_gbp": 0.0
}
~~~

`co2_reduction_ratio = reduction / baseline_co2`; nullable when baseline is zero. `profit_change_ratio = change / abs(baseline_profit)`; nullable when baseline profit is zero. Negative reduction and negative profit changes are allowed. No risk value appears in deterministic metrics; risk is an optional separate result, never a fake `0`.

## 7. Optimization and Pareto tables

Candidates and Pareto use the same schema:

| Column | Type / semantics |
|---|---|
| `strategy_id` | string, joins `strategies` map |
| Six action columns | float, exact config values |
| `total_co2e_tco2e` | float, minimized |
| `total_profit_gbp` | float, maximized |
| `total_cost_gbp` | float, gross outlay |
| `co2_reduction_ratio` | float or nullable if baseline zero |
| `g_budget`, `g_profit`, `g_target` | Dimensionless constraint values; ≤ tolerance feasible |
| `feasible` | bool |
| `pareto_rank` | int; 0 for feasible nondominated points, −1 for infeasible; the WS2 optimizer uses 1 for feasible but dominated candidates (pending review) |

Empty frames retain columns and dtypes. `status="ok"` requires at least one feasible Pareto point. `status="infeasible"` has an empty Pareto and a null recommendation. This means no feasible candidate was found within the search budget, not a mathematical proof of global infeasibility.

Diagnostics include evaluated/unique counts, seed, runtime, termination reason, normalized violation minima, and the tested no-op result. A fixed strategy map preserves provenance and monthly outcomes; do not reconstruct outcomes from rounded UI rows.

## 8. BacktestReport and ExplanationResult

Backtest report fields: common metadata, model family, feature spec ID, driver policy ID, fold records, aggregate metrics, and out-of-fold predictions. Each fold records train cutoff, test dates, target, MAE, RMSE, nullable R², seasonal-naive MAE/RMSE, effective train size, and clipping/reconciliation count.

Out-of-fold prediction columns: `fold_id`, `timestamp`, `target`, `actual`, `predicted`, `naive_predicted`. Aggregate metrics are computed from pooled out-of-fold residuals, not an unweighted mean of fold RMSE. R² is null for constant/insufficient actuals.

SHAP explanation columns: `timestamp`, `target`, `feature`, `feature_value`, `shap_value`, `base_value`, `model_prediction`. Metadata declares units (tonnes or GBP), target, model ID, explained rows, recursive driver policy, and `output_space="raw_model"`. SHAP contributions sum to the raw model prediction within library numerical tolerance, not to a post-clipping/reconciled result. Record the displayed prediction and adjustment separately when different.

## 9. Risk, benchmark, recommendation and narrative objects

Risk summary fields: `co2_mean_tco2e`, `co2_p05_tco2e`, `co2_p95_tco2e`, `profit_mean_gbp`, `profit_p05_gbp`, `profit_p95_gbp`, `cost_mean_gbp`, `cost_p95_gbp`, `target_probability`, `profit_floor_probability`, `budget_probability`, `joint_feasibility_probability`, and `target_probability_mc_standard_error`. Quantile levels are empirical; p05/p95 is a 90% trial outcome interval, not a confidence interval on the mean.

Optional risk samples columns: `trial_id`, `total_co2e_tco2e`, `total_profit_gbp`, `total_cost_gbp`, `target_met`, `profit_met`, `budget_met`. Trial flags use raw constraint boundaries. Nullable summary probabilities are only permitted for undefined ratios; no zero-filled errors. `target_probability_mc_standard_error` is null exactly when `target_probability` is null.

Benchmark peer columns and result semantics are defined in [RISK_AND_BENCHMARK_SPEC.md](RISK_AND_BENCHMARK_SPEC.md). Result status is `ok` or `unavailable`. Benchmark fields are `company_intensity_tco2e_per_million_gbp`, `industry_median`, `percentile`, `better_than_pct`, `peer_count`, `source_id`, `source_url` (nullable), `retrieved_at`, `snapshot_id`, `is_synthetic`, `period_start`, `period_end`, `scope_coverage`, `scope2_method`, `comparison_basis`, and `reason` (nullable).

Recommendation fields: nullable `strategy_id`, `policy`, `tolerance`, `score`, `risk_status`, and `reason`, plus the additive optional `diagnostics` object (selection pool, risk coverage, thresholds and shortfall; pending review). Unavailable risk produces `risk_status="unavailable"` and the deterministic fallback policy; it never claims conservative selection.

Narrative fields: `status`, `text`, `source_run_id`, `provider`, `is_template`. Tool results: `status` (`ok`, `error`, `unavailable`), `tool_name`, `validated_arguments`, `data` (a JSON-safe mapping with a `kind`: `baseline`, `simulation`, `optimization`, `risk`, `company_profile`, `action_comparison`, `public_reference` or `forecast_drivers`; null on failure), and `error` (nullable). Each tool's fields are listed in [CHATBOT_IMPLEMENTATION.md](CHATBOT_IMPLEMENTATION.md) §4.
