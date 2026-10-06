# Tests, Fixtures, Stubs and Acceptance Strategy

Goal: each developer starts independently, while integration verifies both schema compatibility and shared numerical meaning.

## 1. Fixture kit

`tests/fixtures/v1/` holds the machine-readable contract shapes and synthetic numerical examples every test loads through the shared serializers and validators.

| Fixture target | Producer / reviewer | Purpose |
|---|---|---|
| `baseline_12m.json` | WS1 / WS2 | Complete 12-month baseline consumed by every workstream |
| `action_config.json` | WS2 / WS4 | Canonical six-variable config |
| `action_assumptions.json` | WS2 / WS3 | Versioned deterministic parameters and uncertainty hooks |
| `constraints.json` | WS2 / WS4 | Horizon-based cash/profit/CO₂ requirements |
| `simulation_noop.json` | WS2 / WS3 | Exact no-op accounting identity |
| `simulation_nonzero.json` | WS2 / WS4 | Cross-action golden calculation |
| `optimization_ok.json` | WS2 / WS4 | Stable strategy joins and typed tables |
| `optimization_infeasible.json` | WS2 / WS4 | Empty Pareto with retained diagnostics |
| `risk_summary.json` | WS3 / WS2 | Risk shape; labelled illustrative summary |
| `benchmark_result.json` | WS3 / WS4 | Peer units, direction and source metadata |
| `benchmark_peers.json` | WS3 / WS4 | Compatible illustrative peer dataset |

The kit also covers a history CSV, backtest report, SHAP explanation and a golden 1,000-trial Monte Carlo sample (`risk_sample_mock_simulator.json`).

Fixtures are immutable per revision. Update numerical expectations only with domain-owner review; never regenerate snapshots just to silence a failing test.

## 2. Stub modes

### Shape stubs

Load fixtures, validate them, and return fresh DataFrame/dataclass objects. Suitable for dashboard layout, chart handling, result serialization and integration transport. Mark `provenance.is_mock=true`.

Shape stubs accept only their supported known input cases; unknown requests return a documented unsupported-case error. A fixture simulator must not ignore arbitrary slider inputs and return the same apparently computed result.

### Behavioral test doubles

For optimizer and risk development, implement a separate test-only deterministic affine callable conforming to SimulationFn. It must respond to configs and sampled assumptions:

~~~text
test_emissions =
    baseline_emissions * (1 - 0.2*x_renewable*renewable_effectiveness
                              - 0.1*x_ev*ev_effectiveness)
test_cost =
    renewable_capex_at_full*x_renewable + ev_capex_at_full*x_ev
test_profit = baseline_profit - 0.01*test_cost
~~~

Return schema-valid monthly allocation and matching totals. This is a mathematical test double, clearly labelled and kept only in `tests/mocks/`; it is never a production action implementation. The real action engine follows ACTION_MODEL.md.

Use a two-variable toy problem with known dominated/feasible points for solver/constraint adapter tests. Use a risk-sensitive double for uncertainty tests; a constant static response cannot prove Monte Carlo logic.

### Injecting doubles

All doubles and real providers implement the same public protocols and serializers. `tests.mocks.make_services(overrides)` binds a mock to every slot unless a slot is given a provider instance, a variant name (`fixture`, `behavioral`), `real` or `disabled`; it calls `create_services`, which never imports test code.

### Chatbot mocks and tests

`MockChatProvider` (`src/llm/providers.py`) is the **guided assistant**: deterministic rules that map preset
questions to real tool calls and summarise the results. It is not a language model; it runs offline and is
the default and the test double for the model. The LM Studio and Ollama adapters are tested with an injected
fake transport (request shape, tool-call ids, reasoning stripping, out-of-budget replies, timeouts, HTTP
errors, invalid bodies); no test needs a live endpoint.

Covered offline: provider wire formats, configuration validation, no network at import or in mock mode, the
tool allowlist and every argument rule, share conversion and percent ambiguity, each tool's output (forecast
model and accuracy, forecast drivers, infeasible hints, no-effect notes, missing scopes), server-bound context
and versioning, execution limits and duplicate/retry dispatch, prompt rules (Find plans, data kind, what-ifs
without a plan, "all remaining"), the system-message size budget, conversation persistence and stale cards, and
the floating panel through AppTest.

Live checks are opt-in. `tests/integration/test_ollama_live.py` runs with `RUN_OLLAMA_LIVE_SMOKE=1` and
`OLLAMA_BASE_URL`. For LM Studio, start the app with `CHATBOT_PROVIDER=lmstudio` and ask the questions listed in
CHATBOT_IMPLEMENTATION.md §8; each answer's cards show which tool ran and with which result.

## 3. Test structure and minimum suite

| Layer | Paths | What they check |
|---|---|---|
| Contract | `tests/contracts/test_schemas.py`, `test_shared_contract_changes.py`, `test_offline_startup.py` | Fields, dtypes, units, JSON round-trip, versions, date continuity; startup without network or chatbot config |
| Forecast and import | `tests/integration/test_all_workstreams.py`, `test_model_choice.py`, `test_upload.py` | Import repairs and refusals, leakage safety, backtest, model choice and on-demand comparison, uploads end to end |
| Actions and optimizer | `tests/unit/test_actions.py`, `test_accounting.py`, `test_constraints.py`, `test_pareto.py`, `test_optimizer.py`, `test_recommendation.py` | No-op, interactions, profit/cash accounting, feasibility, relaxation hints, dominance, inactive actions, recommendation policy |
| Risk and benchmark | `tests/unit/test_risk.py`, `test_benchmark.py`, `tests/integration/test_ws3_providers.py` | Trial identity, probabilities, percentile, unavailable peers |
| Dashboard | `tests/unit/test_dashboard_state.py`, `test_presentation_and_charts.py`, `test_public_data.py`, `tests/integration/test_product_dashboard.py`, `test_integrated_dashboard.py` | State invalidation, formatting, hints, Monte Carlo text, charts (top-*k* drivers, timeline, model errors, grid), the page through AppTest |
| Assistant | `tests/unit/test_chat_*.py`, `tests/integration/test_chat_ui.py` | See above |
| Integration | `tests/integration/test_pipeline.py`, `test_provider_swap.py`, `test_ws2_ws4_hybrid.py` | Provider substitutions; end-to-end result consistency |

Mandatory cross-boundary tests:

1. Serialize/deserialize a 12-month baseline; totals/dates survive.
2. Direct simulation and manual what-if return identical numerical outcomes.
3. Stored optimizer point equals canonical simulator evaluation of its exact config.
4. Every Pareto point is feasible and nondominated within declared tolerance.
5. Zero-uncertainty risk repeats the deterministic simulation.
6. Mock/real provider swaps change provenance/results but not consumer assumptions.
7. An impossible request yields an empty frontier and visible no-recommendation state.
8. Network/SHAP/LLM unavailability leaves accepted P0 intact.

## 4. Golden action arithmetic

Use the full baseline/assumptions/config examples. Baseline horizon emissions are 1,200 tonnes and profit GBP 1,200,000. Zero config yields exactly those totals and zero costs.

For the nonzero config, tests independently verify scope allocations, electricity savings, added EV load, renewable scaling, capex first month, monthly depreciation, and horizon sums. Compute expected values once from hand equations and keep them frozen.

Delivered nonzero golden totals: 843.744 tCO₂e, GBP 1,210,940.7847619047 operating profit, GBP 164,000 capex and GBP 186,581.12 gross budget outlay. Monthly scopes are 16.08, 8.982 and 45.25 tonnes. UI rounds currency for display; fixtures/tests preserve numerical precision.

Do not test only by calling the same production helper twice: that proves consistency but not correctness. Include independent arithmetic assertions for interaction and financial accounting.

## 5. Failure cases

Reject duplicate/missing months, multiple companies, nonfinite values, scope mismatches, 0–100 percentages, out-of-range actions, negative budgets, malformed forecast dates and unsupported horizons.

Test loss-making baseline, zero total CO₂, zero baseline profit (nullable profit-change ratio), no eligible fleet, zero activity with positive allocation, and full renewable coverage. Define error/result behavior from SHARED_CONTRACTS.md rather than catching all exceptions.

Infeasible optimization is a valid business result; unexpected solver failure is an error. A missing benchmark is a valid unavailable optional result. Distinguish them in tests and UI.

## 6. CI and verification cadence

CI (`.github/workflows/ci.yml`) installs `requirements.txt` and runs the contract, unit and integration suites offline. Measure performance on the configured fixture rather than adding brittle machine-specific timing assertions.

PRs show test commands/results and fixture versions. Model quality thresholds are contextual; leakage safety, honest naive comparison and contract integrity are unconditional.

## 7. Definition of done checklist

- Public input and output schema validation passes.
- Required numerical identities and meaningful edge cases pass.
- Deterministic comparisons exclude transient IDs/timing only.
- Consumer tests pass with the real provider.
- Optional failures and unsupported capabilities are explicit.
- Handoff includes reviewed example payload, configuration IDs and limitations.
- No personal paths, secrets or undeclared network dependency are introduced.
