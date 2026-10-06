"""WS2 simulator provider: the deterministic action engine bound to one assumption file."""

from __future__ import annotations

from pathlib import Path

from src.contracts.types import ActionAssumptions, ActionConfig, BaselineBundle, ProviderInfo, SimulationResult

from . import engine
from .definitions import load_action_assumptions


class WS2SimulatorProvider:
    """The engine bound to an assumption file, or to already built assumptions (an upload's)."""

    def __init__(self, assumptions_path: str | Path | None = None, assumptions: ActionAssumptions | None = None) -> None:
        self._assumptions = assumptions or load_action_assumptions(assumptions_path)
        a = self._assumptions
        self.info = ProviderInfo(slot="simulator", name="ws2-simulate_strategy",
                                 version=f"{engine.__version__}+{a.assumptions_id}@{a.version}", is_mock=False, kind="real")

    def get_assumptions(self) -> ActionAssumptions:
        return self._assumptions

    def simulate(self, baseline: BaselineBundle, config: ActionConfig, *, assumptions: ActionAssumptions) -> SimulationResult:
        return engine.simulate_strategy(baseline, config, assumptions=assumptions)
