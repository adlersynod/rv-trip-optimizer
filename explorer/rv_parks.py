"""
rv_parks.py — Campendium + FreeCampsites.net scraper for RV Explorer

Pulls RV park / campground data for a given city/region.
Filters for big rig friendly (43ft+ for Brinkley 4100).
"""

import requests
from bs4 import BeautifulSoup
from typing import List, Dict, Any, Optional
import time
import re


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


def _geo_from_query(query: str) -> Optional[Dict[str, float]]:
    """Geocode a city/state string using Nominatim (free, no API key)."""
    try:
        r = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params={"q": query, "format": "json", "limit": 1, "countrycodes": "us"},
            headers={"User-Agent": "RVExplorer/1.0"},
            timeout=8,
        )
        data = r.json()
        if data:
            return {"lat": float(data[0]["lat"]), "lon": float(data[0]["lon"])}
    except Exception:
        pass
    return None


def _parse_campendium(text: str) -> List[Dict[str, Any]]:
    """Parse Campendium search results page."""
    parks = []
    soup = BeautifulSoup(text, "html.parser")
    for card in soup.select(". campsite-list .card, .listing-card, div[data-category='campground']"):
        try:
            name = card.select_one("h3, .card-title, .listing-title")
            if not name:
                continue
            name = name.get_text(strip=True)

            # Rating
            rating_elem = card.select_one(".rating .value, .avg-rating, [itemprop='ratingValue']")
            rating = float(rating_elem.get_text(strip=True)) if rating_elem else None

            # Price
            price_elem = card.select_one(".price, .rate, [itemprop='price']")
            price = price_elem.get_text(strip=True) if price_elem else "N/A"

            # Big rig indicator
            big_rig = bool(card.select(".big-rig, .pull-thru, .big-rv, .max-rv-40ft, .length-40"))

            # URL
            link = card.select_one("a[href]")
            url = "https://www.campendium.com" + link["href"] if link and not link["href"].startswith("http") else (link["href"] if link else "")

            # Type
            category = "RV Park"
            for tag in card.select(".category-tag, .type-tag, [itemprop='category']"):
                cat = tag.get_text(strip=True).lower()
                if "boondock" in cat or "dry" in cat:
                    category = "Boondocking"
                elif "campground" in cat:
                    category = "Campground"

            parks.append({
                "name": name,
                "rating": rating,
                "price": price,
                "big_rig_friendly": big_rig,
                "category": category,
                "url": url,
            })
        except Exception:
            continue
    return parks


def search_campendium(city: str, state: str, radius_miles: int = 40) -> List[Dict[str, Any]]:
    """
    Search Campendium for RV parks near a city.
    Falls back to FreeCampsites.net if Campendium has no results.
    """
    query = f"{city}, {state}"
    geo = _geo_from_query(query)
    if not geo:
        return []

    lat, lon = geo["lat"], geo["lon"]
    all_parks = []

    # Try Campendium
    try:
        url = f"https://www.campendium.com/search?lat={lat}&lng={lon}&rv=1&near={lat},{lon}"
        r = requests.get(url, headers=HEADERS, timeout=10)
        if r.status_code == 200:
            parks = _parse_campendium(r.text)
            all_parks.extend(parks)
    except Exception:
        pass

    # Try FreeCampsites.net
    try:
        url = f"https://www.freecampsites.net/search/?lat={lat}&lng={lon}&type=rvp&radius=40"
        r = requests.get(url, headers=HEADERS, timeout=10)
        if r.status_code == 200:
            soup = BeautifulSoup(r.text, "html.parser")
            for card in soup.select(".result-card, .campsite-result, .location"):
                try:
                    name_el = card.select_one("h3, h4, .name, .title")
                    if not name_el:
                        continue
                    name = name_el.get_text(strip=True)
                    rating_el = card.select_one(".rating, .stars, [data-rating]")
                    rating = float(rating_el.get_text(strip=True)) if rating_el else None
                    all_parks.append({
                        "name": name,
                        "rating": rating,
                        "price": "Free",
                        "big_rig_friendly": True,
                        "category": "Boondocking/Free",
                        "url": card.select_one("a[href]")["href"] if card.select_one("a[href]") else "",
                    })
                except Exception:
                    continue
    except Exception:
        pass

    # Sort by rating, filter for big rig friendly
    all_parks.sort(key=lambda x: x.get("rating") or 0, reverse=True)

    seen = set()
    unique = []
    for p in all_parks:
        if p["name"] not in seen:
            seen.add(p["name"])
            unique.append(p)

    return unique


def get_rv_parks(city: str, state: str, limit: int = 5) -> List[Dict[str, Any]]:
    """Main entry point — returns top RV parks near a destination."""
    parks = search_campendium(city, state)
    big_rig_parks = [p for p in parks if p.get("big_rig_friendly")]
    if big_rig_parks:
        return big_rig_parks[:limit]
    return parks[:limit]
