# Architecture Decision Records

This document captures the architectural decisions made during the design and implementation of `vn-portfolio-frontier`. Each ADR follows the [Michael Nygard format](https://cognitect.com/blog/2011/11/15/documenting-architecture-decisions).

**Status legend:**
- **Accepted** — Decided and in effect
- **Proposed** — Under evaluation, deadline noted
- **Superseded** — Replaced by a later ADR (link)
- **Deprecated** — No longer applies, may be removed

---

## ADR-001: Adopt src-layout for the Python package

**Status:** Accepted — 2026-09-07

### Context

Python packages can be organized two ways:
- **Flat layout:** `vn_portfolio_frontier/` at repo root
- **src-layout:** `src/vn_portfolio_frontier/`

Project 1 (`vn-portfolio-optimizer`) used flat layout. During Project 1 sprint, occasional test discovery ambiguity occurred between the "source" version and the "installed" version of the package.

### Decision

Use **src-layout**. Package source lives under `src/vn_portfolio_frontier/`. Test suite (`tests/`) imports only after `pip install -e .`.

### Consequences

**Positive:**
- Tests are forced to use the *installed* package. Guards against "accidentally works because Python found the source dir" bugs.
- CI test behavior mirrors production install behavior.
- Aligned with modern Python packaging guidance ([PyPA Python Packaging User Guide](https://packaging.python.org/en/latest/discussions/src-layout-vs-flat-layout/)).

**Negative:**
- One extra directory level in every import path.
- `pyproject.toml` requires explicit setuptools config: `[tool.setuptools.packages.find] where = ["src"]`.

### Alternatives

**Flat layout** (Project 1 pattern) — rejected. Project 1's benchmark testing occasionally surfaced source-vs-installed mismatches. Src-layout eliminates the class of bug entirely.

---

## ADR-002: Neon Cloud PostgreSQL as primary database

**Status:** Accepted — 2026-08-26 (locked in handoff)

### Context

Project 2 needs PostgreSQL for three data schemas: VN30 prices (migrated from Project 1 SQLite), fundamentals (new), and news/sentiment (new).

Development machine (HP Envy 13) has **8 GB RAM**. Running local PostgreSQL in Docker would consume 500 MB–1 GB just for the DB, leaving little headroom for Streamlit + Prefect + Jupyter concurrently.

Target platform for thesis (2027) is AWS RDS. Migration path from local PostgreSQL to AWS RDS is trivial (same engine), but so is Neon → AWS RDS.

### Decision

Use **Neon Cloud PostgreSQL** on the free tier, region `ap-southeast-1` (Singapore, closest to Vietnam).

### Consequences

**Positive:**
- Zero local RAM impact.
- 0.5 GB storage tier sufficient for VN30 prices + fundamentals + news metadata (Project 1 SQLite was 3.4 MB; scaling factor <100× fits).
- **10 branches per project** enable git-like schema experimentation (unique to Neon).
- Auto-scaling up to 2 CU handles Streamlit UI load.
- Migration path Neon → AWS RDS for thesis (both PostgreSQL 16+).

**Negative:**
- Requires internet connectivity for all DB operations.
- Scales-to-zero adds ~1–3 s cold-start latency on the first query after idle. Prefect scheduled flows must retry through the first cold start.
- Free tier has usage limits (need to monitor if project grows).

### Alternatives

1. **Local PostgreSQL via Docker** — rejected. 8 GB RAM constraint.
2. **Continue SQLite from Project 1** — rejected. Project 2 requires structured NLP data + concurrent read/write. SQLite's file-level locking is inadequate for pipeline + UI concurrent access.
3. **Supabase** — comparable managed Postgres. Rejected because Neon's DB branching (git-like) is a unique advantage for testing schema migrations. Supabase does not branch.

---

## ADR-003: MIT License

**Status:** Accepted — 2026-09-07

### Context

Public OSS repository requires a license. Common Python OSS licenses: MIT, Apache 2.0, BSD 3-Clause, GPL v3.

### Decision

**MIT License** — Copyright 2026 Mai Công Trà Giang (MCTGiang).

### Consequences

**Positive:**
- Matches Python data-science ecosystem norm (numpy, pandas, scipy, streamlit are all MIT).
- Easy for hiring managers / reviewers to verify (no complex compliance).
- Enables commercial use downstream (Vietnamese fintech firms can adopt without legal review).

**Negative:**
- Downstream users can fork and close-source without contribution-back.
- No explicit patent grant (Apache 2.0 has this).

### Alternatives

1. **Apache 2.0** — rejected. No patented algorithms in project (MPT = 1952 public domain; PhoBERT = open-sourced by VinAI). Apache 2.0's added complexity has no benefit here.
2. **GPL v3** — rejected. Copyleft requirement would deter fintech adoption. Positioning as citable/portfolio piece favors permissive licensing.
3. **BSD 3-Clause** — very similar to MIT with additional endorsement clause. MIT is simpler and equally permissive.

---

## ADR-004: GitHub Actions matrix testing on Python 3.11, 3.12, 3.13

**Status:** Accepted — 2026-09-07

### Context

Project's `requires-python = ">=3.11"` (per ADR-005 inheritance from Project 1: pandas 3.0+ requires Python 3.11+). Development happens locally on Python 3.13. Question: which Python versions to test in CI?

### Decision

Matrix strategy testing **Python 3.11, 3.12, 3.13** on every PR.

### Consequences

**Positive:**
- Catches version-specific syntax bugs early (e.g., PEP 695 syntax works on 3.13 but breaks 3.11).
- Ensures pandas 3.0+ / numpy 2.0+ compatibility across the supported range.
- Total CI runtime ~1–2 min per version, parallel — ~2.5 min wall-clock.

**Negative:**
- 3× CI compute compared to single-version testing (still within GitHub free tier for public repos).
- Possible flakiness on older versions requiring version-specific `pytest.skipif` markers.

### Alternatives

1. **Test only Python 3.13** (local dev version) — rejected. Hides breakage on 3.11, which is the stated minimum. Users on 3.11 would encounter runtime errors we never saw.
2. **Test Python 3.11 + 3.13** (skip 3.12) — rejected. Marginal savings; kept 3.12 for defense-in-depth. Python 3.12 is widely deployed in enterprise environments (aligns with target audience).

---

## ADR-005: Docker containerizes applications only, not the database

**Status:** Accepted — 2026-08-26 (locked in handoff)

### Context

Docker adopted for reproducibility of runtime environments. Question: should the database also be containerized?

### Decision

Docker for **applications only** (Streamlit UI, Prefect orchestration workers). Database stays as **managed Neon Cloud** (per ADR-002).

### Consequences

**Positive:**
- Consistent app runtime across development laptop → thesis deployment → potential AWS deploy.
- Neon takes on backup, scaling, high-availability burden — no ops work.
- Local RAM freed for Streamlit + Prefect + Jupyter dev sessions.

**Negative:**
- DB and apps have different deployment lifecycles (schema migrations happen outside Docker).
- Neon connection string must be managed per environment (`.env` locally, GitHub Secrets in CI, cloud env vars in production).

### Alternatives

1. **Docker Compose with Postgres container** — rejected per ADR-002 (8 GB RAM constraint).
2. **No Docker at all, run apps directly on Windows** — rejected. Loses reproducibility. Project 3 (LSTM/XGBoost) and thesis platform need Docker discipline established now.

---

## ADR-006: PhoBERT sentiment as structured information extraction (NOT "predicts returns")

**Status:** Accepted — 2026-08-26 (locked in handoff)

### Context

Vietnamese financial sentiment analysis is a popular ML project topic. The naive framing — "sentiment score predicts next-day returns" — is:
1. Statistically weak (alpha decays as strategy becomes known).
2. Hard to defend academically (requires massive sample sizes for statistical significance).
3. Marketing-heavy, substance-light.

### Decision

Position PhoBERT (or RAG per ADR-008) as a **structured information extractor**. Given a Vietnamese financial news article, output:
- **Ticker(s)** mentioned
- **Event type** (M&A, earnings, macro announcement, regulation, executive change, ...)
- **Sentiment magnitude** (numeric score with confidence interval)
- **Entities** (companies, people, institutions)

Downstream consumers decide how to use this structured output (dashboards, alerts, feature inputs for other models). This project **does not** claim the extraction predicts returns.

### Consequences

**Positive:**
- Defensible thesis position — extraction accuracy is directly measurable against labeled ground truth.
- Scope realistic for a 2-week phase with 5,000 LLM-labeled samples + 200 human-eval samples.
- Output has real-world utility beyond return prediction (analyst news filtering, event timeline construction).

**Negative:**
- Less flashy than "AI predicts stock prices" — may under-impress non-technical audiences.
- Requires labeled evaluation dataset (planned: LLM-distilled + human-audited).

### Alternatives

1. **Direct return prediction (sentiment → next-day return regression)** — rejected. Weak positioning per context above.
2. **Sentiment scoring only (positive/negative/neutral, no structure)** — rejected. Too shallow; misses the entity/event richness of financial news.

---

# Open decisions (pending)

## ADR-007 (OPEN): Prefect vs Apache Airflow for workflow orchestration

**Status:** PROPOSED — decision deadline **2026-09-15**

### Context

Phase 3 needs a workflow orchestrator for scheduled data pipelines:
- Daily VN30 price ingestion (vnstock + yfinance fallback)
- Weekly fundamentals refresh
- Daily news scrape + sentiment extraction
- Retry logic + failure notifications

### Options

| Aspect | Prefect | Airflow |
|--------|---------|---------|
| Language | Python-native flows | DAG-as-Python but heavier DSL |
| Runtime | Lightweight (Prefect Cloud free tier) | Requires scheduler + metadata DB |
| Docker deploy | Single container | Multiple containers (scheduler, webserver, worker) |
| Ecosystem | Newer, smaller | Industry standard, larger |
| Learning curve | Gentler for Python devs | Steeper (concepts like DAG runs, task instances) |

### Preliminary recommendation

**Prefect** — better fits project scale and 8 GB RAM constraint. Airflow's operational complexity is overkill for ~4 daily flows.

---

## ADR-008 (OPEN): PhoBERT fine-tune vs RAG for sentiment extraction

**Status:** PROPOSED — decision deadline **2026-10-20** (moved earlier from 2026-11-15 for schedule risk mitigation)

### Context

Two approaches for the structured extraction task (per ADR-006):

**Option 1: PhoBERT fine-tune**
- Take VinAI's pretrained Vietnamese BERT
- Add task-specific head (entity extraction + sentiment regression)
- Fine-tune on ~5,000 LLM-labeled samples
- Deploy inference on CPU or Colab Pro GPU

**Option 2: RAG (Retrieval-Augmented Generation)**
- Vector DB of news chunks (e.g., using Chroma + embeddings)
- LLM (GPT-4 or local model) retrieves relevant chunks per query
- Prompt-engineered extraction template
- No fine-tuning required

### Decision factor

**Labeling quality of ~5,000 LLM-labeled samples.** If labels are clean and consistent → fine-tune wins (fast inference, no LLM API cost). If labels are noisy → RAG wins (flexibility to adjust extraction template).

Decision at 2026-10-20 will be made after audit of first 200 LLM-labeled samples (human eval).
