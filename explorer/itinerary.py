"""
itinerary.py — AI-powered itinerary builder for RV Explorer

Handles three recommendation tiers:
  - Tourist Favorites: must-see, top-rated
  - Local Gems: underrated, locally loved
  - Unique Ideas: quirky, one-of-a-kind experiences

Respects:
  - Weekday: 2-3 hrs max (remote work constraint)
  - Weekend: Full day available
  - RV travel overhead
"""

from typing import List, Dict, Any, Optional

# ─── Time Constants ───────────────────────────────────────────────
WEEKDAY_MORNING_MAX = 0.75   # hrs — quick coffee, walk, farmer's market
WEEKDAY_EVENING_MAX = 2.5    # hrs — main attraction or dinner outing
SATURDAY_DAY = 7.0           # hrs — full day Saturday
SUNDAY_HALF = 4.5            # hrs — half day Sunday


def _estimate_hours(time_str: Optional[str]) -> float:
    """Parse estimated_time string → hours."""
    if not time_str:
        return 2.0
    s = time_str.lower().strip()
    try:
        if "min" in s or "hr" not in s:
            m = float(re.sub(r"[^0-9.]", "", s))
            return max(0.5, m / 60)
        nums = re.findall(r"[\d.]+", s)
        if not nums:
            return 2.0
        val = float(nums[0])
        if "h" in s and "-" in s:
            # "1-2 hrs" → average
            return (val + float(nums[1])) / 2 if len(nums) > 1 else val
        return val
    except Exception:
        return 2.0


import re


def _categorize_by_tier(attractions: List[Dict[str, Any]]) -> Dict[str, List]:
    """
    Split attractions into three tiers.
    Returns dict with keys: tourist_favorites, local_gems, unique_ideas
    """
    tiers = {
        "tourist_favorites": [],
        "local_gems": [],
        "unique_ideas": [],
        "food": [],
    }

    for item in attractions:
        tier = item.get("tier", "tourist_favorite")
        if tier == "food" or "restaurant" in item.get("category", "").lower() or "food" in item.get("category", "").lower() or "brew" in item.get("category", "").lower():
            tiers["food"].append(item)
        elif tier in ("tourist_favorite", "tourist"):
            tiers["tourist_favorites"].append(item)
        elif tier == "local_gem":
            tiers["local_gems"].append(item)
        elif tier == "unique_idea":
            tiers["unique_ideas"].append(item)
        else:
            tiers["tourist_favorites"].append(item)

    return tiers


def _build_day_slots(
    items: List[Dict[str, Any]],
    day_label: str,
    slot_times: List[str],
    is_full_day: bool = False,
) -> Dict[str, Any]:
    """
    Map a list of items into Morning / Afternoon / Evening slots.
    Each item gets its own slot.
    """
    slots = []
    time_idx = 0

    for item in items:
        if time_idx >= len(slot_times):
            break
        time_label = slot_times[time_idx]
        time_idx += 1

        hrs = _estimate_hours(item.get("estimated_time"))
        icon = ""
        if "nature" in item.get("category", "").lower() or "hike" in item.get("category", "").lower() or "park" in item.get("category", "").lower():
            icon = "🌲"
        elif "museum" in item.get("category", "").lower() or "historic" in item.get("category", "").lower():
            icon = "🏛"
        elif "food" in item.get("category", "").lower() or "restaurant" in item.get("category", "").lower() or "brew" in item.get("category", "").lower():
            icon = "🍽"
        elif "unique" in item.get("category", "").lower() or "quirky" in item.get("category", "").lower():
            icon = "✨"
        else:
            icon = "📍"

        activity_parts = [f"{icon} {item['name']}"]
        if item.get("description"):
            desc = item["description"]
            if len(desc) > 120:
                desc = desc[:120] + "…"
            activity_parts.append(f"_{desc}_")

        slots.append({
            "time": time_label,
            "activity": " | ".join(activity_parts),
            "duration": item.get("estimated_time", f"~{hrs:.1f} hrs"),
            "item": item,
        })

    return {"label": day_label, "slots": slots}


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
    Build a complete stay plan from rich attractions data.

    Each day has Morning / Afternoon / Evening slots.
    Items come from tourist_favorites, local_gems, and unique_ideas tiers.
    """
    tiers = _categorize_by_tier(attractions)

    tourist = tiers["tourist_favorites"]
    gems = tiers["local_gems"]
    unique = tiers["unique_ideas"]
    food = tiers["food"] + restaurants

    # Reserve food items for evening and midday slots
    food_pool = food[:]
    all_other = tourist + gems + unique

    # Estimate total hours
    total_hours = sum(_estimate_hours(a.get("estimated_time")) for a in all_other)
    weekday_available = num_weekdays * WEEKDAY_EVENING_MAX
    weekend_available = num_weekend_days * SATURDAY_DAY
    total_available = weekday_available + weekend_available

    # Stay duration
    if total_hours <= weekday_available:
        duration_label = f"{num_weekdays}-night weekend getaway"
        stay_nights = num_weekdays
    elif total_hours <= total_available:
        stay_nights = num_weekdays + num_weekend_days
        duration_label = f"{stay_nights}-night extended stay"
    else:
        stay_nights = max(2, num_weekdays)
        duration_label = f"{stay_nights}-night stay (condensed)"

    days = []
    day_num = 1

    # ── Weekday Evenings ──────────────────────────────────────────
    weekday_times = [
        ("Morning", "🌅 Quick stop"),
        ("Afternoon", "🏛 Main attraction"),
        ("Evening", "🍽 Dinner"),
    ]

    for i in range(min(num_weekdays, 3)):
        label = f"Day {day_num} — {'Friday' if i == 0 else 'Saturday' if i == 1 else 'Weekday'} Evening"
        day_slots = []

        # Morning: coffee / quick nature if morning slot requested
        if i == 0 and gems:
            item = gems.pop(0)
            day_slots.append({
                "time": "Morning",
                "activity": f"☕ Quick walk — {item['name']}",
                "duration": "30-45 min",
                "item": item,
            })

        # Afternoon: top tourist attraction
        if all_other:
            item = all_other.pop(0)
            day_slots.append({
                "time": "Afternoon",
                "activity": f"📍 {item['name']}",
                "duration": item.get("estimated_time", "2-3 hrs"),
                "item": item,
            })

        # Evening: dinner
        if food_pool:
            item = food_pool.pop(0)
            day_slots.append({
                "time": "Evening",
                "activity": f"🍽 {item['name']}",
                "duration": "1.5-2 hrs",
                "item": item,
            })

        if day_slots:
            days.append({"label": label, "slots": day_slots})
        day_num += 1

    # ── Full Weekend Days ─────────────────────────────────────────
    weekend_slot_times = [
        "Morning", "Midday", "Afternoon", "Evening"
    ]

    for i in range(num_weekend_days):
        label = f"Day {day_num} — {'Saturday' if day_num == num_weekdays + 1 else 'Sunday'} (Full Day)"
        day_slots = []

        # Morning: top attraction
        if all_other:
            item = all_other.pop(0)
            day_slots.append({
                "time": "Morning",
                "activity": f"🌲 {item['name']}",
                "duration": item.get("estimated_time", "2-3 hrs"),
                "item": item,
            })
        elif gems:
            item = gems.pop(0)
            day_slots.append({
                "time": "Morning",
                "activity": f"✨ {item['name']} [Local Gem]",
                "duration": item.get("estimated_time", "1-2 hrs"),
                "item": item,
            })

        # Midday: food / lunch
        if food_pool:
            item = food_pool.pop(0)
            day_slots.append({
                "time": "Midday",
                "activity": f"🍽 Lunch — {item['name']}",
                "duration": "1 hr",
                "item": item,
            })

        # Afternoon: local gem or second attraction
        if gems:
            item = gems.pop(0)
            day_slots.append({
                "time": "Afternoon",
                "activity": f"✨ {item['name']} [Local Gem]",
                "duration": item.get("estimated_time", "1-2 hrs"),
                "item": item,
            })
        elif all_other:
            item = all_other.pop(0)
            day_slots.append({
                "time": "Afternoon",
                "activity": f"📍 {item['name']}",
                "duration": item.get("estimated_time", "2-3 hrs"),
                "item": item,
            })

        # Evening: scenic + dinner
        if unique:
            item = unique.pop(0)
            day_slots.append({
                "time": "Evening",
                "activity": f"🌅 {item['name']} [Unique]",
                "duration": "1.5-2 hrs",
                "item": item,
            })
        elif food_pool:
            item = food_pool.pop(0)
            day_slots.append({
                "time": "Evening",
                "activity": f"🍽 {item['name']}",
                "duration": "1.5-2 hrs",
                "item": item,
            })

        if day_slots:
            days.append({"label": label, "slots": day_slots})
        day_num += 1

    # ── RV Parks ─────────────────────────────────────────────────
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

    # ── Tips ─────────────────────────────────────────────────────
    tips = [
        "🌅 Arrive mid-afternoon to check into RV park before dark",
        "🚐 Allow 30 min buffer between major attractions for setup/travel",
    ]
    if unique:
        tips.append(f"✨ {unique[0]['name']} is a highlight — save it for evening if possible")
    if any("brew" in f.get("name", "").lower() or "brew" in f.get("category", "").lower() for f in food[:3]):
        tips.append("🍺 Local brewery alert — great wind-down spot after driving day")
    if any("farm" in a.get("category", "").lower() or "market" in a.get("category", "").lower() for a in all_other[:5]):
        tips.append("🛒 Check local farmer's market — often on weekends only")
    if any("hike" in a.get("category", "").lower() or "trail" in a.get("category", "").lower() for a in tourist[:3]):
        tips.append("🥾 Pack layers and water — trail conditions vary")

    return {
        "destination": f"{city}, {state}",
        "stay_duration": duration_label,
        "estimated_hours": total_hours,
        "available_hours": total_available,
        "days": days,
        "rv_parks": park_summaries,
        "tips": tips,
        "remaining_attractions": all_other + gems + unique,
        "tiers": {
            "tourist_favorites": tourist[:5],
            "local_gems": gems[:4],
            "unique_ideas": unique[:3],
            "food": food[:5],
        },
    }


def format_itinerary_markdown(result: Dict[str, Any]) -> str:
    """
    Format the full itinerary as readable markdown with links.
    """
    lines = [
        f"# 🗺️ Stay Plan: {result['destination']}",
        f"**Recommended Stay:** {result['stay_duration']}",
        "",
    ]

    # Tiers overview
    tiers = result.get("tiers", {})
    if tiers.get("tourist_favorites"):
        lines.append("## ⭐ Tourist Favorites")
        for item in tiers["tourist_favorites"]:
            url = item.get("yelp_url") or item.get("ta_url") or item.get("wiki_url") or item.get("nps_url") or ""
            rating = f" ★ {item['rating']}" if item.get("rating") else ""
            desc = f" — {item['description'][:100]}" if item.get("description") else ""
            lines.append(f"- **{item['name']}**{rating}{desc}")
            if url:
                lines.append(f"  🔗 [View Details]({url})")

    if tiers.get("local_gems"):
        lines.append("\n## ✨ Local Gems")
        for item in tiers["local_gems"]:
            url = item.get("yelp_url") or item.get("reddit_url") or ""
            desc = f" — {item['description'][:100]}" if item.get("description") else ""
            lines.append(f"- **{item['name']}**{desc}")
            if url:
                lines.append(f"  🔗 [View Details]({url})")

    if tiers.get("unique_ideas"):
        lines.append("\n## 🎯 Unique Ideas")
        for item in tiers["unique_ideas"]:
            url = item.get("yelp_url") or ""
            lines.append(f"- **{item['name']}**")
            if url:
                lines.append(f"  🔗 [View Details]({url})")

    if tiers.get("food"):
        lines.append("\n## 🍽 Where to Eat")
        for item in tiers["food"]:
            url = item.get("yelp_url") or ""
            rating = f" ★ {item['rating']}" if item.get("rating") else ""
            price = f" ({item.get('category', '')})" if item.get("category") else ""
            lines.append(f"- **{item['name']}**{rating}{price}")
            if url:
                lines.append(f"  🔗 [Yelp]({url})")

    lines.append("\n## 🗓️ Day-by-Day Itinerary")
    for day in result["days"]:
        lines.append(f"\n### {day['label']}")
        for slot in day["slots"]:
            item = slot.get("item", {})
            url = item.get("yelp_url") or item.get("ta_url") or item.get("wiki_url") or item.get("nps_url") or ""
            link_str = f" [🔗]({url})" if url else ""
            lines.append(f"- **{slot['time']}** ({slot['duration']}): {slot['activity']}{link_str}")

    if result.get("rv_parks"):
        lines.append("\n## 🏕️ RV Parks")
        for park in result["rv_parks"]:
            url_str = f" [Book Now]({park['url']})" if park.get("url") else ""
            lines.append(f"- **{park['name']}** — {park['category']} · {park['price']}/night · {park['big_rig']}{url_str}")

    if result.get("tips"):
        lines.append("\n## 💡 Tips")
        for tip in result["tips"]:
            lines.append(f"- {tip}")

    return "\n".join(lines)
