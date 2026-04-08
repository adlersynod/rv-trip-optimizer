"""
app.py — RV Trip Optimizer Streamlit UI

Run: streamlit run app.py
Opens at: http://localhost:8501

Personal use for Adler Synod.
Route: Bella Vista, AR → Austin, TX (or custom)
Constraints: ≤300 mi/leg, Starlink + Cellular scoring
"""

import streamlit as st
import sys
import os
from typing import List, Tuple, Optional
import math

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from router.geocoder import geocode_address, distance_haversine
from router.route_engine import RouteEngine
from router.leg_segmenter import LegSegmenter
from stops.campendium_scraper import CampendiumScraper
from stops.connectivity_scorer import ConnectivityScorer
from map_builder.folium_mapper import FoliumMapper

# ─────────────────────────────────────────────
# Page Config
# ─────────────────────────────────────────────
st.set_page_config(
    page_title="RV Trip Optimizer",
    page_icon="🚐",
    layout="wide",
    menu_items={"About": "Built for Adler Synod | Personal Use Only"},
)

# ─────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────
DEFAULT_START = "Bella Vista, AR"
DEFAULT_END = "Austin, TX"
CACHE_DIR = os.path.join(os.path.dirname(__file__), "cache")
os.makedirs(CACHE_DIR, exist_ok=True)

# ─────────────────────────────────────────────
# Session State
# ─────────────────────────────────────────────
def init_state():
    defaults = {
        "route_results": None,
        "legs": None,
        "map": None,
        "start_geo": None,
        "end_geo": None,
        "trip_distance": 0.0,
        "trip_duration": 0.0,
        "legs_with_stops": None,  # List of (leg, stop_report) tuples
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

init_state()


# ─────────────────────────────────────────────
# Header
# ─────────────────────────────────────────────
st.title("🚐 RV Trip Optimizer")
st.caption("Safe routes for the Brinkley 4100 · Connectivity-scored overnight stops")
st.divider()


# ─────────────────────────────────────────────
# Sidebar
# ─────────────────────────────────────────────
with st.sidebar:
    st.header("Vehicle Profile")
    st.markdown("**Brinkley 4100** (43' Fifth Wheel)")
    st.markdown("• 13' 6\" height · 8.5' width · ~45K lbs")
    st.markdown("• Ram 3500 Dually tow vehicle")

    st.divider()
    st.header("Trip Preferences")

    max_leg = st.slider(
        "Max leg distance",
        min_value=150,
        max_value=400,
        value=300,
        step=25,
        help="Maximum driving distance per day",
    )

    connectivity_priority = st.selectbox(
        "Stop priority",
        ["Balanced", "Starlink Priority", "Cellular Priority"],
        index=0,
    )

    toll_threshold = st.slider(
        "Max free-route detour (vs toll)",
        min_value=10,
        max_value=50,
        value=25,
        step=5,
        help="If a free route is more than this many miles longer than the toll route, take the toll. Otherwise prefer free.",
    )

    fetch_details = st.checkbox(
        "Deep-fetch stop details",
        value=False,
        help="Scrape campground pages for Starlink/cellular notes (slower)",
    )

    st.divider()
    st.header("Theo's Preferences 🐾")
    pet_friendly_required = st.checkbox(
        "Pet-friendly required (Theo)",
        value=True,
        help="Only show parks that allow pets. Theo is always welcome.",
    )
    min_quality = st.checkbox(
        "Nice parks only (≥3.5★ + ≥10 reviews)",
        value=True,
        help="Filter out lower-rated or unestablished parks.",
    )
    diesel_only = st.checkbox(
        "Diesel stops only",
        value=True,
        help="Show only stops with diesel fuel within 5 miles.",
    )

    st.divider()
    st.caption("Built for Adler Synod · 2026")


# ─────────────────────────────────────────────
# Main Input Section
# ─────────────────────────────────────────────
col1, col2, col3 = st.columns([3, 1, 3])

with col1:
    start_addr = st.text_input(
        "Starting Point",
        value=DEFAULT_START,
        placeholder="Enter city or address",
        help="Where are you leaving from?",
    )

with col3:
    end_addr = st.text_input(
        "Destination",
        value=DEFAULT_END,
        placeholder="Enter city or address",
        help="Where are you going?",
    )

# ─────────────────────────────────────────────
# Route Button
# ─────────────────────────────────────────────
plan_col, status_col = st.columns([1, 3])

with plan_col:
    plan_btn = st.button("🗺️ Plan Route", type="primary", use_container_width=True)

with status_col:
    status_placeholder = st.empty()


# ─────────────────────────────────────────────
# Routing Pipeline
# ─────────────────────────────────────────────
if plan_btn and start_addr and end_addr:
    status_placeholder.info("🔄 Geocoding addresses...")

    # Step 1: Geocode
    start_geo = geocode_address(start_addr)
    end_geo = geocode_address(end_addr)

    if not start_geo:
        st.error(f"❌ Could not find start address: `{start_addr}`")
        st.stop()
    if not end_geo:
        st.error(f"❌ Could not find destination: `{end_addr}`")
        st.stop()

    st.session_state.start_geo = start_geo
    st.session_state.end_geo = end_geo

    status_placeholder.info("🔄 Computing RV-safe routes...")

    # Step 2: Get routes
    engine = RouteEngine()
    routes = engine.get_safe_routes(
        (start_geo["lat"], start_geo["lon"]),
        (end_geo["lat"], end_geo["lon"]),
        toll_threshold=float(toll_threshold),
    )

    if not routes:
        st.error("❌ No routes found. Check addresses and try again.")
        st.stop()

    primary = routes[0]
    st.session_state.trip_distance = primary["distance_mi"]
    st.session_state.trip_duration = primary["duration_h"]
    st.session_state.route_results = routes

    status_placeholder.info("🔄 Finding overnight stops...")

    # Step 3: Segment into legs
    segmenter = LegSegmenter(max_leg_miles=float(max_leg))

    # Compute cumulative distance along primary route
    route_distances = [0.0]
    for i in range(1, len(primary["geometry"])):
        d = distance_haversine(
            primary["geometry"][i - 1][0], primary["geometry"][i - 1][1],
            primary["geometry"][i][0], primary["geometry"][i][1],
        )
        route_distances.append(route_distances[-1] + d)

    legs = segmenter.segment_route(primary["geometry"], route_distances)

    # Step 4: Find stops near each leg midpoint
    scraper = CampendiumScraper(cache_dir=CACHE_DIR)
    scorer = ConnectivityScorer(cache_dir=CACHE_DIR)
    legs_with_stops = []

    for leg in legs:
        mid_idx = max(1, len(leg.route_geometry) // 2)
        mid_lat = leg.route_geometry[mid_idx][0]
        mid_lon = leg.route_geometry[mid_idx][1]

        parks = scraper.search_near(mid_lat, mid_lon, radius_miles=50.0, limit=5)
        scored_reports = scorer.score_batch(
            parks,
            fetch_details=fetch_details,
            require_pet_friendly=pet_friendly_required,
            require_min_quality=min_quality,
        ) if parks else []
        best_report = scored_reports[0] if scored_reports else None

        leg.route_warnings = primary.get("warnings", [])
        legs_with_stops.append((leg, best_report))

    st.session_state.legs = legs
    st.session_state.legs_with_stops = legs_with_stops

    # Step 5: Build map
    status_placeholder.info("🔄 Rendering interactive map...")

    mapper = FoliumMapper(
        start=(start_geo["lat"], start_geo["lon"]),
        end=(end_geo["lat"], end_geo["lon"]),
    )

    for route in routes:
        mapper.add_route(
            geometry=route["geometry"],
            route_name=route["name"],
            distance_mi=route["distance_mi"],
            duration_h=route["duration_h"],
            score=route["score"],
            warnings=route["warnings"],
        )

    for leg, report in legs_with_stops:
        if report and report.park.lat and report.park.lon:
            badge = scorer.format_badge(report)
            mapper.add_stop(
                name=report.park.name,
                lat=report.park.lat,
                lon=report.park.lon,
                connectivity_badge=badge,
                price=report.park.price_low,
                rating=report.park.rating,
                url=report.park.url,
                stop_type="RV Park",
                pet_friendly=report.pet_friendly,
                diesel_nearby=report.diesel_nearby,
            )

    map_output_path = os.path.join(CACHE_DIR, "trip_map.html")
    mapper.build(output_path=map_output_path)
    st.session_state.map = map_output_path

    status_placeholder.success("✅ Trip planned!")


# ─────────────────────────────────────────────
# Results Section
# ─────────────────────────────────────────────
if st.session_state.route_results:

    # Trip Summary
    st.divider()
    st.subheader("📋 Trip Summary")

    summary_cols = st.columns(4)
    with summary_cols[0]:
        st.metric("Total Distance", f"{st.session_state.trip_distance:.0f} mi")
    with summary_cols[1]:
        st.metric("Est. Drive Time", f"{st.session_state.trip_duration:.1f} hrs")
    with summary_cols[2]:
        leg_count = len(st.session_state.legs) if st.session_state.legs else 0
        st.metric("Travel Days", f"{leg_count} legs")
    with summary_cols[3]:
        if st.session_state.start_geo and st.session_state.end_geo:
            start_name = st.session_state.start_geo.get("display_name", start_addr)
            end_name = st.session_state.end_geo.get("display_name", end_addr)
            st.metric(
                "Route",
                f"{start_name[:20]}… → {end_name[:20]}…",
                help=f"Full: {start_name} → {end_name}",
            )

    # Route Options
    st.divider()
    st.subheader("🗺️ Route Options")

    route_cols = st.columns(len(st.session_state.route_results))
    route_colors = {"Primary": "🟦", "Scenic": "🟩", "Alternate": "🟧"}

    for i, route in enumerate(st.session_state.route_results):
        with route_cols[i]:
            icon = route_colors.get(route["name"], "⬜")
            toll_badge = "💰 TOLL" if route.get("is_toll") else "🆓 FREE"
            st.markdown(f"### {icon} {route['name']}  {toll_badge}")
            st.markdown(f"**Distance:** {route['distance_mi']} mi")
            st.markdown(f"**Drive Time:** {route['duration_h']:.1f} hrs")
            st.markdown(f"**RV Safety Score:** `{route['score']}/100`")
            # Smart toll note
            if route.get("toll_note"):
                st.info(route["toll_note"])
            if route.get("warnings"):
                for w in route["warnings"]:
                    st.warning(f"⚠️ {w}")
            elif not route.get("toll_note"):
                st.success("No major route warnings")

    # Leg Breakdown
    st.divider()
    st.subheader("🚐 Leg Breakdown (≤300 mi each)")

    if st.session_state.legs_with_stops:
        for leg, report in st.session_state.legs_with_stops:
            over_limit = leg.distance_mi > max_leg
            status_icon = "🚨 OVER LIMIT" if over_limit else "✅ Safe"
            with st.expander(
                f"**Leg {leg.leg_index + 1}** — {leg.distance_mi} mi | {status_icon}",
                expanded=True,
            ):
                st.markdown(
                    f"`{leg.route_geometry[0]}` → `{leg.route_geometry[-1]}`"
                )

                if report:
                    badge = scorer.format_full_badge(report)
                    left, right = st.columns([2, 1])
                    with left:
                        st.markdown(f"**🏕️ {report.park.name}**")
                        st.markdown(f"{report.park.city}, {report.park.state}")
                        if report.park.rating:
                            st.markdown(
                                f"★ {report.park.rating:.1f} "
                                f"({report.park.review_count} reviews)"
                            )
                        if report.park.price_low:
                            st.markdown(
                                f"💰 ${report.park.price_low}"
                                f"{'-' + str(report.park.price_high) if report.park.price_high != report.park.price_low else ''}/night"
                            )
                        # Pet + Diesel badges
                        pet_icon = "🐾 Theo OK" if report.pet_friendly else "🚫 No Pets"
                        diesel_icon = "⛽ Diesel" if report.diesel_nearby else ""
                        badges = [b for b in [pet_icon, diesel_icon] if b]
                        if badges:
                            st.markdown(" | ".join(badges))
                        if report.park.url:
                            st.markdown(f"[View on Campendium]({report.park.url})")
                    with right:
                        st.markdown("**Connectivity**")
                        st.markdown(
                            f"Starlink: {'✅ Verified' if report.starlink_verified else '❌ Not reported'}"
                        )
                        st.markdown(f"{report.primary_carrier}")
                        bars_str = "★" * report.cellular_bars_est + "☆" * (5 - report.cellular_bars_est)
                        st.markdown(f"Signal: {bars_str}")
                        st.markdown(f"**Overall: {report.total_score}/10**")
                        if report.notes:
                            for note in report.notes:
                                st.caption(f"• {note}")
                else:
                    st.info(
                        "No suitable stops found automatically in this area. "
                        "Manual research recommended for this leg."
                    )

    # Interactive Map
    st.divider()
    st.subheader("🗺️ Interactive Route Map")

    if st.session_state.map and os.path.exists(st.session_state.map):
        with open(st.session_state.map, "r", encoding="utf-8") as f:
            map_html = f.read()
        st.components.v1.html(map_html, height=600, scrolling=True)

        with open(st.session_state.map, "rb") as f:
            st.download_button(
                "📥 Download Map (HTML)",
                data=f,
                file_name="rv_trip_map.html",
                mime="text/html",
            )

# ─────────────────────────────────────────────
# Empty State
# ─────────────────────────────────────────────
else:
    st.info(
        "👆 Enter a start and destination, then click **Plan Route** to get started."
    )
    st.markdown("""
    **What this does:**

    1. **Geocodes** your addresses via OpenStreetMap (free, no API key)
    2. **Generates 3 RV-safe route options** via OSRM (open-source routing)
    3. **Segments** the trip into ≤300-mile legs
    4. **Finds and scores overnight stops** on Starlink + Cellular connectivity
    5. **Renders an interactive map** you can download and take offline

    *All free-tier data sources. No API keys needed.*
    """)
