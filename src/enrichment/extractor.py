"""
src/enrichment/extractor.py
───────────────────────────
🎓 DE CONCEPT: Transformation Pipeline & Dead-Letter Queue (DLQ)
────────────────────────────────────────────────────────────────
Book Reference:
  - Fundamentals of Data Engineering, Chapter 8 (Transformation)
  - Data Engineering Design Patterns, Chapter 3 (Dead-Letter Queue Pattern)
  - Data Engineering with Python, Chapter 4 (Pipeline Validation with Pydantic)

The Silver layer transforms messy, unstructured Bronze data into query-ready,
typed analytical records adhering to our strict Data Contract (src/models/silver.py).

Core Principles Implemented Here:
  1. SCHEMA-ON-WRITE: Every record must pass full Pydantic validation before
     it is accepted into the Silver lake.
  2. DEAD-LETTER QUEUE (DLQ): If an extraction fails schema constraints or crashes,
     we never silently discard it or crash the entire job. It is routed to
     `data/silver/dlq/failures.ndjson` for triage.
  3. IDEMPOTENT PROCESSING: Processing the same message_id multiple times
     produces the same event_id (`AA-<message_id>`).
  4. TRANSPARENCY ENFORCEMENT: Every record is tagged `is_actor_claim=True`
     because military communiques represent actor-reported claims.
"""

import re
import json
import logging
from pathlib import Path
from datetime import datetime, timezone
from typing import List, Optional, Tuple, Dict, Any

import pandas as pd
from pydantic import ValidationError

from config.settings import BRONZE_DIR, SILVER_DIR, DLQ_DIR
from src.models.silver import (
    SilverEvent,
    EventCategory,
    CasualtyReport,
    DeadLetterRecord
)
from src.enrichment.geocoder import geocoder

logger = logging.getLogger("silver.extractor")
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s — %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


# ─────────────────────────────────────────────────────────────────────────────
# Burmese Linguistic Parsing Helpers
# ─────────────────────────────────────────────────────────────────────────────
BURMESE_DIGITS = {
    '၀': '0', '၁': '1', '၂': '2', '၃': '3', '၄': '4',
    '၅': '5', '၆': '6', '၇': '7', '၈': '8', '၉': '9'
}

BURMESE_MONTHS = {
    'ဇန်နဝါရီ': 1, 'ဖေဖော်ဝါရီ': 2, 'မတ်': 3, 'ဧပြီ': 4,
    'မေ': 5, 'ဇွန်': 6, 'ဇူလိုင်': 7, 'ဩဂုတ်': 8,
    'စက်တင်ဘာ': 9, 'အောက်တိုဘာ': 10, 'နိုဝင်ဘာ': 11, 'ဒီဇင်ဘာ': 12
}

def burmese_to_ascii_digits(text: str) -> str:
    """Converts Burmese numeral characters (၀-၉) to standard ASCII (0-9)."""
    res = text
    for bur, asc in BURMESE_DIGITS.items():
        res = res.replace(bur, asc)
    return res


def extract_incident_date(text: str, fallback_dt: Optional[datetime] = None) -> Optional[str]:
    """
    Extracts incident date from Burmese text patterns like:
    '၂၀၂၆ ခုနှစ်၊ အောက်တိုဘာလ (၄) ရက်' -> '2026-10-04'
    """
    ascii_text = burmese_to_ascii_digits(text)
    
    # Pattern: YYYY ခုနှစ်၊ [Month]လ (D) ရက်
    date_match = re.search(r"(\d{4})\s*ခုနှစ်[၊,\s]+([က-အ]+)လ\s*\(?(\d{1,2})\)?\s*ရက်", ascii_text)
    if date_match:
        year = int(date_match.group(1))
        month_bur = date_match.group(2).strip()
        day = int(date_match.group(3))
        for m_name, m_num in BURMESE_MONTHS.items():
            if m_name in month_bur:
                try:
                    return f"{year:04d}-{m_num:02d}-{day:02d}"
                except ValueError:
                    pass

    # Fallback to published_at if available
    if fallback_dt:
        return fallback_dt.strftime("%Y-%m-%d")
    return None


def classify_event_category(text: str) -> Tuple[EventCategory, List[str]]:
    """Classifies the primary event category and extracts contextual sub-tags."""
    tags = []
    
    # Naval
    if any(k in text for k in ["စစ်သင်္ဘော", "နေဗီ", "ကမ်းထိုးယာဉ်", "ရေတပ်"]):
        tags.append("naval_operations")
        return EventCategory.NAVAL_ENGAGEMENT, tags

    # Aviation / Airstrikes
    if any(k in text for k in ["လေကြောင်း", "ဂျက်ဖိုက်တာ", "ဗုံးကြဲ", "Y-12", "Mi-35", "လေယာဉ်"]):
        tags.append("aviation")
        if "ဗုံးကြဲ" in text or "ဂျက်ဖိုက်တာ" in text:
            tags.append("bombardment")
        return EventCategory.AIRSTRIKE, tags

    # Artillery
    if any(k in text for k in ["လက်နက်ကြီး", "ဟောင်ဝစ်ဇာ", "ဒရုန်းဗုံး"]):
        tags.append("heavy_artillery")
        return EventCategory.ARTILLERY_SHELLING, tags

    # Base capture
    if any(k in text for k in ["စခန်းသိမ်း", "အပြီးသတ်သိမ်းပိုက်", "ဗျူဟာကုန်းသိမ်း", "စခန်းအား"]):
        tags.append("base_seizure")
        return EventCategory.CAMP_SEIZURE, tags

    # Civilian casualties
    if any(k in text for k in ["အရပ်သား", "ပြည်သူလူထု", "နေအိမ်မီးလောင်", "ကျေးရွာသား"]):
        if any(k in text for k in ["သေဆုံး", "ဒဏ်ရာရ", "မီးရှို့"]):
            tags.append("civilian_harm")
            return EventCategory.CIVILIAN_CASUALTY, tags

    # Ground combat
    if any(k in text for k in ["တိုက်ပွဲ", "ထိတွေ့တိုက်ပွဲ", "ထိုးစစ်", "ရင်ဆိုင်"]):
        tags.append("ground_combat")
        return EventCategory.ARMED_CLASH, tags

    # Materiel seizure
    if any(k in text for k in ["လက်နက်ခဲယမ်း", "သိမ်းဆည်းရမိ", "စစ်သုံးပစ္စည်း"]):
        tags.append("logistics_capture")
        return EventCategory.MATERIEL_CAPTURE, tags

    # Humanitarian
    if any(k in text for k in ["စစ်ဘေးရှောင်", "ကယ်ဆယ်ရေး", "စားနပ်ရိက္ခာ", "သတိပေး"]):
        tags.append("humanitarian_relief")
        return EventCategory.HUMANITARIAN, tags

    return EventCategory.OTHER, tags


def extract_casualties(text: str) -> Optional[CasualtyReport]:
    """Extracts actor-reported casualty claims."""
    ascii_text = burmese_to_ascii_digits(text)
    kia = None
    wounded = None
    pow_count = None
    civ_kia = None
    civ_wounded = None

    # Search for numbers preceding/following casualty indicators
    # e.g., "အလောင်း (၁၅) လောင်း" or "သေဆုံးသူ (၁၀) ဦး"
    kia_match = re.search(r"(?:သေဆုံး|အလောင်း)[^\d]{0,15}\(?(\d+)\)?\s*(?:ဦး|ယောက်|လောင်း)", ascii_text)
    if kia_match:
        try:
            kia = int(kia_match.group(1))
        except ValueError:
            pass

    wounded_match = re.search(r"(?:ဒဏ်ရာရ|ထိခိုက်)[^\d]{0,15}\(?(\d+)\)?\s*(?:ဦး|ယောက်)", ascii_text)
    if wounded_match:
        try:
            wounded = int(wounded_match.group(1))
        except ValueError:
            pass

    pow_match = re.search(r"(?:ဖမ်းဆီးရမိ|သုံ့ပန်း)[^\d]{0,15}\(?(\d+)\)?\s*(?:ဦး|ယောက်)", ascii_text)
    if pow_match:
        try:
            pow_count = int(pow_match.group(1))
        except ValueError:
            pass

    if any(v is not None for v in [kia, wounded, pow_count, civ_kia, civ_wounded]):
        return CasualtyReport(
            kia_reported=kia,
            wounded_reported=wounded,
            pow_captured=pow_count,
            civilian_kia=civ_kia,
            civilian_wounded=civ_wounded
        )
    return None


def extract_actors(text: str) -> List[str]:
    """Extracts opposing military units and junta formations mentioned."""
    opponents = []
    if any(k in text for k in ["စစ်ကောင်စီ", "စစ်တပ်", "ဖက်ဆစ်"]):
        opponents.append("SAC Military Junta")
    if "နေဗီ" in text or "စစ်သင်္ဘော" in text or "ရေတပ်" in text:
        opponents.append("Myanmar Military Navy")
    if "လေကြောင်း" in text or "ဂျက်ဖိုက်တာ" in text:
        opponents.append("Myanmar Military Air Force")
    if "နယ်ခြားစောင့်" in text or "BGP" in text:
        opponents.append("Border Guard Police (BGP)")

    # Extract numbered battalions like ခလရ (၅၄၂) or ခမရ (၃၇၅)
    ascii_text = burmese_to_ascii_digits(text)
    for bn_match in re.finditer(r"(ခလရ|ခမရ|တပ်မ)\s*\(?(\d+)\)?", ascii_text):
        bn_type = bn_match.group(1)
        bn_num = bn_match.group(2)
        type_str = "LIB" if bn_type == "ခလရ" else ("LID" if bn_type == "တပ်မ" else "IB")
        opponents.append(f"{type_str} {bn_num}")

    return list(dict.fromkeys(opponents))


def extract_materiel(text: str) -> List[str]:
    """Extracts weapons and materiel captured or utilized."""
    materiel = []
    weapons_map = {
        "RPG": "RPG Rocket Launcher",
        "ဒရုန်း": "Tactical UAV / Drone",
        "လက်နက်ကြီး": "Heavy Artillery Piece",
        "ဟောင်ဝစ်ဇာ": "Howitzer Artillery",
        "စက်သေနတ်": "Machine Gun (LMG/HMG)",
        "စနိုက်ပါ": "Sniper Rifle",
        "ကျည်": "Small Arms Ammunition",
        "မော်တာ": "Mortar (60mm/81mm/120mm)"
    }
    for kw, label in weapons_map.items():
        if kw in text:
            materiel.append(label)
    return materiel


def generate_english_summary(category: EventCategory, location_name: str,
                             opponents: List[str], casualties: Optional[CasualtyReport],
                             headline: str) -> str:
    """Generates a concise English intelligence brief for the event."""
    cat_str = category.value.replace("_", " ").title()
    opp_str = f" involving {', '.join(opponents[:2])}" if opponents else ""
    loc_str = f" in {location_name}" if location_name else " in Rakhine theater"
    
    cas_parts = []
    if casualties:
        if casualties.kia_reported is not None:
            cas_parts.append(f"{casualties.kia_reported} claimed KIA")
        if casualties.wounded_reported is not None:
            cas_parts.append(f"{casualties.wounded_reported} claimed wounded")
        if casualties.pow_captured is not None:
            cas_parts.append(f"{casualties.pow_captured} claimed POWs")
    cas_str = f" ({', '.join(cas_parts)})" if cas_parts else ""

    return f"Reported {cat_str}{loc_str}{opp_str}{cas_str}. Source: AA official communique."


# ─────────────────────────────────────────────────────────────────────────────
# Core Transformation Engine
# ─────────────────────────────────────────────────────────────────────────────
class SilverExtractor:
    """Enriches raw Bronze records into validated SilverEvent instances."""

    def __init__(self):
        self.geocoder = geocoder

    def enrich_record(self, raw_post: dict) -> Tuple[Optional[SilverEvent], Optional[DeadLetterRecord]]:
        """
        Transforms a single Bronze record.
        Returns (SilverEvent, None) on success, or (None, DeadLetterRecord) on validation failure.
        """
        message_id = raw_post.get("message_id")
        raw_text = raw_post.get("raw_text", "")
        post_url = raw_post.get("post_url", f"https://t.me/aainfodesk/{message_id}")
        
        # Parse published_at timestamp
        pub_at = None
        if raw_post.get("published_at"):
            try:
                pub_at = datetime.fromisoformat(raw_post["published_at"])
            except Exception:
                pass

        try:
            # 1. Geocoding
            geo_loc = self.geocoder.geocode_text(raw_text)
            loc_label = geo_loc.raw_place_english if geo_loc else "Rakhine Theater"

            # 2. Category & Tags
            category, sub_tags = classify_event_category(raw_text)

            # 3. Temporal
            incident_date = extract_incident_date(raw_text, fallback_dt=pub_at)

            # 4. Casualties & Actors
            casualties = extract_casualties(raw_text)
            opponents = extract_actors(raw_text)
            materiel = extract_materiel(raw_text)

            # 5. Summarization & Headlines
            headline = raw_text[:200].replace("\n", " ").strip()
            summary = generate_english_summary(category, loc_label, opponents, casualties, headline)

            # 6. Keywords
            keywords = [category.value.lower()] + [t.lower() for t in sub_tags]
            if geo_loc and geo_loc.township:
                keywords.append(geo_loc.township.lower())

            # 7. Construct & Validate Pydantic Model (Schema-on-Write)
            event = SilverEvent(
                event_id=f"AA-{message_id}",
                source_message_id=message_id,
                source_url=post_url,
                source_channel="aainfodesk",
                incident_date=incident_date,
                published_at=pub_at,
                category=category,
                sub_tags=sub_tags,
                reporting_actor="Arakan Army (ULA/AA)",
                opposing_actors=opponents,
                location=geo_loc,
                casualties=casualties,
                materiel_captured=materiel,
                burmese_headline=headline,
                english_summary=summary,
                keywords=keywords,
                is_actor_claim=True,
                extraction_confidence=0.92 if geo_loc and geo_loc.township else 0.75,
                extraction_model="lexical_rule_engine_v1"
            )
            return event, None

        except ValidationError as ve:
            logger.warning(f"Validation error on post {message_id}: {ve}")
            dlq = DeadLetterRecord(
                source_message_id=message_id,
                source_url=post_url,
                raw_text_preview=raw_text[:300],
                failure_reason=str(ve),
                failure_stage="validation"
            )
            return None, dlq

        except Exception as ex:
            logger.error(f"Unexpected enrichment crash on post {message_id}: {ex}")
            dlq = DeadLetterRecord(
                source_message_id=message_id,
                source_url=post_url,
                raw_text_preview=raw_text[:300],
                failure_reason=str(ex),
                failure_stage="extraction_pipeline"
            )
            return None, dlq


# ─────────────────────────────────────────────────────────────────────────────
# Pipeline Runner
# ─────────────────────────────────────────────────────────────────────────────
def run_enrichment() -> Dict[str, Any]:
    """
    Executes the Silver Enrichment pipeline over all Bronze NDJSON partitions.
    Outputs:
      - data/silver/events.parquet
      - data/silver/events.json
      - data/silver/dlq/failures.ndjson (if any validation errors occur)
    """
    logger.info("=" * 60)
    logger.info("STARTING SILVER ENRICHMENT PIPELINE")
    logger.info("=" * 60)

    extractor = SilverExtractor()
    bronze_files = sorted(BRONZE_DIR.rglob("*.ndjson"))
    logger.info(f"Discovered {len(bronze_files)} Bronze partition files.")

    valid_events: List[SilverEvent] = []
    dlq_records: List[DeadLetterRecord] = []
    seen_message_ids = set()

    for bf in bronze_files:
        logger.info(f"Reading Bronze partition: {bf.relative_to(BRONZE_DIR)}")
        with open(bf, "r", encoding="utf-8") as f:
            for line_no, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    raw_post = json.loads(line)
                    msg_id = raw_post.get("message_id")
                    if msg_id in seen_message_ids:
                        continue
                    seen_message_ids.add(msg_id)

                    event, dlq = extractor.enrich_record(raw_post)
                    if event:
                        valid_events.append(event)
                    elif dlq:
                        dlq_records.append(dlq)
                except Exception as parse_err:
                    logger.warning(f"Could not parse line {line_no} in {bf.name}: {parse_err}")

    logger.info(f"Enrichment complete: {len(valid_events)} valid Silver events, {len(dlq_records)} DLQ records.")

    # ── Write Valid Silver Data ───────────────────────────────────────────────
    parquet_path = SILVER_DIR / "events.parquet"
    json_path = SILVER_DIR / "events.json"

    if valid_events:
        # Convert to serializable dicts
        event_dicts = [ev.to_dict() for ev in valid_events]
        
        # Save JSON
        with open(json_path, "w", encoding="utf-8") as jf:
            json.dump(event_dicts, jf, ensure_ascii=False, indent=2)
        logger.info(f"Wrote {len(event_dicts)} Silver records to {json_path}")

        # Flatten records for Parquet storage (DuckDB / Pandas OLAP)
        flat_records = []
        for ev in valid_events:
            d = ev.to_dict()
            loc = d.get("location") or {}
            cas = d.get("casualties") or {}
            flat = {
                "event_id": d["event_id"],
                "source_message_id": d["source_message_id"],
                "source_url": d["source_url"],
                "incident_date": d.get("incident_date"),
                "published_at": d.get("published_at"),
                "category": d["category"],
                "sub_tags": ",".join(d.get("sub_tags", [])),
                "reporting_actor": d["reporting_actor"],
                "opposing_actors": ",".join(d.get("opposing_actors", [])),
                "township": loc.get("township"),
                "mimu_pcode": loc.get("mimu_pcode"),
                "latitude": loc.get("latitude"),
                "longitude": loc.get("longitude"),
                "location_accuracy": loc.get("accuracy"),
                "kia_reported": cas.get("kia_reported"),
                "wounded_reported": cas.get("wounded_reported"),
                "pow_captured": cas.get("pow_captured"),
                "materiel_captured": ",".join(d.get("materiel_captured", [])),
                "burmese_headline": d["burmese_headline"],
                "english_summary": d["english_summary"],
                "is_actor_claim": d["is_actor_claim"],
                "extraction_confidence": d["extraction_confidence"],
                "extraction_model": d["extraction_model"],
                "processed_at": d["processed_at"]
            }
            flat_records.append(flat)

        df = pd.DataFrame(flat_records)
        df.to_parquet(parquet_path, index=False)
        logger.info(f"Wrote {len(df)} Silver records to Parquet: {parquet_path}")

    # ── Write Dead-Letter Queue (DLQ) ─────────────────────────────────────────
    if dlq_records:
        dlq_file = DLQ_DIR / f"failures_{datetime.now(timezone.utc).strftime('%Y%m%d')}.ndjson"
        with open(dlq_file, "a", encoding="utf-8") as df_out:
            for rec in dlq_records:
                df_out.write(json.dumps(rec.to_dict(), ensure_ascii=False) + "\n")
        logger.warning(f"Logged {len(dlq_records)} failed records to Dead-Letter Queue: {dlq_file}")

    return {
        "status": "success",
        "valid_events_count": len(valid_events),
        "dlq_count": len(dlq_records),
        "parquet_output": str(parquet_path) if valid_events else None,
        "json_output": str(json_path) if valid_events else None
    }


if __name__ == "__main__":
    result = run_enrichment()
    print("\nResult:", result)
