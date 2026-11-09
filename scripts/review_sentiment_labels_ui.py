"""Streamlit UI for manual review of 200 Phase C audit samples.

Workflow per sample:
  1. Load next unreviewed sample
  2. Display article URL + title + LLM-generated labels
  3. Auditor opens URL in browser -> read article -> judge
  4. For each field (ticker, relevance, sentiment, event_type), auditor
     choose: Agree / Disagree + optional corrected value
  5. Save decision -> audit_results.jsonl append (idempotent via article_id)

Usage: streamlit run scripts/review_sentiment_labels_ui.py
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import streamlit as st

SAMPLES_PATH = Path("data/sentiment_training/audit_samples.jsonl")
RESULTS_PATH = Path("data/sentiment_training/audit_results.jsonl")

SENTIMENT_OPTIONS = ["positive", "neutral", "negative"]
EVENT_TYPE_OPTIONS = ["macro", "regulatory", "earnings", "other"]


@st.cache_data(ttl=10)
def load_samples() -> list[dict]:
    with SAMPLES_PATH.open("r", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def load_results() -> dict:
    """Load existing audit results, keyed by article_id."""
    if not RESULTS_PATH.exists():
        return {}
    results = {}
    with RESULTS_PATH.open("r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                r = json.loads(line)
                results[r["article_id"]] = r
    return results


def append_result(result: dict):
    """Append audit result to JSONL. Rewrites if article_id exists."""
    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    existing = load_results()
    existing[result["article_id"]] = result
    with RESULTS_PATH.open("w", encoding="utf-8") as f:
        for r in existing.values():
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


# ============================================================
# UI
# ============================================================
st.set_page_config(
    page_title="Phase C Audit - Sentiment Labels Review",
    page_icon="?",
    layout="wide",
)

st.title("Phase C Audit - Review LLM Sentiment Labels")

samples = load_samples()
results = load_results()
total = len(samples)
reviewed = len(results)
pending_samples = [s for s in samples if s["article_id"] not in results]

# Progress bar
st.progress(
    reviewed / total if total else 0,
    text=f"Progress: {reviewed}/{total} reviewed . {len(pending_samples)} pending",
)

if not pending_samples:
    st.success(
        f"[DONE] All {total} samples reviewed! Run audit_sentiment_labels.py to compute metrics."
    )
    st.stop()

# Navigation: pick sample
col_nav1, col_nav2 = st.columns([3, 1])
with col_nav1:
    sample_idx = st.selectbox(
        "Select sample to review",
        options=list(range(len(pending_samples))),
        format_func=lambda i: f"#{i+1}/{len(pending_samples)} . {pending_samples[i]['article_id'][:12]} . "
        f"{pending_samples[i].get('sentiment', '-')} . "
        f"{'VN30' if pending_samples[i].get('is_relevant_vn30') else 'Other'}",
    )
with col_nav2:
    if st.button("[Skip] (keep as-is for now)"):
        sample = pending_samples[sample_idx]
        result = {
            "article_id": sample["article_id"],
            "skipped": True,
            "reviewed_at": datetime.now(UTC).isoformat(),
        }
        append_result(result)
        st.rerun()

sample = pending_samples[sample_idx]

st.divider()

# ============================================================
# Article metadata
# ============================================================
st.subheader("Article")

col_a, col_b = st.columns([2, 1])
with col_a:
    st.markdown(f"**URL**: {sample.get('url', 'N/A')}")
    st.markdown(f"**Article ID**: `{sample['article_id']}`")
    st.markdown(f"**Confidence LLM**: {sample.get('confidence', 0):.2f}")
with col_b:
    st.markdown(f"**Labeled at**: {sample.get('labeled_at', '')[:19]}")
    st.markdown(f"**Model**: {sample.get('model', '-')}")

st.info(
    "**Instructions**: Open URL in new tab -> read article -> compare with LLM labels below -> "
    "tick Agree or Disagree + enter corrected value if disagree."
)

st.divider()

# ============================================================
# LLM labels vs Auditor decisions
# ============================================================
st.subheader("LLM vs Auditor comparison")

col_llm, col_aud = st.columns(2)

with col_llm:
    st.markdown("### LLM labels")
    st.markdown(f"- **Relevant VN30**: `{sample.get('is_relevant_vn30')}`")
    st.markdown(f"- **Ticker**: `{sample.get('ticker') or 'None'}`")
    st.markdown(f"- **Ticker mentions**: `{sample.get('ticker_mentions', [])}`")
    st.markdown(f"- **Sentiment**: `{sample.get('sentiment')}`")
    st.markdown(f"- **Sentiment magnitude**: `{sample.get('sentiment_magnitude', 0)}`")
    st.markdown(f"- **Event type**: `{sample.get('event_type')}`")
    with st.expander("Rationale LLM"):
        st.write(sample.get("rationale", "N/A"))

with col_aud:
    st.markdown("### Auditor decisions")

    # Metric 1: Relevance VN30 (binary)
    rel_llm = sample.get("is_relevant_vn30")
    rel_aud = st.radio(
        "**H2 - Is relevant VN30?**",
        options=[True, False],
        index=0 if rel_llm else 1,
        horizontal=True,
        key=f"rel_{sample['article_id']}",
    )
    rel_match = rel_aud == rel_llm

    # Metric 2: Ticker (multi-select from VN30)
    VN30 = [
        "VCB",
        "FPT",
        "VHM",
        "VNM",
        "HPG",
        "VIC",
        "MSN",
        "GAS",
        "VRE",
        "MWG",
        "TCB",
        "BID",
        "CTG",
        "SSI",
        "VPB",
        "ACB",
        "MBB",
        "STB",
        "HDB",
        "PLX",
        "VIB",
        "SHB",
        "NVL",
        "VJC",
        "POW",
        "SAB",
        "GVR",
        "SSB",
        "VNG",
        "KDH",
    ]
    ticker_llm = sample.get("ticker") or ""
    ticker_mentions_llm = sample.get("ticker_mentions", [])
    ticker_aud = st.multiselect(
        "**H1 - Tickers mentioned (VN30 scope)**",
        options=["None"] + VN30,
        default=ticker_mentions_llm if ticker_mentions_llm else ["None"],
        key=f"ticker_{sample['article_id']}",
    )
    ticker_match = (
        set(ticker_aud) == set(ticker_mentions_llm)
        if ticker_mentions_llm
        else ticker_aud == ["None"]
    )

    # Metric 3: Sentiment
    sent_llm = sample.get("sentiment", "neutral")
    sent_aud = st.radio(
        "**H3 - Sentiment**",
        options=SENTIMENT_OPTIONS,
        index=SENTIMENT_OPTIONS.index(sent_llm) if sent_llm in SENTIMENT_OPTIONS else 1,
        horizontal=True,
        key=f"sent_{sample['article_id']}",
    )
    sent_match = sent_aud == sent_llm

    # Metric 4: Event type
    event_llm = sample.get("event_type", "other")
    event_aud = st.radio(
        "**H4 - Event type**",
        options=EVENT_TYPE_OPTIONS,
        index=EVENT_TYPE_OPTIONS.index(event_llm) if event_llm in EVENT_TYPE_OPTIONS else 3,
        horizontal=True,
        key=f"event_{sample['article_id']}",
    )
    event_match = event_aud == event_llm

    # Note field
    note = st.text_area(
        "Note (optional)",
        key=f"note_{sample['article_id']}",
        placeholder="Notes if any (edge case, ambiguous, LLM hallucination, ...)",
        height=68,
    )

st.divider()

# Match summary
col_m1, col_m2, col_m3, col_m4 = st.columns(4)
with col_m1:
    st.metric("Ticker (H1)", "[OK] Match" if ticker_match else "[X] Disagree")
with col_m2:
    st.metric("Relevance (H2)", "[OK] Match" if rel_match else "[X] Disagree")
with col_m3:
    st.metric("Sentiment (H3)", "[OK] Match" if sent_match else "[X] Disagree")
with col_m4:
    st.metric("Event (H4)", "[OK] Match" if event_match else "[X] Disagree")

# Submit button
if st.button("Save decision + Next sample", type="primary", use_container_width=True):
    result = {
        "article_id": sample["article_id"],
        "auditor_relevance": rel_aud,
        "auditor_tickers": ticker_aud if ticker_aud != ["None"] else [],
        "auditor_sentiment": sent_aud,
        "auditor_event": event_aud,
        "llm_relevance": rel_llm,
        "llm_tickers": ticker_mentions_llm,
        "llm_sentiment": sent_llm,
        "llm_event": event_llm,
        "match_h1_ticker": ticker_match,
        "match_h2_relevance": rel_match,
        "match_h3_sentiment": sent_match,
        "match_h4_event": event_match,
        "note": note,
        "reviewed_at": datetime.now(UTC).isoformat(),
    }
    append_result(result)
    st.success(f"Saved! Progressed to {reviewed + 1}/{total}")
    st.rerun()
