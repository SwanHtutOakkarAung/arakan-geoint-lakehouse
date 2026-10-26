"""
config/settings.py
──────────────────
🎓 DE CONCEPT: Centralized Configuration
────────────────────────────────────────
In a production data system, ALL paths, URLs, and constants live in ONE place.
This means:
  - You change a path here → it changes everywhere automatically.
  - No hardcoded strings scattered through 20 files.
  - Follows the "12-Factor App" principle: config separated from code.

We use pathlib.Path (not os.path) because it's the modern Pythonic way to
handle filesystem paths in a cross-platform, readable way.
"""

from pathlib import Path

# ── Root ──────────────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# ── Medallion Lake Storage ────────────────────────────────────────────────────
# Bronze: raw, immutable, append-only snapshots from the source
# Silver: validated, geocoded, structured events (Data Contracts enforced)
# Gold:   curated analytical marts ready for the dashboard and analysts
DATA_DIR    = PROJECT_ROOT / "data"
BRONZE_DIR  = DATA_DIR / "bronze"
SILVER_DIR  = DATA_DIR / "silver"
GOLD_DIR    = DATA_DIR / "gold"

# ── Source Feed ───────────────────────────────────────────────────────────────
TELEGRAM_CHANNEL     = "aainfodesk"
TELEGRAM_WEB_BASE    = f"https://t.me/s/{TELEGRAM_CHANNEL}"

# ── DuckDB Lakehouse ──────────────────────────────────────────────────────────
# DuckDB is an embedded analytical database (like SQLite but for OLAP).
# It reads Parquet and JSON files directly — no server needed.
# Perfect for a local lakehouse before scaling to BigQuery/Snowflake.
DUCKDB_PATH = DATA_DIR / "lakehouse.duckdb"

# ── Strategic Geopolitical Infrastructure (Corridors & Assets) ────────────────
# 🎓 Reference Data: Strategic assets monitored for corridor proximity.
STRATEGIC_ASSETS = [
    {
        "corridor_id": "CMEC_PIPELINE",
        "corridor_name": "China-Myanmar Oil & Gas Pipelines (CMEC)",
        "sponsor_nation": "China (CNPC / PetroChina)",
        "asset_type": "ENERGY_PIPELINE",
        "latitude": 19.4312,
        "longitude": 93.6385,
        "description": "Crucial energy pipeline connecting Made Island / Kyaukphyu deep sea terminal to Kunming, Yunnan Province."
    },
    {
        "corridor_id": "KYAUKPHYU_SEZ",
        "corridor_name": "Kyaukphyu Deep Sea Port & SEZ",
        "sponsor_nation": "China (CITIC Group)",
        "asset_type": "DEEP_SEA_PORT",
        "latitude": 19.4267,
        "longitude": 93.5583,
        "description": "Major Belt and Road Initiative (BRI) maritime hub providing China direct access to the Bay of Bengal."
    },
    {
        "corridor_id": "KALADAN_CORRIDOR",
        "corridor_name": "Kaladan Multi-Modal Transit Transport Project",
        "sponsor_nation": "India (Ministry of External Affairs)",
        "asset_type": "TRANSIT_RIVER_PORT",
        "latitude": 20.1444,
        "longitude": 92.8969,
        "description": "Indian strategic link connecting Kolkata seaport with Sittwe port and riverine highway to Mizoram, Northeast India."
    },
    {
        "corridor_id": "ANN_WESTERN_CMD",
        "corridor_name": "Western Command Headquarters (Ann)",
        "sponsor_nation": "Myanmar Military (SAC)",
        "asset_type": "MILITARY_HQ",
        "latitude": 19.7833,
        "longitude": 94.0333,
        "description": "Operational military headquarters overseeing all Junta operations across Rakhine and Chin states."
    },
    {
        "corridor_id": "MAUNGDAW_BORDER",
        "corridor_name": "Maungdaw Border Trade & Naf River Crossing",
        "sponsor_nation": "Myanmar / Bangladesh",
        "asset_type": "BORDER_TRADE",
        "latitude": 20.8167,
        "longitude": 92.3667,
        "description": "Strategic international land border and river crossing adjacent to Cox's Bazar, Bangladesh."
    },
    {
        "corridor_id": "PALETWA_KALADAN_HUB",
        "corridor_name": "Paletwa Kaladan Inland Waterway Terminal",
        "sponsor_nation": "India / Myanmar",
        "asset_type": "INLAND_PORT",
        "latitude": 21.3000,
        "longitude": 92.8500,
        "description": "Transit junction where Kaladan river transport shifts to overland road into Mizoram."
    }
]

# ── HTTP Request Settings ─────────────────────────────────────────────────────
REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}
REQUEST_TIMEOUT = 15  # seconds

# ── Dead-Letter Queue (DLQ) Directory ────────────────────────────────────────
DLQ_DIR = SILVER_DIR / "dlq"

# ── Ensure all lake directories exist at import time ─────────────────────────
for _dir in [BRONZE_DIR, SILVER_DIR, GOLD_DIR, DLQ_DIR]:
    _dir.mkdir(parents=True, exist_ok=True)

