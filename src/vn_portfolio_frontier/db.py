"""Database connection helpers for Neon Cloud PostgreSQL.

Loads NEON_DATABASE_URL from `.env` (via python-dotenv) or the system
environment, and exposes connection helpers for the rest of the package.

Typical usage:

    from vn_portfolio_frontier.db import connection_scope

    with connection_scope() as conn, conn.cursor() as cur:
        cur.execute("SELECT version()")
        print(cur.fetchone())
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager

import psycopg2
import psycopg2.extensions
from dotenv import load_dotenv


def _load_url() -> str:
    """Load NEON_DATABASE_URL from environment (.env or system env).

    Returns:
        A libpq-compatible connection string ready for psycopg2.connect.

    Raises:
        RuntimeError: If NEON_DATABASE_URL is not set.
    """
    load_dotenv()  # walks upward from CWD looking for .env; safe if absent
    url = os.getenv("NEON_DATABASE_URL")
    if not url:
        raise RuntimeError(
            "NEON_DATABASE_URL is not set. Copy .env.example to .env and "
            "fill in your Neon connection string, then rerun."
        )
    return url


def is_configured() -> bool:
    """Whether Neon credentials are available in the environment.

    Used by test suites to skip integration tests gracefully when the
    developer has not configured `.env` (typical for CI runs).
    """
    try:
        _load_url()
        return True
    except RuntimeError:
        return False


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
