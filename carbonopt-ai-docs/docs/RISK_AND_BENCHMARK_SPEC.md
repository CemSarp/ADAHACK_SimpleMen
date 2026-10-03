# Risk, Recommendation and External Benchmark Specification

Owner: WS3; WS2 owns final recommendation selection and WS4 owns presentation. Risk and benchmarking are separate P1 capabilities; neither blocks the P0 pipeline.

## 1. Monte Carlo implementation

Risk models uncertainty in action effects and incremental action costs, conditional on a fixed forecast baseline. P1 does not claim a calibrated forecast-error distribution. Label results as assumption-based action uncertainty.

`UncertaintySpec` fields: ID/version, per-action effectiveness bounds/distribution, per-action capex/opex multiplier bounds/distribution, sampling method, correlation groups, and a calibration/provenance note. Initial policy uses independent bounded uniforms for multipliers: effectiveness [0.85,1.0], capex/opex [0.9,1.1]. These are illustrative, not confidence estimates.

Construct sampled `ActionAssumptions`, keeping the config fixed. Apply the sampled effectiveness multiplier as follows:

| Action | Sampled assumption mapping |
|---|---|
| Renewable | Add `renewable_effectiveness` ∈[0,1]; `r_new=r+(1-r)*x*effectiveness` |
| EV | Add `ev_effectiveness` ∈[0,1]; converted km and removed ICE emissions use `x*effectiveness` |
| Building | Multiply `building_max_reduction` by sampled multiplier |
| Travel | Add `travel_effectiveness` ∈[0,1]; reduction/savings use `x*effectiveness` |
| Cloud | Multiply `cloud_max_reduction` by sampled multiplier |
| Supplier | Multiply `supplier_max_reduction` and supplier savings by sampled multiplier |

The deterministic assumptions object includes renewable/EV/travel effectiveness = 1.0. These fields must be in C0 contracts even though uncertainty becomes active in P1. Capex and fixed opex still use the implementation config `x`, multiplied by sampled cost coefficients; ineffective investments still incur costs.

For supplier savings, sampling scales `supplier_monthly_savings_at_full_gbp` as well as `supplier_max_reduction`. For renewable/EV/travel, sampled multipliers replace their default effectiveness values. Other effectiveness multipliers scale their deterministic maximum-reduction coefficients.

Validate `n_simulations` as a positive integer and impose an application limit (default 5,000). Validate optimizer population/generations/evaluation budgets as positive integers. Degenerate uncertainty is permitted for deterministic parity tests; invalid bounds fail before sampling.

Use `numpy.random.default_rng(config.seed)`. Pre-generate a trial matrix in canonical action order so comparisons use common random numbers for the same uncertainty/config seed. Do not derive separate seeds from strategy IDs. Baseline/config inputs remain untouched.

Each sampled assumption copy gets an immutable sample ID derived from the parent assumption ID/version, uncertainty ID/version, seed and trial index. This prevents different sampled parameters sharing a deterministic strategy identity. RiskResult's top-level `strategy_id` refers to the original deterministic strategy, not to the last sampled trial.

For each trial, pass the sampled assumptions through the shared deterministic simulator. Store or summarize totals and raw constraint flags. No alternative emissions or cost formula is permitted in the risk module.

Default trial count is 1,000 for interactive evaluation; 5,000 is an explicitly triggered detailed selected-strategy report. Retaining large samples is optional and disabled by default. A zero-uncertainty specification gives identical trials matching deterministic outputs. No-op gives baseline outputs in every trial because uncertainty affects actions only.

Compute mean and empirical p05/p95 for emissions/profit, p95 cost, separate constraint probabilities and joint feasibility probability. Probability means fraction of trials meeting the original user boundary; Monte Carlo standard error for target probability is `sqrt(p*(1-p)/n)`. A reported probability of 1.0 is a finite trial estimate, not a guarantee.

Independence is the initial documented limitation. Correlated effectiveness/energy prices are future enhancements unless a tested correlation specification fits the timebox. Do not accept an arbitrary non-PSD correlation matrix.

## 2. Risk-aware recommendation

P0 NSGA-II remains deterministic with objectives emissions and profit. P1 evaluates risk for a bounded selection pool of at most 20 deterministic feasible Pareto strategies, preserving both objective endpoints and evenly sampling other points by emissions order. If the frontier has ≤20 points, evaluate all. The UI states that risk selection covers this pool.

All pool strategies use the same trials and full constraints. A missing/failed risk result is excluded from the risk-aware pool. If the pool is empty, return deterministic recommendation with `risk_status="unavailable"`. Partial coverage is visible.

Policies:

| Tolerance | Eligibility / ranking |
|---|---|
| Conservative | Prefer joint feasibility probability ≥0.90; minimize equal-weight normalized CO₂ p95 and negative profit p05 |
| Balanced | Prefer joint feasibility probability ≥0.75; minimize equal-weight normalized mean CO₂ and negative mean profit |
| Aggressive | Rank all evaluated pool strategies by 0.75 normalized mean CO₂ + 0.25 normalized negative mean profit |

Normalize over eligible pool min/max with constant-objective terms equal to zero; tie-break by stable strategy ID. If no strategy meets conservative/balanced probability thresholds, choose the largest joint probability, then the corresponding score, and set `risk_status="threshold_unmet"`. Show the shortfall.

`risk_status` values: `not_requested`, `unavailable`, `partial`, `evaluated`, `threshold_unmet`. All chosen strategies remain deterministically feasible; risk can expose violation probability. A tolerance change may select the same point if scores/eligible set agree; tests use a fixture where policies differ.

Scenario comparison shows actual selected configs, cumulative emissions/profit/cost, deterministic feasibility and target/joint probabilities. It compares selection policies for the same input constraints/baseline and is not a claim that one tolerance mathematically dominates another.

## 3. Benchmark canonical peer data

External data is normalized into `BenchmarkDataset` with metadata plus a peer DataFrame:

| Column | Rule |
|---|---|
| `peer_id` | Unique comparable company-period ID |
| `industry` | Canonical industry category |
| `period_start`, `period_end` | ISO date; exactly 12 months |
| `revenue_gbp` | Positive annual revenue, converted if necessary |
| `total_co2e_tco2e` | Nonnegative annual emissions |
| `scope_coverage` | `scope1_scope2_scope3` for P0-compatible total |
| `scope2_method` | Matches company comparison basis |
| `intensity_tco2e_per_million_gbp` | `emissions / (revenue_gbp/1_000_000)` |
| `source_id` | Dataset/source identifier |
| `is_synthetic` | bool |

Dataset metadata adds source URL, original units/currency, reporting periods, FX method/rate/date if used, retrieval time, licence/usage note, snapshot ID, normalization transformations and missing-data exclusions. Source URLs may be public dataset URLs; no local or personal absolute paths.

Do not mix kg and tonnes, revenue denominators, reporting periods, location/market-based scope2, different scope coverage, synthetic and reported peers, or industries without explicit filters. Never treat a missing scope as zero.

`BenchmarkConfig` fields: industry, expected scope coverage, expected scope2 method, `min_peers=10`, `max_period_end_gap_months=24`, and comparison basis. P1 compares a 12-month forecast baseline to the latest compatible annual peers within the allowed period gap; label `comparison_basis="forecast_vs_historical_peers"`. It is a contextual comparison, not a same-year observed rank. For 36/60 months, benchmark capability is unavailable until annual slices are specified.

## 4. Percentile definition

For company intensity `c` and compatible peer intensities:

~~~text
L = count(peer_intensity < c)
E = count(peer_intensity == c within declared intensity tolerance)
N = peer_count
percentile = 100 * (L + 0.5*E) / N
better_than_pct = 100 - percentile
industry_median = median(peer_intensity)
~~~

Lower intensity is better. All equal intensities yield percentile 50 and better-than 50. UI wording: “Estimated intensity percentile: 31; lower is better,” or “Lower intensity than about 69% of this peer set (ties use midpoint rank).” Avoid claiming a global industry percentile from a small convenience sample.

Exclude the same company when its peer ID matches the target company identity; retain an exclusion count. Constant revenue/emission units are validated before percentile computation.

## 5. Adapter behavior and failure isolation

`BenchmarkSource` identifies provider kind (CSV or HTTP), source ID, relative snapshot location, public endpoint if HTTP, and environment variable names for credentials when required. A provider is chosen during implementation after verifying real field coverage and usage terms.

HTTP rules: finite connect/read timeout, at most two retries for transient errors, capped exponential delay, explicit response validation, and no network call during import. Unit tests mock the HTTP transport. Secrets come from environment variables and never enter logs, examples or result JSON.

Offline mode reads a normalized versioned snapshot. Online failure may use a compatible cached snapshot only when the result marks its source as cache with retrieval age. An illustrative synthetic snapshot remains labelled synthetic. If no compatible snapshot exists, return unavailable with reason; the UI still renders P0/risk.

Benchmarks annotate baseline or selected strategy intensity using the same denominator and clearly distinguish the baseline comparison from an optimized counterfactual. They do not alter model features, objectives or constraints.

## 6. Verification and limitations

Risk tests verify bounded sampled assumptions, deterministic seeds, zero uncertainty/no-op identities, shared trial matrices, quantile ordering, probabilities [0,1], and exact raw constraint flags. Benchmark tests verify unit/FX conversions, compatible peer filtering, ties, direction, peer-count rejection, offline fallback and timeouts.

Forecast uncertainty, causal action calibration, economic covariance, supply-chain substitution effects and external peer coverage are explicitly limited in P1. Add them only behind revised assumptions and tests rather than inflating probability precision.
