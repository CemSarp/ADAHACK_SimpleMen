# Architecture

## Services

`src/integration/services.py` builds one `Services` object from `config/integration.json`
(or the file named by `CARBONOPT_CONFIG`). Each slot is bound to its domain provider:

| Slot | Required | Provider |
|---|---|---|
| forecast | yes | `src/forecasting/provider.py`: CSV import (`history.py`), a RandomForest (or the model chosen with `create_services(model=...)`) from `ml_core.modelling` fitted to the canonical history and cached under `models/ws1/<model_id>/` (`ws1_adapter.py`, ~10 s the first time), baseline and backtest assembly (`baseline.py`). `compare_models` scores other models on request only |
| simulator | yes | `src/actions/provider.py`: the deterministic action engine with the company's assumption file |
| optimizer | yes | `src/optimization/provider.py`: NSGA-II, shared constraint evaluation, recommendation policy |
| risk | no | `src/risk/provider.py`: Monte Carlo over the injected simulator |
| shap | no | `src/explainability/provider.py`: SHAP over the bound forecast's tree models (unavailable for a non-tree model) |
| benchmark | no | `src/benchmarking/provider.py`: offline peer snapshot (`unavailable` without a compatible peer set) |

A required provider that cannot be built stops startup; the dashboard shows a generic error
and logs the cause. An optional provider that cannot be built is disabled and its reason is
recorded in `Services.unavailable`. Nothing falls back to a mock.

`create_services(overrides, *, model=None)` replaces a slot with another instance or disables an optional
slot with `None`; `model` forecasts with a named WS1 model instead of the automatic choice. Uploads use it
(below), and tests through `tests.mocks.make_services`. When the forecast is overridden, the real simulator,
risk and benchmark keep their default config files, so a baseline is never paired with another company's
assumptions, and the SHAP slot explains the bound forecast (never a separately built demo model).

## Uploaded data

`create_dataset_services(table, mapping, *, name, sha256, model=None)` builds the same `Services` for any
monthly CSV:

1. `src/forecasting/mapping.py` suggests which column plays which role (date, revenue, profit or cost,
   emissions, optional activity) from the column names, and detects the date column and currency;
   `src/dashboard/data_panel.py` shows the suggestions as dropdowns, checks what is still missing as the user
   edits, and turns the confirmed choice into an import configuration (`import_mapping`, the same shape as
   `config/company_import.json`).
2. `src/forecasting/history.py` imports the table into the canonical history and records every
   derivation (currency, percentages, gaps, missing scopes or electricity); it refuses data it cannot repair
   (fewer than 24 months, duplicate months, unreadable dates, inconsistent totals) with a field and a reason.
3. The forecast is fitted to that history (FORECASTING_SPEC.md); the driver policy follows whichever
   activities it reports. Planning defaults are sized to the company (`planning_defaults`).
4. `src/actions/calibrate.py` rescales the demo's action assumptions to the company's activity.
   Actions with nothing to act on get zero share and zero cost; `inactive_actions` detects them,
   the optimizer keeps them at zero, the page hides them with a note and the assistant says they do nothing.

`app.py` caches services per (file bytes, mapping, model) with `st.cache_resource`, so switching back to a
file or model already seen is instant.

## Analysis pipeline

`src/integration/pipeline.py` validates every boundary object and propagates provenance:

1. Baseline and backtest from the forecast provider (cached per company and horizon).
2. NSGA-II search and the feasible Pareto frontier.
3. Monte Carlo risk over a bounded frontier pool (`risk_pool_from_frontier`), when requested.
4. The risk-aware recommendation.
5. SHAP and benchmark annotations, when requested.

Failures of optional stages become warnings; required-stage failures propagate.
`compare_scenarios` reruns only the recommendation policy for the three tolerances on the
same analysis. Cache keys (`cache_keys.py`) hash every input and provider version, so a
changed input never reuses another input's result.

## Dashboard

`app.py` builds the sidebar (data source, goals with their accepted ranges, optional checks, **Find plans**) and
renders the sections in `src/dashboard/components.py` from `DashboardState` (`state.py`), which owns all
session state, caching of the baseline and invalidation when inputs change.

| Section | Reads | Notes |
| --- | --- | --- |
| Your data (upload step) | `data_panel.py`, `mapping.py`, `history.py` | Shown instead of the report until an upload is confirmed |
| 1 · Starting point | baseline, backtest, history | **History shown** range; **Compare forecasting models** calls `compare_models` only when pressed; **Forecast with** sets the model in session state, which selects a different cached `Services` |
| 2 · Plans | analysis (optimization, recommendation) | When nothing is feasible, `relaxation_hints` reads the evaluated candidates and `presentation.hint_lines` words one change per goal |
| 3 · Your mix | simulator, `inactive_actions` | Sliders only for actions the data supports |
| 4 · Confidence | risk, recommendation policy, benchmark, SHAP | `uncertainty_method` describes the Monte Carlo draws from the bound uncertainty spec; drivers keep the top *k* |
| 5 · Timing | `src/data_sources/public_data.py` | Saved GB grid forecast offline; the live Carbon Intensity API only on **Get the live forecast**; never added to company totals |
| 6 · Assumptions | action assumptions, analysis | Cost tables and the full JSON download |

Budget limit shown in the sidebar: the outlay of every action at full take-up (one simulator call per
baseline, `components.full_mix_cost`); above it the budget changes nothing.

Data provenance (synthetic demo data or the user's upload, illustrative assumptions) is shown separately from
implementation provenance (which providers produced each result).

## Assistant

`src/llm/` answers questions with eight allow-listed tools that run through the same `Services` as the page:
`get_baseline`, `get_company_profile`, `get_forecast_drivers`, `compare_actions`, `simulate_strategy`,
`optimize_strategies`, `get_risk_summary`, `get_public_reference`. The app builds the `AnalysisContext` from
the dashboard state; the model sees only its summary and cannot select a company, provider or file. Providers:
the offline guided assistant (default), LM Studio (e.g. Gemma 4) or Ollama. See
[CHATBOT_IMPLEMENTATION.md](CHATBOT_IMPLEMENTATION.md).
