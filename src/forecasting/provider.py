"""WS1 forecast provider (bound by src/integration/services.py).

`create_forecast_provider()` binds the configured company CSV (via the explicit
import adapter) to WS1's pipeline. `info.version` is the WS1 model identity, so
a change to the CSV, import mapping, WS1 code, settings or library versions
invalidates every cached analysis. Training is lazy (first baseline request)
and reused from `models/ws1/<model_id>/` afterwards.
"""

from __future__ import annotations

import json
import threading
from typing import Any

import pandas as pd

from src.contracts.errors import ContractValidationError, UnsupportedHorizon, UnsupportedMockInput
from src.contracts.types import BacktestReport, BaselineBundle, ProviderInfo
from src.integration.config import REPO_ROOT, IntegrationConfig

from .baseline import PROVIDER_NAME, build_backtest, build_baseline
from .history import ImportedHistory, load_company_history
from .ws1_adapter import WS1Artifacts, identity_for, load_or_train, model_id_for

__version__ = "ws1-integration-1"


class WS1ForecastProvider:
    def __init__(self, config: IntegrationConfig) -> None:
        self.config = config
        self.imported: ImportedHistory = load_company_history(config.input_csv, config.import_config)
        provenance = json.loads((REPO_ROOT / config.provenance).read_text(encoding="utf-8"))
        if provenance.get("sha256") not in (None, self.imported.csv_sha256):
            raise ContractValidationError(
                "company_csv.sha256", f"{config.input_csv} does not match the checksum recorded in {config.provenance}; "
                "update the provenance record deliberately if the data changed")
        self.data_kind = provenance.get("data_kind", "synthetic")
        self.supported_horizons: tuple[int, ...] = (int(config.horizon_months),)
        self.settings = dict(config.ws1_modelling)
        self.model_id = model_id_for(identity_for(self.imported, self.settings, config.horizon_months))
        self.company_id = self.imported.import_config.company_id
        self.info = ProviderInfo(slot="forecast", name=PROVIDER_NAME, version=f"{__version__}+{self.model_id}",
                                 is_mock=False, kind="real")
        self._lock = threading.Lock()
        self._baseline: BaselineBundle | None = None
        self._backtest: BacktestReport | None = None

    def artifacts(self) -> WS1Artifacts:
        return load_or_train(self.imported, self.settings, self.config.horizon_months, self.config.model_dir)

    def _check(self, company_id: str) -> None:
        if company_id != self.company_id:
            raise UnsupportedMockInput(f"the configured CSV covers company {self.company_id!r} only")

    def get_baseline(self, *, company_id: str, horizon_months: int) -> BaselineBundle:
        self._check(company_id)
        if horizon_months not in self.supported_horizons:
            raise UnsupportedHorizon(horizon_months, self.supported_horizons)
        with self._lock:
            if self._baseline is None:
                self._baseline = build_baseline(
                    self.imported, self.artifacts(), horizon_months, self.config.driver_policy,
                    data_kind=self.data_kind, config_id=self.config.config_id, seed=int(self.settings["seed"]))
            return self._baseline

    def get_backtest(self, *, company_id: str) -> BacktestReport | None:
        self._check(company_id)
        with self._lock:
            if self._backtest is None:
                self._backtest = build_backtest(self.imported, self.artifacts(), config_id=self.config.config_id,
                                                seed=int(self.settings["seed"]),
                                                driver_policy_id=str(self.config.driver_policy["policy_id"]))
            return self._backtest

    def get_history(self, *, company_id: str) -> pd.DataFrame | None:
        self._check(company_id)
        return self.imported.history.copy()

    def describe(self) -> dict[str, Any]:
        return {"company_id": self.company_id, "csv": self.imported.csv_path, "csv_sha256": self.imported.csv_sha256,
                "model_id": self.model_id, "transforms": list(self.imported.transforms), "data_kind": self.data_kind}


def create_forecast_provider(path: str | None = None) -> WS1ForecastProvider:
    return WS1ForecastProvider(IntegrationConfig.load(path))
