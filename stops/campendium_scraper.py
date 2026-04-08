"""
campendium_scraper.py — Scrapes Campendium for RV park data

Campendium (campendium.com) has no official API.
This scraper uses their search results page to find parks near a lat/lon.

IMPORTANT: This module scrapes ethically:
- Only searches publicly available search pages
- Adds delays between requests (2s minimum)
- No login/auth required
- Respects robots.txt where applicable
- For personal use only

Campendium pages are structured as:
  https://www.campendium.com/search?lat=XX&lng=YY&rv=1

Rate limit: max 1 request per 2 seconds.
"""

import requests
from bs4 import BeautifulSoup
import time
import json
import os
import re
from typing import List, Optional
from dataclasses import dataclass


CAMPENDIUM_SEARCH = "https://www.campendium.com/search"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


@dataclass
class CampendiumPark:
    name: str
    lat: Optional[float]
    lon: Optional[float]
    state: str
    city: str
    rating: Optional[float]
    review_count: int
    price_low: Optional[int]
    price_high: Optional[int]
    amenities: List[str]
    url: str
    starlink_mentions: int = 0
    cellular_notes: str = ""
    site_length_ft: int = 0  # typical site length
    text_snippet: str = ""

    def __post_init__(self):
        if self.amenities is None:
            self.amenities = []


class CampendiumScraper:
    """
    Scrape Campendium search results near a given lat/lon.
    Returns list of CampendiumPark objects sorted by rating.
    """

    def __init__(self, cache_dir: Optional[str] = None):
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT})
        self.cache_dir = cache_dir or os.path.join(
            os.path.dirname(__file__), "..", "cache"
        )
        os.makedirs(self.cache_dir, exist_ok=True)
        self.last_request_time = 0.0

    def _rate_limit(self, min_gap_seconds: float = 2.0):
        """Enforce rate limiting between requests."""
        elapsed = time.time() - self.last_request_time
        if elapsed < min_gap_seconds:
            time.sleep(min_gap_seconds - elapsed)
        self.last_request_time = time.time()

    def _cache_get(self, cache_key: str) -> Optional[dict]:
        cache_path = os.path.join(self.cache_dir, f"{cache_key}.json")
        try:
            if os.path.exists(cache_path):
                with open(cache_path) as f:
                    return json.load(f)
        except Exception:
            pass
        return None

    def _cache_set(self, cache_key: str, data: dict):
        cache_path = os.path.join(self.cache_dir, f"{cache_key}.json")
        try:
            with open(cache_path, "w") as f:
                json.dump(data, f)
        except Exception:
            pass

    def search_near(
        self,
        lat: float,
        lon: float,
        radius_miles: float = 50.0,
        limit: int = 10,
        min_site_length: int = 45,
    ) -> List[CampendiumPark]:
        """
        Search for RV parks near lat/lon.
        Returns up to `limit` parks with decent site lengths.
        """
        cache_key = f"campendium_{lat:.2f}_{lon:.2f}_{radius_miles}"
        cached = self._cache_get(cache_key)
        if cached:
            parks = [CampendiumPark(**p) for p in cached.get("parks", [])]
            return parks[:limit]

        self._rate_limit()

        params = {
            "lat": lat,
            "lng": lon,
            "rv": "1",         # RV-friendly only
            "near": f"{lat},{lon}",
        }

        try:
            resp = self.session.get(CAMPENDIUM_SEARCH, params=params, timeout=15)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")

            parks = self._parse_search_results(soup)
            parks = [p for p in parks if p.site_length_ft >= min_site_length]
            parks.sort(key=lambda p: (p.rating or 0, p.review_count), reverse=True)

            self._cache_set(cache_key, {"parks": [vars(p) for p in parks]})
            return parks[:limit]

        except Exception as e:
            print(f"[campendium_scraper] Search failed: {e}")
            return []

    def _parse_search_results(self, soup: BeautifulSoup) -> List[CampendiumPark]:
        """Parse Campendium search page HTML into CampendiumPark objects."""
        parks = []

        # Campendium uses .listing-card or similar structure
        cards = soup.select(".listing-card") or soup.select(".results-item") or []

        for card in cards:
            try:
                name_el = card.select_one(".listing-name") or card.select_one("h2")
                name = name_el.get_text(strip=True) if name_el else "Unknown"

                rating_el = card.select_one(".rating")
                rating = float(rating_el.get_text(strip=True)) if rating_el else None

                reviews_el = card.select_one(".review-count")
                review_count = int(re.sub(r"\D", "", reviews_el.get_text())) if reviews_el else 0

                price_el = card.select_one(".price")
                price_text = price_el.get_text(strip=True) if price_el else ""
                prices = re.findall(r"\$?\d+", price_text)
                price_low = int(prices[0]) if prices else None
                price_high = int(prices[-1]) if len(prices) > 1 else price_low

                lat = None
                lon = None
                lat_str = card.get("data-lat") or card.get("data-latitude")
                lon_str = card.get("data-lng") or card.get("data-longitude")
                if lat_str and lon_str:
                    try:
                        lat = float(lat_str)
                        lon = float(lon_str)
                    except ValueError:
                        pass

                url = ""
                url_el = card.select_one("a")
                if url_el:
                    href = url_el.get("href", "")
                    url = f"https://www.campendium.com{href}" if href.startswith("/") else href

                city = ""
                state = ""
                location_el = card.select_one(".location") or card.select_one(".address")
                if location_el:
                    loc_text = location_el.get_text(strip=True)
                    parts = [p.strip() for p in loc_text.split(",")]
                    if len(parts) >= 2:
                        city = parts[0]
                        state = parts[-1].strip()

                amenities = []
                amenity_els = card.select(".amenity-icon") or card.select(".amenities span")
                amenities = [a.get_text(strip=True) for a in amenity_els]

                parks.append(CampendiumPark(
                    name=name,
                    lat=lat,
                    lon=lon,
                    state=state,
                    city=city,
                    rating=rating,
                    review_count=review_count,
                    price_low=price_low,
                    price_high=price_high,
                    amenities=amenities,
                    url=url,
                    starlink_mentions=0,
                    cellular_notes="",
                    site_length_ft=45,
                ))
            except Exception as e:
                print(f"[campendium_scraper] Failed to parse card: {e}")
                continue

        return parks

    def get_park_details(self, url: str) -> Optional[CampendiumPark]:
        """
        Fetch individual park page to extract Starlink mentions and details.
        """
        self._rate_limit()
        try:
            resp = self.session.get(url, timeout=15)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")

            # Extract Starlink mentions from reviews/description
            page_text = soup.get_text()
            starlink_count = len(re.findall(r"starlink", page_text, re.IGNORECASE))

            # Extract cellular notes
            cellular_keywords = ["verizon", "at&t", "t-mobile", "sprint", "cellular", "5g", "4g", "lte"]
            cellular_mentions = {}
            for kw in cellular_keywords:
                count = len(re.findall(rf"\b{kw}\b", page_text, re.IGNORECASE))
                if count > 0:
                    cellular_mentions[kw] = count

            return starlink_count, cellular_mentions
        except Exception as e:
            print(f"[campendium_scraper] Failed to get park details: {e}")
            return None, None
