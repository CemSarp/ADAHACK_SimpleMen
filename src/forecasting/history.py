"""Import adapter: any monthly company table -> canonical history (DATA_SCHEMAS.md s2).

An import mapping names, for each canonical column, the source column it comes from
(`config/company_import.json` for the demo; the dashboard's mapping form for uploads).
Columns the data does not report are stored as zero. A few quantities are derived
when they are missing, and every derivation is recorded in `transforms`:

* operating profit as revenue minus an operating-cost column,
* total emissions as the sum of the reported scopes; with a total, the one missing
  scope (scope 3 when all are missing) takes the remainder,
* electricity from scope 2 emissions at a UK grid factor,
* 0-100 percentage shares as 0-1 ratios, and missing months or cells by interpolation.

Duplicate months, unparseable dates and inconsistent scope totals are rejected.
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
from src.contracts.types import HISTORY_COLUMNS, HISTORY_INT_COLUMNS, SCOPE_COLUMNS

REPO_ROOT = Path(__file__).resolve().parents[2]
MIN_MONTHS = 24  # the driver projection repeats the last year scaled by year-on-year growth
SHARE_COLUMNS = ("renewable_energy_share", "ev_share")
# Location-based UK grid average (GOV.UK 2024, kgCO2e/kWh / 1000); only used to estimate missing electricity.
GRID_TCO2E_PER_KWH = 0.000207


@dataclass(frozen=True)
class ImportConfig:
    import_id: str
    version: str
    company_id: str
    industry: str
    date_column: str
    currency: str
    gbp_per_unit: float
    fx_note: str
    columns: Mapping[str, Mapping[str, str]]
    not_reported: Mapping[str, str]
    scope2_method: str
    raw: Mapping[str, Any] = field(repr=False, default_factory=dict)

    @classmethod
    def load(cls, path: str | Path) -> "ImportConfig":
        try:
            data = json.loads((REPO_ROOT / path).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ContractValidationError("company_import", f"cannot read {path}: {exc}") from exc
        return cls.from_dict(data)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ImportConfig":
        cur = data.get("currency", {"source": "GBP"})
        source = str(cur.get("source", "GBP")).upper()
        if cur.get("target", "GBP") != "GBP":
            raise ContractValidationError("company_import.currency", "the target currency must be GBP")
        rate = 1.0 if source == "GBP" else val.require_finite(
            "company_import.currency.gbp_per_unit", cur.get("gbp_per_unit", cur.get("gbp_per_eur")))
        if rate <= 0:
            raise ContractValidationError("company_import.currency.gbp_per_unit", "must be > 0")
        columns = dict(data.get("columns", {}))
        if "revenue_gbp" not in columns:
            raise ContractValidationError("company_import.columns", "revenue is required")
        if "operating_profit_gbp" not in columns:
            raise ContractValidationError("company_import.columns", "operating profit (or operating cost) is required")
        if not ({"total_co2e_tco2e", *SCOPE_COLUMNS} & set(columns)):
            raise ContractValidationError("company_import.columns", "total emissions or at least one scope is required")
        return cls(
            import_id=data.get("import_id", "upload"), version=data.get("version", "1.0.0"),
            company_id=val.require_nonempty_str("company_import.company_id", data.get("company_id")),
            industry=data.get("industry", ""), date_column=data.get("date_column", "date"), currency=source,
            gbp_per_unit=rate, fx_note=cur.get("fx_note", ""), columns=columns,
            not_reported=data.get("not_reported", {}), scope2_method=data.get("scope2_method", "market_based"),
            raw=dict(data),
        )

    def content_hash(self) -> str:
        return hashlib.sha256(json.dumps(self.raw, sort_keys=True).encode()).hexdigest()


@dataclass(frozen=True)
class ImportedHistory:
    """Canonical history plus the parsed source table (one row per month)."""

    history: pd.DataFrame
    raw: pd.DataFrame
    csv_path: str
    csv_sha256: str
    import_config: ImportConfig
    transforms: tuple[str, ...]


def file_sha256(path: str | Path) -> str:
    return hashlib.sha256((REPO_ROOT / path).read_bytes()).hexdigest()


def _monthly(raw: pd.DataFrame, cfg: ImportConfig, notes: list[str]) -> pd.DataFrame:
    """Parse dates to month starts, coerce mapped columns to numbers and fill gaps."""
    if cfg.date_column not in raw.columns:
        raise ContractValidationError("company_csv", f"date column {cfg.date_column!r} not found")
    sources = sorted({v for spec in cfg.columns.values() for v in spec.values() if v in raw.columns} - {cfg.date_column})
    referenced = {v for spec in cfg.columns.values() for k, v in spec.items() if k in ("from", "revenue_minus")}
    missing = sorted(referenced - set(raw.columns))
    if missing:
        raise ContractValidationError("company_csv", f"missing columns {missing}")
    dates = pd.to_datetime(raw[cfg.date_column], errors="coerce", format="mixed")
    if dates.isna().any():
        raise ContractValidationError("company_csv.date", f"{int(dates.isna().sum())} rows have no readable date")
    months = dates.dt.to_period("M").dt.to_timestamp()
    if months.duplicated().any():
        raise ContractValidationError("company_csv.date", "one row per month is expected; some months appear twice")
    frame = pd.DataFrame({c: pd.to_numeric(raw[c], errors="coerce") for c in sources}).set_index(months.rename("date"))
    unreadable = [c for c in sources if frame[c].isna().all()]
    if unreadable:
        raise ContractValidationError("company_csv", f"columns {unreadable} contain no numbers")
    frame = frame.sort_index()
    full = pd.date_range(frame.index[0], frame.index[-1], freq="MS")
    if len(full) > len(frame):
        notes.append(f"{len(full) - len(frame)} missing months filled by interpolation")
    frame = frame.reindex(full)
    gaps = int(frame.isna().sum().sum())
    if gaps:
        notes.append(f"{gaps} missing values filled by interpolation")
        frame = frame.interpolate(limit_direction="both")
    if len(frame) < MIN_MONTHS:
        raise ContractValidationError("company_csv", f"at least {MIN_MONTHS} months are needed; found {len(frame)}")
    return frame.rename_axis("date").reset_index()


def _scopes(frame: pd.DataFrame, cfg: ImportConfig, out: pd.DataFrame, notes: list[str]) -> None:
    mapped = [s for s in SCOPE_COLUMNS if s in cfg.columns]
    for s in mapped:
        out[s] = frame[cfg.columns[s]["from"]]
    if "total_co2e_tco2e" not in cfg.columns:
        for s in set(SCOPE_COLUMNS) - set(mapped):
            out[s] = 0.0
        out["total_co2e_tco2e"] = out[list(SCOPE_COLUMNS)].sum(axis=1)
        notes.append("total emissions = sum of the reported scopes")
        return
    out["total_co2e_tco2e"] = frame[cfg.columns["total_co2e_tco2e"]["from"]]
    unmapped = [s for s in SCOPE_COLUMNS if s not in mapped]
    if unmapped:
        remainder = out["total_co2e_tco2e"] - out[mapped].sum(axis=1) if mapped else out["total_co2e_tco2e"]
        if (remainder < -val.SCOPE_ATOL_TCO2E).any():
            raise ContractValidationError("company_csv.total_co2e_tco2e", "is smaller than the sum of the reported scopes")
        target = "scope3_tco2e" if "scope3_tco2e" in unmapped else unmapped[-1]
        for s in unmapped:
            out[s] = remainder.clip(lower=0.0) if s == target else 0.0
        notes.append(f"{target} = total emissions minus the reported scopes"
                     if mapped else "no scope breakdown: all emissions treated as unclassified scope 3")
    scope_sum = out[list(SCOPE_COLUMNS)].sum(axis=1)
    if not np.allclose(scope_sum, out["total_co2e_tco2e"], rtol=val.SCOPE_RTOL, atol=val.SCOPE_ATOL_TCO2E):
        raise ContractValidationError("company_csv.total_co2e_tco2e", "must equal scope1 + scope2 + scope3")


def to_canonical(frame: pd.DataFrame, cfg: ImportConfig) -> tuple[pd.DataFrame, tuple[str, ...]]:
    notes: list[str] = []
    if cfg.currency != "GBP":
        notes.append(f"currency {cfg.currency} -> GBP at fixed {cfg.gbp_per_unit} GBP/{cfg.currency} {cfg.fx_note}".strip())
    out = pd.DataFrame({"company_id": cfg.company_id, "timestamp": frame["date"].astype("datetime64[ns]")})
    for target, spec in cfg.columns.items():
        if target in (*SCOPE_COLUMNS, "total_co2e_tco2e"):
            continue
        if "revenue_minus" in spec:
            series = frame[cfg.columns["revenue_gbp"]["from"]] - frame[spec["revenue_minus"]]
            notes.append(f"{target} = revenue - {spec['revenue_minus']}")
        else:
            series = frame[spec["from"]].astype("float64")
            if spec["from"] != target:
                notes.append(f"{target} <- {spec['from']}")
        if spec.get("convert") in ("to_gbp", "eur_to_gbp"):
            series = series * cfg.gbp_per_unit
        if target in SHARE_COLUMNS and series.max() > 1.0:
            series = series / 100.0
            notes.append(f"{target} read as a percentage and divided by 100")
        out[target] = series
    _scopes(frame, cfg, out, notes)
    for target in HISTORY_COLUMNS[2:]:
        if target not in out.columns:
            out[target] = 0.0
            notes.append(f"{target} = 0 (not reported: {cfg.not_reported.get(target, 'not in the data')})")
    if "electricity_kwh" not in cfg.columns and (out["scope2_tco2e"] > 0).any():
        out["electricity_kwh"] = out["scope2_tco2e"] / (GRID_TCO2E_PER_KWH * (1.0 - out["renewable_energy_share"]).clip(lower=0.01))
        notes.append(f"electricity_kwh estimated from scope 2 at {GRID_TCO2E_PER_KWH * 1000:.3f} kgCO2e/kWh")
    if ((out["scope2_tco2e"] > 0) & (out["renewable_energy_share"] >= 1.0)).any():
        raise ContractValidationError("company_csv.renewable_energy_share",
                                      "is 100% in months with positive scope 2; the model treats full renewable "
                                      "supply as zero scope 2 (market-based)")
    for col in HISTORY_INT_COLUMNS:
        out[col] = out[col].round().astype("int64")
    for col in HISTORY_COLUMNS[2:]:
        if col not in HISTORY_INT_COLUMNS:
            out[col] = out[col].astype("float64")
    return val.validate_history_frame(out[list(HISTORY_COLUMNS)]), tuple(notes)


def import_history(raw: pd.DataFrame, cfg: ImportConfig, *, source: str, sha256: str) -> ImportedHistory:
    notes: list[str] = []
    frame = _monthly(raw, cfg, notes)
    history, transforms = to_canonical(frame, cfg)
    return ImportedHistory(history=history, raw=frame, csv_path=source, csv_sha256=sha256, import_config=cfg,
                           transforms=(*notes, *transforms))


def load_company_history(csv_path: str | Path, import_config_path: str | Path) -> ImportedHistory:
    cfg = ImportConfig.load(import_config_path)
    try:
        raw = pd.read_csv(REPO_ROOT / csv_path)
    except OSError as exc:
        raise ContractValidationError("company_csv", f"cannot read {Path(csv_path).as_posix()}: {exc}") from exc
    return import_history(raw, cfg, source=Path(csv_path).as_posix(), sha256=file_sha256(csv_path))
