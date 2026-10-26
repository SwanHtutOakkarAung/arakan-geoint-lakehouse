# arakan-geoint-lakehouse

A **geospatial intelligence (GEOINT) lakehouse** that ingests, structures, enriches, and
visualizes conflict & geopolitical communications from the Arakan Army public channel
(`@aainfodesk`), combining **Data Engineering**, **Applied NLP/AI**, and **GIS analytics**.

## Architecture: Medallion Lakehouse

```
[Source: t.me/s/aainfodesk]
        │
        ▼  Bronze Ingestion (Full Loader + Incremental Loader patterns)
┌──────────────────────────────┐
│  BRONZE  data/bronze/        │  Raw immutable JSON, append-only
└──────────────┬───────────────┘
               │
               ▼  Silver Enrichment (LLM extraction + MIMU geocoding)
┌──────────────────────────────┐
│  SILVER  data/silver/        │  Validated, typed, geocoded events
└──────────────┬───────────────┘
               │
               ▼  Gold Marts (dimensional models + spatial joins)
┌──────────────────────────────┐
│  GOLD    data/gold/          │  Analytical star schema + GeoJSON
└──────────────┬───────────────┘
               │
               ▼
┌──────────────────────────────┐
│  DASHBOARD  dashboard/        │  5-module interactive intelligence UI
└──────────────────────────────┘
```

## Intelligence Modules
1. **Geopolitical Asset & Corridor Proximity Monitor**
2. **Spatio-Temporal Conflict & Incident Tracker**
3. **Strategic Communications & Narrative Analyzer**
4. **Humanitarian & Early Warning Digest**
5. **OSINT Materiel & Unit ORBAT Catalog**

## Project Layout
```
arakan-geoint-lakehouse/
├── src/
│   ├── ingestion/      # Bronze: scraping + deduplication
│   ├── enrichment/     # Silver: NLP extraction + geocoding
│   ├── marts/          # Gold: dimensional models + spatial joins
│   ├── models/         # Pydantic data contracts (schema-on-write)
│   └── utils/          # Shared helpers (logging, hashing, HTTP)
├── data/
│   ├── bronze/         # Raw JSON (append-only, immutable)
│   ├── silver/         # Validated Parquet/JSON events
│   └── gold/           # Curated marts + GeoJSON
├── config/             # Settings, source URLs, corridor definitions
├── dashboard/          # Interactive HTML/JS frontend
├── tests/              # Data quality + unit tests
└── notebooks/          # Exploratory analysis
```

## Quick Start
```bash
python3 -m pip install -r requirements.txt

# Run Bronze ingestion (fetch latest posts)
python3 -m src.ingestion.collector

# Run Silver enrichment (extract structured events)
python3 -m src.enrichment.extractor

# Launch dashboard
python3 -m dashboard.server
```
