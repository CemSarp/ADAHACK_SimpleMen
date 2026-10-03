"""WS3 risk demo: 100 trials over the BEHAVIORAL MOCK simulator (WS2 engine absent).

Run from the repo root:  python scripts/demo_ws3_risk.py
Production default stays RiskConfig().n_simulations == 1000.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.contracts.identity import compute_strategy_id  # noqa: E402
from src.contracts.types import RiskConfig  # noqa: E402
from src.risk.monte_carlo import evaluate_strategy_risk, load_uncertainty  # noqa: E402
from tests.mocks import fixtures  # noqa: E402
from tests.mocks.behavioral import BehavioralMockSimulator  # noqa: E402

DEMO_TRIALS = 100  # ponytail: demo only; production default is 1,000


def main() -> None:
    baseline, assumptions = fixtures.baseline(), fixtures.assumptions()
    action, constraints = fixtures.action_config(), fixtures.constraints()
    spec = load_uncertainty()
    config = RiskConfig(seed=42, n_simulations=DEMO_TRIALS)
    risk = evaluate_strategy_risk(
        baseline, action, constraints=constraints, assumptions=assumptions,
        uncertainty=spec, config=config, simulator=BehavioralMockSimulator().simulate,
    )
    s = risk.summary
    original_id = compute_strategy_id(baseline.baseline_id, action, assumptions.assumptions_id, assumptions.version)
    assert risk.strategy_id == original_id

    print("=" * 66)
    print("  MOCK SIMULATOR / ILLUSTRATIVE UNCERTAINTY - not a real risk estimate")
    print("=" * 66)
    print(f"simulator           : {BehavioralMockSimulator().info.name} (provenance.is_mock={risk.provenance.is_mock})")
    print(f"uncertainty         : {risk.uncertainty_id} ({spec.sampler_version})")
    print(f"trials              : {risk.n_simulations} DEMO trials (production default {RiskConfig().n_simulations}), seed {config.seed}")
    print(f"original strategy ID: {risk.strategy_id}")
    print(f"constraints         : budget <= {constraints.budget_gbp:,.0f} GBP, profit >= "
          f"{constraints.min_total_profit_gbp:,.0f} GBP, CO2 reduction >= {constraints.min_co2_reduction_ratio:.0%}")
    print("-" * 66)
    print(f"CO2 mean            : {s['co2_mean_tco2e']:,.3f} tCO2e")
    print(f"CO2 p05-p95         : {s['co2_p05_tco2e']:,.3f} - {s['co2_p95_tco2e']:,.3f} tCO2e (trial interval, not a CI)")
    print(f"profit mean         : {s['profit_mean_gbp']:,.2f} GBP")
    print(f"budget success p    : {s['budget_probability']:.3f}")
    print(f"target success p    : {s['target_probability']:.3f} (MC s.e. {s['target_probability_mc_standard_error']:.3f})")
    print(f"joint feasibility p : {s['joint_feasibility_probability']:.3f}")
    print("-" * 66)
    print(f"note: {spec.calibration_note}")


if __name__ == "__main__":
    main()
