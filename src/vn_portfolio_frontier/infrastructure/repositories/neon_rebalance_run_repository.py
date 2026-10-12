"""Concrete RebalanceRunRepository backed by Neon (simulation.rebalance_run).

Per ADR-015 section 2.4. Implements save (INSERT RETURNING run_id),
find_by_id, list_recent (RunSummary projection), and update_status
(partial UPDATE for status + output KPIs).

Schema notes (Migration 005 + 009 + 010):
    - 11 required input fields + 7 nullable output fields + status/completed_at/error_message
    - strategy_params and target_weights are JSONB (serialised via psycopg2 Json wrapper)
    - run_timestamp defaults to NOW() at save time
    - update_status stamps completed_at = NOW() when status transitions to
      completed or failed (matches the behaviour the Fake implements in-memory)
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from psycopg2.extras import Json

from vn_portfolio_frontier.application.ports.run_repository import RunRecord, RunSummary

if TYPE_CHECKING:
    import psycopg2

ConnectionFactory = Callable[[], "psycopg2.extensions.connection"]

# KPI keys the port contract declares as updatable through update_status.
# Unknown keys are silently ignored for forward compatibility with future
# metrics (e.g., when F1 Efficient Frontier adds max_drawdown_pct).
_ALLOWED_KPI_KEYS = frozenset(
    {
        "n_rebalances",
        "total_cost_bps",
        "turnover_avg_pct",
        "sharpe_before_cost",
        "sharpe_after_cost",
    }
)

# Terminal statuses that also stamp completed_at = NOW().
_TERMINAL_STATUSES = frozenset({"completed", "failed"})


class NeonRebalanceRunRepository:
    """Neon-backed RebalanceRunRepository (duck-types the port Protocol)."""

    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._conn_factory = connection_factory

    def save(self, record: RunRecord) -> int:
        sql = """
            INSERT INTO simulation.rebalance_run (
                brokerage_pct,
                tax_pct,
                market_impact_bps,
                strategy_name,
                strategy_params,
                target_weights,
                backtest_start,
                backtest_end,
                git_commit_sha,
                code_version,
                initial_capital,
                sharpe_before_cost,
                sharpe_after_cost,
                total_cost_bps,
                turnover_avg_pct,
                n_rebalances,
                status,
                error_message
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s, %s
            )
            RETURNING run_id
        """
        with self._conn_factory() as conn, conn.cursor() as cur:
            cur.execute(
                sql,
                (
                    record.brokerage_pct,
                    record.tax_pct,
                    record.market_impact_bps,
                    record.strategy_name,
                    Json(record.strategy_params),
                    Json(record.target_weights),
                    record.backtest_start,
                    record.backtest_end,
                    record.git_commit_sha,
                    record.code_version,
                    record.initial_capital,
                    record.sharpe_before_cost,
                    record.sharpe_after_cost,
                    record.total_cost_bps,
                    record.turnover_avg_pct,
                    record.n_rebalances,
                    record.status,
                    record.error_message,
                ),
            )
            run_id = cur.fetchone()[0]
            conn.commit()
            return int(run_id)

    def find_by_id(self, run_id: int) -> RunRecord | None:
        sql = """
            SELECT
                brokerage_pct, tax_pct, market_impact_bps,
                strategy_name, strategy_params, target_weights,
                backtest_start, backtest_end,
                git_commit_sha, code_version, initial_capital,
                sharpe_before_cost, sharpe_after_cost, total_cost_bps,
                turnover_avg_pct, n_rebalances, status, error_message
            FROM simulation.rebalance_run
            WHERE run_id = %s
        """
        with self._conn_factory() as conn, conn.cursor() as cur:
            cur.execute(sql, (run_id,))
            row = cur.fetchone()
            if row is None:
                return None
            return self._row_to_record(row)

    def list_recent(self, limit: int = 20) -> list[RunSummary]:
        if limit <= 0:
            raise ValueError(f"list_recent: limit must be positive, got {limit}")
        sql = """
            SELECT run_id, run_timestamp, strategy_name, sharpe_after_cost, status
            FROM simulation.rebalance_run
            ORDER BY run_timestamp DESC
            LIMIT %s
        """
        with self._conn_factory() as conn, conn.cursor() as cur:
            cur.execute(sql, (limit,))
            return [
                RunSummary(
                    run_id=int(row[0]),
                    run_timestamp=row[1],
                    strategy_name=row[2],
                    sharpe_after_cost=row[3],
                    status=row[4],
                )
                for row in cur.fetchall()
            ]

    def update_status(
        self,
        run_id: int,
        status: str,
        error_message: str | None = None,
        kpis: dict[str, Any] | None = None,
    ) -> None:
        # Build dynamic SET clause from provided fields. Reject empty updates
        # as a no-op would still touch the row (and we want callers to be
        # explicit about intent).
        set_clauses: list[str] = ["status = %s"]
        params: list[Any] = [status]

        if error_message is not None:
            set_clauses.append("error_message = %s")
            params.append(error_message)

        if kpis:
            for key, value in kpis.items():
                if key in _ALLOWED_KPI_KEYS:
                    set_clauses.append(f"{key} = %s")
                    params.append(value)

        if status in _TERMINAL_STATUSES:
            set_clauses.append("completed_at = NOW()")

        sql = f"""
            UPDATE simulation.rebalance_run
            SET {", ".join(set_clauses)}
            WHERE run_id = %s
        """
        params.append(run_id)

        with self._conn_factory() as conn, conn.cursor() as cur:
            cur.execute(sql, params)
            if cur.rowcount == 0:
                conn.rollback()
                raise ValueError(f"update_status: unknown run_id {run_id}")
            conn.commit()

    @staticmethod
    def _row_to_record(row: tuple) -> RunRecord:
        (
            brokerage_pct,
            tax_pct,
            market_impact_bps,
            strategy_name,
            strategy_params,
            target_weights,
            backtest_start,
            backtest_end,
            git_commit_sha,
            code_version,
            initial_capital,
            sharpe_before_cost,
            sharpe_after_cost,
            total_cost_bps,
            turnover_avg_pct,
            n_rebalances,
            status,
            error_message,
        ) = row
        # JSONB columns come back as native Python dicts via psycopg2 default
        # decoder - no manual json.loads() needed.
        if isinstance(strategy_params, str):
            strategy_params = json.loads(strategy_params)
        if isinstance(target_weights, str):
            target_weights = json.loads(target_weights)

        return RunRecord(
            brokerage_pct=brokerage_pct,
            tax_pct=tax_pct,
            market_impact_bps=int(market_impact_bps),
            strategy_name=strategy_name,
            strategy_params=strategy_params,
            target_weights={k: float(v) for k, v in target_weights.items()},
            backtest_start=backtest_start,
            backtest_end=backtest_end,
            git_commit_sha=git_commit_sha,
            code_version=code_version,
            initial_capital=initial_capital,
            sharpe_before_cost=sharpe_before_cost,
            sharpe_after_cost=sharpe_after_cost,
            total_cost_bps=int(total_cost_bps) if total_cost_bps is not None else None,
            turnover_avg_pct=turnover_avg_pct,
            n_rebalances=int(n_rebalances) if n_rebalances is not None else None,
            status=status,
            error_message=error_message,
        )
