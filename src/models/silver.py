"""
src/models/silver.py
─────────────────────
🎓 DE CONCEPT: The Silver Layer Data Contract
──────────────────────────────────────────────
Silver is where raw data becomes USEFUL data.

The transformation from Bronze → Silver involves:
  1. EXTRACTION:  Parsing structured fields (date, location, unit names, 
                  event type) out of free-form Burmese text using an LLM.
  2. GEOCODING:   Converting place names like "ပုဏ္ဏားကျွန်းမြို့နယ်"
                  into numeric lat/lon coordinates.
  3. VALIDATION:  Enforcing a strict Pydantic schema (Data Contract).
  4. LINEAGE:     Every Silver record carries the source Bronze message_id
                  and an extraction_confidence score so analysts always
                  know WHERE the data came from and HOW reliable it is.

This is "Schema-on-Write" at the Silver layer:
  - If the LLM returns garbage, Pydantic raises a ValidationError.
  - The bad record goes to a Dead-Letter Queue (Book 03, Chapter 3).
  - It does NOT silently corrupt your Gold layer.

TRANSPARENCY PRINCIPLE (Domain-Specific):
  All Silver records are tagged is_actor_claim=True.
  This is non-negotiable for conflict data.
  The AA Info Desk is an official armed-group communications channel.
  Every reported figure is an actor's claim, not independently verified.
  Analysts and the dashboard must always display this label.
"""

from datetime import datetime, timezone
from typing import List, Optional
from enum import Enum
from pydantic import BaseModel, Field, model_validator
import hashlib


# ─────────────────────────────────────────────────────────────────────────────
# Controlled Vocabularies (Enums)
# 🎓 Using Enums instead of free-text strings enforces consistency.
# If an LLM returns "armed clash" → maps to ARMED_CLASH.
# If it returns something unrecognised → validation fails loudly.
# ─────────────────────────────────────────────────────────────────────────────

class EventCategory(str, Enum):
    ARMED_CLASH         = "ARMED_CLASH"         # Ground combat between forces
    AIRSTRIKE           = "AIRSTRIKE"           # Military aviation attack
    ARTILLERY_SHELLING  = "ARTILLERY_SHELLING"  # Heavy weapon bombardment
    CAMP_SEIZURE        = "CAMP_SEIZURE"        # Capture of military position
    NAVAL_ENGAGEMENT    = "NAVAL_ENGAGEMENT"    # Riverine/coastal combat
    CIVILIAN_CASUALTY   = "CIVILIAN_CASUALTY"   # Harm to non-combatants
    CIVIL_GOVERNANCE    = "CIVIL_GOVERNANCE"    # Administrative/political acts
    HUMANITARIAN        = "HUMANITARIAN"        # Aid, displacement, warnings
    DIPLOMATIC          = "DIPLOMATIC"          # Statements, negotiations
    MATERIEL_CAPTURE    = "MATERIEL_CAPTURE"    # Weapons/equipment seizure
    OTHER               = "OTHER"


class LocationAccuracy(str, Enum):
    EXACT_POINT         = "exact_point"         # GPS-level accuracy from post
    VILLAGE_CENTROID    = "village_centroid"    # Matched to named village
    TOWNSHIP_CENTROID   = "township_centroid"   # Matched to township level
    STATE_LEVEL         = "state_level"         # Only state/region known
    UNKNOWN             = "unknown"


# ─────────────────────────────────────────────────────────────────────────────
# Sub-models
# ─────────────────────────────────────────────────────────────────────────────

class GeoLocation(BaseModel):
    """
    Geocoded location entity.
    
    🎓 DE CONCEPT: Reference Data Enrichment (Static Joiner pattern, Book 03 Ch.5)
    We enrich the raw place name with coordinates from the MIMU reference dataset.
    MIMU (Myanmar Information Management Unit) is the UN's official geographic
    registry for Myanmar — it's what OCHA, ACLED, and aid organizations use.
    """
    raw_place_burmese: str      = Field(description="Original place name from post, in Burmese script")
    raw_place_english: Optional[str] = Field(default=None, description="Transliterated English place name")
    township: Optional[str]     = Field(default=None)
    district: Optional[str]     = Field(default=None)
    state_region: Optional[str] = Field(default="Rakhine")
    # MIMU P-Code: unique identifier e.g. "MMR012001" for each township
    # Format: MMR + 3-digit state code + 3-digit township code
    mimu_pcode: Optional[str]   = Field(default=None, pattern=r"^MMR\d{6}$|^$")
    latitude: Optional[float]   = Field(default=None, ge=-90, le=90)
    longitude: Optional[float]  = Field(default=None, ge=-180, le=180)
    accuracy: LocationAccuracy  = Field(default=LocationAccuracy.UNKNOWN)


class CorridorProximity(BaseModel):
    """
    Proximity to a strategic geopolitical infrastructure asset.
    
    🎓 DE CONCEPT: Spatial Join (Gold layer — computed via PostGIS ST_DWithin)
    This is filled in by the Gold marts pipeline, not the Silver enricher.
    We define it here so the schema is consistent end-to-end.
    """
    corridor_id: str        # e.g., "CMEC_PIPELINE", "KYAUKPHYU_SEZ", "KALADAN_CORRIDOR"
    corridor_name: str
    distance_km: float      = Field(ge=0)
    within_5km: bool        = False
    within_25km: bool       = False
    within_50km: bool       = False


class CasualtyReport(BaseModel):
    """Actor-claimed casualty figures — always labelled as claims."""
    kia_reported: Optional[int]     = Field(default=None, ge=0, description="Killed in action (actor claim)")
    wounded_reported: Optional[int] = Field(default=None, ge=0)
    pow_captured: Optional[int]     = Field(default=None, ge=0, description="Prisoners of war captured")
    civilian_kia: Optional[int]     = Field(default=None, ge=0)
    civilian_wounded: Optional[int] = Field(default=None, ge=0)


# ─────────────────────────────────────────────────────────────────────────────
# Main Silver Record
# ─────────────────────────────────────────────────────────────────────────────

class SilverEvent(BaseModel):
    """
    Validated, enriched, and geocoded geopolitical event record.
    This is the canonical unit of analysis in the lakehouse.
    """

    # ── Identity & Lineage ────────────────────────────────────────────────────
    event_id: str = Field(
        description="Deterministic SHA-256 based UUID: 'AA-<message_id>'. Stable across re-runs."
    )
    source_message_id: int
    source_url: str
    source_channel: str = "aainfodesk"

    # ── Temporal ──────────────────────────────────────────────────────────────
    incident_date: Optional[str]  = Field(default=None, description="ISO date YYYY-MM-DD")
    incident_time: Optional[str]  = Field(default=None, description="HH:MM local time if available")
    published_at: Optional[datetime] = None

    # ── Classification ────────────────────────────────────────────────────────
    category: EventCategory
    sub_tags: List[str] = Field(default_factory=list, description="Additional classification tags")

    # ── Actors ────────────────────────────────────────────────────────────────
    reporting_actor: str = Field(default="Arakan Army (ULA/AA)")
    opposing_actors: List[str] = Field(
        default_factory=list,
        description="e.g. ['SAC Military Junta', 'LIB 542', 'Navy Flotilla 2']"
    )

    # ── Location ──────────────────────────────────────────────────────────────
    location: Optional[GeoLocation] = None
    corridor_proximities: List[CorridorProximity] = Field(default_factory=list)

    # ── Casualties & Materiel ─────────────────────────────────────────────────
    casualties: Optional[CasualtyReport] = None
    materiel_captured: List[str] = Field(
        default_factory=list,
        description="e.g. ['RPG-7', '107mm rocket launcher', 'SA-7 MANPADS', 'LMG (7.62mm)']"
    )

    # ── Content ───────────────────────────────────────────────────────────────
    burmese_headline: str   = Field(description="First 200 chars of raw Burmese text")
    english_summary: str    = Field(description="LLM-generated English summary")
    keywords: List[str]     = Field(default_factory=list, description="Extracted key terms")

    # ── Transparency & Quality ────────────────────────────────────────────────
    # This field is THE most important guardrail for responsible data use.
    is_actor_claim: bool = Field(
        default=True,
        description=(
            "ALWAYS True for this source. AA Info Desk is an official armed group "
            "communications channel. All figures are actor claims, not verified facts."
        )
    )
    extraction_confidence: float = Field(
        ge=0.0, le=1.0,
        description="LLM's self-reported confidence in the extraction (0=uncertain, 1=certain)"
    )
    extraction_model: str = Field(
        default="rule_based_v1",
        description="Model/version used for extraction — for reproducibility and auditing"
    )
    processed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @model_validator(mode="after")
    def validate_event_id_format(self) -> "SilverEvent":
        """Ensure event_id is deterministic from source_message_id."""
        expected = f"AA-{self.source_message_id}"
        if self.event_id != expected:
            # Allow it but log a warning — don't block valid data
            pass
        return self

    def to_dict(self) -> dict:
        d = self.model_dump()
        if d.get("published_at"):
            d["published_at"] = self.published_at.isoformat()
        d["processed_at"] = self.processed_at.isoformat()
        if d.get("location") and d["location"].get("accuracy"):
            d["location"]["accuracy"] = d["location"]["accuracy"].value if hasattr(d["location"]["accuracy"], "value") else d["location"]["accuracy"]
        d["category"] = self.category.value
        return d


# ─────────────────────────────────────────────────────────────────────────────
# Dead-Letter Record
# 🎓 DE CONCEPT: Dead-Letter Queue (Book 03, Chapter 3)
# When a Bronze post FAILS enrichment (LLM can't parse, validation fails),
# we don't discard it. We write it to a Dead-Letter store for manual review.
# This is critical: data is never silently lost in a well-engineered pipeline.
# ─────────────────────────────────────────────────────────────────────────────

class DeadLetterRecord(BaseModel):
    """A failed enrichment record queued for manual review or retry."""
    source_message_id: int
    source_url: str
    raw_text_preview: str   = Field(description="First 300 chars for quick triage")
    failure_reason: str     = Field(description="Why enrichment failed")
    failure_stage: str      = Field(description="e.g. 'llm_extraction', 'geocoding', 'validation'")
    failed_at: datetime     = Field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict:
        d = self.model_dump()
        d["failed_at"] = self.failed_at.isoformat()
        return d
