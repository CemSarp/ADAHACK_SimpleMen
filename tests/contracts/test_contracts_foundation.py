"""Contract 1.0.0 foundation used by WS2: fixture parsing, JSON round-trips and validation.

Covers the minimal C0 subset implemented for WS2 (flagged for WS4 review).
"""

from __future__ import annotations

import copy
import json
import math
import pickle
import subprocess
import sys

import pytest

from src.contracts import CANDIDATE_COLUMNS, ContractValidationError
from src.contracts import serialization as ser
from tests.support import FIXTURES, REPO_ROOT, frames_identical, load_fixture

DOCS_EXAMPLES = REPO_ROOT / "carbonopt-ai-docs" / "examples"
WS2_FIXTURES = sorted(path.name for path in FIXTURES.glob("*.json"))


@pytest.mark.parametrize("name", WS2_FIXTURES)
def test_fixture_copies_match_the_documentation_examples(name):
    source = DOCS_EXAMPLES / name
    if not source.exists():
        pytest.skip("documentation examples are not present in this checkout")
    assert (FIXTURES / name).read_bytes() == source.read_bytes()


PARSERS = {
    "baseline_12m.json": ser.baseline_from_dict,
    "action_config.json": ser.action_config_from_dict,
    "action_assumptions.json": ser.action_assumptions_from_dict,
    "constraints.json": ser.constraint_config_from_dict,
    "simulation_noop.json": ser.simulation_result_from_dict,
    "simulation_nonzero.json": ser.simulation_result_from_dict,
    "optimization_ok.json": ser.optimization_result_from_dict,
    "optimization_infeasible.json": ser.optimization_result_from_dict,
    "risk_summary.json": ser.risk_result_from_dict,
}


@pytest.mark.parametrize("name", sorted(PARSERS))
def test_fixtures_validate_and_round_trip(name):
    parse = PARSERS[name]
    first = parse(load_fixture(name))
    text = ser.to_json(first)
    assert "NaN" not in text and "Infinity" not in text
    second = parse(json.loads(text))
    assert ser.to_json(second) == text  # stable after one normalization pass


def test_baseline_round_trip_keeps_dates_totals_and_dtypes():
    baseline = ser.baseline_from_dict(load_fixture("baseline_12m.json"))
    payload = json.loads(ser.to_json(baseline))
    assert payload["history_end"] == "2026-12-01" and payload["monthly"][0]["timestamp"] == "2027-01-01"
    assert isinstance(payload["monthly"][0]["employees"], int)
    restored = ser.baseline_from_dict(payload)
    assert frames_identical(restored.monthly, baseline.monthly) and restored.totals == baseline.totals
    assert str(restored.monthly["timestamp"].dtype) == "datetime64[ns]"
    assert str(restored.monthly["fleet_size"].dtype) == "int64"


def _baseline_payload(mutate):
    data = copy.deepcopy(load_fixture("baseline_12m.json"))
    mutate(data)
    return data


def _set_rows(column, value, rows=range(12)):
    def mutate(data):
        for i in rows:
            data["monthly"][i][column] = value

    return mutate


@pytest.mark.parametrize(
    "mutate, fragment",
    [
        (lambda d: d["monthly"].__setitem__(1, dict(d["monthly"][0])), "timestamp"),  # duplicate month
        (lambda d: d["monthly"].pop(5), "monthly"),  # missing month -> wrong row count
        (lambda d: d["monthly"][4].update(timestamp="2027-05-15"), "timestamp"),  # not a month start
        (lambda d: d.update(history_end="2026-11-01"), "timestamp"),  # forecast must start after history_end
        (lambda d: d["monthly"][2].update(company_id="other-company"), "company_id"),
        (lambda d: d["monthly"][0].update(gas_kwh=None), "gas_kwh"),
        (lambda d: d["monthly"][0].update(scope1_tco2e=21), "total_co2e_tco2e"),  # scope mismatch
        (_set_rows("renewable_energy_share", 20), "renewable_energy_share"),  # 0-100 percentage
        (lambda d: d["monthly"][0].update(fleet_km=-1), "fleet_km"),
        (lambda d: d["monthly"][0].update(revenue_gbp=0), "revenue_gbp"),
        (lambda d: d["monthly"][0].update(employees=10.5), "employees"),
        (lambda d: d.update(horizon_months=24), "horizon_months"),
        (lambda d: d.update(schema_version="2.0.0"), "schema_version"),
        (lambda d: d.update(currency="EUR"), "currency"),
        (lambda d: d.update(data_kind="guessed"), "data_kind"),
        (lambda d: d["totals"].update(operating_profit_gbp=1_300_000), "totals.operating_profit_gbp"),
        (lambda d: d["monthly"][0].pop("cloud_compute_hours"), "cloud_compute_hours"),
        (lambda d: d["provenance"].update(is_mock="yes"), "provenance.is_mock"),
    ],
)
def test_invalid_baselines_are_rejected_with_a_field(mutate, fragment):
    with pytest.raises(ContractValidationError) as info:
        ser.baseline_from_dict(_baseline_payload(mutate))
    assert fragment in info.value.field


def test_minor_versions_and_additive_fields_are_tolerated_on_results():
    payload = load_fixture("simulation_noop.json")
    payload["schema_version"] = "1.1.0"
    payload["future_optional_field"] = {"note": "additive"}
    assert ser.simulation_result_from_dict(payload).strategy_id == "strategy-84d0730a93b9d729"


def test_nan_and_infinity_are_never_serialized():
    with pytest.raises(ContractValidationError):
        ser.to_jsonable({"value": math.nan})
    with pytest.raises(ContractValidationError):
        ser.to_jsonable([math.inf])
    assert ser.to_jsonable({"value": None}) == {"value": None}


def test_empty_candidate_frames_keep_columns_and_dtypes():
    frame = ser.empty_frame(CANDIDATE_COLUMNS)
    assert list(frame.columns) == [name for name, _ in CANDIDATE_COLUMNS]
    assert str(frame["strategy_id"].dtype) == "object" and str(frame["feasible"].dtype) == "bool"
    assert str(frame["pareto_rank"].dtype) == "int64" and str(frame["co2_reduction_ratio"].dtype) == "float64"
    assert ser.frame_to_records(frame, CANDIDATE_COLUMNS) == []


def test_contract_errors_are_picklable():
    error = pickle.loads(pickle.dumps(ContractValidationError("config.x", "bad")))
    assert (error.field, error.reason) == ("config.x", "bad")


def test_contracts_import_without_solver_or_ui_dependencies():
    code = "import sys, src.contracts, src.contracts.serialization; print(sorted(m for m in ('pymoo','streamlit','plotly') if m in sys.modules))"
    output = subprocess.run([sys.executable, "-c", code], cwd=REPO_ROOT, capture_output=True, text=True, check=True).stdout
    assert output.strip() == "[]"
