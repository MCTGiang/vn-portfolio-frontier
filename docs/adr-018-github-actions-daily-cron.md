# ADR-018: GitHub Actions daily cron for data refresh

**Status:** PARTIALLY IMPLEMENTED (2026-10-27) — blocked by vnstock Silver tier device registration

Infrastructure shipped (Migration 014 + scripts/audit_log.py + workflow YAML) but
cron trigger disabled. Workflow callable via workflow_dispatch for future testing
when blocker resolves. See "Known blockers" section below.

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
- ~Requires VNSTOCK auth to be stable (currently blocked, see ADR-017).~ **RESOLVED 2026-10-26**: vnstock package upgrade 5.0.1 -> 5.2.0 (released 2026-10-23) restored auth. Server returned InternalError when client version pre-dated server expectations. Status now: `tier: silver, authenticated: True, expires_at: 2026-12-30`.
- GitHub Actions free tier limit: 2000 minutes/month (daily job ~5 min = 150 min/month, well within).
- Timezone drift: GitHub cron uses UTC; need to update if ICT changes (unlikely for VN).

## Implementation plan (Day 12)

- [ ] T1: Add `scripts/sync_prices.py --today` + `scripts/sync_benchmarks.py --today` CLI flags (verify exist).
- [ ] T2: Migration 014: `audit.data_refresh_run` table (run_id, started_at, finished_at, status, rows_fetched, error_message).
- [ ] T3: Create `.github/workflows/daily-data-refresh.yml`.
- [ ] T4: Add GitHub secrets via `gh api repos/MCTGiang/vn-portfolio-frontier/actions/secrets`.
- [ ] T5: Manual trigger test (workflow_dispatch) to verify.
- [ ] T6: Monitor first 3 scheduled runs.
- [x] ~BLOCKED: VNSTOCK API key auth resolution (parallel ticket vnstocks.com).~ **RESOLVED 2026-10-26** via vnstock upgrade 5.2.0.

## Known blockers

### Device registration (discovered 2026-10-27 smoke test run #40446954626)

Vnstock Silver tier binds API key to specific `device_id` (one device per
subscription). Local machine registered during initial `vnstock.login()` call
creates device_id entry on vnstocks.com backend. GitHub Actions runner is
ephemeral (new device_id each run) -> `"Thiet bi chua duoc dang ky"` (Device
not registered) error on all `vnstock.*` calls.

**Impact:** Automated cron data refresh via GitHub Actions NOT POSSIBLE on
Silver tier. Cron trigger commented out in workflow YAML; workflow_dispatch
kept for future testing.

**Workarounds considered:**

1. **Golden tier upgrade** (~$30-60/month): includes vnstock_pipeline package
   designed for CI/CD multi-device. Rejected for Project 2 scope - cost
   outside thesis budget. Reconsider for thesis platform Phase 3+.
2. **Dedicated cloud VM** ($4-10/month): fixed-IP VM registered once as the
   "device". Rejected: setup complexity + ongoing cost not justified for
   thesis timeline (defense 2026-11-17).
3. **Manual weekly sync** (current workaround): Ginny runs
   `python scripts/sync_prices.py --today` + `python scripts/sync_benchmarks.py
   --today` from local machine every Monday + Thursday. Audit log works
   when sourced as `local_dev`. Sufficient for thesis defense data freshness
   requirements.
4. **GitHub self-hosted runner on Ginny machine**: runner stays on same
   device, inherits registered device_id. Rejected: machine must stay on,
   adds attack surface, moot given option 3.

**Decision:** Option 3 (manual weekly sync) adopted for Project 2 /
thesis defense phase. Infrastructure (Migration 014 + audit helper + workflow
YAML) kept for future Phase 3+ when Golden tier is justified.

## References

- Related ADR: [ADR-007 Prefect deferred (SUPERSEDED)](./architecture.md#adr-007), [ADR-017 scipy-based FrontierOptimizer](./adr-017-frontier-optimizer-scipy.md)
- GitHub Actions cron syntax: https://docs.github.com/en/actions/writing-workflows/choosing-when-your-workflow-runs/events-that-trigger-workflows#schedule
- Day 11 memory for context: data integrity bug observed when sim ran on dates beyond DB max.
