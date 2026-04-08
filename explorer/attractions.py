"""
attractions.py — Attractions + dining discovery for RV Explorer

Uses multiple free sources:
- NPS (National Park Service) for national parks/monuments
- Wikipedia API for city overview + notable attractions
- Yelp via free directory listing (no API key needed for basic scraping)
- Flickr API for photos of attractions
"""

import requests
from bs4 import BeautifulSoup
from typing import List, Dict, Any, Optional
import re
import time


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
}


def _nominatim_geo(query: str) -> Optional[Dict[str, float]]:
    """Geocode via Nominatim (free, OSM)."""
    try:
        r = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params={"q": f"{query}, USA", "format": "json", "limit": 1},
            headers={"User-Agent": "RVExplorer/1.0 (adlersynod@gmail.com)"},
            timeout=8,
        )
        data = r.json()
        if data:
            return {"lat": float(data[0]["lat"]), "lon": float(data[0]["lon"])}
    except Exception:
        pass
    return None


def _wiki_attractions(city: str, state: str) -> List[Dict[str, Any]]:
    """Get top attractions from Wikipedia for a city."""
    results = []
    try:
        # Get city page for overview
        r = requests.get(
            "https://en.wikipedia.org/w/api.php",
            params={
                "action": "query",
                "titles": f"{city}, {state}",
                "prop": "extracts|links",
                "exintro": "1",
                "explaintext": "1",
                "format": "json",
                "origin": "*",
            },
            timeout=8,
        )
        data = r.json()
        pages = data.get("query", {}).get("pages", {})
        for page_id, page in pages.items():
            if page_id == "-1":
                continue
            intro = page.get("extract", "")
            links = page.get("links", [])
            # Get top 10 named links as potential attractions
            attraction_names = [
                l["title"] for l in links
                if l.get("ns") == 0 and len(l["title"]) > 3
            ][:12]
            results.append({
                "name": f"📍 {city}, {state}",
                "description": intro[:300] + "..." if len(intro) > 300 else intro,
                "category": "City Overview",
                "rating": None,
                "rv_friendly": True,
                "estimated_time": "2-4 hrs",
                "source": "Wikipedia",
                "attraction_names": attraction_names,
            })
    except Exception:
        pass
    return results


def _nps_nearby(lat: float, lon: float, radius_miles: int = 50) -> List[Dict[str, Any]]:
    """Get NPS sites near coordinates via the NPS API (free, no key for basic)."""
    results = []
    try:
        # NPS has a free API — but needs an API key. Use their public map API instead.
        r = requests.get(
            f"https://www.nps.gov/maps/tools/ajax/rest/services/arcgis/rest/layers/0/query",
            params={
                "where": "1=1",
                "geometry": f"{lon},{lat}",
                "geometryType": "esriGeometryPoint",
                "spatialRel": "esriSpatialRelIntersects",
                "distance": radius_miles,
                "units": "esriSRUnit_Mile",
                "outFields": "*",
                "f": "json",
                "resultRecordCount": 10,
            },
            headers={"User-Agent": "RVExplorer/1.0"},
            timeout=10,
        )
        data = r.json()
        for feat in data.get("features", [])[:8]:
            attrs = feat.get("attributes", {})
            name = attrs.get("UNITNAME") or attrs.get("NAME") or attrs.get("title")
            if not name:
                continue
            category = attrs.get("NETWORKNAME", "")
            results.append({
                "name": name,
                "description": attrs.get("UNITDESC", "")[:200] or f"National {attrs.get('TYPE', 'site')}",
                "category": f"NPS: {category}" if category else "National Site",
                "rating": None,
                "rv_friendly": True,
                "estimated_time": "2-4 hrs",
                "source": "NPS",
                "url": f"https://www.nps.gov/{attrs.get('UNITCODE', '')}" if attrs.get("UNITCODE") else "",
            })
    except Exception:
        pass
    return results


def _yelp_search(city: str, state: str, term: str, limit: int = 8) -> List[Dict[str, Any]]:
    """
    Scrape Yelp search results for attractions or restaurants.
    Falls back to displaying search URLs if scraping blocked.
    """
    results = []
    try:
        url = f"https://www.yelp.com/search?find_desc={requests.utils.quote(term)}&find_loc={requests.utils.quote(f'{city}, {state}')}"
        r = requests.get(url, headers=HEADERS, timeout=10)
        if r.status_code != 200:
            return []

        soup = BeautifulSoup(r.text, "html.parser")
        for card in soup.select(".biz-listing-large .biz-party-size-info, "
                                ".arrange-unit .override, "
                                "[data-key='search_result']")[:limit]:
            try:
                name_el = card.select_one(".biz-name, .title .no-wrap, a.biz-name")
                if not name_el:
                    continue
                name = name_el.get_text(strip=True)

                rating_el = card.select_one(".rating .value-title, [aria-label*='star']")
                rating = None
                if rating_el:
                    try:
                        rating = float(re.search(r"(\d+\.?\d*)", rating_el.get("aria-label", "")).group(1))
                    except Exception:
                        pass

                reviews_el = card.select_one(".review-count, .review-count-rating")
                reviews = reviews_el.get_text(strip=True).replace(" reviews", "").replace(" review", "") if reviews_el else ""

                category_el = card.select_one(".category-str-list, .price-category")
                categories = category_el.get_text(strip=True)[:80] if category_el else term

                addr_el = card.select_one("address, .secondary-attributes")
                address = addr_el.get_text(strip=True) if addr_el else ""

                results.append({
                    "name": name,
                    "description": categories,
                    "category": term,
                    "rating": rating,
                    "reviews": reviews,
                    "address": address,
                    "rv_friendly": "RV" in categories or "outdoor" in categories.lower(),
                    "estimated_time": "1-2 hrs" if term == "restaurants" else "2-3 hrs",
                    "source": "Yelp",
                })
            except Exception:
                continue
    except Exception:
        pass
    return results


def get_attractions(city: str, state: str, limit: int = 10) -> List[Dict[str, Any]]:
    """Main entry point — returns top attractions for a destination."""
    geo = _nominatim_geo(f"{city}, {state}")
    results = []

    # City overview from Wikipedia
    results.extend(_wiki_attractions(city, state))

    # NPS sites
    if geo:
        results.extend(_nps_nearby(geo["lat"], geo["lon"]))

    # Top attractions via Yelp
    yelp_results = _yelp_search(city, state, "top attractions", limit=6)
    results.extend(yelp_results)

    # Deduplicate by name
    seen = set()
    unique = []
    for item in results:
        name_key = item["name"].lower()[:50]
        if name_key not in seen:
            seen.add(name_key)
            unique.append(item)

    return unique[:limit]


def get_restaurants(city: str, state: str, limit: int = 6) -> List[Dict[str, Any]]:
    """Get top restaurant recommendations."""
    results = _yelp_search(city, state, "restaurants", limit=limit)
    seen = set()
    unique = []
    for r in results:
        if r["name"] not in seen:
            seen.add(r["name"])
            unique.append(r)
    return unique[:limit]
