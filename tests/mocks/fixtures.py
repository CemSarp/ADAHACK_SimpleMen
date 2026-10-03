"""Fixture loader for tests/fixtures/v1. Returns fresh, validated objects."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from src.contracts import serialization as ser
from src.contracts import validation as val
from src.contracts.types import (
    ActionAssumptions,
    ActionConfig,
    BacktestReport,
    BaselineBundle,
    BenchmarkResult,
    ConstraintConfig,
    ExplanationResult,
    OptimizationResult,
    RiskResult,
    SimulationResult,
)

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "v1"
FIXTURE_REVISION = "c0-fixtures-r1"


def load_json(name: str) -> Any:
    return json.loads((FIXTURE_DIR / name).read_text())


def baseline() -> BaselineBundle:
    return val.validate_baseline(ser.baseline_from_dict(load_json("baseline_12m.json")))


def assumptions() -> ActionAssumptions:
    return val.validate_assumptions(ser.assumptions_from_dict(load_json("action_assumptions.json")))


def action_config() -> ActionConfig:
    return ser.action_config_from_dict(load_json("action_config.json"))


def constraints() -> ConstraintConfig:
    return ser.constraints_from_dict(load_json("constraints.json"))


def simulation(name: str) -> SimulationResult:
    return val.validate_simulation_result(ser.simulation_from_dict(load_json(f"simulation_{name}.json")))


def optimization(name: str) -> OptimizationResult:
    return val.validate_optimization_result(ser.optimization_from_dict(load_json(f"optimization_{name}.json")))


def risk() -> RiskResult:
    return val.validate_risk_result(ser.risk_from_dict(load_json("risk_summary.json")))


def benchmark() -> BenchmarkResult:
    return val.validate_benchmark_result(ser.benchmark_from_dict(load_json("benchmark_result.json")))


def backtest() -> BacktestReport:
    return val.validate_backtest_report(ser.backtest_from_dict(load_json("backtest_report.json")))


def explanation() -> ExplanationResult:
    return val.validate_explanation(ser.explanation_from_dict(load_json("shap_explanation.json")))


def history() -> pd.DataFrame:
    raw = pd.read_csv(FIXTURE_DIR / "history_96m.csv", dtype={"company_id": str, "timestamp": str})
    return val.validate_history_frame(ser.history_from_records(raw.to_dict("records")))
