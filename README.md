# vn-portfolio-frontier

> **Research platform** for Markowitz portfolio optimization, auto-rebalancing simulation, and structured financial news signal extraction on Vietnamese VN30 equities. Foundation for a long-term AI investment advisor developed as part of an academic research track.

[![Python](https://img.shields.io/badge/python-3.11%2B-blue)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](./LICENSE)
[![Status: Active Development](https://img.shields.io/badge/status-active%20development-green)]()
[![Academic Use](https://img.shields.io/badge/use-academic%20%2F%20educational-blueviolet)]()

> ⚠️ **Educational and research use only.** This platform is a university research project. It is **not** a licensed investment advisory service under Article 72 of Vietnam Securities Law (54/2019/QH14). It does not provide buy/sell/hold recommendations for specific securities. Any investment decisions are solely the responsibility of the user and should be reviewed with a licensed professional advisor.

**Vietnamese README:** [README.vi.md](./README.vi.md)

---

## Overview

Vietnamese retail investors face three recurring quantitative questions that institutional-grade tools answer but educational-grade public tools often do not:

1. **Allocation** — What portfolio weights optimize the risk-return trade-off across a candidate ticker set?
2. **Rebalancing** — When and how should allocations be adjusted to maintain target risk, net of Vietnam-specific transaction costs?
3. **Information signal** — How can published financial news be transformed into structured, auditable signals rather than opaque sentiment scores?

This project builds three foundational components for an academic research track addressing these questions, with explicit scoping for the Vietnamese market context (HOSE lot size rules, Decree 111/2013 transaction tax, VN30 index membership evolution, SBV benchmark rates).

Target users: **academic researchers, quantitative finance students, and self-directed investors seeking educational tooling to understand portfolio theory and news-driven market dynamics**. The platform is positioned as a research artifact and educational tool — not as a commercial advisory service.

## Project context

This is **Project 2** in a four-stage research track leading to a bachelor's thesis in Information Technology Engineering at Hanoi University of Science and Technology (HUST), 2025-2027:

| Stage | Timeline | Scope |
|---|---|---|
| Project 1 — MVP | 04-05/2025 | Minimum-variance optimizer on 29 VN30 tickers, SQLite, scipy baseline ([v1.0.0 released](https://github.com/MCTGiang/vn-portfolio-optimizer)) |
| **Project 2 — Foundation (this repo)** | 09-11/2026 | Full Markowitz efficient frontier + auto-rebalancing + structured news signal corpus + Hexagonal architecture |
| Project 3 — Platform | 12/2026-02/2027 | FastAPI backend, 3-tier auth, Agentic RAG prototype, live prediction tracker |
| Bachelor's Thesis — Agentic AI Advisor | 03-06/2027 | Full-stack educational advisor with usability study and empirical evaluation |

Project 2 is **not** an end-to-end user-facing product. It is a validated research foundation whose outputs (optimization service, rebalance simulator, labeled news corpus) feed the subsequent stages.

## Recent milestones

- `v2.0-sprint12-adr019` (02/11/2026) — Live Prediction Tracking (ADR-019) production go-live
- `v2.0-phase2-ux` (06/11/2026) — Phase 2 UX linear workflow refactor (Bước 1 → 2 → 3 stepper)
- Phase C sentiment audit completed (09/11/2026) — 200 samples reviewed, Sentiment Cohen's κ = 0.967 ("almost perfect"), 2/4 hypothesis pass

---

## Features

Status legend: ✅ Shipped · 🚧 In progress · 📋 Planned (next stage)

### Project 2 (this repository)

- ✅ **Efficient Frontier (F1)** — Full Markowitz efficient frontier with 3 reference portfolios (Minimum Variance, Max Sharpe, Risk Parity) and 20-point curve for user-chosen risk tolerance. Implemented via `scipy.optimize` SLSQP (see ADR-017).
- ✅ **Auto-Rebalancing Simulator (F2)** — Three rebalancing strategies (Threshold Band 500 bps default, Calendar Monthly, Fixed Window 90-day) with Vietnam-specific cost model (TT 111/2013 seller tax, HSX lot size per QĐ 496, user-parameterized broker fee). Strategy Pattern (GoF) enables extensibility without modifying backtest engine (ADR-015).
- 🚧 **Structured News Signal Corpus (F3)** — Labeled dataset of 699 Vietnamese financial news articles with 11-field schema (`ticker`, `event_type`, `sentiment`, `magnitude`, `entities`, ...) extracted via Claude Sonnet 5-5 teacher model. **Phase C audit** (200 stratified samples, independent human review) completed 09/11/2026: Sentiment Cohen's κ = 0.967 ("almost perfect" per Landis-Koch 1977), Relevance accuracy = 96.5%. Positioned as evidence base for Agentic Retrieval-Augmented Generation (RAG) in later stages, not as a standalone sentiment classifier.
- ✅ **Live Prediction Tracking** — Daily prediction logger (ADR-019) running since 02/11/2026 to accumulate 155+ trading observations for empirical evaluation in the thesis stage.
- ✅ **Export Reports** — Download backtest results as PDF (executive summary) or Excel (4 sheets: Config, KPIs, Decisions, DailyValues) for stakeholder sharing and record-keeping. Vietnamese font support via platform-aware fallback (Arial Windows → DejaVu Linux → Helvetica).
- ✅ **Hexagonal Architecture** — Four-layer separation (Domain / Application / Infrastructure / Interface) per Cockburn (2005) with Protocol-based ports. Validated by two live case studies: scipy fallback when `vnstock_quant` auth lock (ADR-017), and Task Scheduler bypass for `vnstock` device-lock (ADR-018).

### Next-stage preview (not implemented in Project 2)

- 📋 **FastAPI REST backend** (Project 3) — Expose F1 and F2 as REST endpoints for Agentic chatbot tool consumption.
- 📋 **Agentic AI advisor** (Thesis) — LangGraph orchestration with 5-7 tools, hybrid RAG retrieval over labeled news corpus, 3-tier authentication (educational positioning, no live advisory sales).
- 📋 **Empirical evaluation report** (Thesis) — MDA, IC, Jensen's Alpha, Sharpe analysis from 7+ months of live prediction data.

## Tech Stack

| Layer | Choice | Rationale |
|-------|--------|-----------|
| Language | Python 3.11-3.13 (matrix tested in CI) | pandas 3.0+ requires 3.11+; matrix tests detect version-specific regressions |
| Database | Neon Cloud PostgreSQL (Singapore) | Managed service, 0.5 GB free tier sufficient for ~215K rows at Project 2 scope; branching enables migration experimentation |
| Portfolio optimization | scipy SLSQP (ADR-017) | Industry standard (LEAN, zipline, backtrader); vendor-neutral; deterministic; mock-friendly for tests |
| News corpus labeling | Claude Sonnet 5-5 teacher model | Native Vietnamese quality; reliable structured JSON output; 11-field schema (ADR-006) |
| Information retrieval architecture | Agentic RAG (Project 3+) | Flexibility over fine-tuned classifier at corpus size <1000 (ADR-008 resolution 02/11/2026) |
| Frontend | Streamlit (internal / admin), Next.js planned (Project 3+ end-user) | Streamlit for research prototype; Next.js for Agentic chatbot UI |
| Orchestration | Windows Task Scheduler (ADR-018) | Required by vnstock Silver tier device-lock; GitHub Actions cron infeasible |
| CI/CD | GitHub Actions matrix (Python 3.11/3.12/3.13) + pip-audit | 1.4 min typical run; 5-job pipeline (lint + 3 Python versions + security scan) |

## Getting Started

### Prerequisites

- Python 3.11 or later
- Git
- A [Neon Cloud](https://neon.tech) account with a Postgres project in region `ap-southeast-1`
- (Recommended) [DBeaver](https://dbeaver.io/) or similar Postgres GUI for schema inspection
- A vnstock Silver tier subscription if full data access is required (free tier works for exploration with rate limits)

### Installation

```bash
git clone https://github.com/MCTGiang/vn-portfolio-frontier.git
cd vn-portfolio-frontier

python -m venv .venv
source .venv/Scripts/activate  # Windows Git Bash
# or: source .venv/bin/activate  # Linux/macOS

pip install -e ".[dev,data]"

cp .env.example .env
# Edit .env with your Neon connection string and vnstock API key
```

**Never commit `.env`** — it is git-ignored.

### Running the Streamlit research prototype

```bash
streamlit run src/vn_portfolio_frontier/interface/streamlit/app.py
```

## Project Structure

```
vn-portfolio-frontier/
├── .github/              # Issue templates, PR template, CI workflows
├── docs/                 # Architecture Decision Records (ADRs), roadmap, methodology
├── migrations/           # SQL schema migrations (Flyway-style, checksum-tracked)
├── scripts/              # Operational scripts (sync, labeling, logger, Task Scheduler wrappers)
├── src/vn_portfolio_frontier/
│   ├── domain/           # Pure business entities and value objects
│   ├── application/      # Use case services (FrontierService, RebalanceSimulator)
│   ├── infrastructure/   # Database adapters, external API adapters
│   └── interface/        # Streamlit UI, CLI (and future FastAPI in Project 3)
├── tests/                # Unit, integration, and contract tests (pytest, 213+ tests)
├── .env.example          # Configuration template
├── LICENSE               # MIT
├── pyproject.toml        # Package config
├── README.md             # This file
└── README.vi.md          # Vietnamese version
```

## Data Sources

| Source | Coverage | Frequency | Access |
|--------|----------|-----------|--------|
| VN30 OHLCV prices | 30 tickers, 2021-01-04 onward | Daily close | vnstock Silver tier |
| VN30 membership events | 11 rebalance events, 2021-2026 | Semi-annual | Manual YAML seed + script (event-sourcing per ADR-013) |
| Fundamentals | VN30 constituents | Quarterly | vnstock Silver (bronze/silver schema per ADR-014) |
| Benchmark rates | VN 1Y bond yield, SBV refi, VCB 13M deposit | Daily | vnstock Macro API |
| Financial news | 18 Vietnamese sources (CafeF, VietStock, VnExpress, CafeBiz, VneconomyÁ, VietnamNet, ...) | Daily | vnstock_news Silver tier |

Historical window starts **04/01/2021** — the effective date HOSE revised lot size from 10 to 100 shares per lot (Decision 496/QĐ-SGDHCM). Backtests before this date would require handling the lot split rule, deferred to the thesis stage.

## Documentation

- **Architecture Decision Records**: [`docs/architecture.md`](./docs/architecture.md) — 19 ADRs documenting decisions with alternatives, consequences, and reversibility notes
- **ADR Nygard format**: [Documenting Architecture Decisions](https://cognitect.com/blog/2011/11/15/documenting-architecture-decisions)
- **Meta-process lessons**: `docs/decisions-and-learnings.md` — 38 lessons learned during development

## Contributing

External contributions are welcome for bug reports, documentation improvements, and discussion of methodology. Pull requests implementing new features will be reviewed in the context of the research scope. See [`CONTRIBUTING.md`](./CONTRIBUTING.md).

## License

MIT — see [`LICENSE`](./LICENSE). The MIT license applies to the source code only. Any derived use for commercial investment advisory requires compliance with Vietnam Securities Law 54/2019/QH14 and licensing by the author's or the derived product's employer organization.

## Legal Notice

This project is a **research artifact** developed as part of a university bachelor's thesis at Hanoi University of Science and Technology. It is not a licensed advisory service and does not provide investment recommendations for specific securities as defined by Article 72 and Article 86 of Vietnam Securities Law 54/2019/QH14. Users bear full responsibility for any investment decisions. For actual investment advisory, consult a licensed professional affiliated with a securities company holding a valid UBCKNN license.

## Acknowledgments

- **VinAI Research** for the PhoBERT model (used for exploratory analysis in early design phases; final F3 architecture pivoted to Agentic RAG per ADR-008 resolution 02/11/2026).
- **Neon** for managed PostgreSQL with a free tier that makes this project feasible on 8 GB RAM development hardware.
- **Anthropic** for Claude Sonnet 5-5 teacher model enabling the structured news labeling pipeline.
- **vnstock team** for Silver tier access to Vietnamese market data (prices, fundamentals, news).

---

Developed as **Project 2** of the HUST Information Technology Engineering second-bachelor program (2025-2027). Project 2 submission deadline: **17/11/2026**. Bachelor's thesis defense: **06/2027**.
