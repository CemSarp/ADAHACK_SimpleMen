# CarbonOpt AI Chatbot: Implementation Plan

Branch: `feat/ws4-chatbot`. Owner: WS4. Priority: P2 (after C4/P1 gates; code is built early behind explicit configuration and does not change P0 behavior).

## 1. Architecture

A floating assistant lives inside the existing Streamlit dashboard. The language model does **not** run on the developer machine or in this repository. A separate Ollama inference server runs the instruction-tuned `llama3.1:8b` tag; the application only holds a configurable client for it.

```text
user message + application-bound dashboard context
  -> model provider (remote Ollama, or labelled mock)
  -> proposed tool call(s)
  -> application validates tool name and arguments
  -> existing CarbonOpt service executes the tool
  -> structured result card + concise explanation grounded in the result
```

The model interprets language and explains results. Forecasting, simulation, optimization, recommendation and risk stay in their existing providers. Nothing in this task downloads weights, installs or launches an inference server, or provisions infrastructure. No remote server is needed to develop or test.

Module layout (all under `src/llm/` except UI/state):

| Path | Responsibility |
| --- | --- |
| `src/llm/config.py` | `ChatbotConfig.from_env()`; validation; no network |
| `src/llm/types.py` | `ChatMessage`, `ToolCall`, `ModelResponse`, `ToolSpec` normalized types |
| `src/llm/providers.py` | `ChatModelProvider` protocol, `OllamaChatProvider`, `MockChatProvider`, typed `Chat*Error`s |
| `src/llm/context.py` | `AnalysisContext` (server-bound) and compact model-facing summary, `context_version` |
| `src/llm/tools.py` | Allowlist, JSON schemas, argument validation, `execute_tool()` |
| `src/llm/assistant.py` | Turn orchestration (tool loop, limits, duplicate-dispatch cache) |
| `src/llm/prompt.py` | System prompt |
| `src/dashboard/chat_state.py` | Conversation state in session (no Streamlit import) |
| `src/dashboard/chat_ui.py` | Floating bubble, panel, result cards |

## 2. Floating bubble behavior

- Closed: a small circular button fixed at the bottom-left of the viewport.
- Open: a compact panel above the button with a title, close control, clear-chat control, message history, suggested questions, text input and a sending indicator.
- Open/closed state and the conversation live in `st.session_state` under the `coc_` prefix, so closing and reopening keeps the conversation. The dashboard state prefix (`cos_`) is separate: clearing chat does not reset the dashboard, and a dashboard provider change does not delete the chat (it marks old cards stale).
- Mobile (`max-width: 640px`): the panel spans the viewport width minus a margin and is height-limited.
- The sidebar reserves bottom padding so the bubble does not cover the Optimize button.
- Implementation: `st.container(key=...)` (Streamlit adds the CSS class `st-key-<key>`), styled with a small injected stylesheet; `st.button`, `st.chat_input`, `st.chat_message` and `st.container(height=...)` for content. If the CSS is not applied, the same widgets render inline and remain fully usable. No JavaScript, no undocumented DOM selectors beyond that documented class name, no browser-side calls to the model or to tools.
- Accessibility: all controls are native Streamlit buttons/inputs with help text; contrast uses theme variables. Programmatic focus on open is not available through supported Streamlit APIs; this is a known limitation.

## 3. Provider interface and configuration

```python
class ChatModelProvider(Protocol):
    info: ProviderInfo
    def chat(self, messages: Sequence[ChatMessage], tools: Sequence[ToolSpec]) -> ModelResponse: ...
```

`ModelResponse` carries `text` and zero or more `ToolCall(name, arguments: dict)`. Provider-specific transport stays inside `providers.py`.

Environment variables (see `.env.example`; the app does not auto-load `.env`, export the variables in your shell):

| Variable | Meaning | Default |
| --- | --- | --- |
| `CHATBOT_PROVIDER` | `mock` or `ollama` | `mock` (labelled) |
| `OLLAMA_BASE_URL` | Remote endpoint, `http(s)://host[:port]`, no embedded credentials | none (required for `ollama`) |
| `OLLAMA_MODEL` | Model tag | `llama3.1:8b` |
| `OLLAMA_TIMEOUT_SECONDS` | Request timeout | `60` |
| `OLLAMA_MAX_OUTPUT_TOKENS` | Mapped to Ollama `options.num_predict` | `512` |
| `OLLAMA_API_KEY` | Optional bearer token if a gateway requires it | none |

Invalid values produce a visible configuration error in the panel; the dashboard keeps working. `ollama` mode without an endpoint never falls back to mock.

### Native Ollama interface used (verified against the current Ollama API documentation)

- `POST {base}/api/chat` with `{"model", "messages", "tools", "stream": false, "options": {"temperature": 0, "num_predict": N}}`.
- Tool definitions: `{"type": "function", "function": {"name", "description", "parameters": {JSON schema}}}`.
- Response: `message.content` and optional `message.tool_calls[].function.{name, arguments}` where `arguments` is an object (a JSON string is tolerated and parsed).
- Tool results go back as `{"role": "tool", "tool_name": "<name>", "content": "<json>"}`.
- Connection check (explicit user action only): `GET {base}/api/tags` and confirm the configured model tag is listed.
- Responses are complete (`stream: false`). Streaming of final text is intentionally not implemented in this iteration: partial output must never execute partial tool arguments, and the complete-response loop is the reliable baseline.

## 4. Conversation state and context binding

Every request is bound to an application-built `AnalysisContext`: company and baseline identity, user constraints (with units), selected strategy and exact config, result summaries, capabilities, mock/synthetic provenance, model/assumption/uncertainty IDs. The model receives a compact JSON summary, never datasets or artifacts.

Tool execution uses the bound context object only. The model cannot choose a company, baseline, provider, endpoint or file.

`context_version` is a hash of baseline ID, constraints, analysis run ID, selected strategy ID and the service/provider key. Result cards store the version that produced them. When it changes, cards are labelled "previous context" and their Apply action is disabled. Chat what-if results are previews; **Apply to dashboard** loads the exact config into the what-if sliders and never overwrites the selected plan or constraints.

## 5. Tools

Allowlist: `get_baseline`, `simulate_strategy`, `optimize_strategies`, `get_risk_summary`. Unknown tools and malformed arguments are rejected before dispatch with a `ToolResult(status="error")` that the model can read.

| Tool | Arguments | Notes |
| --- | --- | --- |
| `get_baseline` | none | Baseline totals, periods, provenance |
| `simulate_strategy` | `actions` (fractions of remaining opportunity, 0-1), `final_shares` (`renewable_energy`, `ev_adoption` final share, 0-1), `start_from` (`no_action` or `selected_strategy`) | Calls the bound simulator |
| `optimize_strategies` | optional `budget_gbp`, `min_total_profit_gbp`, `min_co2_reduction_ratio` (0-1) | Unspecified fields keep the dashboard constraints; evaluations capped at 512 |
| `get_risk_summary` | optional `strategy_id` (default selected) | Unavailable when risk is not available; trials capped at 1000 |

Rules: ratios only (a value such as `80` is rejected with a message asking for `0.8`, never guessed); explicit units in names; for a final adoption target `v_target` with baseline share `v` (month 1), `x = (v_target - v) / (1 - v)`; `v = 1` is handled without division (`x = 0`); targets below the current share are unsupported (adoption-only actions); a given action in both `actions` and `final_shares` is rejected. At most **3 tool executions per user message**; duplicate calls with identical arguments in the same context return the cached result and do not execute or count again. No shell, code, file or URL tools exist.

Optional dependencies: none. P0 startup does not import `src/llm` network code paths.

## 6. Mock versus remote

`MockChatProvider` is deterministic and rule-based (regex intent parsing, template summaries of tool results). It is labelled **MOCK MODEL** in the panel and in every assistant message, runs offline, and is used by tests and by default. It is not a language model; unsupported phrasing returns a clarification listing supported intents.

`OllamaChatProvider` talks to the configured endpoint through an injectable transport (default: standard-library HTTP; tests inject a fake). Backend services bound under mock mode remain labelled mock regardless of the chat provider.

## 7. Error handling

| Condition | Behavior |
| --- | --- |
| Missing endpoint/invalid config | Visible configuration error; no fallback |
| Timeout / connection error / HTTP 5xx / 404 model | Typed error shown in the message with a Retry control; the user message is kept |
| Invalid model JSON or tool arguments | Tool error returned to the model once per call; shown to the user if unresolved |
| Tool limit reached | Remaining calls get a limit error; user is told |
| Infeasible optimization | Valid result card "no feasible plan found" |
| Unavailable backend (e.g. risk) | `ToolResult(status="unavailable")` with reason |
| Context changed | Old cards marked previous; Apply disabled |

Retry re-runs the model loop for the same turn but reuses completed tool results, so a completed tool is never executed twice.

## 8. Tests

Offline only: provider normalization with a fake transport, configuration validation, no network at import or in mock mode, tool allowlist and validation, share conversion and percent ambiguity, context binding and versioning, execution limits and duplicate prevention, capability/provenance propagation, conversation persistence and stale handling, card accuracy against direct service calls, remote failures without mock fallback, Streamlit AppTest for the panel and P0 startup without chatbot configuration. An opt-in live check (`tests/integration/test_ollama_live.py`, enabled by `RUN_OLLAMA_LIVE_SMOKE=1` plus a configured endpoint) exists for later use and is skipped by default.

## 9. Implementation order and definition of done

1. This document and related Markdown updates.
2. Config, types, providers (mock, Ollama), unit tests.
3. Context, tools, executor, limits, tests.
4. Assistant loop, state, duplicate-dispatch cache, tests.
5. Floating UI, cards, apply action, AppTest and browser check.
6. Handoff and remaining-steps update.

Done when: the UI, orchestration, adapter, validation and tests pass offline; mock mode works end to end; endpoint configuration is documented. "Ready for remote use" is distinct from live-model verification and from full real-backend integration; both are listed below as not done.

## 10. Remaining dependencies (not done)

- A reachable Ollama server with `llama3.1:8b` pulled, and its URL (and gateway token if any). Not tested here.
- Live verification of tool-calling quality with the real model; prompt tuning may be needed.
- Real WS1-WS3 providers so tools run on real backends (the chatbot only calls existing services).
- Review of the additive contract type (`ToolResult`) by WS1-WS3 consumers; no approval has occurred.
- Optional streaming of final text.
