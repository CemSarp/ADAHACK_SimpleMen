"""AppTest of the "Real data and sources" section: offline startup, labels, and untouched optimizer inputs."""

from __future__ import annotations

import datetime as dt
import io
import json
import urllib.request

import pytest

st = pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402

from tests.support import REPO_ROOT  # noqa: E402

APP = str(REPO_ROOT / "app.py")
SAVING = "CO₂e saved per year (tCO2e)"
LIVE_KEY = "co_grounding_grid_live"


def _no_network(*args, **kwargs):
    raise AssertionError("network access during app render")


def _timeout(*args, **kwargs):
    raise TimeoutError("timed out")


@pytest.fixture(autouse=True)
def _fresh_cache():
    st.cache_data.clear()  # a cached live fetch from one test must not leak into another


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
    assert "What are scopes?" in [e.label for e in app.expander] and "**Scope 2:**" in text
    assert "7_400_4000_5_1" in text and "gross energy-cost savings before capex/opex" in text
    assert _metric(app, SAVING) == "1,014.74" and "2026-factor scenario using FY2024 activity" in text
    assert _metric(app, "Energy-cost saving per year (£)") == "1,937,125"
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


def _refresh(at: AppTest) -> AppTest:
    [b for b in at.button if b.label == "Refresh grid forecast"][0].click().run()
    assert not at.exception, [e.message for e in at.exception]
    return at


def _best_upcoming(at: AppTest) -> list[str]:
    return [s for s in _texts(at.success) if s.startswith("Best upcoming hour")]


def test_recorded_grid_snapshot_is_labelled_and_not_offered_as_upcoming(app):
    text = _markdown(app)
    assert "Recorded example" in text
    assert "retrieved 2026-10-03 16:02 UTC" in text and "covers 03 Oct" in text
    assert "Historical replay, not an upcoming recommendation" in text
    assert "Live forecast" not in text and not _best_upcoming(app)
    assert any(s.startswith("Cleanest hour in the saved forecast") for s in _texts(app.info))
    assert [b for b in app.button if b.label == "Refresh grid forecast"]


def test_refresh_timeout_keeps_recorded_panel_and_dashboard(app, monkeypatch):
    monkeypatch.setattr(urllib.request, "urlopen", _timeout)
    _refresh(app)
    assert any("Grid refresh failed" in e for e in _texts(app.error))
    assert "Recorded example" in _markdown(app)
    assert app.session_state["cos_baseline"].company_id == "supply-chain-demo-co"
    assert [b for b in app.button if b.label == "Optimize"]


def _future_response() -> bytes:
    now = dt.datetime.now(dt.timezone.utc)
    start = now.replace(minute=now.minute // 30 * 30, second=0, microsecond=0)
    fmt, half = "%Y-%m-%dT%H:%MZ", dt.timedelta(minutes=30)
    return json.dumps({"data": [
        {"from": (start + i * half).strftime(fmt), "to": (start + (i + 1) * half).strftime(fmt),
         "intensity": {"forecast": f, "actual": None, "index": "moderate"}}
        for i, f in enumerate([200, 200, 180, 150, 60, 60, 120, 140])
    ]}).encode()


def test_failed_refresh_after_live_success_falls_back_to_recorded(app, monkeypatch):
    body = _future_response()
    monkeypatch.setattr(urllib.request, "urlopen", lambda *args, **kwargs: io.BytesIO(body))
    _refresh(app)
    assert "Live forecast" in _markdown(app) and _best_upcoming(app)
    st.cache_data.clear()
    monkeypatch.setattr(urllib.request, "urlopen", _timeout)
    _refresh(app)
    assert any("showing the saved example instead" in e for e in _texts(app.error))
    text = _markdown(app)
    assert "Recorded example" in text and "Live forecast" not in text and not _best_upcoming(app)


def test_stale_live_copy_is_not_labelled_live(app):
    from src.data_sources.public_data import load_grid_snapshot
    old = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=2)
    app.session_state[LIVE_KEY] = {**load_grid_snapshot(), "data_kind": "live_forecast",
                                   "fetched_at": old.strftime("%Y-%m-%dT%H:%M:%SZ")}
    app.run()
    text = _markdown(app)
    assert "over 30 minutes old" in text and "Recorded example" in text and "Live forecast" not in text
