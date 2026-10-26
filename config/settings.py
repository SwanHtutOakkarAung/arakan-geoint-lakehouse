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
# It reads Parquet files directly — no server needed.
# Perfect for a local lakehouse before scaling to BigQuery/Snowflake.
DUCKDB_PATH = DATA_DIR / "lakehouse.duckdb"

# ── HTTP Request Settings ─────────────────────────────────────────────────────
REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}
REQUEST_TIMEOUT = 15  # seconds

# ── Ensure all lake directories exist at import time ─────────────────────────
for _dir in [BRONZE_DIR, SILVER_DIR, GOLD_DIR]:
    _dir.mkdir(parents=True, exist_ok=True)
