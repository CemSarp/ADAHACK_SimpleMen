"""WS2 action engine: definitions, validation, no-op, single actions, interactions, invariants.

Expected values are hand-derived from the fixture baseline (per month: E=100,000 kWh,
G=50,000 kWh, fleet 50,000 km, r=0.2, v=0, scope1/2/3 = 20/30/50 t, profit 100,000 GBP,
travel 20,000 km, cloud 10,000 h) and config/action_assumptions.json.
"""

from __future__ import annotations

import dataclasses
import json
import math

import numpy as np
import pytest

from src.actions import (
    ACTION_DEFINITIONS,
    apply_uncertainty_sample,
    compute_action_breakdown,
    compute_strategy_id,
    config_from_vector,
    config_to_vector,
    load_action_assumptions,
    simulate_strategy,
    strategy_identity,
)
from src.actions.definitions import assign_strategy_id, canonical_config, strategy_id_from_identity
from src.contracts import ACTION_NAMES, ActionConfig, ContractValidationError
from src.contracts import serialization as ser
from src.contracts import validation as val
from tests.support import (
    assumptions_with,
    assumptions_with_cost,
    fixture_assumptions,
    frames_identical,
    load_fixture,
    make_baseline,
    snapshot,
)

SCOPE_COLUMNS = ["scope1_tco2e", "scope2_tco2e", "scope3_tco2e", "total_co2e_tco2e"]
COST_COLUMNS = [
    "capex_gbp",
    "incremental_opex_gbp",
    "operating_savings_gbp",
    "depreciation_gbp",
    "budget_cost_gbp",
    "net_cash_impact_gbp",
]


def only(**actions: float) -> ActionConfig:
    values = dict.fromkeys(ACTION_NAMES, 0.0)
    values.update(actions)
    return ActionConfig(**values)


def month(result, index: int = 0):
    return result.monthly.iloc[index]


def close(value: float, rel: float = 1e-12, abs_: float = 1e-9):
    return pytest.approx(value, rel=rel, abs=abs_)


# ---------------------------------------------------------------------------
# Definitions, vector order and bounds
# ---------------------------------------------------------------------------


def test_action_vector_order_is_canonical():
    expected = (
        "renewable_energy",
        "ev_adoption",
        "building_efficiency",
        "travel_reduction",
        "cloud_efficiency",
        "supplier_transition",
    )
    assert ACTION_NAMES == expected
    assert tuple(f.name for f in dataclasses.fields(ActionConfig)) == expected
    assert tuple(d.name for d in ACTION_DEFINITIONS) == expected
    config = ActionConfig(0.1, 0.2, 0.3, 0.4, 0.5, 0.6)
    assert config.as_vector() == (0.1, 0.2, 0.3, 0.4, 0.5, 0.6)
    assert list(config.as_dict()) == list(expected)


def test_vector_round_trip_keeps_full_precision():
    values = [0.1 + 0.2, 1 / 3, 0.0, 1.0, 0.5, 2.0**-40]
    config = config_from_vector(values)
    assert config.as_vector() == tuple(values)
    assert np.array_equal(config_to_vector(config), np.array(values))


@pytest.mark.parametrize("bad", [-0.1, 1.0000001, 70, 100.0, math.nan, math.inf, -math.inf, True, "0.5", None])
def test_action_values_outside_unit_interval_or_wrong_type_are_rejected(bad):
    with pytest.raises(ContractValidationError) as info:
        canonical_config(ActionConfig(bad, 0.0, 0.0, 0.0, 0.0, 0.0))
    assert info.value.field == "config.renewable_energy"


def test_negative_zero_and_numpy_scalars_are_normalised():
    config = canonical_config(ActionConfig(-0.0, np.float64(0.5), np.float32(0.25), np.int64(1), 0, 1))
    assert math.copysign(1.0, config.renewable_energy) == 1.0
    assert all(type(v) is float for v in config.as_vector())
    assert config.as_vector() == (0.0, 0.5, 0.25, 1.0, 0.0, 1.0)
    assert compute_strategy_id("b", ActionConfig(-0.0, 0, 0, 0, 0, 0), fixture_assumptions()) == compute_strategy_id(
        "b", ActionConfig.noop(), fixture_assumptions()
    )


def test_config_mapping_requires_exactly_the_six_actions():
    with pytest.raises(ContractValidationError, match="required"):
        ser.action_config_from_dict({"renewable_energy": 0.1})
    with pytest.raises(ContractValidationError, match="unknown"):
        ser.action_config_from_dict({**dict.fromkeys(ACTION_NAMES, 0.0), "renewables": 0.5})


# ---------------------------------------------------------------------------
# Assumptions
# ---------------------------------------------------------------------------


def test_config_assumption_file_is_the_versioned_illustrative_fixture():
    loaded = load_action_assumptions()
    assert loaded == fixture_assumptions()
    assert loaded.assumptions_id == "demo-actions-v1" and loaded.version == "1.0.0"
    assert loaded.is_calibrated is False
    assert "Illustrative" in loaded.description
    assert (loaded.renewable_effectiveness, loaded.ev_effectiveness, loaded.travel_effectiveness) == (1.0, 1.0, 1.0)


def test_effectiveness_fields_are_required_and_set_to_one_in_the_config():
    # The shared schema has no silent default: the versioned file states the 1.0 hooks.
    data = load_fixture("action_assumptions.json")
    del data["ev_effectiveness"]
    with pytest.raises(ContractValidationError) as info:
        ser.assumptions_from_dict(data)
    assert info.value.field == "assumptions.ev_effectiveness"


def _mutated_assumptions(mutate):
    data = load_fixture("action_assumptions.json")
    mutate(data)
    return data


@pytest.mark.parametrize(
    "mutate, field_fragment",
    [
        (lambda d: d.update(gas_share=0.7), "gas_share"),
        (lambda d: d.update(other_share=0.2), "travel_share"),
        (lambda d: d.update(building_gas_share=1.5), "building_gas_share"),
        (lambda d: d.update(cloud_max_reduction=-0.1), "cloud_max_reduction"),
        (lambda d: d.update(renewable_effectiveness=1.2), "renewable_effectiveness"),
        (lambda d: d.update(electricity_gbp_per_kwh=-0.15), "electricity_gbp_per_kwh"),
        (lambda d: d.update(grid_tco2e_per_kwh=math.inf), "grid_tco2e_per_kwh"),
        (lambda d: d.update(is_calibrated="no"), "is_calibrated"),
        (lambda d: d.update(assumptions_id=""), "assumptions_id"),
        (lambda d: d.update(gas_shares=0.6), "assumptions"),
        (lambda d: d.pop("gas_share"), "assumptions"),
        (lambda d: d["costs"]["travel_reduction"].update(asset_life_months=0), "costs.travel_reduction.asset_life_months"),
        (lambda d: d["costs"]["travel_reduction"].update(asset_life_months=6.5), "costs.travel_reduction.asset_life_months"),
        (lambda d: d["costs"]["ev_adoption"].update(capex_at_full_gbp=-1), "costs.ev_adoption.capex_at_full_gbp"),
        (lambda d: d["costs"].pop("cloud_efficiency"), "assumptions.costs"),
        (lambda d: d["costs"].update(heat_pumps=d["costs"]["cloud_efficiency"]), "assumptions.costs"),
    ],
)
def test_invalid_assumptions_are_rejected_with_field(mutate, field_fragment):
    with pytest.raises(ContractValidationError) as info:
        val.validate_assumptions(ser.assumptions_from_dict(_mutated_assumptions(mutate)))
    assert field_fragment in info.value.field


def test_assumptions_are_immutable(assumptions):
    with pytest.raises(dataclasses.FrozenInstanceError):
        assumptions.gas_share = 0.5  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Exact no-op, immutability and determinism
# ---------------------------------------------------------------------------


def test_noop_matches_golden_fixture_exactly(baseline, assumptions):
    result = simulate_strategy(baseline, ActionConfig.noop(), assumptions=assumptions)
    golden = ser.simulation_from_dict(load_fixture("simulation_noop.json"))
    assert result.strategy_id == golden.strategy_id == "strategy-84d0730a93b9d729"
    assert result.metrics == golden.metrics
    assert frames_identical(result.monthly, golden.monthly)
    for column in COST_COLUMNS:
        assert (result.monthly[column].to_numpy() == 0.0).all()


def _irregular_row(rng):
    def row_fn(i, row):
        row = dict(row)
        row.update(
            revenue_gbp=float(rng.uniform(5e5, 2e6)),
            operating_profit_gbp=float(rng.uniform(-5e4, 2e5)),
            electricity_kwh=float(rng.uniform(5e4, 2e5)),
            gas_kwh=float(rng.uniform(1e4, 1e5)),
            renewable_energy_share=float(rng.uniform(0.0, 0.9)),
            ev_share=float(rng.uniform(0.0, 0.9)),
            fleet_km=float(rng.uniform(1e4, 1e5)),
            business_travel_km=float(rng.uniform(1e3, 5e4)),
            cloud_compute_hours=float(rng.uniform(1e3, 2e4)),
            scope1_tco2e=float(rng.uniform(5.0, 50.0)),
            scope2_tco2e=float(rng.uniform(5.0, 50.0)),
            scope3_tco2e=float(rng.uniform(10.0, 100.0)),
        )
        return row

    return row_fn


def test_noop_is_bitwise_exact_on_an_irregular_float_baseline(assumptions):
    baseline = make_baseline(months=60, row_fn=_irregular_row(np.random.default_rng(7)))
    result = simulate_strategy(baseline, ActionConfig.noop(), assumptions=assumptions)
    for column in ["revenue_gbp", "operating_profit_gbp", *SCOPE_COLUMNS]:
        assert np.array_equal(result.monthly[column].to_numpy(), baseline.monthly[column].to_numpy()), column
    for column in COST_COLUMNS:
        assert (result.monthly[column].to_numpy() == 0.0).all()
    assert result.metrics["co2_reduction_tco2e"] == 0.0 and result.metrics["profit_change_gbp"] == 0.0
    assert result.metrics["total_cost_gbp"] == 0.0
    # Non-vacuous: re-summing the literal scope3 bucket products does not round-trip here.
    s3 = baseline.monthly["scope3_tco2e"].to_numpy()
    literal = s3 * 0.2 + s3 * 0.2 + s3 * 0.5 + s3 * 0.1
    assert (literal != s3).any()


def test_inputs_are_not_mutated(baseline, assumptions, example_config):
    before = (snapshot(baseline), snapshot(assumptions), snapshot(example_config))
    simulate_strategy(baseline, example_config, assumptions=assumptions)
    compute_action_breakdown(baseline, example_config, assumptions=assumptions)
    assert frames_identical(baseline.monthly, before[0].monthly)
    assert baseline.totals == before[0].totals and baseline.provenance == before[0].provenance
    assert assumptions == before[1] and example_config == before[2]


def test_simulation_is_deterministic(baseline, assumptions, example_config):
    first = simulate_strategy(baseline, example_config, assumptions=assumptions)
    second = simulate_strategy(baseline, example_config, assumptions=assumptions)
    assert frames_identical(first.monthly, second.monthly)
    assert first.metrics == second.metrics
    assert (first.strategy_id, first.run_id) == (second.strategy_id, second.run_id)


def test_invalid_inputs_fail_before_computation(baseline, assumptions):
    with pytest.raises(ContractValidationError, match="config"):
        simulate_strategy(baseline, {"renewable_energy": 0.5}, assumptions=assumptions)  # type: ignore[arg-type]
    with pytest.raises(ContractValidationError, match="assumptions"):
        simulate_strategy(baseline, ActionConfig.noop(), assumptions=ser.assumptions_to_dict(assumptions))  # type: ignore[arg-type]
    tampered = snapshot(baseline)
    tampered.monthly.loc[3, "gas_kwh"] = math.nan
    with pytest.raises(ContractValidationError, match="gas_kwh"):
        simulate_strategy(tampered, ActionConfig.noop(), assumptions=assumptions)


# ---------------------------------------------------------------------------
# Individual actions (hand-calculated monthly values)
# ---------------------------------------------------------------------------

# (scope1, scope2, scope3, incremental opex, savings, month-1 capex, monthly depreciation)
SINGLE_ACTION_CASES = {
    # r_new = 0.2 + 0.8*0.5 = 0.6; scope2 = 30*(1-0.5); premium = 100,000*0.4*0.02 = 800; opex 800 + 100*0.5
    "renewable_energy": (20.0, 15.0, 50.0, 850.0, 0.0, 50_000.0, 50_000 / 120),
    # 25,000 km converted; fleet bucket 8*(1-0.5); +5,000 kWh * 0.000375 * 0.8 = 1.5 t scope2;
    # opex 75 + 5,000*0.15; savings 25,000*0.12
    "ev_adoption": (16.0, 31.5, 50.0, 825.0, 3_000.0, 75_000.0, 75_000 / 84),
    # b = 0.3*0.5 = 0.15: gas 12*(1-0.15) + 8; scope2 30*(1-0.7*0.15); savings 10,500*0.15 + 7,500*0.05
    "building_efficiency": (18.2, 26.85, 50.0, 40.0, 1_950.0, 40_000.0, 40_000 / 120),
    # travel bucket 10*(1-0.5); savings 20,000*0.5*0.2
    "travel_reduction": (20.0, 30.0, 45.0, 5.0, 2_000.0, 5_000.0, 5_000 / 36),
    # cloud bucket 10*(1-0.4*0.5); savings 10,000*0.2*0.05
    "cloud_efficiency": (20.0, 30.0, 48.0, 10.0, 100.0, 10_000.0, 10_000 / 36),
    # supplier bucket 25*(1-0.3*0.5); savings 1,000*0.5
    "supplier_transition": (20.0, 30.0, 46.25, 50.0, 500.0, 50_000.0, 50_000 / 120),
}


@pytest.mark.parametrize("action", ACTION_NAMES)
def test_single_action_at_half_matches_hand_calculation(baseline, assumptions, action):
    scope1, scope2, scope3, opex, savings, capex, depreciation = SINGLE_ACTION_CASES[action]
    result = simulate_strategy(baseline, only(**{action: 0.5}), assumptions=assumptions)
    for i in range(12):
        row = month(result, i)
        assert row["scope1_tco2e"] == close(scope1)
        assert row["scope2_tco2e"] == close(scope2)
        assert row["scope3_tco2e"] == close(scope3)
        assert row["total_co2e_tco2e"] == close(scope1 + scope2 + scope3)
        assert row["incremental_opex_gbp"] == close(opex)
        assert row["operating_savings_gbp"] == close(savings)
        assert row["depreciation_gbp"] == close(depreciation)
        assert row["capex_gbp"] == (close(capex) if i == 0 else 0.0)
        assert row["operating_profit_gbp"] == close(100_000 + savings - opex - depreciation)


@pytest.mark.parametrize("action", ACTION_NAMES)
def test_single_action_effect_is_monotone_and_local(baseline, assumptions, action):
    levels = [0.0, 0.25, 0.5, 0.75, 1.0]
    rows = [month(simulate_strategy(baseline, only(**{action: x}), assumptions=assumptions)) for x in levels]
    s1, s2, s3 = (np.array([r[c] for r in rows]) for c in ("scope1_tco2e", "scope2_tco2e", "scope3_tco2e"))
    if action == "ev_adoption":
        assert (np.diff(s1) < 0).all() and (np.diff(s2) > 0).all()  # load transfer
    elif action == "renewable_energy":
        assert (np.diff(s2) < 0).all() and (s1 == 20.0).all()
    elif action == "building_efficiency":
        assert (np.diff(s1) < 0).all() and (np.diff(s2) < 0).all()
    else:
        assert (np.diff(s3) < 0).all() and (s1 == 20.0).all() and (s2 == 30.0).all()
    if action in ("renewable_energy", "ev_adoption", "building_efficiency"):
        assert (s3 == 50.0).all()


# ---------------------------------------------------------------------------
# Remaining-opportunity semantics and interactions
# ---------------------------------------------------------------------------


def test_renewable_action_is_a_fraction_of_remaining_supply(baseline, assumptions):
    partial = compute_action_breakdown(baseline, only(renewable_energy=0.7), assumptions=assumptions)
    assert partial["renewable_energy_share"].iloc[0] == close(0.76)  # 0.2 + 0.8*0.7, not a 70% target
    full = simulate_strategy(baseline, only(renewable_energy=1.0), assumptions=assumptions)
    assert compute_action_breakdown(baseline, only(renewable_energy=1.0), assumptions=assumptions)["renewable_energy_share"].iloc[0] == 1.0
    assert month(full)["scope2_tco2e"] == 0.0


def test_ev_action_converts_only_the_remaining_ice_fleet(assumptions):
    baseline = make_baseline(ev_share=0.5)
    breakdown = compute_action_breakdown(baseline, only(ev_adoption=1.0), assumptions=assumptions)
    assert breakdown["ev_converted_km"].iloc[0] == close(25_000.0)  # 50,000 km * (1 - 0.5)
    assert breakdown["ev_extra_kwh"].iloc[0] == close(5_000.0)
    assert breakdown["ev_share"].iloc[0] == 1.0
    result = simulate_strategy(baseline, only(ev_adoption=1.0), assumptions=assumptions)
    assert month(result)["scope1_tco2e"] == close(12.0)  # the remaining-ICE bucket (8 t) is removed


def test_effectiveness_scales_adoption(baseline, assumptions):
    half_effective = assumptions_with(assumptions, renewable_effectiveness=0.5)
    breakdown = compute_action_breakdown(baseline, only(renewable_energy=1.0), assumptions=half_effective)
    assert breakdown["renewable_energy_share"].iloc[0] == close(0.6)
    result = simulate_strategy(baseline, only(renewable_energy=1.0), assumptions=half_effective)
    assert month(result)["scope2_tco2e"] == close(15.0)
    assert result.metrics["total_capex_gbp"] == 100_000.0  # ineffective adoption still costs the full coefficient


def test_renewable_and_building_combine_multiplicatively(baseline, assumptions):
    both = month(simulate_strategy(baseline, only(renewable_energy=0.5, building_efficiency=0.5), assumptions=assumptions))
    renewable_only = month(simulate_strategy(baseline, only(renewable_energy=0.5), assumptions=assumptions))
    building_only = month(simulate_strategy(baseline, only(building_efficiency=0.5), assumptions=assumptions))
    # existing scope2 = 30 * (1 - 0.7*0.15) * (1 - 0.5) = 13.425
    assert both["scope2_tco2e"] == close(13.425)
    reduction_both = 30.0 - both["scope2_tco2e"]
    reduction_sum = (30.0 - renewable_only["scope2_tco2e"]) + (30.0 - building_only["scope2_tco2e"])
    assert reduction_both == close(16.575)
    assert reduction_sum == close(18.15)  # additive double counting would overstate by 1.575 t


def test_building_savings_exclude_added_ev_load(baseline, assumptions):
    combined = compute_action_breakdown(baseline, only(building_efficiency=1.0, ev_adoption=1.0), assumptions=assumptions)
    building_only = compute_action_breakdown(baseline, only(building_efficiency=1.0), assumptions=assumptions)
    assert combined["electricity_saved_kwh"].iloc[0] == building_only["electricity_saved_kwh"].iloc[0] == close(21_000.0)
    assert combined["electricity_kwh"].iloc[0] == close(89_000.0)  # 100,000 - 21,000 + 10,000 EV kWh


def test_ev_load_is_covered_by_renewable_on_resulting_demand(baseline, assumptions):
    ev_only = month(simulate_strategy(baseline, only(ev_adoption=1.0), assumptions=assumptions))
    assert ev_only["scope2_tco2e"] == close(33.0)  # 30 + 10,000 kWh * 0.000375 * 0.8
    with_renewable = month(simulate_strategy(baseline, only(ev_adoption=1.0, renewable_energy=1.0), assumptions=assumptions))
    assert with_renewable["scope2_tco2e"] == 0.0
    # opex = fixed 100 + 150 + EV kWh 10,000*0.15 + premium on resulting demand 110,000*0.8*0.02
    assert with_renewable["incremental_opex_gbp"] == close(250.0 + 1_500.0 + 1_760.0)


def test_ev_can_increase_total_emissions_and_is_not_clamped(baseline, assumptions):
    dirty_grid = assumptions_with(assumptions, grid_tco2e_per_kwh=0.01)
    result = simulate_strategy(baseline, only(ev_adoption=1.0), assumptions=dirty_grid)
    row = month(result)
    assert row["scope1_tco2e"] == close(12.0)
    assert row["scope2_tco2e"] == close(110.0)  # 30 + 10,000 kWh * 0.01 * 0.8
    assert result.metrics["total_co2e_tco2e"] == close(12 * 172.0)
    assert result.metrics["co2_reduction_tco2e"] == close(1_200.0 - 2_064.0)
    assert result.metrics["co2_reduction_ratio"] == close(-0.72)


# ---------------------------------------------------------------------------
# Scope reconciliation, bucket limits and invariants
# ---------------------------------------------------------------------------


def test_scope_totals_reconcile_and_values_stay_nonnegative(assumptions):
    rng = np.random.default_rng(11)
    baselines = [make_baseline(), make_baseline(months=36, row_fn=_irregular_row(np.random.default_rng(3)))]
    for baseline in baselines:
        for _ in range(40):
            result = simulate_strategy(baseline, config_from_vector(rng.random(6)), assumptions=assumptions)
            frame = result.monthly
            total = frame["total_co2e_tco2e"].to_numpy()
            scopes = frame[["scope1_tco2e", "scope2_tco2e", "scope3_tco2e"]].to_numpy().sum(axis=1)
            assert np.all(np.abs(total - scopes) <= 1e-6 + 1e-8 * np.abs(total))
            assert (frame[SCOPE_COLUMNS + COST_COLUMNS[:-1]].to_numpy() >= 0.0).all()


def test_actions_never_reduce_below_residual_bucket_floors(baseline, assumptions):
    all_scope3 = month(simulate_strategy(baseline, only(travel_reduction=1, cloud_efficiency=1, supplier_transition=1), assumptions=assumptions))
    # floor = other 5 + cloud 10*(1-0.4) + supplier 25*(1-0.3) + travel 0
    assert all_scope3["scope3_tco2e"] == close(28.5)
    cloud_only = month(simulate_strategy(baseline, only(cloud_efficiency=1.0), assumptions=assumptions))
    assert cloud_only["scope3_tco2e"] == close(46.0)  # cloud bucket keeps 6 t
    scope1_actions = month(simulate_strategy(baseline, only(building_efficiency=1, ev_adoption=1), assumptions=assumptions))
    assert scope1_actions["scope1_tco2e"] == close(8.4)  # gas 12*(1-0.3); ICE fleet fully converted


def test_full_elimination_reaches_zero_without_going_negative(baseline):
    extreme = assumptions_with(
        fixture_assumptions(),
        building_max_reduction=1.0,
        cloud_max_reduction=1.0,
        supplier_max_reduction=1.0,
        travel_share=0.2,
        cloud_share=0.3,
        supplier_share=0.5,
        other_share=0.0,
    )
    result = simulate_strategy(baseline, ActionConfig(*[1.0] * 6), assumptions=extreme)
    row = month(result)
    assert row["scope1_tco2e"] == 0.0 and row["scope3_tco2e"] == 0.0
    assert row["scope2_tco2e"] >= 0.0 and row["total_co2e_tco2e"] >= 0.0


@pytest.mark.parametrize(
    "updates, column",
    [
        ({"fleet_km": 0.0}, "fleet_km"),
        ({"ev_share": 1.0}, "fleet_km"),
        ({"gas_kwh": 0.0}, "gas_kwh"),
        ({"electricity_kwh": 0.0}, "electricity_kwh"),
        ({"renewable_energy_share": 1.0}, "scope2_tco2e"),
        ({"business_travel_km": 0.0}, "business_travel_km"),
        ({"cloud_compute_hours": 0.0}, "cloud_compute_hours"),
    ],
)
def test_zero_activity_with_positive_allocated_emissions_is_rejected(assumptions, updates, column):
    baseline = make_baseline(**updates)
    with pytest.raises(ContractValidationError) as info:
        simulate_strategy(baseline, ActionConfig.noop(), assumptions=assumptions)
    assert info.value.field == f"baseline.monthly.{column}"


def test_no_eligible_fleet_is_valid_when_assumptions_allocate_no_fleet_emissions(assumptions):
    baseline = make_baseline(fleet_km=0.0, fleet_size=0)
    no_fleet = assumptions_with_cost(
        assumptions_with(assumptions, gas_share=1.0, ice_fleet_share=0.0),
        "ev_adoption",
        capex_at_full_gbp=0.0,
        monthly_opex_at_full_gbp=0.0,
    )
    noop = simulate_strategy(baseline, ActionConfig.noop(), assumptions=no_fleet)
    ev = simulate_strategy(baseline, only(ev_adoption=1.0), assumptions=no_fleet)
    assert ev.metrics["total_co2e_tco2e"] == noop.metrics["total_co2e_tco2e"]
    assert ev.metrics["total_cost_gbp"] == 0.0 and ev.metrics["total_operating_savings_gbp"] == 0.0
    # A mis-specified assumption set (cost coefficient without opportunity) is charged as written.
    costly = assumptions_with(assumptions, gas_share=1.0, ice_fleet_share=0.0)
    charged = simulate_strategy(baseline, only(ev_adoption=1.0), assumptions=costly)
    assert charged.metrics["total_co2e_tco2e"] == noop.metrics["total_co2e_tco2e"]
    assert charged.metrics["total_capex_gbp"] == 150_000.0


def test_full_renewable_baseline(assumptions):
    baseline = make_baseline(renewable_energy_share=1.0, scope2_tco2e=0.0)
    renewable = simulate_strategy(baseline, only(renewable_energy=1.0), assumptions=assumptions)
    assert renewable.metrics["co2_reduction_tco2e"] == 0.0
    assert month(renewable)["incremental_opex_gbp"] == close(100.0)  # fixed opex only; no premium uplift
    ev = simulate_strategy(baseline, only(ev_adoption=1.0), assumptions=assumptions)
    assert month(ev)["scope2_tco2e"] == 0.0  # added EV load is fully renewable


def test_zero_emission_baseline_has_null_ratio_and_ev_can_add_emissions(assumptions):
    baseline = make_baseline(scope1_tco2e=0.0, scope2_tco2e=0.0, scope3_tco2e=0.0)
    noop = simulate_strategy(baseline, ActionConfig.noop(), assumptions=assumptions)
    assert noop.metrics["baseline_total_co2e_tco2e"] == 0.0 and noop.metrics["co2_reduction_ratio"] is None
    ev = simulate_strategy(baseline, only(ev_adoption=1.0), assumptions=assumptions)
    assert ev.metrics["total_co2e_tco2e"] == close(36.0)  # 12 * 10,000 kWh * 0.000375 * 0.8
    assert ev.metrics["co2_reduction_tco2e"] == close(-36.0) and ev.metrics["co2_reduction_ratio"] is None


# ---------------------------------------------------------------------------
# Strategy identity and serialization
# ---------------------------------------------------------------------------


def test_fixture_strategy_ids_are_reproduced(baseline, assumptions, example_config):
    assert compute_strategy_id(baseline.baseline_id, ActionConfig.noop(), assumptions) == "strategy-84d0730a93b9d729"
    assert compute_strategy_id(baseline.baseline_id, example_config, assumptions) == "strategy-8be15857fffc57f6"


def test_identity_is_sorted_compact_json_of_full_precision_values(example_config):
    identity = strategy_identity("baseline-demo-v1", example_config, assumptions_id="demo-actions-v1", assumptions_version="1.0.0")
    assert identity == (
        '{"assumptions_id":"demo-actions-v1","assumptions_version":"1.0.0","baseline_id":"baseline-demo-v1",'
        '"config":{"building_efficiency":0.2,"cloud_efficiency":0.25,"ev_adoption":0.4,"renewable_energy":0.7,'
        '"supplier_transition":0.1,"travel_reduction":0.3}}'
    )


def test_identity_never_rounds_and_tracks_baseline_and_assumption_version(assumptions):
    a = ActionConfig(0.1 + 0.2, 0, 0, 0, 0, 0)
    b = ActionConfig(0.3, 0, 0, 0, 0, 0)
    assert a != b
    assert compute_strategy_id("base", a, assumptions) != compute_strategy_id("base", b, assumptions)
    reference = compute_strategy_id("base", b, assumptions)
    assert compute_strategy_id("other-base", b, assumptions) != reference
    assert compute_strategy_id("base", b, dataclasses.replace(assumptions, version="1.0.1")) != reference
    assert compute_strategy_id("base", b, dataclasses.replace(assumptions, assumptions_id="x")) != reference


def test_truncated_id_collision_is_extended_by_full_identity_comparison():
    def colliding(identity, *, hex_length):
        return "strategy-" + "a" * 16 if hex_length == 16 else strategy_id_from_identity(identity, hex_length=hex_length)

    taken = {"strategy-" + "a" * 16: '{"existing":1}'}
    assert assign_strategy_id('{"existing":1}', taken, id_fn=colliding) == "strategy-" + "a" * 16
    extended = assign_strategy_id('{"new":2}', taken, id_fn=colliding)
    assert len(extended) == len("strategy-") + 24 and extended != "strategy-" + "a" * 16


def test_simulation_result_json_round_trip_keeps_dates_units_and_precision(baseline, assumptions):
    config = ActionConfig(0.1 + 0.2, 1 / 3, 2.0**-30, 0.5, 0.75, 1.0)
    result = simulate_strategy(baseline, config, assumptions=assumptions)
    text = ser.to_json(result)
    payload = json.loads(text)
    assert payload["schema_version"] == "1.0.0"
    assert payload["monthly"][0]["timestamp"] == "2027-01-01"
    assert payload["config"]["renewable_energy"] == 0.30000000000000004
    restored = ser.simulation_from_dict(payload)
    assert restored.config == config and restored.strategy_id == result.strategy_id
    assert restored.metrics == result.metrics and restored.provenance == result.provenance
    assert frames_identical(restored.monthly, result.monthly)
    assert str(restored.monthly["timestamp"].dtype) == "datetime64[ns]"


def test_provenance_labels_inputs(assumptions, example_config):
    mock = simulate_strategy(make_baseline(), example_config, assumptions=assumptions)
    real = simulate_strategy(make_baseline(is_mock=False), example_config, assumptions=assumptions)
    assert mock.provenance.provider == "action-engine" and mock.provenance.is_mock is True
    assert real.provenance.is_mock is False
    assert real.provenance.assumptions_id == "demo-actions-v1" and real.provenance.seed is None
    other = simulate_strategy(make_baseline(), ActionConfig.noop(), assumptions=assumptions)
    assert other.provenance.input_hash != mock.provenance.input_hash


# ---------------------------------------------------------------------------
# Breakdown and uncertainty hook
# ---------------------------------------------------------------------------


def test_breakdown_matches_golden_intermediates_and_reconciles(baseline, assumptions, example_config):
    breakdown = compute_action_breakdown(baseline, example_config, assumptions=assumptions).iloc[0]
    expected = {
        "renewable_energy_share": 0.76,
        "ev_share": 0.4,
        "electricity_kwh": 99_800.0,  # 100,000 - 4,200 + 4,000
        "gas_kwh": 47_000.0,
        "electricity_saved_kwh": 4_200.0,  # 100,000 * 0.7 * 0.06
        "gas_saved_kwh": 3_000.0,
        "ev_converted_km": 20_000.0,
        "ev_extra_kwh": 4_000.0,
        "gas_baseline_tco2e": 12.0,
        "gas_tco2e": 11.28,
        "ice_fleet_tco2e": 4.8,
        "existing_scope2_tco2e": 8.622,  # 30 * 0.958 * 0.24 / 0.8
        "ev_scope2_tco2e": 0.36,  # 4,000 * 0.000375 * 0.24
        "travel_tco2e": 7.0,
        "cloud_tco2e": 9.0,
        "supplier_tco2e": 24.25,
        "other_tco2e": 5.0,
        "renewable_premium_gbp": 1_117.76,  # 99,800 * 0.56 * 0.02
        "ev_electricity_cost_gbp": 600.0,
        "fixed_opex_gbp": 164.0,
    }
    for name, value in expected.items():
        assert breakdown[name] == close(value), name
    row = month(simulate_strategy(baseline, example_config, assumptions=assumptions))
    assert breakdown["gas_tco2e"] + breakdown["ice_fleet_tco2e"] == close(row["scope1_tco2e"])
    assert breakdown["existing_scope2_tco2e"] + breakdown["ev_scope2_tco2e"] == close(row["scope2_tco2e"])
    scope3 = breakdown[["travel_tco2e", "cloud_tco2e", "supplier_tco2e", "other_tco2e"]].sum()
    assert scope3 == close(row["scope3_tco2e"])


def test_unit_uncertainty_sample_reproduces_deterministic_outcomes(baseline, assumptions, example_config):
    ones = dict.fromkeys(ACTION_NAMES, 1.0)
    sampled = apply_uncertainty_sample(
        assumptions, sample_id="demo-actions-v1/trial-0", effectiveness_multipliers=ones, capex_multipliers=ones, opex_multipliers=ones
    )
    deterministic = simulate_strategy(baseline, example_config, assumptions=assumptions)
    trial = simulate_strategy(baseline, example_config, assumptions=sampled)
    assert frames_identical(trial.monthly, deterministic.monthly) and trial.metrics == deterministic.metrics
    assert trial.strategy_id != deterministic.strategy_id  # sampled parameters never share an identity


def test_uncertainty_sample_follows_the_documented_mapping(assumptions):
    sampled = apply_uncertainty_sample(
        assumptions,
        sample_id="trial-1",
        effectiveness_multipliers={"renewable_energy": 0.9, "building_efficiency": 0.9, "supplier_transition": 0.85},
        capex_multipliers={"renewable_energy": 1.1},
        opex_multipliers={"cloud_efficiency": 0.9},
    )
    assert sampled.renewable_effectiveness == 0.9  # replaced
    assert sampled.building_max_reduction == close(0.27)  # 0.3 * 0.9 scaled
    assert sampled.supplier_max_reduction == close(0.255)
    assert sampled.supplier_monthly_savings_at_full_gbp == close(850.0)
    assert sampled.costs["renewable_energy"].capex_at_full_gbp == close(110_000.0)
    assert sampled.costs["cloud_efficiency"].monthly_opex_at_full_gbp == close(18.0)
    assert sampled.costs["ev_adoption"] == assumptions.costs["ev_adoption"]
    assert sampled.assumptions_id == "trial-1" and sampled.version == assumptions.version
    assert assumptions == fixture_assumptions()  # parent unchanged


@pytest.mark.parametrize(
    "kwargs",
    [
        {"sample_id": "demo-actions-v1"},
        {"sample_id": "t", "effectiveness_multipliers": {"heat_pumps": 0.9}},
        {"sample_id": "t", "effectiveness_multipliers": {"renewable_energy": 1.1}},
        {"sample_id": "t", "capex_multipliers": {"ev_adoption": -0.1}},
        {"sample_id": ""},
    ],
)
def test_invalid_uncertainty_samples_are_rejected(assumptions, kwargs):
    with pytest.raises(ContractValidationError):
        apply_uncertainty_sample(assumptions, **kwargs)
