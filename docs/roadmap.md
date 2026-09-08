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
| **1. Repo foundation** | 1–2 | 27/08 – 06/09 | Repo setup, README bilingual, Python scaffold, CI matrix, OSS templates, docs seed | This repo, CI green |
| **2. Neon PostgreSQL + schema** | 3–4 | 07/09 – 20/09 | Neon setup, schema for prices/fundamentals/news, DBeaver + psycopg2, SQLite migration | Live DB with 3 schemas |
| **3. Prefect orchestration** | 5–6 | 21/09 – 04/10 | Prefect flows in Docker, daily/weekly schedules, retry logic | Scheduled pipeline running |
| **4. dbt transformations** | 7–8 | 05/10 – 18/10 | dbt models for feature engineering, materialization strategy | Feature tables in Neon |
| **5. Efficient frontier + rebalancing** | 9–10 | 19/10 – 01/11 | Extend Project 1 optimizer, frontier viz, rebalancing sim with transaction costs, Streamlit UI | Interactive frontier UI |
| **6. PhoBERT / RAG sentiment** | 11–12 | 02/11 – 15/11 | News scrape (VnExpress, CafeF, VietStock), LLM-labeled dataset, fine-tune or RAG, integration | Sentiment output for VN30 |
| **7. Buffer + submission** | 12 (tail) | 16/11 – 17/11 | Final QA, tag v2.0.0, benchmark documentation | Submission-ready release |

## Decision milestones

| Decision | Deadline | Status | ADR |
|----------|----------|--------|-----|
| Database (Neon Cloud) | 2026-08-26 | ✅ Locked | [ADR-002](./architecture.md#adr-002-neon-cloud-postgresql-as-primary-database) |
| License (MIT) | 2026-09-07 | ✅ Locked | [ADR-003](./architecture.md#adr-003-mit-license) |
| Docker scope (apps only) | 2026-08-26 | ✅ Locked | [ADR-005](./architecture.md#adr-005-docker-containerizes-applications-only-not-the-database) |
| Sentiment framing (structured extraction) | 2026-08-26 | ✅ Locked | [ADR-006](./architecture.md#adr-006-phobert-sentiment-as-structured-information-extraction-not-predicts-returns) |
| **Prefect vs Airflow** | **2026-09-15** | 🚧 Open | [ADR-007](./architecture.md#adr-007-open-prefect-vs-apache-airflow-for-workflow-orchestration) |
| **PhoBERT vs RAG** | **2026-10-20** | 🚧 Open | [ADR-008](./architecture.md#adr-008-open-phobert-fine-tune-vs-rag-for-sentiment-extraction) |

## Live sprint tracker

Interactive Gantt + cadence dashboard (private artifact): visible in the maintainer's Claude workspace. Contact maintainer for view access.

## Current status

**As of 2026-09-08:** Phase 1 near complete. 3/4 commits done (bootstrap, Python scaffold with pytest, CI matrix + OSS templates). This docs commit is the 4th and last of Phase 1. Phase 2 starts immediately after: Neon setup and schema design (`prices`, `fundamentals`, `news`).

## Related documentation

- [`architecture.md`](./architecture.md) — Architecture Decision Records
- [`setup.md`](./setup.md) — Development environment setup
- [`../CONTRIBUTING.md`](../CONTRIBUTING.md) — Contribution workflow
- [`../README.md`](../README.md) — Project overview
- [Project 1 roadmap](https://github.com/MCTGiang/vn-portfolio-optimizer/blob/main/docs/roadmap.md) — Source of truth for 4-phase HUST journey
