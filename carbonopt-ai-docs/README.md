# CarbonOpt AI — Developer Documentation

This package turns the agreed single-company CarbonOpt AI technical plan into four independent workstreams with shared contracts and an explicit integration sequence. It is a documentation handoff, not an implemented application.

Start with [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md), then read the shared contracts and your assigned workstream. Copy the contents of this folder to the application repository root, retaining the relative directory structure. Every source, configuration, fixture, and command path in the documentation is relative to that root.

## Reading map

| Document | Purpose |
|---|---|
| [Central implementation plan](IMPLEMENTATION_PLAN.md) | Scope, priorities, ownership, exact implementation order, milestones |
| [Shared contracts](docs/SHARED_CONTRACTS.md) | Python interfaces, result types, error behavior, dependency rules |
| [Canonical schemas](docs/DATA_SCHEMAS.md) | DataFrames, JSON, units, validation, example payloads |
| [Action model](docs/ACTION_MODEL.md) | One deterministic simulator, action interactions, financial accounting |
| [Forecasting specification](docs/FORECASTING_SPEC.md) | Leakage-safe features, future drivers, recursive prediction, evaluation |
| [Risk and benchmark specification](docs/RISK_AND_BENCHMARK_SPEC.md) | Monte Carlo, recommendation policy, external data compatibility |
| [Integration guide](docs/INTEGRATION_GUIDE.md) | Checkpoints, merge order, branches, handoffs, provider wiring |
| [Tests and mocks](docs/TESTING_AND_MOCKS.md) | Fixtures, stub parity, acceptance tests, failure cases |
| [Workstream 1](docs/workstreams/01_DATA_ML.md) | Data, ML forecasting, backtesting, SHAP |
| [Workstream 2](docs/workstreams/02_ACTIONS_OPTIMIZATION.md) | Action engine, optimization, Pareto |
| [Workstream 3](docs/workstreams/03_RISK_BENCHMARK.md) | Risk, Monte Carlo, external benchmarking/API |
| [Workstream 4](docs/workstreams/04_DASHBOARD_INTEGRATION.md) | Streamlit, Plotly, integration, optional LLM/chatbot |
| [Decision register](docs/DECISIONS.md) | Frozen assumptions, unresolved implementation choices, change process |
| [Fixture examples](examples/README.md) | Machine-readable contract examples and their intended use |

## First team session

1. Assign one developer to each workstream and one reviewer per boundary.
2. Read and approve contract version `1.0.0` together.
3. Establish the shared skeleton, validators, deterministic fixtures, and provider stubs at checkpoint C0.
4. Each developer starts locally against stubs; replace one provider at a time as real components pass contract tests.
5. Keep the original feature acceptance order even while implementation happens in parallel.

The application bootstrap commands, source paths, and tests described here are implementation targets. They become runnable after the corresponding skeleton and modules are implemented. JSON files in `examples/` are available now; they describe contracts and illustrative synthetic results.

## Product boundaries

P0 delivers a 12-month baseline forecast, reproducible temporal evaluation, six-action what-if simulation, constrained two-objective optimization, Pareto selection, and a working Streamlit dashboard. P1 adds risk, SHAP, compatible benchmarks, and scenario comparison. P2 adds explanation and tool-driven chat.

Synthetic monthly history, counterfactual action assumptions, risk estimates, and example benchmarks must remain visibly labelled. Longer horizons and real reported history use the same interfaces when their data requirements are met.
