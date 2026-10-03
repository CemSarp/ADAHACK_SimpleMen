# Tests, Fixtures, Stubs and Acceptance Strategy

Goal: each developer starts independently, while integration verifies both schema compatibility and shared numerical meaning.

## 1. Fixture kit

The package's `examples/` files are initial machine-readable shapes and synthetic numerical examples. During C0 copy/review them into `tests/fixtures/v1/`, create JSON schemas/validators, and expand fixtures where indicated.

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

At C0 add history CSV and short sequence fixtures; backtest report; SHAP explanation; invalid schema cases; unavailable benchmark; two-strategy risk selection pool; zero-uncertainty case. These are explicitly implementation tasks, not files claimed to be delivered here.

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

### Production substitution

All stubs and real providers implement the same public protocols and serializers. Services may replace forecast, simulator, optimizer, risk, SHAP and benchmark independently. Run contract tests parametrized over the corresponding mock and real provider.

### Chatbot mocks and tests

`MockChatProvider` (`src/llm/providers.py`) is a deterministic, rule-based model double labelled **MOCK MODEL**; it is not a language model and exists only so the UI, tool loop and tests run offline. The Ollama adapter is tested with an injected fake transport (request shape, normalization, timeouts, HTTP errors, invalid bodies); no test needs a live endpoint. Required tests: provider normalization, configuration validation, no network at import or in mock mode, tool allowlist and argument validation, adoption-share conversion and percent ambiguity, server-bound context and versioning, execution limits and duplicate/retry dispatch, capability and provenance propagation, conversation persistence and stale cards, card accuracy against direct service calls, remote failure without mock fallback, P0 startup without chatbot configuration, and AppTest coverage of the floating panel. A live smoke test (`tests/integration/test_ollama_live.py`) is opt-in via `RUN_OLLAMA_LIVE_SMOKE=1` with `OLLAMA_BASE_URL` and is skipped otherwise.

## 3. Test structure and minimum suite

| Layer | Paths | Required assertions |
|---|---|---|
| Contract | `tests/contracts/` | Required fields, dtypes, units, JSON round-trip, versions, date continuity |
| WS1 unit | `tests/unit/test_data.py`, `test_features.py`, `test_forecast.py`, `test_backtest.py` | Leakage, recursion, reproducibility, scope reconciliation |
| WS2 unit | `tests/unit/test_actions.py`, `test_accounting.py`, `test_constraints.py`, `test_pareto.py` | No-op, interactions, profit/cash accounting, signs/dominance |
| WS3 unit | `tests/unit/test_risk.py`, `test_benchmark.py`, `test_benchmark_adapters.py` | Trial identity, probability, unit/coverage/percentile, network failure |
| WS4 unit | `tests/unit/test_dashboard_state.py`, `test_tools.py` | Cache/state invalidation, validation, allowlist, provider failure |
| Integration | `tests/integration/test_pipeline.py`, `test_provider_swap.py` | Provider substitutions; end-to-end result consistency |
| Optional | `tests/unit/test_shap.py` | Raw-output additivity, unavailable target |

Entries with only a filename in the unit table are relative to `tests/unit/`.

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

C0 provides a clean offline P0 job installing the locked P0 dependencies and running contract, unit and integration suites. Optional jobs install P1/P2 requirements and run their marked tests without real network/credentials.

Run boundary tests before each provider swap, full P0 suite before C4, affected tests at each P1 gate, and a final all-enabled offline demo smoke test. Measure performance on the configured fixture rather than adding brittle machine-specific timing assertions.

PRs show test commands/results and fixture versions. Model quality thresholds are contextual; leakage safety, honest naive comparison and contract integrity are unconditional.

## 7. Definition of done checklist

- Public input and output schema validation passes.
- Required numerical identities and meaningful edge cases pass.
- Deterministic comparisons exclude transient IDs/timing only.
- Consumer tests pass with the real provider.
- Optional failures and unsupported capabilities are explicit.
- Handoff includes reviewed example payload, configuration IDs and limitations.
- No personal paths, secrets or undeclared network dependency are introduced.
