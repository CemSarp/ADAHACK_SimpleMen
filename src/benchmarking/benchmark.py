"""Baseline intensity versus compatible peers (RISK_AND_BENCHMARK_SPEC.md section 4).

Compares the 12-month forecast baseline totals with the latest compatible annual
peer periods ("forecast_vs_historical_peers"); peer periods may precede the
forecast period by up to `max_period_end_gap_months`. Comparison outcomes
(incompatible inputs, too few peers, unsupported horizon) are `unavailable`
results with a reason, never errors or a fake rank.
"""

from __future__ import annotations

import calendar
from collections import Counter
from dataclasses import dataclass
from typing import Any, Mapping

import numpy as np
import pandas as pd

from src.contracts.errors import ContractValidationError
from src.contracts.identity import canonical_hash
from src.contracts.types import SCHEMA_VERSION, BaselineBundle, BenchmarkResult, Provenance
from src.contracts.validation import validate_baseline, validate_benchmark_result

from .normalize import BenchmarkDataset

INTENSITY_TIE_ATOL = 1e-8  # tCO2e per GBP million
PROVIDER_NAME = "ws3-benchmark"
COMPARISON_BASES = ("forecast_vs_historical_peers",)


@dataclass(frozen=True)
class BenchmarkConfig:
    industry: str
    scope2_method: str
    scope_coverage: str = "scope1_scope2_scope3"
    min_peers: int = 10
    max_period_end_gap_months: int = 24
    comparison_basis: str = "forecast_vs_historical_peers"
    exclude_entity_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in ("industry", "scope2_method", "scope_coverage"):
            if not isinstance(getattr(self, name), str) or not getattr(self, name):
                raise ContractValidationError(f"benchmark_config.{name}", "must be a nonempty string")
        for name, minimum in (("min_peers", 1), ("max_period_end_gap_months", 0)):
            v = getattr(self, name)
            if isinstance(v, bool) or not isinstance(v, int) or v < minimum:
                raise ContractValidationError(f"benchmark_config.{name}", f"must be an int >= {minimum}")
        if self.comparison_basis not in COMPARISON_BASES:
            raise ContractValidationError("benchmark_config.comparison_basis", f"must be one of {list(COMPARISON_BASES)}")
        if not isinstance(self.exclude_entity_ids, tuple) or not all(isinstance(e, str) for e in self.exclude_entity_ids):
            raise ContractValidationError("benchmark_config.exclude_entity_ids", "must be a tuple of strings")

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "BenchmarkConfig":
        d = dict(data)
        unknown = set(d) - set(cls.__dataclass_fields__)
        if unknown:
            raise ContractValidationError("benchmark_config", f"unknown fields {sorted(unknown)}")
        d["exclude_entity_ids"] = tuple(d.get("exclude_entity_ids") or ())
        return cls(**d)

    def to_dict(self) -> dict[str, Any]:
        return {**self.__dict__, "exclude_entity_ids": list(self.exclude_entity_ids)}


def _ordinal(ts: pd.Timestamp) -> int:
    return 12 * ts.year + ts.month


def _period(baseline: BaselineBundle) -> tuple[pd.Timestamp, pd.Timestamp]:
    first = pd.Timestamp(baseline.monthly["timestamp"].min())
    last = pd.Timestamp(baseline.monthly["timestamp"].max())
    return first, last.replace(day=calendar.monthrange(last.year, last.month)[1])


def _envelope(baseline: BaselineBundle, config: BenchmarkConfig, meta: Mapping[str, Any], input_hash: str) -> dict[str, Any]:
    first, period_end = _period(baseline)
    return dict(
        schema_version=SCHEMA_VERSION,
        run_id=f"benchmark-{input_hash[:12]}",
        provenance=Provenance(provider=PROVIDER_NAME, is_mock=False, seed=None, input_hash=input_hash,
                              config_id=f"benchmark@{canonical_hash(config.to_dict())[:12]}", assumptions_id=None),
        source_id=meta.get("source_id"),
        source_url=meta.get("source_url"),
        retrieved_at=meta.get("retrieved_at"),
        snapshot_id=meta.get("snapshot_id"),
        is_synthetic=bool(meta.get("is_synthetic")),
        period_start=str(first.date()),
        period_end=str(period_end.date()),
        scope_coverage=config.scope_coverage,
        scope2_method=config.scope2_method,
        comparison_basis=config.comparison_basis,
    )


def unavailable_result(
    baseline: BaselineBundle, config: BenchmarkConfig, reason: str, *,
    meta: Mapping[str, Any], input_hash: str | None = None, peer_count: int = 0,
) -> BenchmarkResult:
    """Valid `unavailable` result: no intensity, median or rank is fabricated."""
    input_hash = input_hash or canonical_hash({"baseline_id": baseline.baseline_id, "config": config.to_dict(), "reason": reason})
    return validate_benchmark_result(BenchmarkResult(
        status="unavailable", company_intensity_tco2e_per_million_gbp=None, industry_median=None,
        percentile=None, better_than_pct=None, peer_count=peer_count, reason=reason,
        **_envelope(baseline, config, meta, input_hash)))


def benchmark_company(baseline: BaselineBundle, peers: BenchmarkDataset, *, config: BenchmarkConfig) -> BenchmarkResult:
    validate_baseline(baseline)
    meta = peers.metadata
    _, period_end = _period(baseline)
    revenue = float(baseline.totals["revenue_gbp"])
    co2 = float(baseline.totals["total_co2e_tco2e"])
    input_hash = canonical_hash({
        "baseline_id": baseline.baseline_id, "totals": dict(baseline.totals), "period_end": str(period_end.date()),
        "scope2_method": baseline.scope2_method, "peers": peers.to_dict(), "config": config.to_dict(),
    })

    def unavailable(reason: str, peer_count: int = 0) -> BenchmarkResult:
        return unavailable_result(baseline, config, reason, meta=meta, input_hash=input_hash, peer_count=peer_count)

    if baseline.horizon_months != 12:
        return unavailable(f"unsupported_horizon: benchmark compares 12-month baselines only, got {baseline.horizon_months}")
    if baseline.currency != "GBP":
        return unavailable(f"currency_mismatch: baseline currency {baseline.currency!r} is not GBP")
    if baseline.scope2_method != config.scope2_method:
        return unavailable(f"method_mismatch: baseline scope2_method {baseline.scope2_method!r} != {config.scope2_method!r}")
    if not revenue > 0:
        return unavailable("nonpositive_revenue: baseline revenue must be positive")

    df = peers.peers.copy()
    df["_entity"] = df["entity_id"] if "entity_id" in df else df["peer_id"]
    gap = (_ordinal(period_end) - pd.to_datetime(df["period_end"]).map(_ordinal)).abs()
    checks = (
        ("target_entity", df["_entity"].isin({baseline.company_id, *config.exclude_entity_ids})),
        ("industry_mismatch", df["industry"] != config.industry),
        ("scope_mismatch", df["scope_coverage"] != config.scope_coverage),
        ("method_mismatch", df["scope2_method"] != config.scope2_method),
        ("period_gap", gap > config.max_period_end_gap_months),
    )
    excluded: Counter[str] = Counter()
    keep = pd.Series(True, index=df.index)
    for reason, mask in checks:
        hit = keep & mask
        excluded[reason] += int(hit.sum())
        keep &= ~mask
    df = df[keep].sort_values(["_entity", "period_end"])
    newest = df.drop_duplicates("_entity", keep="last")
    excluded["superseded_entity_period"] += len(df) - len(newest)
    n = len(newest)
    if n < config.min_peers:
        detail = ", ".join(f"{k}={v}" for k, v in sorted(excluded.items()) if v) or "none"
        return unavailable(f"insufficient_peers: {n} compatible peers < {config.min_peers} required (excluded: {detail})", n)

    c = co2 / (revenue / 1e6)
    p = newest["intensity_tco2e_per_million_gbp"].to_numpy(dtype="float64")
    ties = int(np.sum(np.abs(p - c) <= INTENSITY_TIE_ATOL))
    lower = int(np.sum(p < c - INTENSITY_TIE_ATOL))
    percentile = 100.0 * (lower + 0.5 * ties) / n
    return validate_benchmark_result(BenchmarkResult(
        status="ok",
        company_intensity_tco2e_per_million_gbp=c,
        industry_median=float(np.median(p)),
        percentile=percentile,
        better_than_pct=100.0 - percentile,
        peer_count=n,
        reason=None,
        **_envelope(baseline, config, meta, input_hash),
    ))
