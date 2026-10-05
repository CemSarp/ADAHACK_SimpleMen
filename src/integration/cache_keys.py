"""Cache keys for baseline, analysis, recommendation and simulation results.

Keys hash every input that can change an output: request fields at full
precision, model/config/assumption IDs, horizon, constraints, optimizer seed and
budget, risk seed/trials, uncertainty ID and the identity/version of every bound
provider. A budget change therefore never reuses another budget's optimization.
Tolerance is excluded from the analysis key (the risk pool can be reused) and
included in the recommendation key.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any, Mapping

from src.contracts.identity import canonical_hash
from src.contracts.types import ActionAssumptions, ActionConfig, AnalysisRequest, BaselineBundle, ProviderInfo

from .services import Services


def provider_fingerprint(providers: Mapping[str, ProviderInfo]) -> dict[str, Any]:
    return {slot: asdict(info) for slot, info in sorted(providers.items())}


def services_key(services: Services) -> str:
    return canonical_hash({
        "providers": provider_fingerprint(services.providers),
        "assumptions": _assumptions_identity(services.assumptions),
        "capabilities": {
            "supported_horizons": list(services.capabilities.supported_horizons),
            "risk": services.capabilities.risk_available,
            "shap": list(services.capabilities.shap_available_targets),
            "benchmark": services.capabilities.benchmark_available,
        },
    })


def _assumptions_identity(assumptions: ActionAssumptions) -> dict[str, str]:
    return {"assumptions_id": assumptions.assumptions_id, "version": assumptions.version}


def baseline_key(company_id: str, horizon_months: int, services: Services) -> str:
    return canonical_hash({
        "company_id": company_id,
        "horizon_months": horizon_months,
        "forecast": asdict(services.providers["forecast"]),
    })


def analysis_key(request: AnalysisRequest, services: Services) -> str:
    risk_info = services.providers.get("risk")
    return canonical_hash({
        "baseline": baseline_key(request.company_id, request.horizon_months, services),
        "constraints": asdict(request.constraints),
        "optimizer_config": asdict(request.optimizer_config),
        "risk_enabled": request.risk_enabled,
        "risk_config": asdict(request.risk_config) if request.risk_enabled else None,
        "uncertainty_id": getattr(services.risk, "uncertainty_id", None) if request.risk_enabled else None,
        "benchmark_enabled": request.benchmark_enabled,
        "explanation_enabled": request.explanation_enabled,
        "assumptions": _assumptions_identity(services.assumptions),
        "providers": provider_fingerprint(services.providers),
        "risk_provider": None if risk_info is None else asdict(risk_info),
    })


def recommendation_key(request: AnalysisRequest, services: Services) -> str:
    return canonical_hash({"analysis": analysis_key(request, services), "tolerance": request.tolerance})


def simulation_key(baseline: BaselineBundle, config: ActionConfig, services: Services) -> str:
    return canonical_hash({
        "baseline_id": baseline.baseline_id,
        "baseline_input_hash": baseline.provenance.input_hash,
        "model_id": baseline.model_id,
        "config": config.as_dict(),
        "assumptions": _assumptions_identity(services.assumptions),
        "simulator": asdict(services.providers["simulator"]),
    })
