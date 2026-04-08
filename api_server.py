"""
api_server.py — Flask API for RV Trip Optimizer
Exposes /api/explore endpoint that calls the explorer data functions.
CORS enabled for all origins.
"""

from flask import Flask, request, jsonify
from flask_cors import CORS
import sys
import os

# Ensure explorer module is importable
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from explorer.attractions import get_attractions, get_restaurants
from explorer.rv_parks import get_rv_parks
from explorer.itinerary import build_itinerary

app = Flask(__name__)
CORS(app)

# ─── Health ────────────────────────────────────────────────────────
@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "service": "rv-trip-optimizer-api"})


# ─── Explore ───────────────────────────────────────────────────────
@app.route("/api/explore", methods=["GET"])
def explore():
    destination = request.args.get("destination", "").strip()
    nights = int(request.args.get("nights", "2"))

    if not destination:
        return jsonify({"error": "destination is required"}), 400

    # Parse city, state
    parts = [p.strip() for p in destination.split(",")]
    if len(parts) >= 2:
        city = parts[0]
        state = parts[-1]  # last segment = state
    else:
        # Try to treat as single city name
        city = parts[0]
        state = "Unknown"

    try:
        # Fetch data from all sources concurrently-ish
        attractions = get_attractions(city, state, limit=15)
        restaurants = get_restaurants(city, state, limit=10)
        rv_parks = get_rv_parks(city, state, limit=5)

        # Build itinerary
        num_weekdays = min(nights, 3)
        num_weekend_days = max(0, nights - num_weekdays)

        itinerary = build_itinerary(
            city=city,
            state=state,
            attractions=attractions,
            restaurants=restaurants,
            rv_parks=rv_parks,
            num_weekdays=num_weekdays,
            num_weekend_days=num_weekend_days,
        )

        return jsonify({
            "destination": f"{city}, {state}",
            "attractions": attractions,
            "restaurants": restaurants,
            "rv_parks": rv_parks,
            "itinerary": itinerary,
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=3000, debug=False)
