"""Neon adapter for predictions schema (migration 015).

Implements PredictionRepository Protocol port per Hexagonal (ADR-015).
Uses connection_factory pattern matching NeonPriceRepository / RebalanceRunRepository.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Protocol
from uuid import UUID

import psycopg2
from psycopg2.extras import Json, RealDictCursor

logger = logging.getLogger(__name__)

ConnectionFactory = Callable[[], psycopg2.extensions.connection]


@dataclass(frozen=True)
class PredictionRecord:
    prediction_date: date
    prediction_source: str
    ticker: str
    action: str
    horizon_days: int
    model_version: str
    weight_recommended: Decimal | None = None
    confidence: Decimal | None = None
    price_at_prediction: Decimal | None = None
    rationale: str | None = None
    sprint_tag: str | None = None
    metadata: dict[str, Any] | None = None


@dataclass(frozen=True)
class MaturedPrediction:
    prediction_id: UUID
    ticker: str
    prediction_date: date
    evaluation_date: date
    horizon_days: int
    price_at_prediction: Decimal
    action: str


class PredictionRepository(Protocol):
    def save_prediction(self, record: PredictionRecord) -> UUID: ...
    def save_actual(
        self,
        prediction_id,
        evaluation_date,
        price_at_evaluation,
        return_actual,
        directional_match,
        benchmark_return,
        alpha,
    ): ...
    def find_matured_without_actual(self, as_of: date) -> list[MaturedPrediction]: ...
    def refresh_evaluation_rolling(self) -> None: ...


class NeonPredictionRepository:
    """PostgreSQL adapter for predictions schema."""

    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._conn_factory = connection_factory

    def _cursor(self, conn):
        return conn.cursor(cursor_factory=RealDictCursor)

    def save_prediction(self, record: PredictionRecord) -> UUID:
        sql = """
            INSERT INTO predictions.daily_prediction (
                prediction_date, prediction_source, ticker,
                weight_recommended, action, horizon_days, confidence,
                price_at_prediction, rationale, model_version, sprint_tag,
                metadata
            )
            VALUES (%(prediction_date)s, %(prediction_source)s, %(ticker)s,
                    %(weight_recommended)s, %(action)s, %(horizon_days)s, %(confidence)s,
                    %(price_at_prediction)s, %(rationale)s, %(model_version)s,
                    %(sprint_tag)s, %(metadata)s)
            ON CONFLICT (prediction_date, prediction_source, ticker,
                         horizon_days, model_version)
            DO UPDATE SET
                weight_recommended = EXCLUDED.weight_recommended,
                action = EXCLUDED.action,
                confidence = EXCLUDED.confidence,
                price_at_prediction = EXCLUDED.price_at_prediction,
                rationale = EXCLUDED.rationale,
                metadata = EXCLUDED.metadata,
                created_at = NOW()
            RETURNING prediction_id;
        """
        params = {
            "prediction_date": record.prediction_date,
            "prediction_source": record.prediction_source,
            "ticker": record.ticker,
            "weight_recommended": record.weight_recommended,
            "action": record.action,
            "horizon_days": record.horizon_days,
            "confidence": record.confidence,
            "price_at_prediction": record.price_at_prediction,
            "rationale": record.rationale,
            "model_version": record.model_version,
            "sprint_tag": record.sprint_tag,
            "metadata": Json(record.metadata or {}),
        }
        conn = self._conn_factory()
        try:
            with self._cursor(conn) as cur:
                cur.execute(sql, params)
                row = cur.fetchone()
                conn.commit()
                return row["prediction_id"]
        finally:
            conn.close()

    def save_actual(
        self,
        prediction_id,
        evaluation_date,
        price_at_evaluation,
        return_actual,
        directional_match,
        benchmark_return,
        alpha,
    ):
        sql = """
            INSERT INTO predictions.daily_actual (
                prediction_id, evaluation_date, price_at_evaluation, return_actual,
                directional_match, benchmark_return, alpha
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (prediction_id) DO UPDATE SET
                evaluation_date = EXCLUDED.evaluation_date,
                price_at_evaluation = EXCLUDED.price_at_evaluation,
                return_actual = EXCLUDED.return_actual,
                directional_match = EXCLUDED.directional_match,
                benchmark_return = EXCLUDED.benchmark_return,
                alpha = EXCLUDED.alpha,
                computed_at = NOW()
            RETURNING actual_id;
        """
        conn = self._conn_factory()
        try:
            with self._cursor(conn) as cur:
                cur.execute(
                    sql,
                    (
                        str(prediction_id),
                        evaluation_date,
                        price_at_evaluation,
                        return_actual,
                        directional_match,
                        benchmark_return,
                        alpha,
                    ),
                )
                row = cur.fetchone()
                conn.commit()
                return row["actual_id"]
        finally:
            conn.close()

    def find_matured_without_actual(self, as_of: date) -> list[MaturedPrediction]:
        sql = """
            SELECT dp.prediction_id, dp.ticker, dp.prediction_date,
                   (dp.prediction_date + (dp.horizon_days || ' days')::INTERVAL)::DATE AS evaluation_date,
                   dp.horizon_days, dp.price_at_prediction, dp.action
            FROM predictions.daily_prediction dp
            LEFT JOIN predictions.daily_actual da ON da.prediction_id = dp.prediction_id
            WHERE da.actual_id IS NULL
              AND dp.price_at_prediction IS NOT NULL
              AND dp.prediction_date + (dp.horizon_days || ' days')::INTERVAL <= %s::DATE
            ORDER BY dp.prediction_date, dp.ticker;
        """
        conn = self._conn_factory()
        try:
            with self._cursor(conn) as cur:
                cur.execute(sql, (as_of,))
                rows = cur.fetchall()
                return [
                    MaturedPrediction(
                        prediction_id=r["prediction_id"],
                        ticker=r["ticker"],
                        prediction_date=r["prediction_date"],
                        evaluation_date=r["evaluation_date"],
                        horizon_days=r["horizon_days"],
                        price_at_prediction=r["price_at_prediction"],
                        action=r["action"],
                    )
                    for r in rows
                ]
        finally:
            conn.close()

    def refresh_evaluation_rolling(self) -> None:
        conn = self._conn_factory()
        try:
            with self._cursor(conn) as cur:
                cur.execute(
                    "REFRESH MATERIALIZED VIEW CONCURRENTLY predictions.evaluation_rolling;"
                )
                conn.commit()
        finally:
            conn.close()


class InMemoryPredictionRepository:
    """Fake for unit tests."""

    def __init__(self):
        from uuid import uuid4

        self._predictions: dict = {}
        self._actuals: dict = {}
        self._uuid = uuid4

    def save_prediction(self, record):
        for pid, rec in self._predictions.items():
            if (
                rec.prediction_date == record.prediction_date
                and rec.prediction_source == record.prediction_source
                and rec.ticker == record.ticker
                and rec.horizon_days == record.horizon_days
                and rec.model_version == record.model_version
            ):
                self._predictions[pid] = record
                return pid
        pid = self._uuid()
        self._predictions[pid] = record
        return pid

    def save_actual(
        self,
        prediction_id,
        evaluation_date,
        price_at_evaluation,
        return_actual,
        directional_match,
        benchmark_return,
        alpha,
    ):
        aid = self._uuid()
        self._actuals[prediction_id] = {
            "actual_id": aid,
            "evaluation_date": evaluation_date,
            "price_at_evaluation": price_at_evaluation,
            "return_actual": return_actual,
            "directional_match": directional_match,
            "benchmark_return": benchmark_return,
            "alpha": alpha,
        }
        return aid

    def find_matured_without_actual(self, as_of):
        result = []
        for pid, rec in self._predictions.items():
            if pid in self._actuals:
                continue
            eval_date = rec.prediction_date + timedelta(days=rec.horizon_days)
            if eval_date <= as_of and rec.price_at_prediction is not None:
                result.append(
                    MaturedPrediction(
                        prediction_id=pid,
                        ticker=rec.ticker,
                        prediction_date=rec.prediction_date,
                        evaluation_date=eval_date,
                        horizon_days=rec.horizon_days,
                        price_at_prediction=rec.price_at_prediction,
                        action=rec.action,
                    )
                )
        return result

    def refresh_evaluation_rolling(self):
        pass
