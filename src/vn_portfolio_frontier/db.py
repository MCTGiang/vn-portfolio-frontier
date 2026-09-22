"""Database connection helpers for Neon Cloud PostgreSQL.

Reads settings via `vn_portfolio_frontier.config.get_settings()` and
exposes connection + introspection helpers for the rest of the package.

Typical usage:

    from vn_portfolio_frontier.db import connection_scope

    with connection_scope() as conn, conn.cursor() as cur:
        cur.execute("SELECT version()")
        print(cur.fetchone())
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

import psycopg2
import psycopg2.extensions

from vn_portfolio_frontier.config import get_settings


def _load_url() -> str:
    """Return the Neon connection URL from settings.

    Raises:
        RuntimeError: If NEON_DATABASE_URL is not configured.
    """
    settings = get_settings()
    if settings.neon_database_url is None:
        raise RuntimeError(
            "NEON_DATABASE_URL is not set. Copy .env.example to .env and "
            "fill in your Neon connection string, then rerun."
        )
    return settings.neon_database_url.get_secret_value()


def is_configured() -> bool:
    """Whether Neon credentials are available.

    Used by test suites to skip integration tests gracefully when the
    developer has not configured `.env` (typical for CI runs).
    """
    return get_settings().neon_database_url is not None


def get_connection() -> psycopg2.extensions.connection:
    """Open a new psycopg2 connection to Neon.

    Caller is responsible for closing (or use `connection_scope`).
    """
    return psycopg2.connect(_load_url())


@contextmanager
def connection_scope() -> Iterator[psycopg2.extensions.connection]:
    """Context manager yielding a psycopg2 connection, closed on exit.

    Preferred over bare `get_connection()` — ensures the connection is
    released even if the caller raises.
    """
    conn = get_connection()
    try:
        yield conn
    finally:
        conn.close()


def list_schemas() -> list[str]:
    """Return sorted list of user schemas.

    Excludes Postgres system schemas (pg_*, information_schema).
    """
    with connection_scope() as conn, conn.cursor() as cur:
        cur.execute("""
            SELECT schema_name
            FROM information_schema.schemata
            WHERE schema_name NOT LIKE 'pg_%'
              AND schema_name != 'information_schema'
            ORDER BY schema_name
            """)
        return [row[0] for row in cur.fetchall()]


def list_tables(schema: str) -> list[str]:
    """Return sorted list of base tables in the given schema."""
    with connection_scope() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = %s
              AND table_type = 'BASE TABLE'
            ORDER BY table_name
            """,
            (schema,),
        )
        return [row[0] for row in cur.fetchall()]
