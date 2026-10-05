"""WS3 risk + benchmark providers discovered through the real-provider registry."""

from __future__ import annotations

import json
import shutil
from dataclasses import replace

import pytest

from src.benchmarking import adapters
from src.benchmarking import provider as bench_provider
from src.contracts import serialization as ser
from src.contracts import validation as val
from src.contracts.protocols import BenchmarkProvider, RiskProvider
from src.contracts.types import AnalysisBundle, RiskConfig
from src.integration import run_analysis
from src.optimization.recommendation import risk_pool_from_frontier
from tests.mocks import make_services

OVERRIDES = {"risk": "real", "benchmark": "real"}


@pytest.fixture
def full_request(request_ok):
    return replace(request_ok, risk_enabled=True, benchmark_enabled=True, risk_config=RiskConfig(seed=3, n_simulations=50))


@pytest.fixture
def repo_copy(monkeypatch, tmp_path):
    """Isolated copy of the benchmark config and snapshot."""
    for rel in ("config/benchmark.json", "data/benchmark.csv", "data/benchmark_metadata.json"):
        (tmp_path / rel).parent.mkdir(exist_ok=True)
        shutil.copy(adapters.REPO_ROOT / rel, tmp_path / rel)
    monkeypatch.setattr(adapters, "REPO_ROOT", tmp_path)
    return tmp_path


def _assert_p0_and_risk_ok(bundle: AnalysisBundle) -> None:
    assert bundle.optimization.status == "ok" and bundle.recommendation.strategy_id is not None
    assert set(bundle.risk_results) == set(risk_pool_from_frontier(bundle.optimization.pareto))
    assert ser.from_json(AnalysisBundle, ser.to_json(bundle)).benchmark == bundle.benchmark


def test_hybrid_discovers_both_ws3_providers():
    services = make_services(OVERRIDES)
    assert isinstance(services.risk, RiskProvider) and isinstance(services.benchmark, BenchmarkProvider)
    info = services.providers["benchmark"]
    assert (info.slot, info.kind, info.is_mock) == ("benchmark", "real", False)
    assert info.version.startswith("ws3-benchmark-1+synthetic-peers-v1+c") and "+d" in info.version and "+m" in info.version
    assert services.capabilities.risk_available and services.capabilities.benchmark_available


def test_pipeline_with_risk_and_benchmark(full_request):
    services = make_services(OVERRIDES)
    bundle = run_analysis(full_request, services=services)
    b = bundle.benchmark
    val.validate_benchmark_result(b)
    assert (b.status, b.company_intensity_tco2e_per_million_gbp, b.industry_median, b.percentile, b.better_than_pct,
            b.peer_count) == ("ok", 100, 105, 45, 55, 10)
    assert b.is_synthetic and b.source_id == "synthetic-peers-v1" and b.comparison_basis == "forecast_vs_historical_peers"
    pareto_ids = set(bundle.optimization.pareto["strategy_id"])
    assert bundle.risk_results and set(bundle.risk_results) <= pareto_ids
    assert all(r.strategy_id == sid for sid, r in bundle.risk_results.items())
    assert {"risk", "benchmark"} <= set(bundle.providers) and not bundle.warnings
    back = ser.from_json(AnalysisBundle, ser.to_json(bundle))
    assert back.benchmark == b and back.risk_results.keys() == bundle.risk_results.keys()
    _assert_p0_and_risk_ok(bundle)


@pytest.mark.parametrize("damage, code", [
    (lambda root: (root / "data/benchmark.csv").unlink(), "offline_snapshot_missing"),
    (lambda root: (root / "data/benchmark.csv").write_text("peer_id,broken\nx,1\n"), "snapshot_invalid"),
    (lambda root: (root / "data/benchmark_metadata.json").write_text("{not json"), "snapshot_invalid"),
])
def test_missing_or_corrupt_snapshot_leaves_p0_and_risk_usable(repo_copy, full_request, damage, code):
    damage(repo_copy)
    services = make_services(OVERRIDES)
    bundle = run_analysis(full_request, services=services)
    b = bundle.benchmark
    assert b.status == "unavailable" and b.reason.startswith(f"source_unavailable: {code}")
    assert b.percentile is None and b.industry_median is None and b.company_intensity_tco2e_per_million_gbp is None
    assert b.is_synthetic  # label kept from the configured source
    _assert_p0_and_risk_ok(bundle)


def test_snapshot_changed_after_binding_is_unavailable(repo_copy, full_request):
    services = make_services(OVERRIDES)
    csv = repo_copy / "data/benchmark.csv"
    csv.write_text(csv.read_text().replace("2000,", "2001,", 1))
    bundle = run_analysis(full_request, services=services)
    assert bundle.benchmark.reason.startswith("source_unavailable: snapshot_hash_mismatch")
    _assert_p0_and_risk_ok(bundle)


def test_version_tracks_config_and_snapshot_content(repo_copy):
    before = bench_provider.create_benchmark_provider().info.version
    cfg = json.loads((repo_copy / "config/benchmark.json").read_text())
    cfg["config"]["max_period_end_gap_months"] = 12
    (repo_copy / "config/benchmark.json").write_text(json.dumps(cfg))
    after_config = bench_provider.create_benchmark_provider().info.version
    meta = repo_copy / "data/benchmark_metadata.json"
    meta.write_text(meta.read_text().replace("Synthetic example", "Synthetic sample"))
    after_meta = bench_provider.create_benchmark_provider().info.version
    assert len({before, after_config, after_meta}) == 3


def test_unexpected_bug_surfaces(monkeypatch, full_request):
    def broken(*args, **kwargs):
        raise RuntimeError("programming bug")

    monkeypatch.setattr(bench_provider, "benchmark_company", broken)
    services = make_services(OVERRIDES)
    with pytest.raises(RuntimeError, match="programming bug"):
        run_analysis(full_request, services=services)


def _risk_spec_variants():
    spec = json.loads((adapters.REPO_ROOT / "config/uncertainty.json").read_text())
    reversed_bounds = json.loads(json.dumps(spec))
    reversed_bounds["actions"]["ev_adoption"]["capex"] = [1.1, 0.9]
    return {"missing": None, "bad_json": "{not json", "reversed_bounds": json.dumps(reversed_bounds), "not_object": "[]"}


@pytest.mark.parametrize("case", ["missing", "bad_json", "reversed_bounds", "not_object"])
def test_invalid_uncertainty_config_disables_only_risk(monkeypatch, tmp_path, full_request, case):
    from src.risk import provider as risk_provider

    content = _risk_spec_variants()[case]
    path = tmp_path / "uncertainty.json"
    if content is not None:
        path.write_text(content)
    monkeypatch.setattr(risk_provider, "DEFAULT_UNCERTAINTY_PATH", path)
    services = make_services(OVERRIDES)
    assert services.risk is None and not services.capabilities.risk_available
    assert services.unavailable["risk"].startswith("uncertainty")
    bundle = run_analysis(full_request, services=services)
    assert bundle.optimization.status == "ok" and bundle.risk_results == {}
    assert any(w.startswith("Risk is unavailable: uncertainty") for w in bundle.warnings)
    assert bundle.benchmark.status == "ok"  # other optional capability unaffected


@pytest.mark.parametrize("damage", [
    lambda cfg: cfg.unlink(),
    lambda cfg: cfg.write_text("{not json"),
    lambda cfg: cfg.write_text(json.dumps({"config": {}})),
    lambda cfg: cfg.write_text(cfg.read_text().replace('"min_peers": 10', '"min_peers": 0')),
    lambda cfg: cfg.write_text(cfg.read_text().replace('"min_peers": 10', '"min_peerz": 10')),
], ids=["missing", "bad_json", "no_source", "invalid_value", "unknown_field"])
def test_invalid_benchmark_config_disables_only_benchmark(repo_copy, full_request, damage):
    damage(repo_copy / "config/benchmark.json")
    services = make_services(OVERRIDES)
    assert services.benchmark is None and not services.capabilities.benchmark_available
    assert services.unavailable["benchmark"].startswith("benchmark_config")
    bundle = run_analysis(full_request, services=services)
    assert bundle.benchmark is None and any(w.startswith("Benchmark is unavailable") for w in bundle.warnings)
    _assert_p0_and_risk_ok(bundle)


def test_factory_programming_error_still_surfaces(monkeypatch):
    from src.risk import provider as risk_provider

    def bug(path):
        raise TypeError("programming bug")

    monkeypatch.setattr(risk_provider, "load_uncertainty", bug)
    with pytest.raises(TypeError, match="programming bug"):
        make_services(OVERRIDES)
