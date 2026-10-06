"""Pure presentation helpers (no Streamlit). Formatting, period labels and the
documented display semantics of action sliders. No domain outcomes here."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

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

MODEL_NAMES = {"RandomForest": "Random forest", "SeasonalNaive": "Seasonal repeat", "XGBoost": "XGBoost",
               "LightGBM": "LightGBM", "Prophet": "Prophet"}


def model_name(model: str) -> str:
    return MODEL_NAMES.get(model, model)


# What an action acts on; shown when the company's data does not report it.
ACTION_NEEDS = {
    "renewable_energy": "electricity use or scope 2 emissions",
    "ev_adoption": "fleet distance and scope 1 emissions",
    "building_efficiency": "electricity or gas use",
    "travel_reduction": "business travel distance",
    "cloud_efficiency": "cloud compute hours",
    "supplier_transition": "scope 3 emissions",
}


def short_gbp(value: float | None) -> str:
    """Compact money for headline figures: £287.5m, £4.3k."""
    if value is None or not math.isfinite(value):
        return "n/a"
    sign, v = ("−" if value < 0 else ""), abs(value)
    for limit, unit in ((1e9, "bn"), (1e6, "m"), (1e3, "k")):
        if v >= limit:
            return f"{sign}£{v / limit:,.1f}{unit}"
    return f"{sign}£{v:,.0f}"


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


def _two_figures(value: float, *, up: bool) -> float:
    """Round to two significant figures, up or down, so a suggested goal stays on the right side."""
    if value == 0:
        return 0.0
    step = 10.0 ** (math.floor(math.log10(abs(value))) - 1)
    return (math.ceil if up else math.floor)(value / step) * step


def _goal_gbp(value: float) -> str:
    return short_gbp(value).replace(".0", "")


def hint_lines(hints: dict[str, float | None], constraints: Any) -> list[str]:
    """Plain suggestions when no plan meets all goals, from `relaxation_hints` (mixes already tried)."""
    lines = []
    budget, floor, cut = hints["budget_gbp"], hints["min_total_profit_gbp"], hints["min_co2_reduction_ratio"]
    if budget is not None and budget > constraints.budget_gbp:
        lines.append(f"Raise the budget to about {_goal_gbp(_two_figures(budget, up=True))}: the cheapest mix tried "
                     "that keeps profit above your floor and reaches the CO₂ target costs that much.")
    if cut is not None and cut < constraints.min_co2_reduction_ratio and math.floor(cut * 100) >= 1:
        lines.append(f"Lower the CO₂ target to {math.floor(cut * 100)}%: the deepest cut tried that fits the budget "
                     "and keeps profit above your floor.")
    if floor is not None and floor < constraints.min_total_profit_gbp:
        lines.append(f"Lower the profit floor to about {_goal_gbp(_two_figures(floor, up=False))}: the most profitable "
                     "mix tried that fits the budget and reaches the CO₂ target.")
    best = hints["max_reduction_ratio"]
    if best is not None and best + 1e-9 < constraints.min_co2_reduction_ratio:
        lines.append(f"The deepest cut any mix reached was {best:.0%}, so the actions available for this data cannot "
                     f"reach a {constraints.min_co2_reduction_ratio:.0%} cut. Lower the target, or add data (fleet, "
                     "travel, cloud or scope 3) that unlocks more actions.")
    lines.append("Or try more mixes under **Search depth** in the sidebar.")
    return lines


def uncertainty_method(risk: Any, *, trials: int) -> str:
    """How the risk provider's Monte Carlo trials are drawn, in plain words, from its own ranges."""
    bounds = risk.uncertainty.bounds.values()
    effect = (min(b["effectiveness"][0] for b in bounds), max(b["effectiveness"][1] for b in bounds))
    cost = (min(min(b["capex"][0], b["fixed_opex"][0]) for b in bounds),
            max(max(b["capex"][1], b["fixed_opex"][1]) for b in bounds))
    text = (f"**Monte Carlo simulation.** Each plan is re-run {trials:,} times. In every trial, each action's effect "
            f"is drawn at random between {effect[0]:.0%} and {effect[1]:.0%} of the assumed effect, and its investment "
            f"and running costs between {cost[0]:.0%} and {cost[1]:.0%} of the estimate (independent, evenly spread "
            "draws). The 12-month forecast, energy prices and grid factors stay fixed. A chance is the share of trials "
            "that meet that goal, and the bars span the middle 90% of trial outcomes.")
    if "ILLUSTRATIVE" in risk.uncertainty.calibration_note.upper():
        text += " The ranges are illustrative assumptions, not measured."
    return text


_FEATURE_NAMES = {
    "seasonal_ref_rel": "Same month last year", "seasonal_ref2_rel": "Same month two years ago",
    "level_growth_12m": "Growth over 12 months", "level_growth_3m": "Growth over 3 months",
    "level_margin": "Recent profit margin", "level_change_12m": "Change over 12 months",
    "level_change_3m": "Change over 3 months", "target_month": "Month number",
    "target_month_sin": "Month of the year", "target_month_cos": "Month of the year (second term)",
}


def feature_label(name: str) -> str:
    """Plain name for a forecast model input (see ml_core.modelling.build_supervised)."""
    from src.forecasting.mapping import ROLES

    if name in _FEATURE_NAMES:
        return _FEATURE_NAMES[name]
    if name.startswith("y_lag") and name.endswith("_rel"):
        k = int(name[5:-4])
        return "Last reported month" if k == 0 else f"{k} month{'s' if k > 1 else ''} before that"
    columns = {r.key: r.label for r in ROLES}
    for suffix, text in (("_diff_12m", ", change over 12 months"), ("_growth_12m", " growth over 12 months"),
                         ("_rel", " vs its 12-month average")):
        if name.endswith(suffix) and name[: -len(suffix)] in columns:
            return columns[name[: -len(suffix)]] + text
    return columns.get(name, name.replace("_", " "))


def shap_importance(explanation: Any, target: str) -> pd.Series:
    """Each forecast input's share of how much the forecast moves (mean |SHAP| over the horizon), largest first."""
    rows = explanation.contributions[explanation.contributions["target"] == target]
    size = rows.groupby("feature")["shap_value"].apply(lambda v: v.abs().mean())
    return (size / size.sum()).sort_values(ascending=False, kind="stable")
