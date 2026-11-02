"""Unit tests for daily prediction logger (ADR-019 Phase A)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from scripts.log_daily_prediction import (
    evaluate_matured,
    run_f1_predictions,
)
from vn_portfolio_frontier.infrastructure.neon.predictions_repo import (
    InMemoryPredictionRepository,
    PredictionRecord,
)


@dataclass
class FakeBar:
    trade_date: date
    close: Decimal


@dataclass
class FakePortfolio:
    label: str
    weights: dict
    expected_return_annual_pct: Decimal = Decimal("0.12")
    volatility_annual_pct: Decimal = Decimal("0.18")
    sharpe: Decimal = Decimal("0.55")


@dataclass
class FakeCurve:
    ref_min_variance: FakePortfolio
    ref_max_sharpe: FakePortfolio
    ref_risk_parity: FakePortfolio


@dataclass
class FakeResult:
    frontier_curve: FakeCurve
    rf_annual_pct: Decimal = Decimal("3.69")
    universe_size: int = 3
    data_window_days: int = 252
    returns_rows: int = 250


@pytest.fixture
def repo():
    return InMemoryPredictionRepository()


@pytest.fixture
def monday():
    return date(2026, 11, 3)


@pytest.fixture
def mock_frontier():
    service = MagicMock()
    weights = {"VCB": 0.4, "FPT": 0.35, "VNM": 0.25}
    service.compute.return_value = FakeResult(
        frontier_curve=FakeCurve(
            ref_min_variance=FakePortfolio("Min Variance", weights),
            ref_max_sharpe=FakePortfolio("Max Sharpe", weights),
            ref_risk_parity=FakePortfolio("Risk Parity", weights),
        ),
    )
    return service


@pytest.fixture
def mock_price_repo():
    repo = MagicMock()
    repo.get_ohlcv.return_value = [FakeBar(trade_date=date(2026, 11, 3), close=Decimal("92000"))]
    return repo


class TestRunF1Predictions:
    def test_logs_3_refs_x_3_tickers(self, monday, repo, mock_frontier, mock_price_repo):
        count, errors = run_f1_predictions(monday, repo, mock_frontier, mock_price_repo)
        assert count == 9
        assert errors == []
        assert mock_frontier.compute.call_count == 1  # ONE call, not 3

    def test_source_tags(self, monday, repo, mock_frontier, mock_price_repo):
        run_f1_predictions(monday, repo, mock_frontier, mock_price_repo)
        sources = {rec.prediction_source for rec in repo._predictions.values()}
        assert sources == {
            "f1_optimizer_minvar",
            "f1_optimizer_maxsharpe",
            "f1_optimizer_riskparity",
        }

    def test_action_na(self, monday, repo, mock_frontier, mock_price_repo):
        run_f1_predictions(monday, repo, mock_frontier, mock_price_repo)
        for rec in repo._predictions.values():
            assert rec.action == "N_A"
            assert rec.weight_recommended is not None
            assert rec.horizon_days == 21

    def test_dry_run_no_writes(self, monday, repo, mock_frontier, mock_price_repo):
        count, _ = run_f1_predictions(monday, repo, mock_frontier, mock_price_repo, dry_run=True)
        assert count == 9
        assert len(repo._predictions) == 0

    def test_missing_price_error(self, monday, repo, mock_frontier, mock_price_repo):
        def price_side(ticker, start, end):
            return [] if ticker == "FPT" else [FakeBar(end, Decimal("90000"))]

        mock_price_repo.get_ohlcv.side_effect = price_side
        count, errors = run_f1_predictions(monday, repo, mock_frontier, mock_price_repo)
        assert count == 6  # 2 tickers x 3 refs
        assert any("FPT" in e for e in errors)

    def test_compute_exception(self, monday, repo, mock_frontier, mock_price_repo):
        mock_frontier.compute.side_effect = RuntimeError("Infeasible")
        count, errors = run_f1_predictions(monday, repo, mock_frontier, mock_price_repo)
        assert count == 0
        assert any("Infeasible" in e for e in errors)

    def test_metadata_populated(self, monday, repo, mock_frontier, mock_price_repo):
        run_f1_predictions(monday, repo, mock_frontier, mock_price_repo)
        rec = next(iter(repo._predictions.values()))
        assert rec.metadata["expected_return_annual_pct"] == 0.12
        assert rec.metadata["sharpe"] == 0.55
        assert rec.metadata["rf_annual_pct"] == 3.69


class TestEvaluateMatured:
    def test_evaluates_only_matured(self, repo, mock_price_repo):
        matured_id = repo.save_prediction(
            PredictionRecord(
                prediction_date=date(2026, 10, 1),
                prediction_source="f1_optimizer_minvar",
                ticker="VCB",
                action="N_A",
                horizon_days=5,
                model_version="x",
                price_at_prediction=Decimal("90000"),
            )
        )
        repo.save_prediction(
            PredictionRecord(
                prediction_date=date(2026, 10, 20),
                prediction_source="f1_optimizer_minvar",
                ticker="FPT",
                action="N_A",
                horizon_days=21,
                model_version="x",
                price_at_prediction=Decimal("120000"),
            )
        )
        count, _ = evaluate_matured(date(2026, 11, 3), repo, mock_price_repo)
        assert count == 1
        assert matured_id in repo._actuals

    def test_na_action_directional_none(self, repo, mock_price_repo):
        pid = repo.save_prediction(
            PredictionRecord(
                prediction_date=date(2026, 10, 1),
                prediction_source="f1_optimizer_minvar",
                ticker="VCB",
                action="N_A",
                horizon_days=21,
                model_version="x",
                price_at_prediction=Decimal("90000"),
            )
        )
        evaluate_matured(date(2026, 11, 3), repo, mock_price_repo)
        assert repo._actuals[pid]["directional_match"] is None

    def test_return_computed(self, repo, mock_price_repo):
        pid = repo.save_prediction(
            PredictionRecord(
                prediction_date=date(2026, 10, 1),
                prediction_source="f1_optimizer_minvar",
                ticker="VCB",
                action="N_A",
                horizon_days=5,
                model_version="x",
                price_at_prediction=Decimal("90000"),
            )
        )
        # mock_price_repo returns close=92000 -> return = (92000/90000)-1 = 0.0222...
        evaluate_matured(date(2026, 11, 3), repo, mock_price_repo)
        ret = repo._actuals[pid]["return_actual"]
        assert float(ret) > 0.02 and float(ret) < 0.025
