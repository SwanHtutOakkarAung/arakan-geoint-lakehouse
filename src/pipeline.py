"""
src/pipeline.py
───────────────
🎓 DE CONCEPT: Unified Orchestration & Dual Watermark State Machine
────────────────────────────────────────────────────────────────────
Book Reference:
  - Fundamentals of Data Engineering, Chapter 6 & 8 (Ingestion & Delta Transformation)
  - Data Engineering Design Patterns, Chapter 1 (Incremental & Historical Patterns)
  - Data Engineering with Python, Chapter 8 (End-to-End Orchestration)

This module provides a unified CLI and production orchestrator:
  1. DUAL WATERMARK TRACKING:
     - Maintains `data/lakehouse_state.json`
     - `high_watermark`: Highest message ID fetched (for incremental forward polling)
     - `low_watermark`: Lowest message ID backfilled (for historical backward sweeps to Day 1)
  2. DELTA PROCESSING:
     - Detects new Bronze records that do not yet exist in Silver
     - Enriches ONLY the delta (0% redundant LLM / NLP compute)
  3. COMPACT GOLD UPDATE:
     - Rebuilds DuckDB marts and GeoJSON outputs after changes
"""

import sys
import json
import time
import argparse
import logging
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, Any, Set, List

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config.settings import DATA_DIR, BRONZE_DIR, SILVER_DIR
from src.models.bronze import BronzePost
from src.utils.deduplication import load_seen_ids, mark_seen, save_seen_ids
from src.ingestion.collector import parse_posts_from_html, write_bronze_batch, TELEGRAM_WEB_BASE, REQUEST_HEADERS, REQUEST_TIMEOUT
from src.enrichment.extractor import SilverExtractor, run_enrichment
from src.marts.builder import GoldMartsBuilder
import requests

logger = logging.getLogger("lakehouse.pipeline")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s — %(message)s")

STATE_FILE = DATA_DIR / "lakehouse_state.json"


# ─────────────────────────────────────────────────────────────────────────────
# 1. Persistent State Machine (Dual Watermarks)
# ─────────────────────────────────────────────────────────────────────────────
def load_lakehouse_state() -> Dict[str, Any]:
    """Loads current high and low watermarks from disk."""
    if not STATE_FILE.exists():
        seen = load_seen_ids()
        state = {
            "high_watermark": max(seen) if seen else 0,
            "low_watermark": min(seen) if seen else float("inf"),
            "total_bronze_records": len(seen),
            "last_sync_utc": None,
            "historical_backfill_complete": False
        }
        save_lakehouse_state(state)
        return state

    with open(STATE_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_lakehouse_state(state: Dict[str, Any]):
    """Persists watermarks to disk."""
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)


# ─────────────────────────────────────────────────────────────────────────────
# 2. Ingestion Modes: Incremental Sync vs. Historical Backfill
# ─────────────────────────────────────────────────────────────────────────────
def sync_latest(max_pages: int = 5, delay: float = 1.5) -> int:
    """
    Incremental Mode: Polls HEAD of channel for new posts published since high_watermark.
    Stops as soon as it hits known message IDs.
    """
    logger.info("=== RUNNING INCREMENTAL FORWARD SYNC ===")
    state = load_lakehouse_state()
    seen_ids = load_seen_ids()
    high_watermark = state.get("high_watermark", 0)
    logger.info(f"Current High Watermark: {high_watermark} (Tracking {len(seen_ids)} total posts)")

    new_posts: List[BronzePost] = []
    before_id = None
    hit_known = False

    for page in range(1, max_pages + 1):
        url = TELEGRAM_WEB_BASE if before_id is None else f"{TELEGRAM_WEB_BASE}?before={before_id}"
        logger.info(f"Checking {url}")

        try:
            resp = requests.get(url, headers=REQUEST_HEADERS, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            posts, all_ids = parse_posts_from_html(resp.text)

            page_new = 0
            for p in posts:
                if p.message_id > high_watermark and p.message_id not in seen_ids:
                    mark_seen(p.message_id, seen_ids)
                    new_posts.append(p)
                    page_new += 1
                elif p.message_id <= high_watermark:
                    hit_known = True

            logger.info(f"Page {page}: {page_new} new posts (Total IDs on page: {len(all_ids)})")

            if hit_known:
                logger.info("Reached known historical records. Halting incremental sync.")
                break

            if all_ids:
                before_id = min(all_ids)
            else:
                break

            time.sleep(delay)

        except Exception as e:
            logger.error(f"Sync error on page {page}: {e}")
            break

    if new_posts:
        write_bronze_batch(new_posts)
        save_seen_ids(seen_ids)
        state["high_watermark"] = max([p.message_id for p in new_posts] + [high_watermark])
        state["total_bronze_records"] = len(seen_ids)
        state["last_sync_utc"] = datetime.now(timezone.utc).isoformat()
        save_lakehouse_state(state)
        logger.info(f"Successfully ingested {len(new_posts)} new posts. New High Watermark: {state['high_watermark']}")
    else:
        logger.info("Lakehouse is completely up to date. No new posts.")

    return len(new_posts)


def backfill_history(batch_pages: int = 10, delay: float = 1.6) -> int:
    """
    Historical Mode: Resumes from `low_watermark` and steps backwards toward Message ID 1.
    """
    logger.info("=== RUNNING RESUMABLE HISTORICAL BACKFILL ===")
    state = load_lakehouse_state()
    seen_ids = load_seen_ids()
    low_watermark = state.get("low_watermark", float("inf"))

    if low_watermark <= 1:
        logger.info("🎉 Historical backfill is already 100% complete down to Message ID 1!")
        state["historical_backfill_complete"] = True
        save_lakehouse_state(state)
        return 0

    logger.info(f"Resuming backfill from Low Watermark: {low_watermark} -> Day 1 (Post 1)")
    new_posts: List[BronzePost] = []
    before_cursor = low_watermark

    for page in range(1, batch_pages + 1):
        url = f"{TELEGRAM_WEB_BASE}?before={before_cursor}"
        logger.info(f"Backfill Step {page}/{batch_pages}: ?before={before_cursor}")

        try:
            resp = requests.get(url, headers=REQUEST_HEADERS, timeout=REQUEST_TIMEOUT)
            if resp.status_code == 429:
                logger.warning("Rate-limited. Pausing 15s...")
                time.sleep(15)
                continue
            resp.raise_for_status()

            posts, all_ids = parse_posts_from_html(resp.text)
            page_new = 0
            for p in posts:
                if p.message_id not in seen_ids:
                    mark_seen(p.message_id, seen_ids)
                    new_posts.append(p)
                    page_new += 1

            logger.info(f"  → Found {len(posts)} text posts ({page_new} new). IDs: {all_ids[:3] if all_ids else 'None'}...")

            if not all_ids or min(all_ids) <= 1:
                logger.info("Reached inception of channel (Message ID 1)!")
                state["historical_backfill_complete"] = True
                state["low_watermark"] = 1
                break

            before_cursor = min(all_ids)
            time.sleep(delay)

        except Exception as e:
            logger.error(f"Error during backfill: {e}")
            break

    if new_posts:
        write_bronze_batch(new_posts)
        save_seen_ids(seen_ids)
        state["low_watermark"] = min([p.message_id for p in new_posts] + [before_cursor])
        state["total_bronze_records"] = len(seen_ids)
        save_lakehouse_state(state)
        logger.info(f"Backfilled {len(new_posts)} historical records. New Low Watermark: {state['low_watermark']}")
    else:
        state["low_watermark"] = before_cursor
        save_lakehouse_state(state)

    return len(new_posts)


# ─────────────────────────────────────────────────────────────────────────────
# 3. Master Pipeline Execution
# ─────────────────────────────────────────────────────────────────────────────
def run_full_pipeline(mode: str = "sync", batch_pages: int = 10):
    """
    Executes the end-to-end Medallion Lifecycle:
      1. Ingest (Sync or Backfill based on watermarks)
      2. Enrich (Delta transformation into Silver)
      3. Marts (DuckDB Gold OLAP re-indexing & GeoJSON export)
    """
    start_time = time.time()
    logger.info("=" * 60)
    logger.info(f"STARTING LAKEHOUSE PIPELINE [Mode: {mode.upper()}]")
    logger.info("=" * 60)

    # Step 1: Ingestion
    if mode == "backfill":
        new_count = backfill_history(batch_pages=batch_pages)
    elif mode == "sync":
        new_count = sync_latest(max_pages=batch_pages)
    else:
        logger.info("Running BOTH: Sync new + Backfill older history")
        new_count = sync_latest(max_pages=3) + backfill_history(batch_pages=batch_pages)

    # Step 2: Silver Delta Transformation
    logger.info("Step 2: Running Silver Transformation...")
    silver_res = run_enrichment()

    # Step 3: Gold Analytical Marts
    logger.info("Step 3: Rebuilding DuckDB Gold Marts...")
    builder = GoldMartsBuilder()
    gold_res = builder.build_all_marts()

    elapsed = round(time.time() - start_time, 2)
    logger.info("=" * 60)
    logger.info(f"PIPELINE COMPLETE in {elapsed}s: {new_count} new posts ingested | {silver_res['valid_events_count']} total Silver events")
    logger.info("=" * 60)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Arakan GEOINT Lakehouse Master Orchestrator")
    parser.add_argument("--mode", choices=["sync", "backfill", "both"], default="sync",
                        help="Execution mode: 'sync' (incremental poll), 'backfill' (step toward Day 1), or 'both'")
    parser.add_argument("--pages", type=int, default=10,
                        help="Number of pages/windows to process in this run")

    args = parser.parse_args()
    run_full_pipeline(mode=args.mode, batch_pages=args.pages)
