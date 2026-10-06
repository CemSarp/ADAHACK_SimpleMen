# Assistant (chatbot)

A floating assistant inside the dashboard. The language model reads the question, picks tools and explains
the results; every number comes from a tool that runs through the same services as the page. The model never
computes, never sees raw data files and cannot choose a company, provider, endpoint or file.

```text
question + compact dashboard context (server-built)
  -> model (guided assistant, LM Studio or Ollama)
  -> proposed tool call(s)
  -> app validates the tool name and every argument
  -> the bound Services run the tool (simulator, optimizer, risk, SHAP, ...)
  -> JSON result back to the model -> short answer + result card in the panel
```

## 1. Modules

| Path | Responsibility |
| --- | --- |
| `src/llm/config.py` | `ChatbotConfig.from_env()`; validation; no network |
| `src/llm/types.py` | `ChatMessage`, `ToolCall`, `ModelResponse`, `ToolSpec` |
| `src/llm/providers.py` | `MockChatProvider` (guided assistant), `LMStudioChatProvider`, `OllamaChatProvider`, typed `Chat*Error`s |
| `src/llm/context.py` | `AnalysisContext` (server-bound) and its compact model-facing `summary()`; `version` hash |
| `src/llm/prompt.py` | System prompt: tool routing, action semantics, answer rules, data-kind rule |
| `src/llm/tools.py` | Allowlist, JSON schemas, argument validation, `execute_tool()` |
| `src/llm/insights.py` | Read-only data views: company profile, action comparison, Wincanton reference |
| `src/llm/summaries.py` | Deterministic text summaries of tool results (guided assistant and fallback answers) |
| `src/llm/assistant.py` | One turn: model -> tools -> answer, with limits and a duplicate-call cache |
| `src/dashboard/chat_state.py` | Conversation in `st.session_state` (`coc_` prefix), retries, suggestions |
| `src/dashboard/chat_ui.py` | Floating button, panel, result cards, Apply buttons |

Action names and forecast-input names in tool results come from `src/dashboard/presentation.py`, so the chat
and the page use the same words ("EV fleet adoption", "Same month last year").

## 2. Providers and configuration

| `CHATBOT_PROVIDER` | What answers | Transport |
| --- | --- | --- |
| `mock` (default) | **Guided assistant**: deterministic rules that recognise preset questions and call the real tools. Not a language model. Runs offline. | none |
| `lmstudio` | A local model served by LM Studio, e.g. `google/gemma-4-12b` | OpenAI-compatible `POST {base}/chat/completions`, `tool_choice: "auto"`, `temperature: 0` |
| `ollama` | A model on an Ollama server you point it at | Native `POST {base}/api/chat`, `stream: false`, `temperature: 0` |

The app does not auto-load `.env`; export the variables in your shell (see `.env.example`).

| Variable | Meaning | Default |
| --- | --- | --- |
| `CHATBOT_PROVIDER` | `mock`, `lmstudio` or `ollama` | `mock` |
| `LMSTUDIO_BASE_URL` | LM Studio server | `http://localhost:1234/v1` |
| `LMSTUDIO_MODEL` | Model identifier as LM Studio lists it | `google/gemma-4-12b` |
| `LMSTUDIO_TIMEOUT_SECONDS` / `LMSTUDIO_MAX_OUTPUT_TOKENS` | Limits. Gemma 4 thinks before it answers, so keep both generous | `300` / `4096` |
| `LMSTUDIO_API_KEY` | Only if LM Studio's server authentication is on | none |
| `OLLAMA_BASE_URL` | Required for `ollama`: `http(s)://host[:port]`, no credentials, query or fragment | none |
| `OLLAMA_MODEL` / `OLLAMA_TIMEOUT_SECONDS` / `OLLAMA_MAX_OUTPUT_TOKENS` | Model tag and limits | `llama3.1:8b` / `60` / `512` |
| `OLLAMA_API_KEY` | Optional bearer token for a gateway | none |

```bash
lms server start && lms load google/gemma-4-12b      # LM Studio's CLI
CHATBOT_PROVIDER=lmstudio python -m streamlit run app.py
```

Invalid configuration shows a generic "assistant unavailable" message in the panel (details in the server
log) and the dashboard keeps working. A configured remote model is never replaced by the mock when it fails.

LM Studio details: tool results are paired with the id of the call they answer (ids are generated when a
model omits them); inline `<think>…</think>` reasoning is stripped; when the model spends its whole token
budget thinking (`finish_reason: "length"` with no text), the panel says so instead of failing.

## 3. What the model knows

`AnalysisContext` is built by the app from the dashboard state: services, current request (goals), baseline,
analysis (if a search ran), the selected plan and the company history. The model only receives
`context.summary()`, a compact JSON object in the system message:

- company ID, data kind (`synthetic` demo or the user's own `reported` upload), mock flags;
- baseline ID, period, model ID and totals (emissions in tCO₂e, money in GBP, over the 12-month horizon);
- the goals: budget, profit floor, CO₂ target (a 0–1 ratio);
- whether a search ran, the recommended plan ID, and the selected plan's action mix and totals, or a note
  that no plan is selected yet and **Find plans** creates one.

No monthly data or files are sent. `context.version` hashes baseline, goals, analysis run, selection and
provider versions; result cards remember the version that produced them.

The system prompt adds one rule depending on the data kind: the demo company is synthetic; an upload is the
user's own figures with illustrative costs scaled to it.

## 4. Tools

Eight allow-listed tools. Unknown tools and malformed arguments are rejected before anything runs, with a
message the model can read and correct (for example `80` for a ratio is rejected with "pass 0.8 for 80%").

| Tool | Arguments | Returns | Used for |
| --- | --- | --- | --- |
| `get_baseline` | none | Forecast totals and period; `forecast`: model name, average monthly miss on the last 12 reported months vs simply repeating last year (emissions and profit), what the data import changed | "Show the forecast", "how accurate is it", "which model" |
| `get_company_profile` | none | Last 12 months vs the 12 before (emissions by scope with shares, revenue, profit, margin, intensity, activity), current renewable/EV shares, what each scope contains, what the data does **not** report (including missing scopes), forecast vs history | "Where do our emissions come from?", trends |
| `get_forecast_drivers` | `top_k` 1–20 (default 5) | Per forecast (emissions, operating profit): the top *k* inputs with plain names, share of the forecast's movement (mean \|SHAP\|), whether each pushes it up or down, and the share the top *k* carry | "What drives the forecast?" |
| `compare_actions` | none | Each action alone at full take-up through the simulator: CO₂ cut, profit change, outlay, £ per tonne; ranked; actions with no effect for this company | "Which action cuts the most / is cheapest per tonne?" |
| `simulate_strategy` | `actions` (fraction of the remaining opportunity, 0–1, per action), `final_shares` (final renewable / EV share, 0–1), `start_from` (`no_action` or `selected_strategy`) | Metrics, final shares before/after, share conversions, check against the current goals, notes (including actions that do nothing for this company) | What-ifs; explaining the selected plan |
| `optimize_strategies` | optional `budget_gbp`, `min_total_profit_gbp`, `min_co2_reduction_ratio` (0–1) | Status, goals used, number of best trade-offs, the recommended mix and metrics; when no plan meets the goals, `how_to_meet_goals` (budget needed, highest reachable profit floor, deepest cut within budget and floor, deepest cut tried) | "Find a plan within £500k", "can we reach 40% with £1m?" |
| `get_risk_summary` | optional `strategy_id` (default: the selected plan) | Monte Carlo probabilities of meeting each goal and p05–p95 outcomes | "How likely are we to meet the target?" |
| `get_public_reference` | optional `electricity_reduction_ratio` (0–1) | Wincanton FY2024 figures (a separate real company), derived shares, a plain Scope 1/2/3 explanation, an optional GOV.UK-factor scenario | Wincanton comparisons |

Rules enforced in `tools.py`:

- Ratios only; percentages above 1 are rejected with the ratio to use instead.
- `actions` values are fractions of the **remaining** opportunity. A final share target converts as
  `x = (target − v) / (1 − v)` (divided by the action's effectiveness when it is below 1), with `v` the month-1
  share; `v = 1` needs no action; targets below the current share are rejected (actions only add adoption).
  An action may not appear in both `actions` and `final_shares`.
- Omitted optimizer goals keep the dashboard's; chat searches are capped at 512 evaluations and risk at
  1,000 trials. Chat results are previews: nothing on the page changes until the user presses Apply.
- `get_forecast_drivers` reuses the analysis' explanation when the search computed one, otherwise asks the
  SHAP provider. A forecast made by a non-tree model has no drivers (`status: "unavailable"`).

## 5. One turn

`run_turn` (in `assistant.py`) sends the system message, the last 12 conversation messages and the question,
then loops up to 4 model rounds:

- at most **3 tool executions per user message**; further calls get a limit error and the answer says so;
- an identical call (same tool, arguments and context version) is answered from the turn record, so it is not
  run or counted twice, and **Retry** after a failure never re-runs a completed tool;
- invalid arguments do not use up an execution;
- if the model ends without text, the answer is the deterministic summary of the last tool result.

The prompt tells the model which tool answers which kind of question (section 4), that what-ifs and searches
work without a selected plan (`start_from: "no_action"`), that "all of the remaining" means 1.0, to ask one
short question when a number is genuinely ambiguous (80 vs 0.8), to suggest a concrete change from
`how_to_meet_goals` when nothing is feasible, never to recommend an action with no effect, and to say plainly
when data is missing or a tool is unavailable.

## 6. Panel and result cards

- A round button at the bottom-right opens the panel; three sizes (compact, large, full width); the
  conversation area can be dragged taller. Conversation and open state live under `coc_` in session state,
  separate from the dashboard (`cos_`): clearing the chat leaves the dashboard alone.
- Suggested questions appear while the conversation is empty.
- **Action cards**: forecast, what-if (with **Apply to dashboard**, which loads the exact mix into the
  *Your mix* sliders), plan search (with **Load recommended into what-if**, or the budget that would work when
  nothing is feasible) and uncertainty.
- **Data cards** (collapsed): company data, action comparison, Wincanton reference, forecast drivers, so the
  answer can be checked against the facts the model was given.
- When the context changes (new goals, new search, another data set or model), old cards are marked as from a
  previous context and their Apply buttons are disabled.

## 7. Errors

| Condition | Behaviour |
| --- | --- |
| Missing endpoint or invalid configuration | "Assistant unavailable" in the panel; no mock fallback |
| Timeout, connection error, HTTP error, unknown model | Error in the message with **Retry**; the question is kept |
| Invalid tool name or arguments | Error result returned to the model, which can correct itself |
| Tool limit reached | Remaining calls get a limit error; the answer notes it |
| No plan meets the goals | A valid result with `how_to_meet_goals`, not an error |
| Optional capability missing (risk, SHAP) | `status: "unavailable"` with the reason |
| Model spent its budget thinking (LM Studio) | A message asking for a narrower question or a larger `LMSTUDIO_MAX_OUTPUT_TOKENS` |

## 8. Verified with Gemma 4

Checked live on 2026-10-05 with `google/gemma-4-12b` (MLX 4-bit) in LM Studio, through `run_turn` on the
demo company (with and without a search) and on `data/sample_upload.csv`. 31 questions; after the prompt and
tool fixes every one called the expected tool with valid arguments. Answers took about 5–45 seconds.

| Question | Tool and arguments the model chose |
| --- | --- |
| Where do our emissions come from? | `get_company_profile` |
| Which action cuts the most CO₂? / cheapest per tonne? | `compare_actions` |
| What if EV share becomes 80%? (no plan selected) | `simulate_strategy` `final_shares.ev_adoption = 0.8`, `start_from = no_action` |
| What if we take up half of the remaining renewable opportunity and cut travel by 30% of what is left? | `simulate_strategy` `actions = {renewable_energy: 0.5, travel_reduction: 0.3}`; answer says travel has no effect for this company |
| What if we switch all remaining electricity to renewable? | `simulate_strategy` `actions.renewable_energy = 1` |
| Find a plan within a £5m budget. | `optimize_strategies` `budget_gbp = 5000000` |
| Can we reach a 40% cut with £1m? | `optimize_strategies` `budget_gbp = 1000000, min_co2_reduction_ratio = 0.4`; answer gives the deepest cut within £1m and the budget that would work |
| How accurate is the forecast and which model is used? | `get_baseline`; answer quotes both misses and "Random forest" |
| What drives the emissions forecast? | `get_forecast_drivers` `top_k = 5` |
| Explain the selected strategy. / How likely are we to meet our target? (no plan) | no tool; says there is no plan yet and points to **Find plans** |
| Explain the selected strategy. (after a search) | `simulate_strategy` `start_from = selected_strategy` |
| How likely is the selected plan to meet our goals? | `get_risk_summary` with the selected plan's ID |
| How do we compare with Wincanton? | `get_company_profile` + `get_public_reference` |
| What if EV share becomes 50%? (upload without a fleet) | `simulate_strategy`; answer says EV adoption has no effect for this company |

To repeat the check, open the panel with `CHATBOT_PROVIDER=lmstudio` and ask the questions above; each answer
shows its cards, so you can see which tool ran and with what result. A small local model can still word a
number loosely (for example "at least" where the tool says "about"); the cards show the exact values.

## 9. Tests

All offline (`tests/unit/test_chat_*.py`, `tests/integration/test_chat_ui.py`, chat cases in
`tests/integration/test_upload.py`): configuration, provider wire formats with an injected fake transport
(Ollama and LM Studio), the allowlist and every argument rule, share conversion, the new tool outputs (model
and accuracy, drivers, infeasible hints, no-effect notes), context binding and versioning, limits and
duplicate/retry dispatch, prompt rules (Find plans, data kind, what-ifs without a plan), card rendering and
staleness, and the panel through Streamlit's AppTest. `tests/integration/test_ollama_live.py` is an opt-in live
check (`RUN_OLLAMA_LIVE_SMOKE=1` with `OLLAMA_BASE_URL`).

## 10. Not done

- Streaming of the final answer (complete responses keep partial tool arguments from ever running).
- Programmatic focus on the input when the panel opens (no supported Streamlit API).
