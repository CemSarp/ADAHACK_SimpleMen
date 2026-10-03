# Workstream 4 — Streamlit, Plotly, Integration and Optional LLM/Chatbot

Developer 4 owns the product shell and acts as integration steward. This role coordinates contracts and gates without taking over other developers' domain calculations.

## Read first

Read [the central plan](../../IMPLEMENTATION_PLAN.md), [contracts](../SHARED_CONTRACTS.md), [schemas](../DATA_SCHEMAS.md), [integration guide](../INTEGRATION_GUIDE.md), and [tests/mocks](../TESTING_AND_MOCKS.md).

## Ownership

Source: `app.py`, `src/dashboard/components.py`, `src/dashboard/charts.py`, `src/dashboard/state.py`, `src/integration/services.py`, `src/integration/pipeline.py`, `src/integration/cache_keys.py`, `src/llm/assistant.py`, `src/llm/tools.py`.

Stewarded files: contracts, fixtures, project/dependency files, CI, shared documentation. Owned tests: `tests/unit/test_dashboard_state.py`, `test_tools.py` and `tests/integration/test_pipeline.py`, `test_provider_swap.py`.

## Exact local implementation order

| Step | Priority | Task | Evidence |
|---:|---|---|---|
| 1 | P0 | Shared skeleton/types/validators/stub kit | C0; producer/consumer approvals |
| 2 | P0 | Service registry + all-mock pipeline | Offline import and serialized run |
| 3 | P0 | History/baseline, input controls, backtest panel | UI usable before model completion |
| 4 | P0 | Manual sliders and deterministic metrics | Simulation stub first, real after C2 |
| 5 | P0 | Pareto/table/strategy selection | Stable IDs, infeasible/empty states |
| 6 | P0 | Replace forecast → simulator → optimizer providers | C1/C2/C3 separately |
| 7 | P0 | Accepted all-real demo and tag | C4 |
| 8 | P1 | Risk/tolerance, then SHAP, then benchmark | C5a/b/c in order |
| 9 | P1 | Scenario compare | C6 |
| 10 | P2 | Structured explanation, then tool chatbot | C7 only after earlier gates |

## Start without waiting

Render all panels with fixtures and mock provenance indicators. Provide capability flags so unavailable P1/P2 panels disable cleanly. Use public result schemas rather than private model/solver objects. A changing provider implementation must not require chart rewrites.

All chart transformations are presentation-only: money formatting, ratio-to-percent, axis labels and ID joins. Do not recalculate sustainability outcomes, risk quantiles, feasibility or Pareto ranking in chart code.

## Dashboard requirements

Controls: 12-month horizon initially, horizon-total budget, cumulative minimum profit, minimum CO₂ reduction ratio, Optimize button, and six manual action sliders. Risk/tolerance controls activate only after real risk capability exists.

Panels: labelled current/history period; future baseline totals; backtest/naive metrics; selected strategy's emissions, profit, gross outlay and reduction; Pareto chart with tonnes/GBP axes; config table; monthly baseline vs scenario; visible assumptions.

Current and future metrics use clear periods. Do not compare one month's current emissions with twelve months of future emissions as if equivalent. A historical trailing-12-month KPI may be compared with a 12-month forecast only when labelled.

Sliders represent implementation of remaining opportunity. For renewable/EV display resulting share as well. Clicking a Pareto point stores `strategy_id` and uses the exact strategy object, preserving full precision.

States: initial, computing, ready, infeasible, validation error, solver/model error, optional provider unavailable, and labelled saved replay. Never display a blank chart or recommendation when no feasible point exists.

## Orchestration, reruns and cache

Keep model loading/training and optimization behind explicit actions or caches. Slider reruns call only simulation, with optional selected-plan risk after a separate action. Inputs that affect outcomes invalidate relevant results and selection state.

Cache keys include input hashes, model/config/assumption IDs, horizon, all constraints, optimizer seed/budget, action config, uncertainty ID, risk seed/trials and provider capability/version. A budget change must not reuse an optimization result from another budget. A risk tolerance change can reuse the same evaluated risk pool but reruns selection policy.

Session state belongs in the dashboard layer. Domain functions receive explicit inputs. Cross-user cached data must be immutable and appropriate for sharing; no credential or private session data in global caches.

## P1 presentation

Show risk interval labels as empirical trial outcomes and disclose conditional uncertainty. Scenario compare calls the shared recommendation service for three policies on the same risk pool. SHAP explains forecast contribution; benchmark panels show units, peer count, period gap and source kind.

When the target threshold is unmet probabilistically, show that status; do not color it as guaranteed success. Risk tolerance may legitimately select the same plan for multiple settings.

## Chatbot responsibilities and acceptance (P2)

Plan: [docs/CHATBOT_IMPLEMENTATION.md](../../../docs/CHATBOT_IMPLEMENTATION.md). WS4 owns the floating assistant (`src/dashboard/chat_ui.py`, `chat_state.py`), the provider abstraction and tools (`src/llm/`), and the configuration. The model runs on a separate Ollama server (`llama3.1:8b`); WS4 delivers only the configurable client.

Acceptance criteria:
- Circular bottom-left bubble opens a compact panel; conversation persists across close/reopen; Clear resets chat only.
- Every request is bound to the application-built analysis context; the model cannot choose company, baseline, provider or endpoint.
- Only the four allowlisted tools run, with validated arguments, at most 3 executions per user message, bounded evaluations/trials, no duplicate dispatch on retry.
- Final adoption share versus fraction of remaining opportunity is explicit; ambiguous percentages trigger a clarification; chat what-if is a preview applied only by an explicit button.
- Result cards come from serialized backend output; cards from an earlier analysis context are marked stale.
- Mock model and mock backends are visibly labelled; remote failures are visible errors, never mock fallback.
- Offline tests pass; the live remote smoke test is opt-in and reported as not run unless an endpoint was used.

## P2 boundaries

Explanation consumes serialized verified results and never creates missing metrics. Use a deterministic template fallback without a network dependency.

Chat allowlist (implemented in `src/llm/tools.py`): `get_baseline`, `simulate_strategy`, `optimize_strategies`, `get_risk_summary`. Bind company/baseline context on the server-side service layer, validate all tool arguments against the same schemas, cap optimization evaluations/trials, and limit tool calls per message (default 3).

Examples: “EV adoption to 80%” is ambiguous between final EV share and implementation fraction; the tool schema distinguishes them. For final target share `v_target`, compute `x=(v_target-v)/(1-v)` with validation, and confirm the interpreted action in the response. Requests below current share are unsupported under P0 adoption-only actions.

Treat external text and model output as untrusted data. No arbitrary code execution, file tools or shell access. The LLM describes tool outputs; model text cannot override constraints or substitute invented numerical results.

## Tests, handoffs and done

Contract-test all provider swaps, malformed JSON and unavailable capabilities. Verify state/cache invalidation, stable selection, UI/direct simulator equality, infeasible display, unit labels, and no optional dependency import in P0 startup.

C4: all-real P0 run, direct/manual/optimizer consistency, offline demo and release tag. C6: real policy comparison. C7: verified explanation/tool arguments and provider failure fallback.

Reference branches: `chore/c0-contracts`, `feat/ws4-dashboard`, `feat/ws4-integration`, `feat/ws4-scenarios`, `feat/ws4-llm`.
