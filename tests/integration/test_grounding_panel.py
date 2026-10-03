"""AppTest of the "Real data and sources" section: offline startup, labels, and untouched optimizer inputs."""

from __future__ import annotations

import urllib.request

import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402

from tests.support import REPO_ROOT  # noqa: E402

APP = str(REPO_ROOT / "app.py")
SAVING = "CO₂e saved (tCO2e)"


def _no_network(*args, **kwargs):
    raise AssertionError("network access during app render")


@pytest.fixture
def app(monkeypatch):
    monkeypatch.setattr(urllib.request, "urlopen", _no_network)
    at = AppTest.from_file(APP, default_timeout=300).run()
    assert not at.exception, [e.message for e in at.exception]
    return at


def _texts(elements) -> list[str]:
    return [e.value for e in elements]


def _markdown(at: AppTest) -> str:
    return "\n".join(_texts(at.markdown) + _texts(at.caption))


def _metric(at: AppTest, label: str) -> str:
    return next(m.value for m in at.metric if m.label == label)


def test_section_loads_offline_with_sources_and_historical_label(app):
    assert "Real data and sources" in [e.label for e in app.expander]
    text = _markdown(app)
    assert "Historical public reference; separate from the synthetic optimization company." in text
    assert "2023-04-01" in text and "2024-03-31" in text
    for url in ("Wincanton_Annual_Review_2024.pdf", "ghg-conversion-factors-2026-flat-format-revised.xlsx",
                "greenhouse-gas-reporting-conversion-factors-2026", "carbon-intensity.github.io/api-definitions",
                "cloud-carbon-footprint"):
        assert url in text, url
    assert "planned; current cloud estimates illustrative" in text
    assert "7_400_4000_5_1" in text and "gross energy-cost savings before capex/opex" in text
    assert _metric(app, SAVING) == "1,014.74" and "2026-factor scenario using FY2024 activity" in text
    assert _metric(app, "Gross energy-cost saving (£)") == "1,937,125"
    assert app.session_state["cos_baseline"].company_id == "supply-chain-demo-co"
    assert not app.session_state["cos_baseline"].provenance.is_mock


def test_calculator_change_leaves_optimizer_company_untouched(app):
    before = app.session_state["cos_baseline"]
    app.slider(key="co_grounding_reduction_pct").set_value(20).run()
    assert not app.exception, [e.message for e in app.exception]
    assert _metric(app, SAVING) == "2,029.49"
    after = app.session_state["cos_baseline"]
    assert (after.baseline_id, after.company_id) == (before.baseline_id, before.company_id)
    assert after.company_id == "supply-chain-demo-co"


def test_custom_activity_is_labelled_user_entered(app):
    app.number_input(key="co_grounding_kwh").set_value(1_000_000.0).run()
    assert any("user-entered, not a reported company value" in c for c in _texts(app.caption))


def test_recorded_grid_snapshot_is_labelled_and_not_offered_as_upcoming(app):
    text = _markdown(app)
    assert "**Recorded example**" in text
    assert "retrieved 2026-10-03 16:02 UTC" in text and "forecast period" in text
    assert "historical replay, not an upcoming recommendation" in text
    assert "Live forecast" not in text and "Recommended upcoming window" not in text
    assert [b for b in app.button if b.label == "Refresh grid forecast"]


def test_refresh_timeout_keeps_recorded_panel_and_dashboard(app, monkeypatch):
    def timeout(*args, **kwargs):
        raise TimeoutError("timed out")
    monkeypatch.setattr(urllib.request, "urlopen", timeout)
    [b for b in app.button if b.label == "Refresh grid forecast"][0].click().run()
    assert not app.exception, [e.message for e in app.exception]
    assert any("Grid refresh failed" in e for e in _texts(app.error))
    assert "**Recorded example**" in _markdown(app)
    assert app.session_state["cos_baseline"].company_id == "supply-chain-demo-co"
    assert [b for b in app.button if b.label == "Optimize"]
