"""Seed loader for VN30 membership history (Migration 006 companion).

Reads data/seed/vn30_history.yaml and populates:
    - fundamentals.vn30_membership_event  (11 events)
    - fundamentals.vn30_membership_snapshot       (360 rows = 12 periods x 30 tickers)

Idempotent: safe to re-run. Skips event insert if table already populated;
uses ON CONFLICT DO NOTHING for constituent rows.

Usage:
    python -m scripts.seed_vn30_history

Related: ADR-013, migrations/006_create_vn30_membership_event.sql.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import psycopg2
import yaml

from vn_portfolio_frontier.config import get_settings

SEED_PATH = Path(__file__).resolve().parent.parent / "data" / "seed" / "vn30_history.yaml"

EXPECTED_EVENTS = 11
EXPECTED_CONSTITUENT_ROWS = 360
EXPECTED_UNIQUE_TICKERS = 43


def load_seed() -> dict[str, Any]:
    with open(SEED_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


def reconcile_yaml(events: list[dict], snapshots: list[dict]) -> bool:
    """Verify YAML events fold correctly into YAML snapshots.

    Runs before DB write as a safety check on the seed file itself.
    """
    snapshots_sorted = sorted(snapshots, key=lambda s: s["effective_date"])
    events_sorted = sorted(events, key=lambda e: e["effective_date"])

    current: set[str] = set(snapshots_sorted[0]["tickers"])
    computed: dict[date, set[str]] = {snapshots_sorted[0]["effective_date"]: set(current)}

    for ev in events_sorted:
        current -= set(ev["tickers_removed"])
        current |= set(ev["tickers_added"])
        computed[ev["effective_date"]] = set(current)

    all_ok = True
    for snap in snapshots_sorted:
        stored = set(snap["tickers"])
        got = computed.get(snap["effective_date"], set())
        if stored != got:
            print(f"[FAIL] {snap['period']}: " f"missing={stored - got} extra={got - stored}")
            all_ok = False

    if all_ok:
        print(
            f"[ok] YAML reconciliation passed: {len(snapshots)} snapshots match {len(events)} events fold"
        )
    return all_ok


def seed_events(conn, events: list[dict]) -> int:
    """Insert events. Skips if table already populated."""
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM fundamentals.vn30_membership_event")
        existing = cur.fetchone()[0]
        if existing > 0:
            print(f"[skip] {existing} events already present, event seed skipped")
            return 0

        insert_sql = """
            INSERT INTO fundamentals.vn30_membership_event (
                effective_date, announced_date, rebalance_type,
                tickers_added, tickers_removed, source_ref, notes
            ) VALUES (%s, %s, %s, %s, %s, %s, %s)
        """
        for ev in sorted(events, key=lambda e: e["effective_date"]):
            cur.execute(
                insert_sql,
                (
                    ev["effective_date"],
                    ev["announced_date"],
                    ev["rebalance_type"],
                    json.dumps(ev["tickers_added"]),
                    json.dumps(ev["tickers_removed"]),
                    ev.get("source_url") or "vn30_history.yaml seed",
                    ev.get("notes") or "",
                ),
            )
        print(f"[ok] Inserted {len(events)} events")
        return len(events)


def seed_constituent(conn, snapshots: list[dict]) -> int:
    """Insert flattened constituent rows. Idempotent via ON CONFLICT."""
    with conn.cursor() as cur:
        insert_sql = """
            INSERT INTO fundamentals.vn30_membership_snapshot (effective_date, ticker)
            VALUES (%s, %s)
            ON CONFLICT (effective_date, ticker) DO NOTHING
        """
        new_rows = 0
        for snap in snapshots:
            for ticker in snap["tickers"]:
                cur.execute(insert_sql, (snap["effective_date"], ticker))
                new_rows += cur.rowcount
        print(f"[ok] Inserted {new_rows} constituent rows (0 = already seeded)")
        return new_rows


def verify_db(conn) -> None:
    """Post-seed sanity: assert row counts + unique ticker set."""
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM fundamentals.vn30_membership_event")
        n_events = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM fundamentals.vn30_membership_snapshot")
        n_const = cur.fetchone()[0]
        cur.execute("SELECT COUNT(DISTINCT ticker) FROM fundamentals.vn30_membership_snapshot")
        n_tickers = cur.fetchone()[0]

    print(f"[verify] events={n_events} constituent={n_const} unique_tickers={n_tickers}")
    assert n_events == EXPECTED_EVENTS, f"expected {EXPECTED_EVENTS} events, got {n_events}"
    assert (
        n_const == EXPECTED_CONSTITUENT_ROWS
    ), f"expected {EXPECTED_CONSTITUENT_ROWS} constituent rows, got {n_const}"
    assert (
        n_tickers == EXPECTED_UNIQUE_TICKERS
    ), f"expected {EXPECTED_UNIQUE_TICKERS} unique tickers, got {n_tickers}"
    print("[ok] All DB assertions passed")


def main() -> None:
    data = load_seed()
    events = data["events"]
    snapshots = data["snapshots"]

    print(f"Loaded {len(events)} events + {len(snapshots)} snapshots from {SEED_PATH.name}")

    if not reconcile_yaml(events, snapshots):
        raise SystemExit("Reconciliation on YAML failed -- fix seed file before running")

    dsn = get_settings().neon_database_url.get_secret_value()
    with psycopg2.connect(dsn) as conn:
        seed_events(conn, events)
        seed_constituent(conn, snapshots)
        conn.commit()
        print("[ok] Transaction committed")
        verify_db(conn)


if __name__ == "__main__":
    main()
