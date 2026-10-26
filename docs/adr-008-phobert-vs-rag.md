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
