# Frozen Decisions and Change Register

## Contract baseline

Contract version is `1.0.0`. Names, types, units, action meanings, result statuses, and core accounting below are frozen at C0. Values described as illustrative remain configurable.

| ID | Decision | Reason / consequence | Change approvers |
|---|---|---|---|
| D01 | Single-company monthly history; synthetic P0 | Reproducible 204-row example; real history is an adapter later | WS1 + WS4 |
| D02 | Backtesting is P0 | Source placement varies; credible forecast requires temporal evaluation | WS1 + WS4 |
| D03 | Python 3.11 reference runtime; LightGBM default | Minimize initial installation and model duplication | WS1 + WS4 |
| D04 | Forecast scopes are reconciled to total prediction | Simulator needs scope-consistent baselines | WS1 + WS2 |
| D05 | Action values are fractions of remaining eligible opportunity | Zero means no change; avoids renewable target/no-op ambiguity | WS2 + all consumers |
| D06 | CO₂ in tonnes; currency GBP; ratios 0–1 | Consistent schemas and graph axes | All four |
| D07 | Capex is cash, depreciation affects operating profit | Avoid subtracting capex twice or mixing cash/profit objectives | WS2 + WS3 + WS4 |
| D08 | Risk is a separate service using the simulator | Stable P0 signature; no randomness inside deterministic simulation | WS2 + WS3 |
| D09 | P1 risk reranks a bounded P0 frontier | Makes tolerance operational without a nested stochastic NSGA-II loop | WS2 + WS3 + WS4 |
| D10 | External benchmark data never trains P0 forecast | Independent provenance and failure boundaries | WS1 + WS3 |
| D11 | File-based local application; optional network features | Streamlit calls services directly | WS4 |
| D12 | P0 supports 12 months; 36/60 explicitly unsupported until tested | Avoid implying long-horizon credibility | WS1 + WS4 |
| D13 | Compact fixtures are illustrative synthetic examples | They validate integration shape, not scientific truth | All four |
| D14 | Shared schemas and documentation are authoritative | Consumers cannot privately rename fields | All four |

## Decisions to resolve during implementation

These do not block C0 contracts: compatible package pins, precise LightGBM hyperparameters, real benchmark provider and dataset licence, source emission factors, calibrated action capex/effect coefficients, final sample budgets, and optional LLM provider.

For each, record the selected value, evidence, reviewer, configuration ID, and affected fixture revision in the relevant configuration or provenance artifact. Illustrative default values are sufficient for synthetic demonstrations when labelled. Never claim they are calibrated company economics.

Real company selection is outside the initial package scope. If annual company data is introduced, preserve reported frequency and label any interpolation; generated monthly observations are not independent reported measurements.

## Contract change workflow

Open `contract/<short-change>` with an example of the incompatibility. Producer and affected consumer review the proposed field/signature and accounting effect. Update this register, shared types/validators, serialization, fixture kit, contract tests, and consumer adapters together.

Patch versions clarify behavior without changing shape. Minor versions add optional fields/capabilities with old fixtures still accepted. Major versions change required fields, action meaning, units, or output semantics. P0 rejects unknown major versions. Keep a migration adapter only when a real consumer needs it.
