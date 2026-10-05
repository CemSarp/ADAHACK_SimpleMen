# Architecture

## Services

`src/integration/services.py` builds one `Services` object from `config/integration.json`
(or the file named by `CARBONOPT_CONFIG`). Each slot is bound to its domain provider:

| Slot | Required | Provider |
|---|---|---|
| forecast | yes | `src/forecasting/provider.py`: CSV import (`history.py`), WS1 `ml_core.modelling` models cached under `models/ws1/<model_id>/` (`ws1_adapter.py`), baseline and backtest assembly (`baseline.py`) |
| simulator | yes | `src/actions/provider.py`: the deterministic action engine with the company's assumption file |
| optimizer | yes | `src/optimization/provider.py`: NSGA-II, shared constraint evaluation, recommendation policy |
| risk | no | `src/risk/provider.py`: Monte Carlo over the injected simulator |
| shap | no | `src/explainability/provider.py`: SHAP over WS1's trained tree models |
| benchmark | no | `src/benchmarking/provider.py`: offline peer snapshot (`unavailable` without a compatible peer set) |

A required provider that cannot be built stops startup; the dashboard shows a generic error
and logs the cause. An optional provider that cannot be built is disabled and its reason is
recorded in `Services.unavailable`. Nothing falls back to a mock.

`create_services(overrides)` replaces a slot with another instance or disables an optional
slot with `None`. Only tests use it, through `tests.mocks.make_services`. When the forecast
is overridden, the real simulator, risk and benchmark keep their default config files, so a
baseline is never paired with another company's assumptions.

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

## Dashboard and assistant

`app.py` renders `src/dashboard/` panels from `DashboardState`, which owns all session
state and invalidation. The assistant (`src/llm/`) calls an allow-listed set of tools that
run through the same `Services` as the UI; see [CHATBOT_IMPLEMENTATION.md](CHATBOT_IMPLEMENTATION.md).

Data provenance (synthetic company data, illustrative assumptions) is shown separately from
implementation provenance (which providers produced each result).
