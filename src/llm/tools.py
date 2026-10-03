"""Allowlisted chat tools: schemas, strict argument validation, execution.

`execute_tool(name, arguments, *, context, services)` validates everything
before dispatch and returns a ToolResult; it never raises for model mistakes or
defined provider failures. All calculations are performed by the bound
services; this module only converts units, calls them and shapes the result.
"""

from __future__ import annotations

import math
from typing import Any, Mapping

from src.contracts import validation as val
from src.contracts.errors import CapabilityUnavailable, CarbonOptError, ContractValidationError
from src.contracts.types import (
    ACTION_NAMES,
    ActionConfig,
    ConstraintConfig,
    OptimizerConfig,
    RiskConfig,
    SimulationResult,
    ToolResult,
)
from src.integration.services import Services

from . import insights
from .context import AnalysisContext
from .types import ToolSpec

ALLOWED_TOOLS = ("get_baseline", "simulate_strategy", "optimize_strategies", "get_risk_summary",
                 "get_company_profile", "compare_actions", "get_public_reference")
MAX_TOOL_EXECUTIONS_PER_MESSAGE = 3
CHAT_MAX_EVALUATIONS = 512
CHAT_MAX_RISK_TRIALS = 1000
SHARE_ACTIONS = ("renewable_energy", "ev_adoption")
START_FROM = ("no_action", "selected_strategy")

_SHOWN_METRICS = (
    "total_co2e_tco2e", "co2_reduction_tco2e", "co2_reduction_ratio", "baseline_total_co2e_tco2e",
    "total_profit_gbp", "profit_change_gbp", "baseline_total_profit_gbp", "total_cost_gbp",
    "net_cash_impact_gbp",
)

TOOL_SPECS: tuple[ToolSpec, ...] = (
    ToolSpec(
        "get_baseline",
        "Return the business-as-usual forecast totals (emissions in tCO2e, GBP) for the current dashboard baseline.",
        {"type": "object", "properties": {}, "additionalProperties": False},
    ),
    ToolSpec(
        "simulate_strategy",
        "Preview the effect of an action mix on emissions, profit and cost. Action values are FRACTIONS (0-1) of the "
        "REMAINING opportunity, not final shares. For a final adoption share target such as 'EV share 80%' use "
        "final_shares with a 0-1 ratio (0.8). Never pass percentages above 1.",
        {"type": "object", "additionalProperties": False, "properties": {
            "actions": {"type": "object", "additionalProperties": False, "description":
                        "Fraction of remaining opportunity (0-1) per action.",
                        "properties": {n: {"type": "number", "minimum": 0, "maximum": 1} for n in ACTION_NAMES}},
            "final_shares": {"type": "object", "additionalProperties": False, "description":
                             "Target FINAL share (0-1 ratio, 80% = 0.8) for renewable_energy and/or ev_adoption.",
                             "properties": {n: {"type": "number", "minimum": 0, "maximum": 1} for n in SHARE_ACTIONS}},
            "start_from": {"type": "string", "enum": list(START_FROM),
                           "description": "Base action mix to modify. Default: selected_strategy if one is selected."},
        }},
    ),
    ToolSpec(
        "optimize_strategies",
        "Search for feasible emissions/profit trade-offs. Omitted fields keep the dashboard constraints. Units: GBP "
        "for money over the whole horizon; min_co2_reduction_ratio is a 0-1 ratio (20% = 0.2).",
        {"type": "object", "additionalProperties": False, "properties": {
            "budget_gbp": {"type": "number", "minimum": 0},
            "min_total_profit_gbp": {"type": "number"},
            "min_co2_reduction_ratio": {"type": "number", "minimum": 0, "maximum": 1},
        }},
    ),
    ToolSpec(
        "get_risk_summary",
        "Return the Monte Carlo risk summary (probabilities and empirical p05-p95 outcomes) for a strategy. "
        "Defaults to the selected strategy. Reports unavailable when risk is not available.",
        {"type": "object", "additionalProperties": False, "properties": {"strategy_id": {"type": "string"}}},
    ),
    ToolSpec(
        "get_company_profile",
        "Facts about the dashboard company from its own data: last 12 months vs the previous 12 (emissions by scope "
        "with shares, revenue, operating profit, margin, emissions per £m revenue, activity), current renewable and EV "
        "shares, what each scope contains, which activities are not reported, and the baseline forecast vs history. "
        "Use for questions about the company, its emissions, trends or where emissions come from.",
        {"type": "object", "properties": {}, "additionalProperties": False},
    ),
    ToolSpec(
        "compare_actions",
        "Explain the six actions and run each one alone at full adoption through the simulator: CO2 cut, operating "
        "profit change, gross outlay and outlay per tonne, ranked, plus which actions have no effect for this company. "
        "Use for 'what can we do', 'what does action X do', 'which action cuts the most / is cheapest per tonne'.",
        {"type": "object", "properties": {}, "additionalProperties": False},
    ),
    ToolSpec(
        "get_public_reference",
        "Wincanton plc FY2024 public disclosure: a real UK logistics company used as a SEPARATE reference, not the "
        "dashboard company. Reported energy, emissions by scope and revenue, derived shares, a plain explanation of "
        "Scope 1/2/3, and optionally an electricity-reduction scenario with the GOV.UK 2026 factor "
        "(electricity_reduction_ratio is a 0-1 ratio, 10% = 0.1). Use for Wincanton, real-world data, scopes, or the "
        "'Real data and sources' panel.",
        {"type": "object", "additionalProperties": False, "properties": {
            "electricity_reduction_ratio": {"type": "number", "minimum": 0, "maximum": 1}}},
    ),
)


class ToolArgumentError(ValueError):
    """Model-supplied arguments are malformed; the message is shown to the model."""


# --------------------------------------------------------------------------- #
# Argument validation
# --------------------------------------------------------------------------- #


def _number(name: str, value: Any, lo: float | None = None, hi: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ToolArgumentError(f"{name} must be a finite number")
    v = float(value)
    if lo is not None and v < lo:
        raise ToolArgumentError(f"{name} must be >= {lo:g}")
    if hi is not None and v > hi:
        hint = (f" It looks like a percentage; pass a 0-1 ratio instead (for example {v / 100:g} for {v:g}%)."
                if hi == 1.0 and 1.0 < v <= 100.0 else "")
        raise ToolArgumentError(f"{name} must be <= {hi:g}.{hint}")
    return v


def _mapping(name: str, value: Any, allowed: tuple[str, ...]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ToolArgumentError(f"{name} must be an object")
    unknown = sorted(set(value) - set(allowed))
    if unknown:
        raise ToolArgumentError(f"{name} has unknown fields {unknown}; allowed: {list(allowed)}")
    return dict(value)


def validate_arguments(name: str, arguments: Any) -> dict[str, Any]:
    if name not in ALLOWED_TOOLS:
        raise ToolArgumentError(f"unknown tool {name!r}; allowed tools: {list(ALLOWED_TOOLS)}")
    args = {} if arguments is None else arguments
    if not isinstance(args, Mapping):
        raise ToolArgumentError("arguments must be an object")
    args = _mapping("arguments", args, {
        "get_baseline": (),
        "simulate_strategy": ("actions", "final_shares", "start_from"),
        "optimize_strategies": ("budget_gbp", "min_total_profit_gbp", "min_co2_reduction_ratio"),
        "get_risk_summary": ("strategy_id",),
        "get_company_profile": (),
        "compare_actions": (),
        "get_public_reference": ("electricity_reduction_ratio",),
    }[name])
    out: dict[str, Any] = {}
    if name == "simulate_strategy":
        actions = _mapping("actions", args.get("actions", {}), ACTION_NAMES)
        shares = _mapping("final_shares", args.get("final_shares", {}), SHARE_ACTIONS)
        both = sorted(set(actions) & set(shares))
        if both:
            raise ToolArgumentError(f"{both} given both as a remaining-opportunity fraction (actions) and as a final "
                                    "share (final_shares); choose one")
        out["actions"] = {k: _number(f"actions.{k}", v, 0.0, 1.0) for k, v in actions.items()}
        out["final_shares"] = {k: _number(f"final_shares.{k}", v, 0.0, 1.0) for k, v in shares.items()}
        start = args.get("start_from", "selected_strategy")
        if start not in START_FROM:
            raise ToolArgumentError(f"start_from must be one of {list(START_FROM)}")
        out["start_from"] = start
    elif name == "optimize_strategies":
        if "budget_gbp" in args:
            out["budget_gbp"] = _number("budget_gbp", args["budget_gbp"], 0.0)
        if "min_total_profit_gbp" in args:
            out["min_total_profit_gbp"] = _number("min_total_profit_gbp", args["min_total_profit_gbp"])
        if "min_co2_reduction_ratio" in args:
            out["min_co2_reduction_ratio"] = _number("min_co2_reduction_ratio", args["min_co2_reduction_ratio"], 0.0, 1.0)
    elif name == "get_public_reference":
        if "electricity_reduction_ratio" in args:
            out["electricity_reduction_ratio"] = _number("electricity_reduction_ratio",
                                                         args["electricity_reduction_ratio"], 0.0, 1.0)
    elif name == "get_risk_summary":
        sid = args.get("strategy_id")
        if sid is not None:
            if not isinstance(sid, str) or not sid.strip():
                raise ToolArgumentError("strategy_id must be a nonempty string")
            out["strategy_id"] = sid
    return out


def adoption_fraction(baseline_share: float, target_share: float, effectiveness: float = 1.0) -> float:
    """Fraction of remaining opportunity for a final share target.

    Documented conversion x = (v_target - v) / (1 - v), divided by the
    effectiveness coefficient when it is below 1. v = 1 never divides by zero.
    """
    if target_share < baseline_share - 1e-12:
        raise ToolArgumentError(
            f"target share {target_share:.1%} is below the current baseline share {baseline_share:.1%}; actions can only "
            "increase adoption")
    if baseline_share >= 1.0 - 1e-12:
        return 0.0  # already fully adopted; any target <= 1 is met with no action
    if target_share <= baseline_share + 1e-12:
        return 0.0
    if effectiveness <= 0.0:
        raise ToolArgumentError("this action has zero effectiveness in the current assumptions")
    x = (target_share - baseline_share) / (1.0 - baseline_share) / effectiveness
    if x > 1.0 + 1e-12:
        raise ToolArgumentError(f"a final share of {target_share:.1%} is unreachable from {baseline_share:.1%}")
    return min(1.0, x)


# --------------------------------------------------------------------------- #
# Execution
# --------------------------------------------------------------------------- #


def _metrics(sim: SimulationResult) -> dict[str, float | None]:
    return {k: sim.metrics[k] for k in _SHOWN_METRICS}


def _tool_get_baseline(args: dict[str, Any], ctx: AnalysisContext, services: Services) -> dict[str, Any]:
    b = ctx.baseline
    ts = b.monthly["timestamp"]
    return {
        "kind": "baseline", "baseline_id": b.baseline_id, "company_id": b.company_id, "horizon_months": b.horizon_months,
        "period": f"{ts.iloc[0]:%b %Y} - {ts.iloc[-1]:%b %Y}", "model_id": b.model_id, "data_kind": b.data_kind,
        "totals": {k: float(v) for k, v in b.totals.items()},
        "is_mock": b.provenance.is_mock,
    }


def _tool_simulate(args: dict[str, Any], ctx: AnalysisContext, services: Services) -> dict[str, Any]:
    baseline = ctx.baseline
    notes: list[str] = []
    start = args["start_from"]
    no_selection = start == "selected_strategy" and ctx.selected is None
    if start == "selected_strategy" and ctx.selected is not None:
        values = ctx.selected.config.as_dict()
    else:
        values = ActionConfig.noop().as_dict()
        if no_selection:
            notes.append("No strategy is selected, so the preview starts from no action.")
    values.update(args["actions"])
    conversions = []
    month1 = baseline.monthly.iloc[0]
    for action, target in args["final_shares"].items():
        column = "renewable_energy_share" if action == "renewable_energy" else "ev_share"
        eff = services.assumptions.renewable_effectiveness if action == "renewable_energy" else services.assumptions.ev_effectiveness
        v = float(month1[column])
        values[action] = adoption_fraction(v, target, eff)
        conversions.append({"action": action, "baseline_share": v, "target_final_share": target,
                            "fraction_of_remaining": values[action]})
        if baseline.monthly[column].nunique() > 1:
            notes.append(f"Baseline {column} varies by month; the conversion uses the month-1 value.")
    config = val.validate_action_config(ActionConfig.from_mapping(values))
    result = val.validate_simulation_result(services.simulate(baseline, config), baseline)
    shares = {}
    for action in SHARE_ACTIONS:
        column = "renewable_energy_share" if action == "renewable_energy" else "ev_share"
        eff = services.assumptions.renewable_effectiveness if action == "renewable_energy" else services.assumptions.ev_effectiveness
        v = float(month1[column])
        shares[action] = {"baseline": v, "resulting": v + (1.0 - v) * getattr(config, action) * eff}
    feasibility = None
    try:
        val.validate_constraints_for_baseline(ctx.request.constraints, baseline)
        ev = services.optimizer.evaluate_constraints(result, ctx.request.constraints)
        labels = {"budget_gbp": "budget", "profit_gbp": "profit floor", "reduction_ratio": "CO2 target"}
        feasibility = {"feasible": ev.feasible,
                       "failed": [labels[k] for k, v in ev.raw_violations.items() if v > 0 and k in labels]}
    except CarbonOptError as exc:
        notes.append(f"Constraint check unavailable: {exc}")
    return {
        "kind": "simulation", "strategy_id": result.strategy_id, "config": config.as_dict(), "start_from": start,
        "conversions": conversions, "resulting_shares": shares, "metrics": _metrics(result), "feasibility": feasibility,
        "matches_selected_strategy": ctx.selected is not None and ctx.selected.strategy_id == result.strategy_id,
        "no_strategy_selected": no_selection,
        **({"what_this_shows": "No plan is selected, so there is no current approach to explain. These numbers are "
                               "only the requested changes applied to the business-as-usual baseline."}
           if no_selection else {}),
        "notes": notes, "is_mock": result.provenance.is_mock,
    }


def _tool_optimize(args: dict[str, Any], ctx: AnalysisContext, services: Services) -> dict[str, Any]:
    base = ctx.request.constraints
    constraints = ConstraintConfig(
        budget_gbp=args.get("budget_gbp", base.budget_gbp),
        min_total_profit_gbp=args.get("min_total_profit_gbp", base.min_total_profit_gbp),
        min_co2_reduction_ratio=args.get("min_co2_reduction_ratio", base.min_co2_reduction_ratio),
    )
    val.validate_constraints_for_baseline(constraints, ctx.baseline)
    cfg = ctx.request.optimizer_config
    capped = OptimizerConfig(seed=cfg.seed, population_size=cfg.population_size, generations=cfg.generations,
                             max_evaluations=min(cfg.max_evaluations, CHAT_MAX_EVALUATIONS))
    optimization = val.validate_optimization_result(services.optimizer.optimize(
        ctx.baseline, constraints, assumptions=services.assumptions, config=capped, simulator=services.simulator.simulate))
    recommendation = val.validate_recommendation(
        services.optimizer.recommend(optimization, tolerance=ctx.request.tolerance), optimization)
    recommended = None
    if recommendation.strategy_id is not None:
        sim = optimization.strategies[recommendation.strategy_id]
        recommended = {"strategy_id": sim.strategy_id, "config": sim.config.as_dict(), "metrics": _metrics(sim)}
    return {
        "kind": "optimization", "status": optimization.status,
        "constraints": {"budget_gbp": constraints.budget_gbp, "min_total_profit_gbp": constraints.min_total_profit_gbp,
                        "min_co2_reduction_ratio": constraints.min_co2_reduction_ratio},
        "constraints_overridden": sorted(args), "evaluated_count": optimization.diagnostics.get("evaluated_count"),
        "max_evaluations_applied": capped.max_evaluations, "pareto_count": len(optimization.pareto),
        "recommended": recommended, "is_mock": optimization.provenance.is_mock,
        "note": "Preview only: the dashboard analysis and constraints were not changed.",
    }


def _tool_risk(args: dict[str, Any], ctx: AnalysisContext, services: Services) -> dict[str, Any]:
    if services.risk is None:
        raise CapabilityUnavailable(services.unavailable.get("risk", "no risk provider is bound"))
    sid = args.get("strategy_id") or (ctx.selected.strategy_id if ctx.selected else None)
    if sid is None:
        raise ToolArgumentError("no strategy is selected; run Optimize and select a strategy first")
    analysis = ctx.analysis
    risk = analysis.risk_results.get(sid) if analysis is not None else None
    if risk is None:
        if analysis is None or sid not in analysis.optimization.strategies:
            raise ToolArgumentError(f"strategy {sid!r} is not part of the current analysis")
        trials = min(ctx.request.risk_config.n_simulations, CHAT_MAX_RISK_TRIALS)
        risk = val.validate_risk_result(services.risk.evaluate(
            ctx.baseline, analysis.optimization.strategies[sid].config, constraints=ctx.request.constraints,
            assumptions=services.assumptions, config=RiskConfig(seed=ctx.request.risk_config.seed, n_simulations=trials),
            simulator=services.simulator.simulate))
    return {"kind": "risk", "strategy_id": sid, "n_simulations": risk.n_simulations, "uncertainty_id": risk.uncertainty_id,
            "summary": dict(risk.summary), "is_mock": risk.provenance.is_mock}


def _tool_public_reference(args: dict[str, Any], ctx: AnalysisContext, services: Services) -> dict[str, Any]:
    try:
        return insights.public_reference(args.get("electricity_reduction_ratio"))
    except (OSError, ValueError) as exc:  # missing or invalid snapshot file
        raise CapabilityUnavailable(f"public reference data unavailable: {exc}") from exc


_HANDLERS = {
    "get_baseline": _tool_get_baseline,
    "simulate_strategy": _tool_simulate,
    "optimize_strategies": _tool_optimize,
    "get_risk_summary": _tool_risk,
    "get_company_profile": lambda args, ctx, services: insights.company_profile(ctx.history, ctx.baseline,
                                                                                services.assumptions),
    "compare_actions": lambda args, ctx, services: insights.compare_actions(ctx.baseline, services),
    "get_public_reference": _tool_public_reference,
}


def execute_tool(name: str, arguments: dict, *, context: AnalysisContext, services: Services) -> ToolResult:
    try:
        validated = validate_arguments(name, arguments)
    except ToolArgumentError as exc:
        return ToolResult("error", str(name), {}, None, f"invalid arguments: {exc}")
    try:
        data = _HANDLERS[name](validated, context, services)
    except ToolArgumentError as exc:
        return ToolResult("error", name, validated, None, str(exc))
    except CapabilityUnavailable as exc:
        return ToolResult("unavailable", name, validated, None, f"capability unavailable: {exc}")
    except ContractValidationError as exc:
        return ToolResult("error", name, validated, None, f"validation failed: {exc}")
    except CarbonOptError as exc:
        return ToolResult("error", name, validated, None, f"{type(exc).__name__}: {exc}")
    return ToolResult("ok", name, validated, data, None)


def tool_result_payload(result: ToolResult) -> dict[str, Any]:
    """JSON payload sent back to the model (and stored on result cards)."""
    return {"status": result.status, "tool_name": result.tool_name, "data": result.data, "error": result.error}
