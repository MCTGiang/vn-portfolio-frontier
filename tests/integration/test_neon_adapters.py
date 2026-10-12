"""Integration tests for the 3 Neon-backed Repository adapters.

Skip clean when NEON_DATABASE_URL is not set (CI matrix without secrets).
Each test owns its lifecycle - inserts rows into a dedicated test run_id
and deletes them in a finally-block to keep the test schema clean.

Run locally:
    pytest tests/integration/ -v

Mark pattern follows M7 workflow: integration tests are gated by env var,
not by a pytest marker alone, so they can run from local dev shells with
.env loaded without extra flags.
"""

from __future__ import annotations

import os
from datetime import date
from decimal import Decimal

import psycopg2
import pytest
from dotenv import load_dotenv

from vn_portfolio_frontier.application.ports.run_repository import RunRecord
from vn_portfolio_frontier.domain.entities import (
    Order,
    OrderSide,
    RebalanceDecision,
    TradingCost,
)
from vn_portfolio_frontier.infrastructure.repositories import (
    NeonPriceRepository,
    NeonRebalanceDecisionRepository,
    NeonRebalanceRunRepository,
)

load_dotenv()

NEON_DSN = os.environ.get("NEON_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not NEON_DSN,
    reason="Integration tests require NEON_DATABASE_URL (skipped on CI without secret)",
)


# =====================================================================
# Fixtures
# =====================================================================


def _conn_factory():
    return psycopg2.connect(NEON_DSN)


@pytest.fixture
def price_repo() -> NeonPriceRepository:
    return NeonPriceRepository(_conn_factory)


@pytest.fixture
def run_repo() -> NeonRebalanceRunRepository:
    return NeonRebalanceRunRepository(_conn_factory)


@pytest.fixture
def decision_repo() -> NeonRebalanceDecisionRepository:
    return NeonRebalanceDecisionRepository(_conn_factory)


@pytest.fixture
def sample_run_record() -> RunRecord:
    return RunRecord(
        brokerage_pct=Decimal("0.0015"),
        tax_pct=Decimal("0.001"),
        market_impact_bps=10,
        strategy_name="threshold_band",
        strategy_params={"band_bps": 500},
        target_weights={"VCB": 0.5, "FPT": 0.5},
        backtest_start=date(2024, 1, 1),
        backtest_end=date(2024, 12, 31),
        git_commit_sha="integration" + "a" * 29,
        code_version="test-v2.0",
        initial_capital=Decimal("100000000"),
        status="running",
    )


@pytest.fixture
def cleanup_runs() -> list[int]:
    """Collect run_ids to delete after each test to keep DB tidy.

    FK CASCADE from rebalance_run drops decision rows automatically.
    """
    created: list[int] = []
    yield created
    if not created:
        return
    with _conn_factory() as conn, conn.cursor() as cur:
        cur.execute(
            "DELETE FROM simulation.rebalance_run WHERE run_id = ANY(%s)",
            (created,),
        )
        conn.commit()


# =====================================================================
# NeonPriceRepository
# =====================================================================


class TestNeonPriceRepository:
    def test_get_ohlcv_returns_sorted_bars(self, price_repo):
        # Rely on seeded data (Sprint 10 B.3 ingested VCB) to avoid
        # mutating the shared prices table. Pick a safe historical window.
        bars = price_repo.get_ohlcv("VCB", date(2024, 1, 1), date(2024, 1, 31))
        assert isinstance(bars, list)
        for i in range(1, len(bars)):
            assert bars[i].trade_date >= bars[i - 1].trade_date

    def test_get_ohlcv_rejects_inverted_range(self, price_repo):
        with pytest.raises(ValueError, match="start"):
            price_repo.get_ohlcv("VCB", date(2024, 12, 31), date(2024, 1, 1))

    def test_get_latest_dates_includes_vcb(self, price_repo):
        latest = price_repo.get_latest_dates()
        assert "VCB" in latest
        assert latest["VCB"] >= date(2024, 1, 1)


# =====================================================================
# NeonRebalanceRunRepository
# =====================================================================


class TestNeonRebalanceRunRepository:
    def test_round_trip_save_and_find(self, run_repo, sample_run_record, cleanup_runs):
        run_id = run_repo.save(sample_run_record)
        cleanup_runs.append(run_id)

        retrieved = run_repo.find_by_id(run_id)
        assert retrieved is not None
        assert retrieved.strategy_name == sample_run_record.strategy_name
        assert retrieved.target_weights == sample_run_record.target_weights
        assert retrieved.initial_capital == sample_run_record.initial_capital
        assert retrieved.status == "running"

    def test_find_by_id_returns_none_for_unknown(self, run_repo):
        assert run_repo.find_by_id(2**31 - 1) is None

    def test_update_status_completed_with_kpis(self, run_repo, sample_run_record, cleanup_runs):
        run_id = run_repo.save(sample_run_record)
        cleanup_runs.append(run_id)

        run_repo.update_status(
            run_id,
            status="completed",
            kpis={
                "n_rebalances": 5,
                "total_cost_bps": 25,
                "turnover_avg_pct": Decimal("0.08"),
                "sharpe_before_cost": Decimal("1.42"),
                "sharpe_after_cost": Decimal("1.18"),
            },
        )
        retrieved = run_repo.find_by_id(run_id)
        assert retrieved.status == "completed"
        assert retrieved.n_rebalances == 5
        assert retrieved.total_cost_bps == 25
        assert retrieved.sharpe_before_cost == Decimal("1.42")

    def test_update_status_failed_captures_error(self, run_repo, sample_run_record, cleanup_runs):
        run_id = run_repo.save(sample_run_record)
        cleanup_runs.append(run_id)

        run_repo.update_status(
            run_id, status="failed", error_message="Strategy raised at 2024-03-15"
        )
        retrieved = run_repo.find_by_id(run_id)
        assert retrieved.status == "failed"
        assert "Strategy raised" in retrieved.error_message

    def test_update_status_rejects_unknown_run_id(self, run_repo):
        with pytest.raises(ValueError, match="unknown run_id"):
            run_repo.update_status(2**31 - 1, status="completed")

    def test_list_recent_includes_saved_run(self, run_repo, sample_run_record, cleanup_runs):
        run_id = run_repo.save(sample_run_record)
        cleanup_runs.append(run_id)
        summaries = run_repo.list_recent(limit=50)
        assert any(s.run_id == run_id for s in summaries)


# =====================================================================
# NeonRebalanceDecisionRepository
# =====================================================================


class TestNeonRebalanceDecisionRepository:
    def _make_decision(self) -> RebalanceDecision:
        return RebalanceDecision(
            strategy_name="threshold_band",
            triggered_at=date(2024, 3, 15),
            reason="band_drift",
            orders=(
                Order("VCB", OrderSide.BUY, 100, Decimal("125000")),
                Order("FPT", OrderSide.SELL, 50, Decimal("95000")),
            ),
            costs=TradingCost(
                brokerage=Decimal("25875.00"),
                slippage=Decimal("17250.00"),
                tax=Decimal("4750.00"),
            ),
            weights_before={"VCB": 0.3, "FPT": 0.7},
            weights_after={"VCB": 0.5, "FPT": 0.5},
        )

    def test_round_trip_save_batch_and_find(
        self, run_repo, decision_repo, sample_run_record, cleanup_runs
    ):
        run_id = run_repo.save(sample_run_record)
        cleanup_runs.append(run_id)

        decisions = [self._make_decision()]
        inserted = decision_repo.save_batch(run_id, decisions)
        assert inserted == 1

        retrieved = decision_repo.find_by_run(run_id)
        assert len(retrieved) == 1
        got = retrieved[0]
        assert got.triggered_at == date(2024, 3, 15)
        assert got.reason == "band_drift"
        assert len(got.orders) == 2
        assert got.orders[0].ticker == "VCB"
        assert got.orders[0].side == OrderSide.BUY
        assert got.orders[0].shares == 100
        assert got.costs.brokerage == Decimal("25875.00")
        assert got.weights_before == {"VCB": 0.3, "FPT": 0.7}
        assert got.weights_after == {"VCB": 0.5, "FPT": 0.5}

    def test_save_batch_empty_is_zero(self, decision_repo):
        assert decision_repo.save_batch(run_id=1, decisions=[]) == 0

    def test_find_by_run_empty_for_unknown(self, decision_repo):
        assert decision_repo.find_by_run(2**31 - 1) == []
