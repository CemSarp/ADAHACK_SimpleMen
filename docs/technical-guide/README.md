# CarbonOpt project guide

These files now describe **CarbonOpt with Django + Plotly**, matching the latest technical implementation plan and confirmed team decision. Technical guidance lives in `docs/technical-guide/`; shared coordination and role plans live in `docs/team-execution/`.

**Start at [the shared team center](../team-execution/CENTER.md).** It is authoritative for contracts, ownership, priorities and integration gates. The four linked role files are the execution plans.

## Supporting guides

- [Architecture](01-architecture.md): current pipeline and module boundaries.
- [Build guide](02-build-guide.md): parallel implementation order and checkpoints.
- [Agent prompts](03-agent-prompts.md): shared context and links to each owner's iterations.
- [Edge cases](04-edge-cases.md): checks for the actual CarbonOpt model.
- [Sources](05-sources.md): source plan and status of older research.

P0 is synthetic monthly history → forecasting/backtest → shared action engine → manual what-if/NSGA-II → Pareto dashboard. P1 adds risk, SHAP, benchmarking and scenario comparison. P2 adds grounded LLM explanations/tools.

The older tariff JSON in `research/` is preserved as historical reference only. It is not CarbonOpt training data, a company benchmark or a required runtime dependency.

## How to start with four people

1. All four review CENTER's contracts, numerical rules and ownership boundaries.
2. D publishes the shared types and labelled 12-month fixture; A supplies its content and B/C verify what they need.
3. Each person reads their role file plus the relevant detailed sections here, then sends one coding-agent iteration at a time.
4. Complete manual simulation first, then the real forecast/optimiser/UI pipeline. Enable P1 only after the integrated P0 gate.
5. Reserve the final two hours for validation, fixes and rehearsal.

The detailed guides retain the original pack's practical depth: architectural reasons, formulas, data contracts, phased implementation, iterative prompts, edge cases and evidence checks. All active product guidance now concerns CarbonOpt. Shared contracts live in one place so supporting guides do not become competing specifications.
