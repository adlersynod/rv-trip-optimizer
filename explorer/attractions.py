"""
attractions.py — Rich destination discovery for RV Explorer

Five-tier recommendation system:
  1. Tourist Favorites  — top-rated must-see destinations (Yelp, TripAdvisor)
  2. Local Gems         — underrated spots known to locals (Yelp neighborhood, Reddit)
  3. Unique Ideas       — unusual, one-of-a-kind experiences
  4. Food & Drink       — top dining + local breweries
  5. RV- Specific       — scenic drives, overlooks, outdoor activities

Each result includes: name, description, category, rating, hours, address, URL, source.
"""

import requests
from bs4 import BeautifulSoup
from typing import List, Dict, Any, Optional
import re
import time
import random

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


# ─────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────

def _nominatim_geo(query: str) -> Optional[Dict[str, float]]:
    """Geocode via Nominatim (free OSM)."""
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


def _youtube_thumbnail(place_name: str) -> Optional[str]:
    """Return a YouTube search thumbnail URL for scenic locations."""
    q = requests.utils.quote(f"{place_name} scenic")
    return f"https://img.youtube.com/vi/0/{q[:20]}/hqdefault.jpg"


def _scrape_yelp_category(city: str, state: str, category: str, limit: int = 8) -> List[Dict[str, Any]]:
    """
    Scrape Yelp search results for a given category.
    Returns rich result objects with ratings, hours, address, URL.
    """
    results = []
    try:
        url = (
            f"https://www.yelp.com/search?find_desc={requests.utils.quote(category)}"
            f"&find_loc={requests.utils.quote(f'{city}, {state}')}&cflt={requests.utils.quote(category)}"
        )
        r = requests.get(url, headers=HEADERS, timeout=12)
        if r.status_code != 200:
            return []
        soup = BeautifulSoup(r.text, "html.parser")

        for item in soup.select(".search-result .biz-listing .arrange-unit")[:limit]:
            try:
                # Name
                name_el = item.select_one(".biz-name span")
                if not name_el:
                    continue
                name = name_el.get_text(strip=True)

                # URL
                link_el = item.select_one("a.biz-name")
                href = link_el.get("href", "") if link_el else ""
                yelp_url = f"https://www.yelp.com{href}" if href else ""

                # Rating
                rating_el = item.select_one("[aria-label*=star], .i-stars")
                rating = None
                if rating_el:
                    m = re.search(r"(\d+\.?\d*)", rating_el.get("aria-label", ""))
                    if m:
                        rating = float(m.group(1))

                # Review count
                rev_el = item.select_one(".review-count")
                reviews = rev_el.get_text(strip=True).replace(" reviews", "").replace(" review", "").replace("(", "").replace(")", "") if rev_el else ""

                # Price + category
                cat_el = item.select_one(".category-str-list")
                cat_text = cat_el.get_text(strip=True) if cat_el else category

                # Address
                addr_el = item.select_one(".secondary-attributes address")
                address = addr_el.get_text(strip=True) if addr_el else ""

                # Hours (if open now)
                hours_el = item.select_one(".hourly-hours-mention, .is-open")
                hours_text = hours_el.get_text(strip=True) if hours_el else ""

                results.append({
                    "name": name,
                    "yelp_url": yelp_url,
                    "rating": rating,
                    "reviews": reviews,
                    "category": cat_text[:80],
                    "address": address,
                    "hours": hours_text,
                    "source": "Yelp",
                })
            except Exception:
                continue

        # Small delay to be respectful
        time.sleep(random.uniform(0.3, 0.7))
    except Exception:
        pass
    return results


def _nps_nearby(lat: float, lon: float, radius_miles: int = 60) -> List[Dict[str, Any]]:
    """
    Get NPS sites near coordinates via ArcGIS endpoint.
    Covers national parks, monuments, historic sites, etc.
    """
    results = []
    try:
        r = requests.get(
            "https://www.nps.gov/maps/tools/ajax/rest/services/arcgis/rest/layers/0/query",
            params={
                "where": "1=1",
                "geometry": f"{lon},{lat}",
                "geometryType": "esriGeometryPoint",
                "spatialRel": "esriSpatialRelIntersects",
                "distance": radius_miles,
                "units": "esriSRUnit_Mile",
                "outFields": "UNITNAME,UNITCODE,UNITDESC,NETWORKNAME,TYPE",
                "f": "json",
                "resultRecordCount": 8,
            },
            headers={"User-Agent": "RVExplorer/1.0"},
            timeout=10,
        )
        data = r.json()
        for feat in data.get("features", [])[:8]:
            attrs = feat.get("attributes", {})
            name = attrs.get("UNITNAME") or attrs.get("NAME")
            if not name:
                continue
            code = attrs.get("UNITCODE", "")
            results.append({
                "name": name,
                "category": f"NPS: {attrs.get('NETWORKNAME', attrs.get('TYPE', 'National Site'))}",
                "description": (attrs.get("UNITDESC") or f"National {attrs.get('TYPE', 'site')}")[:300],
                "rating": None,
                "nps_url": f"https://www.nps.gov/{code}/index.htm" if code else "",
                "source": "NPS",
                "estimated_time": "2-4 hrs",
            })
    except Exception:
        pass
    return results


def _wiki_city_overview(city: str, state: str) -> List[Dict[str, Any]]:
    """
    Pull city overview + notable landmarks from Wikipedia API.
    Returns intro + top-talked-about places from the city's Wikipedia page.
    """
    results = []
    try:
        r = requests.get(
            "https://en.wikipedia.org/w/api.php",
            params={
                "action": "query",
                "titles": f"{city}, {state}",
                "prop": "extracts|links|pageimages",
                "exintro": "1",
                "explaintext": "1",
                "format": "json",
                "origin": "*",
                "pllimit": "max",
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
            page_title = page.get("title", f"{city}, {state}")
            thumb = page.get("thumbnail", {})
            thumb_url = thumb.get("source", "") if thumb else ""

            # Notable linked articles as potential attractions
            attraction_names = [
                l["title"] for l in links
                if l.get("ns") == 0
                and len(l["title"]) > 3
                and not any(
                    bad in l["title"].lower()
                    for bad in ["list of", "index", "outline", "history of", "timeline"]
                )
            ][:15]

            results.append({
                "name": page_title,
                "category": "City Overview",
                "description": intro[:500] + "..." if len(intro) > 500 else intro,
                "rating": None,
                "wiki_url": f"https://en.wikipedia.org/wiki/{requests.utils.quote(page_title)}",
                "thumbnail": thumb_url,
                "source": "Wikipedia",
                "attraction_names": attraction_names,
                "estimated_time": "2-4 hrs (city tour)",
            })
    except Exception:
        pass
    return results


def _wiki_notable_attractions(attraction_names: List[str]) -> List[Dict[str, Any]]:
    """
    Given a list of attraction names from the city page, fetch their descriptions.
    """
    results = []
    if not attraction_names:
        return results
    try:
        titles = "|".join(attraction_names[:10])
        r = requests.get(
            "https://en.wikipedia.org/w/api.php",
            params={
                "action": "query",
                "titles": titles,
                "prop": "extracts|pageimages",
                "exintro": "1",
                "explaintext": "1",
                "format": "json",
                "origin": "*",
            },
            timeout=10,
        )
        data = r.json()
        pages = data.get("query", {}).get("pages", {})
        for page_id, page in pages.items():
            if page_id == "-1":
                continue
            name = page.get("title", "")
            extract = page.get("extract", "")
            thumb = page.get("thumbnail", {})
            thumb_url = thumb.get("source", "") if thumb else ""
            results.append({
                "name": name,
                "category": "Notable Landmark",
                "description": extract[:300] + "..." if len(extract) > 300 else extract,
                "wiki_url": f"https://en.wikipedia.org/wiki/{requests.utils.quote(name)}",
                "thumbnail": thumb_url,
                "source": "Wikipedia",
                "estimated_time": "1-2 hrs",
                "tier": "tourist_favorite",
            })
        time.sleep(random.uniform(0.2, 0.5))
    except Exception:
        pass
    return results


def _tripadvisor_attractions(city: str, state: str, limit: int = 8) -> List[Dict[str, Any]]:
    """
    Scrape TripAdvisor attractions for tourist favorites.
    """
    results = []
    try:
        url = f"https://www.tripadvisor.com/Attractions-{requests.utils.quote(city)}-1-{requests.utils.quote(state)}.html"
        r = requests.get(url, headers=HEADERS, timeout=12)
        if r.status_code != 200:
            return []
        soup = BeautifulSoup(r.text, "html.parser")
        for item in soup.select(".attraction_list .listing .title a")[:limit]:
            try:
                name = item.get_text(strip=True)
                href = item.get("href", "")
                ta_url = f"https://www.tripadvisor.com{href}" if href else ""
                results.append({
                    "name": name,
                    "ta_url": ta_url,
                    "category": "Tourist Attraction",
                    "source": "TripAdvisor",
                    "estimated_time": "1-3 hrs",
                    "tier": "tourist_favorite",
                })
            except Exception:
                continue
    except Exception:
        pass
    return results


def _local_gems_reddit(city: str, state: str) -> List[Dict[str, Any]]:
    """
    Discover local gems via Reddit search (r/city + r/Visiting).
    Returns a curated list of 'underrated' local recommendations.
    """
    gems = []
    try:
        # Try r/city wiki or top posts for recommendations
        subreddit = city.lower().replace(" ", "")
        url = f"https://www.reddit.com/r/{subreddit}/top.json?limit=10&t=year"
        r = requests.get(
            url,
            headers={"User-Agent": "RVExplorer/1.0 (adlersynod@gmail.com)"},
            timeout=8,
        )
        if r.status_code == 200:
            data = r.json()
            for post in data.get("data", {}).get("children", [])[:6]:
                title = post.get("data", {}).get("title", "")
                score = post.get("data", {}).get("score", 0)
                url_post = post.get("data", {}).get("url", "")
                if score > 50 and len(title) > 10:
                    gems.append({
                        "name": title,
                        "category": "Local Recommendation",
                        "description": f"{score} upvotes on r/{subreddit}",
                        "reddit_url": post.get("data", {}).get("permalink", ""),
                        "source": "Reddit",
                        "tier": "local_gem",
                        "estimated_time": "1-2 hrs",
                    })
    except Exception:
        pass
    return gems


# ─────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────

def get_tourist_favorites(city: str, state: str, limit: int = 8) -> List[Dict[str, Any]]:
    """Top-rated tourist attractions and must-see destinations."""
    results = []

    # Yelp top attractions
    yelp = _scrape_yelp_category(city, state, "attractions", limit=6)
    for r in yelp:
        r["tier"] = "tourist_favorite"
        results.append(r)

    # TripAdvisor
    ta = _tripadvisor_attractions(city, state, limit=5)
    results.extend(ta)

    # NPS
    geo = _nominatim_geo(f"{city}, {state}")
    if geo:
        nps = _nps_nearby(geo["lat"], geo["lon"], radius_miles=60)
        for r in nps:
            r["tier"] = "tourist_favorite"
            results.append(r)

    # Deduplicate by name
    seen = set()
    unique = []
    for item in results:
        key = item["name"].lower()[:60]
        if key not in seen:
            seen.add(key)
            item.setdefault("tier", "tourist_favorite")
            unique.append(item)
    return unique[:limit]


def get_local_gems(city: str, state: str, limit: int = 6) -> List[Dict[str, Any]]:
    """
    Underrated, locally-loved spots. Mix of:
    - Neighborhood parks and viewpoints
    - Local diners and hidden restaurants
    - Underrated museums and cultural spots
    """
    results = []

    # Yelp neighborhoods
    geo = _nominatim_geo(f"{city}, {state}")
    neighborhoods = ["Parks", "Local Flavor", "Hidden Gems", "Neighborhoods"]
    for cat in neighborhoods:
        yelp = _scrape_yelp_category(city, state, cat, limit=4)
        for r in yelp:
            r["tier"] = "local_gem"
            results.append(r)

    # Reddit local gems
    reddit_gems = _local_gems_reddit(city, state)
    results.extend(reddit_gems)

    # Deduplicate
    seen = set()
    unique = []
    for item in results:
        key = item["name"].lower()[:60]
        if key not in seen:
            seen.add(key)
            item.setdefault("tier", "local_gem")
            unique.append(item)
    return unique[:limit]


def get_unique_ideas(city: str, state: str, limit: int = 5) -> List[Dict[str, Any]]:
    """
    Unusual, quirky, or one-of-a-kind experiences that make a trip memorable.
    """
    results = []
    geo = _nominatim_geo(f"{city}, {state}")

    # Yelp: unusual categories
    unique_cats = ["Haunted Houses", "Wine Tours", "艺术馆", "Escape Games", "Farmers Market"]
    # Look for quirky Yelp results
    for cat in unique_cats:
        try:
            yelp = _scrape_yelp_category(city, state, cat, limit=3)
            for r in yelp:
                r["tier"] = "unique_idea"
                r["category"] = cat
                results.append(r)
        except Exception:
            pass

    if geo:
        # Scenic byways / drives from Wikipedia
        try:
            wiki_drive = _wiki_city_overview(city, state)
            for w in wiki_drive:
                if w.get("attraction_names"):
                    for name in w["attraction_names"][:3]:
                        results.append({
                            "name": f"Scenic: {name}",
                            "category": "Scenic Drive",
                            "description": "Must-do scenic route near " + city,
                            "source": "Local Guide",
                            "tier": "unique_idea",
                            "estimated_time": "1-2 hrs",
                        })
        except Exception:
            pass

    # Deduplicate
    seen = set()
    unique = []
    for item in results:
        key = item["name"].lower()[:60]
        if key not in seen:
            seen.add(key)
            unique.append(item)
    return unique[:limit]


def get_attractions(city: str, state: str, limit: int = 15) -> List[Dict[str, Any]]:
    """
    Master entry point — returns all attractions across all tiers.
    Prioritizes: tourist_favorites → local_gems → unique_ideas.
    """
    tourist = get_tourist_favorites(city, state, limit=8)
    gems = get_local_gems(city, state, limit=5)
    unique = get_unique_ideas(city, state, limit=4)

    # Wiki notable attractions from city page
    wiki = _wiki_city_overview(city, state)
    wiki_attractions = []
    if wiki and wiki[0].get("attraction_names"):
        wiki_attractions = _wiki_notable_attractions(wiki[0]["attraction_names"][:8])
        for w in wiki_attractions:
            w["tier"] = "tourist_favorite"
            tourist.append(w)

    # Deduplicate
    seen = set()
    unique_all = []
    for item in tourist + gems + unique:
        key = item["name"].lower()[:60]
        if key not in seen:
            seen.add(key)
            unique_all.append(item)

    return unique_all[:limit]


def get_restaurants(city: str, state: str, limit: int = 10) -> List[Dict[str, Any]]:
    """
    Dining recommendations across price tiers and categories:
    - Local favorites / diners
    - Farm-to-table / chef-driven
    - Breweries / wineries
    - Roadside gems (local burger/shake spots)
    """
    results = []
    cats = ["Restaurants", "Breakfast & Brunch", "BBQ", "Seafood", "Steakhouses", "Breweries"]

    for cat in cats:
        try:
            yelp = _scrape_yelp_category(city, state, cat, limit=4)
            for r in yelp:
                r["tier"] = "food"
                results.append(r)
        except Exception:
            pass

    # Deduplicate by name
    seen = set()
    unique = []
    for item in results:
        key = item["name"].lower()[:60]
        if key not in seen:
            seen.add(key)
            unique.append(item)
    return unique[:limit]
