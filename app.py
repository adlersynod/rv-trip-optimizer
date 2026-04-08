"""
app.py — RV Explorer + Trip Optimizer

Tabs:
  1. 📍 RV Explorer  (default / home) — destination-first planning
  2. 🗺️ Trip Planner — A→B route optimizer with connectivity stops
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
from explorer.attractions import get_attractions, get_restaurants
from explorer.rv_parks import get_rv_parks
from explorer.itinerary import build_itinerary, format_itinerary_markdown

# ─────────────────────────────────────────────
# Page Config
# ─────────────────────────────────────────────
st.set_page_config(
    page_title="RV Explorer",
    page_icon="📍",
    layout="wide",
    menu_items={"About": "Built for Adler Synod | Brinkley 4100 | Personal Use Only"},
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
        # Trip Planner state
        "route_results": None,
        "legs": None,
        "map": None,
        "start_geo": None,
        "end_geo": None,
        "trip_distance": 0.0,
        "trip_duration": 0.0,
        "legs_with_stops": None,
        # RV Explorer state
        "explorer_result": None,
        "explorer_destination": None,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

init_state()

# ─────────────────────────────────────────────
# Tab Layout
# ─────────────────────────────────────────────
st.title("📍 RV Explorer")
st.caption("Destination-first trip planning for the Brinkley 4100 · Full-time RV life")
st.divider()

tab_explorer, tab_planner = st.tabs(["📍 RV Explorer", "🗺️ Trip Planner"])

# ══════════════════════════════════════════════════════════════
# TAB 1: RV EXPLORER (HOME)
# ══════════════════════════════════════════════════════════════
with tab_explorer:
    st.subheader("Where do you want to go?")

    dest_col, stay_col = st.columns([3, 1])
    with dest_col:
        destination = st.text_input(
            "Destination",
            placeholder="Enter city, state (e.g. Asheville, NC)",
            help="Any US city or town",
        )
    with stay_col:
        nights = st.selectbox(
            "Nights staying",
            options=[1, 2, 3, 4, 5],
            index=1,
            help="How many nights will you stay?",
        )

    if st.button("🔍 Explore Destination", type="primary", use_container_width=True):
        if not destination:
            st.warning("Enter a destination city and state")
        else:
            parts = [p.strip() for p in destination.split(",")]
            city = parts[0]
            state = parts[1] if len(parts) > 1 else ""
            if not state:
                st.warning("Please enter as `City, State` (e.g. `Asheville, NC`)")
                st.stop()

            status = st.empty()
            status.info(f"🔍 Discovering {city}, {state}...")

            try:
                # Fetch data from all sources in parallel-ish
                attractions = get_attractions(city, state, limit=12)
                restaurants = get_restaurants(city, state, limit=8)
                rv_parks = get_rv_parks(city, state, limit=5)
                status.info("🗺️ Building your itinerary...")

                # Build itinerary
                num_weekdays = nights
                num_weekend = max(2, nights)
                itinerary = build_itinerary(
                    city=city,
                    state=state,
                    attractions=attractions,
                    restaurants=restaurants,
                    rv_parks=rv_parks,
                    num_weekdays=num_weekdays,
                    num_weekend_days=num_weekend,
                )

                st.session_state.explorer_result = itinerary
                st.session_state.explorer_destination = f"{city}, {state}"
                status.success(f"✅ Plan ready for {city}, {state}")
            except Exception as e:
                st.error(f"Error building plan: {e}")

    # ── Display Results ────────────────────────
    if st.session_state.explorer_result:
        result = st.session_state.explorer_result
        tiers = result.get("tiers", {})

        # Summary Bar
        st.divider()
        summary_cols = st.columns([2, 1, 1, 1])
        with summary_cols[0]:
            st.markdown(f"### 📍 {result['destination']}")
            st.caption(f"**Recommended:** {result['stay_duration']}")
        with summary_cols[1]:
            st.metric("Nights", nights)
        with summary_cols[2]:
            att_count = len([d for d in result["days"] for s in d["slots"] if "item" in s])
            st.metric("Activities", att_count)
        with summary_cols[3]:
            park_count = len(result.get("rv_parks", []))
            st.metric("RV Parks", park_count)

        # ── Three Tiers of Recommendations ───────────────────────
        st.divider()
        st.subheader("⭐ What to Do")

        tier_col1, tier_col2, tier_col3 = st.columns(3)

        # Column 1: Tourist Favorites
        with tier_col1:
            st.markdown("**🏛️ Tourist Favorites**")
            st.caption("Top-rated must-sees")
            for item in tiers.get("tourist_favorites", [])[:5]:
                url = item.get("yelp_url") or item.get("ta_url") or item.get("wiki_url") or item.get("nps_url") or ""
                rating_str = f" ★ {item['rating']}" if item.get("rating") else ""
                source_str = f" · {item.get('source','')}" if item.get('source') else ""
                time_str = f" · {item.get('estimated_time','')}" if item.get('estimated_time') else ""
                st.markdown(f"**{item['name']}**{rating_str}")
                if item.get("description"):
                    st.caption(item["description"][:90], help=item["description"])
                if url:
                    st.markdown(f"[🔗 View]({url})" if len(url) < 80 else f"[🔗 View]({url[:60]}...)", unsafe_allow_html=True)
                else:
                    st.caption(item.get("category",""))
                st.divider()

        # Column 2: Local Gems
        with tier_col2:
            st.markdown("**✨ Local Gems**")
            st.caption("Underrated spots locals love")
            for item in tiers.get("local_gems", [])[:5]:
                url = item.get("yelp_url") or item.get("reddit_url") or ""
                rating_str = f" ★ {item['rating']}" if item.get("rating") else ""
                source_str = f" · {item.get('source','')}" if item.get('source') else ""
                st.markdown(f"**{item['name']}**{rating_str}{source_str}")
                if item.get("description"):
                    st.caption(item["description"][:90], help=item["description"])
                if url:
                    st.markdown(f"[🔗 View]({url})" if len(url) < 80 else f"[🔗 View]({url[:60]}...)", unsafe_allow_html=True)
                else:
                    st.caption(item.get("category",""))
                st.divider()

        # Column 3: Unique Ideas
        with tier_col3:
            st.markdown("**🎯 Unique Ideas**")
            st.caption("One-of-a-kind experiences")
            for item in tiers.get("unique_ideas", [])[:5]:
                url = item.get("yelp_url") or ""
                source_str = f" · {item.get('source','')}" if item.get('source') else ""
                st.markdown(f"**{item['name']}**{source_str}")
                if item.get("description"):
                    st.caption(item["description"][:90], help=item["description"])
                if url:
                    st.markdown(f"[🔗 View]({url})" if len(url) < 80 else f"[🔗 View]({url[:60]}...)", unsafe_allow_html=True)
                else:
                    st.caption(item.get("category",""))
                st.divider()

        # ── Food & Drink ─────────────────────────────────────────
        food_items = tiers.get("food", [])
        if food_items:
            st.divider()
            st.subheader("🍽 Where to Eat")
            food_cols = st.columns([1, 1, 1])
            for i, item in enumerate(food_items[:6]):
                col = food_cols[i % 3]
                with col:
                    url = item.get("yelp_url") or ""
                    rating_str = f" ★ {item['rating']}" if item.get("rating") else ""
                    st.markdown(f"**{item['name']}**{rating_str}")
                    if item.get("category"):
                        st.caption(item["category"][:60])
                    if item.get("address"):
                        st.caption(item["address"][:60])
                    if url:
                        st.markdown(f"[🔗 Yelp]({url})" if len(url) < 80 else f"[🔗 Yelp]({url[:60]}...)", unsafe_allow_html=True)
                    st.divider()

        # ── Day-by-Day Itinerary ────────────────────────────────
        st.divider()
        st.subheader("🗓️ Your Stay Plan")

        for day in result["days"]:
            if not day["slots"]:
                continue
            with st.expander(f"**{day['label']}**", expanded=True):
                for slot in day["slots"]:
                    item = slot.get("item", {})
                    col_time, col_act = st.columns([1, 4])
                    with col_time:
                        st.markdown(f"**{slot['time']}**")
                        st.caption(slot["duration"])
                    with col_act:
                        # Show activity with any inline URL
                        st.markdown(slot["activity"].replace("|", " — "))
                        if item:
                            url = item.get("yelp_url") or item.get("ta_url") or item.get("wiki_url") or item.get("nps_url") or ""
                            if item.get("rating"):
                                st.caption(f"★ {item.get('rating')} · {item.get('source', '')}")
                            if url:
                                st.markdown(f"[🔗 More Info]({url})" if len(url) < 80 else f"[🔗 More Info]({url[:60]}...)", unsafe_allow_html=True)
                            if item.get("description") and item.get("source") != "Wikipedia":
                                st.caption(item["description"][:120])

        # ── RV Parks ─────────────────────────────────────────────
        if result.get("rv_parks"):
            st.divider()
            st.subheader("🏕️ RV Parks (Big Rig Friendly)")
            for park in result["rv_parks"]:
                with st.expander(f"**{park['name']}** — {park['category']}", expanded=False):
                    left, right = st.columns([2, 1])
                    with left:
                        st.markdown(f"**Price:** {park['price']}/night")
                        st.markdown(f"**Type:** {park['category']}")
                        st.markdown(park["big_rig"])
                        if park.get("rating"):
                            st.markdown(f"**Rating:** {park['rating']}")
                        if park.get("url"):
                            st.markdown(f"[📍 View Details & Book]({park['url']})")
                    with right:
                        st.markdown("### ✅")
                        st.caption("Checked-in")
                        st.markdown("### 📍")
                        st.caption(f"Stay: {nights} nights")

        # ── Tips ─────────────────────────────────────────────────
        if result.get("tips"):
            st.divider()
            with st.expander("💡 Travel Tips for This Destination"):
                for tip in result["tips"]:
                    st.markdown(f"- {tip}")

        # ── Also Worth a Look ────────────────────────────────────
        remaining = result.get("remaining_attractions", [])
        if remaining:
            with st.expander(f"📚 Also worth a look ({len(remaining)} more)"):
                for item in remaining:
                    url = item.get("yelp_url") or item.get("ta_url") or ""
                    tier_label = f"[{item.get('tier','').replace('_',' '').title()}]"
                    st.markdown(f"- **{item['name']}** — {tier_label} ({item.get('category', 'Attraction')})")
                    if url:
                        st.caption(f"[🔗 View]({url})" if len(url) < 80 else f"[🔗 View]({url[:60]}...)", unsafe_allow_html=True)
                    if item.get("description"):
                        st.caption(item["description"][:100])

        # ── Download Plan ────────────────────────────────────────
        plan_text = format_itinerary_markdown(result)
        st.download_button(
            "📥 Download Full Stay Plan (.md)",
            data=plan_text,
            file_name=f"rv_stay_plan_{result['destination'].replace(' ', '_')}.md",
            mime="text/markdown",
        )

    # ── Empty State ───────────────────────────
    else:
        st.info("👆 Enter a destination above to get a personalized stay plan.")
        col1, col2 = st.columns(2)
        with col1:
            st.markdown("""
            **How it works:**
            1. Enter any US city or destination
            2. We find top attractions, dining, and RV parks
            3. AI builds a day-by-day itinerary
            4. Respecting your weekday 2-3 hr work window
            """)
        with col2:
            st.markdown("""
            **Weeknight vs Weekend:**
            - 📅 Weekdays: 2-3 hrs max (remote work)
            - 🌅 Weekends: Full exploration days
            - 🏕️ RV parks filtered for 43ft big rigs
            """)

# ══════════════════════════════════════════════════════════════
# TAB 2: TRIP PLANNER (existing route optimizer)
# ══════════════════════════════════════════════════════════════
with tab_planner:
    st.subheader("Plan a Multi-Day Route")

    # ── Sidebar ──────────────────────────────
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
        )

        fetch_details = st.checkbox(
            "Deep-fetch stop details",
            value=False,
        )

        st.divider()
        st.header("Theo's Preferences 🐾")
        pet_friendly_required = st.checkbox("Pet-friendly required (Theo)", value=True)
        min_quality = st.checkbox("Nice parks only (≥3.5★ + ≥10 reviews)", value=True)
        diesel_only = st.checkbox("Diesel stops only", value=True)

        st.divider()
        st.caption("Built for Adler Synod · 2026")

    # ── Main Input ───────────────────────────
    col1, col2, col3 = st.columns([3, 1, 3])
    with col1:
        start_addr = st.text_input(
            "Starting Point",
            value=DEFAULT_START,
            placeholder="Enter city or address",
        )
    with col3:
        end_addr = st.text_input(
            "Destination",
            value=DEFAULT_END,
            placeholder="Enter city or address",
        )

    plan_col, status_col = st.columns([1, 3])
    with plan_col:
        plan_btn = st.button("🗺️ Plan Route", type="primary", use_container_width=True)
    with status_col:
        status_placeholder = st.empty()

    # ── Routing Pipeline ─────────────────────
    if plan_btn and start_addr and end_addr:
        status_placeholder.info("🔄 Geocoding addresses...")

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
        segmenter = LegSegmenter(max_leg_miles=float(max_leg))

        route_distances = [0.0]
        for i in range(1, len(primary["geometry"])):
            d = distance_haversine(
                primary["geometry"][i - 1][0], primary["geometry"][i - 1][1],
                primary["geometry"][i][0], primary["geometry"][i][1],
            )
            route_distances.append(route_distances[-1] + d)

        legs = segmenter.segment_route(primary["geometry"], route_distances)
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

    # ── Results ──────────────────────────────
    if st.session_state.route_results:
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
                st.metric(
                    "Route",
                    f"{st.session_state.start_geo.get('display_name', start_addr)[:20]}… → "
                    f"{st.session_state.end_geo.get('display_name', end_addr)[:20]}…",
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
                    st.markdown(f"`{leg.route_geometry[0]}` → `{leg.route_geometry[-1]}`")
                    if report:
                        badge = scorer.format_full_badge(report)
                        left, right = st.columns([2, 1])
                        with left:
                            st.markdown(f"**🏕️ {report.park.name}**")
                            st.markdown(f"{report.park.city}, {report.park.state}")
                            if report.park.rating:
                                st.markdown(f"★ {report.park.rating:.1f} ({report.park.review_count} reviews)")
                            if report.park.price_low:
                                st.markdown(f"💰 ${report.park.price_low}/night")
                            pet_icon = "🐾 Theo OK" if report.pet_friendly else "🚫 No Pets"
                            diesel_icon = "⛽ Diesel" if report.diesel_nearby else ""
                            badges = [b for b in [pet_icon, diesel_icon] if b]
                            if badges:
                                st.markdown(" | ".join(badges))
                            if report.park.url:
                                st.markdown(f"[View on Campendium]({report.park.url})")
                        with right:
                            st.markdown("**Connectivity**")
                            st.markdown(f"Starlink: {'✅ Verified' if report.starlink_verified else '❌ Not reported'}")
                            st.markdown(f"{report.primary_carrier}")
                            bars_str = "★" * report.cellular_bars_est + "☆" * (5 - report.cellular_bars_est)
                            st.markdown(f"Signal: {bars_str}")
                            st.markdown(f"**Overall: {report.total_score}/10**")
                            if report.notes:
                                for note in report.notes:
                                    st.caption(f"• {note}")
                    else:
                        st.info("No suitable stops found automatically. Manual research recommended.")

        # Map
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

    # Empty state
    else:
        st.info("👆 Enter a start and destination above to plan your route.")
        st.markdown("""
        **What this does:**
        1. **Geocodes** your addresses via OpenStreetMap
        2. **Generates 3 RV-safe route options** via OSRM
        3. **Segments** the trip into ≤300-mile legs
        4. **Finds and scores overnight stops** on Starlink + Cellular connectivity
        5. **Renders an interactive map** you can download and take offline
        """)
