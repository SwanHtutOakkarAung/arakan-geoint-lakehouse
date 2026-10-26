"""
src/ingestion/collector.py
───────────────────────────
🎓 DE CONCEPT: The Bronze Ingestion Layer
──────────────────────────────────────────
(Ref: Book 03, Chapter 2 — Data Ingestion Design Patterns)
(Ref: Book 01, Chapter 2 — The Data Engineering Lifecycle: Ingestion)

This is the FIRST stage of our Medallion Lakehouse.
It implements two patterns from Book 03:

  1. FULL LOADER (initial backfill):
     On the very first run, we fetch as many historical posts as possible.
     Telegram's public web view paginates via ?before=<message_id>.
     We walk backwards in history until we hit our limit or run out of posts.

  2. INCREMENTAL LOADER (ongoing updates):
     On subsequent runs, we only fetch posts NEWER than our last seen ID.
     This is efficient: we don't re-download 2,000 posts every hour.

KEY PRINCIPLES demonstrated here:
  - Separation of Concerns: This module ONLY fetches and stores raw data.
    Parsing, translating, and enriching are NOT done here.
  - Immutability: Bronze files are NEVER modified after writing.
    They are appended to or new files are created for each batch.
  - Storage pattern: Each ingestion run saves a NDJSON file
    (Newline-Delimited JSON) partitioned by date:
    data/bronze/year=2026/month=10/day=27/batch_<timestamp>.ndjson
    This is the "Horizontal Partitioner" pattern (Book 03, Chapter 8).
    Partitioning by date lets us query "show me all posts from October"
    by scanning only the October partition — not the entire dataset.
"""

import json
import re
import time
import logging
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup

# Internal imports — always use relative paths within a package
from src.models.bronze import BronzePost
from src.utils.deduplication import load_seen_ids, save_seen_ids, is_new, mark_seen
from config.settings import BRONZE_DIR, TELEGRAM_WEB_BASE, REQUEST_HEADERS, REQUEST_TIMEOUT

# ── Logging setup ─────────────────────────────────────────────────────────────
# 🎓 DE CONCEPT: Observability
# A pipeline without logging is a black box. When it fails at 3am,
# you need a breadcrumb trail. We use Python's standard logging module.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("bronze.collector")


# ── Parser ────────────────────────────────────────────────────────────────────
def parse_posts_from_html(html: str) -> tuple[list[BronzePost], list[int]]:
    """
    Parse raw HTML from t.me/s/<channel> into BronzePost records.

    Returns:
        (text_posts, all_message_ids)
        - text_posts: Only posts with text content (stored in Bronze lake)
        - all_message_ids: ALL message IDs found on the page, including
          media-only posts. Used for pagination cursor advancement.

    🎓 DE CONCEPT: Why return all_message_ids separately?
    Telegram pages contain both text posts and media-only posts.
    Our Bronze lake only stores text posts (media-only have no analysis value
    without a computer vision pipeline).
    BUT: we must paginate using the SMALLEST ID on the page — including
    media-only posts — otherwise we'll re-request the same page forever.
    This is the "pagination cursor" pattern: the cursor advances based on
    what the SOURCE returned, not what WE decided to store.

    Telegram's public channel HTML structure:
    <div class="tgme_widget_message" data-post="aainfodesk/2247">
      <div class="tgme_widget_message_text">...Burmese text...</div>
      <time datetime="2026-09-20T12:34:56+00:00">...</time>
    </div>
    """
    soup = BeautifulSoup(html, "lxml")
    posts: list[BronzePost] = []
    all_ids: list[int] = []

    message_wraps = soup.find_all("div", class_="tgme_widget_message_wrap")
    logger.info(f"Found {len(message_wraps)} message containers in HTML.")

    for wrap in message_wraps:
        msg_div = wrap.find("div", class_=re.compile(r"tgme_widget_message\b"))
        if not msg_div:
            continue

        # ── Extract message_id (always, even for media-only) ──────────────────
        data_post = msg_div.get("data-post", "")
        match = re.search(r"/(\d+)$", data_post)
        if not match:
            continue
        message_id = int(match.group(1))
        all_ids.append(message_id)  # Track ALL IDs for pagination cursor

        post_url = f"https://t.me/aainfodesk/{message_id}"

        # ── Extract text ──────────────────────────────────────────────────────
        text_div = msg_div.find("div", class_=re.compile(r"tgme_widget_message_text"))
        raw_text = text_div.get_text(separator="\n").strip() if text_div else ""

        # Only store posts with text content
        if not raw_text:
            logger.debug(f"Skipping media-only post {message_id} (no text).")
            continue

        # ── Extract timestamp ─────────────────────────────────────────────────
        time_tag = msg_div.find("time")
        published_at = None
        if time_tag and time_tag.get("datetime"):
            try:
                published_at = datetime.fromisoformat(time_tag["datetime"])
            except ValueError:
                pass

        # ── Extract media ─────────────────────────────────────────────────────
        photo_links = msg_div.find_all("a", class_=re.compile(r"tgme_widget_message_photo"))
        media_urls = [a["href"] for a in photo_links if a.get("href")]
        has_media = bool(media_urls) or bool(msg_div.find("video"))

        # ── Validate with Pydantic Data Contract ──────────────────────────────
        try:
            post = BronzePost(
                message_id=message_id,
                post_url=post_url,
                raw_text=raw_text,
                published_at=published_at,
                has_media=has_media,
                media_urls=media_urls,
            )
            posts.append(post)
        except Exception as e:
            logger.warning(f"Skipping post {message_id}: validation failed — {e}")

    logger.info(f"  Parsed: {len(posts)} text posts, {len(all_ids)} total containers (incl. media-only).")
    return posts, all_ids


# ── Storage ───────────────────────────────────────────────────────────────────
def get_partition_path(dt: datetime) -> Path:
    """
    🎓 DE CONCEPT: Date Partitioning (Horizontal Partitioner)
    We store data in Hive-style partitions: year=YYYY/month=MM/day=DD/
    This is the universal convention for partitioned data lakes.
    Tools like DuckDB, Spark, and BigQuery can automatically discover
    and prune these partitions during queries.
    """
    return BRONZE_DIR / f"year={dt.year}" / f"month={dt.month:02d}" / f"day={dt.day:02d}"


def write_bronze_batch(posts: list[BronzePost]) -> Path | None:
    """
    Write a batch of new posts to the Bronze lake as NDJSON.

    🎓 DE CONCEPT: NDJSON (Newline-Delimited JSON)
    Each line is a complete, independent JSON object.
    NDJSON is ideal for streaming/appending because you can write
    one record at a time without loading the whole file into memory.
    It's also directly readable by DuckDB: SELECT * FROM read_ndjson('*.ndjson')
    """
    if not posts:
        return None

    now = datetime.now(timezone.utc)
    partition_path = get_partition_path(now)
    partition_path.mkdir(parents=True, exist_ok=True)

    timestamp = now.strftime("%Y%m%dT%H%M%SZ")
    output_file = partition_path / f"batch_{timestamp}.ndjson"

    with open(output_file, "w", encoding="utf-8") as f:
        for post in posts:
            f.write(json.dumps(post.to_dict(), ensure_ascii=False) + "\n")

    logger.info(f"Wrote {len(posts)} posts to {output_file}")
    return output_file


# ── Main Ingestion Orchestrator ───────────────────────────────────────────────
def run_ingestion(max_pages: int = 10, delay_seconds: float = 1.5,
                  start_before_id: int | None = None, force_backfill: bool = False) -> dict:
    """
    Main entry point. Handles both incremental updates and historical backfills.

    Args:
        max_pages:       Max pages to paginate (each ~5-20 posts).
        delay_seconds:   Polite delay between HTTP requests.
        start_before_id: Start pagination from this message_id backwards.
                         Use to backfill older history below a known oldest ID.
        force_backfill:  If True, continue paginating even when all posts on a
                         page are already seen (for explicit historical backfills).

    Returns:
        Summary dict with counts.

    🎓 DE CONCEPT: The "Readiness Marker" pattern (Book 03)
    We return a summary dict so the orchestrator (or calling code)
    knows whether ingestion succeeded and how many records were written.
    """
    logger.info("=" * 60)
    logger.info(f"BRONZE INGESTION — {'BACKFILL' if force_backfill else 'INCREMENTAL'}")
    logger.info("=" * 60)

    seen_ids = load_seen_ids()
    logger.info(f"Loaded deduplication registry: {len(seen_ids)} known IDs.")

    total_fetched = 0
    total_new = 0
    all_new_posts: list[BronzePost] = []
    before_id: int | None = start_before_id

    for page_num in range(1, max_pages + 1):
        url = TELEGRAM_WEB_BASE if before_id is None else f"{TELEGRAM_WEB_BASE}?before={before_id}"
        logger.info(f"[Page {page_num}/{max_pages}] Fetching: {url}")

        try:
            response = requests.get(url, headers=REQUEST_HEADERS, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
        except requests.RequestException as e:
            logger.error(f"HTTP error on page {page_num}: {e}")
            break

        text_posts, all_page_ids = parse_posts_from_html(response.text)

        # Stop only if the source returned NO containers at all
        if not all_page_ids:
            logger.info("No message containers found — reached end of channel history.")
            break

        total_fetched += len(text_posts)
        new_posts = [p for p in text_posts if is_new(p.message_id, seen_ids)]
        logger.info(f"  → {len(new_posts)} new text posts (of {len(text_posts)} text, {len(all_page_ids)} total containers).")

        if not new_posts and not force_backfill:
            logger.info("All text posts already ingested — stopping (use force_backfill=True to continue).")
            break

        all_new_posts.extend(new_posts)
        total_new += len(new_posts)

        for p in new_posts:
            mark_seen(p.message_id, seen_ids)

        # Advance pagination cursor using ALL IDs (including media-only)
        # This is the key fix: cursor is based on source data, not our filter
        before_id = min(all_page_ids)

        if page_num < max_pages:
            time.sleep(delay_seconds)

    output_file = write_bronze_batch(all_new_posts)
    save_seen_ids(seen_ids)

    summary = {
        "status": "success",
        "pages_fetched": page_num,
        "total_posts_seen": total_fetched,
        "new_posts_written": total_new,
        "output_file": str(output_file) if output_file else None,
    }
    logger.info(f"BRONZE INGESTION COMPLETE: {summary}")
    return summary


if __name__ == "__main__":
    # Full historical backfill from channel beginning
    run_ingestion(max_pages=200, delay_seconds=1.2, force_backfill=True)
