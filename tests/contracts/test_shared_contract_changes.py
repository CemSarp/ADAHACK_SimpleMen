"""Shared-contract changes made while integrating WS2 with the WS4 C0 foundation.

Each test pins one reviewed change (see docs/handoffs/WS2_HANDOFF.md, "Shared contract
changes"), plus byte parity between the fixture kit and the documentation examples.
"""

from __future__ import annotations

import json
import pickle

import pytest

from src.contracts import serialization as ser
from src.contracts import validation as val
from src.contracts.errors import ContractValidationError, UnsupportedHorizon
from src.contracts.identity import compute_strategy_id
from src.contracts.types import ActionConfig, ConstraintEvaluation, OptimizerConfig, RecommendationResult
from tests.mocks import fixtures
from tests.support import REPO_ROOT

DOCS_EXAMPLES = REPO_ROOT / "carbonopt-ai-docs" / "examples"
DOC_FIXTURES = sorted(p.name for p in DOCS_EXAMPLES.glob("*.json")) if DOCS_EXAMPLES.exists() else []


@pytest.mark.parametrize("name", DOC_FIXTURES)
def test_fixture_kit_matches_the_documentation_examples(name):
    assert (fixtures.FIXTURE_DIR / name).read_bytes() == (DOCS_EXAMPLES / name).read_bytes()


def test_config_assumption_file_matches_the_fixture():
    assert (REPO_ROOT / "config" / "action_assumptions.json").read_bytes() == (fixtures.FIXTURE_DIR / "action_assumptions.json").read_bytes()


def _assumptions_payload(**changes):
    data = fixtures.load_json("action_assumptions.json")
    data.update(changes)
    return data


def test_assumption_files_reject_unknown_fields():
    with pytest.raises(ContractValidationError, match="unknown fields"):
        ser.assumptions_from_dict(_assumptions_payload(renewable_effectivness=0.9))
    data = _assumptions_payload()
    data["costs"]["cloud_efficiency"]["capex_gbp"] = 1.0
    with pytest.raises(ContractValidationError, match="unknown fields"):
        ser.assumptions_from_dict(data)


def test_asset_life_must_be_whole_months_not_truncated():
    data = _assumptions_payload()
    data["costs"]["travel_reduction"]["asset_life_months"] = 6.5
    with pytest.raises(ContractValidationError) as info:
        ser.assumptions_from_dict(data)
    assert info.value.field == "assumptions.costs.travel_reduction.asset_life_months"
    data["costs"]["travel_reduction"]["asset_life_months"] = 36.0
    assert ser.assumptions_from_dict(data).costs["travel_reduction"].asset_life_months == 36


def test_boolean_is_not_a_number_in_assumptions():
    with pytest.raises(ContractValidationError, match="must be a number"):
        ser.assumptions_from_dict(_assumptions_payload(gas_share=True))


def test_negative_zero_shares_the_zero_identity():
    zero = ActionConfig.noop()
    negative = ActionConfig(-0.0, -0.0, 0.0, 0.0, 0.0, 0.0)
    ids = {compute_strategy_id("baseline-demo-v1", c, "demo-actions-v1", "1.0.0") for c in (zero, negative)}
    assert ids == {"strategy-84d0730a93b9d729"}


def test_optimizer_seed_must_be_nonnegative():
    with pytest.raises(ContractValidationError, match="optimizer_config.seed"):
        val.validate_optimizer_config(OptimizerConfig(seed=-1))
    assert val.validate_optimizer_config(OptimizerConfig(seed=0)).seed == 0


def test_constraint_evaluation_satisfied_flags_are_optional():
    legacy = ConstraintEvaluation(g_budget=0.0, g_profit=0.0, g_target=0.0, feasible=True, raw_violations={})
    assert legacy.satisfied == {}


def test_recommendation_diagnostics_round_trip_and_default():
    rec = RecommendationResult(
        schema_version="1.0.0", run_id="r", provenance=fixtures.simulation("noop").provenance, strategy_id=None,
        policy="p", tolerance="balanced", score=None, risk_status="not_requested", reason=None,
        diagnostics={"pool_size": 3, "excluded_strategy_ids": {"strategy-x": "missing"}},
    )
    restored = ser.recommendation_from_dict(json.loads(ser.to_json(rec)))
    assert restored == rec
    payload = ser.recommendation_to_dict(rec)
    del payload["diagnostics"]  # producers that predate the additive field
    assert ser.recommendation_from_dict(payload).diagnostics == {}


def test_risk_standard_error_may_be_null_only_with_an_undefined_target():
    risk = fixtures.risk()
    undefined = dict(risk.summary, target_probability=None, joint_feasibility_probability=None,
                     target_probability_mc_standard_error=None)
    val.validate_risk_result(type(risk)(**{**risk.__dict__, "summary": undefined}))
    zero_filled_target = dict(risk.summary, target_probability_mc_standard_error=None)
    with pytest.raises(ContractValidationError, match="target_probability_mc_standard_error"):
        val.validate_risk_result(type(risk)(**{**risk.__dict__, "summary": zero_filled_target}))


def test_typed_errors_are_picklable():
    error = pickle.loads(pickle.dumps(ContractValidationError("config.x", "bad")))
    assert (error.field, error.reason) == ("config.x", "bad")
    horizon = pickle.loads(pickle.dumps(UnsupportedHorizon(36, (12,))))
    assert (horizon.horizon_months, horizon.supported) == (36, (12,))
