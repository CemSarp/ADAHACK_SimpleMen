# Integration, Branching and Handoff Guide

WS4 coordinates checkpoints. Domain owners approve numerical correctness; integration stewardship does not override their review.

## 1. C0 foundation

Agree contract `1.0.0` before independently changing interfaces. Implement shared dataclasses, validation, JSON conversion, provider protocols and fixture loader. Check in deterministic fixture revisions and add schema tests.

The C0 PR also creates the agreed repository skeleton, importable `src` package, project/dependency configuration, optional dependency groups, ignore rules and CI. All four developers review their producer/consumer fields. This is the only initial shared critical path and should take about two hours.

C0 exit evidence:

1. All example payloads validate and round-trip.
2. Each workstream can import public contracts without optional libraries, Streamlit, model files or network.
3. A mock pipeline exposes baseline, simulation, optimization, risk, SHAP and benchmark shapes.
4. Provider overrides are explicit; no real provider silently falls back to fake output.
5. Each developer has a unique branch and declared file ownership.

## 2. Provider substitution

`create_services(mode="mock")` binds all fixture providers. `mode="real"` binds implemented domain providers and errors if required P0 capability is missing. `mode="hybrid"` uses explicit per-provider overrides and propagates provenance into the AnalysisBundle.

Hybrid mode is a development tool; the UI displays a mock banner and shows which outputs are mocked. C4 acceptance requires all P0 domain outputs to be real. Optional unavailable providers are allowed; fake P1 output is not described as real.

Recommended swap sequence:

~~~text
Mock baseline → real forecast + backtest
Mock simulator → real action engine + manual what-if
Mock optimizer → real NSGA-II + validated Pareto
Mock risk → real Monte Carlo
Mock SHAP → real model explanation
Mock benchmark → normalized compatible snapshot/API result
~~~

Run provider contract tests at every swap. Input/output schemas, chart columns and consumer signatures remain unchanged.

## 3. Checkpoints and evidence

| Checkpoint | Producer(s) | Required evidence | Consumer sign-off |
|---|---|---|---|
| C0 | All; WS4 steward | Contracts, fixtures, stubs, skeleton, offline import | All four |
| C1 | WS1 | History → forecast → backtest, real baseline fixture, naive metrics | WS2 + WS4 |
| C2 | WS2 | Real action engine; no-op/nonzero outputs; what-if/direct parity | WS3 + WS4 |
| C3 | WS2 | Real constrained optimizer, Pareto, infeasible payload | WS4 |
| C4 | WS4 + all | Fully real P0 UI; no mock P0 results; release checklist | All four |
| C5a | WS3 + WS2 | Real risk + policy selection, seed/trials/runtime | WS4 |
| C5b | WS1 | SHAP raw-output additivity and interpretation | WS4 |
| C5c | WS3 | Benchmark compatibility/provenance/failure handling | WS4 |
| C6 | WS4 | Three-policy comparison with same baseline/constraints | WS2 + WS3 |
| C7 | WS4 | Narrative fidelity, tools, bounded failure fallback | One domain reviewer |

P1 code can be developed and reviewed before C4, but feature acceptance follows C5a → C5b → C5c → C6. Keep unfinished optional features behind capability flags.

## 4. Merge order

Merge contract foundation first. During parallel development, merge small contract-compatible modules into `main` when tests pass; mark incomplete providers unavailable. A module merge is distinct from end-to-end feature acceptance.

For acceptance/release wiring, preserve:

1. C0 contracts, skeleton, mock kit and CI.
2. WS1 data, forecasting, then backtesting.
3. WS2 action engine and WS4 manual what-if wiring.
4. WS2 optimizer, then Pareto/recommendation.
5. WS4 all-real dashboard integration and `mvp-working` tag.
6. WS3 risk and WS2 risk recommendation, then WS4 panel.
7. WS1 SHAP, then WS4 panel.
8. WS3 benchmark, then WS4 panel.
9. WS4 scenario comparison.
10. Optional explanation, then chatbot.

Do not hold a completed simulator PR for an unmerged forecast PR when the simulator passes canonical baseline fixtures. Its integration gate still waits for C1.

## 5. Branch and PR conventions

Use `main` as the protected integration branch. No personal names in branch conventions.

| Pattern | Use |
|---|---|
| `chore/c0-contracts` | Initial shared foundation |
| `feat/ws1-<task>` | Data/ML/evaluation |
| `feat/ws2-<task>` | Actions/optimization |
| `feat/ws3-<task>` | Risk/benchmark |
| `feat/ws4-<task>` | UI/integration |
| `contract/<change>` | Shared interface/schema revision |
| `fix/integration-<issue>` | Bounded integration correction |

Keep PRs scoped to one boundary or checkpoint. Require owner and at least one consumer review for public changes. Rebase/update from `main` before integration, resolve conflicts in owned files, and ask the shared-file steward to resolve overlapping schema/dependency edits. Do not force-push another developer's branch or discard their changes.

Use concise commits such as `feat(actions): preserve no-op and account for EV load`. Tag accepted P0 `mvp-working`, accepted P1 `p1-ready`, final demo `demo-ready`.

## 6. Handoff PR template

~~~markdown
## Change and public boundary
Producer / consumers:
Owned paths:
Contract version:

## Reproduction
Repo-root commands:
Config, seed, model/assumption/uncertainty IDs:
Fixture revision and serialized result:

## Evidence
Contract/unit/integration checks:
Numerical/accounting checks:
Runtime profile:

## Compatibility and limitations
Capability flags:
Known limitations:
Required consumer action:
~~~

Do not include personal absolute paths, environment dumps or credentials in handoffs. A model artifact is referenced by relative artifact ID plus metadata, not a developer's local directory.

## 7. Bootstrap commands after C0 implementation

These are target commands for the implemented application. C0 must provide the declared modules and dependency files before claiming they run.

~~~sh
python -m venv .venv
python -m pip install -r requirements.txt
python -m pytest tests/contracts tests/unit
python -m pytest tests/integration
python -m streamlit run app.py
~~~

Activate/select the repo-local virtual environment using the platform's standard method before installing. Document one shared Python version and compatible locked dependency set. P1 installation uses `requirements-p1.txt`; P2 uses `requirements-p2.txt` only when the corresponding feature is enabled.

Suggested CLI modules added by C0/WS1:

~~~sh
python -m src.data.generate --config config/default.json --output data/company_timeseries.csv
python -m src.forecasting.train --config config/default.json
python -m src.forecasting.backtest --config config/default.json
~~~

The exact CLI implementation must agree with these commands or update the guide in the same PR. These module names do not imply code exists in this documentation package.

## 8. Integration acceptance and rollback

Run the same AnalysisRequest with fixtures and then real providers; verify shape, dates, units, ID joins, no-op and accounting invariants rather than expecting real model predictions to equal fixture values.

Manual what-if with a selected Pareto config must numerically equal the stored canonical SimulationResult. Risk zero-uncertainty must match that result. Benchmark failure must leave optimization visible.

If a replacement fails contract tests, keep the accepted provider and leave the failing new capability disabled. A labelled development mock is permitted in hybrid mode; an accepted real feature never silently reverts to a mock.

Before the demo, freeze config/seed/dependency revision and tag the tested commit. Save a labelled replay bundle as an explicit fallback. Release notes state enabled capabilities and their limitations.
