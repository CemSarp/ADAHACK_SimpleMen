"""WS3 benchmark provider factory (bound by src/integration/services.py).

Binds config/benchmark.json (source + comparison config) at factory time and
delegates to load_benchmark_data / benchmark_company. `info.is_mock` is False
(the calculation is implemented); synthetic peers stay `is_synthetic=True` on
every result. Only BenchmarkSourceError becomes `unavailable`; bugs surface.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Mapping

from src.contracts.errors import ContractValidationError
from src.contracts.types import BaselineBundle, BenchmarkResult, ProviderInfo

from . import adapters
from .adapters import BenchmarkSource, BenchmarkSourceError, load_benchmark_data
from .benchmark import PROVIDER_NAME, BenchmarkConfig, benchmark_company, unavailable_result

__version__ = "ws3-benchmark-1"
DEFAULT_CONFIG_PATH = Path("config") / "benchmark.json"


def _file_hash(relative: str) -> str:
    path = adapters.REPO_ROOT / relative
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else "missing"


class OfflineBenchmarkProvider:
    def __init__(self, source: BenchmarkSource, config: BenchmarkConfig, config_sha256: str) -> None:
        self._source, self._config = source, config
        self._data_hashes = self._current_hashes()
        csv_h, meta_h = self._data_hashes
        self.info = ProviderInfo(
            slot="benchmark",
            name=PROVIDER_NAME,
            # Config + snapshot content hashes: any data/config change invalidates cached analyses.
            version=f"{__version__}+{source.source_id}+c{config_sha256[:12]}+d{csv_h[:12]}+m{meta_h[:12]}",
            is_mock=False,
            kind="real",
        )

    def _current_hashes(self) -> tuple[str, str]:
        return _file_hash(self._source.snapshot_path), _file_hash(self._source.metadata_path)

    def benchmark(self, baseline: BaselineBundle) -> BenchmarkResult:
        try:
            if self._current_hashes() != self._data_hashes:
                # Results must match info.version, or caches would mix snapshots.
                raise BenchmarkSourceError("snapshot_hash_mismatch", "snapshot changed after the provider was created")
            dataset = load_benchmark_data(source=self._source)
        except BenchmarkSourceError as exc:
            meta = {"source_id": self._source.source_id, "is_synthetic": self._source.is_synthetic}
            return unavailable_result(baseline, self._config, f"source_unavailable: {exc}", meta=meta)
        return benchmark_company(baseline, dataset, config=self._config)


def create_benchmark_provider(path: str | Path | None = None) -> OfflineBenchmarkProvider:
    target = adapters.REPO_ROOT / (path or DEFAULT_CONFIG_PATH)
    try:
        raw = target.read_bytes()
        data = json.loads(raw)
    except OSError as exc:
        raise ContractValidationError("benchmark_config", f"cannot read {target.name}: {exc.strerror}") from exc
    except json.JSONDecodeError as exc:
        raise ContractValidationError("benchmark_config", f"{target.name} is not valid JSON: {exc.msg}") from exc
    for key in ("source", "config"):
        if not isinstance(data, Mapping) or not isinstance(data.get(key), Mapping):
            raise ContractValidationError(f"benchmark_config.{key}", "must be a JSON object")
    return OfflineBenchmarkProvider(
        BenchmarkSource.from_dict(data["source"]),
        BenchmarkConfig.from_dict(data["config"]),
        hashlib.sha256(raw).hexdigest(),
    )
