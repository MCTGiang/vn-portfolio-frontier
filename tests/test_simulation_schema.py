"""Integration tests for simulation schema (rebalance_run).

Verifies structural state per ADR-012 (locked cost model naming) +
CHECK constraints actively enforced at DB level (not just declared).
"""

from __future__ import annotations

import pytest
from psycopg2 import errors as pg_errors

from vn_portfolio_frontier.db import connection_scope, is_configured, list_tables

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not is_configured(),
        reason=(
            "NEON_DATABASE_URL not configured; " "run `cp .env.example .env` and set credentials"
        ),
    ),
]


def test_simulation_schema_and_table_exist() -> None:
    """Migration 005 created simulation schema + rebalance_run table."""
    tables = set(list_tables("simulation"))
    assert (
        "rebalance_run" in tables
    ), f"Missing rebalance_run in simulation schema. Have: {sorted(tables)}"


def test_migration_005_recorded() -> None:
    """The tracking table records migration 005."""
    with connection_scope() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT filename FROM public._migrations WHERE filename = %s",
            ("005_create_simulation_schema.sql",),
        )
        row = cur.fetchone()
    assert row is not None, "005_create_simulation_schema.sql not recorded"


def test_rebalance_run_has_expected_columns() -> None:
    """Schema matches ADR-012 API contract (brokerage_pct/tax_pct/market_impact_bps)."""
    with connection_scope() as conn, conn.cursor() as cur:
        cur.execute("""
            SELECT column_name, data_type, is_nullable
            FROM information_schema.columns
            WHERE table_schema = 'simulation'
              AND table_name = 'rebalance_run'
            ORDER BY ordinal_position
            """)
        rows = cur.fetchall()

    columns = {row[0]: (row[1], row[2]) for row in rows}

    expected: dict[str, tuple[str, str]] = {
        "run_id": ("bigint", "NO"),
        "run_timestamp": ("timestamp with time zone", "NO"),
        "brokerage_pct": ("numeric", "NO"),
        "tax_pct": ("numeric", "NO"),
        "market_impact_bps": ("smallint", "NO"),
        "strategy_name": ("character varying", "NO"),
        "strategy_params": ("jsonb", "NO"),
        "target_weights": ("jsonb", "NO"),
        "backtest_start": ("date", "NO"),
        "backtest_end": ("date", "NO"),
        "sharpe_before_cost": ("numeric", "YES"),
        "sharpe_after_cost": ("numeric", "YES"),
        "total_cost_bps": ("smallint", "YES"),
        "turnover_avg_pct": ("numeric", "YES"),
        "n_rebalances": ("integer", "YES"),
        "git_commit_sha": ("character varying", "NO"),
        "code_version": ("character varying", "NO"),
    }
    for name, (dtype, nullable) in expected.items():
        actual = columns.get(name)
        assert actual == (
            dtype,
            nullable,
        ), f"rebalance_run.{name}: expected {(dtype, nullable)}, got {actual}"


def _valid_insert_kwargs() -> dict:
    """Baseline valid row — reused by CHECK tests via mutation."""
    return {
        "brokerage_pct": 0.15,
        "tax_pct": 0.10,
        "market_impact_bps": 10,
        "strategy_name": "threshold_band",
        "strategy_params": '{"band_pct": 5.0}',
        "target_weights": '{"VCB": 0.15, "VNM": 0.12}',
        "backtest_start": "2021-01-01",
        "backtest_end": "2025-12-31",
        "git_commit_sha": "0" * 40,
        "code_version": "0.1.0",
    }


_INSERT_SQL = """
    INSERT INTO simulation.rebalance_run
        (brokerage_pct, tax_pct, market_impact_bps,
         strategy_name, strategy_params, target_weights,
         backtest_start, backtest_end,
         git_commit_sha, code_version)
    VALUES
        (%(brokerage_pct)s, %(tax_pct)s, %(market_impact_bps)s,
         %(strategy_name)s, %(strategy_params)s::jsonb, %(target_weights)s::jsonb,
         %(backtest_start)s, %(backtest_end)s,
         %(git_commit_sha)s, %(code_version)s)
    RETURNING run_id
"""


def test_valid_insert_returns_run_id() -> None:
    """A well-formed row inserts and RETURNING yields run_id. Rolled back for cleanup."""
    with connection_scope() as conn, conn.cursor() as cur:
        cur.execute(_INSERT_SQL, _valid_insert_kwargs())
        row = cur.fetchone()
        conn.rollback()  # don't persist test data
    assert row is not None and row[0] > 0


def test_check_brokerage_pct_range_enforced() -> None:
    """CHECK constraint rejects brokerage_pct > 1.0 (unit trap: user meant bps)."""
    params = _valid_insert_kwargs() | {"brokerage_pct": 1.5}
    with connection_scope() as conn, conn.cursor() as cur, pytest.raises(pg_errors.CheckViolation):
        cur.execute(_INSERT_SQL, params)


def test_check_strategy_name_known_enforced() -> None:
    """CHECK constraint rejects unknown strategy_name (set locked by ADR-012)."""
    params = _valid_insert_kwargs() | {"strategy_name": "random_walk"}
    with connection_scope() as conn, conn.cursor() as cur, pytest.raises(pg_errors.CheckViolation):
        cur.execute(_INSERT_SQL, params)


def test_check_backtest_dates_ordering_enforced() -> None:
    """CHECK constraint rejects backtest_end < backtest_start."""
    params = _valid_insert_kwargs() | {
        "backtest_start": "2025-12-31",
        "backtest_end": "2021-01-01",
    }
    with connection_scope() as conn, conn.cursor() as cur, pytest.raises(pg_errors.CheckViolation):
        cur.execute(_INSERT_SQL, params)


def test_indexes_created() -> None:
    """All 4 expected indexes on rebalance_run exist."""
    with connection_scope() as conn, conn.cursor() as cur:
        cur.execute("""
            SELECT indexname
            FROM pg_indexes
            WHERE schemaname = 'simulation'
              AND tablename = 'rebalance_run'
            """)
        indexes = {row[0] for row in cur.fetchall()}

    expected = {
        "idx_run_strategy",
        "idx_run_brokerage",
        "idx_run_timestamp",
        "idx_run_git_sha",
    }
    missing = expected - indexes
    assert not missing, f"Missing indexes: {missing}. Have: {sorted(indexes)}"
