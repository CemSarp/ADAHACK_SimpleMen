"""Canonical peer dataset (RISK_AND_BENCHMARK_SPEC.md section 3).

Dataset-level problems (missing columns, unparseable values, duplicate IDs,
mixed source/synthetic labels, unsupported units/currency) raise
ContractValidationError. Row-level problems exclude the row with a closed reason
code recorded in ``metadata["exclusions"]``. A missing value is never read as 0.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Mapping

import numpy as np
import pandas as pd

from src.contracts.errors import ContractValidationError
from src.contracts.types import SCHEMA_VERSION

PEER_COLUMNS: tuple[str, ...] = (
    "peer_id",
    "industry",
    "period_start",
    "period_end",
    "revenue_gbp",
    "total_co2e_tco2e",
    "scope_coverage",
    "scope2_method",
    "intensity_tco2e_per_million_gbp",
    "source_id",
    "is_synthetic",
)
OPTIONAL_PEER_COLUMNS: tuple[str, ...] = ("entity_id",)
NUMERIC_COLUMNS = ("revenue_gbp", "total_co2e_tco2e", "intensity_tco2e_per_million_gbp")
SUPPORTED_EMISSION_UNITS: Mapping[str, str | None] = {"tco2e": None, "kgco2e": "kgco2e_to_tco2e"}
INTENSITY_RTOL = 1e-6
REQUIRED_METADATA = (
    "source_id", "retrieved_at", "snapshot_id", "is_synthetic", "original_currency",
    "original_emissions_unit", "reporting_frequency", "fx_method", "licence_note",
)


def _fail(field: str, reason: str) -> None:
    raise ContractValidationError(field, reason)


@dataclass(frozen=True, eq=False)
class BenchmarkDataset:
    schema_version: str
    metadata: Mapping[str, Any]
    peers: pd.DataFrame  # PEER_COLUMNS (+ optional entity_id); dates as ISO strings

    def to_dict(self) -> dict[str, Any]:
        records = self.peers.astype(object).where(self.peers.notna(), None).to_dict("records")
        return {"schema_version": self.schema_version, "metadata": dict(self.metadata), "peers": records}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "BenchmarkDataset":
        if str(data.get("schema_version", "")).split(".")[0] != SCHEMA_VERSION.split(".")[0]:
            _fail("benchmark_dataset.schema_version", "major version must be 1")
        return normalize_peers(pd.DataFrame(list(data.get("peers") or [])), data.get("metadata") or {})


def _validate_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    meta = dict(metadata)
    for key in REQUIRED_METADATA:
        if meta.get(key) in (None, ""):
            _fail(f"benchmark.metadata.{key}", "is required")
    if not isinstance(meta["is_synthetic"], bool):
        _fail("benchmark.metadata.is_synthetic", "must be a bool")
    if meta["original_currency"] != "GBP" or meta["fx_method"] != "not_required":
        _fail("benchmark.metadata.original_currency", "only GBP sources are supported (FX conversion is not implemented)")
    if meta["reporting_frequency"] != "annual":
        _fail("benchmark.metadata.reporting_frequency", "must be 'annual'")
    unit = meta["original_emissions_unit"]
    if unit not in SUPPORTED_EMISSION_UNITS:
        _fail("benchmark.metadata.original_emissions_unit", f"must be one of {list(SUPPORTED_EMISSION_UNITS)}")
    transforms = list(meta.get("transforms") or [])
    needed = SUPPORTED_EMISSION_UNITS[unit]
    if needed and needed not in transforms:
        _fail("benchmark.metadata.transforms", f"{unit} source must record the {needed!r} normalization")
    meta["transforms"] = transforms
    meta["exclusions"] = list(meta.get("exclusions") or [])
    return meta


def _parse_bool(series: pd.Series) -> pd.Series:
    mapped = series.map(lambda v: v if isinstance(v, bool) else {"true": True, "false": False}.get(str(v).strip().lower()))
    if mapped.isna().any():
        _fail("benchmark.peers.is_synthetic", "must be true/false")
    return mapped.astype(bool)


def _is_annual(start: pd.Timestamp, end: pd.Timestamp) -> bool:
    return start.day == 1 and end == start + pd.DateOffset(months=12) - pd.Timedelta(days=1)


def normalize_peers(raw: pd.DataFrame, metadata: Mapping[str, Any]) -> BenchmarkDataset:
    meta = _validate_metadata(metadata)
    missing = [c for c in PEER_COLUMNS if c not in raw.columns]
    if missing:
        _fail("benchmark.peers", f"missing columns {missing}")
    cols = list(PEER_COLUMNS) + [c for c in OPTIONAL_PEER_COLUMNS if c in raw.columns]
    df = raw[cols].copy()
    for c in ("peer_id", "industry", "scope_coverage", "scope2_method", "source_id", *OPTIONAL_PEER_COLUMNS):
        if c in df:
            df[c] = df[c].map(lambda v: "" if v is None or (isinstance(v, float) and math.isnan(v)) else str(v).strip())
    for c in NUMERIC_COLUMNS:
        blank = df[c].isna() | (df[c].astype(str).str.strip() == "")
        parsed = pd.to_numeric(df[c].where(~blank), errors="coerce")
        if (parsed.isna() & ~blank).any():
            _fail(f"benchmark.peers.{c}", "contains a non-numeric value")
        df[c] = parsed.astype("float64")  # blanks stay NaN, never 0
    starts = pd.to_datetime(df["period_start"].astype(str), format="%Y-%m-%d", errors="coerce")
    ends = pd.to_datetime(df["period_end"].astype(str), format="%Y-%m-%d", errors="coerce")
    if starts.isna().any() or ends.isna().any():
        _fail("benchmark.peers.period_start", "dates must be ISO YYYY-MM-DD")
    df["period_start"], df["period_end"] = starts.dt.strftime("%Y-%m-%d"), ends.dt.strftime("%Y-%m-%d")
    df["is_synthetic"] = _parse_bool(df["is_synthetic"])

    if (df["peer_id"] == "").any() or df["peer_id"].duplicated().any():
        _fail("benchmark.peers.peer_id", "must be nonempty and unique")
    if set(df["source_id"]) - {meta["source_id"]}:
        _fail("benchmark.peers.source_id", "every row must match metadata.source_id")
    if (df["is_synthetic"] != meta["is_synthetic"]).any():
        _fail("benchmark.peers.is_synthetic", "synthetic and reported peers must not mix")
    if not meta["is_synthetic"] and ("entity_id" not in df or (df["entity_id"] == "").any()):
        _fail("benchmark.peers.entity_id", "is required for non-synthetic sources")
    entity = df["entity_id"] if "entity_id" in df else df["peer_id"]
    if pd.DataFrame({"e": entity, "p": df["period_end"]}).duplicated().any():
        _fail("benchmark.peers.entity_id", "duplicate entity and period_end")

    retrieved = pd.Timestamp(str(meta["retrieved_at"])[:10])
    reasons: list[str | None] = []
    for i, row in df.iterrows():
        computed = row["total_co2e_tco2e"] / (row["revenue_gbp"] / 1e6) if row["revenue_gbp"] > 0 else np.nan
        if row["scope_coverage"] == "":
            reasons.append("missing_scope")
        elif not row["revenue_gbp"] > 0:
            reasons.append("nonpositive_revenue")
        elif not (np.isfinite(row["total_co2e_tco2e"]) and row["total_co2e_tco2e"] >= 0):
            reasons.append("invalid_emissions")
        elif not _is_annual(starts[i], ends[i]):
            reasons.append("non_annual_period")
        elif not row["is_synthetic"] and ends[i] >= retrieved:
            reasons.append("period_not_completed")
        elif not (np.isfinite(row["intensity_tco2e_per_million_gbp"])
                  and math.isclose(row["intensity_tco2e_per_million_gbp"], computed, rel_tol=INTENSITY_RTOL, abs_tol=1e-9)):
            reasons.append("intensity_mismatch")
        else:
            reasons.append(None)
    meta["exclusions"] += [{"peer_id": p, "reason": r} for p, r in zip(df["peer_id"], reasons) if r]
    keep = [r is None for r in reasons]
    return BenchmarkDataset(schema_version=SCHEMA_VERSION, metadata=meta, peers=df[keep].reset_index(drop=True))
