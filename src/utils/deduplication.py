"""
src/utils/deduplication.py
───────────────────────────
🎓 DE CONCEPT: Idempotency & Deduplication
────────────────────────────────────────────
(Ref: Book 03, Chapter 4 — Idempotency Design Patterns)

"Idempotent" means: running the same operation multiple times
produces the same result as running it once.

This is one of the most fundamental properties of a good data pipeline.
Without it:
  - You re-run your ingestion after a network error → you get duplicate records.
  - Your database grows 2x, 3x, 10x — with identical data.
  - Your analytics double-count events. Your conflict maps lie.

HOW WE IMPLEMENT IT:
  We maintain a "seen IDs" registry — a simple JSON file that records
  which Telegram message_ids we have already ingested.
  Before writing a new post to Bronze, we check this registry.
  If the ID is already there → skip (idempotent).
  If it's new → ingest and record the ID.

In production systems this would be a database table or a Bloom filter.
For our local lakehouse, a JSON file is perfectly sufficient and transparent.

Pattern used: "Keyed Idempotency" from Book 03 Chapter 4.
The "key" is the Telegram message_id — a stable, unique identifier
assigned by Telegram itself.
"""

import json
from pathlib import Path


SEEN_IDS_FILE = Path(__file__).resolve().parent.parent.parent / "data" / "bronze" / ".seen_ids.json"


def load_seen_ids() -> set[int]:
    """Load the set of already-ingested message IDs from disk."""
    if not SEEN_IDS_FILE.exists():
        return set()
    with open(SEEN_IDS_FILE, "r") as f:
        return set(json.load(f))


def save_seen_ids(seen: set[int]) -> None:
    """Persist the updated seen-ID registry to disk."""
    SEEN_IDS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(SEEN_IDS_FILE, "w") as f:
        json.dump(sorted(seen), f)


def is_new(message_id: int, seen: set[int]) -> bool:
    """Return True if this message_id has NOT been ingested before."""
    return message_id not in seen


def mark_seen(message_id: int, seen: set[int]) -> None:
    """Add a message_id to the in-memory seen set (call save_seen_ids to persist)."""
    seen.add(message_id)
