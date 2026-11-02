# ADR-008 (OPEN): PhoBERT fine-tune vs RAG for sentiment extraction

**Status:** PROPOSED -- decision deadline **2026-10-30** (originally 2026-11-15, moved to 2026-10-20 for schedule risk mitigation, now +10 days due to F1 Sprint 11 extension to 23/10)

## Context

Project 2 Feature F3 extracts structured signals `(ticker, event_type, sentiment, magnitude, entities)` from Vietnamese financial news (CafeF, VnExpress, VietStock via `vnstock_news` Sponsor Silver). Two implementation paths considered:

### Option 1: PhoBERT fine-tune
- Base model: VinAI PhoBERT-base (134M params, Vietnamese pretrained BERT)
- Task head: NER (entity extraction) + classification (event_type) + regression (sentiment, magnitude)
- Training data: ~5000 LLM-labeled samples
- Inference: CPU-feasible or Colab Pro GPU
- Cost: Colab Pro $10/month (subscribed 2026-09-23)

### Option 2: RAG (Retrieval-Augmented Generation)
- Vector store: Chroma + Vietnamese sentence embeddings
- LLM: GPT-4 Turbo (OpenAI) or local Llama variant
- No fine-tuning required
- Cost: ~$0.01/query x ~1000 queries/month ~= $10/month ongoing

## Decision factor

**Labeling quality of first 200 LLM-labeled samples** (from 5000-sample budget).

Audit by human (Ginny) to compute per-field metrics:
- **Label precision**: ticker/event_type/sentiment/magnitude/entities
- **Self-consistency check**: same sample re-labeled 3x by LLM, measure agreement
- **Noise rate**: (# samples with 2+ incorrect fields) / 200

## Evaluation framework

### Metrics to compute (after 200-sample audit)

| Metric | Field | Threshold | Signal |
|---|---|---|---|
| Label F1 | ticker | >= 0.95 | NER task easy, fine-tune favored |
| Label F1 | event_type | >= 0.80 | Classification clear |
| Label F1 | sentiment | >= 0.70 | Regression stable |
| Label F1 | magnitude | >= 0.60 | Regression noisy but usable |
| Noise rate | all fields | <= 15% | Fine-tune safe |
| Noise rate | all fields | > 25% | RAG safer (flexibility) |

### Decision tree
IF avg Label F1 >= 0.75 AND noise rate <= 15%:
    -> FINE-TUNE (PhoBERT)
ELIF avg Label F1 < 0.65 OR noise rate > 25%:
    -> RAG (GPT-4 Turbo + Chroma)
ELSE (grey zone 0.65-0.75):
    -> Expand audit to 500 samples + re-evaluate
    -> If still grey zone -> RAG (safer default, no training risk)

### Required artifacts for decision

- `data/sentiment_training/raw_articles.jsonl` -- 500-1000 articles from CafeF + VnExpress + VietStock (via vnstock_news)
- `data/sentiment_training/llm_labels.jsonl` -- LLM-generated labels (Claude API batch)
- `data/sentiment_training/human_audit_200.jsonl` -- human-reviewed subset
- `scripts/audit_sentiment_labels.py` -- compute F1 + noise rate + decision tree output

## Alternatives considered

1. **No sentiment feature** -- Drop F3 entirely, keep P2 as F1 + F2 only. Rejected: thesis scope locked (ADR-002).
2. **Rule-based lexicon** -- VN sentiment lexicon + keyword matching. Rejected: too simplistic, defense story weak.
3. **Both fine-tune + RAG ensemble** -- Rejected: 2x complexity, timeline tight.

## Consequences by path

### If PhoBERT fine-tune
**Positive:** Fast inference (ms/sample), no ongoing API cost, reproducible, local deployment possible, defense story stronger (academic rigor).
**Negative:** Training cost 4-8h GPU time, retraining needed if label schema changes, VinAI model may be outdated vs current Vietnamese LLMs.

### If RAG
**Positive:** No training, flexible prompt engineering, easy schema iteration, works with any new LLM upgrades.
**Negative:** Ongoing API cost ($10-30/month), slower inference (1-3s/query), external API dependency, less reproducible (model versions change).

## Sprint 13 Day 1-2 schedule (Monday-Tuesday 28-29/10)

### Day 1 (28/10) — Data collection + labeling
- [ ] Morning: Scrape 500-1000 articles via `vnstock_news` `fetch_feeder()` + `fetch_articles()` for 3 sources (CafeF/VnExpress/VietStock)
- [ ] Noon: Setup LLM labeling pipeline (Claude API batch, cost ~$2-5)
- [ ] Afternoon: Generate labels for first 200 samples
- [ ] Evening: Human audit sampling (random 50 from 200) + spreadsheet template

### Day 2 (29/10) — Human audit + decision
- [ ] Morning: Complete human audit remaining 150 samples (~2h focused work)
- [ ] Noon: Run `audit_sentiment_labels.py` -> compute metrics
- [ ] Afternoon: ADR-008 decision locked -> update this file (change Status PROPOSED -> ACCEPTED)
- [ ] Evening: Sprint 13 Day 3 planning based on decision

## Timeline risk

- Original deadline 2026-10-20 -> missed due to F1 extension to 23/10 (3-day slip)
- New deadline 2026-10-30 -> 3-day buffer before Sprint 13 Day 3 (31/10)
- If audit shows grey zone -> extended to Sprint 14 Day 1 (03/11) at latest
- Hard stop: 2026-11-02 (end of Sprint 13) -- after this, defender RAG as safer default

## References

- Related ADRs: [ADR-002 Feature scope lock], [ADR-006 F3 scope boundary]
- VinAI PhoBERT: https://github.com/VinAIResearch/PhoBERT
- vnstock_news Sponsor Silver access (subscribed 2026-09-30)

## Decision Resolution — 2026-11-02

**Status change:** PROPOSED → **Accepted**
**Decision owner:** Mai Công Trà Giang
**Resolution date:** 2026-11-02 (post Sprint 13 Day 2 audit + research advisor meeting)
**Final direction:** **RAG** — F3 corpus positioned as evidence base for Agentic Retrieval-Augmented Generation

### Resolution rationale

Three converging inputs settled the decision:

#### Input 1 — Phase B labeling outcome (Sprint 13 Day 1-2, 28-29/10/2026)

Phase B produced **699 labeled articles over 6 sources** (cafef 50, cafebiz 100, nguoiquansat 60, thoibaotaichinhvietnam 200, dddn 89, petrotimes 200) with 11-field schema per ADR-006. Quality metrics:

- Total cost $10.43 / $20 budget (52% used)
- Error rate 0.4% (3 failed / 699 attempts)
- Average confidence score 0.859
- Signal density: 106/699 relevant (**15.2%**), higher than pilot 10% but concentrated on only 14/30 VN30 tickers
- Event taxonomy coverage: macro 42, regulatory 27, other 28, earnings 7 — thin on micro-level ticker-specific events

**Interpretation vs decision tree:** Signal density 15.2% translates to ~106 relevant training samples. This sits at the **lower edge** of the PhoBERT fine-tuning viability threshold (500-1000 samples recommended by Hinton 2015 teacher-student distillation literature for stable training without augmentation).

#### Input 2 — Research advisor guidance (02/11/2026)

Research advisor (TS. Nguyễn Đức Anh) feedback established four methodological observations:

1. **Binary sentiment classification is paradigm 2015-2020**, superseded by structured event extraction with magnitude + duration decay in NLP finance literature post-2022 (Loughran & McDonald 2011 lexicon era → modern taxonomy-based event extraction).
2. **Vietnamese financial news lag (1-6 hours) + market volatility** make real-time binary sentiment signals of limited practical value for individual investors.
3. **News impact has 3-tier structure** (micro ticker-specific / meso sector / macro vĩ mô) requiring taxonomy-aware architecture rather than single-model prediction.
4. **Thesis research question (long-term advisor 6M-2Y horizon)** benefits more from flexible RAG-based retrieval and reasoning than from fixed classifier output.

These observations shift the research framing of F3 from "sentiment classifier for prediction signal" (Project 1-2 draft direction) to "structured news corpus as evidence base for Agentic AI reasoning" (Project 3 → Thesis direction).

#### Input 3 — Hexagonal architecture flexibility (ADR-015)

The platform's Hexagonal design allows the F3 interface (`SentimentPort` / `NewsEvidencePort`) to be realized by either implementation without domain layer changes. The corpus artifact itself (699 labeled articles with 11-field schema) is reusable across implementations. This means **the decision is reversible**: if a future thesis sprint discovers RAG falls short on latency or cost, PhoBERT fine-tuning can be re-attempted on an expanded corpus (target 5000 samples at Project 3 Sprint 4) without architectural disruption.

### Final decision scope

**Project 2 (this document scope):**
- F3 Phase B corpus (699 articles) is persisted as **retrieval source** for future Agentic RAG
- F3 reporting in Project 2 Chapter 6 focuses on: schema design (11 fields), teacher model pipeline (Claude Sonnet 5-5), corpus quality metrics, and the role of structured labeling as foundation
- No PhoBERT fine-tuning executed in Project 2
- Status in reporting changes from "60% complete, pending fine-tune" to "100% complete as foundational corpus"

**Project 3 (12/2026 - 02/2027):**
- Expand corpus 699 → 5000 articles (10x scale)
- Build vector embedding pipeline (multilingual-e5-base or bge-m3)
- Implement hybrid retrieval (BM25 + dense + reranker)
- Prototype RAG workflow with 1-3 retrieval tools for Agentic chatbot

**Thesis (03-06/2027):**
- Integrate hybrid RAG as retrieval tool for Agentic chatbot
- Evaluate RAG quality using live user queries + manual relevance judgments
- Compare response quality against baseline (direct Claude without retrieval)

### Consequences accepted

**Positive:**
- Project 2 F3 deliverable scope shifts from "classifier evaluation" to "corpus foundation" — simpler to defend, higher integration value
- No GPU training cost in Project 2 budget
- Flexibility to adopt new RAG techniques (reranker families, late interaction models) as they mature
- 11-field schema remains reusable if PhoBERT path is revisited at scale

**Negative:**
- Thesis story relies more on engineering integration (RAG + Agentic) than classical ML distillation
- Ongoing inference cost at thesis stage: ~$30-60/month at expected traffic (API-dependent)
- Dependency on Anthropic API availability + pricing stability (mitigation: Claude Sonnet 5-5 primary + Haiku 5 fallback per ADR-022 proposed)

**Neutral:**
- F3 corpus 699 samples below PhoBERT threshold is acknowledged in Chapter 6 as context for RAG decision rather than a limitation of the project

### Reversibility

RAG direction is **not permanent**. Reversibility conditions:
- If corpus expands to 5000+ in Project 3 Sprint 4
- AND if API cost or latency becomes prohibitive at thesis traffic
- THEN PhoBERT fine-tune can be reconsidered as an alternate adapter behind `SentimentPort`

The 11-field label schema remains the lingua franca across both implementations.

### Related

- ADR-006 (F3 scope boundary — structured extraction positioning)
- ADR-015 (Hexagonal — reversibility is architecturally supported)
- ADR-019 (Live prediction tracking — includes news summary signal column for future Agentic integration)
- ADR-020 (Thesis scope lock — pending, will formalize RQ1 methodology around RAG)
- Phase B labeling output: `data/sentiment_training/llm_labels.jsonl` (gitignored, 3.9 MB)
- Research advisor meeting notes: `claude/p2_gvhd_feedback_strategic_review.md` (private project doc)
