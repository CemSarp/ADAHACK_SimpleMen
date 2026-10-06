"""Match an uploaded table's columns to the canonical fields the analysis needs.

Every dataset names things differently and reports a different subset, so the app asks
for *roles*, not a fixed layout: a few are required (date, revenue, profit or cost,
emissions), the rest are optional and each one unlocks the actions that act on it.
`suggest_mapping` guesses the roles from column names; the user confirms or corrects
them, and `import_mapping` turns the result into an import configuration
(src/forecasting/history.py).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class Role:
    key: str
    label: str
    group: str            # "required", "emissions" or "activity"
    pattern: str
    money: bool = False
    unlocks: str = ""     # what the role enables, shown next to optional fields
    exclude: str = r"price|per_|rate|factor|intensity|share|ratio|capex"


ROLES: tuple[Role, ...] = (
    Role("revenue_gbp", "Revenue", "required", r"revenue|sales|turnover", money=True),
    Role("operating_profit_gbp", "Operating profit", "required",
         r"ebitda|ebit|operating_profit|operating_income|profit", money=True),
    Role("operating_cost", "Operating cost", "required",
         r"operating_cost|opex|operating_expense|costs?$|expenses?$", money=True),
    Role("total_co2e_tco2e", "Total", "emissions",
         r"total.*(emission|co2|ghg|carbon)|(emission|co2|ghg|carbon).*total|^(co2e?|ghg|emissions|carbon)(_t\w*)?$"),
    Role("scope1_tco2e", "Scope 1", "emissions", r"scope_?1|direct_emission"),
    Role("scope2_tco2e", "Scope 2", "emissions", r"scope_?2"),
    Role("scope3_tco2e", "Scope 3", "emissions", r"scope_?3|value_chain"),
    Role("electricity_kwh", "Electricity (kWh)", "activity", r"electric(ity)?(_consumption|_use)?|power_kwh",
         unlocks="renewable electricity, building efficiency"),
    Role("renewable_energy_share", "Renewable share", "activity", r"renewable",
         unlocks="a more accurate renewable action", exclude=r"price|cost"),
    Role("gas_kwh", "Gas (kWh)", "activity", r"(natural_)?gas", unlocks="building efficiency (heating)"),
    Role("fleet_km", "Fleet distance (km)", "activity", r"vehicle_km|fleet_km|km_driven|mileage|distance",
         unlocks="EV fleet adoption"),
    Role("ev_share", "EV share", "activity", r"(^|_)ev(_|$)|electric_vehicle", unlocks="EV fleet adoption",
         exclude=r"price|cost|count"),
    Role("fleet_size", "Fleet size", "activity", r"fleet_size|vehicles|trucks|fleet_count",
         unlocks="fleet context"),
    Role("business_travel_km", "Business travel (km)", "activity", r"travel|flight", unlocks="travel reduction"),
    Role("cloud_compute_hours", "Cloud (hours)", "activity", r"cloud|compute", unlocks="cloud efficiency"),
    Role("employees", "Employees", "activity", r"employee|headcount|fte|staff", unlocks="company context"),
)
ROLE_BY_KEY = {role.key: role for role in ROLES}
CURRENCIES = ("GBP", "EUR", "USD")
GBP_PER_UNIT = {"GBP": 1.0, "EUR": 0.85, "USD": 0.79}  # illustrative defaults; the user can change them


def _normal(name: str) -> str:
    name = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", str(name))  # camelCase -> camel_Case
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def detect_date_column(frame: pd.DataFrame) -> str | None:
    by_name = [c for c in frame.columns if re.search(r"date|month|period|time", _normal(c))]
    for column in [*by_name, *frame.columns]:
        parsed = pd.to_datetime(frame[column].astype(str), errors="coerce", format="mixed")
        if parsed.notna().mean() > 0.9 and not pd.api.types.is_numeric_dtype(frame[column]):
            return column
    return by_name[0] if by_name else None


def detect_currency(columns: list[str]) -> str:
    names = " ".join(_normal(c) for c in columns)
    return next((cur for cur in ("EUR", "USD", "GBP") if re.search(rf"(^|_){cur.lower()}(_|\s|$)", names)), "GBP")


def suggest_mapping(columns: list[str], date_column: str | None = None) -> dict[str, str | None]:
    """Best guess per role; each column is used at most once."""
    free = [c for c in columns if c != date_column]
    mapping: dict[str, str | None] = {}
    for role in ROLES:
        match = next((c for c in free if re.search(role.pattern, _normal(c)) and not re.search(role.exclude, _normal(c))),
                     None)
        mapping[role.key] = match
        if match is not None:
            free.remove(match)
    if mapping["operating_profit_gbp"]:
        mapping["operating_cost"] = None  # a profit column wins; cost only derives profit when profit is absent
    return mapping


def missing_required(mapping: dict[str, str | None]) -> list[str]:
    problems = []
    if not mapping.get("revenue_gbp"):
        problems.append("revenue")
    if not (mapping.get("operating_profit_gbp") or mapping.get("operating_cost")):
        problems.append("operating profit or operating cost")
    if not any(mapping.get(k) for k in ("total_co2e_tco2e", "scope1_tco2e", "scope2_tco2e", "scope3_tco2e")):
        problems.append("total emissions or at least one scope")
    return problems


def import_mapping(mapping: dict[str, str | None], *, company: str, date_column: str, currency: str,
                   gbp_per_unit: float) -> dict:
    """An import configuration (the same shape as config/company_import.json)."""
    columns: dict[str, dict[str, str]] = {}
    for key, column in mapping.items():
        if not column or key == "operating_cost":
            continue
        columns[key] = {"from": column, **({"convert": "to_gbp"} if ROLE_BY_KEY[key].money else {})}
    if not mapping.get("operating_profit_gbp") and mapping.get("operating_cost"):
        columns["operating_profit_gbp"] = {"revenue_minus": mapping["operating_cost"], "convert": "to_gbp"}
    slug = re.sub(r"[^a-z0-9]+", "-", company.lower()).strip("-") or "my-company"
    return {"import_id": f"upload-{slug}", "version": "1.0.0", "company_id": slug, "date_column": date_column,
            "currency": {"source": currency, "target": "GBP", "gbp_per_unit": gbp_per_unit,
                         "fx_note": "(user-entered rate)" if currency != "GBP" else ""},
            "columns": columns, "scope2_method": "market_based"}
