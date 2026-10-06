# Frozen Decisions and Change Register

## Contract baseline

Contract version is `1.0.0`. Names, types, units, action meanings, result statuses, and core accounting below are frozen at C0. Values described as illustrative remain configurable.

| ID | Decision | Reason / consequence | Change approvers |
|---|---|---|---|
| D01 | Single-company monthly history; synthetic P0 | Reproducible 204-row example; real history is an adapter later | WS1 + WS4 |
| D02 | Backtesting is P0 | Source placement varies; credible forecast requires temporal evaluation | WS1 + WS4 |
| D03 | Python 3.11 reference runtime; ~~LightGBM default~~ (model choice superseded by D26) | Minimize initial installation and model duplication | WS1 + WS4 |
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
| D15 | ~~Chat model runs on a separate remote Ollama server, never on developer machines~~ Superseded by D31; still no weights or servers in this repo | Avoids local weights/infrastructure; the app ships only a configurable client | WS4 + deployment owner |
| D16 | Model tag is configurable (`OLLAMA_MODEL`), default `llama3.1:8b` (instruction-tuned tag) | Model can change without code changes | WS4 |
| D17 | Mock chat mode is explicit (`CHATBOT_PROVIDER=mock`), labelled, and never a fallback for a failed remote call | Prevents mock output being mistaken for model output | WS4 |
| D18 | Chat UI is a floating bubble opening a panel inside the Streamlit dashboard (bottom-right, D32) | Keeps the assistant available without leaving the dashboard | WS4 |
| D19 | LLM interprets and explains; allowlisted tools through existing services compute; chat what-if is a preview applied by an explicit button | Preserves single-simulator and ownership boundaries | WS2 + WS4 |
| D20 | Company data enters only through one explicit import adapter (`config/company_import.json` or the mapping built for an upload); unreported activities are 0 with a recorded reason. ~~Problems are rejected, not repaired~~: superseded by D27 | Keeps data lineage explicit | WS1 + WS4 |
| D21 | EUR money converts to GBP at a configured fixed rate (0.85, illustrative) and EBITDA is the operating-profit series for the supply-chain CSV | The contract is GBP and the CSV reports no depreciation; both are visible assumptions | WS1 + WS2 + WS4 |
| D22 | WS1 artifacts are trained once and cached by an identity hash of data, mapping, settings, WS1 code and library versions | No training on reruns; a stale model is never reused | WS1 + WS4 |
| D23 | Company-specific WS2 assumptions and WS3 benchmark config bind only to the real CSV-backed forecast | A baseline is never paired with another company's economics | WS2 + WS3 + WS4 |
| D24 | Activities use a deterministic seasonal driver policy and scopes are reconciled to WS1's total forecast | WS1 forecasts only totals; WS2 needs activities and scopes | WS1 + WS2 |
| D25 | SHAP explains WS1 tree models in their relative raw output space | Explains the deployed model honestly; not tonnes or GBP | WS1 + WS4 |
| D26 | The planning forecast fits one model: Random forest from 60 months of history, the seasonal repeat below. XGBoost, LightGBM and Prophet run only when the user asks (`compare_models`), and a chosen model becomes part of the cache identity | Running every model before the page loaded took ~5 minutes per dataset and kept choosing Random forest | WS1 + WS4 |
| D27 | Imports repair what they safely can (sorting, interpolating gaps, percentages to shares, totals/scopes/electricity derived, profit = revenue − cost) and list every change; they refuse duplicates, fewer than 24 months, unreadable dates and inconsistent totals | Real tables have gaps; visible notes keep lineage honest | WS1 + WS4 |
| D28 | Uploads are matched by role, not by a fixed layout: date, revenue, profit (or cost) and emissions are required; each optional activity column unlocks the actions that act on it; actions without data get zero share and zero cost and are hidden with what they need | Every dataset names and reports different things | WS1 + WS2 + WS4 |
| D29 | Upload action costs are the demo assumptions scaled by the company's addressable activity and stay labelled illustrative; starting goals are sized to the company (budget ≈ 8% of yearly revenue, floor ≈ 80% of yearly profit, 10% cut) | No calibrated costs exist for arbitrary companies | WS2 + WS4 |
| D30 | When no plan meets the goals, hints come from the candidates the search already evaluated, one goal loosened at a time, rounded towards a goal that works and worded "about" | No extra search; numbers stay traceable to evaluated mixes | WS2 + WS4 |
| D31 | The chat model may run locally in LM Studio (default `google/gemma-4-12b`) or on an Ollama server; the guided assistant stays the offline default | A local model makes real-language answers possible without infrastructure | WS4 |
| D32 | The chat bubble sits at the bottom-right | At the bottom-left it covered the sidebar's Find plans button | WS4 |
| D33 | Chat tools return pre-computed, labelled numbers (forecast model and accuracy, top-*k* drivers, how to meet goals, actions with no effect); the prompt maps question types to tools and stays under 6,000 characters | Verified live with Gemma 4: small models route well when the facts are ready-made and the rules are short | WS4 |
| D34 | Forecast drivers explain whichever forecast is bound (demo or upload, chosen model); a non-tree model has no drivers | A driver chart for a different model would be wrong | WS1 + WS4 |

## Decisions to resolve during implementation

These do not block C0 contracts: compatible package pins, model hyperparameters, real benchmark provider and dataset licence, source emission factors, calibrated action capex/effect coefficients, final sample budgets, and, if a shared chat server is deployed, its endpoint, gateway authentication and hardware sizing (the provider decisions are D17, D19 and D31).

For each, record the selected value, evidence, reviewer, configuration ID, and affected fixture revision in the relevant configuration or provenance artifact. Illustrative default values are sufficient for synthetic demonstrations when labelled. Never claim they are calibrated company economics.

Real company selection is outside the initial package scope. If annual company data is introduced, preserve reported frequency and label any interpolation; generated monthly observations are not independent reported measurements.

## Pending change requests (WS2–WS4 integration)

Made while merging WS4's contract package into `workstream2`; each is pinned by `tests/contracts/test_shared_contract_changes.py`. They are additive or stricter validation within 1.0.x and await the listed approvals.

| ID | Change | Approvers |
|---|---|---|
| R01 | `ConstraintEvaluation.satisfied` and `RecommendationResult.diagnostics` additive optional fields | WS2 + WS3 + WS4 |
| R02 | `pareto_rank = 1` marks feasible but dominated candidates | WS2 + WS4 |
| R03 | Assumption files reject unknown fields, booleans as numbers and non-integral `asset_life_months` | WS2 + WS3 + WS4 |
| R04 | `target_probability_mc_standard_error` null exactly when `target_probability` is null | WS3 + WS4 |
| R05 | Optimizer seeds must be nonnegative; strategy identity maps `-0.0` to `0.0` | WS2 + WS4 |
| R06 | `pymoo==0.6.2` joins the pinned requirements | WS2 + WS4 |

## Contract change workflow

Open `contract/<short-change>` with an example of the incompatibility. Producer and affected consumer review the proposed field/signature and accounting effect. Update this register, shared types/validators, serialization, fixture kit, contract tests, and consumer adapters together.

Patch versions clarify behavior without changing shape. Minor versions add optional fields/capabilities with old fixtures still accepted. Major versions change required fields, action meaning, units, or output semantics. P0 rejects unknown major versions. Keep a migration adapter only when a real consumer needs it.
