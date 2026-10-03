# Person D — Product, UI and integration

Read [CENTER.md](CENTER.md) first. This role maps PDF sections 9–10 and its delivery/demo checklist. You coordinate the one shared pipeline and own the center status board.

## Your responsibility and boundary

Own Django configuration, forms/views/routes/services, templates/static assets, Plotly charts, `src/contracts.py`, dependency declarations and integration tests. A/B/C own their numerical modules. You orchestrate them; never reimplement their forecasting, action, optimiser or risk logic in views/JavaScript.

The user confirmed **Django + Plotly** for the PDF's CarbonOpt scope. Replace its Streamlit presentation example with Django while preserving the shared Python modules. Do not maintain two frontends or introduce a separate React/FastAPI stack/database product.

## Work in order

### 0:00–0:30 — establish the parallel checkpoint

1. Inspect current repository instructions, Git state and Python environment. The root README was conflicted at planning time; do not overwrite, reset, abort a merge/rebase or stage others' work automatically.
2. Agree CENTER's fields, units and ownership with A/B/C. Publish `src/contracts.py`, a labelled baseline fixture and a minimal Django page. These are the team's first shared checkpoint.
3. Preserve the existing Conda setup. Coordinate one ML library, pymoo and Django additions; do not let all four people edit dependencies or prune unrelated packages.
4. Establish loader/service interfaces so UI fixtures can be replaced by real outputs without redesigning the page.

### 0:30–2:00 — manual what-if first

1. Build the executive dashboard layout: source/synthetic label, history/forecast area, budget/min-profit/carbon controls, six action sliders, outcome cards and Pareto chart space.
2. Keep horizon fixed at supported 12 months. Hide/disable unavailable risk/benchmark/chat controls; no decorative controls that do nothing.
3. Wire the sliders to B's real `simulate_strategy` as soon as it arrives. Server validates [0,1] bounds and finite numbers; the browser only displays returned values.
4. Serve Plotly locally for offline demo reliability, escape job/action text and safely encode chart JSON. Preserve input values after errors.

**First handoff:** manual config → shared engine → consistent cards/plots. Clearly label any remaining fixture data.

### 2:00–4:00 — complete P0

1. Load A's genuine model-produced ForecastBundle, with temporal metrics and origin labels.
2. Connect Optimize to B's NSGA-II output. Plot profit versus carbon reduction with units and approximate-search label. Clicking a point retrieves its exact candidate ID/config.
3. Show recommendation, six intensities, investment, horizon profit/carbon, constraint slacks and deterministic reasons.
4. Compare manual outcomes against a selected returned efficient strategy. Prefer “Compare with optimised strategy” over claiming a unique exact AI optimum.
5. Implement invalid-input, unavailable-data, no-feasible-candidate and computation-failure states. Changed inputs invalidate old results; cache keys include baseline/model, config, constraints, seed and algorithm parameters. Training does not rerun on every slider edit.
6. Run the P0 walkthrough with all three owners and record gate status in CENTER. Do not mark a fixture-only forecast or isolated notebook integrated.

### 4:00–6:00 — add only connected P1

Connect C's risk-based recommendation and enable the risk control only when it applies a real policy. Connect A's SHAP as forecast explanation and C's benchmark with peer/source labels. Add saved/manual/optimised scenario comparison reusing stored configs and shared outputs. Keep LLM explanation/chat P2 deferred unless all higher-priority gates pass.

If P2 is attempted, the assistant receives structured analysis and calls existing simulator/optimizer tools. It does not invent metrics, generate independent equations or change business inputs without an explicit UI action.

### 6:00–8:00 — final integration and rehearsal

Freeze features. Verify a clean start, all major inputs, numerical consistency, empty/error states and offline core operation. Preserve a reproducible P0 checkpoint using the team's authorised Git process; do not create commits/tags automatically. Prepare a clearly labelled recorded fallback if useful.

Demo follows the PDF: history → BAU forecast → constraints → optimise → inspect Pareto config → manual change → risk → SHAP/benchmark if available. Each teammate explains their contribution. Lead with the decision and actual outputs rather than the library list.

## Acceptance checks

- One loader/service path for all modules; no duplicated numerical logic.
- Manual and optimised identical configs give identical deterministic results.
- Plot points, recommendation, cards and exports agree on baseline/config IDs.
- Updating constraints cannot leave stale results presented as current.
- Forecast/risk/benchmark labels distinguish synthetic assumptions from sourced observations.
- P0 starts and works without risk, SHAP, benchmark or an LLM.
- No unimplemented controls; no dependency on live internet for the core demonstration.

## Coding-agent iteration prompts

1. **D1:** “Read CENTER.md and this role file. Inspect repository state without changing unrelated work. Establish shared types, baseline fixture and minimal Django skeleton, coordinating dependencies centrally. Publish the checkpoint so A/B/C can work in parallel. Stop before implementing their numerical modules.”
2. **D2:** “Build the manual what-if UI against B's shared simulator and then integrate A's ForecastBundle and B's optimiser. Use exact candidate IDs, server validation and stale-result handling. Keep unavailable P1/P2 controls disabled. Demonstrate the complete P0 workflow and record actual checks in CENTER.”
3. **D3, gated:** “P0 passed. Connect C's operative risk policy, A's SHAP and sourced benchmark if available, plus scenario comparison. Reuse the same engine/results. Freeze features by hour 6, verify clean/offline startup and prepare the four-person demonstration. Do not add a generic chatbot or duplicate calculations.”

For each checkpoint report completed behaviour, actual commands/tests, blockers and the next owner handoff. Ask for contract changes before modifying another person's module.
