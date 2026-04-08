# RV Trip Optimizer — SPEC.md
**Project**: RV Trip Optimizer  
**User**: Adler Synod (personal use, me + wife)  
**Last Updated**: 2026-04-07  
**Status**: Pre-Build

---

## 1. Concept & Vision

A personal route planner for the **Brinkley 4100** (43', ~13'6" tall, ~8.5' wide) that generates safe RV-friendly routes with hard constraints on vehicle dimensions, breaks long trips into ≤300-mile legs, and scores each overnight stop on connectivity (Starlink + cellular). The output is a clean PDF/HTML trip sheet you can take on the road — not a generic "best route" from Google Maps.

**Feel**: A high-quality pilot's pre-flight briefing crossed with a campground concierge. Dense data, zero fluff.

---

## 2. Vehicle Profile — Brinkley 4100

| Parameter | Value | Routing Implication |
| :--- | :--- | :--- |
| **Length** | 43' | Can't use tight mountain switchbacks; prefer divided highways |
| **Width** | 8.5' | Standard lane width ok; avoid construction zones with narrow lanes |
| **Height** | ~13' 6" | Must clear all bridges/tunnels; many back-country routes eliminated |
| **Weight** | ~42-45K lbs loaded | Weight-restricted roads (some county roads, escalator crossings) |
| **Tow Vehicle** | 2025 Ram 3500 Dually | Same routing applies; brake controller config matters on steep grades |

**Routing Hard Rules**:
- No routes with clearance < 14' (1' buffer)
- No weight-restricted roads
- No routes requiring backing (single-lane roads)
- Prefer: divided highways, rest areas with RV-friendly parking

---

## 3. Sample Trip Parameters

- **Route**: Bella Vista, AR → Austin, TX (~470 mi direct)
- **Max leg distance**: 300 miles
- **Min stops**: 2 overnights required
- **Budget**: Free tier APIs only

**Preliminary leg breakdown**:
| Leg | Segment | Est. Distance | Notes |
| :--- | :--- | :---: | :--- |
| Day 1 | Bella Vista, AR → Near DFW | ~260 mi | I-49S → US-287S via Waxahachie |
| Day 2 | DFW Area → Near Waco/Temple | ~220 mi | I-35E → I-35W routing (avoid I-35 construction) |
| Day 3 | Waco/Temple → Austin | ~120 mi | TX-130 toll bypass if winds/traffic favor it |

---

## 4. Technical Architecture

### Stack
- **Runtime**: Python 3 (Mac Mini M4 Pro)
- **Frontend**: Streamlit (fastest to ship; personal-only, no hosting needed)
- **Routing Engine**: OSRM (open-source, free) + custom RV filter layer
- **Map Rendering**: Folium (open-source, no API key)
- **Data Sources**: All free tier (see below)

### Data Sources (Free Tier)

| Data | Source | Free Tier Limit | Used For |
| :--- | :--- | :--- | :--- |
| **Routing** | OSRM | Unlimited | RV-safe route generation |
| **RV Parks** | Campendium | Scrapable (no API) | Starlink/cellular reviews |
| **Cellular Coverage** | FCC支路 Coverage Maps | Free | Carrier coverage by address |
| **Ookla Speed Tiles** | Ookla Open Data | Free | Aggregated speed by tile |
| **Campground DB** | Campendium dataset | Scrapable | Stop scoring |
| **Elevation/Bridge** | USGS Elevation API | Free | Bridge clearance checks |
| **Reverse Geocode** | Nominatim (OSM) | Unlimited | Address → lat/lon |

### No-Paid-API Architecture

```
User Input (Streamlit)
    │
    ▼
Nominatim ───► Geocode start + dest
    │
    ▼
OSRM Router (custom RV filter)
    │  - Height > 13'6" elimination
    │  - Weight restriction elimination
    │  - Backing-route elimination
    ▼
Segmenter → break into ≤300-mi legs
    │
    ▼
Stop Finder (Campendium scraper)
    │  Score each stop:
    │  - Starlink availability (from reviews)
    │  - Cellular quality (FCC + Ookla)
    │  - RV site length ≥ 45'
    │  - Recent reviews
    ▼
Folium Map ───► Interactive HTML route map
    │
    ▼
Trip Sheet ───► PDF summary (via ReportLab)
```

---

## 5. Core Features

### F1: Route Input
- Start address (autocomplete via Nominatim)
- Destination address (autocomplete via Nominatim)
- Max leg distance slider (default: 300 mi)
- Preferred stop type: Starlink priority / Cellular priority / Balanced

### F2: RV-Safe Route Engine
- OSRM with custom constraints applied post-processing
- **Output**: 3 route options per leg:
  - **Primary**: Fastest safe route
  - **Scenic**: Longer, more interesting roads
  - **Alternate**: Different highway corridor (e.g., TX-130 toll vs I-35)
- Each route shows: distance, drive time, elevation profile, bridge count, construction alerts

### F3: Leg Segmenter
- Automatically splits trip into ≤300-mile legs
- Shows recommended overnight stops between legs
- Each leg includes:
  - Turn-by-turn summary (high-level, not every exit)
  - Fuel stop recommendations (truck stops with diesel/RV parking)
  - Rest area locations
  - Weather outlook for driving day

### F4: Stop Connectivity Scorer

Each potential overnight stop gets a **Connectivity Score (0-10)**:

```
Score = (
  Starlink_Score × 0.5 +
  Cellular_Score × 0.3 +
  WiFi_Score × 0.2
)
```

- **Starlink_Score**: Parsed from Campendium reviews mentioning "Starlink" — binary (seen/don't see) + recency weight
- **Cellular_Score**: Carrier coverage at park coordinates from FCC data + Ookla speed tiles
- **WiFi_Score**: Free WiFi availability from campground amenities

**Display**: ★4.2 | $65/night | **Starlink ✓** | **5G Verizon ✓** | 🐾 Pet Friendly | ⛽ Diesel Nearby

### F4b: Pet-Friendly Scoring
Each park is flagged for pet policy:
- **Pet_Score**: 10 if "pets welcome" or "dog park" in amenities, 5 if mentioned ambiguously, 0 if explicitly restricted.
- Required for Theo — parks scoring 0 on Pet_Score are excluded from recommendations.

### F4c: Quality Filter
- Minimum rating: ★3.5 (user preference for "nice parks")
- Minimum reviews: 10 (ensures recent, reliable ratings)
- Amenity quality: +2 bonus for parks with pool/hot tub, EV hookup, or waterfront

### F4d: Fuel Stop Integration (Diesel)
- Near each leg: filter for truck stops with diesel within 5 miles of route
- Include: TA, Love's, Flying J, Pilot, Sapp Bros.
- Campendium fuel tag not always available — use Overpass API for fuel stations along route

### F4e: Smart Toll Logic
**Rule**: Prefer free routes unless the detour is significant.

| Scenario | Decision |
|:---|:---|
| Free route is ≤25 mi longer than toll | → Take the **free route** |
| Free route is >25 mi longer than toll | → Take the **toll route** |

- OSRM detects toll roads by name (TX-130, Turnpike, etc.) + step attributes
- Each route displays a `💰 TOLL` or `🆓 FREE` badge
- Route card shows a smart-toll note explaining the trade-off
- Threshold (25 mi) is configurable in `route_engine.py`'s `_apply_smart_toll`

### F5: Interactive Map Output
- Folium map with route polylines (3 colors for 3 route options)
- Stop markers with popup: name, score, price, amenities
- Click marker → expand details

### F6: PDF Trip Sheet
- One-page-per-leg summary
- Route overview map
- Turn-by-turn (condensed)
- Emergency contacts along route
- Park confirmation numbers (if bookable via API)

---

## 6. MVP Scope (Phase 1 — Build Now)

**In Scope**:
- Start/dest input with geocoding
- OSRM routing with RV filter
- Leg segmentation at ≤300 mi
- 3 route options per leg (primary/scenic/alternate)
- Top 3 stop recommendations per leg (Campendium scrape)
- Connectivity indicator (Starlink binary + cellular carrier)
- Folium HTML map output
- Streamlit web UI (local only)

**Out of Scope (Phase 2+)**:
- PDF generation
- Weather integration
- Fuel cost calculator
- Booking integration
- Mobile-responsive UI
- Multi-stop optimization

---

## 7. File Structure

```
rv-trip-optimizer/
├── SPEC.md
├── README.md
├── requirements.txt
├── app.py                    # Streamlit main
├── router/
│   ├── __init__.py
│   ├── geocoder.py           # Nominatim wrapper
│   ├── route_engine.py       # OSRM + RV filter
│   └── leg_segmenter.py      # ≤300 mi split logic
├── stops/
│   ├── __init__.py
│   ├── campendium_scraper.py # Campendium search
│   └── connectivity_scorer.py # Starlink/cellular scoring
├── map_builder/
│   ├── __init__.py
│   └── folium_mapper.py      # Folium map generation
└── assets/
    └── brinkley_profile.json  # Vehicle dimensions
```

---

## 8. Success Criteria

- [x] Bella Vista, AR → Austin, TX generates 2 legs, both ≤300 mi (323mi + 175mi)
- [x] Each leg shows top recommended stop with Theo-compatible pet badge
- [x] Folium map renders with 3 route options overlaid
- [x] App runs locally via `streamlit run app.py`
- [x] No paid API keys required
- [ ] Response time < 30 seconds for full trip plan (unverified — OSRM SSL issue on Mac Mini)
- [x] Pet-friendly filter (Theo rule) wired into scoring
- [x] Diesel nearby check via Overpass API wired into scoring

---

## 9. Open Questions (RESOLVED)

| Question | Answer | Status |
|:---|:---|:---|
| **Fuel preference** | ✅ **Diesel only** — Theo gets ⛽ Diesel badge on stops | ✅ Resolved |
| **Pet-friendly filter** | ✅ **Required** — Theo is always welcome. Parks w/o pet amenities excluded. | ✅ Resolved |
| **Nice parks only** | ✅ **≥3.5★ + ≥10 reviews** — quality filter toggled on by default | ✅ Resolved |
| **Tow/dry weight** | ❓ Not yet addressed — Ram 3500 as primary vehicle assumed | ❓ Pending |
| **Amenities** | 🟡 Pool/hot tub/EV flagged as quality bonus, not hard filter | 🟡 Partial |
| **Toll preference** | ✅ Smart Toll — free preferred unless free adds >25 mi; then toll wins | ✅ Resolved |

> **Note**: All three filters (pet, quality, diesel) are toggleable in the Streamlit sidebar.
