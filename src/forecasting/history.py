"""Explicit import adapter: company CSV -> canonical history (DATA_SCHEMAS.md s2).

The configured CSV is read as-is and never regenerated or rewritten. Every field
mapping and conversion comes from `config/company_import.json`; columns the CSV
does not report are listed there with the reason they are stored as zero. Gaps,
duplicates, non-finite values or broken identities are rejected, not repaired.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd

from src.contracts import validation as val
from src.contracts.errors import ContractValidationError
from src.contracts.types import HISTORY_COLUMNS, HISTORY_INT_COLUMNS

REPO_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class ImportConfig:
    import_id: str
    version: str
    company_id: str
    industry: str
    date_column: str
    gbp_per_eur: float
    fx_note: str
    columns: Mapping[str, Mapping[str, str]]
    not_reported: Mapping[str, str]
    scope2_method: str
    raw: Mapping[str, Any] = field(repr=False, default_factory=dict)

    @classmethod
    def load(cls, path: str | Path) -> "ImportConfig":
        target = REPO_ROOT / path
        try:
            data = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ContractValidationError("company_import", f"cannot read {path}: {exc}") from exc
        cur = data.get("currency", {})
        if cur.get("source") != "EUR" or cur.get("target") != "GBP":
            raise ContractValidationError("company_import.currency", "only an explicit EUR -> GBP mapping is supported")
        rate = val.require_finite("company_import.currency.gbp_per_eur", cur.get("gbp_per_eur"))
        if rate <= 0:
            raise ContractValidationError("company_import.currency.gbp_per_eur", "must be > 0")
        mapped = set(data.get("columns", {})) | set(data.get("not_reported", {}))
        missing = [c for c in HISTORY_COLUMNS if c not in ("company_id", "timestamp") and c not in mapped]
        if missing:
            raise ContractValidationError("company_import.columns", f"no mapping or not-reported entry for {missing}")
        return cls(
            import_id=data["import_id"], version=data["version"], company_id=val.require_nonempty_str(
                "company_import.company_id", data.get("company_id")),
            industry=data.get("industry", ""), date_column=data.get("date_column", "date"), gbp_per_eur=rate,
            fx_note=cur.get("fx_note", ""), columns=data["columns"], not_reported=data.get("not_reported", {}),
            scope2_method=data.get("scope2_method", "market_based"), raw=data,
        )

    def content_hash(self) -> str:
        return hashlib.sha256(json.dumps(self.raw, sort_keys=True).encode()).hexdigest()


@dataclass(frozen=True)
class ImportedHistory:
    """Canonical history plus the raw frame WS1 models consume in its native units."""

    history: pd.DataFrame
    raw: pd.DataFrame
    csv_path: str
    csv_sha256: str
    import_config: ImportConfig
    transforms: tuple[str, ...]


def file_sha256(path: str | Path) -> str:
    return hashlib.sha256((REPO_ROOT / path).read_bytes()).hexdigest()


def _validate_raw(raw: pd.DataFrame, cfg: ImportConfig) -> pd.DataFrame:
    needed = {cfg.date_column} | {spec["from"] for spec in cfg.columns.values()} | {"operating_cost_eur"}
    missing = sorted(needed - set(raw.columns))
    if missing:
        raise ContractValidationError("company_csv", f"missing columns {missing}")
    dates = pd.to_datetime(raw[cfg.date_column], format="%Y-%m-%d", errors="coerce")
    if dates.isna().any():
        raise ContractValidationError("company_csv.date", "unparseable or missing dates")
    if not (dates.dt.day == 1).all():
        raise ContractValidationError("company_csv.date", "dates must be month starts (YYYY-MM-01)")
    if dates.duplicated().any():
        raise ContractValidationError("company_csv.date", "duplicate months")
    if not dates.is_monotonic_increasing:
        raise ContractValidationError("company_csv.date", "months must be in ascending order")
    periods = dates.dt.year * 12 + dates.dt.month
    if len(periods) > 1 and not (periods.diff().iloc[1:] == 1).all():
        raise ContractValidationError("company_csv.date", "months must be contiguous (gaps are not filled by the importer)")
    numeric = raw.drop(columns=[cfg.date_column])
    non_numeric = [c for c in numeric.columns if not pd.api.types.is_numeric_dtype(numeric[c])]
    if non_numeric:
        raise ContractValidationError("company_csv", f"non-numeric columns {non_numeric}")
    if not np.isfinite(numeric.to_numpy(dtype="float64")).all():
        raise ContractValidationError("company_csv", "missing or non-finite values")
    scopes = raw["scope1_tco2e"] + raw["scope2_tco2e"] + raw["scope3_tco2e"]
    if not np.allclose(scopes, raw["total_emissions_tco2e"], rtol=val.SCOPE_RTOL, atol=val.SCOPE_ATOL_TCO2E):
        raise ContractValidationError("company_csv.total_emissions_tco2e", "must equal scope1 + scope2 + scope3")
    if not np.allclose(raw["revenue_eur"] - raw["operating_cost_eur"], raw["ebitda_eur"], atol=0.01):
        raise ContractValidationError("company_csv.ebitda_eur", "must equal revenue_eur - operating_cost_eur")
    out = raw.copy()
    out[cfg.date_column] = dates.astype("datetime64[ns]")
    return out


def to_canonical(raw: pd.DataFrame, cfg: ImportConfig) -> tuple[pd.DataFrame, tuple[str, ...]]:
    frame = pd.DataFrame({"company_id": cfg.company_id, "timestamp": raw[cfg.date_column].astype("datetime64[ns]")})
    transforms = [f"currency EUR -> GBP at fixed {cfg.gbp_per_eur} GBP/EUR ({cfg.fx_note})"]
    for target, spec in cfg.columns.items():
        series = raw[spec["from"]].astype("float64")
        if spec.get("convert") == "eur_to_gbp":
            series = series * cfg.gbp_per_eur
        frame[target] = series
        if spec["from"] != target or spec.get("convert"):
            transforms.append(f"{target} <- {spec['from']}" + (" x gbp_per_eur" if spec.get("convert") else ""))
    for target, reason in cfg.not_reported.items():
        frame[target] = 0
        transforms.append(f"{target} = 0 (not reported: {reason})")
    for col in HISTORY_INT_COLUMNS:
        values = frame[col].to_numpy(dtype="float64")
        if not np.all(np.mod(values, 1) == 0):
            raise ContractValidationError(f"company_csv.{col}", "count column must hold whole numbers")
        frame[col] = values.astype("int64")
    for col in HISTORY_COLUMNS:
        if col not in ("company_id", "timestamp", *HISTORY_INT_COLUMNS):
            frame[col] = frame[col].astype("float64")
    frame = frame[list(HISTORY_COLUMNS)]
    return val.validate_history_frame(frame), tuple(transforms)


def load_company_history(csv_path: str | Path, import_config_path: str | Path) -> ImportedHistory:
    cfg = ImportConfig.load(import_config_path)
    path = REPO_ROOT / csv_path
    try:
        raw = pd.read_csv(path)
    except OSError as exc:
        raise ContractValidationError("company_csv", f"cannot read {Path(csv_path).as_posix()}: {exc}") from exc
    raw = _validate_raw(raw, cfg)
    history, transforms = to_canonical(raw, cfg)
    return ImportedHistory(history=history, raw=raw, csv_path=Path(csv_path).as_posix(), csv_sha256=file_sha256(csv_path),
                           import_config=cfg, transforms=transforms)
