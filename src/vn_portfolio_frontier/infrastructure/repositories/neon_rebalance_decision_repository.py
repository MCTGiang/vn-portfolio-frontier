"""Concrete RebalanceDecisionRepository backed by Neon.

Per ADR-015 section 2.4. Implements save_batch (execute_values) and
find_by_run (chronological retrieval with JSONB deserialisation).

Schema mapping (Migration 009 simulation.rebalance_decision):
    - trigger_date         <-- entity.triggered_at
    - orders_json          <-- entity.orders (tuple[Order] -> list[dict])
    - order_count          <-- len(entity.orders) (DB default 0)
    - cost_total           <-- entity.costs.total() (DB default 0)
    - weight_drift_bps     <-- derived from max |weight_after - weight_before|
    - portfolio_value_*    <-- NOT stored by Day 6 Simulator (NULL in DB).
                               Day 10+ may populate when integrating daily
                               values into decisions.
    - cost_brokerage/slippage/tax: flat NUMERIC columns from TradingCost
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from decimal import Decimal
from typing import TYPE_CHECKING

from psycopg2.extras import Json, execute_values

from vn_portfolio_frontier.domain.entities.order import Order, OrderSide
from vn_portfolio_frontier.domain.entities.rebalance_decision import (
    RebalanceDecision,
    TradingCost,
)

if TYPE_CHECKING:
    import psycopg2

ConnectionFactory = Callable[[], "psycopg2.extensions.connection"]


class NeonRebalanceDecisionRepository:
    """Neon-backed RebalanceDecisionRepository (duck-types the port Protocol).

    Decisions share no strategy_name column in the schema - the parent
    rebalance_run row carries it. The entity preserves strategy_name for
    in-memory flow but it is dropped at persistence boundary.
    """

    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._conn_factory = connection_factory

    def save_batch(
        self,
        run_id: int,
        decisions: Sequence[RebalanceDecision],
    ) -> int:
        if not decisions:
            return 0
        sql = """
            INSERT INTO simulation.rebalance_decision (
                run_id,
                trigger_date,
                reason,
                weights_before,
                weights_after,
                weight_drift_bps,
                orders_json,
                order_count,
                cost_brokerage,
                cost_slippage,
                cost_tax,
                cost_total
            ) VALUES %s
        """
        rows = [self._decision_to_row(run_id, d) for d in decisions]
        with self._conn_factory() as conn, conn.cursor() as cur:
            execute_values(cur, sql, rows, page_size=5000)
            conn.commit()
            return len(decisions)

    def find_by_run(self, run_id: int) -> list[RebalanceDecision]:
        sql = """
            SELECT
                trigger_date,
                reason,
                weights_before,
                weights_after,
                orders_json,
                cost_brokerage,
                cost_slippage,
                cost_tax
            FROM simulation.rebalance_decision
            WHERE run_id = %s
            ORDER BY trigger_date ASC, decision_id ASC
        """
        with self._conn_factory() as conn, conn.cursor() as cur:
            cur.execute(sql, (run_id,))
            return [self._row_to_decision(row) for row in cur.fetchall()]

    @staticmethod
    def _decision_to_row(run_id: int, d: RebalanceDecision) -> tuple:
        orders_payload = [
            {
                "ticker": o.ticker,
                "side": o.side.value,
                "shares": o.shares,
                "est_price": str(o.est_price),
            }
            for o in d.orders
        ]
        # weight_drift_bps = max absolute change in weight across union of tickers,
        # expressed in basis points. NULL when no weights recorded (no_action).
        tickers = set(d.weights_before) | set(d.weights_after)
        if tickers:
            weight_drift_bps = int(
                max(
                    abs(d.weights_after.get(t, 0.0) - d.weights_before.get(t, 0.0)) for t in tickers
                )
                * 10000
            )
        else:
            weight_drift_bps = None

        return (
            run_id,
            d.triggered_at,
            d.reason,
            Json(d.weights_before),
            Json(d.weights_after),
            weight_drift_bps,
            Json(orders_payload),
            len(d.orders),
            d.costs.brokerage,
            d.costs.slippage,
            d.costs.tax,
            d.costs.total(),
        )

    @staticmethod
    def _row_to_decision(row: tuple) -> RebalanceDecision:
        (
            trigger_date,
            reason,
            weights_before,
            weights_after,
            orders_json,
            cost_brokerage,
            cost_slippage,
            cost_tax,
        ) = row
        if isinstance(weights_before, str):
            weights_before = json.loads(weights_before)
        if isinstance(weights_after, str):
            weights_after = json.loads(weights_after)
        if isinstance(orders_json, str):
            orders_json = json.loads(orders_json)

        orders = tuple(
            Order(
                ticker=o["ticker"],
                side=OrderSide(o["side"]),
                shares=int(o["shares"]),
                est_price=Decimal(o["est_price"]),
            )
            for o in orders_json
        )
        costs = TradingCost(
            brokerage=cost_brokerage,
            slippage=cost_slippage,
            tax=cost_tax,
        )
        # strategy_name is not persisted on the decision row - parent run carries it.
        # Caller join to simulation.rebalance_run if needed (list_recent returns it).
        # Here we fall back to the generic marker "persisted" so field is non-empty.
        return RebalanceDecision(
            strategy_name="persisted",
            triggered_at=trigger_date,
            reason=reason,
            orders=orders,
            costs=costs,
            weights_before={k: float(v) for k, v in weights_before.items()},
            weights_after={k: float(v) for k, v in weights_after.items()},
        )
