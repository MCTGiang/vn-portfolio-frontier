# Roadmap

`vn-portfolio-frontier` is **Project 2** of a 4-phase HUST second-bachelor's programme running from August 2026 through June 2027. The full 4-phase roadmap lives in the predecessor project's [`docs/roadmap.md`](https://github.com/MCTGiang/vn-portfolio-optimizer/blob/main/docs/roadmap.md) — this file zooms into Project 2 details and links back for context.

## The 4-phase picture

| # | Project | Timeline | Deliverable |
|---|---------|----------|-------------|
| 1 | [`vn-portfolio-optimizer`](https://github.com/MCTGiang/vn-portfolio-optimizer) | Done · v1.0.0 · 2026-08-15 | MPT minimum-variance optimizer, VN30. **25.9% volatility reduction** vs equal-weighted baseline. |
| 2 | **`vn-portfolio-frontier`** (this repo) | **27/08 – 17/11/2026** | Efficient frontier + auto-rebalancing + PhoBERT sentiment |
| 3 | TBD | 18/11/2026 – 19/01/2027 | Ensemble ML forecasting (LSTM + XGBoost + Random Forest), VaR, Monte Carlo |
| 4 | Thesis platform | Mar – Jun 2027 | Microservices integration of P1+P2+P3, real-time streaming, SSI FastConnect, AWS deploy |

## Project 2 phase breakdown

Deadline for submission: **2026-11-17** (Tuesday). Working cadence: ~2 h weekday + 3 h Saturday (Bret Fisher Docker Mastery + review) + 3 h Sunday flex buffer.

| Phase | Weeks | Dates | Scope | Key deliverable |
|-------|-------|-------|-------|-----------------|
| **1. Repo foundation** | 1-2 | 27/08 - 06/09 | Repo setup, bilingual README, Python scaffold, CI matrix, OSS templates, 8 ADRs seed | Green CI, ADR-001 to ADR-008 |
| **2. Neon + 3-domain schema** | 3-4 | 07/09 - 20/09 | Neon connection helpers, idempotent migration runner, schemas for `prices` / `fundamentals` / `news_sentiment` (6 tables total) | Live DB, 23 tests, coverage 90% |
| **3. Security + config + ADR series** | 5 | 21/09 - 28/09 | Commits 9a-9d: SECURITY/CODEOWNERS/Dependabot/pre-commit/pip-audit, Pydantic Settings config, ADR-009 to ADR-012, title + spec lock, simulation schema (migration 005) | 5-layer security posture, config.py, 12 ADRs |
| **4. Data population** | 6 | 29/09 - 05/10 | Hybrid SQLite -> Neon migration + fresh vnstock delta fetch for fundamentals + prices | ~40k price rows + 24-quarter fundamentals |
| **5. Auto-rebalancing (Feature 2)** | 7-8 | 06/10 - 19/10 | Cost calculator (user-input `brokerage_pct` + tax + MI), `threshold_band` + `periodic` strategies, sensitivity sweep CLI, persistence to `simulation.rebalance_run` (per ADR-012) | Working simulator + Sharpe-vs-cost curve |
| **6. PhoBERT sentiment (Feature 3)** | 9-11 | 20/10 - 08/11 | Data labeling (LLM-assisted ~500-1000 samples), fine-tune on Colab Pro, integration pipeline, RAG comparison baseline. **Milestone gates**: labeled dataset (end week 9); fine-tune convergence (end week 10 - pivot RAG-only if NO). | End-to-end sentiment extraction on VN30 |
| **7. Report + submission** | 12 | 09/11 - 17/11 | Report finalization, video demo 3-5 min, defense prep. Chapters F1+F2 drafted in week 8; F3 drafted in week 11. | Submission-ready v2.0.0 |

## Decision milestones

| Decision | Deadline | Status | ADR |
|----------|----------|--------|-----|
| Database (Neon Cloud) | 2026-08-26 | Locked | [ADR-002](./architecture.md#adr-002-neon-cloud-postgresql-as-primary-database) |
| License (MIT) | 2026-09-07 | Locked | [ADR-003](./architecture.md#adr-003-mit-license) |
| Docker scope (apps only) | 2026-08-26 | Locked | [ADR-005](./architecture.md#adr-005-docker-containerizes-applications-only-not-the-database) |
| Sentiment framing (structured extraction) | 2026-08-26 | Locked | [ADR-006](./architecture.md#adr-006-phobert-sentiment-as-structured-information-extraction-not-predicts-returns) |
| Feature-driven schema methodology | 2026-09-08 | Locked | [ADR-009](./architecture.md#adr-009-feature-driven-schema-evaluation-for-project-2-domains) |
| Security posture + version pinning | 2026-09-22 | Locked | [ADR-010](./architecture.md#adr-010-security-posture-and-version-pinning-discipline) |
| VN news sources (VnExpress/CafeF/VietStock) | 2026-09-22 | Locked | [ADR-011](./architecture.md#adr-011-vietnamese-financial-news-sources-for-sentiment-extraction) |
| Rebalancing cost model (user-parameterized) | 2026-09-21 | Locked | [ADR-012](./architecture.md#adr-012-auto-rebalancing-transaction-cost-model--user-parameterized-cost-agnostic-framework) |
| **Prefect vs Airflow** | 2026-09-15 (passed) | Reassess - may defer to thesis phase | [ADR-007](./architecture.md#adr-007-open-prefect-vs-apache-airflow-for-workflow-orchestration) |
| **PhoBERT vs RAG** | **2026-10-20** | Open (milestone gate end of week 10) | [ADR-008](./architecture.md#adr-008-open-phobert-fine-tune-vs-rag-for-sentiment-extraction) |

## Live sprint tracker

Interactive Gantt + cadence dashboard (private artifact): visible in the maintainer's Claude workspace. Contact maintainer for view access.

## Current status

**As of 2026-09-22:** Phases 1-2 complete + Phase 3 in progress. Repository at 11 linear commits on `main` (Commits 1-8 = foundation + schemas; Commits 9a-9c = security posture, config abstraction, ADR docs). 27/27 tests pass, coverage 95%. Remaining in Phase 3 (Sprint 9): Commit 9d (title + spec lock - this commit), Task 4b (migration 005 simulation schema), Task 5 kickoff (data population). Colab Pro subscribe still pending (owner action).

## Related documentation

- [`architecture.md`](./architecture.md) — Architecture Decision Records
- [`setup.md`](./setup.md) — Development environment setup
- [`../CONTRIBUTING.md`](../CONTRIBUTING.md) — Contribution workflow
- [`../README.md`](../README.md) — Project overview
- [Project 1 roadmap](https://github.com/MCTGiang/vn-portfolio-optimizer/blob/main/docs/roadmap.md) — Source of truth for the 4-phase HUST journey
