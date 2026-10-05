"""Offline benchmark source loading. Only normalized repo-relative CSV snapshots
are supported; HTTP sources are rejected explicitly and nothing touches the network.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

import pandas as pd

from src.contracts.errors import ContractValidationError, ProviderError

from .normalize import BenchmarkDataset, normalize_peers

REPO_ROOT = Path(__file__).resolve().parents[2]


class BenchmarkSourceError(ProviderError):
    """Expected source failure; the provider converts it to status='unavailable'."""

    def __init__(self, reason_code: str, message: str) -> None:
        self.reason_code = reason_code
        super().__init__(f"{reason_code}: {message}")


def _relative(field: str, value: Any) -> str:
    if not isinstance(value, str) or not value or PurePosixPath(value).is_absolute() or ".." in PurePosixPath(value).parts:
        raise ContractValidationError(field, "must be a repo-relative path")
    return value


@dataclass(frozen=True)
class BenchmarkSource:
    source_id: str
    kind: str  # only "csv" is enabled
    snapshot_path: str
    metadata_path: str
    is_synthetic: bool

    def __post_init__(self) -> None:
        if not isinstance(self.source_id, str) or not self.source_id:
            raise ContractValidationError("benchmark_source.source_id", "must be a nonempty string")
        if not isinstance(self.kind, str) or not self.kind:
            raise ContractValidationError("benchmark_source.kind", "must be a nonempty string")
        _relative("benchmark_source.snapshot_path", self.snapshot_path)
        _relative("benchmark_source.metadata_path", self.metadata_path)
        if not isinstance(self.is_synthetic, bool):
            raise ContractValidationError("benchmark_source.is_synthetic", "must be a bool")

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "BenchmarkSource":
        return cls(**{k: data.get(k) for k in ("source_id", "kind", "snapshot_path", "metadata_path", "is_synthetic")})

    def to_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


def load_benchmark_data(*, source: BenchmarkSource) -> BenchmarkDataset:
    """Read the normalized offline CSV snapshot (no network)."""
    if source.kind != "csv":
        # ponytail: live HTTP sources are out of scope; add an adapter only after a real source qualifies.
        raise BenchmarkSourceError("unsupported_source", f"source kind {source.kind!r} is not supported; only offline csv")
    snapshot, metadata = REPO_ROOT / source.snapshot_path, REPO_ROOT / source.metadata_path
    for path in (snapshot, metadata):
        if not path.is_file():
            raise BenchmarkSourceError("offline_snapshot_missing", f"{path.relative_to(REPO_ROOT).as_posix()} is missing")
    try:
        meta = json.loads(metadata.read_text())
        raw = pd.read_csv(snapshot, dtype=str, keep_default_na=False)
        dataset = normalize_peers(raw, meta)
    except (ValueError, pd.errors.ParserError) as exc:  # includes JSONDecodeError and ContractValidationError
        raise BenchmarkSourceError("snapshot_invalid", str(exc)) from exc
    m = dataset.metadata
    if m["source_id"] != source.source_id or m["is_synthetic"] != source.is_synthetic:
        raise BenchmarkSourceError("snapshot_invalid", "snapshot source_id/is_synthetic do not match the configured source")
    return dataset
