"""Provider protocols (shared C0 file; flag for WS4 review)."""

from __future__ import annotations

from typing import Protocol

from src.contracts.types import ActionAssumptions, ActionConfig, BaselineBundle, SimulationResult


class SimulationFn(Protocol):
    """The canonical simulator signature injected into optimizer and risk services."""

    def __call__(
        self, baseline: BaselineBundle, config: ActionConfig, *, assumptions: ActionAssumptions
    ) -> SimulationResult: ...
