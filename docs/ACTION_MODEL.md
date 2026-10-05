# Action Engine and Accounting Specification

Owner: WS2. Reviewers: WS1 for baseline compatibility, WS3 for uncertainty hooks, WS4 for units and display. This specification defines an illustrative synthetic P0 model. Calibrate assumptions separately before making company-specific claims.

## 1. Deterministic boundary

`simulate_strategy(baseline, config, assumptions=...)` returns monthly outcomes and horizon metrics without randomness, model retraining, HTTP calls, or UI imports. Do not add `n_simulations` to this signature. The risk service calls the same function repeatedly with sampled assumption objects.

Each action config value lies in [0,1], covers a fraction of the remaining eligible opportunity, is implemented in month 1, and stays fixed throughout the horizon. The all-zero config is an exact no-op. Full implementation does not promise a 100% emissions reduction: efficiency coefficients and unaffected buckets bound the effect.

## 2. Assumption object

`ActionAssumptions` fields are grouped as below. All values are finite, versioned, and serialized in `config/action_assumptions.json`.

| Group | Fields / invariant |
|---|---|
| Identity | `assumptions_id`, `version`, `is_calibrated`, `description` |
| Scope1 partition | `gas_share`, `ice_fleet_share`; each ≥0, sum = 1 |
| Scope3 partition | `travel_share`, `cloud_share`, `supplier_share`, `other_share`; sum = 1 |
| Activity allocation | `building_electricity_share`, `building_gas_share` in [0,1] |
| Action effectiveness | `building_max_reduction`, `cloud_max_reduction`, `supplier_max_reduction` in [0,1] |
| Adoption effectiveness | `renewable_effectiveness`, `ev_effectiveness`, `travel_effectiveness` in [0,1], default 1.0 |
| Electric fleet | `ev_kwh_per_km` ≥0; marginal grid factor `grid_tco2e_per_kwh` ≥0 |
| Cost coefficients | Per-action `capex_at_full_gbp`, `monthly_opex_at_full_gbp`, `asset_life_months` >0 |
| Renewable cost | `renewable_premium_gbp_per_kwh` ≥0 |
| Avoided costs | `electricity_gbp_per_kwh`, `gas_gbp_per_kwh`, `ice_fuel_gbp_per_km`, `travel_gbp_per_km`, `cloud_gbp_per_hour` ≥0 |
| Supplier operations | `supplier_monthly_savings_at_full_gbp` ≥0 |

The serialized object stores the shared scalar fields at the top level. Per-action cost fields live under `costs`, a map keyed by the six canonical ActionConfig names. [The assumption example](../tests/fixtures/v1/action_assumptions.json) fixes the exact nesting.

An assumption ID/version identifies immutable parameter values. Changing a coefficient requires a new ID/version and new strategy identities. Full-action capex coefficients describe remaining eligible opportunity for this baseline company; a zero eligible opportunity requires a zero capex/opex coefficient for that action and no claimed savings.

P0 capex and fixed opex coefficients describe the configured demo company, not universally transferable costs. If company scale changes, regenerate assumptions or introduce a reviewed activity-based cost model; the UI cannot rescale economics privately.

In scope allocations, `gas_share` and `ice_fleet_share` allocate reported scope1, not separate measured scope1 columns. Scope3 shares are synthetic decomposition assumptions. Show them in the assumptions panel. Incompatible zero activity/positive allocated emissions fails validation.

## 3. Monthly transformation sequence

Let `E` be baseline electricity, `G` baseline gas, `K` fleet km, `r` renewable share, `v` existing EV share, and `x_*` action intensities. Let `b = building_max_reduction * x_building`.

1. Partition scope1 into gas/ICE-fleet buckets and scope3 into travel/cloud/supplier/other.
2. Apply building efficiency to baseline building electricity and gas; it does not apply to newly added EV electricity.
3. Convert remaining ICE fleet to EV, removing the corresponding scope1 bucket and adding electricity demand.
4. Apply increased renewable coverage to the resulting electricity demand.
5. Apply travel, cloud and supplier actions to their distinct scope3 buckets.
6. Compute capex, incremental opex, operating savings and depreciation; aggregate outcomes.

Equations:

~~~text
r_new = r + (1 - r) * x_renewable * renewable_effectiveness
new_ev_share = v + (1 - v) * x_ev * ev_effectiveness
ev_converted_km = K * (1 - v) * x_ev * ev_effectiveness

electricity_saved = E * building_electricity_share * b
gas_saved = G * building_gas_share * b
ev_extra_kwh = ev_converted_km * ev_kwh_per_km
E_new = E - electricity_saved + ev_extra_kwh
G_new = G - gas_saved

gas_emissions = scope1 * gas_share * (1 - building_gas_share * b)
fleet_emissions = scope1 * ice_fleet_share * (1 - x_ev * ev_effectiveness)
scope1_new = gas_emissions + fleet_emissions

if r < 1 and E > 0:
    existing_scope2_new =
        scope2 * (1 - electricity_saved/E) * (1 - r_new)/(1 - r)
else:
    existing_scope2_new = 0

ev_scope2 = ev_extra_kwh * grid_tco2e_per_kwh * (1 - r_new)
scope2_new = existing_scope2_new + ev_scope2

travel_new = scope3 * travel_share * (1 - x_travel * travel_effectiveness)
cloud_new = scope3 * cloud_share * (1 - cloud_max_reduction*x_cloud)
supplier_new = scope3 * supplier_share * (1 - supplier_max_reduction*x_supplier)
other_new = scope3 * other_share
scope3_new = travel_new + cloud_new + supplier_new + other_new
total_new = scope1_new + scope2_new + scope3_new
~~~

Existing scope2 uses baseline-implied emissions to preserve exact no-op identity after forecast reconciliation. Added EV load uses the explicit marginal factor, which can differ from the historical average. With `r=1`, baseline scope2 must be zero under the P0 market-based demonstration assumption.

This model assumes baseline fleet scope1 represents remaining ICE vehicles; it assumes cloud purchased services sit in scope3, distinct from owned-site scope2; and supplier emissions exclude cloud/travel buckets. If these assumptions do not fit a real dataset, normalize or revise the model before integration.

Cloud and supplier effectiveness are bounded by their separate eligible buckets. Renewable and building actions combine multiplicatively on electricity rather than adding independent whole-company reductions. EV may increase scope2, and in adverse energy mixes total emissions may increase. Never clamp a negative reduction to zero.

## 4. Financial accounting

For each action `i`:

~~~text
action_capex_i = capex_at_full_gbp_i * x_i
fixed_opex_i_month = monthly_opex_at_full_gbp_i * x_i
depreciation_i_month = action_capex_i / asset_life_months_i
~~~

Charge capex only in month 1. Depreciation begins in month 1 and ends after the asset life; do not charge depreciation beyond that month when longer horizons are enabled.

Monthly incremental opex comprises fixed action opex, added EV electricity at `electricity_gbp_per_kwh`, and the incremental renewable premium:

~~~text
renewable_premium_increment =
    E_new * (r_new - r) * renewable_premium_gbp_per_kwh
incremental_opex =
    sum(fixed_opex_i_month)
    + ev_extra_kwh * electricity_gbp_per_kwh
    + renewable_premium_increment
~~~

The renewable price premium is charged only for increased renewable share; prices are incremental assumptions relative to the baseline operating profit. Operating savings comprise:

~~~text
operating_savings =
    electricity_saved * electricity_gbp_per_kwh
    + gas_saved * gas_gbp_per_kwh
    + ev_converted_km * ice_fuel_gbp_per_km
    + business_travel_km * x_travel * travel_effectiveness * travel_gbp_per_km
    + cloud_compute_hours * cloud_max_reduction*x_cloud * cloud_gbp_per_hour
    + supplier_monthly_savings_at_full_gbp * x_supplier

profit_new = baseline_profit + operating_savings - incremental_opex - depreciation
budget_cost = capex + incremental_opex
net_cash_impact = operating_savings - incremental_opex - capex
~~~

Capex does not also subtract directly from operating profit. The budget uses gross outlay; expected savings cannot make an unaffordable investment feasible. No discounting, financing, tax, disposal gain, or action-related revenue change is modeled in P0.

## 5. Constraint adapter and objective signs

All objectives and thresholds use horizon totals. Normalize constraints before passing them to the solver:

~~~text
F[0] = total_co2e_tco2e
F[1] = -total_profit_gbp

g_budget = (total_cost_gbp - budget_gbp) / max(budget_gbp, 1.0)
g_profit = (min_total_profit_gbp - total_profit_gbp)
           / max(abs(min_total_profit_gbp), abs(baseline_total_profit_gbp), 1.0)
g_target = min_co2_reduction_ratio - co2_reduction_ratio
~~~

Use a dimensionless tolerance `1e-8` for solver feasibility, and independently check raw totals with currency tolerance `0.01` and reduction tolerance `1e-8`. If baseline CO₂ is zero and target is zero, set `g_target=0`; a positive ratio target on zero baseline is invalid. Require nonnegative budget and target in [0,1]. Profit floor can be negative.

The optimizer minimizes both objectives. Plotting can display profit positively but never feeds that sign back into search. Cost is a constraint, not a third P0 objective.

## 6. Pareto, identity and recommendation

Evaluate no-op plus deterministic seed configurations before NSGA-II. Retain all unique candidates actually evaluated. A point dominates another if it is no worse in emissions/profit and strictly better in at least one dimension beyond numerical tolerance. Filter infeasible points first; cost does not participate in P0 dominance.

Retain equivalent objective ties when configs differ and risk outcomes may differ; use stable strategy ID order for deterministic presentation. Exact duplicate configs are removed by canonical full-precision identity. Recompute all returned Pareto points using the canonical simulator and validate feasibility before publishing them.

P0 recommendation uses min-max normalized emissions and negative profit among feasible Pareto points, equal weights, and stable ID tie-break. If one objective is constant, its normalized term is zero; if the frontier has one point, select it. [The risk specification](RISK_AND_BENCHMARK_SPEC.md) defines P1 tolerance selection without changing deterministic frontier semantics.

Canonical identity uses sorted-key compact JSON with config values normalized to floats, preserving their full float precision. Hash UTF-8 bytes using SHA-256 and prefix the first 16 hexadecimal characters with `strategy-`. Detect any truncated-ID collision by comparing the full identity and extend the ID if needed. Identity object keys are `baseline_id`, `config`, `assumptions_id` and `assumptions_version`. No decimal rounding is part of identity.

## 7. Required invariants

All-zero config preserves every baseline emission/profit row and creates zero costs. Increasing cloud action never reduces below the cloud bucket's allowed minimum. Scope totals reconcile. Scope values and costs remain nonnegative; operating profit can be negative. Inputs are unchanged after a call. Action order is fixed. The same baseline/config/assumptions gives the same outcomes for all consumers.
