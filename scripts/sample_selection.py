"""Select 200 stratified samples from 699 LLM labels for Phase C audit.

Strategy:
  - 100 relevant samples (is_relevant_vn30=True): all 106 -> take first 100
  - 100 non-relevant samples (is_relevant_vn30=False): stratify by sentiment
    (positive/neutral/negative) proportional to population

Output: data/sentiment_training/audit_samples.jsonl (200 samples subset)
"""

from __future__ import annotations

import json
import random
from pathlib import Path

RANDOM_SEED = 42
TOTAL_SAMPLES = 200
LABELS_PATH = Path("data/sentiment_training/llm_labels.jsonl")
OUTPUT_PATH = Path("data/sentiment_training/audit_samples.jsonl")


def load_labels(path: Path) -> list[dict]:
    labels = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                labels.append(json.loads(line))
    return labels


def stratified_sample(labels: list[dict]) -> list[dict]:
    """Stratified selection: 100 relevant + 100 non-relevant."""
    rng = random.Random(RANDOM_SEED)

    relevant = [item for item in labels if item.get("is_relevant_vn30") is True]
    non_relevant = [item for item in labels if item.get("is_relevant_vn30") is False]

    print(f"Pool: {len(relevant)} relevant . {len(non_relevant)} non-relevant")

    # Take 100 relevant (random from 106)
    n_relevant_target = min(100, len(relevant))
    rng.shuffle(relevant)
    sample_relevant = relevant[:n_relevant_target]

    # Take 100 non-relevant stratified by sentiment
    non_relevant_by_sent = {"positive": [], "neutral": [], "negative": []}
    for item in non_relevant:
        s = item.get("sentiment", "neutral")
        non_relevant_by_sent.setdefault(s, []).append(item)

    total_non_rel = sum(len(v) for v in non_relevant_by_sent.values())
    n_remaining = TOTAL_SAMPLES - n_relevant_target
    sample_non_relevant = []
    for _sent, items in non_relevant_by_sent.items():
        n_target = int(round(n_remaining * len(items) / total_non_rel)) if total_non_rel > 0 else 0
        rng.shuffle(items)
        sample_non_relevant.extend(items[:n_target])

    # Trim/pad to exactly 100 non-relevant
    sample_non_relevant = sample_non_relevant[:n_remaining]

    combined = sample_relevant + sample_non_relevant
    rng.shuffle(combined)
    return combined


def main():
    print(f"Loading from {LABELS_PATH}...")
    labels = load_labels(LABELS_PATH)
    print(f"Loaded {len(labels)} labels")

    samples = stratified_sample(labels)
    print(f"Selected {len(samples)} samples")

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_PATH.open("w", encoding="utf-8") as f:
        for s in samples:
            f.write(json.dumps(s, ensure_ascii=False) + "\n")

    print(f"Wrote {OUTPUT_PATH}")
    print()
    print("Breakdown:")
    rel_count = sum(1 for s in samples if s.get("is_relevant_vn30"))
    print(f"  Relevant VN30: {rel_count}")
    print(f"  Non-relevant: {len(samples) - rel_count}")
    sent_counts = {}
    for s in samples:
        sent = s.get("sentiment", "unknown")
        sent_counts[sent] = sent_counts.get(sent, 0) + 1
    for sent, n in sorted(sent_counts.items()):
        print(f"  {sent}: {n}")


if __name__ == "__main__":
    main()
