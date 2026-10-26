"""
src/models/bronze.py
─────────────────────
🎓 DE CONCEPT: Data Contracts & Schema-on-Write
────────────────────────────────────────────────
A Data Contract is a formal, versioned agreement about the shape
of data as it crosses a layer boundary.

WHY does this matter?
  - Without contracts, a messy upstream change (e.g., Telegram changes
    its HTML structure) silently corrupts your entire pipeline.
  - With Pydantic contracts, the failure is LOUD and immediate at
    the point of ingestion — not discovered 3 days later downstream.

This is "Schema-on-Write" (validate when you write to the lake),
as opposed to "Schema-on-Read" (discover structure only when you query).
Schema-on-write is always preferred for production data pipelines.

BronzePost is intentionally MINIMAL and RAW.
  - It preserves exactly what we saw from the source.
  - It does NOT interpret, classify, or enrich.
  - Enrichment is the Silver layer's job.
  - This separation is critical: Bronze = Source of Truth.
"""

from datetime import datetime, timezone
from typing import List, Optional
from pydantic import BaseModel, Field, field_validator


class BronzePost(BaseModel):
    """
    Immutable raw representation of a single Telegram post.

    Every field maps directly to something observable in the HTML
    of t.me/s/aainfodesk — no inference, no interpretation.
    """

    # ── Identity ──────────────────────────────────────────────────────────────
    message_id: int = Field(
        description="Telegram's own numeric message ID. This is our deduplication key."
    )
    channel: str = Field(
        default="aainfodesk",
        description="Source channel handle. Hardcoded for now; parameterized for multi-source later."
    )
    post_url: str = Field(
        description="Canonical URL to the post, e.g. https://t.me/aainfodesk/2247"
    )

    # ── Content ───────────────────────────────────────────────────────────────
    raw_text: str = Field(
        description="Full raw text of the post, in original Burmese (Myanmar Script). Preserved verbatim."
    )

    # ── Temporal ──────────────────────────────────────────────────────────────
    published_at: Optional[datetime] = Field(
        default=None,
        description="Publication timestamp parsed from Telegram's <time datetime=...> attribute."
    )

    # ── Media ─────────────────────────────────────────────────────────────────
    has_media: bool = Field(
        default=False,
        description="True if the post contains photos or videos."
    )
    media_urls: List[str] = Field(
        default_factory=list,
        description="List of absolute URLs to media attachments."
    )

    # ── Lineage & Audit ───────────────────────────────────────────────────────
    # 🎓 DE CONCEPT: Data Lineage
    # Every record in the Bronze lake carries a timestamp of WHEN we ingested it.
    # This is separate from when Telegram PUBLISHED it.
    # Why? If we re-ingest, we can see: "this post was first seen by our system at X."
    ingested_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC timestamp of when our pipeline ingested this record."
    )

    @field_validator("raw_text")
    @classmethod
    def text_must_not_be_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("raw_text cannot be empty — skipping media-only posts.")
        return v.strip()

    def to_dict(self) -> dict:
        """Serialize for JSON storage in the Bronze lake."""
        d = self.model_dump()
        # Convert datetime objects to ISO strings for JSON serialization
        if d.get("published_at"):
            d["published_at"] = self.published_at.isoformat()
        d["ingested_at"] = self.ingested_at.isoformat()
        return d
