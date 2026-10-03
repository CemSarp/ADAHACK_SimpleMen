# CarbonOpt AI — Central Implementation Plan

## 1. Objective and scope

Build a single-company decision application: project business-as-usual performance, simulate sustainability interventions, search for feasible financial/environmental trade-offs, and explain the selected strategy.

The central engineering boundary is `simulate_strategy()`. Manual what-if, optimizer evaluations, risk trials, scenario comparison, and chatbot tools use that implementation. Forecasting predicts the baseline; it does not estimate causal action effects. Intervention effects come from explicit, versioned assumptions.

This plan follows the technical stack and feature order in the source conversation. The source contains two placements for backtesting; this package resolves the ambiguity by making leakage-safe backtesting a P0 acceptance gate, matching the detailed sequence requested for this handoff. Integration acceptance order is fixed:

~~~text
Data → Forecast → Backtest → Action Engine → What-if → Optimizer
→ Pareto → Dashboard → Risk → SHAP → Benchmark → Scenario Compare
→ LLM Explanation → Chatbot
~~~

This is a dependency and acceptance order. It does not require four developers to code sequentially: all downstream work starts against C0 contracts and stubs.

## 2. Technology stack

| Layer | Selection | Priority | Owner / implementation policy |
|---|---|---|---|
| Runtime | Python 3.11; 3.12 after compatibility check | P0 | WS4 pins the team runtime |
| Data and synthesis | Pandas, NumPy | P0 | WS1 |
| Forecast models | LightGBM; XGBoost only as a coordinated alternative | P0 | WS1; two targets, one chosen library |
| Temporal evaluation | scikit-learn metrics and chronological splits | P0 | WS1 |
| Multi-objective optimization | pymoo, NSGA-II | P0 | WS2 |
| Dashboard | Streamlit | P0 | WS4 |
| Charts | Plotly | P0 | WS4 |
| Risk | NumPy; SciPy only if required | P1 | WS3 |
| Forecast explainability | SHAP | P1 | WS1 |
| External adapters | requests, normalized CSV snapshots | P1 | WS3 |
| LLM and tool chat | Floating Streamlit assistant; model provider behind an adapter: remote Ollama server running `llama3.1:8b` (not on developer machines), explicit mock for development/tests | P2 | WS4 |
| Tests | pytest, schema validators | P0 | Each owner; WS4 coordinates CI |
| Storage | CSV/JSON and local model artifacts | P0 | File-based; no initial database |

No initial FastAPI, React, database, or LIME is required. Internal API means Python interfaces plus JSON serialization, not a web server. Choose and lock exact dependency versions during C0 after a clean installation and import check; the plan does not claim an unverified current version combination.

## 3. Ownership and dependency boundaries

| Developer | Workstream | Owns | Consumes | Publishes |
|---|---|---|---|---|
| 1 | [Data + ML](docs/workstreams/01_DATA_ML.md) | `src/data/`, `src/forecasting/`, `src/explainability/` | Schemas; future driver policy | History, baseline, backtest, SHAP |
| 2 | [Actions + Optimization](docs/workstreams/02_ACTIONS_OPTIMIZATION.md) | `src/actions/`, `src/optimization/` | Baseline; shared types | Simulation, search candidates, Pareto |
| 3 | [Risk + Benchmark](docs/workstreams/03_RISK_BENCHMARK.md) | `src/risk/`, `src/benchmarking/` | Simulator callable; normalized peer data | Risk summaries, benchmark result |
| 4 | [UI + Integration](docs/workstreams/04_DASHBOARD_INTEGRATION.md) | `app.py`, `src/dashboard/`, `src/integration/`, `src/llm/` | All public provider interfaces | Dashboard, orchestration, scenario compare |

WS4 is shared-file steward for `src/contracts/`, `tests/contracts/`, dependency files, CI, and documentation links. Stewardship means coordinating edits, not defining all domain logic. WS1 approves baseline fields, WS2 approves action semantics, WS3 approves uncertainty and benchmark fields. Cross-boundary changes require both producer and consumer approval.

Production dependencies flow inward to contracts. WS1 does not import actions, risk, dashboard, or optimization. WS2 does not import risk or dashboard. WS3 receives a simulator callable rather than depending on optimizer internals. WS4 wires providers. No domain module imports Streamlit.

## 4. Repo target layout

~~~text
carbonopt-ai/
├── README.md
├── IMPLEMENTATION_PLAN.md
├── app.py
├── pyproject.toml
├── requirements.txt
├── requirements-p1.txt
├── requirements-p2.txt
├── .env.example
├── .gitignore
├── config/
│   ├── default.json
│   ├── action_assumptions.json
│   └── uncertainty.json
├── data/
│   ├── company_timeseries.csv
│   ├── benchmark.csv
│   └── provenance.json
├── models/
│   └── .gitkeep
├── src/
│   ├── __init__.py
│   ├── contracts/      # types, validation, serialization, protocols
│   ├── data/           # generate, features, drivers
│   ├── forecasting/    # train, predict, backtest
│   ├── explainability/ # shap_analysis
│   ├── actions/        # definitions, engine
│   ├── optimization/   # optimizer, constraints, pareto, recommendation
│   ├── risk/           # monte_carlo
│   ├── benchmarking/   # adapters, normalize, benchmark
│   ├── integration/    # services, pipeline, cache_keys
│   ├── dashboard/      # components, charts, state
│   └── llm/            # assistant, tools
├── tests/
│   ├── contracts/
│   ├── fixtures/
│   ├── mocks/
│   ├── unit/
│   └── integration/
├── examples/
└── docs/
~~~

Do not commit generated model binaries, API credentials, large simulation samples, or private company data. C0 defines ignore rules. Shared model artifacts carry a metadata sidecar and are rebuilt from versioned inputs. The documentation package itself contains Markdown and contract examples; it does not create the target source tree.

## 5. Priority and exact acceptance sequence

| Order | Deliverable | Priority | Owner | Acceptance dependency | Can start before dependency? |
|---:|---|---|---|---|---|
| 0 | Contracts, fixture kit, stubs, skeleton | P0 | WS4 + all reviewers | Team agreement | Immediate |
| 1 | Synthetic single-company monthly history | P0 | WS1 | C0 | Yes |
| 2 | 12-month baseline forecast | P0 | WS1 | History | Features and fixture pipeline first |
| 3 | Temporal backtesting and naive comparator | P0 | WS1 | Forecast | Split and metric tests first |
| 4 | Six-action deterministic engine | P0 | WS2 | Baseline contract | Yes, baseline fixture |
| 5 | Manual what-if service | P0 | WS2 / WS4 UI | Real simulator | Yes, simulation stub |
| 6 | Budget/profit/target-constrained NSGA-II | P0 | WS2 | Simulator | Yes, toy evaluator |
| 7 | Feasible, validated Pareto output | P0 | WS2 | Optimizer | Yes, fixed candidate table |
| 8 | Integrated dashboard and MVP tag | P0 | WS4 | Steps 1–7 | Yes, all stubs |
| 9 | Monte Carlo and risk-aware recommendation | P1 | WS3 / WS2 / WS4 | P0 simulator + frontier | Yes, injected simulator stub |
| 10 | Forecast SHAP | P1 | WS1 | Trained model | UI panel can start from fixture |
| 11 | External benchmark adapter and normalization | P1 | WS3 | Baseline + compatible dataset | Yes, synthetic peer fixture |
| 12 | Conservative/balanced/aggressive comparison | P1 | WS4 | P1 risk + shared selection policy | Yes, risk fixtures |
| 13 | Structured-result explanation | P2 | WS4 | Verified result bundle | Yes, template fallback |
| 14 | Allowlisted tool chatbot (floating assistant, remote Ollama adapter, labelled mock) | P2 | WS4 | Stable providers | Yes: tool validation and mock-model flow first; see [chatbot plan](../docs/CHATBOT_IMPLEMENTATION.md) |

Baseline target horizons are 12/36/60 months in the contract. P0 providers implement only 12 months and raise `UnsupportedHorizon` for 36/60. UI hides longer horizons until the forecast provider advertises support; no silent extension.

## 6. Parallel execution and checkpoints

Reference schedule: a 48-hour hackathon with four developers. These are timeboxes, not promises. A 24-hour event keeps the same gates and cuts optional work sooner.

| Window | WS1 | WS2 | WS3 | WS4 | Gate |
|---|---|---|---|---|---|
| Hours 0–2 | Baseline fields and fixture review | Action/cost semantics review | Risk/peer fields review | Shared skeleton + stubs | C0 freeze |
| Hours 2–8 | Generate history, lag features, train | Simulator against golden baseline | Monte Carlo with injected stub; peer normalization | Full UI against stubs; provider registry | Parallel development |
| Hours 8–16 | Recursive forecast + rolling backtest | Real simulator, what-if; NSGA-II toy tests | Risk tests and offline benchmark; prepare adapter | Replace forecast/simulation providers separately | C1 baseline, C2 simulation |
| Hours 16–24 | Fix evaluation/model quality; publish artifacts | Real constrained search + Pareto | Validate real simulator trials on branch | Integrate P0, empty/error states, demo | C3 optimizer, C4 MVP |
| Hours 24–36 | SHAP | Risk selection support + frontier checks | Risk then benchmark release | Risk then SHAP then benchmark panels | C5a/b/c in source order |
| Hours 36–42 | Integration review | Performance and selection audit | Peer compatibility and failure audit | Scenario comparison | C6 |
| Hours 42–48 | Freeze and demo support | Freeze and demo support | Freeze and demo support | Optional P2 only if gates pass | C7 or P0/P1 release |

If C4 is late, freeze feature scope at P0. WS3 still contributes deterministic mock parity, simulation boundary tests, and offline demo support. Do not block P0 on network access or P1 imports.

Read [the integration guide](docs/INTEGRATION_GUIDE.md) for each gate's evidence, merge order, and mock removal policy.

### P2 chatbot plan and remote inference decision

The chatbot is a floating assistant inside the existing Streamlit dashboard. The language model does **not** run on developer machines or in this repository: a separate Ollama inference server runs the instruction-tuned `llama3.1:8b` tag, and the application holds a configurable client (`CHATBOT_PROVIDER`, `OLLAMA_BASE_URL`, `OLLAMA_MODEL`). Flow: user message plus application-bound dashboard context, then model interpretation, then application validation of proposed tool arguments, then execution by the existing services, then a result card and a concise grounded explanation. The model interprets language and explains results; it never calculates. Development and CI use an explicitly labelled mock model, and no step requires a live server. Implementation order: provider adapters, context binding, tools and limits, floating UI, live verification against a real endpoint (not yet done). Details: [docs/CHATBOT_IMPLEMENTATION.md](../docs/CHATBOT_IMPLEMENTATION.md).

## 7. Shared handoff artifacts

Every handoff includes contract version, fixture revision, seed, config/assumption IDs, exact command from repository root, a sample serialized result, test evidence, and known limitations. Producers hand off validated public objects, never notebook-specific variables or personal file paths.

| Boundary | Producer → consumer | Required artifact |
|---|---|---|
| History → forecast | WS1 → WS1 | Monthly schema-valid CSV + provenance |
| Baseline → simulator | WS1 → WS2/WS3/WS4 | BaselineBundle JSON + frame conversion + 12 rows |
| Simulator → optimization/risk/UI | WS2 → WS2/WS3/WS4 | No-op and nonzero SimulationResult fixtures |
| Pareto → dashboard/risk | WS2 → WS4/WS3 | Stable IDs, normalized config, objective units, status |
| Risk → recommendation/UI | WS3 → WS2/WS4 | Per-strategy risk IDs and distribution summary |
| SHAP → UI | WS1 → WS4 | Feature-level explanation with prediction units |
| Benchmark → UI | WS3 → WS4 | Source/method compatibility + percentile semantics |

## 8. Definition of done and release gates

A module is done when its public contract validates; deterministic tests pass; invalid inputs yield defined errors; units and assumptions are documented; it imports without UI/network side effects; it has a consumer review and a handoff fixture; and provider substitution needs no consumer rewrite.

P0 is done when one fully real run goes from generated history through evaluated forecast, simulator, feasible optimization, frontier and dashboard; a manual slider result matches a direct simulator result; budget and target constraints are respected; no-op is exact; infeasible cases are visible; mock provenance is absent from accepted P0 domain outputs; all standard tests run offline; and performance is measured on the team's declared demo configuration.

P1 is done feature-by-feature in source order. Report probabilities only from actual risk results; show benchmark coverage and SHAP interpretation limits. P2 is done only if explanations preserve numerical results, tool arguments validate, and provider failure is reported visibly and recovers cleanly (a remote failure is never silently replaced by mock output; a deterministic template explanation is allowed only where labelled).

Performance starting budgets: a deterministic simulation under 20 ms, 2,000 optimizer evaluations under 20 seconds, and 1,000 trials for one selected strategy under 5 seconds. These are team tuning targets on a documented shared demo profile, not guarantees across machines. Measure before raising sample counts or extending horizons.

## 9. Demo and submission

Demo flow: labelled company history → baseline and backtest metrics → budget/profit/target inputs → optimize → inspect feasible Pareto trade-offs → choose strategy → adjust action sliders → compare impacts → P1 risk/SHAP/benchmark if available.

Tag the accepted P0 commit `mvp-working`. Freeze demo seed and configuration, retain an offline mode, record known assumptions and limitations, and save the real accepted result bundle for troubleshooting. A saved bundle may support a clearly labelled replay; it must not be presented as a fresh live computation.
