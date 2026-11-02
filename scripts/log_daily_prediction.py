"""scripts/log_daily_prediction.py

Daily prediction logger (ADR-019 Phase A: F1-only).
Runs Mon-Fri 16:30 via Windows Task Scheduler.
Logs 3 reference portfolios (minvar/maxsharpe/riskparity) weights for VN30.

Phase A (now): F1 Markowitz only, news deferred Sprint 13 Day 2+
Phase B (later): add news-based BUY/SELL/HOLD signals when news_summarizer ready.

Usage:
    python scripts/log_daily_prediction.py --today
    python scripts/log_daily_prediction.py --date 2026-11-03
    python scripts/log_daily_prediction.py --today --dry-run
    python scripts/log_daily_prediction.py --today --skip-eval
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, datetime, timedelta
from decimal import Decimal

from vn_portfolio_frontier.application.services.frontier_service import FrontierRequest
from vn_portfolio_frontier.infrastructure.factory import AppFactory
from vn_portfolio_frontier.infrastructure.neon.predictions_repo import PredictionRecord

logger = logging.getLogger(__name__)

MODEL_VERSION = "v2.0-sprint12-f1"
SPRINT_TAG = "sprint12"
LOOKBACK_CALENDAR_DAYS = 400  # ~1 trading year with buffer for weekends/holidays
F1_HORIZON_DAYS = 21  # monthly rebalance

VN30_TICKERS = (
    "ACB",
    "BCM",
    "BID",
    "BVH",
    "CTG",
    "FPT",
    "GAS",
    "GVR",
    "HDB",
    "HPG",
    "LPB",
    "MBB",
    "MSN",
    "MWG",
    "PLX",
    "SAB",
    "SHB",
    "SSB",
    "SSI",
    "STB",
    "TCB",
    "TPB",
    "VCB",
    "VHM",
    "VIB",
    "VIC",
    "VJC",
    "VNM",
    "VPB",
    "VRE",
)


def run_f1_predictions(target_date, repo, frontier, price_repo, dry_run=False):
    """Compute 1 FrontierCurve, log 3 reference portfolios + ticker weights."""
    errors = []
    count = 0

    request = FrontierRequest(
        tickers=VN30_TICKERS,
        backtest_start=target_date - timedelta(days=LOOKBACK_CALENDAR_DAYS),
        backtest_end=target_date,
        rf_source="vn_bond_1y",
        upper_bound=0.4,
        n_frontier_points=20,
    )

    try:
        result = frontier.compute(request)
    except Exception as exc:
        errors.append(f"F1 compute failed: {exc!r}")
        logger.exception("F1 FrontierService.compute failed")
        return 0, errors

    curve = result.frontier_curve

    # Price cache: avoid refetching per reference portfolio
    price_cache = {}
    for ticker in VN30_TICKERS:
        try:
            bars = price_repo.get_ohlcv(
                ticker, start=target_date - timedelta(days=14), end=target_date
            )
            price_cache[ticker] = float(bars[-1].close) if bars else None
        except Exception as exc:
            errors.append(f"Price fetch {ticker}: {exc!r}")
            price_cache[ticker] = None

    for ref_name, portfolio in [
        ("minvar", curve.ref_min_variance),
        ("maxsharpe", curve.ref_max_sharpe),
        ("riskparity", curve.ref_risk_parity),
    ]:
        source_tag = f"f1_optimizer_{ref_name}"
        for ticker, weight in portfolio.weights.items():
            price = price_cache.get(ticker)
            if price is None or price <= 0:
                errors.append(f"{source_tag}:{ticker} missing price")
                continue

            record = PredictionRecord(
                prediction_date=target_date,
                prediction_source=source_tag,
                ticker=ticker,
                weight_recommended=Decimal(str(round(weight, 5))),
                action="N_A",
                horizon_days=F1_HORIZON_DAYS,
                confidence=None,
                price_at_prediction=Decimal(str(price)),
                rationale=f"F1 {portfolio.label}, lookback {LOOKBACK_CALENDAR_DAYS}d, "
                f"Rf={result.rf_annual_pct}%, universe={result.universe_size}",
                model_version=MODEL_VERSION,
                sprint_tag=SPRINT_TAG,
                metadata={
                    "ref_portfolio": portfolio.label,
                    "expected_return_annual_pct": float(portfolio.expected_return_annual_pct),
                    "volatility_annual_pct": float(portfolio.volatility_annual_pct),
                    "sharpe": float(portfolio.sharpe) if portfolio.sharpe is not None else None,
                    "rf_annual_pct": float(result.rf_annual_pct),
                    "data_window_days": result.data_window_days,
                    "returns_rows": result.returns_rows,
                },
            )

            if dry_run:
                logger.info(f"[DRY RUN] {source_tag}:{ticker} w={weight:.4f} price={price}")
                count += 1
            else:
                try:
                    repo.save_prediction(record)
                    count += 1
                except Exception as exc:
                    errors.append(f"Save {source_tag}:{ticker}: {exc!r}")

    return count, errors


def evaluate_matured(target_date, repo, price_repo, dry_run=False):
    """Find matured predictions, compute return + directional_match."""
    errors = []
    count = 0
    matured = repo.find_matured_without_actual(as_of=target_date)
    logger.info(f"Found {len(matured)} matured predictions")

    for pred in matured:
        try:
            bars = price_repo.get_ohlcv(
                pred.ticker,
                start=pred.evaluation_date - timedelta(days=14),
                end=pred.evaluation_date,
            )
            if not bars:
                errors.append(f"No price for {pred.ticker} on {pred.evaluation_date}")
                continue
            actual_price = float(bars[-1].close)
            price_prediction = float(pred.price_at_prediction)
            return_actual = (actual_price / price_prediction) - 1.0

            if pred.action == "BUY":
                directional = return_actual > 0
            elif pred.action == "SELL":
                directional = return_actual < 0
            elif pred.action == "HOLD":
                directional = abs(return_actual) < 0.005
            else:
                directional = None

            if dry_run:
                logger.info(f"[DRY RUN] eval {pred.ticker}: return={return_actual:.4f}")
                count += 1
            else:
                repo.save_actual(
                    prediction_id=pred.prediction_id,
                    evaluation_date=pred.evaluation_date,
                    price_at_evaluation=Decimal(str(actual_price)),
                    return_actual=Decimal(str(round(return_actual, 6))),
                    directional_match=directional,
                    benchmark_return=None,
                    alpha=None,
                )
                count += 1
        except Exception as exc:
            errors.append(f"Evaluate {pred.prediction_id}: {exc!r}")
    return count, errors


def main(argv=None):
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--today", action="store_true")
    group.add_argument("--date", type=str)
    parser.add_argument("--skip-eval", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    target_date = date.today() if args.today else date.fromisoformat(args.date)
    if target_date.weekday() >= 5:
        logger.warning(f"{target_date} is weekend, skipping")
        return 0

    factory = AppFactory()
    repo = factory.prediction_repo()
    frontier = factory.frontier_service()
    price_repo = factory.price_repo()

    started = datetime.now()
    all_errors = []

    logger.info(f"[{target_date}] F1 predictions...")
    n_f1, errs = run_f1_predictions(target_date, repo, frontier, price_repo, dry_run=args.dry_run)
    all_errors.extend(errs)

    n_eval = 0
    if not args.skip_eval:
        logger.info(f"[{target_date}] Evaluating matured...")
        n_eval, errs = evaluate_matured(target_date, repo, price_repo, dry_run=args.dry_run)
        all_errors.extend(errs)

    if not args.dry_run and n_eval > 0:
        try:
            repo.refresh_evaluation_rolling()
        except Exception as exc:
            all_errors.append(f"Refresh view: {exc!r}")

    duration = (datetime.now() - started).total_seconds()
    print(f"=== Report {target_date} ===")
    print(f"F1 predictions: {n_f1}")
    print(f"Matured evaluations: {n_eval}")
    print(f"Errors: {len(all_errors)}")
    print(f"Duration: {duration:.2f}s")
    for e in all_errors[:10]:
        print(f"  - {e}")

    return 0 if not all_errors else (1 if (n_f1 > 0 or n_eval > 0) else 2)


if __name__ == "__main__":
    import os

    os.makedirs("logs", exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler("logs/predictions.log", mode="a", encoding="utf-8"),
        ],
    )
    sys.exit(main())
