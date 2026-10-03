from __future__ import annotations

import json
import shutil
import socket

import pandas as pd
import pytest

from src.benchmarking import adapters
from src.benchmarking.adapters import BenchmarkSource, BenchmarkSourceError, load_benchmark_data
from src.benchmarking.benchmark import INTENSITY_TIE_ATOL as TOL
from src.benchmarking.benchmark import BenchmarkConfig, benchmark_company
from src.benchmarking.normalize import BenchmarkDataset, normalize_peers
from src.contracts import serialization as ser
from src.contracts.errors import ContractValidationError
from src.contracts.types import BenchmarkResult
from tests.mocks import fixtures

CFG = json.loads((adapters.REPO_ROOT / "config" / "benchmark.json").read_text())


def _source(**kw) -> BenchmarkSource:
    return BenchmarkSource.from_dict({**CFG["source"], **kw})


def _config(**kw) -> BenchmarkConfig:
    return BenchmarkConfig.from_dict({**CFG["config"], **kw})


def _peers(metadata=None, **cols):
    raw = fixtures.load_json("benchmark_peers.json")
    df = pd.DataFrame(raw["peers"])
    for k, v in cols.items():
        df[k] = v
    return df, {**raw["metadata"], **(metadata or {})}


def _with_intensities(values):
    df, meta = _peers()
    df["intensity_tco2e_per_million_gbp"] = values
    df["total_co2e_tco2e"] = [v * 10 for v in values]  # revenue is 10m GBP
    return normalize_peers(df, meta)


def _bench(dataset=None, **cfg) -> BenchmarkResult:
    return benchmark_company(fixtures.baseline(), dataset or load_benchmark_data(source=_source(), offline=True), config=_config(**cfg))


def test_offline_fixture_oracle_matches_shared_fixture():
    r = _bench()
    expected = fixtures.benchmark()
    for f in ("status", "company_intensity_tco2e_per_million_gbp", "industry_median", "percentile", "better_than_pct",
              "peer_count", "source_id", "source_url", "retrieved_at", "snapshot_id", "is_synthetic", "period_start",
              "period_end", "scope_coverage", "scope2_method", "comparison_basis", "reason"):
        assert getattr(r, f) == getattr(expected, f), f
    assert (r.company_intensity_tco2e_per_million_gbp, r.industry_median, r.percentile, r.better_than_pct, r.peer_count) == (100, 105, 45, 55, 10)
    assert r.is_synthetic and r.provenance.provider == "ws3-benchmark"


@pytest.mark.parametrize("values, percentile", [
    ([100.0] * 10, 50.0),                                                    # all ties
    ([150.0] * 10, 0.0),                                                     # all higher
    ([50.0] * 10, 100.0),                                                    # all lower
    ([100 - 2 * TOL, 100 - TOL / 2, 100, 100 + TOL / 2, 100 + 2 * TOL] + [200.0] * 5, 25.0),  # L1 E3 G6
])
def test_ties_and_tolerance(values, percentile):
    r = _bench(_with_intensities(values))
    assert r.percentile == pytest.approx(percentile) and r.better_than_pct == pytest.approx(100 - percentile)


def test_nine_peers_is_unavailable_not_rank_zero():
    df, meta = _peers()
    r = _bench(normalize_peers(df.iloc[:9], meta))
    assert r.status == "unavailable" and r.percentile is None and r.peer_count == 9
    assert r.reason.startswith("insufficient_peers: 9")
    r = _bench(exclude_entity_ids=["synthetic-peer-05"])
    assert r.status == "unavailable" and "target_entity=1" in r.reason


def test_units_currency_and_revenue():
    df, meta = _peers()
    with pytest.raises(ContractValidationError, match="kgco2e_to_tco2e"):
        normalize_peers(df, {**meta, "original_emissions_unit": "kgco2e"})
    assert len(normalize_peers(df, {**meta, "original_emissions_unit": "kgco2e", "transforms": ["kgco2e_to_tco2e"]}).peers) == 10
    with pytest.raises(ContractValidationError, match="GBP"):
        normalize_peers(df, {**meta, "original_currency": "USD"})
    with pytest.raises(ContractValidationError):
        normalize_peers(df, {**meta, "original_emissions_unit": "lbco2e"})

    bad = df.copy()
    bad.loc[0, "revenue_gbp"] = 0
    bad.loc[1, "revenue_gbp"] = 10  # reported in millions: computed intensity disagrees
    bad.loc[2, "total_co2e_tco2e"] = None  # missing emissions are never 0
    ds = normalize_peers(bad, meta)
    assert {e["reason"] for e in ds.metadata["exclusions"]} == {"nonpositive_revenue", "intensity_mismatch", "invalid_emissions"}
    assert len(ds.peers) == 7 and _bench(ds).status == "unavailable"


def test_method_scope_and_period_mismatch():
    assert _bench(scope2_method="location_based").reason.startswith("method_mismatch")
    df, meta = _peers()
    df.loc[0, "scope_coverage"] = "scope1_scope2"
    df.loc[1, "scope2_method"] = "location_based"
    r = _bench(normalize_peers(df, meta))
    assert r.status == "unavailable" and "scope_mismatch=1" in r.reason and "method_mismatch=1" in r.reason
    df, meta = _peers(period_start="2024-01-01", period_end="2024-12-31")  # 36-month gap > 24
    assert "period_gap=10" in _bench(normalize_peers(df, meta)).reason
    df, meta = _peers()
    df.loc[0, "period_end"] = "2026-11-30"  # 11 months
    ds = normalize_peers(df, meta)
    assert ds.metadata["exclusions"] == [{"peer_id": "synthetic-peer-01", "reason": "non_annual_period"}]


def test_target_entity_excluded_and_newest_period_per_entity():
    df, meta = _peers()
    df["entity_id"] = df["peer_id"]
    extra = pd.DataFrame([
        {**df.iloc[0].to_dict(), "peer_id": "self-2026", "entity_id": "demo-company",
         "total_co2e_tco2e": 500, "intensity_tco2e_per_million_gbp": 50},
        {**df.iloc[9].to_dict(), "peer_id": "synthetic-peer-10-2025", "period_start": "2025-01-01",
         "period_end": "2025-12-31", "total_co2e_tco2e": 100, "intensity_tco2e_per_million_gbp": 10},
    ])
    r = _bench(normalize_peers(pd.concat([df, extra], ignore_index=True), meta))
    assert (r.percentile, r.peer_count, r.industry_median) == (45, 10, 105)


def test_zero_network(monkeypatch):
    def no_network(*a, **k):
        raise AssertionError("network access attempted")

    monkeypatch.setattr(socket.socket, "connect", no_network)
    monkeypatch.setattr(socket, "create_connection", no_network)
    for offline in (True, False):  # CSV never needs the network
        assert _bench(load_benchmark_data(source=_source(), offline=offline)).status == "ok"


def test_missing_corrupt_and_unsupported_sources(monkeypatch, tmp_path):
    (tmp_path / "data").mkdir()
    for name in ("benchmark.csv", "benchmark_metadata.json"):
        shutil.copy(adapters.REPO_ROOT / "data" / name, tmp_path / "data" / name)
    monkeypatch.setattr(adapters, "REPO_ROOT", tmp_path)
    assert len(load_benchmark_data(source=_source()).peers) == 10

    with pytest.raises(BenchmarkSourceError) as exc:
        load_benchmark_data(source=_source(kind="http"))
    assert exc.value.reason_code == "unsupported_source"
    with pytest.raises(BenchmarkSourceError) as exc:
        load_benchmark_data(source=_source(source_id="other-source"))
    assert exc.value.reason_code == "snapshot_invalid"

    csv = tmp_path / "data" / "benchmark.csv"
    csv.write_text(csv.read_text().replace("revenue_gbp", "revenue_usd", 1))
    with pytest.raises(BenchmarkSourceError) as exc:
        load_benchmark_data(source=_source())
    assert exc.value.reason_code == "snapshot_invalid"
    (tmp_path / "data" / "benchmark_metadata.json").write_text("{not json")
    with pytest.raises(BenchmarkSourceError) as exc:
        load_benchmark_data(source=_source())
    assert exc.value.reason_code == "snapshot_invalid"
    csv.unlink()
    with pytest.raises(BenchmarkSourceError) as exc:
        load_benchmark_data(source=_source())
    assert exc.value.reason_code == "offline_snapshot_missing"


def test_dataset_duplicates_and_mixed_labels_rejected():
    df, meta = _peers()
    with pytest.raises(ContractValidationError, match="unique"):
        normalize_peers(pd.concat([df, df.iloc[[0]]]), meta)
    df.loc[0, "is_synthetic"] = False
    with pytest.raises(ContractValidationError, match="mix"):
        normalize_peers(df, meta)


def test_json_round_trips():
    ds = load_benchmark_data(source=_source())
    back = BenchmarkDataset.from_dict(json.loads(json.dumps(ds.to_dict())))
    pd.testing.assert_frame_equal(back.peers, ds.peers)
    assert back.metadata == ds.metadata
    r = _bench(ds)
    assert ser.to_dict(ser.from_json(BenchmarkResult, ser.to_json(r))) == ser.to_dict(r)
    assert BenchmarkConfig.from_dict(_config().to_dict()) == _config()


@pytest.mark.parametrize("bad", [{"min_peers": 0}, {"min_peers": True}, {"max_period_end_gap_months": -1},
                                 {"comparison_basis": "same_year"}, {"industry": ""}])
def test_invalid_config_rejected(bad):
    with pytest.raises(ContractValidationError):
        _config(**bad)
    with pytest.raises(ContractValidationError):
        BenchmarkSource.from_dict({**CFG["source"], "snapshot_path": "/abs/benchmark.csv"})


def _baseline_36m():
    from dataclasses import replace

    from src.contracts.validation import validate_baseline

    b = fixtures.baseline()
    monthly = pd.concat([b.monthly] * 3, ignore_index=True)
    monthly["timestamp"] = pd.date_range(b.monthly["timestamp"].iloc[0], periods=36, freq="MS")
    totals = {k: float(monthly[k].sum()) for k in b.totals}
    return validate_baseline(replace(b, horizon_months=36, monthly=monthly, totals=totals, baseline_id="baseline-demo-36m"))


def test_longer_horizon_is_unavailable_not_ranked():
    r = benchmark_company(_baseline_36m(), load_benchmark_data(source=_source()), config=_config())
    assert r.status == "unavailable" and r.reason.startswith("unsupported_horizon")
    assert (r.company_intensity_tco2e_per_million_gbp, r.industry_median, r.percentile, r.better_than_pct) == (None,) * 4
    assert (r.period_start, r.period_end, r.is_synthetic) == ("2027-01-01", "2029-12-31", True)
