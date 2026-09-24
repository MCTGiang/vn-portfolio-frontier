"""Tests for Migration 006 (VN30 membership) + seed loader.

Two tiers:
- unit: pure logic on seed YAML, no DB (CI-safe, always runs).
- integration: schema + CHECK constraints + seeded rows on live Neon
  (skipped on CI where NEON_DATABASE_URL is not set).

The last two integration tests assume the seed script has been run at
least once; if not, they will fail on the row-count assertions.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from seed_vn30_history import (  # noqa: E402
    EXPECTED_CONSTITUENT_ROWS,
    EXPECTED_EVENTS,
    EXPECTED_UNIQUE_TICKERS,
    load_seed,
    reconcile_yaml,
)

# ============================================================
# Unit tests (YAML + reconciliation logic, no DB)
# ============================================================


@pytest.fixture(scope="module")
def seed_data():
    return load_seed()


@pytest.mark.unit
def test_seed_loads(seed_data):
    """YAML parses to dict with expected top-level keys."""
    assert "events" in seed_data
    assert "snapshots" in seed_data
    assert "universe_all_time" in seed_data


@pytest.mark.unit
def test_seed_counts(seed_data):
    """11 events + 12 snapshots + 43 tickers universe."""
    assert len(seed_data["events"]) == EXPECTED_EVENTS
    assert len(seed_data["snapshots"]) == 12
    assert seed_data["universe_all_time"]["count"] == EXPECTED_UNIQUE_TICKERS
    assert len(seed_data["universe_all_time"]["tickers"]) == EXPECTED_UNIQUE_TICKERS


@pytest.mark.unit
def test_snapshots_size_30(seed_data):
    """Every snapshot has exactly 30 tickers, all unique."""
    for snap in seed_data["snapshots"]:
        assert len(snap["tickers"]) == 30, f"{snap['period']}: {len(snap['tickers'])} tickers"
        assert len(set(snap["tickers"])) == 30, f"{snap['period']}: duplicates"


@pytest.mark.unit
def test_reconciliation_passes(seed_data):
    """Events fold correctly into snapshots (11 events -> 12 snapshots)."""
    assert reconcile_yaml(seed_data["events"], seed_data["snapshots"])


@pytest.mark.unit
def test_universe_closed(seed_data):
    """Union of all snapshot tickers equals declared universe."""
    all_seen = set()
    for snap in seed_data["snapshots"]:
        all_seen.update(snap["tickers"])
    declared = set(seed_data["universe_all_time"]["tickers"])
    assert (
        all_seen == declared
    ), f"Extra in declared: {declared - all_seen}, Missing from declared: {all_seen - declared}"


@pytest.mark.unit
def test_rebalance_types_valid(seed_data):
    """Every event has rebalance_type matching schema CHECK constraint."""
    allowed = {"january_review", "july_review", "special"}
    for ev in seed_data["events"]:
        assert (
            ev["rebalance_type"] in allowed
        ), f"event {ev['event_id']}: {ev['rebalance_type']} not in {allowed}"


@pytest.mark.unit
def test_dates_ordered(seed_data):
    """Every event: announced_date <= effective_date (matches chk_dates)."""
    for ev in seed_data["events"]:
        assert (
            ev["announced_date"] <= ev["effective_date"]
        ), f"event {ev['event_id']}: announced {ev['announced_date']} > effective {ev['effective_date']}"


@pytest.mark.unit
def test_no_change_events_have_empty_arrays(seed_data):
    """3 no-change periods (7/2021->1/2022, 7/2023->1/2024, 1/2024->7/2024)."""
    no_change = [
        ev for ev in seed_data["events"] if not ev["tickers_added"] and not ev["tickers_removed"]
    ]
    assert len(no_change) == 3, f"Expected 3 no-change events, got {len(no_change)}"


# ============================================================
# Integration tests (live Neon, skip on CI)
# ============================================================

try:
    from vn_portfolio_frontier.config import get_settings

    _url = get_settings().neon_database_url.get_secret_value()
    NEON_URL = _url if _url and _url.startswith(("postgresql://", "postgres://")) else None
except Exception:
    NEON_URL = None

requires_neon = pytest.mark.skipif(
    not NEON_URL,
    reason="Neon URL not configured; integration tests require live DB",
)


@pytest.fixture(scope="module")
def db_conn():
    import psycopg2

    conn = psycopg2.connect(NEON_URL)
    yield conn
    conn.close()


@pytest.mark.integration
@requires_neon
def test_event_table_exists(db_conn):
    """fundamentals.vn30_membership_event has all 9 expected columns."""
    with db_conn.cursor() as cur:
        cur.execute("""
            SELECT column_name FROM information_schema.columns
            WHERE table_schema = 'fundamentals'
              AND table_name = 'vn30_membership_event'
            """)
        cols = {row[0] for row in cur.fetchall()}
    expected = {
        "event_id",
        "effective_date",
        "announced_date",
        "rebalance_type",
        "tickers_added",
        "tickers_removed",
        "source_ref",
        "notes",
        "logged_at",
    }
    assert expected.issubset(cols), f"Missing columns: {expected - cols}"


@pytest.mark.integration
@requires_neon
def test_membership_snapshot_table_exists(db_conn):
    """fundamentals.vn30_membership_snapshot has (effective_date, ticker) columns."""
    with db_conn.cursor() as cur:
        cur.execute("""
            SELECT column_name FROM information_schema.columns
            WHERE table_schema = 'fundamentals'
              AND table_name = 'vn30_membership_snapshot'
            """)
        cols = {row[0] for row in cur.fetchall()}
    assert cols == {"effective_date", "ticker"}


@pytest.mark.integration
@requires_neon
def test_reject_invalid_rebalance_type(db_conn):
    """chk_rebalance_type CHECK constraint rejects unknown type."""
    with db_conn.cursor() as cur, pytest.raises(Exception, match="chk_rebalance_type"):
        cur.execute("""
                INSERT INTO fundamentals.vn30_membership_event
                (effective_date, announced_date, rebalance_type,
                 tickers_added, tickers_removed, source_ref)
                VALUES ('2027-01-01', '2026-12-15', 'weekly_review',
                        '[]'::jsonb, '[]'::jsonb, 'test-invalid-type')
                """)
    db_conn.rollback()


@pytest.mark.integration
@requires_neon
def test_reject_date_order_violation(db_conn):
    """chk_dates CHECK constraint rejects announced > effective."""
    with db_conn.cursor() as cur, pytest.raises(Exception, match="chk_dates"):
        cur.execute("""
                INSERT INTO fundamentals.vn30_membership_event
                (effective_date, announced_date, rebalance_type,
                 tickers_added, tickers_removed, source_ref)
                VALUES ('2027-01-01', '2027-01-15', 'january_review',
                        '[]'::jsonb, '[]'::jsonb, 'test-bad-dates')
                """)
    db_conn.rollback()


@pytest.mark.integration
@requires_neon
def test_seeded_row_counts(db_conn):
    """After seed script runs: 11 events + 360 constituent + 43 unique tickers."""
    with db_conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM fundamentals.vn30_membership_event")
        n_events = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM fundamentals.vn30_membership_snapshot")
        n_const = cur.fetchone()[0]
        cur.execute("SELECT COUNT(DISTINCT ticker) FROM fundamentals.vn30_membership_snapshot")
        n_tickers = cur.fetchone()[0]
    assert n_events == EXPECTED_EVENTS, f"events={n_events}, expected {EXPECTED_EVENTS}"
    assert (
        n_const == EXPECTED_CONSTITUENT_ROWS
    ), f"constituent={n_const}, expected {EXPECTED_CONSTITUENT_ROWS}"
    assert (
        n_tickers == EXPECTED_UNIQUE_TICKERS
    ), f"unique tickers={n_tickers}, expected {EXPECTED_UNIQUE_TICKERS}"


@pytest.mark.integration
@requires_neon
def test_point_in_time_query(db_conn):
    """VN30 as of 2022-08-01 (kỳ 7/2022): includes VIB, excludes PNJ, still has KDH."""
    with db_conn.cursor() as cur:
        cur.execute("""
            SELECT ticker FROM fundamentals.vn30_membership_snapshot
            WHERE effective_date = '2022-08-01'
            """)
        tickers = {row[0] for row in cur.fetchall()}
    assert len(tickers) == 30, f"Expected 30 tickers at 2022-08-01, got {len(tickers)}"
    assert "VIB" in tickers, "VIB added in 7/2022 should be present"
    assert "PNJ" not in tickers, "PNJ removed in 7/2022 should be absent"
    assert "KDH" in tickers, "KDH not yet removed (1/2023 event) should be present"
