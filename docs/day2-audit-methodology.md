# Day 2 Audit Methodology — F3 Sentiment Labels

**Sprint 13 Day 2 (29/10/2026) · F3 Sentiment**
**Prerequisite:** Day 1 full-run output `data/sentiment_training/llm_labels.jsonl` (~699 labeled articles)
**Deliverable:** `data/sentiment_training/human_audit_200.jsonl` + agreement metrics report

---

## 1. Mục tiêu

Validate chất lượng Claude Sonnet 5-5 labels bằng human audit → đo inter-rater agreement để đưa evidence cho ADR-008 (PhoBERT vs RAG) deadline 30/10.

**Hypothesis cần test:**
- H1: Claude ticker extraction accuracy ≥ 90% trên bài có mention VN30
- H2: Claude is_relevant_vn30 filter precision ≥ 85% (ít false positive)
- H3: Claude sentiment agreement ≥ 70% weighted κ
- H4: Claude event_type categorization ≥ 75% agreement

**Gate ADR-008:**
- Nếu H1+H2+H3+H4 ≥ 3/4 PASS → **PhoBERT path** (labels đủ chất lượng training ground truth)
- Nếu < 3/4 PASS → **RAG path** (dùng Claude at inference thay vì train student model)

---

## 2. Sample selection

### Stratified random 200 bài

Lý do stratified: random đơn thuần có thể skew theo petrotimes (200 bài energy — overweight). Stratify by site + is_relevant_vn30 để audit balanced.

```python
# scripts/select_audit_sample.py
import json
import random
from collections import defaultdict
from pathlib import Path

random.seed(42)  # reproducibility
labels = [json.loads(l) for l in open('data/sentiment_training/llm_labels.jsonl', encoding='utf-8')]

# Bucket: (site, is_relevant_vn30) → list
buckets = defaultdict(list)
for lbl in labels:
    url = lbl['url']
    site = next((s for s in ['cafef', 'cafebiz', 'nguoiquansat', 'thoibaotaichinhvietnam', 'dddn', 'petrotimes'] if s in url), 'unknown')
    buckets[(site, lbl['is_relevant_vn30'])].append(lbl)

# Target: 200 total, split 60/40 relevant/irrelevant across sites
TARGET_RELEVANT = 80   # oversample relevant (sparse)
TARGET_IRRELEVANT = 120
sites = ['cafef', 'cafebiz', 'nguoiquansat', 'thoibaotaichinhvietnam', 'dddn', 'petrotimes']
per_site_relevant = TARGET_RELEVANT // len(sites)      # ~13 each
per_site_irrelevant = TARGET_IRRELEVANT // len(sites)  # ~20 each

sample = []
for site in sites:
    rel = buckets.get((site, True), [])
    irr = buckets.get((site, False), [])
    sample.extend(random.sample(rel, min(per_site_relevant, len(rel))))
    sample.extend(random.sample(irr, min(per_site_irrelevant, len(irr))))

# Pad if short
remaining = 200 - len(sample)
pool = [l for l in labels if l not in sample]
sample.extend(random.sample(pool, min(remaining, len(pool))))

Path('data/sentiment_training').mkdir(parents=True, exist_ok=True)
with open('data/sentiment_training/audit_sample.jsonl', 'w', encoding='utf-8') as f:
    for lbl in sample[:200]:
        f.write(json.dumps(lbl, ensure_ascii=False) + '\n')
print(f"Sample size: {len(sample[:200])}")
```

### Fallback nếu relevance thực tế <10%
Nếu Day 1 full-run cho relevance rate <10% → relevant bucket <70 bài, không đủ 80. Giải pháp:
- Giảm target 60 relevant + 140 irrelevant (vẫn đủ κ reliability)
- Hoặc expand corpus Opt3 vietstock patch trước

---

## 3. Audit UI — Streamlit mini-app

### Lựa chọn tool

| Option | Pro | Con | Pick |
|---|---|---|---|
| Jupyter notebook cell-by-cell | Zero setup | Keyboard shortcut awkward, no save/resume | ✗ |
| **Streamlit mini-app** | Keyboard shortcut, auto-save, progress bar, native Vietnamese | 50 line code setup | **✓** |
| Google Sheets manual | Collaborative | No programmatic validation, slow | ✗ |

### Streamlit audit skeleton `scripts/audit_labels.py`

```python
import json
import streamlit as st
from pathlib import Path

AUDIT_INPUT = Path('data/sentiment_training/audit_sample.jsonl')
AUDIT_OUTPUT = Path('data/sentiment_training/human_audit_200.jsonl')

@st.cache_data
def load_samples():
    return [json.loads(l) for l in open(AUDIT_INPUT, encoding='utf-8')]

def load_done_ids():
    if not AUDIT_OUTPUT.exists():
        return set()
    return {json.loads(l)['article_id'] for l in open(AUDIT_OUTPUT, encoding='utf-8')}

st.set_page_config(page_title="F3 Label Audit", layout="wide")
samples = load_samples()
done_ids = load_done_ids()
pending = [s for s in samples if s['article_id'] not in done_ids]
st.sidebar.metric("Progress", f"{len(done_ids)}/{len(samples)}")
st.sidebar.progress(len(done_ids) / len(samples))

if not pending:
    st.success("All done!")
    st.stop()

current = pending[0]
col1, col2 = st.columns([2, 1])

with col1:
    st.subheader(current['url'].split('/')[-1][:60])
    with st.expander("Full URL + content", expanded=False):
        st.markdown(f"**URL:** {current['url']}")
    # Fetch original content from raw_articles.jsonl
    for raw in open('data/sentiment_training/raw_articles.jsonl', encoding='utf-8'):
        raw_a = json.loads(raw)
        if raw_a['url'] == current['url']:
            st.markdown(f"**Title:** {raw_a['title']}")
            st.markdown(f"**Content:**\n\n{raw_a['content'][:3000]}")
            break

with col2:
    st.markdown("### Claude label")
    st.json({
        'ticker': current['ticker'],
        'ticker_mentions': current['ticker_mentions'],
        'event_type': current['event_type'],
        'sentiment': current['sentiment'],
        'sentiment_magnitude': current['sentiment_magnitude'],
        'is_relevant_vn30': current['is_relevant_vn30'],
        'confidence': current['confidence'],
        'rationale': current['rationale'],
    })

    st.markdown("### Human verdict")
    agree_overall = st.radio("Overall agree?", ['Yes', 'Partial', 'No'], horizontal=True)
    disagree_fields = st.multiselect(
        "Fields disagree (if partial/no):",
        ['ticker', 'ticker_mentions', 'event_type', 'sentiment', 'magnitude', 'is_relevant_vn30'],
    )
    correct_ticker = st.text_input("Corrected ticker (nếu disagree)", value=current['ticker'] or '')
    correct_sentiment = st.selectbox(
        "Corrected sentiment",
        ['positive', 'neutral', 'negative'],
        index=['positive', 'neutral', 'negative'].index(current['sentiment']) if current['sentiment'] else 1,
    )
    notes = st.text_area("Notes (optional)")

    if st.button("Save & Next", type="primary"):
        audit_record = {
            **current,
            'human_agree_overall': agree_overall,
            'human_disagree_fields': disagree_fields,
            'human_correct_ticker': correct_ticker or None,
            'human_correct_sentiment': correct_sentiment,
            'human_notes': notes,
            'audited_at': __import__('datetime').datetime.now(__import__('datetime').UTC).isoformat(),
        }
        with open(AUDIT_OUTPUT, 'a', encoding='utf-8', newline='\n') as f:
            f.write(json.dumps(audit_record, ensure_ascii=False) + '\n')
        st.rerun()
```

### Chạy audit UI
```bash
streamlit run scripts/audit_labels.py --server.port 8502
# Browser: http://localhost:8502
```

### Est thời gian audit
- 200 bài × ~45s/bài (read article + verify label + decide) = ~2.5 giờ
- Có thể split 2-3 session (100 bài/session tránh fatigue)

---

## 4. Metrics computation `scripts/compute_audit_metrics.py`

### Metrics định nghĩa

| Metric | Formula | Threshold PASS |
|---|---|---|
| **H1** Ticker exact match | correct_ticker / (relevant & has_ticker) | ≥ 0.90 |
| **H2** Relevance precision | TP_relevant / (TP_relevant + FP_relevant) | ≥ 0.85 |
| **H3** Sentiment Cohen's κ | sklearn.metrics.cohen_kappa_score | ≥ 0.70 |
| **H4** Event_type accuracy | correct_event / total_audited | ≥ 0.75 |

### Script skeleton

```python
import json
from collections import Counter
from sklearn.metrics import cohen_kappa_score, precision_recall_fscore_support

records = [json.loads(l) for l in open('data/sentiment_training/human_audit_200.jsonl', encoding='utf-8')]
total = len(records)
print(f"Audit n = {total}")

# H1 Ticker
tp_tkr = sum(1 for r in records if r['is_relevant_vn30'] and r['ticker'] == r['human_correct_ticker'])
den_tkr = sum(1 for r in records if r['is_relevant_vn30'] and r['ticker'])
h1 = tp_tkr / den_tkr if den_tkr else 0
print(f"H1 Ticker exact match: {h1:.3f} ({tp_tkr}/{den_tkr}) {'PASS' if h1 >= 0.90 else 'FAIL'}")

# H2 Relevance precision
tp_rel = sum(1 for r in records if r['is_relevant_vn30'] and 'is_relevant_vn30' not in r['human_disagree_fields'])
fp_rel = sum(1 for r in records if r['is_relevant_vn30'] and 'is_relevant_vn30' in r['human_disagree_fields'])
h2 = tp_rel / (tp_rel + fp_rel) if (tp_rel + fp_rel) else 0
print(f"H2 Relevance precision: {h2:.3f} ({tp_rel}/{tp_rel+fp_rel}) {'PASS' if h2 >= 0.85 else 'FAIL'}")

# H3 Sentiment κ
claude_sent = [r['sentiment'] for r in records if r['sentiment']]
human_sent = [r['human_correct_sentiment'] for r in records if r['sentiment']]
h3 = cohen_kappa_score(claude_sent, human_sent)
print(f"H3 Sentiment Cohen's κ: {h3:.3f} {'PASS' if h3 >= 0.70 else 'FAIL'}")

# H4 Event_type (approximate: not in disagree list)
h4_correct = sum(1 for r in records if 'event_type' not in r['human_disagree_fields'])
h4 = h4_correct / total
print(f"H4 Event_type accuracy: {h4:.3f} {'PASS' if h4 >= 0.75 else 'FAIL'}")

# Gate ADR-008
pass_count = sum([h1 >= 0.90, h2 >= 0.85, h3 >= 0.70, h4 >= 0.75])
print(f"\nGate ADR-008: {pass_count}/4 PASS -> {'PhoBERT path' if pass_count >= 3 else 'RAG path'}")
```

---

## 5. Discrepancy taxonomy

Phân loại disagreement patterns để Day 3+ prompt refinement:

| Category | Example | Fix pattern |
|---|---|---|
| **Over-reject** | Claude is_relevant_vn30=False cho bài VN30 regulatory | Weaken rejection threshold prompt |
| **Under-reject** | Claude is_relevant_vn30=True cho bài CT3 (non-VN30 ticker) | Strengthen VN30 roster check |
| **Wrong primary ticker** | Bài bàn VCB+BID bằng nhau, Claude pick BID | Clarify ">60% focus" rule in prompt |
| **Sentiment flip** | Dividend ex-date Claude=positive, human=neutral | Add ex-date rule to few-shot |
| **Event mis-cat** | insider trading classified "regulatory" | Add insider definition rule |

---

## 6. Timeline Day 2 (29/10 Thứ 3)

```
08:30-09:00  Run select_audit_sample.py + review 200 selected bài
09:00-11:00  Audit batch 1 (100 bài, ~1.5h effective)
11:00-11:30  Break
13:30-15:00  Audit batch 2 (100 bài)
15:00-15:30  Run compute_audit_metrics.py + review gate
15:30-16:00  Document findings → draft ADR-008 evidence table
16:00+       Discrepancy analysis + prompt refinement OR start ADR-008 draft
```

Total: ~5-6h effective. Fit weekday base extended mode.

---

## 7. Fallback nếu audit cho tín hiệu phức tạp

### If 2/4 PASS, 2/4 marginal fail
- Re-prompt với refinement based on top-3 discrepancy categories
- Re-label 100 bài subset → re-audit 50-sample
- Decide path Day 4

### If < 2/4 PASS
- RAG path mặc định (Claude at inference, no student training)
- Skip Sprint 14 PhoBERT fine-tune → polish RAG pipeline Sprint 14-15
- ADR-008 locked "RAG only"

### If 4/4 PASS strong
- PhoBERT path confident
- Sprint 14 start fine-tune với 80/10/10 split của ~70-100 relevant labels (data augmentation nếu < 100)
