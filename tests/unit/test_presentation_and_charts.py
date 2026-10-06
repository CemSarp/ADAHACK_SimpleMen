"""Presentation helpers and provider-agnostic chart builders."""

from __future__ import annotations

from dataclasses import replace

import pandas as pd
import pytest

from src.dashboard import charts
from src.dashboard.presentation import gbp, hint_lines, pct, period_label, resulting_share, tonnes, uncertainty_method
from src.integration import run_analysis
from tests.mocks import fixtures


def test_resulting_share_follows_documented_semantics():
    baseline, a = fixtures.baseline(), fixtures.assumptions()
    share = resulting_share(baseline, "renewable_energy", 0.7, a)
    assert share.baseline_min == 0.2 and share.resulting_min == pytest.approx(0.2 + 0.8 * 0.7)
    assert share.describe() == "20% → 76%"
    ev = resulting_share(baseline, "ev_adoption", 0.4, replace(a, ev_effectiveness=0.5))
    assert ev.resulting_max == pytest.approx(0.0 + 1.0 * 0.4 * 0.5)
    assert resulting_share(baseline, "cloud_efficiency", 0.4, a) is None


def test_formatting_units():
    assert gbp(1210940.78) == "£1,210,941" and gbp(-132221.12, signed=True) == "−£132,221"
    assert tonnes(843.744) == "843.7 tCO₂e" and pct(0.29688) == "29.7%" and pct(None) == "n/a"
    assert period_label(fixtures.baseline().monthly["timestamp"]) == "Jan 2027 – Dec 2027 (12 months)"


@pytest.mark.parametrize("dark", [False, True])
def test_charts_render_from_fixture_and_behavioral_providers(dark, mock_services, fixture_services, request_ok):
    """The same chart code consumes fixture shape stubs and behavioral outputs."""
    for services in (fixture_services, mock_services):
        bundle = run_analysis(request_ok, services=services)
        opt = bundle.optimization
        sid = bundle.recommendation.strategy_id
        pf = charts.pareto_scatter(opt, bundle.baseline, selected_id=sid, recommended_id=sid, dark=dark)
        pareto_ids = set(opt.pareto["strategy_id"])
        frontier = [t for t in pf.figure.data if t.name == "Best trade-offs"][0]
        assert len(frontier.x) == len(opt.pareto)
        # Every clickable point maps back to a stored strategy ID.
        assert set(pf.point_ids.values()) <= set(opt.strategies)
        assert pareto_ids <= set(pf.point_ids.values())
        selected = opt.strategies[sid]
        charts.scope_totals(bundle.baseline, {"selected": selected, "whatif": selected}, dark=dark)
        for column in ("total_co2e_tco2e", "operating_profit_gbp"):
            charts.history_forecast(fixtures.history(), bundle.baseline, column, dark=dark)


def test_pareto_chart_values_are_unchanged_provider_values(mock_services, request_ok):
    bundle = run_analysis(request_ok, services=mock_services)
    pf = charts.pareto_scatter(bundle.optimization, bundle.baseline, selected_id=None, recommended_id=None)
    frontier = [t for t in pf.figure.data if t.name == "Best trade-offs"][0]
    expected = bundle.optimization.pareto.sort_values("total_co2e_tco2e")
    assert list(frontier.x) == expected["total_co2e_tco2e"].tolist()
    assert list(frontier.y) == expected["total_profit_gbp"].tolist()


def test_empty_frontier_draws_no_frontier_or_recommendation(mock_services, request_infeasible):
    bundle = run_analysis(request_infeasible, services=mock_services)
    pf = charts.pareto_scatter(bundle.optimization, bundle.baseline, selected_id=None,
                               recommended_id=bundle.recommendation.strategy_id)
    names = {t.name for t in pf.figure.data}
    assert "Best trade-offs" not in names and "Recommended" not in names
    assert "Misses a goal" in names
    missed = next(t for t in pf.figure.data if t.name == "Misses a goal")
    assert missed.visible is True  # nothing met the goals, so show how close the tried mixes came


def test_optional_panel_charts_from_fixtures():
    charts.risk_intervals(fixtures.risk(), fixtures.simulation("nonzero"))
    charts.shap_top_k(fixtures.explanation(), "total_co2e_tco2e", k=3)
    charts.benchmark_position(fixtures.benchmark())


def test_infeasible_hints_round_towards_a_goal_that_works():
    from src.contracts.types import ConstraintConfig

    goals = ConstraintConfig(budget_gbp=500_000.0, min_total_profit_gbp=30_000_000.0, min_co2_reduction_ratio=0.2)
    lines = hint_lines({"budget_gbp": 1_234_567.0, "min_total_profit_gbp": 28_765_432.0,
                        "min_co2_reduction_ratio": 0.1279, "max_reduction_ratio": 0.4}, goals)
    text = " ".join(lines)
    assert "Raise the budget to about £1.3m" in text          # rounded up, so the plan still fits
    assert "Lower the profit floor to about £28m" in text      # rounded down
    assert "Lower the CO₂ target to 12%" in text               # whole percent, rounded down
    assert "Search depth" in text


def test_infeasible_hints_say_when_the_target_is_out_of_reach():
    from src.contracts.types import ConstraintConfig

    goals = ConstraintConfig(budget_gbp=0.0, min_total_profit_gbp=0.0, min_co2_reduction_ratio=0.5)
    text = " ".join(hint_lines({"budget_gbp": None, "min_total_profit_gbp": None, "min_co2_reduction_ratio": 0.0,
                                "max_reduction_ratio": 0.31}, goals))
    assert "31%" in text and "cannot reach a 50% cut" in text


def test_uncertainty_method_names_monte_carlo_and_the_ranges():
    from src.risk.provider import create_risk_provider

    text = uncertainty_method(create_risk_provider(), trials=1000)
    assert "Monte Carlo" in text and "1,000" in text
    assert "85%" in text and "100%" in text and "90%" in text and "110%" in text


def test_shap_top_k_keeps_k_inputs_and_groups_the_rest():
    exp = fixtures.explanation()
    target = exp.contributions["target"].iloc[0]
    n = exp.contributions.loc[exp.contributions["target"] == target, "feature"].nunique()
    share = charts.shap_importance(exp, target)
    assert abs(share.sum() - 1.0) < 1e-9 and share.is_monotonic_decreasing
    fig = charts.shap_top_k(exp, target, k=2)
    labels = list(fig.data[0].y)
    assert len(labels) == 3 and labels[0] == f"All other {n - 2} inputs"
    assert len(charts.shap_top_k(exp, target, k=n).data[0].y) == n  # nothing left to group
    # Bar length is the share of the movement, so the order, the lengths and the caption agree.
    assert list(fig.data[0].x)[1:] == sorted(list(fig.data[0].x)[1:])
    assert abs(sum(fig.data[0].x) - 100.0) < 1e-6


def test_history_window_limits_the_reported_months(mock_services, request_ok):
    bundle = run_analysis(request_ok, services=mock_services)
    history = fixtures.history()
    start, end = history["timestamp"].iloc[10], history["timestamp"].iloc[40]
    fig = charts.history_forecast(history, bundle.baseline, "total_co2e_tco2e", start=start, end=end)
    reported = fig.data[0]
    assert pd.Timestamp(reported.x[0]) == start and pd.Timestamp(reported.x[-1]) == end
    assert len(fig.data) == 1  # the forecast is only drawn when the window reaches the last reported month


@pytest.mark.parametrize("raw,label", [
    ("y_lag0_rel", "Last reported month"),
    ("y_lag3_rel", "3 months before that"),
    ("seasonal_ref_rel", "Same month last year"),
    ("level_growth_12m", "Growth over 12 months"),
    ("electricity_kwh_rel", "Electricity (kWh) vs its 12-month average"),
    ("renewable_energy_share_diff_12m", "Renewable share, change over 12 months"),
    ("target_month_sin", "Month of the year"),
    ("total_co2e_lag_1", "total co2e lag 1"),  # unknown names stay readable
])
def test_forecast_inputs_get_plain_names(raw, label):
    from src.dashboard.presentation import feature_label

    assert feature_label(raw) == label


def test_model_error_chart_has_one_bar_per_model_and_target():
    table = pd.DataFrame({"target": ["emissions", "profit"] * 2, "model": ["RandomForest"] * 2 + ["SeasonalNaive"] * 2,
                          "wape": [3.0, 9.0, 4.0, 7.5], "seconds": [1.0, 1.0, 0.1, 0.1], "note": [None] * 4})
    fig = charts.model_errors(table)
    assert [t.name for t in fig.data] == ["Emissions", "Operating profit"]
    assert list(fig.data[0].x) == [3.0, 4.0] and list(fig.data[0].y) == ["Random forest", "Seasonal repeat"]


def test_grid_chart_shades_the_cleanest_hour():
    times = pd.date_range("2026-01-01", periods=6, freq="30min")
    fig = charts.grid_intensity(pd.Series(times), pd.Series([200, 180, 90, 95, 210, 220]), (times[2], times[4]))
    assert len(fig.data) == 1 and len(fig.layout.shapes) == 1
    assert len(charts.grid_intensity(pd.Series(times), pd.Series([1.0] * 6), None).layout.shapes) == 0


def test_forecast_input_names_are_unique():
    from src.dashboard.presentation import _FEATURE_NAMES

    assert len(set(_FEATURE_NAMES.values())) == len(_FEATURE_NAMES)
