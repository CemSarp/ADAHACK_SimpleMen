"""Choose the company data: the demo company, or the user's own monthly CSV matched to the
roles the analysis needs (src/forecasting/mapping.py). Datasets differ in columns and
units, so instead of a fixed layout the user confirms which column plays which role; only
date, revenue, profit-or-cost and emissions are required, and every optional column
unlocks the actions that act on it."""

from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path

import pandas as pd
import streamlit as st

from src.contracts.errors import ContractValidationError
from src.forecasting.history import REPO_ROOT, ImportConfig, import_history
from src.forecasting.mapping import (
    CURRENCIES,
    GBP_PER_UNIT,
    ROLES,
    detect_currency,
    detect_date_column,
    import_mapping,
    missing_required,
    suggest_mapping,
)

SOURCE_KEY = "co_widget_source"
DATASET_KEY = "co_dataset"  # confirmed upload: {"name", "bytes", "mapping"}
DEMO, OWN = "Demo company", "Your data"
SAMPLE = REPO_ROOT / "data" / "sample_upload.csv"
NONE = "— not in my data —"
HOW_IT_WORKS = """**How it works**

1. **Upload a CSV** with one row per month, at least 24 months. Column names and units can be anything. Not sure what
   it should look like? Download the example file below.
2. **Check our guesses.** We read your column names and guess which column is revenue, profit, emissions and so on.
   Change any guess that is wrong. If something is missing or cannot be read, a message says what is wrong and how to
   fix it.
3. **We tidy the data**, and every change is listed so you can check it before you start:
   - money in another currency is converted to pounds at the rate you set;
   - percentages such as 35% are read as shares of 100%;
   - a missing month or an empty cell is filled in from the months either side;
   - a missing emissions scope is worked out from the total and the other scopes;
   - missing electricity use is estimated from Scope 2 emissions.

**You need** revenue, operating profit (or operating cost) and emissions (a total or any scopes). Electricity, gas,
fleet, travel and cloud figures are optional; each one unlocks the actions that work on it."""


def source_selector() -> str:
    st.sidebar.segmented_control("Company data", (DEMO, OWN), key=SOURCE_KEY, default=DEMO, width="stretch")
    return st.session_state.get(SOURCE_KEY) or DEMO


def confirmed() -> dict | None:
    return st.session_state.get(DATASET_KEY)


def sidebar_summary(dataset: dict) -> None:
    st.sidebar.caption(f"Using **{dataset['name']}**")
    if st.sidebar.button("Change file or columns", icon=":material/edit:", width="stretch"):
        st.session_state.pop(DATASET_KEY, None)
        st.rerun()


@st.cache_data(show_spinner=False, max_entries=8)
def read_table(data: bytes) -> pd.DataFrame:
    return pd.read_csv(io.BytesIO(data), sep=None, engine="python")  # sniffs , ; or tab


def upload_step() -> None:
    st.html('<div class="co-eyebrow">Your data</div>')
    st.subheader("Bring your own monthly figures", anchor=False)
    st.markdown(HOW_IT_WORKS)
    file = st.file_uploader("Monthly company data (CSV)", type=["csv", "txt"], key="co_upload")
    st.download_button("Download an example file", SAMPLE.read_bytes(), file_name="example_company_data.csv",
                       mime="text/csv", icon=":material/download:", type="tertiary")
    if file is None:
        return
    data = file.getvalue()
    try:
        raw = read_table(data)
    except (ValueError, UnicodeDecodeError) as exc:
        st.error(f"This file could not be read as a table ({exc}). Save it as CSV and upload it again.")
        return
    _mapping_form(raw, data, file.name)


def _mapping_form(raw: pd.DataFrame, data: bytes, name: str) -> None:
    sha = hashlib.sha256(data).hexdigest()
    key = f"co_map_{sha[:10]}_"  # a new file starts from fresh suggestions
    columns = [str(c) for c in raw.columns]
    raw.columns = columns
    date_guess = detect_date_column(raw)
    suggestion = suggest_mapping(columns, date_guess)

    st.markdown(f"**Match your columns** · {len(raw):,} rows, {len(columns)} columns. "
                "We guessed from the names; correct anything that is wrong.")
    c1, c2 = st.columns(2)
    c3, c4 = st.columns(2)
    company = c1.text_input("Company name", value=Path(name).stem.replace("_", " ").title(), key=key + "company")
    date_column = c2.selectbox("Month column", columns, index=columns.index(date_guess) if date_guess in columns else 0,
                               key=key + "date")
    currency = c3.selectbox("Currency", CURRENCIES, index=CURRENCIES.index(detect_currency(columns)), key=key + "cur")
    rate = c4.number_input("£ per unit", min_value=0.0001, value=GBP_PER_UNIT[currency], format="%.4f",
                           key=f"{key}rate_{currency}", disabled=currency == "GBP",
                           help="Fixed exchange rate applied to every money column and month.")

    options = [NONE, *[c for c in columns if c != date_column]]
    mapping: dict[str, str | None] = {}
    groups = (("required", "Required (operating cost is only used when there is no profit column)"),
              ("emissions", "Emissions in tCO₂e: a total, scopes, or both"),
              ("activity", "Optional: each one unlocks more actions"))
    for group, title in groups:
        st.markdown(f"**{title}**")
        roles = [r for r in ROLES if r.group == group]
        cols = st.columns(3)
        for i, role in enumerate(roles):
            guess = suggestion.get(role.key)
            choice = cols[i % 3].selectbox(role.label, options, index=options.index(guess) if guess in options else 0,
                                           key=key + role.key, help=f"Unlocks {role.unlocks}." if role.unlocks else None)
            mapping[role.key] = None if choice == NONE else choice

    problems = missing_required(mapping)
    if problems:
        st.warning("Still needed: " + "; ".join(problems) + ". Pick the matching column above.")
        return
    config = import_mapping(mapping, company=company, date_column=date_column, currency=currency, gbp_per_unit=rate)
    try:
        imported = import_history(raw, ImportConfig.from_dict(config), source=name, sha256=sha)
    except ContractValidationError as exc:
        st.error(f"The data cannot be used yet: {exc.reason}. Check the column chosen for "
                 f"**{exc.field.split('.')[-1].replace('_', ' ')}**, or fix the file and upload it again.")
        return
    h = imported.history
    st.success(f"Ready: {len(h)} months from {h['timestamp'].iloc[0]:%b %Y} to {h['timestamp'].iloc[-1]:%b %Y}.")
    if imported.transforms:
        with st.expander("What the import does to your data"):
            st.markdown("\n".join(f"- {note}" for note in imported.transforms))
    if st.button("Analyse this data", type="primary", icon=":material/arrow_forward:"):
        st.session_state[DATASET_KEY] = {"name": name, "bytes": data, "mapping": config}
        st.rerun()


def mapping_json(dataset: dict) -> str:
    return json.dumps(dataset["mapping"], sort_keys=True)
