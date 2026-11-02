# ADR-019: Live Prediction Tracking Protocol

**Status:** Accepted
**Date:** 2026-11-02
**Deciders:** Mai Công Trà Giang (Ginny)
**Sprint:** Sprint 12 (continuation)
**Supersedes:** None
**Superseded by:** None

---

## 1. Context

### 1.1 Problem

Project 2 ships three features (F1 Markowitz optimizer, F2 Rebalance simulator, F3 news labeling) that produce *predictions* about Vietnamese equities. All current evaluation is **backtest-only** on historical data (2021-2026). Backtest results suffer from:

- **Overfitting risk**: hyper-parameters tuned on same data used for evaluation
- **Lookahead bias**: subtle leaks from using data not available at prediction time
- **Survivorship bias**: VN30 membership changed 11 times during backtest period
- **Regime bias**: 2021-2026 includes specific macro regimes that may not generalize

For the thesis defense (June 2027), the committee is expected to challenge the external validity of backtest-only evaluation. Live out-of-sample tracking is the gold standard for addressing this.

### 1.2 Statistical requirement

Standard econometric practice for return prediction evaluation (Grinold & Kahn 2000, Harvey & Liu 2015) requires:

| Metric | Minimum N for p<0.05 | Translation to trading days |
|---|---|---|
| Mean Directional Accuracy | ~125 obs | ~6 months |
| Information Coefficient | ~60 obs | ~3 months (weak) |
| Risk-adjusted Alpha | ~125-250 obs | 6-12 months |

Thesis defense window = **June 2027**. Working backward:

| Logger start | N at defense | Statistical power |
|---|---|---|
| 03/11/2026 | ~155 trading days | p<0.05 with margin |
| 01/12/2026 | ~135 trading days | p<0.05 at boundary |
| 01/01/2027 | ~115 trading days | marginal |
| 01/03/2027 | ~75 trading days | Insufficient |

**Implication**: logger must start NOW (02-07/11/2026) to secure defense-grade sample size.

### 1.3 GVHD guidance (30/10/2026 and 02/11/2026)

TS. Nguyễn Đức Anh explicitly asked:
> *"Việc mô hình dự đoán cũng cần có đánh giá kết quả thực tế ví dụ chạy ít nhất dự đoán trong 1 tháng song song và so sánh với kết quả thị trường thực tế cho 1 tháng tới có độ chính xác như thế nào? Giai đoạn tối thiểu cần thiết để chạy kiểm thử độ chính xác là bao nhiêu?"*

GVHD proposed 1-month minimum; this ADR formalizes that 6+ months is required for defense-grade significance (p<0.05).

---

## 2. Decision

Implement a live prediction tracking pipeline consisting of three artefacts:

### 2.1 Data model (migration 015)

Three objects in a new `predictions` schema:

- **`predictions.daily_prediction`** — one row per (date × source × ticker × horizon × model_version). Idempotent via composite UNIQUE constraint.
- **`predictions.daily_actual`** — one row per matured prediction, carrying realised return, directional_match, benchmark_return, and alpha.
- **`predictions.evaluation_rolling`** — materialized view aggregating weekly MDA / IC / Alpha / standard-error per source × model × horizon.

Full DDL in `migrations/015_predictions.sql`.

### 2.2 Logger script

`scripts/log_daily_prediction.py` executes three steps per run:

1. **F1 predictions** — run FrontierService with each of 3 strategies (MinVar, MaxSharpe, RiskParity) over 30 VN30 tickers → 90 weight predictions × 21-day horizon
2. **News predictions** — call ClaudeNewsSummarizer per ticker → variable count × 5-day horizon, action ∈ {BUY, SELL, HOLD}
3. **Evaluate matured** — find predictions where `prediction_date + horizon_days <= today AND no actual exists`, fetch close prices, compute return + alpha + directional_match

The script is **idempotent** (ON CONFLICT DO UPDATE) and **backfill-safe** (`--date YYYY-MM-DD`). Weekend/holiday runs are no-ops.

### 2.3 Scheduling

Windows Task Scheduler task `vn-portfolio-daily-predictions`:
- Trigger: Mon-Fri 16:30 local time (after HOSE close 15:00 + sync_prices buffer)
- Depends on: `vn-portfolio-sync-prices` (60-minute wait)
- Not scheduled while on battery (prevent silent drain)
- Logs to `logs/predictions_YYYYMMDD.log`

Rationale for Windows Task Scheduler over GitHub Actions: same as ADR-018 (vnstock device registration blocker).

---

## 3. Alternatives considered

### 3.1 Manual paper trading in Excel

Rejected. Does not scale (90 F1 + ~5-15 news predictions per day × 155 days = 15k+ records). Prone to typos. No audit trail. No reproducibility.

### 3.2 In-memory logging, flush weekly

Rejected. If laptop crashes or script fails mid-week, lose data. Postgres durability is a free guarantee.

### 3.3 S3 / Google Sheet logging

Rejected. Query patterns (compute MDA by week × source) are relational — materialized view is the right tool. S3/Sheets would require re-building this.

### 3.4 Separate microservice for prediction logging

Rejected as over-engineering for Project 2 scope. Monolithic script with Hexagonal port abstraction (PredictionRepository Protocol) achieves the same loose coupling without operational overhead.

### 3.5 Start logger only at Project 3 kickoff (Dec 2026)

Rejected. Statistical analysis (§1.2) shows this cuts to ~135 obs — at the p<0.05 boundary with no margin for days missed (holidays, bugs, laptop off).

### 3.6 Delay to thesis start (Mar 2027)

Rejected. Only ~75 obs by defense, insufficient for any meaningful inference.

---

## 4. Consequences

### 4.1 Positive

- **Defense-grade empirical evidence**: 155+ observations by thesis defense enables rigorous MDA / IC / Alpha hypothesis testing
- **Thesis contribution #2** (empirical) is now feasible — see `claude/p2_gvhd_feedback_strategic_review.md` §6.3.7
- **Reusable infrastructure**: same pipeline continues through Project 3 and thesis, scaling to agentic chatbot predictions when added
- **Audit trail**: every prediction stamped with `model_version` and `sprint_tag` enables **ablation studies** ("did v2.1 improve MDA vs v2.0?")
- **Honest negative result capability**: if MDA ≤ 55% after 6 months, the result itself is academically valid — "null hypothesis not rejected" is a legitimate thesis conclusion

### 4.2 Negative

- **Daily operational burden**: Windows Task Scheduler must run reliably. Mitigation: idempotent script + backfill protocol.
- **Claude API cost**: ~$2-5/month for news summarization × 7 months = ~$20-35 total. Acceptable for defense value.
- **Laptop uptime dependency**: logger does not run if laptop is off at 16:30. Mitigation: backfill with `--date` CLI next business day.
- **Model drift**: if the model changes mid-tracking (e.g., swap scipy fallback for CVXPY), evaluation metrics mix two regimes. Mitigation: `model_version` field segments evaluation by version.
- **Legal exposure consideration**: Even private logging could be construed as "systematic investment advice" if public. **Mitigation**: logger output stays private to Ginny's local machine + Neon database; not exposed via any UI until positioning is finalized post-ADR-022.

### 4.3 Neutral

- Logger runs even on days with no new predictions worth analyzing (nothing happens → F1 produces baseline weights). Storage cost negligible (Postgres < 1KB per row).
- Backfilled predictions carry `created_at` later than `prediction_date`, which must be documented but is not a bias (Grinold-Kahn: use data available AT prediction time, which is what price_at_prediction captures).

---

## 5. Implementation plan

| Date | Deliverable | Owner |
|---|---|---|
| 02/11/2026 | Draft migration 015 SQL, logger script, Protocol port, unit tests, this ADR | Ginny |
| 03/11/2026 | Apply migration 015 to Neon via DBeaver + verify schema | Ginny |
| 04/11/2026 | Integrate `NeonPredictionRepository` into `AppFactory` + add contract tests | Ginny |
| 05/11/2026 | Dry-run logger: `python scripts/log_daily_prediction.py --today --dry-run` + review output | Ginny |
| 05/11/2026 | **First real run (backfilled 03-04/11)**: `python scripts/log_daily_prediction.py --date 2026-11-03` | Ginny |
| 06/11/2026 | Setup Windows Task Scheduler + verify first automatic run after HOSE close | Ginny |
| 07/11/2026 | **MILESTONE: first fully automatic daily log recorded** | — |
| 15/11/2026 | 1-week review: verify MDA/IC compute, no missing days, schema stable | Ginny |
| 30/11/2026 | 1-month checkpoint: ~20 obs, early directional read on signal quality | Ginny |
| 01/01/2027 | 2-month checkpoint: ~40 obs, assess whether model_version swap is warranted | Ginny |
| 15/06/2027 | Final data pull for thesis chapter — 155+ obs | Ginny |

---

## 6. Risks and monitoring

### 6.1 Risk register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Laptop off at 16:30 | Medium | Low | Backfill protocol tested, idempotent CLI |
| Script crashes mid-run | Low | Low | Partial results persist (per-record transaction) |
| Claude API quota exceeded | Low | Low | Rate limit check + fallback to F1-only logging |
| Neon free tier (0.5GB) exceeded | Very low | Medium | 15k rows × 1KB avg = 15MB over 155 days, well under limit |
| vnstock price fetch fails | Medium | Low | Script skips affected ticker, logs error, continues |
| **MDA < 55% after 6 months** | Medium-high | Low (academically) | Publish as negative result — still a valid thesis contribution |
| Model version changes mid-tracking | High (deliberate) | Low | `model_version` field segments evaluation per model |

### 6.2 Weekly health check queries

```sql
-- 1. Did logger run every weekday?
SELECT prediction_date, COUNT(*) AS n_predictions
FROM predictions.daily_prediction
WHERE prediction_date >= CURRENT_DATE - INTERVAL '14 days'
GROUP BY prediction_date
ORDER BY prediction_date DESC;
-- Expect ~102 rows per weekday (90 F1 + ~12 news)

-- 2. Are matured predictions being evaluated?
SELECT
    DATE_TRUNC('week', prediction_date) AS week,
    COUNT(DISTINCT dp.prediction_id)   AS predicted,
    COUNT(DISTINCT da.prediction_id)   AS evaluated,
    ROUND(100.0 * COUNT(DISTINCT da.prediction_id) /
          NULLIF(COUNT(DISTINCT dp.prediction_id), 0), 1) AS pct_evaluated
FROM predictions.daily_prediction dp
LEFT JOIN predictions.daily_actual da ON dp.prediction_id = da.prediction_id
WHERE dp.prediction_date < CURRENT_DATE - INTERVAL '30 days'
GROUP BY week
ORDER BY week DESC;
-- Expect pct_evaluated → 100% once horizon passed

-- 3. Rolling MDA by source
SELECT * FROM predictions.evaluation_rolling
WHERE week_starting >= CURRENT_DATE - INTERVAL '8 weeks'
ORDER BY prediction_source, week_starting DESC;
```

---

## 7. References

- Grinold, R. C., & Kahn, R. N. (2000). *Active Portfolio Management: A Quantitative Approach for Producing Superior Returns and Controlling Risk* (2nd ed.). McGraw-Hill. [Information Coefficient methodology]
- Harvey, C. R., & Liu, Y. (2015). "Backtesting." *The Journal of Portfolio Management*, 42(1), 13-28. [Multiple testing correction]
- Perold, A. F. (1988). "The Implementation Shortfall: Paper versus Reality." *Journal of Portfolio Management*. [Live vs backtest divergence]
- ADR-015: Hexagonal Architecture (Port abstraction used here)
- ADR-017: scipy SLSQP fallback (model_version tracking rationale)
- ADR-018: Windows Task Scheduler (scheduling precedent)
- `claude/p2_gvhd_feedback_strategic_review.md` §6.3.5 (roadmap integration)
- `claude/p2_action_pack_02112026.md` §1 (implementation details)

---

## 8. Linked artefacts

- `migrations/015_predictions.sql` — schema DDL
- `scripts/log_daily_prediction.py` — logger entrypoint
- `src/vn_portfolio_frontier/infrastructure/neon/predictions_repo.py` — Neon adapter + Protocol port + in-memory fake
- `tests/unit/test_log_daily_prediction.py` — unit test suite
- `scripts/log_predictions_daily.bat` — Windows Task Scheduler wrapper
