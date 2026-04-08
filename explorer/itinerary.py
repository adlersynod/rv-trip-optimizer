"""
itinerary.py — AI-powered itinerary builder for RV Explorer

Builds a loose day-by-day plan from attractions, dining, and RV parks.
Respects:
  - Weekday: 2-3 hrs max (remote work constraint)
  - Weekend: Full day available
  - RV travel: Driving between stops factored in
"""

from typing import List, Dict, Any, Optional
import math


# ─────────────────────────────────────────────
# Time Constants
# ─────────────────────────────────────────────
WEEKDAY_MORNING_MIN = 0.5   # hrs — quick walk, coffee, farmer's market
WEEKDAY_EVENING_MAX = 2.5   # hrs — main attraction or dinner outing
SATURDAY_DAY = 7.0          # hrs — full day Saturday
SUNDAY_HALF = 4.0           # hrs — half day Sunday
TRANSIT_OVERHEAD = 0.5      # hrs — travel/parking/setup between stops


def _estimate_activities(attractions: List[Dict[str, Any]]) -> float:
    """Estimate total hours needed for all attractions."""
    total = 0.0
    for a in attractions:
        time_str = a.get("estimated_time", "2 hrs")
        try:
            hrs = float(time_str.replace(" hrs", "").replace(" hr", "").strip())
        except Exception:
            hrs = 2.0
        total += hrs
    return total


def _parse_price(price_str: str) -> float:
    """Convert price string like '$45/night' to float."""
    if not price_str or price_str in ("N/A", "Free", "Unknown"):
        return 0.0
    try:
        nums = [float(s) for s in price_str if s.isdigit() or s == "."]
        return float("".join(str(n) for n in nums)) if nums else 0.0
    except Exception:
        return 0.0


def _categorize_items(attractions: List[Dict[str, Any]], restaurants: List[Dict[str, Any]]) -> Dict[str, List]:
    """Group attractions into Morning / Afternoon / Evening buckets."""
    categories = {"nature": [], "food": [], "culture": [], "relax": []}
    for a in attractions:
        cat = a.get("category", "").lower()
        desc = a.get("description", "").lower()
        if any(w in cat or w in desc for w in ["park", "trail", "lake", "nature", "hike", "nps", "national", "beach"]):
            categories["nature"].append(a)
        elif any(w in cat or w in desc for w in ["museum", "historic", "culture", "art", "downtown", "old", "site"]):
            categories["culture"].append(a)
        elif any(w in cat or w in desc for w in ["restaurant", "dining", "eat", "food", "brew"]):
            categories["food"].append(a)
        else:
            categories["relax"].append(a)

    for r in restaurants:
        categories["food"].append(r)

    return categories


def build_itinerary(
    city: str,
    state: str,
    attractions: List[Dict[str, Any]],
    restaurants: List[Dict[str, Any]],
    rv_parks: List[Dict[str, Any]],
    arrival_date: Optional[str] = None,
    num_weekdays: int = 2,
    num_weekend_days: int = 2,
) -> Dict[str, Any]:
    """
    Build a complete stay plan.

    Args:
        city, state: Destination
        attractions: List from attractions.py
        restaurants: List from attractions.py
        rv_parks: List from rv_parks.py
        arrival_date: ISO date string or None
        num_weekdays: Number of weeknights (default: 2 = Fri/Sat nights)
        num_weekend_days: Weekend full days (default: 2 = Sat/Sun)

    Returns:
        Dict with keys: summary, days (list), stay_duration, rv_parks, tips
    """
    categories = _categorize_items(attractions, restaurants)
    total_hours = _estimate_activities(attractions)
    nature_hours = _estimate_activities(categories["nature"])
    culture_hours = _estimate_activities(categories["culture"])

    # ── Stay Duration ──────────────────────────
    weekday_hours_available = num_weekdays * WEEKDAY_EVENING_MAX
    weekend_hours_available = num_weekend_days * SATURDAY_DAY
    total_available = weekday_hours_available + weekend_hours_available

    if total_hours <= weekday_hours_available:
        stay_nights = num_weekdays
        stay_days = num_weekdays + 1
        duration_label = f"{stay_nights}-night weekend getaway"
    elif total_hours <= total_available:
        stay_nights = num_weekdays + num_weekend_days
        stay_days = stay_nights + 1
        duration_label = f"{stay_nights}-night / {stay_days}-day extended stay"
    else:
        # Compress itinerary — prioritize
        stay_nights = max(2, num_weekdays)
        stay_days = stay_nights + 1
        duration_label = f"{stay_nights}-night stay (condensed itinerary)"

    # ── Day-by-Day Plan ────────────────────────
    days = []
    day_num = 1

    # Weekday evenings
    for i in range(min(num_weekdays, 3)):
        if i == 0:
            label = f"Day {day_num} — Friday Evening"
        elif i == 1:
            label = f"Day {day_num} — Saturday Evening" if num_weekdays > 1 else f"Day {day_num} — Weekday Evening"
        else:
            label = f"Day {day_num} — Evening"

        slots = []
        # Morning slot (optional for weekday)
        if categories["nature"] and i == 0:
            item = categories["nature"].pop(0)
            slots.append({"time": "Morning", "activity": f"☕ Quick coffee walk + {item['name']}", "duration": "30-60 min", "item": item})
        elif categories["relax"] and i == 0:
            item = categories["relax"].pop(0)
            slots.append({"time": "Morning", "activity": f"☕ Relaxed morning — {item['name']}", "duration": "1 hr", "item": item})

        # Afternoon — nature or culture
        if categories["nature"]:
            item = categories["nature"].pop(0)
            slots.append({"time": "Afternoon", "activity": f"🌲 {item['name']}", "duration": item.get("estimated_time", "2-3 hrs"), "item": item})
        elif categories["culture"]:
            item = categories["culture"].pop(0)
            slots.append({"time": "Afternoon", "activity": f"🏛 {item['name']}", "duration": item.get("estimated_time", "2-3 hrs"), "item": item})

        # Evening — food
        if categories["food"]:
            item = categories["food"].pop(0)
            slots.append({"time": "Evening", "activity": f"🍽 {item['name']}", "duration": "1.5-2 hrs", "item": item})

        days.append({"label": label, "slots": slots})
        day_num += 1

    # Weekend full days
    for i in range(num_weekend_days):
        label = f"Day {day_num} — {'Saturday' if i == 0 else 'Sunday'} (Full Day)"
        slots = []

        # Morning
        if categories["nature"]:
            item = categories["nature"].pop(0)
            slots.append({"time": "Morning", "activity": f"🌲 {item['name']}", "duration": item.get("estimated_time", "2-3 hrs"), "item": item})
        elif categories["culture"]:
            item = categories["culture"].pop(0)
            slots.append({"time": "Morning", "activity": f"🏛 {item['name']}", "duration": item.get("estimated_time", "2-3 hrs"), "item": item})

        # Midday — food
        if categories["food"]:
            item = categories["food"].pop(0)
            slots.append({"time": "Midday", "activity": f"🍽 Lunch — {item['name']}", "duration": "1-1.5 hrs", "item": item})

        # Afternoon
        if categories["nature"]:
            item = categories["nature"].pop(0)
            slots.append({"time": "Afternoon", "activity": f"🌲 {item['name']}", "duration": item.get("estimated_time", "2-3 hrs"), "item": item})
        elif categories["culture"]:
            item = categories["culture"].pop(0)
            slots.append({"time": "Afternoon", "activity": f"🏛 {item['name']}", "duration": item.get("estimated_time", "2-3 hrs"), "item": item})

        # Evening — scenic + dinner
        if categories["nature"]:
            item = categories["nature"].pop(0)
            slots.append({"time": "Evening", "activity": f"🌅 Sunset at {item['name']} + dinner", "duration": "2-3 hrs", "item": item})
        elif categories["food"]:
            item = categories["food"].pop(0)
            slots.append({"time": "Evening", "activity": f"🍽 Dinner — {item['name']}", "duration": "1.5-2 hrs", "item": item})

        days.append({"label": label, "slots": slots})
        day_num += 1

    # ── Tips ──────────────────────────────────
    avg_park_price = 0.0
    if rv_parks:
        prices = [_parse_price(p.get("price", "")) for p in rv_parks]
        prices = [p for p in prices if p > 0]
        if prices:
            avg_park_price = sum(prices) / len(prices)

    tips = [
        "🌅 Arrive mid-afternoon to check into RV park before dark",
        "🚐 Give yourself 30 min buffer between major attractions for setup/travel",
    ]
    if avg_park_price > 0:
        tips.append(f"💰 Average RV park cost: ~${avg_park_price:.0f}/night")
    if nature_hours > 4:
        tips.append("🥾 Pack layers — nature trails vary in difficulty, bring water and snacks")
    if any("brew" in r.get("description","").lower() or "brew" in r.get("name","").lower() for r in categories["food"]):
        tips.append("🍺 Local brewery alert — great evening wind-down spot!")

    # ── RV Park Summary ────────────────────────
    park_summaries = []
    for p in rv_parks[:3]:
        price = p.get("price", "N/A")
        rating = f"⭐ {p.get('rating', 'N/A')}" if p.get("rating") else ""
        park_summaries.append({
            "name": p.get("name", "Unknown Park"),
            "price": price,
            "rating": rating,
            "category": p.get("category", "RV Park"),
            "big_rig": "✅ Big Rig Friendly" if p.get("big_rig_friendly") else "⚠️ Check Site Length",
            "url": p.get("url", ""),
        })

    return {
        "destination": f"{city}, {state}",
        "stay_duration": duration_label,
        "estimated_hours": total_hours,
        "available_hours": total_available,
        "days": days,
        "rv_parks": park_summaries,
        "tips": tips,
        "remaining_attractions": categories["nature"] + categories["culture"] + categories["relax"],
    }


def format_itinerary_text(result: Dict[str, Any]) -> str:
    """Format the itinerary as readable markdown text."""
    lines = [
        f"# 🗺️ Stay Plan: {result['destination']}",
        f"**Recommended Stay:** {result['stay_duration']}",
        f"**Estimated exploration time:** {result['estimated_hours']:.1f} hrs available",
        "",
    ]

    for day in result["days"]:
        lines.append(f"## {day['label']}")
        for slot in day["slots"]:
            lines.append(f"- **{slot['time']}** ({slot['duration']}): {slot['activity']}")
        lines.append("")

    lines.append("## 🏕 RV Parks")
    for park in result["rv_parks"]:
        lines.append(f"- **{park['name']}** — {park['category']} | {park['price']} | {park['big_rig']} {park['rating']}")

    if result["tips"]:
        lines.append("")
        lines.append("## 💡 Tips")
        for tip in result["tips"]:
            lines.append(f"- {tip}")

    return "\n".join(lines)
