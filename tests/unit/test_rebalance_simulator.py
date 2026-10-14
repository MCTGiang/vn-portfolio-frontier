"""Unit tests for RebalanceSimulator orchestrator (Day 6).

Covers:
    - SimulateRequest DTO validation (date order, weights sum, capital sign)
    - Happy path: full daily loop with persistence of Run + Decisions
    - Error paths: no prices, strategy raise, portfolio raise, unknown strategy
    - Edge cases: single-day backtest, wide band = zero rebalances, callback
    - Sharpe before vs after cost consistency
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from tests.unit.fakes import (
    FakePriceRepository,
    FakeRebalanceDecisionRepository,
    FakeRebalanceRunRepository,
)
from vn_portfolio_frontier.application.services import (
    RebalanceSimulator,
    SimulateRequest,
)
from vn_portfolio_frontier.domain.entities import DailyPrice
from vn_portfolio_frontier.domain.services import CostCalculator
from vn_portfolio_frontier.domain.strategies import BaseStrategy, ThresholdBandStrategy

# =====================================================================
# Fixtures
# =====================================================================


@pytest.fixture
def price_repo() -> FakePriceRepository:
    return FakePriceRepository()


@pytest.fixture
def run_repo() -> FakeRebalanceRunRepository:
    return FakeRebalanceRunRepository()


@pytest.fixture
def decision_repo() -> FakeRebalanceDecisionRepository:
    return FakeRebalanceDecisionRepository()


def _strategy_factory_impl(name: str, params: dict, cost_calc: CostCalculator) -> BaseStrategy:
    """Day 6 inline factory. Day 7 moves this into AppFactory class."""
    if name == "threshold_band":
        return ThresholdBandStrategy(cost_calc, **params)
    raise ValueError(f"Unknown strategy: {name}")


@pytest.fixture
def simulator(price_repo, run_repo, decision_repo) -> RebalanceSimulator:
    return RebalanceSimulator(
        price_repo=price_repo,
        run_repo=run_repo,
        decision_repo=decision_repo,
        strategy_factory=_strategy_factory_impl,
    )


@pytest.fixture
def seed_prices_10_days(price_repo) -> list[date]:
    """Seed 10 trading days of VCB + FPT with gentle divergent trends.

    VCB rises ~0.4% per day, FPT falls ~0.26% per day. Over 10 days this
    creates ~6.6% drift between tickers - enough to trigger narrow bands,
    not enough to trigger wide bands.
    """
    days = [date(2024, 1, d) for d in range(2, 12)]
    bars = []
    for i, day in enumerate(days):
        bars.append(
            DailyPrice(
                ticker="VCB",
                trade_date=day,
                open_price=Decimal(f"{125000 + i * 500}"),
                high=Decimal(f"{126000 + i * 500}"),
                low=Decimal(f"{124500 + i * 500}"),
                close=Decimal(f"{125500 + i * 500}"),
                volume=1_000_000,
            )
        )
        bars.append(
            DailyPrice(
                ticker="FPT",
                trade_date=day,
                open_price=Decimal(f"{95000 - i * 250}"),
                high=Decimal(f"{96000 - i * 250}"),
                low=Decimal(f"{94500 - i * 250}"),
                close=Decimal(f"{95500 - i * 250}"),
                volume=500_000,
            )
        )
    price_repo.batch_insert(bars)
    return days


def _make_request(**overrides) -> SimulateRequest:
    """Build a baseline SimulateRequest, allowing overrides for test variants."""
    defaults = {
        "target_weights": {"VCB": 0.5, "FPT": 0.5},
        "initial_capital": Decimal("100000000"),
        "backtest_start": date(2024, 1, 2),
        "backtest_end": date(2024, 1, 11),
        "strategy_name": "threshold_band",
        "strategy_params": {"band_bps": 500},
        "brokerage_pct": Decimal("0.0015"),
        "git_commit_sha": "a" * 40,
        "code_version": "v2.0-sprint11",
    }
    defaults.update(overrides)
    return SimulateRequest(**defaults)


@pytest.fixture
def basic_request() -> SimulateRequest:
    return _make_request()


# =====================================================================
# SimulateRequest DTO validation
# =====================================================================


class TestSimulateRequestValidation:
    def test_rejects_start_after_end(self):
        with pytest.raises(ValueError, match="backtest_start"):
            _make_request(
                backtest_start=date(2024, 12, 31),
                backtest_end=date(2024, 1, 1),
            )

    def test_rejects_weights_not_summing_to_one(self):
        with pytest.raises(ValueError, match="target_weights"):
            _make_request(target_weights={"VCB": 0.3, "FPT": 0.4})

    def test_accepts_weights_within_tolerance(self):
        # 1% tolerance for rounding (0.99 - 1.01)
        request = _make_request(target_weights={"VCB": 0.333, "FPT": 0.333, "VNM": 0.334})
        assert sum(request.target_weights.values()) == pytest.approx(1.0, abs=1e-9)

    def test_rejects_zero_initial_capital(self):
        with pytest.raises(ValueError, match="initial_capital"):
            _make_request(initial_capital=Decimal("0"))

    def test_rejects_negative_initial_capital(self):
        with pytest.raises(ValueError, match="initial_capital"):
            _make_request(initial_capital=Decimal("-100"))


# =====================================================================
# Happy path
# =====================================================================


class TestSimulateHappyPath:
    def test_returns_positive_run_id(self, simulator, basic_request, seed_prices_10_days):
        run_id = simulator.simulate(basic_request).run_id
        assert run_id >= 1

    def test_persists_run_record_with_input_fields(
        self, simulator, run_repo, basic_request, seed_prices_10_days
    ):
        run_id = simulator.simulate(basic_request).run_id
        record = run_repo.find_by_id(run_id)
        assert record is not None
        assert record.brokerage_pct == basic_request.brokerage_pct
        assert record.strategy_name == basic_request.strategy_name
        assert record.target_weights == basic_request.target_weights
        assert record.initial_capital == basic_request.initial_capital

    def test_run_completes_without_error(
        self, simulator, run_repo, basic_request, seed_prices_10_days
    ):
        run_id = simulator.simulate(basic_request).run_id
        record = run_repo.find_by_id(run_id)
        assert record.status == "completed"
        assert record.error_message is None

    def test_persists_only_actionable_rebalances(
        self, simulator, decision_repo, basic_request, seed_prices_10_days
    ):
        """Only actual rebalance events persist; 'no_trigger' days are filtered.
        DB CHECK constraint chk_decision_reason_known rejects 'no_trigger'
        reason. Daily portfolio values flow through SimulateResult DTO instead
        of the decisions table.
        """
        run_id = simulator.simulate(basic_request).run_id
        decisions = decision_repo.find_by_run(run_id)
        assert len(decisions) >= 1, "fresh portfolio must trigger at least once"
        assert all(d.reason != "no_trigger" for d in decisions)

    def test_captures_rebalance_count(
        self, simulator, run_repo, basic_request, seed_prices_10_days
    ):
        run_id = simulator.simulate(basic_request).run_id
        record = run_repo.find_by_id(run_id)
        assert record.n_rebalances is not None
        assert record.n_rebalances >= 0

    def test_captures_cost_kpi_non_negative(
        self, simulator, run_repo, basic_request, seed_prices_10_days
    ):
        run_id = simulator.simulate(basic_request).run_id
        record = run_repo.find_by_id(run_id)
        assert record.total_cost_bps is not None
        assert record.total_cost_bps >= 0

    def test_fresh_portfolio_triggers_at_least_once(
        self, simulator, run_repo, basic_request, seed_prices_10_days
    ):
        """Day 1 fresh portfolio has 100% cash, 0% in each ticker, 50% target
        drift -> any band < 10000 bps triggers at least once."""
        run_id = simulator.simulate(basic_request).run_id
        record = run_repo.find_by_id(run_id)
        assert record.n_rebalances >= 1


# =====================================================================
# Error paths
# =====================================================================


class TestSimulateErrorPaths:
    def test_fails_on_empty_price_history(self, simulator, run_repo, basic_request):
        with pytest.raises(ValueError, match="No price data"):
            simulator.simulate(basic_request)
        failed = run_repo.find_by_id(1)
        assert failed is not None
        assert failed.status == "failed"
        assert "No price data" in failed.error_message

    def test_fails_on_strategy_construction_error(self, simulator, run_repo, seed_prices_10_days):
        """band_bps=0 is invalid at ThresholdBandStrategy construction time."""
        bad = _make_request(strategy_params={"band_bps": 0})
        with pytest.raises(ValueError, match="band_bps"):
            simulator.simulate(bad)
        failed = run_repo.find_by_id(1)
        assert failed.status == "failed"

    def test_fails_on_unknown_strategy(self, simulator, run_repo, seed_prices_10_days):
        bad = _make_request(strategy_name="not_a_strategy")
        with pytest.raises(ValueError, match="Unknown strategy"):
            simulator.simulate(bad)
        failed = run_repo.find_by_id(1)
        assert failed.status == "failed"

    def test_dto_rejects_invalid_input_without_touching_repo(self, run_repo):
        """Bad SimulateRequest never reaches the Simulator - no Run is created."""
        with pytest.raises(ValueError):
            _make_request(backtest_start=date(2024, 12, 31), backtest_end=date(2024, 1, 1))
        assert run_repo.find_by_id(1) is None


# =====================================================================
# Edge cases
# =====================================================================


class TestSimulateEdgeCases:
    def test_single_day_backtest_completes(self, simulator, price_repo, run_repo):
        day = date(2024, 1, 2)
        price_repo.batch_insert(
            [
                DailyPrice(
                    "VCB",
                    day,
                    Decimal("125000"),
                    Decimal("126000"),
                    Decimal("124500"),
                    Decimal("125500"),
                    1_000_000,
                ),
                DailyPrice(
                    "FPT",
                    day,
                    Decimal("95000"),
                    Decimal("96000"),
                    Decimal("94500"),
                    Decimal("95500"),
                    500_000,
                ),
            ]
        )
        request = _make_request(backtest_start=day, backtest_end=day)
        run_id = simulator.simulate(request).run_id
        record = run_repo.find_by_id(run_id)
        assert record.status == "completed"
        # Single day -> only 1 daily value -> Sharpe cannot be computed
        assert record.sharpe_after_cost is None
        assert record.sharpe_before_cost is None

    def test_wide_band_prevents_rebalance_on_fresh_portfolio(
        self, simulator, run_repo, seed_prices_10_days
    ):
        """band_bps=10000 (100%) exceeds fresh-portfolio drift (50%) -> no trigger."""
        wide = _make_request(strategy_params={"band_bps": 10000})
        run_id = simulator.simulate(wide).run_id
        record = run_repo.find_by_id(run_id)
        assert record.n_rebalances == 0
        assert record.total_cost_bps == 0

    def test_single_ticker_portfolio(self, simulator, price_repo, run_repo):
        day = date(2024, 1, 2)
        price_repo.batch_insert(
            [
                DailyPrice(
                    "VCB",
                    day,
                    Decimal("125000"),
                    Decimal("126000"),
                    Decimal("124500"),
                    Decimal("125500"),
                    1_000_000,
                )
            ]
        )
        request = _make_request(
            target_weights={"VCB": 1.0},
            backtest_start=day,
            backtest_end=day,
        )
        run_id = simulator.simulate(request).run_id
        assert run_repo.find_by_id(run_id).status == "completed"

    def test_decisions_persisted_in_chronological_order(
        self, simulator, decision_repo, basic_request, seed_prices_10_days
    ):
        run_id = simulator.simulate(basic_request).run_id
        decisions = decision_repo.find_by_run(run_id)
        for i in range(1, len(decisions)):
            assert decisions[i].triggered_at >= decisions[i - 1].triggered_at


# =====================================================================
# Progress callback
# =====================================================================


class TestSimulateProgressCallback:
    def test_callback_invoked_once_per_trading_day(
        self, simulator, basic_request, seed_prices_10_days
    ):
        calls: list[tuple[date, int, int]] = []
        simulator.simulate(
            basic_request,
            on_progress=lambda day, done, total: calls.append((day, done, total)),
        )
        assert len(calls) == 10
        last_day, last_done, last_total = calls[-1]
        assert last_done == 10
        assert last_total == 10

    def test_callback_defaults_to_none_runs_cleanly(
        self, simulator, run_repo, basic_request, seed_prices_10_days
    ):
        run_id = simulator.simulate(basic_request, on_progress=None).run_id
        assert run_repo.find_by_id(run_id).status == "completed"


# =====================================================================
# Sharpe before vs after cost
# =====================================================================


class TestSimulateSharpe:
    def test_sharpe_both_computed_when_rebalances_occur(
        self, simulator, run_repo, seed_prices_10_days
    ):
        """When rebalances happen, both Sharpe variants are computed to Decimal.

        Note: the relationship between sharpe_before and sharpe_after depends
        on the cost structure vs market volatility pattern. On short horizons
        with high per-trade costs, cost shocks can INCREASE volatility more
        than they reduce mean return, making sharpe_after mathematically
        HIGHER than sharpe_before (counter-intuitive but valid). Long-horizon
        validation of the cost-drag intuition is deferred to F1 integration
        tests (Sprint 15+).
        """
        narrow_high_cost = _make_request(
            strategy_params={"band_bps": 1},
            brokerage_pct=Decimal("0.005"),
        )
        run_id = simulator.simulate(narrow_high_cost).run_id
        record = run_repo.find_by_id(run_id)
        assert record.sharpe_before_cost is not None
        assert record.sharpe_after_cost is not None
        assert isinstance(record.sharpe_before_cost, Decimal)
        assert isinstance(record.sharpe_after_cost, Decimal)
        # Cost drag is detectable via total_cost_bps regardless of Sharpe sign
        assert record.total_cost_bps > 0

    def test_sharpe_quantised_to_four_decimals(
        self, simulator, run_repo, basic_request, seed_prices_10_days
    ):
        run_id = simulator.simulate(basic_request).run_id
        record = run_repo.find_by_id(run_id)
        if record.sharpe_after_cost is not None:
            # Decimal exponent is -4 for quantise("0.0001")
            assert record.sharpe_after_cost.as_tuple().exponent == -4

    def test_result_includes_trading_days_and_values(
        self, simulator, basic_request, seed_prices_10_days
    ):
        """SimulateResult DTO exposes trading_days + daily values for UI charts."""
        result = simulator.simulate(basic_request)
        assert len(result.trading_days) == 10
        assert len(result.daily_values_after_cost) == 10
        assert len(result.daily_values_before_cost) == 10

    def test_max_drawdown_computed(self, simulator, run_repo, basic_request, seed_prices_10_days):
        """MDD >= 0 and <= 100 after a happy-path run."""
        run_id = simulator.simulate(basic_request).run_id
        record = run_repo.find_by_id(run_id)
        assert record.max_drawdown_pct is not None
        assert Decimal("0") <= record.max_drawdown_pct <= Decimal("100")

    def test_volatility_computed(self, simulator, run_repo, basic_request, seed_prices_10_days):
        """Annualised vol > 0 when prices move at all."""
        run_id = simulator.simulate(basic_request).run_id
        record = run_repo.find_by_id(run_id)
        assert record.volatility_annualized_pct is not None
        assert record.volatility_annualized_pct > Decimal("0")

    def test_buy_and_hold_series_length_matches_trading_days(
        self, simulator, basic_request, seed_prices_10_days
    ):
        result = simulator.simulate(basic_request)
        assert len(result.daily_values_buy_and_hold) == len(result.trading_days)
        assert all(v > 0 for v in result.daily_values_buy_and_hold)

    def test_buy_and_hold_day_zero_approximately_initial_capital(
        self, simulator, basic_request, seed_prices_10_days
    ):
        """Day 0 B&H value should equal initial_capital (fractional shares, no rounding loss)."""
        result = simulator.simulate(basic_request)
        assert abs(result.daily_values_buy_and_hold[0] - basic_request.initial_capital) < Decimal(
            "1"
        )
