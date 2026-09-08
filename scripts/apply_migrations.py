#!/usr/bin/env python3
"""Apply pending SQL migrations to the Neon database.

Reads .sql files from `migrations/` in alphabetical order, tracks applied
migrations in `public._migrations`, and refuses to re-apply a migration
whose on-disk checksum has drifted from what was originally applied.

Usage
-----
    python scripts/apply_migrations.py            # apply pending migrations
    python scripts/apply_migrations.py --dry-run  # print what would run
    python scripts/apply_migrations.py --verbose  # extra logging

Design notes
------------
- All pending migrations for one invocation run in a single transaction.
  Any failure rolls the whole batch back. Postgres DDL (CREATE SCHEMA,
  CREATE TABLE, CREATE INDEX) is transactional in modern versions, so
  this is safe.
- The migration runner is itself idempotent — running it again on a fully
  applied database is a no-op.
- Checksum drift detection guards against silent edits to already-applied
  migration files. If a file needs to change after being applied, create a
  new migration file instead.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

from vn_portfolio_frontier.db import connection_scope

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"


def sha256_of(path: Path) -> str:
    """Return hex-encoded SHA256 of file contents."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def get_applied_migrations(conn) -> dict[str, str]:
    """Return dict of {filename: checksum} for migrations recorded in DB.

    Returns an empty dict if the tracking table doesn't exist yet (fresh DB).
    """
    with conn.cursor() as cur:
        cur.execute("SELECT to_regclass('public._migrations') IS NOT NULL")
        (exists,) = cur.fetchone()
        if not exists:
            return {}

        cur.execute("SELECT filename, checksum_sha256 FROM public._migrations")
        return dict(cur.fetchall())


def apply_migration(conn, path: Path, checksum: str, verbose: bool) -> None:
    """Execute a migration file and record it in the tracking table."""
    sql = path.read_text()
    if verbose:
        print(f"  applying {path.name} ({len(sql)} bytes)")
    with conn.cursor() as cur:
        cur.execute(sql)
        cur.execute(
            """
            INSERT INTO public._migrations (filename, checksum_sha256)
            VALUES (%s, %s)
            ON CONFLICT (filename) DO NOTHING
            """,
            (path.name, checksum),
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Apply pending SQL migrations to the Neon database."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would run without applying anything.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Extra logging.",
    )
    args = parser.parse_args(argv)

    if not MIGRATIONS_DIR.is_dir():
        print(f"ERROR: migrations directory not found: {MIGRATIONS_DIR}", file=sys.stderr)
        return 2

    sql_files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    if not sql_files:
        print(f"No .sql files found in {MIGRATIONS_DIR}")
        return 0

    with connection_scope() as conn:
        applied = get_applied_migrations(conn)

        pending: list[tuple[Path, str]] = []
        for path in sql_files:
            checksum = sha256_of(path)
            if path.name in applied:
                if applied[path.name] != checksum:
                    print(
                        f"ERROR: checksum drift for {path.name}. "
                        f"Applied {applied[path.name][:12]}..., "
                        f"on-disk {checksum[:12]}...",
                        file=sys.stderr,
                    )
                    print(
                        "Create a new migration file instead of editing an " "already-applied one.",
                        file=sys.stderr,
                    )
                    return 3
                if args.verbose:
                    print(f"  skip {path.name} (already applied)")
                continue
            pending.append((path, checksum))

        if not pending:
            print(f"Up to date. {len(sql_files)} migrations, 0 pending.")
            return 0

        print(f"Pending: {len(pending)} migration(s)")
        for path, _ in pending:
            print(f"  - {path.name}")

        if args.dry_run:
            print("\nDry run — nothing applied.")
            return 0

        try:
            for path, checksum in pending:
                apply_migration(conn, path, checksum, args.verbose)
            conn.commit()
        except Exception:
            conn.rollback()
            raise

        print(f"\nApplied {len(pending)} migration(s).")
        return 0


if __name__ == "__main__":
    sys.exit(main())
