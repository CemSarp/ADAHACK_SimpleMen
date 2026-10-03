"""Central integration configuration (config/integration.json).

Names the company CSV, its import mapping, the WS1 modelling settings, and the
company-specific WS2 assumptions, WS3 uncertainty and benchmark configs used when
the forecast slot is the real CSV-backed WS1 provider. `CARBONOPT_CONFIG`
selects another file (repo-relative). Reading it performs no training or I/O
beyond the JSON file itself.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from src.contracts.errors import ContractValidationError

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = "config/integration.json"


@dataclass(frozen=True)
class IntegrationConfig:
    config_id: str
    input_csv: str
    import_config: str
    provenance: str
    horizon_months: int
    model_dir: str
    ws1_modelling: Mapping[str, Any]
    driver_policy: Mapping[str, Any]
    assumptions: str
    uncertainty: str
    benchmark: str
    dashboard_defaults: Mapping[str, float]
    path: str

    @classmethod
    def load(cls, path: str | None = None) -> "IntegrationConfig":
        rel = path or os.environ.get("CARBONOPT_CONFIG") or DEFAULT_CONFIG_PATH
        target = REPO_ROOT / rel
        try:
            data = json.loads(target.read_text(encoding="utf-8"))
            return cls(
                config_id=data["config_id"],
                input_csv=data["company"]["input_csv"],
                import_config=data["company"]["import_config"],
                provenance=data["company"]["provenance"],
                horizon_months=int(data["forecast"]["horizon_months"]),
                model_dir=data["forecast"]["model_dir"],
                ws1_modelling=data["forecast"]["ws1_modelling"],
                driver_policy=data["forecast"]["driver_policy"],
                assumptions=data["assumptions"],
                uncertainty=data["uncertainty"],
                benchmark=data["benchmark"],
                dashboard_defaults=data["dashboard_defaults"],
                path=Path(rel).as_posix(),
            )
        except OSError as exc:
            raise ContractValidationError("integration_config", f"cannot read {rel}: {exc.strerror}") from exc
        except (ValueError, KeyError, TypeError) as exc:
            raise ContractValidationError("integration_config", f"{rel} is invalid: {exc!r}") from exc
