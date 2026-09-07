# vn-portfolio-frontier

> Efficient Frontier extension with auto-rebalancing and PhoBERT sentiment signals for Vietnamese equity portfolios.

[![Python](https://img.shields.io/badge/python-3.11%2B-blue)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](./LICENSE)
[![Status: In Development](https://img.shields.io/badge/status-in%20development-orange)]()

**Successor to** [`vn-portfolio-optimizer`](https://github.com/MCTGiang/vn-portfolio-optimizer) — this project extends the Modern Portfolio Theory (MPT) minimum-variance optimizer with three new capabilities: efficient frontier visualization across risk levels, automated rebalancing simulations with transaction costs, and structured sentiment extraction from Vietnamese financial news using PhoBERT.

**Vietnamese README:** [README.vi.md](./README.vi.md)

---

## Overview

Vietnamese retail investors currently have limited access to institutional-grade quantitative portfolio tools that account for local market microstructure, transaction costs, and news-driven volatility. This project builds on Project 1's MPT foundation to deliver:

1. **Full efficient frontier navigation** — Beyond the minimum-variance portfolio, select any point on the risk-return curve.
2. **Realistic rebalancing simulation** — Periodic reoptimization with turnover constraints, transaction cost drag, and drift tracking.
3. **News-aware signals** — Structured information extraction from Vietnamese financial press (event type, ticker, sentiment magnitude, entities), not naive "sentiment predicts returns" claims.

Target audience: Vietnamese retail investors and quantitative researchers working with VN30 constituents.

## Features

Status legend: ✅ Shipped · 🚧 In progress · 📋 Planned

- 📋 **Efficient Frontier Visualization** — Interactive Streamlit UI to select portfolios across the full risk-return curve.
- 📋 **Auto-Rebalancing Simulator** — Configurable rebalance frequency, transaction cost model, and turnover limits.
- 📋 **Vietnamese Financial Sentiment** — PhoBERT (or RAG-based) structured extraction from VnExpress, CafeF, VietStock news.
- 📋 **Fundamentals Integration** — Second heterogeneous data source (fundamentals) alongside VN30 prices.

## Tech Stack

| Layer | Choice | Rationale |
|-------|--------|-----------|
| Language | Python 3.11+ | pandas 3.0+ requires 3.11+; drops Python 3.10 support |
| Database | Neon Cloud PostgreSQL (Singapore) | 8 GB RAM constraint on dev machine; zero-infra managed service; migration path to AWS RDS |
| Orchestration | Prefect (planned) or Airflow — decision due 2026-09-15 | Lightweight Python-native flows |
| Transformations | dbt | Version-controlled SQL feature engineering |
| Modeling | scipy (SLSQP), NumPy, pandas | Same MPT foundation as Project 1 |
| NLP | PhoBERT (VinAI) — fine-tune or RAG, decision due 2026-10-20 | Vietnamese pretrained; structured extraction task |
| Frontend | Streamlit | Continuity from Project 1; Metabase as stretch goal |
| Containerization | Docker (apps only, not DB) | Isolate Prefect + Streamlit; DB stays managed |
| CI/CD | GitHub Actions | pytest matrix, black + ruff enforcement |

## Getting Started

> ⚠️ Project is in early scaffolding (Phase 1: repo foundation). Instructions below will fill in as components land.

### Prerequisites

- Python 3.11 or later
- Git
- Docker Desktop (for local Prefect + Streamlit containers, Phase 3+)
- A [Neon Cloud](https://neon.tech) account with a Postgres project in region `ap-southeast-1` (Singapore)
- (Recommended) [DBeaver](https://dbeaver.io/) or similar Postgres GUI for schema inspection

### Installation

```bash
git clone https://github.com/MCTGiang/vn-portfolio-frontier.git
cd vn-portfolio-frontier

# Package install (once pyproject.toml lands in Commit 2)
# pip install -e ".[dev]"
```

### Configuration

Copy `.env.example` to `.env` and fill in your Neon connection string:

```bash
cp .env.example .env
# Then edit .env with your actual credentials
```

**Never commit `.env`** — it is git-ignored.

## Project Structure

```
vn-portfolio-frontier/
├── .github/              # Issue templates, PR template, CI workflows
├── docs/                 # Architecture ADRs, roadmap, setup guide
├── src/                  # Package source
│   └── vn_portfolio_frontier/
├── tests/                # pytest suite
├── notebooks/            # Exploratory + canonical analysis notebooks
├── .env.example          # Configuration template
├── LICENSE               # MIT
├── pyproject.toml        # Package config, black + ruff (Commit 2)
├── README.md             # This file
└── README.vi.md          # Vietnamese version
```

## Data Sources

| Source | Coverage | Frequency | Access |
|--------|----------|-----------|--------|
| VN30 prices | 29 tickers, 2021-present | Daily OHLCV | vnstock (primary) + yfinance (fallback) — inherited from Project 1 |
| Fundamentals | VN30 constituents | Quarterly | TBD — second heterogeneous data source (Phase 2 decision) |
| Financial news | VnExpress, CafeF, VietStock | Daily scrape | HTTP fetch + parse; Phase 6 |

## Roadmap

Detailed roadmap will land in [`docs/roadmap.md`](./docs/roadmap.md) (Commit 4). Summary:

- **Phase 1 (current):** Repo foundation, README, CI skeleton
- **Phase 2:** Neon setup + schema design (VN30 prices, fundamentals, news)
- **Phase 3:** Prefect workflow orchestration in Docker
- **Phase 4:** dbt transformations
- **Phase 5:** Efficient frontier + rebalancing
- **Phase 6:** PhoBERT / RAG sentiment
- **Submission:** 2026-11-17

## Related Projects

- [`vn-portfolio-optimizer`](https://github.com/MCTGiang/vn-portfolio-optimizer) (Project 1) — MPT minimum-variance optimizer, achieved **25.9% volatility reduction** vs equal-weighted baseline on VN30 (v1.0.0, 2026-08-15).

## Contributing

Coming soon — `CONTRIBUTING.md` will land alongside the CI workflow (Commit 3).

## License

MIT — see [`LICENSE`](./LICENSE).

## Acknowledgments

- **VinAI Research** for [PhoBERT](https://github.com/VinAIResearch/PhoBERT), the Vietnamese BERT model.
- **Neon** for managed Postgres with a free tier that makes this project feasible on an 8 GB RAM development machine.
- **Bret Fisher** for the Docker Mastery course guiding the Phase 3+ Docker work.

---

Built as part of the HUST IT Engineering second-bachelor's program (2025-2027). Submitting **2026-11-17**.
