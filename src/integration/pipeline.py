"""run_analysis(request, services): Data -> Forecast -> Optimizer -> Pareto ->
recommendation, then optional risk / SHAP / benchmark.

The pipeline validates every public boundary object and propagates provenance.
It catches only defined failures of OPTIONAL capabilities (turned into
warnings); P0 provider failures and validation errors propagate to the caller.
It never computes emissions, accounting, feasibility, Pareto ranks or risk.
"""

from __future__ import annotations

from dataclasses import replace

import pandas as pd

from src.contracts import validation as val
from src.contracts.errors import ContractValidationError, ProviderError
from src.contracts.identity import config_from_row
from src.contracts.types import (
    SCHEMA_VERSION,
    AnalysisBundle,
    AnalysisRequest,
    BacktestReport,
    BaselineBundle,
    BenchmarkResult,
    ExplanationResult,
    OptimizationResult,
    Provenance,
    RecommendationResult,
    RiskResult,
)

from .cache_keys import analysis_key
from .services import Services

RISK_POOL_MAX = 20


def load_baseline(request: AnalysisRequest, *, services: Services) -> tuple[BaselineBundle, BacktestReport | None, list[str]]:
    """Forecast stage. Rejects unsupported horizons before any computation."""
    val.validate_analysis_request(request, services.capabilities.supported_horizons)
    baseline = val.validate_baseline(
        services.forecast.get_baseline(company_id=request.company_id, horizon_months=request.horizon_months)
    )
    if baseline.company_id != request.company_id or baseline.horizon_months != request.horizon_months:
        raise ContractValidationError("baseline", "forecast provider returned a baseline for a different request")
    warnings: list[str] = []
    backtest = services.forecast.get_backtest(company_id=request.company_id)
    if backtest is None:
        warnings.append("Backtest report is not available from the forecast provider.")
    else:
        val.validate_backtest_report(backtest)
    return baseline, backtest, warnings


def select_risk_pool(pareto: pd.DataFrame, max_size: int = RISK_POOL_MAX) -> list[str]:
    """Bounded risk selection pool (RISK_AND_BENCHMARK_SPEC.md section 2).

    Delegates to WS2's single rule (both emission endpoints plus evenly spaced points by
    emissions order, at most ``max_size``), so the strategies sent to Monte Carlo are
    exactly the ones the recommendation policy ranks. Pure and pymoo-free.
    """
    from src.optimization.recommendation import risk_pool_from_frontier

    return list(risk_pool_from_frontier(pareto, max_size=max_size))


def _evaluate_risk(
    request: AnalysisRequest, services: Services, baseline: BaselineBundle, optimization: OptimizationResult, warnings: list[str]
) -> dict[str, RiskResult]:
    if not request.risk_enabled:
        return {}
    if services.risk is None:
        warnings.append(f"Risk is unavailable: {services.unavailable.get('risk', 'no provider bound')}.")
        return {}
    if optimization.status != "ok":
        return {}
    results: dict[str, RiskResult] = {}
    failures: dict[str, list[str]] = {}
    pool = select_risk_pool(optimization.pareto)
    pareto_rows = optimization.pareto.set_index("strategy_id")
    for sid in pool:
        try:
            result = services.risk.evaluate(
                baseline,
                config_from_row(pareto_rows.loc[sid]),
                constraints=request.constraints,
                assumptions=services.assumptions,
                config=request.risk_config,
                simulator=services.simulator.simulate,
            )
            val.validate_risk_result(result)
            if result.strategy_id != sid:
                raise ContractValidationError("risk.strategy_id", f"expected {sid!r}, got {result.strategy_id!r}")
            results[sid] = result
        except ProviderError as exc:
            failures.setdefault(str(exc), []).append(sid)
    if failures:
        reasons = "; ".join(f"{reason} ({len(ids)} excluded)" for reason, ids in failures.items())
        warnings.append(f"Risk evaluated for {len(results)} of {len(pool)} pool strategies. {reasons}")
    return results


def recommend(
    request: AnalysisRequest, services: Services, optimization: OptimizationResult, risk_results: dict[str, RiskResult]
) -> RecommendationResult:
    # Risk requested but nothing evaluated -> empty mapping, which the policy
    # reports as risk_status="unavailable" (never as a conservative selection).
    rec = services.optimizer.recommend(
        optimization, risk_results=risk_results if request.risk_enabled else None, tolerance=request.tolerance
    )
    return val.validate_recommendation(rec, optimization)


def run_analysis_for_baseline(
    request: AnalysisRequest,
    *,
    services: Services,
    baseline: BaselineBundle,
    backtest: BacktestReport | None,
    warnings: list[str] | None = None,
) -> AnalysisBundle:
    """Optimization and optional stages for an already validated baseline.
    Lets the dashboard reuse a cached baseline without retraining."""
    warnings = list(warnings or [])
    val.validate_analysis_request(request, services.capabilities.supported_horizons)
    val.validate_constraints_for_baseline(request.constraints, baseline)

    optimization = val.validate_optimization_result(
        services.optimizer.optimize(
            baseline,
            request.constraints,
            assumptions=services.assumptions,
            config=request.optimizer_config,
            simulator=services.simulator.simulate,
        )
    )
    if optimization.baseline_id != baseline.baseline_id:
        raise ContractValidationError("optimization.baseline_id", "does not match the analysed baseline")
    if optimization.constraints != request.constraints:
        raise ContractValidationError("optimization.constraints", "do not match the requested constraints")

    risk_results = _evaluate_risk(request, services, baseline, optimization, warnings)
    recommendation = recommend(request, services, optimization, risk_results)

    explanation: ExplanationResult | None = None
    if request.explanation_enabled:
        if services.shap is None:
            warnings.append(f"SHAP is unavailable: {services.unavailable.get('shap', 'no provider bound')}.")
        else:
            try:
                explanation = val.validate_explanation(services.shap.explain(baseline))
            except ProviderError as exc:
                warnings.append(f"SHAP failed: {exc}")

    benchmark: BenchmarkResult | None = None
    if request.benchmark_enabled:
        if services.benchmark is None:
            warnings.append(f"Benchmark is unavailable: {services.unavailable.get('benchmark', 'no provider bound')}.")
        else:
            try:
                benchmark = val.validate_benchmark_result(services.benchmark.benchmark(baseline))
            except ProviderError as exc:
                warnings.append(f"Benchmark failed: {exc}")

    used = {"forecast", "simulator", "optimizer"}
    if risk_results:
        used.add("risk")
    if explanation is not None:
        used.add("shap")
    if benchmark is not None:
        used.add("benchmark")
    providers = {slot: info for slot, info in services.providers.items() if slot in used}
    key = analysis_key(request, services)
    return AnalysisBundle(
        schema_version=SCHEMA_VERSION,
        run_id=f"analysis-{key[:16]}",
        provenance=Provenance(
            provider=f"pipeline:{services.mode}",
            is_mock=any(info.is_mock for info in providers.values()),
            seed=request.optimizer_config.seed,
            input_hash=key,
            config_id=baseline.provenance.config_id,
            assumptions_id=services.assumptions.assumptions_id,
        ),
        baseline=baseline,
        backtest=backtest,
        optimization=optimization,
        recommendation=recommendation,
        risk_results=risk_results,
        explanation=explanation,
        benchmark=benchmark,
        warnings=tuple(warnings),
        request=request,
        providers=providers,
    )


def run_analysis(request: AnalysisRequest, *, services: Services) -> AnalysisBundle:
    baseline, backtest, warnings = load_baseline(request, services=services)
    return run_analysis_for_baseline(request, services=services, baseline=baseline, backtest=backtest, warnings=warnings)


SCENARIO_TOLERANCES = ("conservative", "balanced", "aggressive")


def compare_scenarios(bundle: AnalysisBundle, *, services: Services) -> dict[str, RecommendationResult]:
    """C6: the three WS2 tolerance policies over ONE analysis: same baseline,
    constraints, optimization result and evaluated risk pool. No re-optimization,
    no new risk trials; selection is WS2's `recommend_strategy` only."""
    if not services.capabilities.scenario_compare_available:
        raise ContractValidationError(
            "scenario_compare", services.unavailable.get("scenario_compare", "capability unavailable"))
    if bundle.request is None or not bundle.request.risk_enabled:
        raise ContractValidationError("scenario_compare", "requires an analysis run with risk enabled")
    return {
        tol: val.validate_recommendation(
            services.optimizer.recommend(bundle.optimization, risk_results=dict(bundle.risk_results), tolerance=tol),
            bundle.optimization)
        for tol in SCENARIO_TOLERANCES
    }


def rerun_recommendation(bundle: AnalysisBundle, tolerance: str, *, services: Services) -> AnalysisBundle:
    """Tolerance change: reuse the evaluated risk pool, rerun only the selection policy."""
    if bundle.request is None:
        raise ContractValidationError("analysis.request", "is required to rerun recommendation")
    request = replace(bundle.request, tolerance=tolerance)
    recommendation = recommend(request, services, bundle.optimization, dict(bundle.risk_results))
    return replace(bundle, recommendation=recommendation, request=request)
