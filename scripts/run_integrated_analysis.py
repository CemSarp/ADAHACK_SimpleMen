"""Reproduce the integrated all-real analysis from the configured company CSV.

    python scripts/run_integrated_analysis.py                    # uses config/integration.json
    python scripts/run_integrated_analysis.py --trials 1000 --evaluations 2048

Runs: CSV -> WS1 baseline + backtest -> WS2 NSGA-II/Pareto -> WS3 risk over the
bounded frontier pool -> WS2 risk-aware recommendation -> SHAP -> benchmark ->
three-policy scenario comparison, for a feasible and an infeasible request.
Prints timings and results. Numbers describe SYNTHETIC data.
"""

from __future__ import annotations

import argparse
import sys
import time
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.contracts.types import AnalysisRequest, ConstraintConfig, OptimizerConfig, RiskConfig  # noqa: E402
from src.integration import create_services, run_analysis  # noqa: E402
from src.integration.pipeline import compare_scenarios  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--evaluations", type=int, default=2048)
    ap.add_argument("--trials", type=int, default=1000)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    t = time.perf_counter()
    services = create_services()
    print(f"services: {time.perf_counter() - t:.2f}s")
    for slot, info in services.providers.items():
        print(f"  {slot:10s} {info.kind:5s} mock={info.is_mock} {info.name} {info.version}")
    for slot, reason in services.unavailable.items():
        print(f"  {slot:10s} unavailable: {reason}")
    defaults = services.forecast.config.dashboard_defaults
    company = services.forecast.company_id
    base_request = AnalysisRequest(
        company_id=company, horizon_months=12,
        constraints=ConstraintConfig(defaults["budget_gbp"], defaults["min_total_profit_gbp"],
                                     defaults["min_co2_reduction_ratio"]),
        optimizer_config=OptimizerConfig(seed=args.seed, max_evaluations=args.evaluations),
        risk_enabled=True, risk_config=RiskConfig(seed=args.seed, n_simulations=args.trials),
        tolerance="balanced", benchmark_enabled=True, explanation_enabled=True,
    )
    t = time.perf_counter()
    baseline = services.forecast.get_baseline(company_id=company, horizon_months=12)
    backtest = services.forecast.get_backtest(company_id=company)
    print(f"baseline+backtest: {time.perf_counter() - t:.2f}s  {baseline.baseline_id} data_kind={baseline.data_kind}")
    print(f"  totals {dict(baseline.totals)}")
    for target, m in backtest.aggregate_metrics.items():
        print(f"  backtest {target}: MAE {m['mae']:.2f} (naive {m['naive_mae']:.2f})  RMSE {m['rmse']:.2f} (naive {m['naive_rmse']:.2f})")

    for label, request in (("feasible", base_request),
                           ("infeasible", replace(base_request, constraints=replace(base_request.constraints, budget_gbp=0.0)))):
        t = time.perf_counter()
        bundle = run_analysis(request, services=services)
        elapsed = time.perf_counter() - t
        opt, rec = bundle.optimization, bundle.recommendation
        print(f"\n[{label}] run_analysis {elapsed:.2f}s  status={opt.status} candidates={len(opt.candidates)} "
              f"pareto={len(opt.pareto)} risk_results={len(bundle.risk_results)} is_mock={bundle.provenance.is_mock}")
        print(f"  constraints {request.constraints}")
        print(f"  recommendation {rec.strategy_id} policy={rec.policy} tolerance={rec.tolerance} risk_status={rec.risk_status}")
        if rec.strategy_id:
            m = opt.strategies[rec.strategy_id].metrics
            print(f"  -> CO2 {m['total_co2e_tco2e']:.1f} t ({(m['co2_reduction_ratio'] or 0) * 100:.1f}%), profit "
                  f"£{m['total_profit_gbp']:,.0f}, gross outlay £{m['total_cost_gbp']:,.0f}")
            risk = bundle.risk_results.get(rec.strategy_id)
            if risk:
                s = risk.summary
                print(f"  risk: P(target) {s['target_probability']:.3f} P(joint) {s['joint_feasibility_probability']:.3f}"
                      f" CO2 p05-p95 {s['co2_p05_tco2e']:.1f}-{s['co2_p95_tco2e']:.1f}")
            t = time.perf_counter()
            scenarios = compare_scenarios(bundle, services=services)
            print(f"  scenario comparison {time.perf_counter() - t:.2f}s")
            for tol, r in scenarios.items():
                print(f"    {tol:12s} {r.strategy_id} risk_status={r.risk_status}")
        if bundle.explanation is not None:
            e = bundle.explanation
            print(f"  shap: model {e.model_id} rows={len(e.contributions)} targets={sorted(e.units)} output_space={e.output_space}")
        if bundle.benchmark is not None:
            print(f"  benchmark: status={bundle.benchmark.status} reason={bundle.benchmark.reason}")
        for w in bundle.warnings:
            print(f"  warning: {w}")


if __name__ == "__main__":
    main()
