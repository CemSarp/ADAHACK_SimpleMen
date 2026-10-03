# CarbonOpt AI Real-Data Grounding Implementation Plan

> **For agentic workers:** Execute sequentially, task by task. If the Superpowers skills are available, use `superpowers:executing-plans`. Do not spawn agents unless the user authorizes delegation. Steps use checkboxes for tracking. This document authorizes no deployment or changes to external accounts.

**Goal:** Add a traceable real-data demonstration to CarbonOpt AI within the user's remaining 1–2 hours.

**Architecture:** Add a self-contained public-data module and one dashboard section. Local JSON stores the company disclosure, official factors and a recorded API response; pure functions calculate electricity sensitivity and scheduling examples. The existing provider workflow continues to analyse synthetic inputs.

**Tech Stack:** Existing Python 3.11+, pandas, Streamlit, Plotly, pytest; standard-library JSON and `urllib.request`. No new dependencies.

**Spec:** [Real-data grounding design](../specs/2026-10-03-real-data-grounding-design.md). Read it first for the verified company numbers, accounting boundaries and URLs.

## Global Constraints

- Keep the existing Python/Streamlit stack; add no runtime dependencies.
- Keep the existing forecast, simulator, optimizer, risk and benchmark contracts unchanged.
- Keep reference data, calculator results and grid scheduling separate from the optimizer's synthetic inputs.
- Label each number as reported historical, official factor, forecast, recorded example, or assumption.
- Network failure must leave the existing dashboard usable and visibly label recorded data.
- Use kgCO2 for the grid example and tCO2e for the official-factor calculator; never combine them into a corporate total.
- Leave all existing fixture and action-assumption files unchanged.
- Stop implementation after 120 minutes; cut optional work before risking the working demo.

## Review Focus

1. Annual company data is historical and has an explicit period; it must not appear as observed monthly data. Test in Task 1.
2. Negative/non-finite activity, out-of-range reductions and incompatible factor units produce useful errors. Test in Task 2.
3. Gaps, overlapping timestamps and null forecasts cannot produce a valid one-hour schedule. Test in Task 3.
4. API outage or stale recorded data cannot appear as a current recommendation or block the app. Test in Tasks 3–4.
5. New panels cannot silently alter optimizer inputs, provider identities, or synthetic provenance. Test in Task 4.

## Time budget and cut line

These are engineering estimates, not guaranteed runtimes. Use the already configured project interpreter; do not spend the sprint rebuilding the environment.

| Task | Budget | Deliverable |
|---|---:|---|
| 1. Snapshot company reference and factor | 15 min | Traceable local data |
| 2. Official-factor sensitivity calculator | 20 min | Correct interactive arithmetic |
| 3. Grid forecast and scheduling example | 25 min | API + recorded fallback |
| 4. Dashboard integration | 25 min | One coherent section |
| 5. Verify and rehearse | 15 min | Reliable demo |
| Buffer | 20 min | Source access or UI fixes |

**If only 60 minutes are available:** do Tasks 1, 2 and a reduced Task 4, with 10 minutes reserved for verification. Omit Task 3 entirely and explain the Carbon Intensity integration in the sources text. Link CCF as the later cloud method. A correct official-factor scenario is the shipping requirement.

At minute 90, stop feature work and start verification. By minute 120, deliver whichever verified scope works. If the grid service fails, ship its labelled recorded example, not a fabricated live reading.

## File map

| File | Responsibility |
|---|---|
| `data/public/wincanton_fy2024.json` | Historical annual values and source metadata |
| `data/public/uk_factors_2026.json` | Small checked factor snapshot and workbook identifiers |
| `data/public/grid_forecast_snapshot.json` | Actual captured forecast response and capture metadata; two-hour scope |
| `src/data_sources/__init__.py` | Package marker |
| `src/data_sources/public_data.py` | Load snapshots, pure arithmetic, grid fetch/normalization |
| `src/dashboard/grounding_panel.py` | Streamlit section and cached live refresh |
| `app.py` | Import and call the section |
| `tests/unit/test_public_data.py` | Source, arithmetic and scheduling edge cases |
| `tests/integration/test_grounding_panel.py` | Offline startup, labels and unchanged optimizer inputs |
| `tests/integration/test_dashboard_hybrid_apptest.py` | Existing optimizer regression plus company-ID assertion |
| `README.md` | Data boundary, run instructions and one-minute demo |
| `src/llm/prompt.py` | One grounding rule: reference panels are separate from tool inputs |

## Task 1: Store a company reference and official electricity factor

**Files:** Create the first two JSON files, `src/data_sources/__init__.py`, `src/data_sources/public_data.py`, and `tests/unit/test_public_data.py`.

**Interfaces:**

- `load_company_reference() -> dict`: returns annual values plus `source_id`, `source_url`, `retrieved_at`, `period_start`, `period_end`, `data_kind`, units, and source page references.
- `load_factors() -> dict`: returns a mapping keyed by factor key. Each record contains `value`, `unit`, `factor_id`, `sheet`, `row`, `year`, `version`, `source_url`, `retrieved_at` and license attribution.
- Resolve data paths relative to the module's repository root, not the current working directory.

- [ ] Add `test_company_reference_retains_historical_period`: assert `period_start == "2023-04-01"`, `period_end == "2024-03-31"`, `data_kind == "reported_historical"`; no monthly rows are generated.
- [ ] Add `test_company_reference_reconciles`: assert `234907 + 7948 + 149 + 17433 == 260437`; electricity non-transport is `77485` MWh and revenue is `1406.6` £m. Keep the scope categories and units intact.
- [ ] Add `test_electricity_factor_has_exact_source`: assert `uk_electricity.value == 0.13096`, unit `kgCO2e/kWh`, factor ID `7_400_4000_5_1`, year `2026`, version `1.2`, and row `3066`.
- [ ] Run `python -m pytest tests/unit/test_public_data.py -q` and confirm the new tests fail because loaders/data are absent.
- [ ] Implement the loaders and snapshots from the verified spec. Require nonempty source metadata and reject missing factors. Electricity is mandatory; gas/diesel can be omitted from this sprint.
- [ ] Run the same command; all Task 1 tests must pass. A source link must open to the company publication or official factor workbook.

No scraper, annual-history adapter or spreadsheet library is required. The spec contains verified values. If rechecking the original company PDF fails, use its linked publisher-hosted mirror; do not substitute an unverified value.

## Task 2: Calculate an electricity-efficiency scenario

**Files:** Modify `src/data_sources/public_data.py` and `tests/unit/test_public_data.py`.

**Consumes:** Task 1's `load_factors()` and company-reference values.

**Produces:**

```python
def calculate_electricity_scenario(
    electricity_kwh: float,
    reduction_ratio: float,
    tariff_gbp_per_kwh: float,
    *,
    factor: dict,
) -> dict:
    ...
```

Result fields: `baseline_tco2e`, `scenario_tco2e`, `saved_tco2e`, `saved_kwh`, `gross_energy_savings_gbp`, `factor_id`, `factor_year`, and `assumptions`. `assumptions` records the reduction and tariff. Invalid inputs raise `ValueError` with a field-specific message.

- [ ] Add tests using `77_485_000` kWh, reduction `0.10`, tariff `0.25`, factor `0.13096`: baseline `10147.4356`, saving `1014.74356` tCO2e, saved kWh `7_748_500`, gross energy savings `1_937_125` GBP, each with `pytest.approx` where appropriate.
- [ ] Add `test_scenario_zero_and_full_reduction`: zero leaves the baseline intact; full reduction yields zero scenario emissions. Zero consumption yields zero savings.
- [ ] Parameterize errors for negative kWh, `NaN`, infinite tariff, negative tariff, reductions outside `[0,1]`, missing factor value and factor unit `gCO2/kWh`.
- [ ] Run the unit test file and confirm the new calculator tests fail before implementation.
- [ ] Implement deterministic arithmetic using kg-to-tonnes division by 1,000. Accept only a finite nonnegative `kgCO2e/kWh` factor; a blank is not zero.
- [ ] Rerun the unit test file; all tests must pass. Do not call the LLM for arithmetic and do not change `config/action_assumptions.json`.

## Task 3: Fetch a forecast and find a cleaner one-hour window

**Two-hour scope only. Files:** Modify `public_data.py` and its tests; create `grid_forecast_snapshot.json` from an actual API fetch.

**Interfaces:**

```python
def fetch_grid_forecast(as_of: datetime) -> dict: ...
def load_grid_snapshot() -> dict: ...
def normalize_grid_snapshot(snapshot: dict) -> pd.DataFrame: ...
def choose_one_hour_window(
    intervals: pd.DataFrame, *, energy_kwh: float, as_of: datetime
) -> dict | None: ...
```

Require timezone-aware `as_of`. Snapshot keys are `source_url`, `fetched_at`, `data_kind`, and `response` containing the API JSON. Normalized columns are UTC-aware `from`, `to`, `forecast_gco2_per_kwh`, and nullable `actual_gco2_per_kwh`.

Scheduling result fields are `baseline_start`, `baseline_end`, `best_start`, `best_end`, `baseline_kgco2`, `best_kgco2`, `saved_kgco2`, and `energy_kwh`. Compare adjacent complete 30-minute intervals with exact continuity. Use the earliest eligible contiguous pair as baseline, minimize forecast kgCO2, and choose the earliest pair on a tie. Return `None` if there is no eligible full hour. Reject invalid or negative energy.

- [ ] Add a four-slot UTC test with forecasts `[200,200,100,100]`, 100 kWh over one hour, and `as_of` at the first slot start. Assert baseline 20 kgCO2, best 10 kgCO2, saving 10 kgCO2, and best starts at slot 3.
- [ ] Add tests for a missing forecast, gap, overlapping timestamps, fewer than two valid future slots, and a past window. Invalid pairs must be excluded; absence of a valid pair returns `None`. A null `actual` stays null.
- [ ] Add a tie test: constant forecasts choose the earliest window with zero saving.
- [ ] Patch `urllib.request.urlopen` to raise a timeout; assert `fetch_grid_forecast` raises a controlled error. No unit test accesses the internet.
- [ ] Run the tests and verify failures, then implement the functions. Use the documented national `fw48h` endpoint with a UTC timestamp and five-second timeout; validate response shape and finite nonnegative forecasts.
- [ ] Capture one real response in the JSON snapshot, preserving retrieval time and request URL. Verify its period; do not save documentation example values as a real snapshot.
- [ ] Run the unit test file and confirm all tests pass. Runtime fallback selection belongs to Task 4, not an implicit replacement inside the fetch function.

Scheduling uses constant 100 kW across a one-hour job by default; changing total task energy does not change duration. The API measures estimated/forecast generation CO2, not lifecycle CO2e or job-specific cloud emissions.

## Task 4: Add the dashboard section without changing analysis inputs

**Files:** Create `src/dashboard/grounding_panel.py` and `tests/integration/test_grounding_panel.py`; modify `app.py` and `src/llm/prompt.py`.

**Consumes:** The public-data functions from Tasks 1–3.

**Produces:** `render_grounding_panel() -> None`, called below the existing provenance banner and before company context. It does not accept or mutate `DashboardState`, `Services`, `AnalysisRequest`, or shared action assumptions.

- [ ] Add an AppTest using hybrid mode. Monkeypatch grid network access to raise if called on startup. Assert the section loads, source links/period appear, Wincanton is labelled a historical reference, and the original partially-mocked provenance warning remains visible.
- [ ] Add an interaction test: change the new electricity-reduction slider; assert the displayed saving changes while `app.session_state["cos_baseline"]` retains its baseline ID and company ID. Extend the existing hybrid optimization test to assert `analysis.request.company_id == "demo-company"`.
- [ ] For the grid scope, inject a stale captured snapshot and assert **Recorded example** appears, its retrieval/forecast dates are shown, and no upcoming recommendation is claimed. Patch refresh to time out; the recorded panel and main dashboard must remain usable with a visible refresh error.
- [ ] Run `python -m pytest tests/integration/test_grounding_panel.py -q`; confirm the missing section causes the new tests to fail.
- [ ] Implement a compact expander titled **Real data and sources**, with the following contents:
  1. A Wincanton reference card: period, revenue, reported energy/emissions table, and publication link. Caption: **Historical public reference; separate from the synthetic optimization company.**
  2. A calculator defaulted to 77,485,000 kWh, 10% reduction and an illustrative £0.25/kWh tariff. Controls use keys prefixed `co_grounding_`. Label output **2026-factor scenario using FY2024 activity**, show formula/factor source, and explicitly label gross energy-cost savings before capex/opex. Explain that the UK factor is a scenario proxy for group activity whose exclusively UK boundary is unverified. Custom activity is user-entered, not a reported company value.
  3. In two-hour scope, a Plotly grid forecast chart, captured/live status, and a **Refresh grid forecast** button. Use `st.cache_data(ttl=1800)` for successful requests. No network call on initial app render. A successful fresh refresh uses current UTC time for future windows; a recorded replay uses its own first interval start solely to demonstrate the historical algorithm. Display times in Europe/London with timezone labels, preserving UTC internally.
  4. Source links to GOV.UK, Carbon Intensity API, Wincanton and CCF. Mark CCF integration **planned; current cloud estimates illustrative**.
- [ ] Keep all existing provider captions and warnings truthful. Add one system-prompt grounding rule: reference panels do not change company tool inputs; the assistant may quote new numeric results only when exposed by an authoritative tool, which this sprint does not add.
- [ ] Run the new integration tests and `python -m pytest tests/integration/test_dashboard_hybrid_apptest.py -q`; all must pass.

For a 60-minute implementation, render only the reference, calculator and source links. Omit all grid functions/UI/tests rather than displaying a fictional API response.

## Task 5: Validate and prepare the handoff

**Files:** Update `README.md`; preserve the plan and design alongside the implementation.

- [ ] Explain that the app now contains reported historical reference data, official factors, and optionally a grid forecast, while optimization history/economics remain synthetic and uncalibrated. Document the source dates and live-refresh behavior.
- [ ] Run `python -m pytest tests/unit/test_public_data.py tests/integration/test_grounding_panel.py tests/integration/test_dashboard_hybrid_apptest.py tests/unit/test_actions.py tests/unit/test_accounting.py -q`. Expected: passing selected checks with no required network. Record actual results; do not repeat the README's old test count as a fresh result.
- [ ] If the deadline permits, run `python -m pytest tests/contracts tests/unit -q`; resolve failures caused by this change. Do not rebuild environments or expand the feature scope.
- [ ] Start `CARBONOPT_PROVIDER_MODE=hybrid python -m streamlit run app.py`. Verify the default 10% calculator saving is approximately 1,014.74 tCO2e, source links work, and changing the calculator does not change the optimizer company.
- [ ] Rehearse once with network disabled. At two-hour scope, refresh once online and confirm the returned timestamps are current. An API error is acceptable only with an explicitly recorded fallback.
- [ ] Run `git diff --check` and inspect `git diff --stat`. Deliver source changes and a brief test report; commit only if the user's execution request includes committing.

### One-minute demo

1. Show the Wincanton report link and 77,485 MWh of non-transport electricity.
2. Show how the verified factor turns a hypothetical 10% consumption cut into roughly 1,014.74 tCO2e under a 2026-factor scenario.
3. If implemented, refresh the grid chart and compare a 100 kWh task's forecast CO2 across one-hour windows. Say whether the result is fresh or recorded.
4. Show the existing budget-constrained optimizer, clearly describing its inputs and costs as illustrative.

## Deferred work and the next real customer dataset

Request 12–24 months of electricity/gas bills, fleet fuel and mileage, business travel, cloud usage exports, revenue and operating profit in GBP, and quoted intervention capex/opex. Record reporting boundary and Scope 2 method. That dataset can support a company-specific forecasting provider and calibrated action model.

Defer automated annual-report extraction, monthly interpolation, new forecast training, cloud credentials, supplier spend estimates, real-peer rankings, new chatbot tools and deployment. If cloud later becomes the central customer problem, use a UK software company and its actual CCF export instead of inventing logistics-company cloud activity.

## Copy-paste execution prompt for Codex or Claude Code

```text
Implement the hackathon grounding additions in this repository using:
docs/superpowers/specs/2026-10-03-real-data-grounding-design.md
docs/superpowers/plans/2026-10-03-real-data-grounding.md

I have at most two hours. Complete Tasks 1, 2, 4 and 5 first; add Task 3
if time permits, then finish its Task 4 integration and tests. Reserve the
last 20 minutes for verification. Execute sequentially and preserve the
existing working dashboard and unrelated local changes.

Use Wincanton FY2024 as a public reference, the verified 2026 GOV.UK
electricity factor for a clearly labelled sensitivity scenario, and the
GB Carbon Intensity API only for the separate scheduling illustration.
Use no new dependencies. Keep all existing optimizer inputs/fixtures and
action assumptions unchanged. Never label interpolated or synthetic data
as observed, and do not claim the six-action optimization is grounded in
Wincanton records. Link Cloud Carbon Footprint as a future method.

Run the relevant tests and demonstrate offline startup. Report the files
changed, exact test results, implemented scope and any omitted optional
work. Do not deploy, create cloud accounts or change external services.
```
