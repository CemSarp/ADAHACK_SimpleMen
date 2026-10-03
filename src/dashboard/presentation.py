"""Pure presentation helpers (no Streamlit). Formatting, period labels and the
documented display semantics of action sliders. No domain outcomes here."""

from __future__ import annotations

import math
from dataclasses import dataclass

import pandas as pd

from src.contracts.types import ActionAssumptions, BaselineBundle

ACTION_LABELS = {
    "renewable_energy": "Renewable electricity",
    "ev_adoption": "EV fleet adoption",
    "building_efficiency": "Building efficiency",
    "travel_reduction": "Business travel reduction",
    "cloud_efficiency": "Cloud efficiency",
    "supplier_transition": "Supplier transition",
}
ACTION_HELP = {
    "renewable_energy": "Fraction of the remaining non-renewable electricity supply switched to renewable at month 1.",
    "ev_adoption": "Fraction of the remaining internal-combustion fleet converted to electric at month 1.",
    "building_efficiency": "Fraction of the building-efficiency opportunity implemented at month 1.",
    "travel_reduction": "Fraction of business travel removed at month 1.",
    "cloud_efficiency": "Fraction of the cloud-efficiency opportunity implemented at month 1.",
    "supplier_transition": "Fraction of the supplier-transition opportunity implemented at month 1.",
}


def gbp(value: float | None, *, signed: bool = False) -> str:
    if value is None or not math.isfinite(value):
        return "n/a"
    sign = "+" if signed and value > 0 else ("−" if value < 0 else "")
    return f"{sign}£{abs(value):,.0f}"


def tonnes(value: float | None, *, signed: bool = False, decimals: int = 1) -> str:
    if value is None or not math.isfinite(value):
        return "n/a"
    sign = "+" if signed and value > 0 else ("−" if value < 0 else "")
    return f"{sign}{abs(value):,.{decimals}f} tCO₂e"


def pct(ratio: float | None, *, signed: bool = False, decimals: int = 1) -> str:
    """Ratio (0-1) to percent text. The UI is the only place ratios become %."""
    if ratio is None or not math.isfinite(ratio):
        return "n/a"
    value = ratio * 100.0
    sign = "+" if signed and value > 0 else ("−" if value < 0 else "")
    return f"{sign}{abs(value):.{decimals}f}%"


def period_label(timestamps: pd.Series) -> str:
    first, last = pd.Timestamp(timestamps.iloc[0]), pd.Timestamp(timestamps.iloc[-1])
    return f"{first:%b %Y} – {last:%b %Y} ({len(timestamps)} months)"


def trailing_window(history: pd.DataFrame, months: int = 12) -> pd.DataFrame:
    return history.sort_values("timestamp").tail(months)


@dataclass(frozen=True)
class ShareRange:
    baseline_min: float
    baseline_max: float
    resulting_min: float
    resulting_max: float

    def describe(self) -> str:
        def rng(lo: float, hi: float) -> str:
            return pct(lo, decimals=0) if math.isclose(lo, hi, abs_tol=5e-4) else f"{pct(lo, decimals=0)}–{pct(hi, decimals=0)}"

        return f"{rng(self.baseline_min, self.baseline_max)} → {rng(self.resulting_min, self.resulting_max)}"


def resulting_share(baseline: BaselineBundle, action: str, x: float, assumptions: ActionAssumptions) -> ShareRange | None:
    """Final adoption share for renewable/EV sliders using the documented
    semantics share_new = share + (1 - share) * x * effectiveness
    (docs/DATA_SCHEMAS.md section 5, docs/ACTION_MODEL.md section 3)."""
    column, effectiveness = {
        "renewable_energy": ("renewable_energy_share", assumptions.renewable_effectiveness),
        "ev_adoption": ("ev_share", assumptions.ev_effectiveness),
    }.get(action, (None, None))
    if column is None:
        return None
    base = baseline.monthly[column].astype("float64")
    result = base + (1.0 - base) * x * effectiveness
    return ShareRange(float(base.min()), float(base.max()), float(result.min()), float(result.max()))
