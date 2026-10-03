"""Typed boundary errors from docs/SHARED_CONTRACTS.md §4.

Shared C0 file (WS4 steward). Only the errors WS2 raises are defined here; other
workstreams add theirs (for example ``UnsupportedHorizon``) through a contract PR.
"""

from __future__ import annotations


class ContractValidationError(ValueError):
    """Invalid column, type, range, unit or configuration at a public boundary."""

    def __init__(self, field: str, reason: str) -> None:
        self.field = field
        self.reason = reason
        super().__init__(f"{field}: {reason}")

    def __reduce__(self):  # keep picklable despite the two-argument constructor
        return (type(self), (self.field, self.reason))


class OptimizationError(RuntimeError):
    """Unexpected solver failure. Distinct from a valid ``status="infeasible"`` result."""
