"""
connectivity_scorer.py — Scores RV park stops on Starlink + Cellular + Quality + Pet-Friendliness

Scoring formula (Phase 2):
  Total = (Connectivity × 0.40) + (Quality × 0.35) + (Pet_Score × 0.25)

Sub-scores:
  - Starlink: 10 if verified, 5 if mentioned, 0 if not
  - Cellular: 0-10 based on carrier coverage heuristics
  - WiFi: 0-10 based on amenity flags
  - Quality: rating × review_count factor, min 3.5★ required
  - Pet_Score: 10 if pet-friendly, 0 if restricted (THEO RULE: exclude 0-score parks)

Diesel fuel stops: identified via Overpass API along route corridor.
"""

import requests
import re
import os
import json
import math
import time
from typing import Optional, List, Dict, Tuple
from dataclasses import dataclass
from .campendium_scraper import CampendiumPark


OVERPASS_URL = "https://overpass-api.de/api/interpreter"

DIESEL_BRANDS = {
    "TA Travel Centers", "Love's", "Flying J", "Pilot", "Sapp Bros.",
    "Petro", "Road Ranger", "Buc-ee's", "AM Best", "CITGO", "Shell", "Chevron"
}

PET_KEYWORDS = [
    "pets welcome", "pet friendly", "dog park", "dog wash", "pets allowed",
    "no breed restrictions", "two pets max", "pet area", "dog walking", "pet wash"
]

PET_RESTRICT_KEYWORDS = [
    "no pets", "pets not allowed", "no dogs", "pet free", "restricted pets",
    "no animals", "service animals only"
]

QUALITY_BONUS_KEYWORDS = [
    "pool", "hot tub", "heated pool", "ev hookup", "waterfront",
    "beach access", "private dock", "golf course", "fishing", "boat ramp",
    "mini golf", "pickleball", "dog park", "bocce", "horseshoes"
]

# Quality minimum thresholds
MIN_RATING = 3.5
MIN_REVIEWS = 10


@dataclass
class ConnectivityReport:
    park: CampendiumPark
    starlink_score: int
    cellular_score: int
    wifi_score: int
    quality_score: int       # 0-10 (rating + review count + amenities)
    pet_score: int           # 0-10 (10 = pet-friendly, 0 = restricted/THEO-EXCLUDED)
    connectivity_sub: int     # 0-10 (Starlink+Cellular+WiFi composite)
    total_score: int         # 0-10 (weighted composite)
    primary_carrier: str
    starlink_verified: bool
    cellular_bars_est: int
    pet_friendly: bool       # True = Theo can stay here
    diesel_nearby: bool      # True = diesel station within 5 mi
    notes: List[str]

    def __post_init__(self):
        if self.notes is None:
            self.notes = []


class ConnectivityScorer:
    """
    Score RV parks on connectivity (Starlink + Cellular + WiFi),
    quality (rating + amenities), and pet-friendliness (Theo rule).

    Diesel fuel stops along route corridor identified via Overpass API.
    """

    def __init__(self, cache_dir: Optional[str] = None):
        self.cache_dir = cache_dir or os.path.join(
            os.path.dirname(__file__), "..", "cache"
        )
        os.makedirs(self.cache_dir, exist_ok=True)
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": "RV-Trip-Optimizer/1.0 (personal)"})

    def _cache_get(self, key: str) -> Optional[dict]:
        path = os.path.join(self.cache_dir, f"scorer_v2_{key}.json")
        try:
            if os.path.exists(path):
                with open(path) as f:
                    return json.load(f)
        except Exception:
            pass
        return None

    def _cache_set(self, key: str, data: dict):
        path = os.path.join(self.cache_dir, f"scorer_v2_{key}.json")
        try:
            with open(path, "w") as f:
                json.dump(data, f)
        except Exception:
            pass

    def score_park(
        self,
        park: CampendiumPark,
        fetch_details: bool = False,
    ) -> ConnectivityReport:
        """
        Full scoring: Connectivity + Quality + Pet (Theo) + Diesel.
        """
        key_base = f"{park.name.replace(' ', '_')}_{park.lat}_{park.lon}"
        cached = self._cache_get(key_base)
        if cached:
            return ConnectivityReport(park=park, **cached)

        # ── Sub-scores ──────────────────────────────────
        starlink_score, starlink_verified = self._score_starlink(park)
        cellular_score, carrier, bars = self._score_cellular(park.lat, park.lon)
        wifi_score = self._score_wifi(park)
        quality_score = self._score_quality(park)
        pet_score, pet_notes = self._score_pet(park)

        # Connectivity composite (0-10)
        connectivity_sub = int(
            starlink_score * 0.5 +
            cellular_score * 0.3 +
            wifi_score * 0.2
        )

        # Weighted total
        total_score = int(
            connectivity_sub * 0.40 +
            quality_score * 0.35 +
            pet_score * 0.25
        )

        # Pet-friendliness flag (Theo rule)
        pet_friendly = pet_score >= 5

        # Diesel nearby
        diesel_nearby = self._has_diesel_nearby(park.lat, park.lon)

        notes = []
        if starlink_verified:
            notes.append("Starlink verified")
        if pet_friendly:
            notes.append(f"Theo welcome: {pet_notes}")
        if diesel_nearby:
            notes.append("Diesel within 5 mi")
        if not park.rating or park.rating < MIN_RATING:
            notes.append(f"Rating {park.rating or '?'} below 3.5★ threshold")

        report = ConnectivityReport(
            park=park,
            starlink_score=starlink_score,
            cellular_score=cellular_score,
            wifi_score=wifi_score,
            quality_score=quality_score,
            pet_score=pet_score,
            connectivity_sub=connectivity_sub,
            total_score=total_score,
            primary_carrier=carrier or "Unknown",
            starlink_verified=starlink_verified,
            cellular_bars_est=bars,
            pet_friendly=pet_friendly,
            diesel_nearby=diesel_nearby,
            notes=notes,
        )

        cache_data = {
            k: v for k, v in vars(report).items()
            if k != "park"
        }
        self._cache_set(key_base, cache_data)

        return report

    def score_batch(
        self,
        parks: List[CampendiumPark],
        fetch_details: bool = False,
        require_pet_friendly: bool = True,
        require_min_quality: bool = True,
    ) -> List[ConnectivityReport]:
        """
        Score multiple parks, filter by pet/quality thresholds, return sorted.
        THEO RULE: require_pet_friendly=True excludes all parks scoring 0 on pet_score.
        """
        results = []
        for park in parks:
            if park.lat is None or park.lon is None:
                continue
            report = self.score_park(park, fetch_details=fetch_details)

            # THEO RULE: skip parks that don't allow pets
            if require_pet_friendly and not report.pet_friendly:
                continue

            # Quality filter
            if require_min_quality:
                if not report.park.rating or report.park.rating < MIN_RATING:
                    continue
                if report.park.review_count < MIN_REVIEWS:
                    continue

            results.append(report)
            time.sleep(0.3)  # Rate limit

        results.sort(key=lambda r: r.total_score, reverse=True)
        return results

    def _score_starlink(self, park: CampendiumPark) -> Tuple[int, bool]:
        """Starlink: 10 if verified amenity flag, 5 if mentioned in reviews."""
        combined = " ".join(park.amenities).lower() + " " + park.name.lower()
        if any(kw in combined for kw in ["starlink", "spacex", "satellite internet"]):
            return 10, True
        if park.starlink_mentions >= 3:
            return 10, True
        if park.starlink_mentions > 0:
            return 7, False
        return 0, False

    def _score_cellular(self, lat: float, lon: float) -> Tuple[int, str, int]:
        """Cellular coverage heuristic based on geography."""
        score, carrier, bars = self._fcc_heuristic(lat, lon)
        return score, carrier, bars

    def _fcc_heuristic(self, lat: float, lon: float) -> Tuple[int, str, int]:
        """Rough cellular heuristic for TX/AR corridor."""
        known = {
            (32.7767, -96.7970): ("Dallas", "AT&T/Verizon", 5),
            (30.2672, -97.7431): ("Austin", "All carriers", 5),
            (29.7604, -95.3698): ("Houston", "All carriers", 5),
            (34.7465, -92.2896): ("Little Rock", "AT&T/T-Mobile", 4),
            (32.3510, -95.3010): ("East TX", "Verizon", 3),
            (31.9686, -99.9018): ("TX Rural", "Verizon", 2),
            (34.8800, -92.1000): ("AR Rural", "AT&T", 2),
        }
        best_dist = float("inf")
        best = ("Rural", "Verizon", 2)
        for (clat, clon), info in known.items():
            d = math.sqrt((lat - clat) ** 2 + (lon - clon) ** 2)
            if d < best_dist:
                best_dist = d
                best = info

        city, carrier, bars = best
        if best_dist < 0.5:
            return bars * 2, carrier, bars
        elif best_dist < 1.5:
            return max(2, bars * 2 - 2), carrier, max(1, bars - 1)
        return 4, "Verizon", 2

    def _score_wifi(self, park: CampendiumPark) -> int:
        """WiFi score from amenity list."""
        text = " ".join(park.amenities).lower()
        matches = sum(1 for w in ["wifi", "wi-fi", "free wifi", "free wi-fi", "internet"] if w in text)
        if matches >= 2:
            return 10
        elif matches == 1:
            return 7
        elif any(p in text for p in ["campstore wifi", "cafe wifi", "lobby wifi"]):
            return 4
        return 0

    def _score_quality(self, park: CampendiumPark) -> int:
        """
        Quality score: rating (0-10 scaled) + review count bonus + amenity bonus.
        Parks below 3.5★ or < 10 reviews get filtered out downstream.
        """
        rating = park.rating or 0.0

        # Rating component (0-8)
        rating_score = min(8, rating * 2)

        # Review count bonus (0-1)
        rc = park.review_count
        if rc >= 200:
            review_bonus = 1.0
        elif rc >= 50:
            review_bonus = 0.7
        elif rc >= 20:
            review_bonus = 0.4
        elif rc >= 10:
            review_bonus = 0.2
        else:
            review_bonus = 0.0

        # Amenity bonus (0-1)
        text = " ".join(park.amenities).lower()
        amenity_bonus = sum(1 for kw in QUALITY_BONUS_KEYWORDS if kw in text) * 0.25
        amenity_bonus = min(1.0, amenity_bonus)

        return int(min(10, rating_score + review_bonus + amenity_bonus))

    def _score_pet(self, park: CampendiumPark) -> Tuple[int, str]:
        """
        Pet-friendliness score for Theo.
        Returns (score 0-10, note).
        Score 0 = restricted (excluded), Score 10 = confirmed pet-friendly.
        """
        text = " ".join(park.amenities).lower() + " " + park.name.lower()

        # Check restrictions first
        for kw in PET_RESTRICT_KEYWORDS:
            if kw in text:
                return 0, "pets restricted"

        # Check positive indicators
        matches = sum(1 for kw in PET_KEYWORDS if kw in text)
        if matches >= 2:
            return 10, "multiple pet amenities"
        elif matches == 1:
            return 10, "pet-friendly confirmed"
        return 5, "pet policy unclear"

    def _has_diesel_nearby(self, lat: float, lon: float, radius_mi: float = 5.0) -> bool:
        """
        Check for diesel fuel stations within radius_mi using Overpass API.
        Caches result per lat/lon bucket (0.5° grid).
        """
        # Bucket cache to avoid duplicate API calls
        bucket_lat = round(lat * 2) / 2
        bucket_lon = round(lon * 2) / 2
        cache_key = f"diesel_{bucket_lat}_{bucket_lon}"
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached

        # Overpass query: fuel stations within bounding box
        lat_delta = radius_mi / 69.0  # ~69 mi per degree
        lon_delta = radius_mi / 54.6   # ~54.6 mi per degree at mid-latitudes

        query = f"""
        [out:json][timeout:10];
        node["amenity"="fuel"]({lat - lat_delta},{lon - lon_delta},{lat + lat_delta},{lon + lon_delta});
        out body;
        """
        try:
            resp = self._session.post(
                OVERPASS_URL,
                data={"data": query},
                timeout=15,
            )
            if resp.status_code == 200:
                data = resp.json()
                nodes = data.get("elements", [])
                for node in nodes:
                    tags = node.get("tags", {})
                    name = tags.get("name", "")
                    brand = tags.get("brand", "")
                    fuel = tags.get("fuel", "")
                    # Check for diesel brand or diesel fuel type
                    if any(b in (name + brand) for b in DIESEL_BRANDS):
                        self._cache_set(cache_key, True)
                        return True
                    if "diesel" in fuel.lower():
                        self._cache_set(cache_key, True)
                        return True
            self._cache_set(cache_key, False)
            return False
        except Exception:
            self._cache_set(cache_key, False)
            return False

    def format_badge(self, report: ConnectivityReport) -> str:
        """Formatted one-line connectivity + pet badge."""
        parts = []
        if report.starlink_verified:
            parts.append("Starlink ✓")
        bars = "★" * report.cellular_bars_est + "☆" * (5 - report.cellular_bars_est)
        if report.primary_carrier:
            parts.append(f"{report.primary_carrier} {bars}")
        if report.pet_friendly:
            parts.append("🐾 Pet OK")
        if report.diesel_nearby:
            parts.append("⛽ Diesel")
        return " | ".join(parts) if parts else "No connectivity data"

    def format_full_badge(self, report: ConnectivityReport) -> Dict[str, str]:
        """Return structured badge dict for Streamlit rendering."""
        return {
            "connectivity": f"Starlink {'✓' if report.starlink_verified else '✗'} | {report.primary_carrier} {'★' * report.cellular_bars_est}{'☆' * (5 - report.cellular_bars_est)}",
            "pet": "🐾 Theo OK" if report.pet_friendly else "🚫 No Pets",
            "diesel": "⛽ Diesel nearby" if report.diesel_nearby else "⛽ No diesel data",
            "quality": f"★ {report.park.rating:.1f} ({report.park.review_count} reviews)" if report.park.rating else "No rating",
            "price": f"${report.park.price_low}/night" if report.park.price_low else "Price N/A",
            "total": f"{report.total_score}/10",
        }
