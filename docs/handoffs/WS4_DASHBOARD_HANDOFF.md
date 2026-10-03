# WS4 Handoff: Dashboard, Integration and C0 Foundation

> **Update (branch `feat/integration-all-workstreams`):** all four workstreams are integrated and `real` mode runs every provider for real on the synthetic company CSV. The current wiring, configuration, verification and review list are in [INTEGRATION_HANDOFF.md](INTEGRATION_HANDOFF.md); sections below describe earlier milestones.

Branch: `feat/ws4-dashboard`, merged to `main` in PR #2; integrated with WS2 on `workstream2` (merge pending review).
Contract version: `1.0.0`. Fixture revision: `c0-fixtures-r1`.

**Status: WS2 is integrated. The working configuration is the `hybrid` preset "Fixture forecast + real WS2":** labelled fixture baseline, real WS2 simulator/constraints/optimizer/recommendation, and WS3 capabilities disabled with their reason. This is not the accepted all-real C4 MVP. Real mode now names only the missing WS1 forecast provider (see "WS2 integration" below).

## Run from the repository root

```bash
python3.11 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m pytest
.venv/bin/python -m streamlit run app.py
```

`CARBONOPT_PROVIDER_MODE=mock|real|hybrid` sets the initial mode; the sidebar can change it. In hybrid mode, `CARBONOPT_HYBRID_PRESET` (default `fixture-forecast-real-ws2`) selects a named preset; `custom` restores the per-slot choices.

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

## WS2 integration (merge of `main` into `workstream2`)

- **One contract package.** WS4's `src/contracts/` is the schema; WS2's stopgap copy was dropped and WS2's domain code now reads and writes the WS4 types (mapping-based metrics, totals and risk summaries). Additive changes for review are listed in the WS2 handoff, "Shared contract changes".
- **Provider wiring is unchanged.** `RealSimulatorProvider` and `RealOptimizerProvider` bind the documented WS2 functions. WS2 modules now expose `__version__`, so provider versions (and therefore cache keys) change when WS2 outputs can change.
- **Hybrid preset.** `HYBRID_PRESETS["fixture-forecast-real-ws2"]` in `src/integration/services.py` is forecast `fixture`; simulator, optimizer, risk and benchmark `real`; shap `disabled`. Risk and benchmark resolve to *unavailable* with the reason until WS3 publishes factories, then bind without code changes. SHAP stays off because a fixture baseline has no model to explain. `Services.provenance_summary()` renders the "Baseline: fixture · Simulator: WS2 · Optimizer: WS2 · …" line.
- **Dashboard.** A mixed run shows a **PARTIALLY MOCKED** banner (never "all real"), plus the provenance line. What-if badges use WS2's per-constraint `satisfied` flags.
- **Single pool rule.** `pipeline.select_risk_pool` delegates to WS2's `risk_pool_from_frontier`, so the strategies sent to Monte Carlo are exactly the ones recommendation ranks.
- **Optional pymoo.** `src.optimization` imports without pymoo. Mock startup still needs no solver; the real optimizer reports "missing dependency: pymoo" if it is absent.
- **Tests.** `tests/integration/test_ws2_ws4_hybrid.py` and `test_dashboard_hybrid_apptest.py` cover the requested cross-boundary checks. Three WS4 tests that encoded "WS2 is missing" now assert the WS1-only gap.
- **Performance (one laptop, not a guarantee).** Optimize with 2,048 evaluations takes about 12 s end to end. Most of that is per-call boundary validation (`validate_baseline` about 1.6 ms per simulation; pipeline re-validation of all stored strategies about 2.5 s). Vectorizing those validators is a WS4 follow-up; nothing was skipped to save time.

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
2. WS2: done. The simulator, constraints, optimizer, recommendation and `config/action_assumptions.json` are bound and pass `src.contracts.validation` (see the WS2 handoff).
3. WS3: publish risk and benchmark provider factories.
4. All: replace providers one slot at a time and run `tests/integration/test_provider_swap.py` plus a direct-versus-what-if equality check at each swap.
5. Left for later: P1 acceptance (C5a-c), scenario comparison (C6), P2 explanation and chat (C7), saved-replay state, 36/60-month horizons, `mvp-working` tag (needs an all-real run).

## Review requirements (no approvals have occurred)

| Change | Needs review from |
| --- | --- |
| Provider factory names and `ProviderInfo` convention above | WS1, WS2, WS3 |
| Additive `AnalysisBundle.request` / `providers` fields | WS1, WS2, WS3 consumers |
| `BacktestReport.selected_models`, fold `test_start`/`test_end` names | WS1 |
| Risk-pool selection rule: now WS2's `risk_pool_from_frontier`, called by `pipeline.select_risk_pool` | WS3 |
| Fixture revision `c0-fixtures-r1` (new history, backtest, SHAP fixtures) | WS1, WS3 |
| Pinned P0 dependency versions in `requirements.txt` (WS2 added `pymoo==0.6.2`) | WS1 (add its libraries after a clean install check) |

## Verification evidence

102 pytest tests passed at WS4 handoff. After the WS2 merge the full suite is 333 tests, all passing (contracts, unit, integration, offline startup with optional libraries and sockets blocked, and Streamlit AppTest of the hybrid flow). Streamlit AppTest and a manual browser pass covered Optimize, table selection, what-if equality, slider changes and constraint warnings. The GitHub CI workflow has not been run.

---

# Chatbot handoff (branch `feat/ws4-chatbot`)

Plan and architecture: [CHATBOT_IMPLEMENTATION.md](../CHATBOT_IMPLEMENTATION.md). Status: **mock-backed chatbot working; remote Ollama adapter implemented and tested against a fake transport only. No live `llama3.1:8b` server was contacted, and the tools run on mock backends.** Nothing is committed, pushed, merged or tagged on this branch.

## Implemented behavior

- Floating circular bottom-left bubble opening a panel (title, Clear, Close, history, suggested questions, input, "Thinking" indicator, Check connection for remote mode). Conversation persists across close/reopen; Clear affects chat only; mobile layout checked in a browser emulation.
- Provider abstraction `src/llm/providers.py`: `OllamaChatProvider` (native `/api/chat`, `stream: false`, tools, tool-role replies, `/api/tags` connection check, optional bearer token) and deterministic `MockChatProvider` (labelled MOCK MODEL).
- Allowlisted tools `get_baseline`, `simulate_strategy`, `optimize_strategies`, `get_risk_summary` through the existing services; strict argument validation; final-share versus remaining-fraction semantics with the documented conversion; 3 executions per message; evaluations capped at 512, risk trials at 1000; duplicate-dispatch and retry safety.
- Application-bound `AnalysisContext` with a `context_version`; result cards from serialized backend output; stale cards disable **Apply to dashboard**; apply loads the exact config into the what-if sliders and never changes the selected plan or constraints.
- Template `explain_analysis()` and `ToolResult`/`NarrativeResult` contract types.

## Files

New: `src/llm/` (`config.py`, `types.py`, `providers.py`, `context.py`, `tools.py`, `assistant.py`, `prompt.py`, `summaries.py`), `src/dashboard/chat_state.py`, `src/dashboard/chat_ui.py`, `.env.example`, `docs/CHATBOT_IMPLEMENTATION.md`, tests `tests/unit/test_chat_*.py`, `tests/integration/test_chat_ui.py`, `tests/integration/test_ollama_live.py`.
Changed: `app.py` (renders the assistant, sidebar spacer), `src/contracts/types.py` and `__init__.py` (additive), `tests/contracts/test_offline_startup.py`, `README.md`, and the Markdown under `carbonopt-ai-docs/` (plan, WS4 workstream, shared contracts, testing, decisions D15-D19).

## Run and configure

```bash
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m pytest
.venv/bin/python -m streamlit run app.py          # mock model by default
CHATBOT_PROVIDER=ollama OLLAMA_BASE_URL=https://<host> .venv/bin/python -m streamlit run app.py
```

Required remote server configuration: an Ollama server reachable from the Streamlit host over HTTP(S), with `llama3.1:8b` pulled (`ollama pull llama3.1:8b` on that server), tool-calling enabled for the model, and, if behind a gateway, a bearer token in `OLLAMA_API_KEY`. Variables are listed in `.env.example`.

## Verification (what actually ran)

- `pytest`: 208 passed, 1 skipped before merging `main`; 439 passed, 1 skipped (the opt-in live smoke test) after merging WS2 from `main`. Chatbot browser checks below were done in mock mode before that merge and not repeated against the real WS2 providers.
- Browser (built-in preview, mock mode): bubble open/close, suggested question, what-if card, Apply to dashboard (EV slider set to 0.80, selected strategy unchanged), history preserved after close/reopen, mobile width layout.
- AppTest only (not in a browser): all five suggestions, typed message, stale cards, remote error with Retry, missing endpoint, invalid provider value.
- **Not run:** live Ollama smoke test; dark-mode check of the panel; keyboard-only navigation and screen-reader pass; any real WS1-WS3 backend.

## Mock limitations

The mock model matches a small set of phrases with regular expressions and writes template summaries; it is not a language model. Tool results inherit the mock backend limits above (fixture risk covers one strategy, so a risk question on a behavioral frontier returns a visible tool error instead of a probability). The panel marks mock model and mock backends.

## Known limitations

- Final text is not streamed (complete responses only).
- The launcher icon uses a Streamlit material icon and tooltip; there is no programmatic focus on open, and the accessible name comes from the icon text. The CSS positioning relies on the `st-key-<key>` class Streamlit generates for keyed containers.
- The bubble overlays the bottom of the sidebar; the sidebar keeps bottom padding so Optimize stays reachable.
- Model quality with real `llama3.1:8b` tool calling is unverified; the prompt may need tuning.

## Contract-review requirements (no approvals have occurred)

Additive `ToolResult` and `NarrativeResult` in `src/contracts/types.py` need review by WS1-WS3 consumers; the chat tools call WS2/WS3 providers only through existing service interfaces. `ChatModelProvider` is WS4-internal.

## Exact remaining steps to connect and test a real `llama3.1:8b`

1. Obtain the endpoint URL (and gateway token if required) for an Ollama server with `llama3.1:8b` pulled.
2. Export `CHATBOT_PROVIDER=ollama`, `OLLAMA_BASE_URL`, optionally `OLLAMA_API_KEY`; start the app and press **Check connection** in the panel.
3. Run `RUN_OLLAMA_LIVE_SMOKE=1 CHATBOT_PROVIDER=ollama OLLAMA_BASE_URL=... .venv/bin/python -m pytest tests/integration/test_ollama_live.py -q`.
4. Try the five suggested questions; check tool selection, `final_shares` versus `actions` handling, and refusals; tune `src/llm/prompt.py` if needed.
5. When WS1-WS3 providers land, repeat in `real`/`hybrid` provider mode.
6. Optional: add streaming of final text (never partial tool arguments).
