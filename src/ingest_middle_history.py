"""
src/ingest_middle_history.py
────────────────────────────
Executes the full historical ingestion of the middle channel history (IDs 140 to 2460),
followed by Silver NLP/geocoding enrichment and Gold DuckDB mart materialization.
"""

import sys
import time
import json
import logging
from pathlib import Path
from datetime import datetime, timezone

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.ingestion.backfill_forward import run_historical_backfill
from src.enrichment.extractor import run_enrichment
from src.marts.builder import GoldMartsBuilder
from src.utils.deduplication import load_seen_ids
from src.pipeline import load_lakehouse_state, save_lakehouse_state

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("middle_history")

def main():
    start_time = time.time()
    logger.info("=" * 70)
    logger.info("STARTING FULL MIDDLE HISTORY INGESTION (IDs 140 -> 2460)")
    logger.info("=" * 70)

    # 1. Ingest Bronze Layer
    logger.info("Step 1/3: Ingesting Bronze NDJSON records from Telegram web preview...")
    backfill_res = run_historical_backfill(start_id=140, end_id=2460, step=20, delay_seconds=0.8)
    logger.info(f"Bronze Ingestion Result: {backfill_res}")

    # 2. Enrich Silver Layer
    logger.info("\nStep 2/3: Running Silver NLP & MIMU Geocoding Enrichment...")
    silver_res = run_enrichment()
    logger.info(f"Silver Enrichment Result: {silver_res}")

    # 3. Build Gold Layer Marts & DuckDB
    logger.info("\nStep 3/3: Rebuilding DuckDB Star Schema & Gold Geospatial Marts...")
    builder = GoldMartsBuilder()
    builder.build_all_marts()

    # 4. Update Lakehouse State
    seen_ids = load_seen_ids()
    state = load_lakehouse_state()
    state["total_bronze_records"] = len(seen_ids)
    state["low_watermark"] = min(seen_ids) if seen_ids else 1
    state["high_watermark"] = max(seen_ids) if seen_ids else 2491
    state["historical_backfill_complete"] = True
    state["last_sync_utc"] = datetime.now(timezone.utc).isoformat()
    save_lakehouse_state(state)

    elapsed = time.time() - start_time
    logger.info("=" * 70)
    logger.info(f"FULL MIDDLE HISTORY INGESTION COMPLETE in {elapsed:.1f}s ({elapsed/60:.2f} mins)!")
    logger.info(f"   • Total Bronze Records: {len(seen_ids)}")
    logger.info(f"   • Silver Events: {silver_res.get("events_count")}")
    logger.info(f"   • High Watermark: {state["high_watermark"]} | Low Watermark: {state["low_watermark"]}")
    logger.info("=" * 70)

if __name__ == "__main__":
    main()