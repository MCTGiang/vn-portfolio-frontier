# ADR-018: GitHub Actions daily cron for data refresh

**Status:** Proposed — placeholder for Day 12 implementation

## Context

Project 2 ingests daily VN30 OHLCV + VN Government Bond yield + SBV policy rate data from `vnstock` Sponsor Silver API into Neon Postgres (singapore region). As of Day 11, data ingestion runs manually via `scripts/sync_prices.py` and `scripts/sync_benchmarks.py` executed on Ginny's local Windows machine when she notices the Streamlit UI shows stale data.

Problems with manual sync:
- Defense day risk: if forgotten the night before, demo shows stale data (last observed: Day 11 shipped with data to 2026-10-16 while real-world was 2026-10-20).
- No audit trail of sync runs (no log table, no success/failure history).
- Vacation blocker: 1-week absence = 1-week data gap.

End-user context (defense story): "This system runs continuously in production, data auto-refreshes daily after HSX close."

## Decision (PENDING — Day 12 scope)

**Set up GitHub Actions scheduled workflow to run data sync daily on weekdays at 17:00 ICT (post HSX close):**

- Workflow file: `.github/workflows/daily-data-refresh.yml`
- Trigger: `schedule: - cron: "0 10 * * 1-5"` (10:00 UTC = 17:00 ICT, Mon-Fri)
- Steps:
  1. Checkout + Python 3.13 setup
  2. Install dependencies (requirements.txt + Sponsor Silver vnstock)
  3. Run `scripts/sync_prices.py --today` for VN30 universe
  4. Run `scripts/sync_benchmarks.py --today` for Rf series
  5. Log results to Neon audit table (migration 014 PENDING)
  6. On failure: send Slack/Discord webhook (TBD — defer post-defense)

Secrets required (GitHub Actions):
- `NEON_DATABASE_URL` — DB connection string
- `VNSTOCK_API_KEY` — Sponsor Silver auth (PENDING resolution of auth issue, see ADR-017)

## Alternatives considered

1. **Prefect/Airflow** — Overkill for 2 jobs. ADR-007 superseded this direction already.
2. **Neon's own scheduled jobs** — Not available on free tier.
3. **cron on Ginny's laptop** — Laptop sleep + Windows Task Scheduler reliability issues.
4. **AWS Lambda scheduled** — Additional AWS account complexity, costs money ($0-$2/month).

## Consequences

**Positive:**
- Zero-touch daily refresh after setup.
- Audit trail via GitHub Actions logs (90-day retention) + Neon audit table (unlimited).
- Reproducible: same workflow runs on same codebase, no "works on my machine".
- Defense story: "Production-grade automation".

**Negative:**
- Requires VNSTOCK auth to be stable (currently blocked, see ADR-017).
- GitHub Actions free tier limit: 2000 minutes/month (daily job ~5 min = 150 min/month, well within).
- Timezone drift: GitHub cron uses UTC; need to update if ICT changes (unlikely for VN).

## Implementation plan (Day 12)

- [ ] T1: Add `scripts/sync_prices.py --today` + `scripts/sync_benchmarks.py --today` CLI flags (verify exist).
- [ ] T2: Migration 014: `audit.data_refresh_run` table (run_id, started_at, finished_at, status, rows_fetched, error_message).
- [ ] T3: Create `.github/workflows/daily-data-refresh.yml`.
- [ ] T4: Add GitHub secrets via `gh api repos/MCTGiang/vn-portfolio-frontier/actions/secrets`.
- [ ] T5: Manual trigger test (workflow_dispatch) to verify.
- [ ] T6: Monitor first 3 scheduled runs.
- [ ] BLOCKED: VNSTOCK API key auth resolution (parallel ticket vnstocks.com).

## References

- Related ADR: [ADR-007 Prefect deferred (SUPERSEDED)](./architecture.md#adr-007), [ADR-017 scipy-based FrontierOptimizer](./adr-017-frontier-optimizer-scipy.md)
- GitHub Actions cron syntax: https://docs.github.com/en/actions/writing-workflows/choosing-when-your-workflow-runs/events-that-trigger-workflows#schedule
- Day 11 memory for context: data integrity bug observed when sim ran on dates beyond DB max.
