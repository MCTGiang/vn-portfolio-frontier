"""Label articles with Claude API for F3 sentiment training (Sprint 13 Day 1).

Reads raw articles from JSONL, calls Claude API to extract structured labels
(ticker, event_type, sentiment, magnitude, entities), writes labels to JSONL.

Schema per phase_b_label_spec.md:
    article_id, url, ticker, ticker_mentions, event_type, sentiment,
    sentiment_magnitude, entities, rationale, is_relevant_vn30, confidence,
    model, labeled_at, input_tokens, output_tokens, cost_usd

Related: ADR-006 (F3 structured signal extraction), ADR-008 (PhoBERT vs RAG),
         docs/phase-b-label-spec.md

Usage:
    # Dry-run: print prompt for 3 articles, no API call
    python scripts/label_articles_llm.py --limit 3 --dry-run

    # Pilot: label 5 articles with Sonnet (~$0.05)
    python scripts/label_articles_llm.py --limit 5

    # Full batch: label all 699 articles (~$7 Sonnet)
    python scripts/label_articles_llm.py --max-cost-usd 10

    # Haiku ablation (cheaper, Sprint 14 comparison)
    python scripts/label_articles_llm.py --model claude-haiku-5-5
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import logging
import os
import re
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from dotenv import load_dotenv

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

# VN30 roster (sync with Reference().index.members("VN30") quarterly)
VN30_ROSTER = {
    "VCB",
    "VHM",
    "VIC",
    "VNM",
    "VRE",
    "SAB",
    "BID",
    "BVH",
    "CTG",
    "EIB",
    "FPT",
    "GAS",
    "GVR",
    "HDB",
    "HPG",
    "MBB",
    "MSN",
    "MWG",
    "NVL",
    "PDR",
    "PLX",
    "POW",
    "SHB",
    "SSB",
    "SSI",
    "STB",
    "TCB",
    "TPB",
    "VIB",
    "VJC",
}

# Pricing per 1M tokens (verify at https://claude.com/pricing on first run)
MODEL_PRICING = {
    "claude-sonnet-5-5": {"input": 3.0, "output": 15.0},
    "claude-haiku-5-5": {"input": 1.0, "output": 5.0},
}

EVENT_TYPES = {
    "earnings",
    "dividend",
    "ma",
    "insider",
    "regulatory",
    "macro",
    "litigation",
    "other",
}
SENTIMENTS = {"positive", "neutral", "negative"}

DEFAULT_INPUT = Path("data/sentiment_training/raw_articles.jsonl")
DEFAULT_OUTPUT = Path("data/sentiment_training/llm_labels.jsonl")
DEFAULT_MODEL = "claude-sonnet-5-5"
DEFAULT_MAX_COST = 10.0
DEFAULT_CONTENT_MAX_CHARS = 6000
RATE_LIMIT_SLEEP_SECONDS = 0.5  # Anthropic Tier 1 default 50 req/min

SYSTEM_PROMPT = """Ban la chuyen gia phan tich tin tuc tai chinh Viet Nam cho ro VN30.

Nhiem vu: Phan tich 1 bai bao tieng Viet va trich xuat signal co cau truc theo schema JSON.

Output BAT BUOC la 1 JSON object hop le (khong kem text giai thich ngoai JSON, khong markdown code block).
Moi truong "rationale" viet TIENG VIET.

VN30 roster: VCB VHM VIC VNM VRE SAB BID BVH CTG EIB FPT GAS GVR HDB HPG MBB MSN MWG NVL PDR PLX POW SHB SSB SSI STB TCB TPB VIB VJC

Quy tac trich ticker:
- ticker = ma VN30 PRIMARY CHI KHI bai co >60% content focus 1 ma (title + doan dau khang dinh)
- ticker = "VN30-INDEX" neu macro/sector affecting toan thi truong
- ticker = null neu bai ban nganh/sector/nhieu ma bang nhau hoac khong lien quan VN30
- ticker_mentions = TAT CA ma VN30 duoc nhac (co the rong)

event_type:
- earnings: Bao cao tai chinh, loi nhuan
- dividend: Co tuc, chia tach, phat hanh
- ma: M&A, sap nhap, thau tom
- insider: Giao dich co dong noi bo, ban lanh dao
- regulatory: UBCKNN, SBV, HSX quy dinh / xu phat
- macro: Vi mo (lai suat, GDP, ty gia, FDI)
- litigation: Kien tung, tranh chap phap ly
- other: Khac (bao gom non-finance neu is_relevant_vn30=false)

sentiment nhin goc do GIA CO PHIEU:
- positive: Tin tot, gia ky vong tang
- neutral: Trung tinh, khong anh huong ro
- negative: Tin xau, gia ky vong giam

Vi du chuan:

INPUT: VCB bao lai quy 3/2026 dat 12.500 ty dong, tang 18% YoY vuot ky vong
OUTPUT: {"ticker":"VCB","ticker_mentions":["VCB"],"event_type":"earnings","sentiment":"positive","sentiment_magnitude":4,"entities":{"persons":[],"orgs":["Vietcombank"],"amounts":["12.500 ty dong","18% YoY"]},"rationale":"VCB bao lai vuot ky vong 18%, tich cuc cho gia co phieu.","is_relevant_vn30":true,"confidence":0.92}

INPUT: Diem lai loat xe sang bi thu giu trong vu an Mr Pips (bai ve vu an hinh su)
OUTPUT: {"ticker":null,"ticker_mentions":[],"event_type":"other","sentiment":"neutral","sentiment_magnitude":1,"entities":{"persons":["Pho Duc Nam"],"orgs":[],"amounts":["1.560 ty dong"]},"rationale":"Bai ve vu an hinh su, khong lien quan trading VN30.","is_relevant_vn30":false,"confidence":0.98}

INPUT: SBV dieu chinh tang lai suat tai cap von 25bps len 4,75%
OUTPUT: {"ticker":"VN30-INDEX","ticker_mentions":[],"event_type":"macro","sentiment":"negative","sentiment_magnitude":3,"entities":{"persons":[],"orgs":["SBV"],"amounts":["25bps","4,75%"]},"rationale":"Nang lai suat dieu hanh gay ap luc chi phi von, tieu cuc ngan han cho VN30 banking.","is_relevant_vn30":true,"confidence":0.88}"""

USER_PROMPT_TEMPLATE = """# Bai bao can phan tich

Nguon: {site}
Thoi gian xuat ban: {publish_time}
Tieu de: {title}

Noi dung:
{content}

Tra ve JSON object theo schema (khong kem text ngoai JSON, khong markdown wrapper):
{{"ticker": null, "ticker_mentions": [], "event_type": "...", "sentiment": "...", "sentiment_magnitude": 1-5, "entities": {{"persons": [], "orgs": [], "amounts": []}}, "rationale": "...", "is_relevant_vn30": true, "confidence": 0.0-1.0}}"""


def _ensure_utf8_streams() -> None:
    """M5: Windows Git Bash cp1252 -> UTF-8 stdout."""
    with contextlib.suppress(Exception):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    with contextlib.suppress(Exception):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")


def _article_id(url: str) -> str:
    """Deterministic 16-hex ID from URL (dedup key)."""
    return hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]


def _strip_markdown_artifacts(text: str) -> str:
    """Remove html2text leftovers before LLM feed."""
    text = re.sub(r"!\[[^\]]*\]\([^)]+\)", "", text)  # images
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)  # links -> text
    text = re.sub(r"\n{3,}", "\n\n", text)  # collapse newlines
    return text.strip()


def _load_done_ids(output_path: Path) -> set[str]:
    """Resume checkpoint: read existing labels, build set of done article_ids."""
    if not output_path.exists():
        return set()
    done: set[str] = set()
    with open(output_path, encoding="utf-8") as f:
        for line in f:
            with contextlib.suppress(Exception):
                done.add(json.loads(line)["article_id"])
    return done


def _build_user_prompt(article: dict, max_chars: int) -> str:
    content = _strip_markdown_artifacts(article.get("content", ""))
    if len(content) > max_chars:
        content = content[:max_chars] + "\n[... truncated]"
    return USER_PROMPT_TEMPLATE.format(
        site=article.get("site", ""),
        publish_time=article.get("publish_time", ""),
        title=article.get("title", ""),
        content=content,
    )


def _validate_label(label: dict) -> dict:
    """Clamp invalid fields; log warnings; never crash."""
    ticker = label.get("ticker")
    if ticker and ticker != "VN30-INDEX" and ticker not in VN30_ROSTER:
        logger.warning(f"  Invalid ticker '{ticker}' -> null")
        label["ticker"] = None
    mentions = label.get("ticker_mentions", []) or []
    label["ticker_mentions"] = [t for t in mentions if t in VN30_ROSTER]
    if label.get("event_type") not in EVENT_TYPES:
        label["event_type"] = "other"
    if label.get("sentiment") not in SENTIMENTS:
        label["sentiment"] = "neutral"
    try:
        mag = int(label.get("sentiment_magnitude", 1))
        label["sentiment_magnitude"] = max(1, min(5, mag))
    except (TypeError, ValueError):
        label["sentiment_magnitude"] = 1
    try:
        conf = float(label.get("confidence", 0.0))
        label["confidence"] = max(0.0, min(1.0, conf))
    except (TypeError, ValueError):
        label["confidence"] = 0.0
    ent = label.get("entities", {}) or {}
    label["entities"] = {
        "persons": ent.get("persons", []) or [],
        "orgs": ent.get("orgs", []) or [],
        "amounts": ent.get("amounts", []) or [],
    }
    label["is_relevant_vn30"] = bool(label.get("is_relevant_vn30", False))
    if not label.get("rationale"):
        label["rationale"] = ""
    return label


def _label_one(client, article: dict, model: str, content_max_chars: int) -> dict:
    """Call Claude API, parse JSON, validate. Return label with cost tracking."""
    user_prompt = _build_user_prompt(article, content_max_chars)
    try:
        response = client.messages.create(
            model=model,
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
        )
    except Exception as e:
        logger.error(f"  API error: {type(e).__name__}: {str(e)[:120]}")
        return _error_label(article, model, str(e))

    text = next((b.text.strip() for b in response.content if hasattr(b, "text")), "")
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.MULTILINE).strip()
    try:
        label_core = json.loads(text)
    except json.JSONDecodeError as e:
        logger.warning(f"  JSON parse failed: {e}; raw: {text[:200]}")
        return _error_label(article, model, f"JSON parse: {e}")

    label_core = _validate_label(label_core)

    pricing = MODEL_PRICING.get(model, {"input": 3.0, "output": 15.0})
    cost_usd = (
        response.usage.input_tokens * pricing["input"] / 1_000_000
        + response.usage.output_tokens * pricing["output"] / 1_000_000
    )

    label_core.update(
        {
            "article_id": _article_id(article["url"]),
            "url": article["url"],
            "model": model,
            "labeled_at": datetime.now(UTC).isoformat(),
            "input_tokens": response.usage.input_tokens,
            "output_tokens": response.usage.output_tokens,
            "cost_usd": round(cost_usd, 6),
        }
    )
    return label_core


def _error_label(article: dict, model: str, error_msg: str) -> dict:
    """Fallback label for API/parse errors; keeps pipeline moving."""
    return {
        "article_id": _article_id(article["url"]),
        "url": article["url"],
        "ticker": None,
        "ticker_mentions": [],
        "event_type": "other",
        "sentiment": None,
        "sentiment_magnitude": 1,
        "entities": {"persons": [], "orgs": [], "amounts": []},
        "rationale": f"LABEL ERROR: {error_msg[:200]}",
        "is_relevant_vn30": False,
        "confidence": 0.0,
        "model": model,
        "labeled_at": datetime.now(UTC).isoformat(),
        "input_tokens": 0,
        "output_tokens": 0,
        "cost_usd": 0.0,
        "error": True,
    }


def main() -> int:
    _ensure_utf8_streams()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--model", default=DEFAULT_MODEL, choices=list(MODEL_PRICING.keys()))
    parser.add_argument("--limit", type=int, default=None, help="Label only first N articles")
    parser.add_argument("--max-cost-usd", type=float, default=DEFAULT_MAX_COST)
    parser.add_argument("--content-max-chars", type=int, default=DEFAULT_CONTENT_MAX_CHARS)
    parser.add_argument("--no-resume", action="store_true", help="Overwrite existing labels")
    parser.add_argument("--dry-run", action="store_true", help="Print prompt without API call")
    args = parser.parse_args()

    load_dotenv(".env")
    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key and not args.dry_run:
        logger.error("ANTHROPIC_API_KEY not set in .env")
        return 1

    if not args.input.exists():
        logger.error(f"Input file not found: {args.input}")
        return 1

    done_ids = set() if args.no_resume else _load_done_ids(args.output)
    if done_ids:
        logger.info(f"Resume: {len(done_ids)} article(s) already labeled, will skip")

    client = None
    if not args.dry_run:
        import anthropic

        client = anthropic.Anthropic(api_key=api_key)

    logger.info(
        f"Config: model={args.model}, limit={args.limit}, max_cost=${args.max_cost_usd}, "
        f"content_max_chars={args.content_max_chars}, dry_run={args.dry_run}"
    )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    cum_cost = 0.0
    labeled_count = 0
    with (
        open(args.input, encoding="utf-8") as f_in,
        open(args.output, "a", encoding="utf-8", newline="\n") as f_out,
    ):
        for i, line in enumerate(f_in, 1):
            if args.limit and labeled_count >= args.limit:
                break
            article = json.loads(line)
            aid = _article_id(article["url"])
            if aid in done_ids:
                continue
            if args.dry_run:
                prompt = _build_user_prompt(article, args.content_max_chars)
                print(f"\n=== Article [{i}] {aid} ===")
                print(f"Title: {article.get('title', '')[:100]}")
                print(f"Prompt preview (first 500 chars):\n{prompt[:500]}")
                print("---")
                labeled_count += 1
                continue
            if cum_cost >= args.max_cost_usd:
                logger.error(f"Budget exceeded ${cum_cost:.4f} >= ${args.max_cost_usd}")
                return 1
            label = _label_one(client, article, args.model, args.content_max_chars)
            cum_cost += label.get("cost_usd", 0.0)
            f_out.write(json.dumps(label, ensure_ascii=False) + "\n")
            f_out.flush()
            labeled_count += 1
            logger.info(
                f"  [{i}] {aid[:8]} ticker={label.get('ticker')} "
                f"sent={label.get('sentiment')} mag={label.get('sentiment_magnitude')} "
                f"relevant={label.get('is_relevant_vn30')} "
                f"conf={label.get('confidence', 0.0):.2f} cost=${cum_cost:.4f}"
            )
            time.sleep(RATE_LIMIT_SLEEP_SECONDS)

    logger.info(f"DONE: labeled {labeled_count} articles, total cost ${cum_cost:.4f}")
    if not args.dry_run:
        logger.info(f"Output: {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
