"""In-memory Fake implementations of application.ports Protocol interfaces.

Lives in `tests/` không `src/` vì chỉ test dependency. Dict-backed cho
unit tests: fast (no network), deterministic (no clock skew), explicit
(see all state in-memory).

Pattern per ADR-015 §2.4 Repository Pattern:
    - Each Fake duck-types to its corresponding Protocol
    - isinstance(fake, SomeRepository) returns True (verified in test_ports.py)
    - Unit tests inject Fake directly (bypass Factory) để avoid DB setup

Usage trong test code:
    >>> from tests.unit.fakes.in_memory_repos import (
    ...     FakePriceRepository, FakeRebalanceRunRepository,
    ...     FakeRebalanceDecisionRepository,
    ... )
    >>> price_repo = FakePriceRepository()
    >>> price_repo.batch_insert([daily_price_bar_1, daily_price_bar_2])
    >>> # ... inject into service under test
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, date, datetime

from vn_portfolio_frontier.application.ports.run_repository import RunRecord, RunSummary
from vn_portfolio_frontier.domain.entities.daily_price import DailyPrice
from vn_portfolio_frontier.domain.entities.rebalance_decision import RebalanceDecision


class FakePriceRepository:
    """Dict-backed PriceRepository cho unit tests.

    Keys by (ticker, trade_date) tuple cho O(1) duplicate check.
    """

    def __init__(self) -> None:
        self._data: dict[tuple[str, date], DailyPrice] = {}

    def get_ohlcv(self, ticker: str, start: date, end: date) -> list[DailyPrice]:
        if start > end:
            raise ValueError(f"get_ohlcv: start ({start}) > end ({end})")
        return sorted(
            [price for (t, d), price in self._data.items() if t == ticker and start <= d <= end],
            key=lambda p: p.trade_date,
        )

    def get_latest_dates(self) -> dict[str, date]:
        latest: dict[str, date] = {}
        for ticker, trade_date in self._data:
            if ticker not in latest or trade_date > latest[ticker]:
                latest[ticker] = trade_date
        return latest

    def batch_insert(self, records: list[DailyPrice]) -> int:
        before = len(self._data)
        for record in records:
            key = (record.ticker, record.trade_date)
            if key not in self._data:  # idempotent: skip duplicates
                self._data[key] = record
        return len(self._data) - before

    # Test helpers (NOT part of Protocol - convenience for arranging test state)

    def seed(self, records: list[DailyPrice]) -> None:
        """Shortcut cho arranging initial test state. Equivalent to batch_insert."""
        self.batch_insert(records)

    def clear(self) -> None:
        """Reset state giữa test cases."""
        self._data.clear()


class FakeRebalanceRunRepository:
    """Dict-backed RebalanceRunRepository cho unit tests.

    Auto-increments run_id starting from 1 (mimics BIGSERIAL).
    Timestamps use UTC now() at save() time.
    """

    def __init__(self) -> None:
        self._records: dict[int, RunRecord] = {}
        self._timestamps: dict[int, datetime] = {}
        self._next_id = 1

    def save(self, record: RunRecord) -> int:
        run_id = self._next_id
        self._next_id += 1
        self._records[run_id] = record
        self._timestamps[run_id] = datetime.now(UTC)
        return run_id

    def find_by_id(self, run_id: int) -> RunRecord | None:
        return self._records.get(run_id)

    def list_recent(self, limit: int = 20) -> list[RunSummary]:
        if limit <= 0:
            raise ValueError(f"list_recent: limit must be positive, got {limit}")
        sorted_ids = sorted(self._records.keys(), reverse=True)[:limit]
        return [
            RunSummary(
                run_id=rid,
                run_timestamp=self._timestamps[rid],
                strategy_name=self._records[rid].strategy_name,
                sharpe_after_cost=self._records[rid].sharpe_after_cost,
                status=self._records[rid].status,
            )
            for rid in sorted_ids
        ]

    # Test helpers

    def clear(self) -> None:
        self._records.clear()
        self._timestamps.clear()
        self._next_id = 1


class FakeRebalanceDecisionRepository:
    """Dict-backed RebalanceDecisionRepository cho unit tests.

    Keys by run_id -> list[RebalanceDecision]. find_by_run returns
    chronologically-sorted copy (defensive - caller can't mutate internal).
    """

    def __init__(self) -> None:
        self._data: dict[int, list[RebalanceDecision]] = {}

    def save_batch(
        self,
        run_id: int,
        decisions: Sequence[RebalanceDecision],
    ) -> int:
        """Append `decisions` to the list cho `run_id`. Not idempotent."""
        if run_id not in self._data:
            self._data[run_id] = []
        self._data[run_id].extend(decisions)
        return len(decisions)

    def find_by_run(self, run_id: int) -> list[RebalanceDecision]:
        """Return chronologically-sorted copy. Empty list cho unknown run_id."""
        return sorted(
            self._data.get(run_id, []),
            key=lambda d: d.triggered_at,
        )

    # Test helpers

    def clear(self) -> None:
        self._data.clear()
