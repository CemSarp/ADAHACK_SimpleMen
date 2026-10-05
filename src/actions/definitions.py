"""WS2 action definitions, assumption loading, strategy identity and uncertainty hooks.

Every action value is the fraction of the *remaining eligible opportunity* implemented in
month 1 and held for the horizon (docs/ACTION_MODEL.md §1). The vector order is fixed by
:data:`src.contracts.ACTION_NAMES`. Types, validators and the canonical identity come from
the shared contract package; this module only adds WS2 semantics on top of them.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, Sequence

import numpy as np

from src.contracts import ACTION_NAMES, ActionAssumptions, ActionConfig, BaselineBundle
from src.contracts import serialization as ser
from src.contracts import validation as val
from src.contracts.errors import ContractValidationError
from src.contracts.identity import STRATEGY_ID_HEX_LENGTH, canonical_hash, strategy_id_from_identity
from src.contracts.types import HISTORY_COLUMNS

__version__ = "ws2-actions-1.1.0"

REPO_ROOT = Path(__file__).resolve().parents[2]
#: Versioned illustrative (uncalibrated) assumptions owned by WS2.
DEFAULT_ASSUMPTIONS_PATH = REPO_ROOT / "config" / "action_assumptions.json"


@dataclass(frozen=True)
class ActionDefinition:
    """Human-readable semantics of one decision variable (for UI labels and documentation)."""

    name: str
    label: str
    eligible_opportunity: str
    effect: str
    effect_coefficient: str


ACTION_DEFINITIONS: tuple[ActionDefinition, ...] = (
    ActionDefinition(
        "renewable_energy",
        "Renewable electricity",
        "Non-renewable share (1 - r) of the resulting electricity demand",
        "r_new = r + (1 - r) * x * renewable_effectiveness; scales existing and EV-added scope2",
        "renewable_effectiveness",
    ),
    ActionDefinition(
        "ev_adoption",
        "Fleet electrification",
        "Remaining ICE fleet km: fleet_km * (1 - ev_share)",
        "Removes x * ev_effectiveness of the ICE-fleet scope1 bucket; adds ev_kwh_per_km per converted km",
        "ev_effectiveness",
    ),
    ActionDefinition(
        "building_efficiency",
        "Building efficiency",
        "Baseline building electricity and gas (not added EV load)",
        "Cuts building electricity and gas by building_max_reduction * x",
        "building_max_reduction",
    ),
    ActionDefinition(
        "travel_reduction",
        "Business travel reduction",
        "Scope3 travel bucket and business_travel_km",
        "Cuts travel emissions and km by x * travel_effectiveness",
        "travel_effectiveness",
    ),
    ActionDefinition(
        "cloud_efficiency",
        "Cloud efficiency",
        "Scope3 cloud bucket and cloud_compute_hours",
        "Cuts cloud emissions and hours by cloud_max_reduction * x",
        "cloud_max_reduction",
    ),
    ActionDefinition(
        "supplier_transition",
        "Supplier transition",
        "Scope3 supplier bucket",
        "Cuts supplier emissions by supplier_max_reduction * x; saves supplier_monthly_savings_at_full_gbp * x",
        "supplier_max_reduction",
    ),
)


def load_action_assumptions(path: str | Path | None = None) -> ActionAssumptions:
    """Load and validate a versioned assumption file (default: config/action_assumptions.json)."""
    target = DEFAULT_ASSUMPTIONS_PATH if path is None else Path(path)
    with open(target, encoding="utf-8") as handle:
        return val.validate_assumptions(ser.assumptions_from_dict(json.load(handle)))


def canonical_config(config: ActionConfig, field: str = "config") -> ActionConfig:
    """Validated copy holding built-in floats, with ``-0.0`` normalised to ``0.0``.

    Out-of-range, non-finite and non-numeric values are rejected, never clamped. Equal
    configurations therefore always share one strategy identity.
    """
    val.validate_action_config(config, field)
    return ActionConfig(*(float(value) + 0.0 for value in config.as_vector()))


def config_to_vector(config: ActionConfig) -> np.ndarray:
    """Decision vector in canonical order (full precision)."""
    return np.array(config.as_vector(), dtype=np.float64)


def config_from_vector(values: Sequence[float] | np.ndarray) -> ActionConfig:
    """Validated ActionConfig from a canonical-order vector."""
    vector = np.asarray(values, dtype=np.float64).ravel()
    if vector.shape[0] != len(ACTION_NAMES):
        raise ContractValidationError("config", f"expected {len(ACTION_NAMES)} values in canonical order; got {vector.shape[0]}")
    return canonical_config(ActionConfig(*(float(v) for v in vector)))


# ---------------------------------------------------------------------------
# Strategy identity (ACTION_MODEL.md §6) lives in src/contracts/identity.py;
# WS2 adds only truncated-ID collision handling.
# ---------------------------------------------------------------------------


def assign_strategy_id(
    identity: str,
    taken: Mapping[str, str],
    *,
    id_fn: Callable[..., str] = strategy_id_from_identity,
) -> str:
    """Shortest ID (16, 24, ... 64 hex chars) not already bound to a *different* identity.

    ``taken`` maps already-issued IDs to their full identity, so a truncated-hash collision
    is detected by comparing full identities and resolved by extending the new ID.
    """
    for hex_length in range(STRATEGY_ID_HEX_LENGTH, 65, 8):
        candidate = id_fn(identity, hex_length=hex_length)
        bound = taken.get(candidate)
        if bound is None or bound == identity:
            return candidate
    raise ContractValidationError("strategy_id", "SHA-256 collision on the full digest")


# ---------------------------------------------------------------------------
# Content fingerprints for provenance input hashes
# ---------------------------------------------------------------------------


def baseline_fingerprint(baseline: BaselineBundle) -> str:
    """SHA-256 over baseline metadata and the exact monthly values."""
    header = {
        name: getattr(baseline, name)
        for name in ("schema_version", "run_id", "baseline_id", "company_id", "horizon_months", "model_id",
                     "driver_policy_id", "data_kind", "scope2_method", "currency")
    }
    header["history_end"] = baseline.history_end.isoformat()
    header["provenance"] = ser.provenance_to_dict(baseline.provenance)
    header["totals"] = {key: float(value) for key, value in baseline.totals.items()}
    digest = hashlib.sha256(canonical_hash(header).encode("utf-8"))
    monthly = baseline.monthly
    digest.update(monthly["timestamp"].to_numpy(dtype="datetime64[ns]").astype("<i8").tobytes())
    numeric = [name for name in HISTORY_COLUMNS if name not in ("company_id", "timestamp")]
    digest.update(np.ascontiguousarray(monthly[numeric].to_numpy(dtype="<f8")).tobytes())
    digest.update("\x1f".join(str(v) for v in monthly["company_id"].tolist()).encode("utf-8"))
    return digest.hexdigest()


def assumptions_fingerprint(assumptions: ActionAssumptions) -> str:
    return canonical_hash(ser.assumptions_to_dict(assumptions))
