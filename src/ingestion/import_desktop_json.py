"""
src/ingestion/import_desktop_json.py
───────────────────────────────────
🎓 DE CONCEPT: Bulk File Importer (Batch Ingestion Pattern)
──────────────────────────────────────────────────────────
Book Reference:
  - Data Engineering Design Patterns, Chapter 1 (Batch File Loader)
  - Fundamentals of Data Engineering, Chapter 6 (Bulk Ingestion Systems)

Telegram Desktop has a built-in feature to export complete channel history:
  1. Open Telegram Desktop -> Open @aainfodesk channel
  2. Click 3 dots (top right) -> "Export chat history"
  3. Format: Machine-readable JSON (`result.json`)

This script parses that JSON export and loads ALL posts from Day 1 to current
directly into the Bronze lakehouse in seconds, bypassing web scraping rate limits.
"""

import sys
import json
import logging
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, Any, List

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.models.bronze import BronzePost

from src.utils.deduplication import load_seen_ids, mark_seen, save_seen_ids
from src.ingestion.collector import write_bronze_batch

logger = logging.getLogger("bronze.importer")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


def import_telegram_desktop_json(json_file_path: str | Path) -> Dict[str, Any]:
    """
    Parses a Telegram Desktop export file (`result.json`) and loads posts into Bronze.
    """
    path = Path(json_file_path)
    if not path.exists():
        raise FileNotFoundError(f"Export file not found: {path}")

    logger.info(f"Loading Telegram Desktop JSON export from: {path}")
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    channel_name = data.get("name", "aainfodesk")
    messages = data.get("messages", [])
    logger.info(f"Found {len(messages)} total messages in export for channel '{channel_name}'.")

    seen_ids = load_seen_ids()
    new_posts: List[BronzePost] = []

    for msg in messages:
        if msg.get("type") != "message":
            continue

        msg_id = msg.get("id")
        if not msg_id or msg_id in seen_ids:
            continue

        # Extract text (Telegram export can format text as string or array of chunks)
        raw_text_val = msg.get("text", "")
        if isinstance(raw_text_val, list):
            text_parts = []
            for item in raw_text_val:
                if isinstance(item, str):
                    text_parts.append(item)
                elif isinstance(item, dict) and "text" in item:
                    text_parts.append(item["text"])
            raw_text = "".join(text_parts).strip()
        else:
            raw_text = str(raw_text_val).strip()

        if not raw_text:
            continue

        # Extract timestamp
        date_str = msg.get("date")
        published_dt = None
        if date_str:
            try:
                published_dt = datetime.fromisoformat(date_str).replace(tzinfo=timezone.utc)
            except Exception:
                pass

        # Media detection
        has_media = bool(msg.get("photo") or msg.get("file") or msg.get("media_type"))

        try:
            post = BronzePost(
                message_id=msg_id,
                channel="aainfodesk",
                post_url=f"https://t.me/aainfodesk/{msg_id}",
                raw_text=raw_text,
                published_at=published_dt,
                has_media=has_media,
                media_urls=[]
            )
            mark_seen(msg_id, seen_ids)
            new_posts.append(post)
        except Exception as e:
            logger.debug(f"Skipping msg {msg_id}: {e}")

    logger.info(f"Parsed {len(new_posts)} valid text posts from export.")
    output_path = write_bronze_batch(new_posts)
    if new_posts:
        save_seen_ids(seen_ids)


    return {
        "status": "success",
        "total_in_export": len(messages),
        "new_posts_ingested": len(new_posts),
        "bronze_output": str(output_path) if output_path else None
    }


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python3 -m src.ingestion.import_desktop_json <path_to_result.json>")
        sys.exit(1)
    res = import_telegram_desktop_json(sys.argv[1])
    print("\nResult:", res)
