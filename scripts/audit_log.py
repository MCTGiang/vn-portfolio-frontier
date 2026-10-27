"""Audit log helper for scheduled data refresh runs (Day 12, Sprint 11, ADR-018).

CLI wrapper that INSERTs/UPDATEs rows in audit.data_refresh_run table.
Called by .github/workflows/daily-data-refresh.yml to track script lifecycle.

Usage:
    # Mark a sync script as started
    python scripts/audit_log.py start sync_prices \\
        --github-run-id $GITHUB_RUN_ID \\
        --github-run-url $GITHUB_RUN_URL \\
        --source github_actions_cron
    # Prints the run_id (UUID) to stdout for workflow capture

    # Mark it as succeeded
    python scripts/audit_log.py end <run_id> --status succeeded --rows 1234

    # Mark it as failed
    python scripts/audit_log.py end <run_id> --status failed --error "connection timeout"

Idempotent: UPDATE WHERE run_id=... + status='pending' guards against double-end.
"""

from __future__ import annotations

import argparse
import logging
import sys
import uuid

import psycopg2

from vn_portfolio_frontier.config import get_settings

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


def _get_dsn() -> str:
    """Fetch NEON_DATABASE_URL from env/.env via Settings."""
    s = get_settings()
    dsn = s.neon_database_url
    if hasattr(dsn, "get_secret_value"):
        dsn = dsn.get_secret_value()
    return str(dsn)


def start_run(
    script_name: str,
    github_run_id: str | None = None,
    github_run_url: str | None = None,
    source: str = "github_actions_cron",
) -> str:
    """INSERT a new audit row with status='pending'. Returns run_id."""
    run_id = str(uuid.uuid4())
    with psycopg2.connect(_get_dsn()) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO audit.data_refresh_run (
                    run_id, script_name, status,
                    github_run_id, github_run_url, source
                )
                VALUES (%s, %s, 'pending', %s, %s, %s)
                """,
                (run_id, script_name, github_run_id, github_run_url, source),
            )
        conn.commit()
    logger.info(f"audit.data_refresh_run started: run_id={run_id} script={script_name}")
    return run_id


def end_run(
    run_id: str,
    status: str,
    rows_fetched: int = 0,
    error_message: str | None = None,
) -> None:
    """UPDATE audit row to succeeded or failed. Idempotent."""
    if status not in ("succeeded", "failed"):
        raise ValueError(f"status must be succeeded|failed, got {status!r}")
    if status == "failed" and not error_message:
        raise ValueError("status=failed requires error_message")
    with psycopg2.connect(_get_dsn()) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE audit.data_refresh_run
                SET status = %s,
                    finished_at = NOW(),
                    rows_fetched = %s,
                    error_message = %s
                WHERE run_id = %s AND status = 'pending'
                """,
                (status, rows_fetched, error_message, run_id),
            )
            if cur.rowcount == 0:
                logger.warning(f"audit.data_refresh_run end noop: run_id={run_id} not pending")
            else:
                logger.info(
                    f"audit.data_refresh_run end: run_id={run_id} status={status} rows={rows_fetched}"
                )
        conn.commit()


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit log helper for data refresh runs")
    subparsers = parser.add_subparsers(dest="cmd", required=True)

    # start subcommand
    p_start = subparsers.add_parser("start", help="Mark a sync script as started (prints run_id)")
    p_start.add_argument("script_name", choices=["sync_prices", "sync_benchmarks", "sync_universe"])
    p_start.add_argument("--github-run-id", default=None)
    p_start.add_argument("--github-run-url", default=None)
    p_start.add_argument(
        "--source",
        default="github_actions_cron",
        choices=["github_actions_cron", "github_actions_dispatch", "local_dev", "manual_backfill"],
    )

    # end subcommand
    p_end = subparsers.add_parser("end", help="Mark a sync script as succeeded or failed")
    p_end.add_argument("run_id")
    p_end.add_argument("--status", choices=["succeeded", "failed"], required=True)
    p_end.add_argument("--rows", type=int, default=0)
    p_end.add_argument("--error", default=None)

    args = parser.parse_args()

    try:
        if args.cmd == "start":
            run_id = start_run(
                script_name=args.script_name,
                github_run_id=args.github_run_id,
                github_run_url=args.github_run_url,
                source=args.source,
            )
            print(run_id)  # stdout for workflow $() capture
        elif args.cmd == "end":
            end_run(
                run_id=args.run_id,
                status=args.status,
                rows_fetched=args.rows,
                error_message=args.error,
            )
    except Exception as exc:
        logger.exception(f"audit_log {args.cmd} failed: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
