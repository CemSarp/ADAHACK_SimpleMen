"""Train (or verify cached) WS1 artifacts ahead of launching the dashboard.

    python -m src.forecasting.train            # reuse compatible artifacts, else train
    python -m src.forecasting.train --retrain  # force a fresh WS1 run
"""

from __future__ import annotations

import argparse
import logging
import time

from src.integration.config import IntegrationConfig

from .provider import WS1ForecastProvider
from .ws1_adapter import load_or_train


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=None, help="integration config (default config/integration.json)")
    parser.add_argument("--retrain", action="store_true", help="ignore cached artifacts")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    for noisy in ("cmdstanpy", "prophet"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    provider = WS1ForecastProvider(IntegrationConfig.load(args.config))
    started = time.perf_counter()
    art = load_or_train(provider.imported, provider.settings, provider.config.horizon_months,
                        provider.config.model_dir, retrain=args.retrain)
    baseline = provider.get_baseline(company_id=provider.company_id, horizon_months=provider.config.horizon_months)
    report = provider.get_backtest(company_id=provider.company_id)
    print(f"model_id={art.model_id} trained_now={art.trained_now} training_seconds={art.training_seconds:.1f} "
          f"wall_seconds={time.perf_counter() - started:.1f} artifacts={art.directory}")
    print(f"best models: {dict(art.best_models)}")
    print(f"baseline {baseline.baseline_id}: {baseline.monthly['timestamp'].iloc[0]:%Y-%m}.."
          f"{baseline.monthly['timestamp'].iloc[-1]:%Y-%m} totals={dict(baseline.totals)}")
    for target, m in report.aggregate_metrics.items():
        print(f"backtest {target}: MAE {m['mae']:.2f} vs seasonal-naive {m['naive_mae']:.2f}")


if __name__ == "__main__":
    main()
