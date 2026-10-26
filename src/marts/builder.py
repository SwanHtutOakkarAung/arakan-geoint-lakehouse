"""
src/marts/builder.py
────────────────────
🎓 DE CONCEPT: The Gold Layer & Dimensional Modeling (Star Schema)
──────────────────────────────────────────────────────────────────
Book Reference:
  - Fundamentals of Data Engineering, Chapter 9 (Serving Data for Analytics & ML)
  - Data Engineering with Python, Chapter 8 (DuckDB Analytical Processing)
  - Data Engineering Design Patterns, Chapter 4 (Dimensional Modeling)

The Gold layer is the curated analytical tier of the Medallion Architecture.
While Bronze is raw and Silver is cleansed/typed, Gold is designed for CONSUMPTION:
  - Business/Intelligence Analysts
  - Interactive Dashboards
  - Spatial threat monitoring & proximity alerts

Key Features of this Module:
  1. EMBEDDED OLAP (DuckDB): Queries the Silver Parquet data directly using SQL
     without requiring an external database cluster.
  2. SPATIAL PROXIMITY ENGINE: Computes great-circle (Haversine) distances
     between conflict events and critical geopolitical corridors (e.g. China's CMEC
     pipelines, India's Kaladan Multi-Modal Project, SAC Western Command HQ).
  3. DIMENSIONAL TABLES:
     - `dim_corridors`: Strategic infrastructure reference dimensions.
     - `fct_events`: Denormalized fact table linking events to corridor threat tiers.
     - `agg_township_risk`: Township rollups for situational awareness.
     - `agg_corridor_threat`: International stakeholder threat matrix.
  4. GEOJSON EXPORT: Generates RFC 7946 compliant GeoJSON layers for direct
     rendering in Leaflet/Mapbox mapping interfaces.
"""

import math
import json
import logging
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, Any, List, Tuple

import duckdb
import pandas as pd

from config.settings import SILVER_DIR, GOLD_DIR, DUCKDB_PATH, STRATEGIC_ASSETS

logger = logging.getLogger("gold.marts")
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s — %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


# ─────────────────────────────────────────────────────────────────────────────
# Spatial Geometry Helpers (Haversine Distance)
# ─────────────────────────────────────────────────────────────────────────────
def haversine_distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Computes great-circle distance between two GPS coordinates in kilometers.
    Formula: d = 2R * asin(sqrt(sin²(Δlat/2) + cos(lat1)*cos(lat2)*sin²(Δlon/2)))
    """
    R = 6371.0  # Earth's mean radius in km
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(dlon / 2) ** 2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return round(R * c, 2)


def calculate_corridor_proximities(event_lat: float, event_lon: float) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """
    Computes distance from an event coordinate to all monitored strategic assets.
    Returns:
      - list of corridor proximity details
      - nearest corridor summary dict
    """
    proximities = []
    nearest_asset = None
    min_dist = float("inf")

    for asset in STRATEGIC_ASSETS:
        dist = haversine_distance_km(event_lat, event_lon, asset["latitude"], asset["longitude"])
        item = {
            "corridor_id": asset["corridor_id"],
            "corridor_name": asset["corridor_name"],
            "sponsor_nation": asset["sponsor_nation"],
            "asset_type": asset["asset_type"],
            "distance_km": dist,
            "within_5km": dist <= 5.0,
            "within_25km": dist <= 25.0,
            "within_50km": dist <= 50.0
        }
        proximities.append(item)

        if dist < min_dist:
            min_dist = dist
            nearest_asset = item

    return proximities, nearest_asset


# ─────────────────────────────────────────────────────────────────────────────
# Gold Marts Builder
# ─────────────────────────────────────────────────────────────────────────────
class GoldMartsBuilder:
    """Orchestrates DuckDB analytical models and builds Gold marts."""

    def __init__(self):
        self.silver_parquet = SILVER_DIR / "events.parquet"
        self.duckdb_file = DUCKDB_PATH

    def build_all_marts(self) -> Dict[str, Any]:
        """Runs the spatial joiner, builds star-schema marts, and exports GeoJSON."""
        logger.info("=" * 60)
        logger.info("STARTING GOLD MARTS BUILD PIPELINE")
        logger.info("=" * 60)

        if not self.silver_parquet.exists():
            raise FileNotFoundError(f"Silver Parquet file not found at {self.silver_parquet}. Run Silver enrichment first.")

        # Connect to DuckDB
        con = duckdb.connect(str(self.duckdb_file))
        logger.info(f"Connected to embedded DuckDB lakehouse: {self.duckdb_file}")

        # 1. Load Silver events into DuckDB
        con.execute(f"CREATE OR REPLACE TABLE raw_silver_events AS SELECT * FROM read_parquet('{self.silver_parquet}')")
        silver_count = con.execute("SELECT count(*) FROM raw_silver_events").fetchone()[0]
        logger.info(f"Loaded {silver_count} Silver events into DuckDB.")

        # 2. Enrich events with spatial corridor proximities (Python UDF / processing)
        df_silver = con.execute("SELECT * FROM raw_silver_events").fetchdf()

        enriched_rows = []
        for _, row in df_silver.iterrows():
            r = row.to_dict()
            lat = r.get("latitude")
            lon = r.get("longitude")

            if pd.notna(lat) and pd.notna(lon):
                proximities, nearest = calculate_corridor_proximities(float(lat), float(lon))
                r["nearest_corridor_id"] = nearest["corridor_id"]
                r["nearest_corridor_name"] = nearest["corridor_name"]
                r["nearest_corridor_dist_km"] = nearest["distance_km"]
                r["within_5km_of_corridor"] = nearest["within_5km"]
                r["within_25km_of_corridor"] = nearest["within_25km"]
                r["within_50km_of_corridor"] = nearest["within_50km"]
                r["corridor_proximities_json"] = json.dumps(proximities)
            else:
                r["nearest_corridor_id"] = None
                r["nearest_corridor_name"] = None
                r["nearest_corridor_dist_km"] = None
                r["within_5km_of_corridor"] = False
                r["within_25km_of_corridor"] = False
                r["within_50km_of_corridor"] = False
                r["corridor_proximities_json"] = json.dumps([])

            enriched_rows.append(r)

        df_enriched = pd.DataFrame(enriched_rows)

        # 3. Create Fact Table: fct_conflict_events
        con.register("df_enriched_view", df_enriched)
        con.execute("CREATE OR REPLACE TABLE fct_conflict_events AS SELECT * FROM df_enriched_view")
        logger.info("Created Fact Table: `fct_conflict_events` in DuckDB.")

        # 4. Create Dimension Table: dim_corridors
        df_corridors = pd.DataFrame(STRATEGIC_ASSETS)
        con.register("df_corridors_view", df_corridors)
        con.execute("CREATE OR REPLACE TABLE dim_corridors AS SELECT * FROM df_corridors_view")
        logger.info("Created Dimension Table: `dim_corridors` in DuckDB.")

        # 5. Create Aggregate Mart: agg_township_risk
        con.execute("""
            CREATE OR REPLACE TABLE agg_township_risk AS
            SELECT 
                COALESCE(township, 'Unspecified') AS township,
                COALESCE(mimu_pcode, 'UNKNOWN') AS mimu_pcode,
                COUNT(*) AS total_incidents,
                SUM(CASE WHEN category = 'AIRSTRIKE' THEN 1 ELSE 0 END) AS airstrike_count,
                SUM(CASE WHEN category = 'ARTILLERY_SHELLING' THEN 1 ELSE 0 END) AS artillery_count,
                SUM(CASE WHEN category = 'ARMED_CLASH' THEN 1 ELSE 0 END) AS armed_clash_count,
                SUM(CASE WHEN category = 'CAMP_SEIZURE' THEN 1 ELSE 0 END) AS camp_seizure_count,
                SUM(COALESCE(kia_reported, 0)) AS total_claimed_kia,
                SUM(COALESCE(wounded_reported, 0)) AS total_claimed_wounded,
                MIN(incident_date) AS earliest_incident,
                MAX(incident_date) AS latest_incident
            FROM fct_conflict_events
            GROUP BY township, mimu_pcode
            ORDER BY total_incidents DESC
        """)
        logger.info("Created Aggregate Mart: `agg_township_risk` in DuckDB.")

        # 6. Create Aggregate Mart: agg_corridor_threat
        con.execute("""
            CREATE OR REPLACE TABLE agg_corridor_threat AS
            SELECT 
                nearest_corridor_id AS corridor_id,
                nearest_corridor_name AS corridor_name,
                COUNT(*) AS incident_count_within_vicinity,
                SUM(CASE WHEN within_5km_of_corridor THEN 1 ELSE 0 END) AS critical_threat_5km,
                SUM(CASE WHEN within_25km_of_corridor THEN 1 ELSE 0 END) AS operational_threat_25km,
                SUM(CASE WHEN within_50km_of_corridor THEN 1 ELSE 0 END) AS theater_threat_50km,
                MIN(nearest_corridor_dist_km) AS closest_incident_km
            FROM fct_conflict_events
            WHERE nearest_corridor_id IS NOT NULL
            GROUP BY nearest_corridor_id, nearest_corridor_name
            ORDER BY critical_threat_5km DESC, closest_incident_km ASC
        """)
        logger.info("Created Aggregate Mart: `agg_corridor_threat` in DuckDB.")

        # 7. Export Marts to Gold Parquet & CSV files
        for table_name in ["fct_conflict_events", "dim_corridors", "agg_township_risk", "agg_corridor_threat"]:
            pq_out = GOLD_DIR / f"{table_name}.parquet"
            csv_out = GOLD_DIR / f"{table_name}.csv"
            con.execute(f"COPY {table_name} TO '{pq_out}' (FORMAT PARQUET)")
            con.execute(f"COPY {table_name} TO '{csv_out}' (HEADER, DELIMITER ',')")
            logger.info(f"Exported mart `{table_name}` -> {pq_out.name} and {csv_out.name}")

        # 7b. Export complete list of ALL events (spatial + non-spatial)
        all_events_list = df_enriched.to_dict(orient="records")
        all_events_path = GOLD_DIR / "all_events.json"
        with open(all_events_path, "w", encoding="utf-8") as f:
            json.dump(all_events_list, f, ensure_ascii=False, indent=2, default=str)
        logger.info(f"Exported all {len(all_events_list)} events to {all_events_path}")

        # 8. Generate GeoJSON for Map Visualizations
        self._export_events_geojson(con)
        self._export_corridors_geojson()
        self._export_summary_metrics(con)

        con.close()
        logger.info("GOLD MARTS GENERATION COMPLETED SUCCESSFULLY.")

        return {
            "status": "success",
            "duckdb_lakehouse": str(self.duckdb_file),
            "events_count": len(df_enriched),
            "gold_directory": str(GOLD_DIR)
        }

    def _export_events_geojson(self, con: duckdb.DuckDBPyConnection):
        """Generates RFC 7946 GeoJSON FeatureCollection for all conflict incidents & communiques."""
        events_df = con.execute("SELECT * FROM fct_conflict_events").fetchdf()
        features = []

        def clean_val(v, default=None):
            if v is None or pd.isna(v):
                return default
            return v

        for _, r in events_df.iterrows():
            lat = clean_val(r.get("latitude"))
            lon = clean_val(r.get("longitude"))
            
            # If coordinates are missing (e.g. diplomatic statement or alliance greeting),
            # assign general theater coordinates for map exploration
            has_explicit_coords = (lat is not None and lon is not None)
            display_lat = float(lat) if has_explicit_coords else 20.1444
            display_lon = float(lon) if has_explicit_coords else 92.8969
            accuracy = clean_val(r.get("location_accuracy"), "theater_wide" if not has_explicit_coords else "unknown")

            properties = {
                "event_id": str(r["event_id"]),
                "source_message_id": int(r["source_message_id"]),
                "source_url": str(r["source_url"]),
                "incident_date": str(r["incident_date"]) if pd.notna(r.get("incident_date")) else None,
                "category": str(r["category"]),
                "township": clean_val(r.get("township"), "Rakhine Theater (General)"),
                "mimu_pcode": clean_val(r.get("mimu_pcode"), "THEATER"),
                "location_accuracy": accuracy,
                "has_explicit_coords": has_explicit_coords,
                "headline": str(r.get("burmese_headline", "")),
                "summary": str(r.get("english_summary", "")),
                "opposing_actors": str(clean_val(r.get("opposing_actors"), "")),
                "kia_reported": int(clean_val(r.get("kia_reported"), 0)),
                "wounded_reported": int(clean_val(r.get("wounded_reported"), 0)),
                "nearest_corridor": clean_val(r.get("nearest_corridor_name")),
                "corridor_dist_km": float(clean_val(r.get("nearest_corridor_dist_km"), 0.0)) if pd.notna(r.get("nearest_corridor_dist_km")) else None,
                "within_5km": bool(clean_val(r.get("within_5km_of_corridor"), False)),
                "within_25km": bool(clean_val(r.get("within_25km_of_corridor"), False)),
                "is_actor_claim": bool(clean_val(r.get("is_actor_claim"), True))
            }

            feature = {
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [display_lon, display_lat]
                },
                "properties": properties
            }
            features.append(feature)

        geojson_obj = {
            "type": "FeatureCollection",
            "metadata": {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "total_features": len(features),
                "data_layer": "Gold Incident Layer"
            },
            "features": features
        }

        geojson_path = GOLD_DIR / "events.geojson"
        with open(geojson_path, "w", encoding="utf-8") as f:
            json.dump(geojson_obj, f, ensure_ascii=False, indent=2, allow_nan=False)
        logger.info(f"Generated GeoJSON: {geojson_path} ({len(features)} points).")

    def _export_corridors_geojson(self):
        """Generates GeoJSON FeatureCollection for all Strategic Infrastructure Assets."""
        features = []
        for asset in STRATEGIC_ASSETS:
            feature = {
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [asset["longitude"], asset["latitude"]]
                },
                "properties": {
                    "corridor_id": asset["corridor_id"],
                    "corridor_name": asset["corridor_name"],
                    "sponsor_nation": asset["sponsor_nation"],
                    "asset_type": asset["asset_type"],
                    "description": asset["description"]
                }
            }
            features.append(feature)

        geojson_obj = {
            "type": "FeatureCollection",
            "metadata": {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "total_corridors": len(features),
                "data_layer": "Strategic Geopolitical Assets"
            },
            "features": features
        }

        corridors_path = GOLD_DIR / "corridors.geojson"
        with open(corridors_path, "w", encoding="utf-8") as f:
            json.dump(geojson_obj, f, ensure_ascii=False, indent=2)
        logger.info(f"Generated Strategic Corridors GeoJSON: {corridors_path} ({len(features)} assets).")

    def _export_summary_metrics(self, con: duckdb.DuckDBPyConnection):
        """Exports high-level KPI metrics for fast dashboard rendering."""
        total_events = con.execute("SELECT count(*) FROM fct_conflict_events").fetchone()[0]
        airstrikes = con.execute("SELECT count(*) FROM fct_conflict_events WHERE category = 'AIRSTRIKE'").fetchone()[0]
        corridor_alerts_25km = con.execute("SELECT count(*) FROM fct_conflict_events WHERE within_25km_of_corridor = true").fetchone()[0]
        total_kia_claims = con.execute("SELECT coalesce(sum(kia_reported), 0) FROM fct_conflict_events").fetchone()[0]

        summary = {
            "total_incidents": total_events,
            "total_airstrikes": airstrikes,
            "corridor_threat_alerts_25km": corridor_alerts_25km,
            "total_claimed_kia": int(total_kia_claims),
            "updated_at": datetime.now(timezone.utc).isoformat()
        }

        summary_path = GOLD_DIR / "summary_metrics.json"
        with open(summary_path, "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2)
        logger.info(f"Generated Summary KPI Metrics: {summary_path}")


if __name__ == "__main__":
    builder = GoldMartsBuilder()
    res = builder.build_all_marts()
    print("\nGold Marts Result:", res)
