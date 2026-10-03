"""Canonical strategy identity (docs/ACTION_MODEL.md section 6).

Sorted-key compact JSON of baseline ID, full-precision config, assumption ID and
version; SHA-256; first 16 hex characters prefixed with ``strategy-``. No
decimal rounding participates in identity.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

from .types import ACTION_NAMES, ActionConfig

STRATEGY_ID_PREFIX = "strategy-"
STRATEGY_ID_HEX_LENGTH = 16


def strategy_identity_payload(
    baseline_id: str, config: ActionConfig, assumptions_id: str, assumptions_version: str
) -> str:
    identity = {
        "baseline_id": baseline_id,
        "config": {name: float(getattr(config, name)) for name in ACTION_NAMES},
        "assumptions_id": assumptions_id,
        "assumptions_version": assumptions_version,
    }
    return json.dumps(identity, sort_keys=True, separators=(",", ":"))


def compute_strategy_id(
    baseline_id: str,
    config: ActionConfig,
    assumptions_id: str,
    assumptions_version: str,
    *,
    hex_length: int = STRATEGY_ID_HEX_LENGTH,
) -> str:
    payload = strategy_identity_payload(baseline_id, config, assumptions_id, assumptions_version)
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return STRATEGY_ID_PREFIX + digest[:hex_length]


def canonical_hash(value: Any) -> str:
    """SHA-256 of sorted-key compact JSON; used for input hashes and cache keys."""
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def config_from_row(row: Mapping[str, Any]) -> ActionConfig:
    """Exact ActionConfig from a candidate/Pareto row (no rounding)."""
    return ActionConfig(**{name: float(row[name]) for name in ACTION_NAMES})
