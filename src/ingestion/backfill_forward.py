"""
src/ingestion/backfill_forward.py
─────────────────────────────────
🎓 DE CONCEPT: Historical Backfill & Range Partitioning
───────────────────────────────────────────────────────
Book Reference:
  - Fundamentals of Data Engineering, Chapter 6 (Ingestion & Historical Backfills)
  - Data Engineering Design Patterns, Chapter 1 (Full Historical Loader)

Telegram's channel history for @aainfodesk begins on January 1, 2022 (Message ID 1).
While the real-time collector paginates backwards from HEAD, this module performs
a FORWARD-SWEEP historical backfill:
  - Takes range: start_id=20 to max_id=2550
  - Stepping with `?before={target_id}` in intervals
  - Deduplicates against the local registry so existing records are never duplicated
  - Writes new records to Bronze partitioned NDJSON storage
"""

import sys
import time
import logging
from pathlib import Path
from typing import Dict, Any, List

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import requests

from src.models.bronze import BronzePost
from src.utils.deduplication import load_seen_ids, mark_seen, save_seen_ids
from src.ingestion.collector import parse_posts_from_html, write_bronze_batch
from config.settings import TELEGRAM_WEB_BASE, REQUEST_HEADERS, REQUEST_TIMEOUT

logger = logging.getLogger("bronze.backfill")
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s — %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


def run_historical_backfill(start_id: int = 25, end_id: int = 2500, step: int = 20, delay_seconds: float = 1.6) -> Dict[str, Any]:
    """
    Sweeps historical message ID ranges to ingest early channel posts.
    
    Args:
        start_id: Earliest message ID to query (e.g. 25 gets posts 1-24).
        end_id: Upper bound message ID.
        step: Increment between query windows.
        delay_seconds: Rate-limiting pause between requests.
    """
    logger.info("=" * 60)
    logger.info(f"HISTORICAL BACKFILL: Range [{start_id} -> {end_id}] (Step: {step})")
    logger.info("=" * 60)

    seen_ids = load_seen_ids()
    logger.info(f"Loaded deduplication registry: {len(seen_ids)} existing IDs.")

    total_new_posts: List[BronzePost] = []
    current_before = start_id
    pages_queried = 0

    while current_before <= end_id:
        pages_queried += 1
        url = f"{TELEGRAM_WEB_BASE}?before={current_before}"
        logger.info(f"[{pages_queried}] Fetching window ?before={current_before}")

        try:
            resp = requests.get(url, headers=REQUEST_HEADERS, timeout=REQUEST_TIMEOUT)
            if resp.status_code == 429:
                logger.warning("Rate-limited by Telegram (429). Backing off for 15s...")
                time.sleep(15)
                continue
            resp.raise_for_status()

            parsed_posts, all_ids = parse_posts_from_html(resp.text)
            new_on_page = 0

            for post in parsed_posts:
                if post.message_id not in seen_ids:
                    mark_seen(post.message_id, seen_ids)
                    total_new_posts.append(post)
                    new_on_page += 1

            logger.info(f"  → Parsed {len(parsed_posts)} text posts ({new_on_page} new). IDs on page: {all_ids[:3]}...")

        except Exception as err:
            logger.error(f"Error fetching {url}: {err}")

        current_before += step
        time.sleep(delay_seconds)

    output_path = write_bronze_batch(total_new_posts)
    if total_new_posts:
        save_seen_ids(seen_ids)
    logger.info(f"Historical backfill complete: {len(total_new_posts)} total new posts added.")

    return {
        "status": "success",
        "pages_queried": pages_queried,
        "new_posts_written": len(total_new_posts),
        "output_file": str(output_path) if output_path else None
    }


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Forward historical backfill for Telegram public channels")
    parser.add_argument("--start", type=int, default=25, help="Starting before_id (default: 25)")
    parser.add_argument("--end", type=int, default=200, help="Ending before_id (default: 200)")
    parser.add_argument("--step", type=int, default=20, help="Step increment (default: 20)")
    parser.add_argument("--delay", type=float, default=1.5, help="Polite delay between requests (default: 1.5s)")

    args = parser.parse_args()
    res = run_historical_backfill(start_id=args.start, end_id=args.end, step=args.step, delay_seconds=args.delay)
    print("\nResult:", res)
