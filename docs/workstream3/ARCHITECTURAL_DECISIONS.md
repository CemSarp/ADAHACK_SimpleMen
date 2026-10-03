# Workstream 3 architectural decision register

Authority: the pulled documentation at `63dc29b`. This register separates frozen requirements from implementation proposals. Every accepted proposal needs a recorded value, reviewer, evidence, config/version ID and affected fixture revision. Until then it is not a team decision.

## Already fixed: do not redesign these privately

| Area | Fixed decision and consequence |
|---|---|
| Product | Single-company monthly CarbonOpt; synthetic P0; 12-month baseline initially; backtesting is P0 |
| Stack | Python 3.11 reference; Pandas/NumPy; LightGBM default for WS1; pymoo NSGA-II for WS2; Streamlit/Plotly for WS4; WS3 uses NumPy/requests and normalized snapshots |
| Architecture | Synchronous Python services; frozen config dataclasses; DataFrames internally and JSON records externally; no initial database, FastAPI or React |
| Contract | `1.0.0`; shared types/protocols/validation/serialization under `src/contracts/`; unknown majors and invalid required enums fail; no private renamed fields |
| Units | tCO₂e, GBP, fractions [0,1], monthly flows summed; state variables not summed; ISO dates and UTC metadata; JSON NaN/Infinity prohibited |
| Forecast | Forecast predicts baseline, not causal action effects; complete reconciled scopes/activities; baseline zero and negative profit rules preserved |
| Actions | Six variables in fixed order; fraction of remaining opportunity; same shared deterministic simulator for manual/optimizer/risk; no randomness inside simulator |
| Accounting | Month-1 capex; depreciation affects operating profit; gross capex + incremental opex is budget; savings cannot finance a budget violation; no action revenue change |
| Risk model | Fixed baseline/config; action effect/cost uncertainty only; immutable sampled assumptions; independent bounded uniform initial policy; forecast uncertainty excluded |
| Sampling | Default RNG(seed); common trial matrix across strategies; no seed by strategy ID; sample identity distinct from original strategy identity |
| Risk outputs | All 13 summary fields; empirical p05/p95; raw individual/joint flags; target MCSE; optional sample retention; no fake risk zeros |
| Selection | Deterministic frontier first; risk pool ≤20 with endpoints; WS2 owns tolerance ranking; probabilities expose risk without changing P0 feasibility |
| Benchmark | Normalize before comparison; baseline-only public interface; 12-month comparable annual peers; tCO₂e per million GBP; midpoint ties; lower is better |
| Source | Peers do not train forecast or change optimizer; units/currency/FX/scope/method/period/industry/licence/provenance required; missing scopes never become zero |
| Failure | Typed invalid inputs; valid unavailable optional benchmark; no import-time network; no silent mock fallback; offline tests need no credentials |
| Delivery | WS4 stewards shared files/caches/credentials; domain review plus consumer review; C5a risk → C5b SHAP → C5c benchmark; optional features do not block P0 |

## Decisions you need to make or coordinate

These cover implementation choices the current spec leaves open. “Proposed” is a concrete starting point, not an approval inferred from this guide.

| ID | Decision | Proposed initial choice | Alternatives / consequence | Reviewer; timing |
|---|---|---|---|---|
| A01 | Application root and dependency workflow | Runtime `src/`, `config/`, `data/`, `tests/` at Git root; keep authoritative docs in `carbonopt-ai-docs/` with corrected reading links. WS4 chooses one locked Python 3.11 setup; avoid duplicate drifting conda/pip lists. | Copy docs to root only as a coordinated move; nested runtime is a different layout. Existing conda manifest is not complete. | WS4 + all; C0 |
| A02 | Exact `UncertaintySpec` JSON/type and versions | Frozen typed spec with ID/version, sampler version, canonical per-action effect/capex/fixed-opex Uniform bounds, empty correlation groups and calibration note. Reject unsupported distributions/correlations. | A generic distribution registry adds work and untested combinations; P1 only needs bounded uniform. | WS3 + WS2 + WS4; C0 |
| A03 | Which cost coefficients vary | Scale each action's `costs[action].capex_at_full_gbp` and `monthly_opex_at_full_gbp` independently. Keep tariffs, renewable premium, marginal grid factor, avoided rates and asset lives fixed. | Sampling all operating prices creates correlated effects and changes meaning; require an explicit expanded mapping. | WS3 + WS2; before sampler |
| A04 | Neutral uncertainty and nondefault adoption factors | Neutral spec has all multiplier bounds [1,1]. P1 replacement mapping assumes deterministic renewable/EV/travel factors equal 1. Reject incompatible nondefault factors pending reviewed policy. | Multiplying pre-calibrated adoption factors may be useful later, but conflicts with current replace-default text if adopted privately. | WS2 + WS3; before sampler |
| A05 | Channel order, algorithm and reuse | `(n_trials,18)` matrix: six actions in canonical order × `(effectiveness,capex,fixed_opex)` per action. Draw U[0,1] for every channel including degenerate bounds; affine-map to bounds. Record sampler/NumPy/bit-generator versions. | Group-first ordering also works, but changes seeded results. Conditional draws break common trials. | WS3; document before fixtures |
| A06 | Failure of one Monte Carlo trial | Validate before running; abort on invalid/nonfinite simulator output or unexpected exception. Do not discard/resample a bad trial or publish probabilities over survivors. WS4 disables failed risk explicitly. | Partial-trial estimates require a new result/status contract and selection semantics. Current risk type has no success/failure status. | WS3 + WS4; runner boundary |
| A07 | Probability boundaries versus solver epsilon | Inclusive strict comparisons on raw metrics: cost ≤ budget; profit ≥ floor; reduction ≥ target. Zero CO₂/zero target is true; positive target is invalid. Optimizer epsilons remain its separate checks. | Tolerance-based flags differ at boundaries. If team chooses them, revise the “raw original boundary” language and fixtures consistently. | WS2 + WS3 + WS4; C0 |
| A08 | Quantile convention and retention | `np.quantile(..., method="linear")`; float64 arrays; keep only CO₂/profit/cost/flags during computation; publish samples only if requested. | Different interpolation methods shift small-n quantiles; streaming quantiles are unnecessary at n≤5,000. | WS3 + WS4; before summary fixtures |
| A09 | Runtime/trial/frontier budgets | 1,000 default, 5,000 maximum per selected plan, ≤20 policy plans; sequential canonical simulator calls initially; measure 1,000-trial and pool wall time. | Parallelism or a fast aggregate simulator requires reviewed identity/accounting parity and resource limits. Do not put stochastic NSGA-II inside risk. | WS3 + WS2 + WS4; before UI enabling |
| A10 | Benchmark period/date rules | Start-inclusive/end-inclusive full 12 calendar months: `end = start + 12 calendar months - 1 day`, allowing fiscal years. Compare year-month ordinals of baseline vs peer end, max absolute gap 24. Reported peers must already be completed by retrieval date. | “365 days” fails leap years. Forward peer periods may need a stricter directional gap rule; synthetic fixtures are separately labelled. | WS3 + WS1 + WS4; before normalization |
| A11 | Percentile tie tolerance | Absolute intensity tolerance `1e-8` tCO₂e/million GBP, relative tolerance 0. Define E first as `abs(peer-c)≤tol`, then L as `peer<c-tol`; no overlap. | Exact equality is brittle; a coarse display-based tolerance distorts ranking. This value is proposed, not given by the source. | WS3 + WS4; before rank tests |
| A12 | Company identity and repeated annual peers | Preserve source entity-ID mapping in dataset metadata; peer ID stays a company-period key. Exclude all target entity periods; retain newest compatible period per other entity. | The existing peer schema has no entity column; never substring-match IDs. An optional `company_id` column needs a shared contract update, not a local invention. | WS3 + WS4; C0 / provider qualification |
| A13 | Industry taxonomy and comparison population | Explicit configured mapping into canonical categories; homogeneous synthetic or reported cohort; count exclusions by reason. No guessed industry or undocumented cross-source mixing. | Broad industry categories can bias convenience samples; narrower groups may have <10 peers and should be unavailable. | WS3 + WS4; normalization |
| A14 | Real provider, licence and minimum usable coverage | CSV-first offline delivery. Timebox real-source research; choose only a verified source with ≥10 eligible entities, scope1+2+3 and compatible scope2 method, annual revenue/FX, period and usage rights. | No source may satisfy `market_based_demo`. Explicit unavailable or synthetic result is preferable to relabelled reported data. | WS3 + WS1/WS2/WS4 for method change; before external claim |
| A15 | FX conversion | Explicit supplied GBP per source-currency unit; disclosed method, rate date and period convention (prefer documented annual-average rate for annual revenue). No implicit current spot conversion or HTTP inside rank computation. | Provider-reported GBP is simplest; a second FX provider adds latency, provenance and historical-rate checks. | WS3 + WS4; source mapping |
| A16 | Duplicate, malformed and partially usable rows | Reject malformed dataset structure/conflicting duplicate peer IDs. Record and exclude individual rows with defined domain/data gaps; no success with hidden exclusions. Never treat missing scope3 as zero. | Failing every source for one missing report reduces availability; silently dropping without reason obscures bias. Fix policy in source mapping. | WS3 + WS4; normalization |
| A17 | Source loading failures and result conversion | Keep loader signature returning `BenchmarkDataset`. Introduce/approve narrow transport/snapshot exceptions in shared boundary; WS4 catches known optional failures and creates unavailable BenchmarkResult. Compatibility/count failure is handled by `benchmark_company`. | Returning BenchmarkResult from loader violates its declared type. Catch-all inside rank code hides bugs. Exact exception names require C0 agreement. | WS3 + WS4; C0 |
| A18 | HTTP transport policy | GET-only provider-specific endpoint; explicit requests Session injected in adapter internals; finite connect/read timeouts; initial attempt + at most 2 retries for timeout/connection/429/502/503/504; capped delay and bounded Retry-After. | Other response codes require provider evidence. Automatic broad retries or arbitrary URLs enlarge latency and make tests ambiguous. | WS3 + WS4; adapter |
| A19 | Cache age, snapshot selection and offline semantics | Versioned immutable normalized snapshot; preserve original retrieval time. WS4 sets finite online-fallback max age, proposed 30 days. Explicit offline replay may use older compatible snapshot with visible age and label. | Do not invent freshness from current file mtime. No silent synthetic fallback after a reported-provider failure. | WS3 + WS4; adapter integration |
| A20 | Where source-kind/age/exclusions metadata lives | Shared provenance extension for `source_kind=live|snapshot|cache|synthetic`, retrieval age, exclusion counts and normalization IDs; agree optional version-1 serialization fields with WS4. | Benchmark top-level status remains `ok|unavailable`; adding `cached` status violates current enum. A private unvalidated dict is not an interface. | WS3 + WS4; C0 |
| A21 | Content hashes and cache invalidation | Hash baseline contents/IDs, full precision config, parent assumptions, uncertainty contents/version, constraints, seed, n, sampler version, retain flag and provider version; benchmark keys include source/snapshot/hash, industry, coverage/method, peer policy and period gap. | Seeds/IDs alone cannot detect reused IDs with changed contents. Tolerance changes reuse risk, then rerun WS2 selection. | WS3 specifies + WS4 implements; integration |
| A22 | Optional import and error exposure | Domain modules import contracts plus lightweight domain deps; optional HTTP/provider imports at boundary; no UI, optimizer private objects or model imports. Unexpected errors surface; only expected failures become optional-unavailable. | Eager optional/model imports can break P0 before a feature is enabled. | WS3 + WS4; all tasks |
| A23 | Selected-strategy benchmark and >12 months | Baseline-only public method initially; longer horizons yield unavailable capability. An optimized counterfactual comparison needs a separately reviewed input contract/service, same revenue denominator and explicit label. | Do not pass SimulationResult into a BaselineBundle signature or annualize blindly. | WS3 + WS4; defer beyond initial scope |
| A24 | Numerical reproducibility across versions | Numerical reproducibility within recorded pinned runtime/library/sampler versions; stable content identities and config hashes; ignore only transient run IDs/time. Record environment evidence, not a cross-version bitwise guarantee. | Parallel summation, dependency upgrades or changed RNG channels may change numbers; revised sampler/fixtures make this visible. | WS3 + WS4; fixture/release policy |

## Proposed uncertainty file

This is a **proposal for C0**, not an existing canonical serialized contract. WS4 must implement/review the matching shared type and serializer before it becomes runtime input.

```json
{
  "uncertainty_id": "illustrative-action-uncertainty-v1",
  "version": "1.0.0",
  "sampling_method": "independent_uniform",
  "sampler_version": "uniform-action-major-v1",
  "correlation_groups": [],
  "calibration_note": "Illustrative independent action/cost ranges; fixed forecast baseline; not calibrated company risk.",
  "actions": {
    "renewable_energy": {"effectiveness": {"distribution": "uniform", "low": 0.85, "high": 1.0}, "capex": {"distribution": "uniform", "low": 0.9, "high": 1.1}, "fixed_opex": {"distribution": "uniform", "low": 0.9, "high": 1.1}},
    "ev_adoption": {"effectiveness": {"distribution": "uniform", "low": 0.85, "high": 1.0}, "capex": {"distribution": "uniform", "low": 0.9, "high": 1.1}, "fixed_opex": {"distribution": "uniform", "low": 0.9, "high": 1.1}},
    "building_efficiency": {"effectiveness": {"distribution": "uniform", "low": 0.85, "high": 1.0}, "capex": {"distribution": "uniform", "low": 0.9, "high": 1.1}, "fixed_opex": {"distribution": "uniform", "low": 0.9, "high": 1.1}},
    "travel_reduction": {"effectiveness": {"distribution": "uniform", "low": 0.85, "high": 1.0}, "capex": {"distribution": "uniform", "low": 0.9, "high": 1.1}, "fixed_opex": {"distribution": "uniform", "low": 0.9, "high": 1.1}},
    "cloud_efficiency": {"effectiveness": {"distribution": "uniform", "low": 0.85, "high": 1.0}, "capex": {"distribution": "uniform", "low": 0.9, "high": 1.1}, "fixed_opex": {"distribution": "uniform", "low": 0.9, "high": 1.1}},
    "supplier_transition": {"effectiveness": {"distribution": "uniform", "low": 0.85, "high": 1.0}, "capex": {"distribution": "uniform", "low": 0.9, "high": 1.1}, "fixed_opex": {"distribution": "uniform", "low": 0.9, "high": 1.1}}
  }
}
```

Use a second neutral spec whose 18 bounds all have `low=high=1.0`. Effect bounds must lie in [0,1] under this initial mapping; cost multipliers must be finite and nonnegative. Changing distribution bounds/content needs a new identity/version. For nonempty correlation metadata or unsupported distributions, fail explicitly rather than silently treating them as independent uniform.

## Decision record template

```text
Decision ID:
State: proposed | accepted | superseded
Selected value and exact behavior:
Reason and rejected alternatives:
Source/evidence:
Owner and producer/consumer reviewer:
Contract/config/sampler version:
Changed fields / files / fixture revision:
Tests proving it:
Effective commit:
Known limitations:
```

Do not privately modify the root decision register's frozen meanings. Contract changes follow the coordinated workflow: types, serializers, validators, specs, fixtures and consumers change together; patch clarifies, minor adds compatible optional fields, major changes required meanings/shape.
