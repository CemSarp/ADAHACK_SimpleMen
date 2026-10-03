"""Developer CLI for the WS2 backend: simulate, optimize and profile from the repository root.

    python -m src.optimization.cli simulate --config tests/fixtures/v1/action_config.json
    python -m src.optimization.cli optimize --output optimization.json
    python -m src.optimization.cli profile

Defaults use the synthetic fixture baseline and the illustrative (uncalibrated) assumptions;
every summary prints the provenance so fixture-based results are never mistaken for real ones.
"""

from __future__ import annotations

import argparse
import json
import platform
import statistics
import sys
import time
from pathlib import Path
from typing import Sequence

import numpy as np
import pandas as pd
import pymoo

from src.actions import load_action_assumptions, simulate_strategy
from src.actions.definitions import DEFAULT_ASSUMPTIONS_PATH, REPO_ROOT
from src.contracts import ACTION_NAMES, ActionConfig, OptimizerConfig
from src.contracts import serialization as ser
from src.optimization.constraints import evaluate_constraints
from src.optimization.optimizer import optimize_strategies
from src.optimization.recommendation import recommend_strategy

FIXTURES = REPO_ROOT / "tests" / "fixtures" / "v1"
DEFAULT_BASELINE = FIXTURES / "baseline_12m.json"
DEFAULT_CONFIG = FIXTURES / "action_config.json"
DEFAULT_CONSTRAINTS = FIXTURES / "constraints.json"


def _relative(path: Path) -> str:
    try:
        return str(Path(path).resolve().relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def _write(path: str | None, text: str) -> None:
    if path:
        Path(path).write_text(text + "\n", encoding="utf-8")
        print(f"wrote {path}")


def _config_from_args(args: argparse.Namespace) -> ActionConfig:
    values = ser.load_json(args.config)
    for item in args.action or []:
        name, _, value = item.partition("=")
        if name not in ACTION_NAMES:
            raise SystemExit(f"unknown action {name!r}; expected one of {', '.join(ACTION_NAMES)}")
        values[name] = float(value)
    return ser.action_config_from_dict(values)


def _print_metrics(metrics) -> None:
    ratio = "n/a (zero baseline)" if metrics.co2_reduction_ratio is None else f"{metrics.co2_reduction_ratio:.4%}"
    print(f"  total CO2e        {metrics.total_co2e_tco2e:,.3f} t (baseline {metrics.baseline_total_co2e_tco2e:,.3f} t; reduction {ratio})")
    print(f"  operating profit  GBP {metrics.total_profit_gbp:,.2f} (baseline GBP {metrics.baseline_total_profit_gbp:,.2f})")
    print(f"  gross outlay      GBP {metrics.total_cost_gbp:,.2f} (capex GBP {metrics.total_capex_gbp:,.2f})")
    print(f"  net cash impact   GBP {metrics.net_cash_impact_gbp:,.2f}")


def cmd_simulate(args: argparse.Namespace) -> int:
    baseline = ser.baseline_from_dict(ser.load_json(args.baseline))
    assumptions = load_action_assumptions(args.assumptions)
    config = _config_from_args(args)
    result = simulate_strategy(baseline, config, assumptions=assumptions)
    print(f"strategy {result.strategy_id}  provider={result.provenance.provider} is_mock={result.provenance.is_mock}")
    print(f"  assumptions {assumptions.assumptions_id} v{assumptions.version} (calibrated={assumptions.is_calibrated})")
    print("  config " + ", ".join(f"{k}={v!r}" for k, v in config.to_dict().items()))
    _print_metrics(result.metrics)
    if args.constraints:
        evaluation = evaluate_constraints(result, ser.constraint_config_from_dict(ser.load_json(args.constraints)))
        flags = evaluation.satisfied
        print(f"  feasible={evaluation.feasible} (budget={flags.budget}, profit={flags.profit}, target={flags.target})")
    _write(args.output, ser.to_json(result, indent=2))
    return 0


def cmd_optimize(args: argparse.Namespace) -> int:
    baseline = ser.baseline_from_dict(ser.load_json(args.baseline))
    assumptions = load_action_assumptions(args.assumptions)
    constraints = ser.constraint_config_from_dict(ser.load_json(args.constraints))
    config = OptimizerConfig(
        seed=args.seed, population_size=args.population, generations=args.generations, max_evaluations=args.max_evaluations
    )
    result = optimize_strategies(baseline, constraints, assumptions=assumptions, config=config, simulator=simulate_strategy)
    diagnostics = result.diagnostics
    print(f"status={result.status} run_id={result.run_id} is_mock={result.provenance.is_mock}")
    print(
        f"  evaluations {diagnostics['evaluated_count']}/{config.max_evaluations} (unique {diagnostics['unique_count']}), "
        f"generations {diagnostics['generations_completed']}/{config.generations}, "
        f"termination={diagnostics['termination_reason']}, runtime {diagnostics['runtime_seconds']:.2f}s"
    )
    print(f"  feasible candidates {diagnostics['feasible_count']}, Pareto strategies {diagnostics['pareto_count']}")
    if "warning" in diagnostics:
        print(f"  warning: {diagnostics['warning']}")
    recommendation = recommend_strategy(result, tolerance=args.tolerance)
    print(f"recommendation: {recommendation.strategy_id} (policy={recommendation.policy}, risk_status={recommendation.risk_status})")
    if recommendation.strategy_id is not None:
        chosen = result.strategies[recommendation.strategy_id]
        print("  config " + ", ".join(f"{k}={v:.4f}" for k, v in chosen.config.to_dict().items()) + "  (display rounding only)")
        _print_metrics(chosen.metrics)
    if args.output:
        payload = ser.optimization_result_to_dict(result, strategies="frontier" if args.compact else "all")
        _write(args.output, json.dumps(payload, indent=2, ensure_ascii=False, allow_nan=False))
    return 0


def cmd_profile(args: argparse.Namespace) -> int:
    baseline = ser.baseline_from_dict(ser.load_json(args.baseline))
    assumptions = load_action_assumptions(args.assumptions)
    constraints = ser.constraint_config_from_dict(ser.load_json(args.constraints))
    config = ser.action_config_from_dict(ser.load_json(DEFAULT_CONFIG))
    simulate_strategy(baseline, config, assumptions=assumptions)  # warm-up
    samples = []
    for _ in range(args.repeats):
        started = time.perf_counter()
        simulate_strategy(baseline, config, assumptions=assumptions)
        samples.append((time.perf_counter() - started) * 1e3)
    reference = OptimizerConfig(seed=args.seed)
    started = time.perf_counter()
    result = optimize_strategies(baseline, constraints, assumptions=assumptions, config=reference, simulator=simulate_strategy)
    elapsed = time.perf_counter() - started
    print(f"machine: {platform.platform()} | {platform.processor() or platform.machine()} | Python {platform.python_version()}")
    print(f"libraries: numpy {np.__version__}, pandas {pd.__version__}, pymoo {pymoo.__version__}")
    print(f"inputs: {_relative(args.baseline)} ({baseline.horizon_months} months), {_relative(args.assumptions)}")
    print(
        f"simulate_strategy x{args.repeats}: median {statistics.median(samples):.3f} ms, "
        f"p95 {np.percentile(samples, 95):.3f} ms, max {max(samples):.3f} ms (team target < 20 ms)"
    )
    print(
        f"optimize_strategies {reference.population_size}x{reference.generations} "
        f"(max_evaluations={reference.max_evaluations}, seed={reference.seed}): {elapsed:.2f} s wall, "
        f"{result.diagnostics['evaluated_count']} evaluations, {result.diagnostics['pareto_count']} Pareto, "
        f"status={result.status} (team target < 20 s for 2,000 evaluations)"
    )
    print("measurements describe this machine only; they are not guarantees")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m src.optimization.cli", description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)

    def common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE, help="BaselineBundle JSON")
        p.add_argument("--assumptions", type=Path, default=DEFAULT_ASSUMPTIONS_PATH, help="ActionAssumptions JSON")

    simulate = sub.add_parser("simulate", help="run the deterministic simulator for one config")
    common(simulate)
    simulate.add_argument("--config", type=Path, default=DEFAULT_CONFIG, help="ActionConfig JSON (all six actions)")
    simulate.add_argument("--action", action="append", metavar="NAME=VALUE", help="override one action fraction in [0, 1]")
    simulate.add_argument("--constraints", type=Path, help="optional ConstraintConfig JSON for feasibility badges")
    simulate.add_argument("--output", help="write the SimulationResult JSON here")
    simulate.set_defaults(handler=cmd_simulate)

    optimize = sub.add_parser("optimize", help="run constrained NSGA-II and the P0 recommendation")
    common(optimize)
    defaults = OptimizerConfig()
    optimize.add_argument("--constraints", type=Path, default=DEFAULT_CONSTRAINTS, help="ConstraintConfig JSON")
    optimize.add_argument("--seed", type=int, default=defaults.seed)
    optimize.add_argument("--population", type=int, default=defaults.population_size)
    optimize.add_argument("--generations", type=int, default=defaults.generations)
    optimize.add_argument("--max-evaluations", type=int, default=defaults.max_evaluations)
    optimize.add_argument("--tolerance", choices=["conservative", "balanced", "aggressive"], default="balanced")
    optimize.add_argument("--output", help="write the OptimizationResult JSON here")
    optimize.add_argument("--compact", action="store_true", help="serialize only frontier and no-op strategies")
    optimize.set_defaults(handler=cmd_optimize)

    profile = sub.add_parser("profile", help="measure simulator and reference optimizer runtime")
    common(profile)
    profile.add_argument("--constraints", type=Path, default=DEFAULT_CONSTRAINTS)
    profile.add_argument("--repeats", type=int, default=500)
    profile.add_argument("--seed", type=int, default=OptimizerConfig().seed)
    profile.set_defaults(handler=cmd_profile)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.handler(args)


if __name__ == "__main__":
    sys.exit(main())
