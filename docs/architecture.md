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

---

## ADR-009: Feature-driven schema evaluation for Project 2 domains

**Status:** Accepted — 2026-09-08

### Context

Phase 2 requires three domain schemas: `prices`, `fundamentals`, `news_sentiment`. Initial design proposals tended toward comprehensive coverage — for example, an early `fundamentals.financial_report` draft carried 14 columns (revenue, net income, EPS, total assets, equity, debt, P/E, P/B, ROE, auditor firm, dividends, interest expense, ...). Question: how comprehensive vs how minimal?

Neon free tier caps storage at 0.5 GB, and every column adds test surface and cognitive load. On the other hand, missing columns cost `ALTER TABLE` migrations later. Where should the line sit?

### Decision

Adopt **feature-driven schema evaluation** as the standing methodology for Project 2 schema design.

For each proposed column or table, ask: **"which Project 2 feature actually uses this?"** Columns without a feature dependency are cut from the initial schema and deferred to future ADRs when a real need emerges.

### Methodology

1. Enumerate Project 2's three user-facing features: **Efficient Frontier**, **Auto-rebalancing**, **PhoBERT sentiment extraction**.
2. For each feature, list the SQL queries it needs (mean returns, portfolio drift, ticker validation, ...).
3. Map queries → columns and tables required.
4. Design the schema covering exactly those requirements plus audit/metadata columns (source, ingested_at).
5. Reject additions justified only by "might be useful in Phase 3" or "industry standard practice" — deferred to future ADRs written when the need is concrete.

### Applied results

**`fundamentals` domain (Commit 7):**

Original proposal: 1 table, 14 columns spanning full income statement, balance sheet, and derived ratios.

After feature-driven evaluation:
- **`vn30_constituent`** (12 columns) — ticker metadata registry. Used by sentiment extraction for ticker validation and dashboards for sector grouping.
- **`financial_report`** (9 columns) — minimal (revenue, net_income, EPS) for sentiment context enrichment only.

Columns **cut** with rationale:
| Cut column | Why |
|-----------|-----|
| `pe_ratio`, `pb_ratio`, `roe_percent` | Derivable from stored data + prices; staleness risk if stored |
| `total_assets`, `total_equity`, `total_debt` | Balance sheet detail — no Project 2 feature uses it |
| `auditor_firm` | Metadata detail — no feature uses it |
| `dividends_paid`, `interest_expense` | Corporate detail — belongs to a future events schema if ever needed |

**`news_sentiment` domain (Commit 8):**

- **`entities`** stored as JSONB (per Q3 planning decision) rather than a normalized `entity` table.
  - Rationale: entity schema evolves during PhoBERT/RAG development; JSONB flexibility beats strict normalization for research-phase code.
  - GIN index enables containment queries without normalization.
- **`ticker`** in `extracted_signal` is **not** FK-constrained to `vn30_constituent` — allows news mentioning non-VN30 tickers to be preserved for downstream filtering.
- Cut: `word_count` (derivable from body), `is_processed` flag (LEFT JOIN pattern finds unprocessed articles).

**`prices` domain (Commit 6):**

Migrated conservatively from Project 1 SQLite:
- Composite PK `(ticker, trade_date)` — natural key, no surrogate ID.
- Only `source` column added — provenance for the hybrid Task 5 migration (SQLite bootstrap + fresh vnstock fetch).

### Consequences

**Positive:**
- Smaller schemas: 6 tables total, most under 12 columns. Less code, less test surface, faster CI.
- Every column has a defensible purpose. Easier to answer *"why this column?"* in the thesis review.
- Neon free tier storage stays comfortable — projected ~120 MB used at Phase 2 completion (mostly news bodies), well under 500 MB cap.
- Migration runner is idempotent and checksum-tracked (see Commit 6), so future `ALTER TABLE` additions are safe and auditable.

**Negative:**
- Phase 3 (ensemble ML forecasting) may need cut columns → `ALTER TABLE` migrations expected.
- Hindsight-bias risk: "we should have designed for the future." Mitigated by cheap `ALTER TABLE` via the migration runner.
- Requires discipline to reject "just in case" columns during design reviews.

### Alternatives considered

1. **Comprehensive-first design** — include all standard financial columns from the start.
   - Rejected: waste of dev effort, harder to defend individual column choices, higher storage cost.
2. **Star schema with dim/fact tables** (data warehouse pattern) — separate ticker dimension, time dimension, and central fact tables.
   - Rejected: over-engineered for a 3-month project scope. Phase 4 dbt models can build derived star-schema views on top of the source tables designed here.

### Related

- Q1-Q4 planning decisions (2026-09-08 session) — locked strategy: hybrid data population, `NUMERIC(12,2)` prices, 1-table financial reports with `period_type`, JSONB entities, Python migration runner (dbt deferred to Phase 4).
- ADR-002 (Neon Cloud) — the storage-constrained context that motivates minimalism.
- ADR-006 (structured extraction, not return prediction) — bounds the news_sentiment schema shape.
- Task 5 (data population, upcoming) — will surface any missed requirements. If it does, add a new migration + document the change in a follow-up ADR.

---

## ADR-010: Security posture and version pinning discipline

**Status:** Accepted — 2026-09-22

### Context

Repo is public on GitHub for thesis defense visibility. Contains connection-string patterns in `.env.example`, and CI runs against a real Neon database. A systems-engineer review on 2026-09-13 graded the security posture as **C+**, flagging missing vulnerability disclosure, no dependency scanning, no CVE surfacing pipeline, and unlocked tool versions creating CI drift risk.

Solo research project scope means "production-grade security" is overkill, but *credibility for thesis defense* and *first-time contributor onboarding* both require visible security discipline.

### Decision

Adopt a **five-layer security posture** as the standing baseline (Commit 9a):

1. **`SECURITY.md`** — vulnerability disclosure policy, response SLA (5 business days ack, 14 days assessment, 30 days fix), scope statement, private reporting channels (GitHub Security tab preferred + email fallback).
2. **`CODEOWNERS`** — auto-request review from @MCTGiang on every PR. Trivial today (solo project) but future-proofs collaborator onboarding.
3. **Dependabot** (`.github/dependabot.yml`) — weekly pip + github-actions PRs, Monday 09:00 Asia/Ho_Chi_Minh. Minor/patch batched to reduce noise; major stays individual.
4. **Pre-commit hooks** (`.pre-commit-config.yaml`) — local defense in depth: gitleaks, private-key detection, trailing-whitespace, EOL normalization, black, ruff.
5. **CI vulnerability scan** (tests.yml `security-scan` job) — pip-audit runs on every PR, `continue-on-error: true` (non-strict warning-only, does not block merge). GitHub-native secret scanning + push protection remain enabled at the repo level as a separate blocker.

### Version pinning subclause (lesson from PR#8)

Tool versions MUST be pinned **exact** in **both** `pyproject.toml` dev deps AND `.pre-commit-config.yaml` revs. Loose ranges (`>=`) cause CI drift when new versions release between local dev and CI.

Concrete example: PR#8 first CI run failed on black check because pre-commit locked `black==25.1.0` while pyproject specified `black>=24.0`, so `pip install .[dev]` on CI fetched black 26.5.1 with different formatting output. Fixup commit needed to sync. Commit 9b pinned both at exact versions to prevent recurrence.

### Consequences

**Positive:**
- GitHub Security tab shows "policy defined" badge → reviewer credibility.
- CVEs in dependencies surface within 24-48h (Dependabot cadence) rather than staying silent for months.
- Secret leaks blocked at commit-time (gitleaks) AND push-time (GitHub push protection) — defense in depth.
- Version pinning eliminates class of CI drift failures.
- Pre-commit reformats 4-5 files/commit on Windows dev (line endings) automatically → no manual cleanup burden.

**Negative:**
- Pre-commit hooks add 3-5s to each `git commit`.
- Version pinning creates PR churn when Dependabot proposes tool version bumps (accepted trade-off — better to see the bump than have it silently apply differently on CI).
- pip-audit non-strict means CVEs surface but don't force action — requires developer discipline to check CI logs.

### Alternatives considered

1. **Wait until Phase 3 or thesis defense to add security layer** — rejected. Retroactive fixes are disruptive; incremental practice throughout the project is cheaper.
2. **Strict pip-audit (`--strict` flag or `continue-on-error: false`)** — rejected for research pace. A CVE in a dep with no available fix should not block feature work. Non-strict lets CI surface the issue while allowing pragmatic merges.
3. **Manual dependency updates only (no Dependabot)** — rejected. Bit-rot on a 3-month project is inevitable; automation buys back review time.

### Related

- Commit 9a (SHA 5914c9e, PR#8) — implementation.
- Commit 9b (SHA a989fee, PR#12) — added version pinning discipline (`black==26.5.1`, `ruff==0.16.6`) following PR#8 lessons.
- ADR-002 (Neon Cloud) — secret handling for connection strings is the primary threat surface this posture protects.

---

## ADR-011: Vietnamese financial news sources for sentiment extraction

**Status:** Accepted — 2026-09-22

### Context

Feature 3 (structured sentiment extraction) requires a corpus of Vietnamese financial news for PhoBERT fine-tuning and inference. No public labeled dataset exists for VN finance-domain sentiment — VLSP and UIT-VSFC are general-domain, missing financial vocabulary (mÃ£ cá»• phiáº¿u, sá»± kiá»‡n M&A, phiÃªn Ä‘áº¥u giÃ¡, ...).

Options for corpus acquisition:
- Scrape public Vietnamese financial news sites
- Purchase from data vendor (cost + coverage limited for VN market)
- Manual curation (unscalable)
- Real-time API (SSI FastConnect deferred to thesis phase per roadmap)

### Decision

Scrape three publicly accessible Vietnamese financial news sources:

| Source | Type | Coverage | Estimated volume |
|--------|------|----------|-------------------|
| **VnExpress** (Kinh doanh section) | Mainstream general-audience | Broad market news, corporate announcements | ~800 articles/month |
| **CafeF** | Specialist financial | Market analysis, VN30 focus, macro commentary | ~500 articles/month |
| **VietStock** | Stock-focused | Technical + fundamental analysis, trading signals | ~200 articles/month |

Total estimate: **~1,500 articles/month** across three sources.

### Ethical and legal constraints

Compliance requirements for the scraper (enforced in Phase 3 implementation):

1. **`robots.txt` compliance** — mandatory. Any URL disallowed is skipped.
2. **Rate limiting** — maximum 1 request per 2 seconds per source (0.5 rps); randomized jitter to avoid burst detection.
3. **User-agent identification** — request headers identify the traffic as research use (`vn-portfolio-frontier-scraper/0.1 (thesis; contact: mctgiang@gmail.com)`).
4. **No public redistribution** — article body content is stored in private Neon DB for research use only. If the thesis is published, only aggregate statistics + short quotes (fair-use) are included, never full article bodies.
5. **Attribution preserved** — every scraped article records `source`, `url`, `published_at` per the `news_sentiment.article` schema (Commit 8).

### Technical design

Schema `news_sentiment.article` (from Commit 8) supports this decision:
- `UNIQUE(url)` — URL as deduplication key; scrapers can UPSERT on conflict without exploding row count on re-runs.
- `source` enum-constrained to `('vnexpress', 'cafef', 'vietstock', 'manual')` — extensible for future sources; `manual` reserved for human-labeled ground-truth entries.
- `language VARCHAR(10) DEFAULT 'vi'` — English coverage reserved for thesis phase (potential cross-lingual analysis).
- `scraped_at TIMESTAMPTZ DEFAULT NOW()` — pipeline monitoring and freshness checks.

### Consequences

**Positive:**
- Diverse coverage: mainstream (VnExpress) balances specialist (CafeF, VietStock). Reduces single-source bias in sentiment training.
- Volume sufficient: ~1,500/month Ã— 3 months backfill ≈ 4,500 articles → 500-1000 human/LLM-labeled samples for fine-tuning is a viable subset (per Feature 3 timeline in Sprint 13).
- Free (respectful use of public content) — no vendor dependency.
- URL-keyed dedup means re-running scrapers is idempotent.

**Negative:**
- HTML structure changes on source sites require scraper maintenance (mitigation: version-tagged scraper modules per source, from ADR-010 risk table).
- Rate limits slow full historical backfill: 1500 articles Ã— 2s = ~50 minutes minimum per full sweep.
- Legal risk if sources add explicit anti-scraping clauses — mitigated by robots.txt compliance + limited use scope.
- No structured metadata from sources (article category, tags) — must infer from body content via NLP.

### Alternatives considered

1. **Single source (CafeF only)** — rejected. Lack of diversity increases sentiment model bias; failure of one site kills the corpus.
2. **News API vendor (Bloomberg, Refinitiv)** — rejected. Cost (typically $500+/month), Vietnamese market coverage minimal.
3. **Manual curation** — rejected. Not scalable to volumes needed for ML fine-tuning.
4. **SSI FastConnect real-time API** — deferred to thesis phase per roadmap. Requires broker account + subscription; overkill for research-phase batch processing.

### Related

- ADR-006 (structured extraction, not return prediction) — bounds what the sentiment pipeline outputs.
- ADR-008 (PhoBERT vs RAG, open) — decision at 2026-10-20 uses this corpus as training data.
- Commit 8 (news_sentiment schema, SHA 288113d) — implements the storage layer this decision plans against.
- Task 5 (Sprint 10) — initial scraper build reads from these sources.

---

## ADR-012: Auto-rebalancing transaction cost model — user-parameterized, cost-agnostic framework

**Status:** Accepted — 2026-09-21

### Context

Feature 2 (Auto-rebalancing simulator) must account for transaction costs when evaluating rebalancing strategies. Costs vary materially across three dimensions:

1. **Broker**: 0.00% (Pinetree, DNSE zero-commission) to 0.40% (traditional retail default).
2. **Tax**: 0.10% seller-only (ThÃ´ng tÆ° 111/2013/TT-BTC, fixed by law).
3. **Market impact**: 0.02% (large-cap liquid VN30) to >1% (illiquid small-cap, large order relative to average daily volume).

Design question: how does the simulator receive cost input?

Approaches considered during 21/09/2026 design session:
- Hardcode a single cost value (simple, misleading — one broker's fee)
- Broker preset dropdown (maintenance burden, endorsement risk)
- Fully user-parameterized (flexible, cost-agnostic)

Author works at VCBS. Hardcoding or featuring VCBS in preset lists would introduce potential conflict-of-interest questions at thesis defense.

### Decision

Adopt a **user-parameterized, cost-agnostic** framework. User inputs their broker's advertised fee (a number they can read from their contract); system auto-derives the total cost.

### Cost model
total_cost_bps = int(brokerage_pct * 100) + int(tax_pct * 100) + market_impact_bps

Applied per trade side (buy or sell). Total per rebalance = sum over all rebalanced positions Ã— turnover.

### API contract (LOCKED naming)

```python
@dataclass
class TransactionCostConfig:
    brokerage_pct: float                # required, user input, % scale (0.15 = 0.15%)
    tax_pct: float = 0.10               # regulated seller tax (ThÃ´ng tÆ° 111/2013/TT-BTC)
    market_impact_bps: int = 10         # VN30-liquid default, overridable for small-cap

    @property
    def total_cost_bps(self) -> int:
        return int(self.brokerage_pct * 100) + int(self.tax_pct * 100) + self.market_impact_bps
```

**Canonical names (no aliases across P2/P3/thesis codebase):**

| Concept | Canonical | Prohibited synonyms |
|---------|-----------|---------------------|
| Broker fee | `brokerage_pct` | `broker_fee`, `commission`, `fee_pct` |
| Seller tax | `tax_pct` | `sell_tax`, `pit_rate`, `tax_bps` |
| Market impact | `market_impact_bps` | `slippage_bps`, `execution_cost`, `mi` |
| Total | `total_cost_bps` (computed property) | `cost_bps`, `all_in_cost` |

### Validation rules

```python
if brokerage_pct < 0:
    raise ValueError("brokerage_pct must be non-negative")
if brokerage_pct > 1.0:
    raise ValueError(
        f"brokerage_pct = {brokerage_pct} looks like a unit mistake. "
        f"Input is %-scale: 0.15 means 0.15%. "
        f"If you meant {brokerage_pct} basis points, use {brokerage_pct/100}"
    )
if brokerage_pct > 0.40:
    warnings.warn(f"brokerage_pct = {brokerage_pct}% is unusually high for VN market")
```

Streamlit UI (NICE tier, Sprint 15) enforces `st.number_input(min_value=0.0, max_value=1.0, step=0.01, format="%.2f%%")` at the UI boundary.

### Output format (mandatory decomposition)

Every rebalancing report MUST decompose cost into all three components + total. No aggregated `total = 35 bps` without breakdown. Example:
Cost decomposition (per trade side):
Brokerage: 0.15% (user input)
Tax: 0.10% (ThÃ´ng tÆ° 111/2013/TT-BTC, seller-only)
Market impact: 10 bps (VN30 default assumption)
─────────────────────────
Total: 35 bps

Reasoning: transparency is defensibility. Aggregated "cost = 35 bps" invites a defense committee to ask "what is that composed of?" — pre-empt with breakdown.

### Primary output = sensitivity curve, not fixed scenario

Feature 2's headline deliverable is `Sharpe_after_cost(brokerage)` curve computed across `brokerage_pct ∈ [0.00, 0.40]` (step 0.01). Fixed cost scenarios are secondary; user reads the curve at their broker's fee to determine their scenario-specific result.

### Persistence

All simulation runs are persisted to `simulation.rebalance_run` (Task 4b, migration 005 upcoming). Every row records the exact `brokerage_pct`, `tax_pct`, `market_impact_bps`, strategy params, git commit SHA, and output metrics — enabling reproducibility and defense-time run comparison.

### Consequences

**Positive:**
- Framework broker-agnostic: eliminates "why VNDIRECT and not VCBS?" question at defense (conflict-of-interest concern moot).
- Author-employer conflict avoided: no explicit VCBS fee number in code or featured preset.
- Naming stability across P2/P3/thesis prevents refactor churn as codebase grows.
- Sensitivity curve is a stronger academic contribution than a fixed scenario table (Perold-Sharpe 1988, Donohue-Yip 2003 precedent).
- Unit-trap validator catches common input mistakes with actionable error messages.

**Negative:**
- Three parameters instead of one increase interface complexity (mitigation: default `tax_pct` and `market_impact_bps`; only `brokerage_pct` is required user input).
- Reference table of broker fees in docs (`docs/features/rebalancing.md`, coming with Feature 2 build) may go stale — mitigated by "as of research date, verify at broker's current schedule" disclaimer + explicitly non-authoritative labeling.
- Docs illustrative brokers list intentionally excludes VCBS to avoid perceived endorsement.

### Alternatives considered

1. **Hardcode single `cost_bps=25` constant** — rejected. Misleading; different brokers 40+ bps apart. Weak defense against "why this number?"
2. **Broker preset dropdown (SSI/VNDIRECT/TCBS)** — rejected. Maintenance burden (fee schedules change every 1-2 years); featuring specific brokers implies endorsement; author-employer VCBS ambiguity worsens.
3. **Bundle broker + tax as single `total_fee_pct` input** — rejected. Tax is regulated separately (fixed 0.10%); users need override control for edge cases (fund exemptions, block trades). Bundling loses that flexibility.
4. **Full Almgren-Chriss market impact model** (calibrated per-ticker `Î· Ã— Ïƒ Ã— √(q/V)`) — deferred to Phase 3. Requires L1 bid-ask spread data (vnstock availability unverified); overscoped for Feature 2 timeline.

### Related

- ADR-006 (structured extraction positioning) — Feature 3 informs but does not gate Feature 2.
- Feature 2 scope (locked 21/09/2026): MUST = brokerage_pct input + threshold_band strategy; SHOULD = sensitivity sweep + persistence; NICE = Streamlit UI + Almgren-Chriss (Phase 3).
- Task 4b (Sprint 9-10) — migration 005 creates `simulation.rebalance_run` schema referenced above.
- Sprint 11-12 (06-19/10) — Feature 2 build implements this ADR.

# Open decisions (pending)

## ADR-007: Prefect vs Apache Airflow for workflow orchestration

**Status:** SUPERSEDED — 2026-09-22 (deferred to Phase 4 / thesis platform)

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

### Resolution (2026-09-22)

**Deferred to Phase 4 (thesis platform).** Original deadline (2026-09-15) passed without decision because Project 2's core features (Efficient Frontier + Auto-Rebalancing + PhoBERT Sentiment) don't require a workflow orchestrator during the 3-month build phase:

- Data ingestion (Task 5, Sprint 10) is a **one-time backfill** — no scheduling needed.
- Feature 2 rebalancing runs are user-triggered simulations, not scheduled jobs.
- Feature 3 sentiment extraction is batch-invoked from ad-hoc scripts during PhoBERT development.

Scheduled pipelines (daily price refresh, weekly fundamentals, hourly news scrape) become meaningful only in **Phase 4 (thesis platform)** when the microservices architecture serves real-time users. Decision defers to that phase.

Preliminary recommendation **Prefect** remains the leaning choice for Phase 4 — reasons preserved below for future reference.

### Preliminary recommendation (retained for Phase 4)

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
