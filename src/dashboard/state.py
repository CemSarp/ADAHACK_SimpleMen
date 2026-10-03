"""Dashboard session state and controllers.

Operates on any MutableMapping (st.session_state in the app, a dict in tests);
it never imports Streamlit. Results are stored together with the cache key they
were computed for. When the current inputs produce a different key, the stale
result is dropped rather than displayed as current.

Invalidation matrix:
  provider/mode/assumptions change -> everything
  company or horizon change        -> baseline, analysis, selection, what-if
  constraints/optimizer/risk/flags -> analysis and selection (what-if kept;
                                      its constraint badge is re-evaluated)
  tolerance change                 -> recommendation only (risk pool reused)
  slider change                    -> what-if simulation only
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, MutableMapping

import pandas as pd

from src.contracts import validation as val
from src.contracts.errors import (
    CarbonOptError,
    ContractValidationError,
    ProviderConfigurationError,
    ProviderError,
    UnsupportedHorizon,
)
from src.contracts.types import (
    ACTION_NAMES,
    ActionConfig,
    AnalysisBundle,
    AnalysisRequest,
    BacktestReport,
    BaselineBundle,
    ConstraintEvaluation,
    SimulationResult,
)
from src.integration import cache_keys
from src.integration.pipeline import load_baseline, rerun_recommendation, run_analysis_for_baseline
from src.integration.services import Services

PREFIX = "cos_"  # state-owned keys only; widget keys use "co_widget_"
SLIDER_PREFIX = "co_slider_"

# Analysis status values shown by the UI.
INITIAL = "initial"
COMPUTING = "computing"
READY = "ready"
INFEASIBLE = "infeasible"
VALIDATION_ERROR = "validation_error"
PROVIDER_ERROR = "provider_error"


@dataclass(frozen=True)
class ErrorInfo:
    kind: str  # validation_error | provider_error
    error_type: str
    message: str


def classify_error(exc: CarbonOptError) -> ErrorInfo:
    if isinstance(exc, (ContractValidationError, UnsupportedHorizon)):
        kind = VALIDATION_ERROR
    elif isinstance(exc, (ProviderError, ProviderConfigurationError)):
        kind = PROVIDER_ERROR
    else:
        kind = PROVIDER_ERROR
    return ErrorInfo(kind=kind, error_type=type(exc).__name__, message=str(exc))


def slider_key(action: str) -> str:
    return f"{SLIDER_PREFIX}{action}"


class DashboardState:
    """Typed accessors over a session mapping."""

    def __init__(self, store: MutableMapping[str, Any]) -> None:
        self.store = store

    def _get(self, name: str, default: Any = None) -> Any:
        return self.store.get(PREFIX + name, default)

    def _set(self, name: str, value: Any) -> None:
        self.store[PREFIX + name] = value

    # ---- services --------------------------------------------------------- #

    def sync_services(self, services: Services) -> bool:
        """Reset everything when the bound providers/assumptions change."""
        key = cache_keys.services_key(services)
        if self._get("services_key") == key:
            return False
        for name in [k[len(PREFIX):] for k in list(self.store) if k.startswith(PREFIX) and not k.startswith(SLIDER_PREFIX)]:
            del self.store[PREFIX + name]
        self._set("services_key", key)
        self._set("whatif_config", ActionConfig.noop())
        self.set_slider_values(ActionConfig.noop())
        return True

    # ---- baseline ---------------------------------------------------------- #

    @property
    def baseline(self) -> BaselineBundle | None:
        return self._get("baseline")

    @property
    def backtest(self) -> BacktestReport | None:
        return self._get("backtest")

    @property
    def history(self) -> pd.DataFrame | None:
        return self._get("history")

    @property
    def baseline_error(self) -> ErrorInfo | None:
        return self._get("baseline_error")

    @property
    def baseline_warnings(self) -> list[str]:
        return list(self._get("baseline_warnings", []))

    def ensure_baseline(self, request: AnalysisRequest, services: Services) -> BaselineBundle | None:
        """Load (or reuse) the forecast baseline for company + horizon."""
        key = cache_keys.baseline_key(request.company_id, request.horizon_months, services)
        if self._get("baseline_key") == key:
            return self.baseline
        self._set("baseline_key", key)
        for name in ("baseline", "backtest", "history", "baseline_error", "baseline_warnings"):
            self.store.pop(PREFIX + name, None)
        self.clear_analysis()
        self.clear_whatif_result()
        try:
            baseline, backtest, warnings = load_baseline(request, services=services)
            history = services.forecast.get_history(company_id=request.company_id)
            if history is not None:
                val.validate_history_frame(history)
        except CarbonOptError as exc:
            self._set("baseline_error", classify_error(exc))
            return None
        self._set("baseline", baseline)
        self._set("backtest", backtest)
        self._set("history", history)
        self._set("baseline_warnings", warnings)
        return baseline

    # ---- analysis ---------------------------------------------------------- #

    @property
    def analysis(self) -> AnalysisBundle | None:
        return self._get("analysis")

    @property
    def status(self) -> str:
        return self._get("status", INITIAL)

    @property
    def error(self) -> ErrorInfo | None:
        return self._get("error")

    @property
    def invalidated(self) -> bool:
        """True when a previous result was discarded because inputs changed."""
        return bool(self._get("invalidated", False))

    def clear_analysis(self, *, invalidated: bool = False) -> None:
        for name in ("analysis", "analysis_key", "recommendation_key", "error", "selected_strategy_id"):
            self.store.pop(PREFIX + name, None)
        self._set("status", INITIAL)
        self._set("invalidated", invalidated)

    def sync_inputs(self, request: AnalysisRequest, services: Services) -> None:
        """Drop results computed for different inputs; rerun only the policy
        when tolerance alone changed."""
        if self.analysis is None and self.status not in (VALIDATION_ERROR, PROVIDER_ERROR):
            return
        stored = self._get("analysis_key")
        if stored != cache_keys.analysis_key(request, services):
            self.clear_analysis(invalidated=stored is not None or self.error is not None)
            return
        if self._get("recommendation_key") != cache_keys.recommendation_key(request, services) and self.analysis is not None:
            try:
                bundle = rerun_recommendation(self.analysis, request.tolerance, services=services)
            except CarbonOptError as exc:
                self._fail(exc)
                return
            self._store_analysis(bundle, request, services)

    def _fail(self, exc: CarbonOptError) -> None:
        info = classify_error(exc)
        self.store.pop(PREFIX + "analysis", None)
        self.store.pop(PREFIX + "selected_strategy_id", None)
        self._set("error", info)
        self._set("status", info.kind)

    def _store_analysis(self, bundle: AnalysisBundle, request: AnalysisRequest, services: Services) -> None:
        self._set("analysis", bundle)
        self._set("analysis_key", cache_keys.analysis_key(request, services))
        self._set("recommendation_key", cache_keys.recommendation_key(request, services))
        self._set("status", READY if bundle.optimization.status == "ok" else INFEASIBLE)
        self._set("invalidated", False)
        self.store.pop(PREFIX + "error", None)
        current = self.selected_strategy_id
        if current is None or current not in set(bundle.optimization.pareto["strategy_id"]):
            self._set("selected_strategy_id", bundle.recommendation.strategy_id)

    def run_optimize(self, request: AnalysisRequest, services: Services) -> None:
        """Explicit Optimize action. Uses the cached baseline (no retraining)."""
        baseline = self.ensure_baseline(request, services)
        if baseline is None:
            err = self.baseline_error
            self.store.pop(PREFIX + "analysis", None)
            self._set("error", err)
            self._set("status", err.kind if err else PROVIDER_ERROR)
            self._set("analysis_key", cache_keys.analysis_key(request, services))
            return
        self._set("status", COMPUTING)
        self._set("analysis_key", cache_keys.analysis_key(request, services))
        try:
            bundle = run_analysis_for_baseline(
                request, services=services, baseline=baseline, backtest=self.backtest, warnings=self.baseline_warnings
            )
        except CarbonOptError as exc:
            self._fail(exc)
            return
        self.store.pop(PREFIX + "selected_strategy_id", None)
        self._store_analysis(bundle, request, services)

    # ---- selection --------------------------------------------------------- #

    @property
    def selected_strategy_id(self) -> str | None:
        return self._get("selected_strategy_id")

    def select_strategy(self, strategy_id: str) -> SimulationResult:
        """Select a feasible Pareto strategy by ID; returns the exact stored result."""
        analysis = self.analysis
        if analysis is None:
            raise KeyError("no current analysis to select from")
        if strategy_id not in set(analysis.optimization.pareto["strategy_id"]):
            raise KeyError(f"{strategy_id!r} is not a feasible Pareto strategy of the current analysis")
        self._set("selected_strategy_id", strategy_id)
        return analysis.optimization.strategies[strategy_id]

    def selected_strategy(self) -> SimulationResult | None:
        analysis, sid = self.analysis, self.selected_strategy_id
        if analysis is None or sid is None:
            return None
        return analysis.optimization.strategies.get(sid)

    # ---- manual what-if ---------------------------------------------------- #

    @property
    def whatif_config(self) -> ActionConfig:
        return self._get("whatif_config") or ActionConfig.noop()

    @property
    def whatif_result(self) -> SimulationResult | None:
        return self._get("whatif_result")

    @property
    def whatif_error(self) -> ErrorInfo | None:
        return self._get("whatif_error")

    def set_slider_values(self, config: ActionConfig) -> None:
        for name in ACTION_NAMES:
            self.store[slider_key(name)] = float(getattr(config, name))

    def set_whatif_action(self, action: str, value: float) -> None:
        """Slider callback: change one action, keep the others' exact values."""
        if action not in ACTION_NAMES:
            raise KeyError(action)
        config = replace(self.whatif_config, **{action: float(value)})
        val.validate_action_config(config)
        self._set("whatif_config", config)

    def load_whatif(self, config: ActionConfig) -> None:
        """Load an exact config (e.g. the selected strategy) into the sliders."""
        val.validate_action_config(config)
        self._set("whatif_config", config)
        self.set_slider_values(config)

    def clear_whatif_result(self) -> None:
        for name in ("whatif_result", "whatif_key", "whatif_error"):
            self.store.pop(PREFIX + name, None)

    def ensure_whatif(self, services: Services) -> SimulationResult | None:
        """Call the simulator directly when baseline/config/provider changed."""
        baseline = self.baseline
        if baseline is None:
            return None
        config = self.whatif_config
        key = cache_keys.simulation_key(baseline, config, services)
        if self._get("whatif_key") == key:
            return self.whatif_result
        self.clear_whatif_result()
        self._set("whatif_key", key)
        try:
            result = val.validate_simulation_result(services.simulate(baseline, config), baseline)
        except CarbonOptError as exc:
            self._set("whatif_error", classify_error(exc))
            return None
        self._set("whatif_result", result)
        return result

    def whatif_constraint_check(self, services: Services, request: AnalysisRequest) -> ConstraintEvaluation | None:
        """Shared WS2 constraint evaluation for the current what-if result."""
        result = self.whatif_result
        if result is None or self.baseline is None:
            return None
        try:
            val.validate_constraints_for_baseline(request.constraints, self.baseline)
            return services.optimizer.evaluate_constraints(result, request.constraints)
        except CarbonOptError:
            return None
