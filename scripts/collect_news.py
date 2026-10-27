"""Collect financial news articles for F3 sentiment training (Sprint 13 Day 1).

Fetches news from 3 Vietnamese financial sources via vnstock_news SDK:
    - CafeF (cafef.vn)       - stock market + macro
    - VietStock (vietstock.vn) - stock + sector analysis
    - VnExpress (vnexpress.net) - general news (needs sitemap config)

Output format: JSONL at data/sentiment_training/raw_articles.jsonl
    Each line = 1 article with full content + metadata

Related: ADR-008 (PhoBERT vs RAG decision), Sprint 13 Day 1 schedule.

Usage:
    # Fetch default 100 articles per site (300 total)
    python scripts/collect_news.py

    # Custom per-site limit
    python scripts/collect_news.py --limit 200

    # Specific sites only (comma-separated)
    python scripts/collect_news.py --sites cafef,vietstock

    # Dry-run (no file write)
    python scripts/collect_news.py --dry-run
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from dotenv import load_dotenv

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

# Rate limit per vnstock_news docs: max 2 concurrent / site, 1s gap
RATE_LIMIT_SLEEP_SECONDS = 1.1

DEFAULT_SITES = ["cafef", "vietstock", "vnexpress"]
DEFAULT_OUTPUT = Path("data/sentiment_training/raw_articles.jsonl")


def _setup_vnstock() -> None:
    """Load env + login vnstock. Fail-fast if key missing."""
    load_dotenv(".env")
    key = os.environ.get("VNSTOCK_API_KEY", "").strip()
    if not key:
        logger.error("VNSTOCK_API_KEY not set in .env")
        sys.exit(1)
    import vnstock

    vnstock.login(key)
    status = vnstock.status()
    if not status.get("authenticated"):
        logger.error(f"VNSTOCK auth failed: {status}")
        sys.exit(1)
    logger.info(f"vnstock tier: {status['tier']}")


def fetch_from_site(site_name: str, limit: int) -> list[dict]:
    """Fetch latest N articles from one site + full details.

    Returns list of {site, url, title, content, publish_time, author, ...}.
    Skips articles that fail detail fetch (logs warning).
    """
    from vnstock_news import Crawler

    logger.info(f"[{site_name}] fetching {limit} article URLs...")
    try:
        c = Crawler(site_name=site_name)
        url_list = c.get_latest_articles(limit=limit)
    except Exception as e:
        logger.error(f"[{site_name}] URL discovery failed: {type(e).__name__}: {e}")
        return []

    logger.info(f"[{site_name}] got {len(url_list)} URLs, fetching details...")
    articles = []
    for i, item in enumerate(url_list, 1):
        url = item.get("url") if isinstance(item, dict) else None
        if not url:
            continue
        try:
            details = c.get_article_details(url)
            if not details or not details.get("content"):
                logger.debug(f"  [{i}/{len(url_list)}] empty content, skip {url[:60]}")
                continue
            articles.append(
                {
                    "site": site_name,
                    "url": details.get("url", url),
                    "title": details.get("title", ""),
                    "short_description": details.get("short_description", ""),
                    "content": details.get("content", ""),
                    "publish_time": str(details.get("publish_time", "")),
                    "author": details.get("author", ""),
                    "category": details.get("category", ""),
                    "tags": details.get("tags", []),
                    "collected_at": datetime.now(UTC).isoformat(),
                }
            )
            if i % 20 == 0:
                logger.info(f"  [{site_name}] {i}/{len(url_list)} fetched ({len(articles)} valid)")
        except Exception as e:
            logger.warning(
                f"  [{i}/{len(url_list)}] detail fetch failed: {type(e).__name__}: {str(e)[:80]}"
            )
        time.sleep(RATE_LIMIT_SLEEP_SECONDS)
    logger.info(f"[{site_name}] DONE: {len(articles)}/{len(url_list)} valid articles")
    return articles


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=100, help="Articles per site (default 100)")
    parser.add_argument(
        "--sites",
        default=",".join(DEFAULT_SITES),
        help=f"Comma-separated sites. Default: {','.join(DEFAULT_SITES)}",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"Output JSONL file (default: {DEFAULT_OUTPUT})",
    )
    parser.add_argument("--dry-run", action="store_true", help="Skip file write")
    args = parser.parse_args()

    _setup_vnstock()

    sites = [s.strip() for s in args.sites.split(",") if s.strip()]
    logger.info(
        f"Collect target: {len(sites)} site(s)={sites}, limit={args.limit}/site, "
        f"total ~{len(sites) * args.limit} articles, dry_run={args.dry_run}"
    )

    all_articles = []
    for site in sites:
        articles = fetch_from_site(site, args.limit)
        all_articles.extend(articles)

    logger.info(f"TOTAL collected: {len(all_articles)} articles")

    if args.dry_run:
        logger.info("[DRY-RUN] skipping file write")
        return 0

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        for art in all_articles:
            f.write(json.dumps(art, ensure_ascii=False) + "\n")
    logger.info(f"Wrote {len(all_articles)} articles -> {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
