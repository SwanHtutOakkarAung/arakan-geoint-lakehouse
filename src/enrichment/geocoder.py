"""
src/enrichment/geocoder.py
──────────────────────────
🎓 DE CONCEPT: The Static Joiner (Reference Data Enrichment)
────────────────────────────────────────────────────────────
Book Reference:
  - Data Engineering Design Patterns, Chapter 5 (Reference Data Enrichment)
  - Fundamentals of Data Engineering, Chapter 8 (Transformation & Context Enrichment)

In data engineering, "Reference Data" is slow-moving, authoritative master data
(such as ISO country codes, postal codes, or UN geographic registries).

The Static Joiner pattern loads an immutable lookup table into memory once at startup
and performs fast, deterministic key/fuzzy joins against the incoming stream of raw events.

Why MIMU?
  MIMU (Myanmar Information Management Unit) is the United Nations geographic standard
  for Myanmar. Every township in Myanmar has an official P-Code (Place Code):
    - State prefix: MMR012 (Rakhine State), MMR004 (Chin State)
    - Township suffix: 001 to 017
  International bodies like UN OCHA, ACLED, and the Red Cross standardize on MIMU P-codes.
  By assigning P-codes in the Silver layer, our lakehouse data is immediately interoperable
  with global geospatial datasets.
"""

import re
import logging
from typing import Optional, Dict, Any, List
from src.models.silver import GeoLocation, LocationAccuracy

logger = logging.getLogger("silver.geocoder")
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s — %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


# ─────────────────────────────────────────────────────────────────────────────
# Authoritative Reference Data: UN MIMU P-Code Master Table
# ─────────────────────────────────────────────────────────────────────────────
RAKHINE_TOWNSHIPS: Dict[str, Dict[str, Any]] = {
    "Sittwe": {
        "mimu_pcode": "MMR012001",
        "burmese": "စစ်တွေ",
        "district": "Sittwe",
        "state_region": "Rakhine",
        "lat": 20.1444,
        "lon": 92.8969,
        "aliases": ["စစ်တွေ", "စစ်တွေမြို့", "စစ်တွေမြို့နယ်", "Sittwe", "Akyab"]
    },
    "Ponnagyun": {
        "mimu_pcode": "MMR012002",
        "burmese": "ပုဏ္ဏားကျွန်း",
        "district": "Sittwe",
        "state_region": "Rakhine",
        "lat": 20.3333,
        "lon": 93.0000,
        "aliases": ["ပုဏ္ဏားကျွန်း", "ပုဏ္ဏားကျွန်းမြို့", "ပုဏ္ဏားကျွန်းမြို့နယ်", "Ponnagyun"]
    },
    "Mrauk-U": {
        "mimu_pcode": "MMR012003",
        "burmese": "မြောက်ဦး",
        "district": "Mrauk-U",
        "state_region": "Rakhine",
        "lat": 20.5975,
        "lon": 93.1897,
        "aliases": ["မြောက်ဦး", "မြောက်ဦးမြို့", "မြောက်ဦးမြို့နယ်", "မြောက်ဦးမြို့ဟောင်း", "Mrauk-U", "Mrauk U"]
    },
    "Kyauktaw": {
        "mimu_pcode": "MMR012004",
        "burmese": "ကျောက်တော်",
        "district": "Mrauk-U",
        "state_region": "Rakhine",
        "lat": 20.8406,
        "lon": 92.9667,
        "aliases": ["ကျောက်တော်", "ကျောက်တော်မြို့", "ကျောက်တော်မြို့နယ်", "Kyauktaw"]
    },
    "Minbya": {
        "mimu_pcode": "MMR012005",
        "burmese": "မင်းပြား",
        "district": "Mrauk-U",
        "state_region": "Rakhine",
        "lat": 20.3667,
        "lon": 93.2667,
        "aliases": ["မင်းပြား", "မင်းပြားမြို့", "မင်းပြားမြို့နယ်", "Minbya"]
    },
    "Myebon": {
        "mimu_pcode": "MMR012006",
        "burmese": "မြေပုံ",
        "district": "Mrauk-U",
        "state_region": "Rakhine",
        "lat": 20.0500,
        "lon": 93.6000,
        "aliases": ["မြေပုံ", "မြေပုံမြို့", "မြေပုံမြို့နယ်", "Myebon"]
    },
    "Pauktaw": {
        "mimu_pcode": "MMR012007",
        "burmese": "ပေါက်တော",
        "district": "Sittwe",
        "state_region": "Rakhine",
        "lat": 20.1833,
        "lon": 93.0667,
        "aliases": ["ပေါက်တော", "ပေါက်တောမြို့", "ပေါက်တောမြို့နယ်", "Pauktaw"]
    },
    "Rathedaung": {
        "mimu_pcode": "MMR012008",
        "burmese": "ရသေ့တောင်",
        "district": "Sittwe",
        "state_region": "Rakhine",
        "lat": 20.4833,
        "lon": 92.7500,
        "aliases": ["ရသေ့တောင်", "ရသေ့တောင်မြို့", "ရသေ့တောင်မြို့နယ်", "Rathedaung"]
    },
    "Buthidaung": {
        "mimu_pcode": "MMR012009",
        "burmese": "ဘူးသီးတောင်",
        "district": "Maungdaw",
        "state_region": "Rakhine",
        "lat": 20.8667,
        "lon": 92.5333,
        "aliases": ["ဘူးသီးတောင်", "ဘူးသီးတောင်မြို့", "ဘူးသီးတောင်မြို့နယ်", "Buthidaung"]
    },
    "Maungdaw": {
        "mimu_pcode": "MMR012010",
        "burmese": "မောင်တော",
        "district": "Maungdaw",
        "state_region": "Rakhine",
        "lat": 20.8167,
        "lon": 92.3667,
        "aliases": ["မောင်တော", "မောင်တောမြို့", "မောင်တောမြို့နယ်", "Maungdaw"]
    },
    "Kyaukphyu": {
        "mimu_pcode": "MMR012011",
        "burmese": "ကျောက်ဖြူ",
        "district": "Kyaukphyu",
        "state_region": "Rakhine",
        "lat": 19.4267,
        "lon": 93.5583,
        "aliases": ["ကျောက်ဖြူ", "ကျောက်ဖြူမြို့", "ကျောက်ဖြူမြို့နယ်", "Kyaukphyu", "Kyaukpyu"]
    },
    "Manaung": {
        "mimu_pcode": "MMR012012",
        "burmese": "မာန်အောင်",
        "district": "Kyaukphyu",
        "state_region": "Rakhine",
        "lat": 18.8600,
        "lon": 93.7200,
        "aliases": ["မာန်အောင်", "မာန်အောင်မြို့", "မာန်အောင်မြို့နယ်", "Manaung", "Cheduba"]
    },
    "Ramree": {
        "mimu_pcode": "MMR012013",
        "burmese": "ရမ်းဗြဲ",
        "district": "Kyaukphyu",
        "state_region": "Rakhine",
        "lat": 19.0900,
        "lon": 93.8600,
        "aliases": ["ရမ်းဗြဲ", "ရမ်းဗြဲမြို့", "ရမ်းဗြဲမြို့နယ်", "Ramree", "Yanbye"]
    },
    "Ann": {
        "mimu_pcode": "MMR012014",
        "burmese": "အမ်း",
        "district": "Kyaukphyu",
        "state_region": "Rakhine",
        "lat": 19.7833,
        "lon": 94.0333,
        "aliases": ["အမ်း", "အမ်းမြို့", "အမ်းမြို့နယ်", "Ann", "An"]
    },
    "Thandwe": {
        "mimu_pcode": "MMR012015",
        "burmese": "သံတွဲ",
        "district": "Thandwe",
        "state_region": "Rakhine",
        "lat": 18.4633,
        "lon": 94.3600,
        "aliases": ["သံတွဲ", "သံတွဲမြို့", "သံတွဲမြို့နယ်", "ငပလီ", "Thandwe", "Sandoway", "Ngapali"]
    },
    "Toungup": {
        "mimu_pcode": "MMR012016",
        "burmese": "တောင်ကုတ်",
        "district": "Thandwe",
        "state_region": "Rakhine",
        "lat": 18.8500,
        "lon": 94.2333,
        "aliases": ["တောင်ကုတ်", "တောင်ကုတ်မြို့", "တောင်ကုတ်မြို့နယ်", "Toungup", "Taungup"]
    },
    "Gwa": {
        "mimu_pcode": "MMR012017",
        "burmese": "ဂွ",
        "district": "Thandwe",
        "state_region": "Rakhine",
        "lat": 17.5833,
        "lon": 94.5800,
        "aliases": ["ဂွ", "ဂွမြို့", "ဂွမြို့နယ်", "Gwa"]
    },
    # Strategically integrated theater: Paletwa (Chin State, administered by AA)
    "Paletwa": {
        "mimu_pcode": "MMR004001",
        "burmese": "ပလက်ဝ",
        "district": "Mindat",
        "state_region": "Chin",
        "lat": 21.3000,
        "lon": 92.8500,
        "aliases": ["ပလက်ဝ", "ပလက်ဝမြို့", "ပလက်ဝမြို့နယ်", "Paletwa"]
    }
}

# ─────────────────────────────────────────────────────────────────────────────
# Local Landmark & Village Registry (Maps micro-locations to Townships)
# ─────────────────────────────────────────────────────────────────────────────
KNOWN_VILLAGES: Dict[str, Dict[str, Any]] = {
    "သရက်ချို": {"township": "Ponnagyun", "burmese": "သရက်ချိုရွာ", "lat": 20.3520, "lon": 93.0120},
    "ယိုးငူ": {"township": "Ponnagyun", "burmese": "ယိုးငူရွာ", "lat": 20.3410, "lon": 93.0250},
    "ကျောက်တန်း": {"township": "Rathedaung", "burmese": "ကျောက်တန်းရွာ", "lat": 20.5100, "lon": 92.7800},
    "မီးချောင်း": {"township": "Paletwa", "burmese": "မီးချောင်းဗျူဟာ", "lat": 21.3200, "lon": 92.8600},
    "တရွန်အိုင်": {"township": "Paletwa", "burmese": "တရွန်အိုင်ဗျူဟာ", "lat": 21.2800, "lon": 92.8300},
    "ခမောင်းဆိပ်": {"township": "Maungdaw", "burmese": "ခမောင်းဆိပ်ရွာ", "lat": 21.0500, "lon": 92.2900},
    "ငပလီ": {"township": "Thandwe", "burmese": "ငပလီကမ်းခြေ", "lat": 18.4350, "lon": 94.3400},
    "မဒေးကျွန်း": {"township": "Kyaukphyu", "burmese": "မဒေးကျွန်း", "lat": 19.3800, "lon": 93.6800},
    "မင်းပြင်": {"township": "Kyaukphyu", "burmese": "မင်းပြင်ရွာ", "lat": 19.4100, "lon": 93.5900},
    "တောဟိန်းတောင်": {"township": "Ann", "burmese": "တောဟိန်းတောင်ဗျူဟာ", "lat": 19.8200, "lon": 94.0700},
}


class SilverGeocoder:
    """
    Authoritative Geocoding Engine for the Arakan Lakehouse.
    Uses UN MIMU township registries and local settlement registries.
    """

    def __init__(self):
        # Sort villages by length descending so longer compound names match first
        self._sorted_villages = sorted(KNOWN_VILLAGES.items(), key=lambda x: len(x[0]), reverse=True)
        
        # Build flat list of (alias, township_name, meta) sorted by alias length descending
        aliases_list = []
        for ts_name, data in RAKHINE_TOWNSHIPS.items():
            for alias in data["aliases"]:
                aliases_list.append((alias, ts_name, data))
        self._sorted_township_aliases = sorted(aliases_list, key=lambda x: len(x[0]), reverse=True)

    def geocode_text(self, text: str) -> Optional[GeoLocation]:
        """
        Geocode raw Burmese text into a standardized GeoLocation model.
        
        Resolution Strategy:
          1. Village-level match (High accuracy: VILLAGE_CENTROID or EXACT_POINT)
          2. Township-level match (Township accuracy: TOWNSHIP_CENTROID)
          3. General theater fallback (State accuracy: STATE_LEVEL)
        """
        if not text:
            return None

        # Tier 1: Check known villages / military tactical bases
        for v_name, v_data in self._sorted_villages:
            if v_name in text:
                ts_name = v_data["township"]
                ts_meta = RAKHINE_TOWNSHIPS[ts_name]
                logger.debug(f"Resolved village: '{v_name}' -> Township '{ts_name}'")
                return GeoLocation(
                    raw_place_burmese=f"{v_name} ({ts_meta['burmese']}မြို့နယ်)",
                    raw_place_english=f"{v_name} ({ts_name})",
                    township=ts_name,
                    district=ts_meta["district"],
                    state_region=ts_meta["state_region"],
                    mimu_pcode=ts_meta["mimu_pcode"],
                    latitude=v_data["lat"],
                    longitude=v_data["lon"],
                    accuracy=LocationAccuracy.VILLAGE_CENTROID
                )

        # Tier 2: Check township names and aliases (longest match first)
        for alias, ts_name, ts_meta in self._sorted_township_aliases:
            if alias in text:
                logger.debug(f"Resolved township: '{alias}' -> '{ts_name}'")
                return GeoLocation(
                    raw_place_burmese=alias,
                    raw_place_english=ts_name,
                    township=ts_name,
                    district=ts_meta["district"],
                    state_region=ts_meta["state_region"],
                    mimu_pcode=ts_meta["mimu_pcode"],
                    latitude=ts_meta["lat"],
                    longitude=ts_meta["lon"],
                    accuracy=LocationAccuracy.TOWNSHIP_CENTROID
                )

        # Tier 3: Check generic mentions of Arakan / Rakhine
        if any(term in text for term in ["အာရက္ခ", "ရခိုင်", "Arakan", "Rakhine"]):
            return GeoLocation(
                raw_place_burmese="အာရက္ခဒေသ / ရခိုင်ပြည်နယ်",
                raw_place_english="Rakhine State (General Theater)",
                township=None,
                district=None,
                state_region="Rakhine",
                mimu_pcode=None,
                latitude=20.1444,
                longitude=92.8969,
                accuracy=LocationAccuracy.STATE_LEVEL
            )

        return None


# Global singleton instance
geocoder = SilverGeocoder()


if __name__ == "__main__":
    print("Testing SilverGeocoder (MIMU Static Joiner)...")
    test_cases = [
        "ပုဏ္ဏားကျွန်းမြို့နယ်၊ သရက်ချို နှင့် ယိုးငူကျေးရွာကြားတွင် တိုက်ပွဲဖြစ်ပွားခဲ့သည်။",
        "အမ်းမြို့နယ်ရှိ အနောက်ပိုင်းတိုင်းစစ်ဌာနချုပ် (နပခ) အနီး လက်နက်ကြီးကျရောက်။",
        "ကျောက်ဖြူမြို့နယ်၊ မဒေးကျွန်း ရေနံပိုက်လိုင်းအနီး လုံခြုံရေးတင်းကျပ်။",
        "မောင်တောမြို့နယ် နယ်စပ်စည်းရိုးအနီး တိုက်ပွဲပြင်းထန်နေသည်။",
        "အာရက္ခတပ်တော်၏ ထုတ်ပြန်ချက်။"
    ]
    for sample in test_cases:
        res = geocoder.geocode_text(sample)
        if res:
            print(f"\nText: {sample[:40]}...")
            print(f" -> Township: {res.township} | P-Code: {res.mimu_pcode} | Coords: ({res.latitude}, {res.longitude}) | Accuracy: {res.accuracy}")
        else:
            print(f"\nText: {sample[:40]}... -> UNRESOLVED")
