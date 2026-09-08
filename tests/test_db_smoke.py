"""Smoke tests for Neon PostgreSQL connectivity.

Require a live NEON_DATABASE_URL in `.env` (or the environment). Tagged
`@pytest.mark.integration` — the whole module is skipped when credentials
aren't configured, so `pytest` still passes on a fresh clone or in CI
without secrets.

Run locally:
    pytest -v tests/test_db_smoke.py

Run only integration tests:
    pytest -v -m integration

Skip integration tests:
    pytest -v -m "not integration"
"""

from __future__ import annotations

import pytest

from vn_portfolio_frontier.db import (
    connection_scope,
    get_connection,
    is_configured,
)

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not is_configured(),
        reason=(
            "NEON_DATABASE_URL not configured; " "run `cp .env.example .env` and set credentials"
        ),
    ),
]


def test_get_connection_yields_open_connection() -> None:
    """get_connection() returns a live psycopg2 connection."""
    conn = get_connection()
    try:
        assert not conn.closed
    finally:
        conn.close()


def test_connection_scope_closes_on_exit() -> None:
    """connection_scope closes the connection when the context exits."""
    with connection_scope() as conn:
        assert not conn.closed
    assert conn.closed


def test_neon_is_postgres_18() -> None:
    """The Neon instance is running PostgreSQL 18.x.

    Guards against silent server-side major version downgrade. Update the
    prefix here if the project intentionally targets a different major
    version in the future.
    """
    with connection_scope() as conn, conn.cursor() as cur:
        cur.execute("SELECT version()")
        (version_string,) = cur.fetchone()

    assert "PostgreSQL 18" in version_string, f"Expected PostgreSQL 18.x, got: {version_string}"


def test_current_database_matches_expected() -> None:
    """Connected to the `portfolio` database as `portfolio_owner`.

    Guards against .env pointing at a wrong project (e.g. someone else's
    Neon endpoint) and against accidental role changes.
    """
    with connection_scope() as conn, conn.cursor() as cur:
        cur.execute("SELECT current_database(), current_user")
        db, user = cur.fetchone()

    assert db == "portfolio", f"Expected database 'portfolio', got '{db}'"
    assert user == "portfolio_owner", f"Expected user 'portfolio_owner', got '{user}'"
