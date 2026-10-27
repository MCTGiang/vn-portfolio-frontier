# Sentiment training data (Sprint 13 F3)

Local-only directory for F3 (PhoBERT vs RAG) training corpus.
**Not committed to git** — see `.gitignore` entry below.

## Files (expected after Sprint 13 Day 1-2)

- `raw_articles.jsonl` — News articles collected via `scripts/collect_news.py`
  - Sources: CafeF, VietStock, VnExpress (3 sites, ~100 articles/site = 300 total)
  - Schema per line: `{site, url, title, short_description, content, publish_time, author, category, tags, collected_at}`

- `llm_labels.jsonl` — LLM-generated labels (Claude API batch, Sprint 13 Day 1 afternoon)
  - Schema per line: `{article_url, ticker, event_type, sentiment, magnitude, entities, llm_model, llm_version, labeled_at}`
  - Target: 200 samples labeled for ADR-008 audit (expandable to 500 if grey zone)

- `human_audit_200.jsonl` — Ginny's manual audit (Sprint 13 Day 2)
  - Schema per line: `{article_url, llm_label, human_label, agreement_per_field, notes, audited_at}`

## Workflow

Per ADR-008 (`docs/adr-008-phobert-vs-rag.md`):
Day 1 (28/10 Mon):
09:00 - scripts/collect_news.py --limit 100 --sites cafef,vietstock,vnexpress
10:30 - scripts/label_articles_llm.py (TBD, Claude API batch)
14:00 - Prepare human audit spreadsheet template
18:00 - Audit kickoff (first 50 samples)

Day 2 (29/10 Tue):
08:00 - Complete human audit (remaining 150 samples)
12:00 - scripts/audit_sentiment_labels.py -> compute F1 + noise rate
13:00 - ADR-008 decision locked (fine-tune / RAG / grey zone)


## Decision criteria (summary, see ADR-008 for full)

| avg F1 | noise rate | Decision |
|---|---|---|
| ≥ 0.75 | ≤ 15% | **FINE-TUNE** (PhoBERT) |
| < 0.65 | > 25% | **RAG** (GPT-4 Turbo) |
| 0.65-0.75 | 15-25% | Expand to 500 samples → RAG default |

## Privacy / IP note

- Article content fetched is for research use (thesis defense context)
- NOT republished / commercialized
- Source URLs preserved per article for attribution
- Content_selector custom config may be needed for sites with scraping restrictions

## .gitignore

Add to `.gitignore` (if not already):
data/sentiment_training/raw_articles.jsonl
data/sentiment_training/llm_labels.jsonl
data/sentiment_training/human_audit_200.jsonl

(README.md itself IS committed as documentation.)
