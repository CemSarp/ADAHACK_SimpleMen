"""Application-bound analysis context.

The context is built by the application from dashboard state. Tools execute
against it; the model only ever sees `summary()`. Model output cannot select a
company, baseline, provider, endpoint or file.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from src.contracts.identity import canonical_hash
from src.contracts.types import AnalysisBundle, AnalysisRequest, BaselineBundle, SimulationResult
from src.integration import cache_keys
from src.integration.services import Services


@dataclass(frozen=True, eq=False)
class AnalysisContext:
    services: Services
    request: AnalysisRequest
    baseline: BaselineBundle
    analysis: AnalysisBundle | None
    selected: SimulationResult | None

    @property
    def version(self) -> str:
        """Changes whenever inputs, analysis, selection or providers change."""
        return canonical_hash({
            "baseline_id": self.baseline.baseline_id,
            "baseline_input_hash": self.baseline.provenance.input_hash,
            "constraints": asdict(self.request.constraints),
            "optimizer_seed": self.request.optimizer_config.seed,
            "analysis_run_id": None if self.analysis is None else self.analysis.run_id,
            "selected": None if self.selected is None else self.selected.strategy_id,
            "services": cache_keys.services_key(self.services),
        })[:16]

    def summary(self) -> dict[str, Any]:
        """Compact, model-facing summary. No monthly data, no artifacts."""
        s, b, r = self.services, self.baseline, self.request
        out: dict[str, Any] = {
            "context_version": self.version,
            "is_mock": s.is_mock,
            "mocked_providers": list(s.mocked_slots),
            "data_kind": b.data_kind,
            "company_id": b.company_id,
            "baseline": {
                "baseline_id": b.baseline_id,
                "horizon_months": b.horizon_months,
                "model_id": b.model_id,
                "period": f"{b.monthly['timestamp'].iloc[0]:%Y-%m} to {b.monthly['timestamp'].iloc[-1]:%Y-%m}",
                "totals": {k: float(v) for k, v in b.totals.items()},
                "units": {"emissions": "tCO2e over horizon", "money": "GBP over horizon"},
            },
            "constraints": {
                "budget_gbp": r.constraints.budget_gbp,
                "min_total_profit_gbp": r.constraints.min_total_profit_gbp,
                "min_co2_reduction_ratio": r.constraints.min_co2_reduction_ratio,
            },
            "assumptions_id": s.assumptions.assumptions_id,
            "capabilities": {
                "risk_available": s.capabilities.risk_available,
                "supported_horizons": list(s.capabilities.supported_horizons),
            },
            "analysis_status": "not_run" if self.analysis is None else self.analysis.optimization.status,
        }
        if s.risk is not None:
            out["uncertainty_id"] = getattr(s.risk, "uncertainty_id", None)
        if self.analysis is not None:
            out["recommended_strategy_id"] = self.analysis.recommendation.strategy_id
        if self.selected is not None:
            m = self.selected.metrics
            out["selected_strategy"] = {
                "strategy_id": self.selected.strategy_id,
                "config_fraction_of_remaining_opportunity": self.selected.config.as_dict(),
                "total_co2e_tco2e": m["total_co2e_tco2e"],
                "co2_reduction_ratio": m["co2_reduction_ratio"],
                "total_profit_gbp": m["total_profit_gbp"],
                "total_cost_gbp": m["total_cost_gbp"],
            }
        return out
