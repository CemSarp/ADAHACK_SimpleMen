"""Presentation helpers and provider-agnostic chart builders."""

from __future__ import annotations

from dataclasses import replace

import pytest

from src.dashboard import charts
from src.dashboard.presentation import gbp, pct, period_label, resulting_share, tonnes
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
        frontier = [t for t in pf.figure.data if t.name == "Pareto frontier"][0]
        assert len(frontier.x) == len(opt.pareto)
        # Every clickable point maps back to a stored strategy ID.
        assert set(pf.point_ids.values()) <= set(opt.strategies)
        assert pareto_ids <= set(pf.point_ids.values())
        selected = opt.strategies[sid]
        charts.monthly_comparison(bundle.baseline, {"selected": selected, "whatif": selected}, dark=dark)
        charts.scope_totals(bundle.baseline, {"selected": selected}, dark=dark)
        charts.backtest_predictions(bundle.backtest, "total_co2e_tco2e", dark=dark)
        charts.history_and_baseline(fixtures.history(), bundle.baseline, "operating_profit_gbp", dark=dark)


def test_pareto_chart_values_are_unchanged_provider_values(mock_services, request_ok):
    bundle = run_analysis(request_ok, services=mock_services)
    pf = charts.pareto_scatter(bundle.optimization, bundle.baseline, selected_id=None, recommended_id=None)
    frontier = [t for t in pf.figure.data if t.name == "Pareto frontier"][0]
    expected = bundle.optimization.pareto.sort_values("total_co2e_tco2e")
    assert list(frontier.x) == expected["total_co2e_tco2e"].tolist()
    assert list(frontier.y) == expected["total_profit_gbp"].tolist()


def test_empty_frontier_draws_no_frontier_or_recommendation(mock_services, request_infeasible):
    bundle = run_analysis(request_infeasible, services=mock_services)
    pf = charts.pareto_scatter(bundle.optimization, bundle.baseline, selected_id=None,
                               recommended_id=bundle.recommendation.strategy_id)
    names = {t.name for t in pf.figure.data}
    assert "Pareto frontier" not in names and "Recommended" not in names
    assert "Infeasible candidate" in names


def test_optional_panel_charts_from_fixtures():
    charts.risk_intervals(fixtures.risk(), fixtures.simulation("nonzero"))
    charts.shap_contributions(fixtures.explanation(), "total_co2e_tco2e")
    charts.benchmark_position(fixtures.benchmark())
