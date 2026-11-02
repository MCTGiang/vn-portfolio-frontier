# Phase B — LLM Labeling Spec

**Sprint 13 Day 1 (28/10/2026) · F3 Sentiment**
**Author:** Mai Công Trà Giang + Cowork
**Status:** Draft v1, pending Day 1 pilot (10-sample) test

---

## 1. Mục tiêu

Dùng Claude API label 699 bài corpus `data/sentiment_training/raw_articles.jsonl` thành structured JSONL output `data/sentiment_training/llm_labels.jsonl` theo schema ADR-006.

Output phục vụ:
- **Day 2**: 200-sample human audit → inter-rater agreement (Cohen's κ)
- **ADR-008 decision (Thứ 6 30/10)**: evidence base PhoBERT vs RAG
- **Sprint 14**: Nếu PhoBERT wins → training dataset
- **Sprint 15**: Nếu RAG wins → ground truth cho eval set

---

## 2. Label Schema (strict JSON per article)

```json
{
  "article_id": "sha256(url)[:16]",
  "ticker": "VCB | HPG | ... | VN30-INDEX | null",
  "ticker_mentions": ["VCB", "FPT"],
  "event_type": "earnings | dividend | ma | insider | regulatory | macro | litigation | other",
  "sentiment": "positive | neutral | negative",
  "sentiment_magnitude": 1,
  "entities": {
    "persons": ["Phó Đức Nam"],
    "orgs": ["Vietcombank"],
    "amounts": ["1.560 tỷ đồng"]
  },
  "rationale": "1-2 câu giải thích sentiment reasoning",
  "is_relevant_vn30": true,
  "confidence": 0.85,
  "model": "claude-sonnet-4-5",
  "labeled_at": "2026-10-28T10:45:00Z",
  "input_tokens": 1234,
  "output_tokens": 189,
  "cost_usd": 0.0064
}
```

### Field semantics

| Field | Type | Rule |
|---|---|---|
| `article_id` | str | SHA256(url) first 16 hex — deterministic dedup key |
| `ticker` | str\|null | Mã VN30 PRIMARY (nếu bài focus 1 mã); `VN30-INDEX` nếu macro affecting all; `null` nếu không ticker-specific |
| `ticker_mentions` | list[str] | TẤT CẢ mã VN30 được nhắc (có thể rỗng) |
| `event_type` | enum | 1 trong 8 giá trị. Fallback `other` |
| `sentiment` | enum | positive/neutral/negative tác động giá cổ phiếu |
| `sentiment_magnitude` | int 1-5 | 1=mild, 5=strong directional move expected |
| `entities` | obj | 3 lists, có thể rỗng |
| `rationale` | str | 1-2 câu tiếng Việt giải thích sentiment |
| `is_relevant_vn30` | bool | False cho crime/entertainment/non-finance → filter audit |
| `confidence` | float 0-1 | LLM self-assessed label confidence |
| `cost_usd` | float | Compute runtime: (in_tok × in_price + out_tok × out_price) / 1_000_000 |

### VN30 roster (sync với `src/vn_portfolio_frontier/shared/vn30_roster.py` hoặc Reference().index.members("VN30"))

`VCB VHM VIC VNM VRE SAB BID BVH CTG EIB FPT GAS GVR HDB HPG MBB MSN MWG NVL PDR PLX POW SHB SSB SSI STB TCB TPB VIB VJC`

---

## 3. Prompt template

### System prompt

```
Bạn là chuyên gia phân tích tin tức tài chính Việt Nam cho rổ VN30.

Nhiệm vụ: Phân tích 1 bài báo tiếng Việt và trích xuất signal có cấu trúc theo schema JSON.

Output BẮT BUỘC là 1 JSON object hợp lệ, không kèm text giải thích ngoài JSON.
Mọi trường "rationale" viết TIẾNG VIỆT.

VN30 roster: VCB VHM VIC VNM VRE SAB BID BVH CTG EIB FPT GAS GVR HDB HPG MBB MSN MWG NVL PDR PLX POW SHB SSB SSI STB TCB TPB VIB VJC
```

### User prompt template

```
# Bài báo cần phân tích

**Nguồn:** {site}
**Thời gian xuất bản:** {publish_time}
**Tiêu đề:** {title}

**Nội dung:**
{content_truncated_6000_chars}

# Schema output

```json
{{
  "ticker": null | "VCB" | ... | "VN30-INDEX",
  "ticker_mentions": [],
  "event_type": "earnings" | "dividend" | "ma" | "insider" | "regulatory" | "macro" | "litigation" | "other",
  "sentiment": "positive" | "neutral" | "negative",
  "sentiment_magnitude": 1-5,
  "entities": {{ "persons": [], "orgs": [], "amounts": [] }},
  "rationale": "<1-2 câu tiếng Việt>",
  "is_relevant_vn30": true | false,
  "confidence": 0.0-1.0
}}
```

# Hướng dẫn
1. Nếu bài không liên quan VN30 (giải trí, tội phạm, du lịch) → is_relevant_vn30=false, ticker=null, event_type="other"
2. event_type "macro" cho tin về SBV/lãi suất/tỷ giá/GDP ảnh hưởng toàn thị trường → ticker="VN30-INDEX"
3. sentiment nhìn góc độ GIÁ CỔ PHIẾU: dividend ex-date neutral, dividend announcement positive, scandal negative
4. confidence thấp (<0.5) nếu bài quá ngắn hoặc ambiguous
5. amounts giữ nguyên format gốc ("500 tỷ đồng", "15%")
```

### Few-shot examples (append to system prompt)

**Example 1 — VN30 ticker earnings positive**
```
Input title: "VCB báo lãi quý 3/2026 đạt 12.500 tỷ đồng, tăng 18% YoY vượt kỳ vọng"
Output: {
  "ticker": "VCB",
  "ticker_mentions": ["VCB"],
  "event_type": "earnings",
  "sentiment": "positive",
  "sentiment_magnitude": 4,
  "entities": {"persons": [], "orgs": ["Vietcombank"], "amounts": ["12.500 tỷ đồng", "18% YoY"]},
  "rationale": "VCB báo lãi vượt kỳ vọng 18%, dấu hiệu tích cực cho giá cổ phiếu.",
  "is_relevant_vn30": true,
  "confidence": 0.92
}
```

**Example 2 — Non-VN30 crime, irrelevant**
```
Input title: "Điểm lại loạt xe sang bị thu giữ trong vụ án Mr Pips"
Output: {
  "ticker": null,
  "ticker_mentions": [],
  "event_type": "other",
  "sentiment": "neutral",
  "sentiment_magnitude": 1,
  "entities": {"persons": ["Phó Đức Nam", "Lê Khắc Ngọ"], "orgs": [], "amounts": ["1.560 tỷ đồng"]},
  "rationale": "Bài về vụ án hình sự, không liên quan trading VN30.",
  "is_relevant_vn30": false,
  "confidence": 0.98
}
```

**Example 3 — Macro affecting all VN30**
```
Input title: "SBV điều chỉnh tăng lãi suất tái cấp vốn 25bps lên 4,75%"
Output: {
  "ticker": "VN30-INDEX",
  "ticker_mentions": [],
  "event_type": "macro",
  "sentiment": "negative",
  "sentiment_magnitude": 3,
  "entities": {"persons": [], "orgs": ["SBV"], "amounts": ["25bps", "4,75%"]},
  "rationale": "Nâng lãi suất điều hành gây áp lực lên chi phí vốn, tiêu cực ngắn hạn cho VN30 banking.",
  "is_relevant_vn30": true,
  "confidence": 0.88
}
```

---

## 4. Cost estimate

### Pricing (Anthropic Claude Sonnet 4.5, cross-check tại claude.com/pricing khi chạy)
- Input: ~$3 / 1M tokens
- Output: ~$15 / 1M tokens

### Per-article avg (based on raw_articles.jsonl stats)
- Avg content length: ~5000 chars ≈ **1500 Vietnamese tokens** (CJK ratio ~3 chars/token)
- System + prompt + examples: ~800 tokens overhead
- Total input: ~2300 tokens
- Output JSON: ~200 tokens

### Cost per article
- Input: 2300 / 1M × $3 = $0.0069
- Output: 200 / 1M × $15 = $0.0030
- **Total: ~$0.01/bài**

### Full corpus 699 bài
- **Sonnet 4.5: ~$7** ← recommended quality tier for Vietnamese NLP
- Haiku 4.5 alternative: ~$2 (quality trade-off, ablation option Sprint 14)
- Pilot 10 bài: ~$0.10 Day 1 test

### Budget guard
Set `MAX_COST_USD` env/CLI arg → script abort nếu accumulated cost > budget trước khi label hết. Default $10 (buffer cho Sonnet 699 + retries).

---

## 5. CLI skeleton `scripts/label_articles_llm.py`

### Signature
```bash
python scripts/label_articles_llm.py \
    --input data/sentiment_training/raw_articles.jsonl \
    --output data/sentiment_training/llm_labels.jsonl \
    --model claude-sonnet-4-5 \
    --limit 10 \
    --dry-run
```

### Flags
| Flag | Default | Purpose |
|---|---|---|
| `--input` | `data/sentiment_training/raw_articles.jsonl` | JSONL input |
| `--output` | `data/sentiment_training/llm_labels.jsonl` | JSONL output |
| `--model` | `claude-sonnet-4-5` | Alternative: `claude-haiku-4-5` for cost ablation |
| `--limit N` | None | Label only first N (useful pilot) |
| `--max-cost-usd` | 10.0 | Abort if cumulative cost exceeds |
| `--resume` | True | Skip article_ids đã có trong output file |
| `--dry-run` | False | Print prompt without API call (format verify) |
| `--content-max-chars` | 6000 | Truncate content để control token budget |

### Core flow
```python
def main():
    _ensure_utf8_streams()  # M5 pattern for Windows cp1252 terminal
    args = parse_args()
    _load_env()  # ANTHROPIC_API_KEY from .env

    # Resume: read existing labels, build set of done article_ids
    done_ids = _load_done_ids(args.output) if args.resume else set()

    # Stream input
    with open(args.input, encoding='utf-8') as f_in, \
         open(args.output, 'a', encoding='utf-8', newline='\n') as f_out:
        cum_cost = 0.0
        for i, line in enumerate(f_in, 1):
            if args.limit and i > args.limit:
                break
            article = json.loads(line)
            aid = _article_id(article['url'])
            if aid in done_ids:
                continue
            if args.dry_run:
                print(_build_prompt(article)[:500])
                continue
            label = _label_one(client, article, args.model)
            cum_cost += label['cost_usd']
            if cum_cost > args.max_cost_usd:
                logger.error(f"Budget exceeded ${cum_cost:.2f} > ${args.max_cost_usd}")
                sys.exit(1)
            f_out.write(json.dumps(label, ensure_ascii=False) + '\n')
            f_out.flush()
            logger.info(f"  [{i}] {aid[:8]} ${cum_cost:.3f} {label['ticker']} {label['sentiment']}")
```

### Key design points

1. **Resume checkpoint** — `--resume` default True. Reads output file, builds set of done `article_id`. Interrupt-safe (f_out.flush() every line).

2. **Error handling** — nếu Claude return không parse được JSON, retry 1 lần. Fail-silent → label `{..., sentiment: null, confidence: 0, rationale: "LLM parse error"}`, continue.

3. **Rate limit** — Anthropic default 50 req/min Tier 1. Add `time.sleep(0.5)` entre call để safe (gồm cả large payload latency).

4. **Content preprocessing** — strip markdown artifacts (regex `\[.*?\]\(.*?\)` cho links html2text) trước feed prompt.

5. **ensure_ascii=False** cho output — Vietnamese readable khi mở JSONL direct trong VSCode.

---

## 6. Validation (Day 1 chiều hoặc Day 2 sáng)

Sau label pilot 10 bài, verify:

### Smoke checks
- [ ] JSONL parsable, mỗi line valid JSON
- [ ] Schema fields đủ (10 required keys)
- [ ] `ticker` value ∈ VN30 roster ∪ {"VN30-INDEX", null}
- [ ] `event_type` ∈ 8 enum values
- [ ] `sentiment_magnitude` ∈ [1, 5]
- [ ] `confidence` ∈ [0, 1]
- [ ] Rationale tiếng Việt (không fallback English)

### Quality sanity (Ginny đọc 10 bài)
- [ ] Example VCB earnings → ticker VCB, event earnings, sentiment positive, magnitude 3-5
- [ ] Example crime news → is_relevant_vn30 false
- [ ] Example macro → ticker VN30-INDEX, event macro
- [ ] Confidence calibrated — low confidence cho ambiguous bài

### Nếu fail
- Prompt engineering refinement (add more few-shot, strengthen output schema example)
- Max 2 iterations trước Day 2 full-batch run

---

## 7. Day 2 full-batch run (sau pilot OK)

```bash
python scripts/label_articles_llm.py \
    --input data/sentiment_training/raw_articles.jsonl \
    --output data/sentiment_training/llm_labels.jsonl \
    --model claude-sonnet-4-5 \
    --max-cost-usd 10
```

Est wall time:
- 699 bài × ~5s latency = ~1h
- Rate limit 50 req/min → 699/50 × 60s = 839s = ~14 min minimum
- Realistic: 30-45 min với latency + retry

Có thể chạy foreground với tee log, hoặc background nohup.

---

## 8. Day 3-4 downstream (nếu PhoBERT win ADR-008)

- Export filtered `is_relevant_vn30=true` → PhoBERT training CSV
- 80/10/10 train/val/test stratified by ticker + event_type
- Baseline: naïve PhoBERT CLS → MLP head cho 3-class sentiment

Nếu RAG win:
- Index all 699 bài vào vector store (Chroma local)
- Metadata filter by (ticker, event_type, publish_time)
- Prompt-based inference tại query time

---

## 9. Reusable utilities

```python
# scripts/_common.py (có thể promote lên library sau Sprint 13)
def _ensure_utf8_streams():
    """M5: Windows Git Bash cp1252 → UTF-8 stdout."""
    import sys, contextlib
    with contextlib.suppress(Exception):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')

def _article_id(url: str) -> str:
    """Deterministic 16-hex ID from URL."""
    import hashlib
    return hashlib.sha256(url.encode('utf-8')).hexdigest()[:16]

def _strip_markdown_artifacts(text: str) -> str:
    """Remove html2text leftovers."""
    import re
    # Strip markdown links: [text](url) → text
    text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)
    # Strip inline images: ![](url)
    text = re.sub(r'!\[[^\]]*\]\([^)]+\)', '', text)
    # Collapse excessive newlines
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()
```

---

## 10. Open questions (decide Day 1 pilot)

1. **Content truncation strategy** — 6000 chars (abstract-only) vs full? Trade-off: cost ($0.01 → $0.02/bài) vs quality.
2. **Multi-ticker article** — Nếu bài bàn 3 ticker ngang nhau, chọn `ticker` nào primary? → ticker đầu tiên trong title, hoặc dùng `null` + mentions.
3. **Confidence calibration** — Dùng raw LLM self-reported hay external verifier (second Haiku pass)? → Day 1 raw, Day 3+ polish.
4. **Entity NER** — Rely full LLM extraction hay post-hoc VietNER? → Day 1 LLM, Sprint 14 benchmark VietNER accuracy.

---

## Appendix — Memory lessons applied

- M1 (VSCode paste): Spec này write từ VSCode không heredoc
- M5 (UTF-8 streams): `_ensure_utf8_streams()` required Windows
- M7 (Settings mock): Pydantic `anthropic_api_key` SecretStr qua `get_settings()`
- M12 (post-paste ruff): Run ruff immediately sau Cowork paste
- M13 (branch first): Script code trên feature branch `feat/sprint13-day1-f3-corpus`
- M15 (check-ascii): spec file này ở `docs/` không bị check-ascii; nếu code có em-dash → sed strip
- M26 (API key): `.env` edit qua `code .env`, không paste terminal
- M34 (Windows terminal mislead): Dữ liệu clean nhưng terminal display confusing
