# ADR-008 — PhoBERT fine-tune vs RAG for F3 Sentiment Signal Extraction

**Status:** DRAFT — pending Day 2 audit metrics (29/10)
**Deadline:** 30/10/2026 (Thứ 6)
**Decision owner:** Mai Công Trà Giang
**Context:** Sprint 13 kickoff · F3 PhoBERT scope locked ADR-006

---

## 1. Context

F3 (Feature 3) scope per ADR-006: STRUCTURED SIGNAL EXTRACTION từ tin tức tài chính Việt Nam. Output per article: `(ticker, event_type, sentiment, magnitude, entities)`.

**NOT scope** (clarified ADR-006):
- "Sentiment predicts returns" — không claim correlation sentiment vs price
- Pure news summarization — tập trung structured JSON output

Pipeline hiện tại Day 1 Sprint 13 shipped:
- Corpus 699 articles từ 6 sources (cafef, cafebiz, nguoiquansat, thoibaotaichinhvietnam, dddn, petrotimes)
- LLM labels 699 articles qua Claude Sonnet 5-5 (~$10 cost)
- Relevance rate 10% (~70 bài có is_relevant_vn30=True)

**Quyết định cần đưa:** Dùng workflow nào ở production Streamlit cho F3?

---

## 2. Options

### Option A — PhoBERT fine-tune (Student model path)

**Workflow:**
1. Sprint 13 Day 1: ✓ Claude labels 699 raw articles → `llm_labels.jsonl` (ground truth)
2. Sprint 13 Day 2: Human audit 200-sample → validate label quality
3. Sprint 14: Fine-tune PhoBERT-base (135M params) trên labeled dataset, Colab Pro T4 GPU
4. Sprint 15: Deploy fine-tuned PhoBERT vào Streamlit F3 inference pipeline, Neon write labels at scrape time

**Architecture:**
```
News scrape (daily) → PhoBERT inference (local CPU/GPU) → fact_sentiment_signal table (Neon)
                                                         ↓
                                                    Streamlit F3 panel (query signal)
```

**Pros:**
- **Latency**: ~50-100ms/article inference (CPU) — real-time scrape
- **Cost**: $0 inference (self-hosted) sau fine-tune (~$2-5 Colab GPU hours one-time)
- **Reproducibility**: Deterministic (no API variability)
- **Thesis story**: Teacher-student distillation (Hinton 2015) — classical ML approach
- **Scalability**: Infinite inference, no API rate limit

**Cons:**
- **Training data dependency**: Chất lượng final model ≤ chất lượng Claude labels (teacher quality bottleneck)
- **Dev complexity**: Fine-tune code + hyperparameter tuning + eval pipeline (~15-20h Sprint 14)
- **Deployment complexity**: Model file ~500MB, cần Hugging Face Transformers runtime trong Streamlit container
- **Vocabulary limitation**: PhoBERT trained 2020-2021 — có thể miss modern terms (NFT, crypto, Decree 65)
- **Rigid output**: Predict 1 vector per article — khó extract structured entities (fallback regex NER)

### Option B — RAG (Claude at inference)

**Workflow:**
1. Sprint 13 Day 1: ✓ Claude labels 699 raw articles → used as retrieval corpus
2. Sprint 13 Day 2: Index corpus vào vector DB (Chroma local)
3. Sprint 14: Build RAG pipeline (query → retrieve top-K → Claude re-rank + synthesize)
4. Sprint 15: Deploy RAG Streamlit F3 panel

**Architecture:**
```
User query (ticker/date range) → ChromaDB retrieve top-10 bài liên quan → Claude Sonnet 5-5 rerank + extract signal → Streamlit F3 panel
```

**Pros:**
- **Simplicity**: No fine-tune, no hyperparameter — just embed + retrieve + prompt
- **Flexibility**: Prompt-level control cho new event types without retrain
- **State-of-art output**: Claude quality unchanged over time (API-side improvements benefit automatically)
- **Faster MVP**: Sprint 14 ship RAG trong ~1 tuần vs 2 tuần PhoBERT
- **Natural multi-ticker handling**: Prompt có thể ask "list all VN30 impacts" per query

**Cons:**
- **Cost per inference**: $0.01-0.02/query (Claude API) × usage frequency
- **Latency**: 2-5s/query (API round-trip + Claude generation)
- **Vendor lock**: Dependency on Anthropic API availability + pricing stability
- **Rate limit**: 50 req/min (Tier 1) — potential bottleneck nếu Streamlit cao traffic (unlikely cá nhân thesis)
- **Thesis story**: Yếu hơn (RAG là engineering choice, không có learning claim)

---

## 3. Evaluation criteria (filled Day 2 after audit)

### Scoring matrix

| Criterion | Weight | PhoBERT score | RAG score | Note |
|---|---|---|---|---|
| **Label quality** (H1-H4 Day 2 audit) | 25% | TBD | TBD (same labels) | H1-H4 ≥ 3/4 PASS → PhoBERT có đủ ground truth |
| **Inference latency** | 15% | 9/10 (50ms) | 5/10 (3s) | PhoBERT win |
| **Inference cost** | 10% | 10/10 ($0) | 4/10 ($0.015/query) | PhoBERT win |
| **Dev effort Sprint 14** | 15% | 4/10 (20h) | 8/10 (8h) | RAG win |
| **Flexibility (new event types)** | 10% | 3/10 (retrain) | 9/10 (prompt-only) | RAG win |
| **Thesis defense story** | 15% | 9/10 (distillation) | 5/10 (engineering) | PhoBERT win |
| **Reproducibility** | 10% | 10/10 (deterministic) | 6/10 (API versioning) | PhoBERT win |

**Decision rule:**
- Total weighted score higher wins
- Nếu score < 2 điểm chênh lệch → consider hybrid (Option C below)

### Hybrid option (consider only nếu scores sát)

**Option C — Hybrid RAG + PhoBERT lightweight**
- PhoBERT serves is_relevant_vn30 filter (binary classifier, cheap train, bulk filter)
- RAG serves detailed signal extraction (ticker, sentiment, event, entities) on top-K filtered
- Pipeline: scrape → PhoBERT filter → RAG extract → Neon write
- Pros: Best of both — cheap bulk filter + rich on-demand extract
- Cons: 2 systems to maintain, Sprint 15+ complexity

---

## 4. Decision (fill Day 5 Thứ 6)

**Decision:** [PhoBERT / RAG / Hybrid]

**Reasoning:** [paste scoring matrix result + 1 paragraph rationale]

**Risks accepted:**
- [list top 2-3 risks + mitigation plans]

**Consequences:**
- Sprint 14 scope: [update per decision]
- Sprint 15 scope: [update per decision]
- Thesis Chapter 6: [update structure per decision]
- Report deadline impact: [none/positive/negative + explain]

---

## 5. Alternatives considered but rejected early

### Open-source LLM (Llama-3-8B, Qwen-2.5-7B) local
- **Why rejected**: Vietnamese quality kém Sonnet, setup overhead 2-4h, GPU dependency Colab session timeout risk
- **Could revisit**: Nếu Anthropic pricing tăng mạnh Sprint 15+

### Pre-trained Vietnamese sentiment models (VietnameseFinancialBERT)
- **Why rejected**: Domain mismatch (general sentiment, không VN30-specific), label schema cứng (positive/neutral/negative only, không có event_type, entities)
- **Could revisit**: Baseline comparison Sprint 15 (zero-shot vs fine-tune)

### Regex rule-based system
- **Why rejected**: Zero ML content → thesis defense weak, không scalable cho new event types
- **Not revisit**: Below MVP floor

---

## 6. Implementation roadmap post-decision

### If PhoBERT path chosen

**Sprint 14 Week 1 (04-07/11)**
- Day 1-2: Prepare training dataset (80/10/10 split từ labeled 699, data augmentation nếu <100 relevant)
- Day 3-4: Fine-tune PhoBERT trên Colab T4 (2-3 runs với different LR/batch)
- Day 5: Eval best model trên test set + confusion matrix

**Sprint 14 Week 2 (08-10/11)**
- Day 6: Export model to Hugging Face format
- Day 7: Streamlit F3 panel integration + Neon fact_sentiment_signal schema (migration 015)
- Day 8: End-to-end smoke test

### If RAG path chosen

**Sprint 14 Week 1**
- Day 1: Install ChromaDB, embed 699 bài với multilingual-e5-base (local, free)
- Day 2: Build retrieve-rerank-extract pipeline
- Day 3: Streamlit F3 panel + query UI (filter by ticker, date range, event_type)
- Day 4-5: End-to-end smoke test + prompt refinement

**Sprint 14 Week 2**
- Day 6-7: Scheduled scrape → re-index pipeline (daily job)
- Day 8: Thesis Chapter 6 draft (RAG architecture + eval)

### If Hybrid path chosen
- Sprint 14 split: PhoBERT filter (5 days) + RAG extract (5 days)
- Sprint 15 integration + eval
- Highest risk timeline → not recommend trừ khi scoring quá sát

---

## 7. Decision log

| Date | Author | Note |
|---|---|---|
| 2026-10-02 | Giang | ADR-008 opened post Formal Analysis sprint |
| 2026-10-26 | Giang + Cowork | Full evaluation framework formalized (Day 12 Combo) |
| 2026-10-28 | Giang + Cowork | Day 1 corpus 699 bài shipped, Day 2 audit scoped |
| 2026-10-29 | TBD | Day 2 audit metrics populated |
| 2026-10-30 | TBD | **FINAL DECISION** |
