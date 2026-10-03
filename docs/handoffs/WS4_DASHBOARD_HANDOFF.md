# WS4 Handoff: Dashboard, Integration and C0 Foundation

Branch: `feat/ws4-dashboard` (uncommitted work; nothing merged, pushed or tagged).
Contract version: `1.0.0`. Fixture revision: `c0-fixtures-r1`.

**Status: mock-backed P0 only. This is not the accepted all-real C4 MVP.** Real mode refuses to start until the WS1 forecast and WS2 simulator/optimizer providers exist.

## Run from the repository root

```bash
python3.11 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m pytest
.venv/bin/python -m streamlit run app.py
```

`CARBONOPT_PROVIDER_MODE=mock|real|hybrid` sets the initial mode; the sidebar can change it.

## Provider wiring

`src/integration/services.py` exposes `create_services(mode, provider_overrides)`.

| Slot | Required | Mock default | Real entry point WS4 looks for |
| --- | --- | --- | --- |
| forecast | P0 | fixture | `src.forecasting.provider.create_forecast_provider()` |
| simulator | P0 | behavioral mock | `src.actions.engine.simulate_strategy` and `config/action_assumptions.json` |
| optimizer | P0 | behavioral mock | `src.optimization.optimizer.optimize_strategies`, `constraints.evaluate_constraints`, `recommendation.recommend_strategy` |
| risk | P1 | fixture | `src.risk.provider.create_risk_provider()` |
| shap | P1 | fixture | `src.explainability.provider.create_explanation_provider()` |
| benchmark | P1 | fixture | `src.benchmarking.provider.create_benchmark_provider()` |

- **mock:** all slots are doubles from `tests/mocks/`. **real:** real providers only; a missing P0 provider raises `ProviderConfigurationError` naming it, a missing optional one disables the capability. **hybrid:** explicit per-slot overrides (`"real"`, `"mock"`, `"fixture"`, `"behavioral"`, `"disabled"` for optional slots, or a provider instance).
- Nothing falls back from real to mock. `AnalysisBundle.providers` and `provenance.is_mock` record what was used; the UI shows a banner and `MOCK` tags.
- Real providers must expose `info: ProviderInfo` whose `version` changes whenever outputs can change; it is part of every cache key.

## What WS4 owns

`app.py`, `src/dashboard/`, `src/integration/`, WS4 tests, plus stewarded shared files: `src/contracts/`, `tests/contracts/`, `tests/fixtures/`, `tests/mocks/`, `requirements*.txt`, `pyproject.toml`, `.gitignore`, `.github/workflows/ci.yml`.

Dashboard code does presentation only. Feasibility, Pareto ranks, constraint badges and recommendations come from the optimizer provider; manual what-if calls the simulator provider directly.

## Mock limitations

- The behavioral simulator is an affine test double (documented in TESTING_AND_MOCKS.md, extended to six actions). It has no scope buckets, savings, interactions or depreciation life.
- The behavioral optimizer is seeded random search with a plain nondominance filter, not NSGA-II.
- Fixture providers accept only their fixture inputs and raise `UnsupportedMockInput` otherwise. Fixture risk covers one strategy, so mock recommendations report `risk_status="unavailable"`.
- Fixture history, backtest and SHAP numbers are illustrative layout data, not model results.
- Behavioral mock output is deterministic for a seed but uses no calibrated economics.

## Outstanding integration points

1. WS1: publish forecast and SHAP provider factories; backtest report must include `selected_models` and fold fields `test_start`/`test_end`.
2. WS2: publish the simulator, constraints, optimizer and recommendation modules plus `config/action_assumptions.json`. Returned objects must pass `src.contracts.validation`.
3. WS3: publish risk and benchmark provider factories.
4. All: replace providers one slot at a time and run `tests/integration/test_provider_swap.py` plus a direct-versus-what-if equality check at each swap.
5. Left for later: P1 acceptance (C5a-c), scenario comparison (C6), P2 explanation and chat (C7), saved-replay state, 36/60-month horizons, `mvp-working` tag (needs an all-real run).

## Review requirements (no approvals have occurred)

| Change | Needs review from |
| --- | --- |
| Provider factory names and `ProviderInfo` convention above | WS1, WS2, WS3 |
| Additive `AnalysisBundle.request` / `providers` fields | WS1, WS2, WS3 consumers |
| `BacktestReport.selected_models`, fold `test_start`/`test_end` names | WS1 |
| Risk-pool selection rule in `pipeline.select_risk_pool` (endpoints plus even spacing, max 20) | WS2, WS3 |
| Fixture revision `c0-fixtures-r1` (new history, backtest, SHAP fixtures) | WS1, WS3 |
| Pinned P0 dependency versions in `requirements.txt` | WS1, WS2 (add their libraries after a clean install check) |

## Verification evidence

102 pytest tests pass (contracts, unit, integration, offline startup with optional libraries and sockets blocked). Streamlit AppTest and a manual browser pass covered Optimize, table selection, what-if equality, slider changes and constraint warnings. The GitHub CI workflow has not been run.
