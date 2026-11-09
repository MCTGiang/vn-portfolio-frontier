"""Compute 4 metrics H1-H4 from audit_results.jsonl.

Metrics:
  H1: Ticker F1 (binary multi-label) - target >= 0.90
  H2: Relevance accuracy (binary) - target >= 0.85
  H3: Sentiment Cohen's kappa (3-class) - target >= 0.70
  H4: Event type F1 macro-avg (4-class) - target >= 0.75

Output: Terminal report + JSON summary for pasting into Chapter 6 section 6.4.4.

Usage: python scripts/audit_sentiment_labels.py
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

RESULTS_PATH = Path("data/sentiment_training/audit_results.jsonl")

# Target thresholds
TARGETS = {
    "H1": 0.90,
    "H2": 0.85,
    "H3": 0.70,
    "H4": 0.75,
}


def load_results() -> list[dict]:
    if not RESULTS_PATH.exists():
        print(f"[ERROR] {RESULTS_PATH} not found. Run review UI first.")
        return []
    with RESULTS_PATH.open("r", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def compute_cohens_kappa(y_llm: list, y_aud: list) -> float:
    """Compute Cohen's kappa for categorical agreement."""
    if len(y_llm) != len(y_aud) or not y_llm:
        return 0.0
    categories = sorted(set(y_llm) | set(y_aud))
    n = len(y_llm)
    # Observed agreement
    po = sum(1 for a, b in zip(y_llm, y_aud, strict=True) if a == b) / n
    # Expected agreement
    pe = 0.0
    for cat in categories:
        p_llm = sum(1 for x in y_llm if x == cat) / n
        p_aud = sum(1 for x in y_aud if x == cat) / n
        pe += p_llm * p_aud
    if pe >= 1.0:
        return 1.0
    return (po - pe) / (1 - pe)


def compute_f1_binary(y_true: list[bool], y_pred: list[bool]) -> float:
    """Compute F1 for binary classification."""
    tp = sum(1 for t, p in zip(y_true, y_pred, strict=True) if t and p)
    fp = sum(1 for t, p in zip(y_true, y_pred, strict=True) if not t and p)
    fn = sum(1 for t, p in zip(y_true, y_pred, strict=True) if t and not p)
    if tp + fp == 0 or tp + fn == 0:
        return 0.0
    precision = tp / (tp + fp)
    recall = tp / (tp + fn)
    if precision + recall == 0:
        return 0.0
    return 2 * precision * recall / (precision + recall)


def compute_f1_macro(y_true: list[str], y_pred: list[str]) -> float:
    """Compute macro-averaged F1 for multi-class."""
    classes = sorted(set(y_true) | set(y_pred))
    f1_per_class = []
    for cls in classes:
        y_true_bin = [t == cls for t in y_true]
        y_pred_bin = [p == cls for p in y_pred]
        f1_per_class.append(compute_f1_binary(y_true_bin, y_pred_bin))
    return sum(f1_per_class) / len(f1_per_class) if f1_per_class else 0.0


def compute_multilabel_f1(y_true: list[list[str]], y_pred: list[list[str]]) -> float:
    """Compute F1 for multi-label (ticker lists)."""
    tp, fp, fn = 0, 0, 0
    for true_set, pred_set in zip(y_true, y_pred, strict=True):
        true_set = set(true_set)
        pred_set = set(pred_set)
        tp += len(true_set & pred_set)
        fp += len(pred_set - true_set)
        fn += len(true_set - pred_set)
    if tp + fp == 0 or tp + fn == 0:
        return 0.0
    precision = tp / (tp + fp)
    recall = tp / (tp + fn)
    if precision + recall == 0:
        return 0.0
    return 2 * precision * recall / (precision + recall)


def main():
    results = load_results()
    results = [r for r in results if not r.get("skipped")]

    if not results:
        print("[ERROR] No audit results found.")
        return

    n = len(results)
    print(f"Phase C Audit Metrics - N = {n} samples")
    print("=" * 70)

    # H1: Ticker F1 (multi-label)
    y_llm_tickers = [r.get("llm_tickers", []) for r in results]
    y_aud_tickers = [r.get("auditor_tickers", []) for r in results]
    h1_f1 = compute_multilabel_f1(y_aud_tickers, y_llm_tickers)
    h1_pass = h1_f1 >= TARGETS["H1"]
    print(
        f"H1 Ticker F1 (multi-label):     {h1_f1:.3f}  {'[PASS]' if h1_pass else '[ERROR] FAIL'}  (target >= {TARGETS['H1']})"
    )

    # H2: Relevance accuracy
    y_llm_rel = [r["llm_relevance"] for r in results]
    y_aud_rel = [r["auditor_relevance"] for r in results]
    h2_acc = sum(1 for a, b in zip(y_llm_rel, y_aud_rel, strict=True) if a == b) / n
    h2_pass = h2_acc >= TARGETS["H2"]
    print(
        f"H2 Relevance accuracy:          {h2_acc:.3f}  {'[PASS]' if h2_pass else '[ERROR] FAIL'}  (target >= {TARGETS['H2']})"
    )

    # H3: Sentiment Cohen kappa
    y_llm_sent = [r["llm_sentiment"] for r in results]
    y_aud_sent = [r["auditor_sentiment"] for r in results]
    h3_kappa = compute_cohens_kappa(y_llm_sent, y_aud_sent)
    h3_pass = h3_kappa >= TARGETS["H3"]
    print(
        f"H3 Sentiment Cohen's kappa:         {h3_kappa:.3f}  {'[PASS]' if h3_pass else '[ERROR] FAIL'}  (target >= {TARGETS['H3']})"
    )

    # H4: Event type F1 macro
    y_llm_event = [r["llm_event"] for r in results]
    y_aud_event = [r["auditor_event"] for r in results]
    h4_f1 = compute_f1_macro(y_aud_event, y_llm_event)
    h4_pass = h4_f1 >= TARGETS["H4"]
    print(
        f"H4 Event type F1 macro:         {h4_f1:.3f}  {'[PASS]' if h4_pass else '[ERROR] FAIL'}  (target >= {TARGETS['H4']})"
    )

    print("=" * 70)
    pass_count = sum([h1_pass, h2_pass, h3_pass, h4_pass])
    print(f"Total: {pass_count}/4 metrics PASS")

    # Breakdown by sentiment
    print()
    print("Distribution:")
    sent_counts_llm = Counter(y_llm_sent)
    sent_counts_aud = Counter(y_aud_sent)
    for sent in ["positive", "neutral", "negative"]:
        print(
            f"  {sent:10s}: LLM {sent_counts_llm.get(sent, 0):3d} . Auditor {sent_counts_aud.get(sent, 0):3d}"
        )

    # Save summary JSON
    summary_path = Path("data/sentiment_training/audit_metrics_summary.json")
    summary = {
        "N": n,
        "H1_ticker_f1": round(h1_f1, 4),
        "H2_relevance_accuracy": round(h2_acc, 4),
        "H3_sentiment_kappa": round(h3_kappa, 4),
        "H4_event_f1_macro": round(h4_f1, 4),
        "pass_count": pass_count,
        "targets": TARGETS,
    }
    with summary_path.open("w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print(f"\nSummary saved: {summary_path}")


if __name__ == "__main__":
    main()
