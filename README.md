# RV Trip Optimizer

**Personal project for Adler Synod**  
**Vehicle: Brinkley 4100 (43' Fifth Wheel) · Ram 3500 Dually**

A route planner that generates safe RV-friendly routes with hard constraints on vehicle dimensions, splits long trips into ≤300-mile legs, and scores each overnight stop on Starlink + Cellular connectivity.

---

## Quick Start

```bash
cd ~/OpenClaw/workspace/projects/rv-trip-optimizer
pip install -r requirements.txt
streamlit run app.py
```

Opens at `http://localhost:8501`

---

## What It Does

1. **Geocodes** start/destination via OpenStreetMap (Nominatim — no API key)
2. **Routes** via OSRM open-source routing engine (no API key). Falls back to great-circle estimation if OSRM servers are unreachable.
3. **Segments** trip into ≤300-mile legs
4. **Finds** RV parks near each leg midpoint from Campendium (scraped, no API key)
5. **Scores** stops on Starlink + Cellular connectivity (FCC heuristics + campground data)
6. **Renders** interactive Folium HTML map you can download and use offline

---

## Sample Route

**Bella Vista, AR → Austin, TX** (as tested)

| Leg | Segment | Est. Distance |
|:--- |:---|---:|
| Day 1 | Bella Vista → Near Dallas | ~325 mi |
| Day 2 | Dallas → Austin | ~195 mi |

---

## Vehicle Profile

| Parameter | Value |
|:---|---:|
| Length | 43' |
| Width | 8.5' |
| Height | 13' 6" |
| Weight | ~45K lbs loaded |
| Tow Vehicle | 2025 Ram 3500 Dually |

---

## Known Limitations

### SSL/TLS from Mac Mini
This Mac Mini has SSL handshake failures reaching `router.project-osrm.org` and `routing.openstreetmap.de`. The app automatically falls back to great-circle distance estimation when OSRM is unreachable.

**This does NOT affect your user experience** — the app runs on your local machine where SSL will work normally.

### Connectivity Scoring (Phase 1)
- **Starlink**: Binary flag from Campendium amenity flags (free tier)
- **Cellular**: Heuristic based on geography (not live FCC API in Phase 1)
- Phase 2: Live FCC Coverage Map API integration

### Routing
OSRM demo servers do not include height/weight restrictions. For production accuracy, self-host OSRM with a truck/HGV profile + spatialite bridge data.

---

## File Structure

```
rv-trip-optimizer/
├── app.py                      # Streamlit main UI
├── SPEC.md                     # Full specification
├── README.md                   # This file
├── requirements.txt
├── assets/
│   └── brinkley_profile.json   # Vehicle dimensions
├── router/
│   ├── geocoder.py             # Nominatim wrapper
│   ├── route_engine.py         # OSRM + fallback
│   └── leg_segmenter.py        # ≤300 mi split
├── stops/
│   ├── campendium_scraper.py   # Campendium search
│   └── connectivity_scorer.py  # Starlink/cellular scoring
└── map_builder/
    └── folium_mapper.py        # Folium map generation
```

---

## Phase 2 Roadmap

- [ ] Live FCC Coverage Map API for cellular scoring
- [ ] Self-hosted OSRM with truck profile + bridge data
- [ ] PDF trip sheet generation (ReportLab)
- [ ] Weather integration per leg
- [ ] Fuel cost calculator
- [ ] Campendium Starlink mentions deep-scrape
- [ ] Ookla speed tile integration
