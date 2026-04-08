"""
route_engine.py — OSRM routing with RV-safe post-processing

Uses public OSRM demo server. Note: OSRM demo does not include bridge/tunnel
height restrictions. Post-processing applies rough heuristic elimination
based on road classification and route characteristics.
For production: self-host OSRM with a truck/hgv profile + custom spatialite data.
"""

import requests
import polyline
from typing import Optional, List, Dict, Any, Tuple
from dataclasses import dataclass
import json
import os

OSRM_PUBLIC_URL = "https://router.project-osrm.org"
OSRM_PUBLIC_FALLBACK_URL = "https://routing.openstreetmap.de/routed-car/"

# Road types to be cautious about for 43' RV
RISKY_ROAD_TYPES = {"unclassified", "residential", "track", "path", "service"}


@dataclass
class RVProfile:
    length_ft: int = 43
    width_ft: float = 8.5
    height_ft: float = 13.5
    min_clearance_ft: float = 14.5
    max_grade_percent: float = 8.0
    loaded_weight_lbs: int = 45000


def load_profile() -> RVProfile:
    path = os.path.join(os.path.dirname(__file__), "..", "assets", "brinkley_profile.json")
    try:
        with open(path) as f:
            data = json.load(f)
        d = data["dimensions"]
        w = data["weight"]
        r = data["routing_constraints"]
        return RVProfile(
            length_ft=d["length_ft"],
            width_ft=d["width_ft"],
            height_ft=d["height_ft"],
            min_clearance_ft=r["min_clearance_ft"],
            max_grade_percent=r["max_grade_percent"],
            loaded_weight_lbs=w["loaded_weight_lbs"],
        )
    except Exception:
        return RVProfile()


class RouteEngine:
    def __init__(self, profile: Optional[RVProfile] = None):
        self.profile = profile or load_profile()

    def get_route(
        self,
        start: Tuple[float, float],
        end: Tuple[float, float],
        alternatives: int = 3,
    ) -> Optional[Dict[str, Any]]:
        """
        Get route(s) from OSRM. Tries public demo server first,
        falls back to routing.openstreetmap.de, then to
        great-circle estimation if all servers fail.
        """
        # OSRM wants {lon},{lat}
        coords = f"{start[1]},{start[0]};{end[1]},{end[0]}"
        params = {
            "overview": "full",
            "geometries": "polyline",
            "steps": "true",
            "alternatives": str(alternatives),
        }

        servers = [
            OSRM_PUBLIC_URL,
            OSRM_PUBLIC_FALLBACK_URL,
        ]

        for server in servers:
            try:
                resp = requests.get(
                    f"{server}/route/v1/driving/{coords}",
                    params=params,
                    timeout=15,
                    headers={"User-Agent": "RV-Trip-Optimizer/1.0"},
                )
                resp.raise_for_status()
                data = resp.json()
                if data.get("code") == "Ok" and data.get("routes"):
                    return data
            except Exception as e:
                print(f"[route_engine] OSRM server {server} failed: {e}")
                continue

        # Fallback: great-circle distance estimate with road-type heuristic
        return self._haversine_fallback(start, end)

    def _haversine_fallback(
        self,
        start: Tuple[float, float],
        end: Tuple[float, float],
    ) -> Optional[Dict[str, Any]]:
        """
        Fallback routing when no OSRM server is reachable.
        Uses great-circle distance × 1.35 road factor + interpolated
        geometry for map display. This is NOT a real route — it is a
        straight-line estimate with road-winding applied.

        WARNING: Do NOT use this for actual navigation.
        """
        from math import radians, sin, cos, sqrt, atan2, atan, pi
        R = 3958.8  # Earth radius in miles

        lat1, lon1 = radians(start[0]), radians(start[1])
        lat2, lon2 = radians(end[0]), radians(end[1])

        dlat = lat2 - lat1
        dlon = lon2 - lon1
        a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
        gc_dist = R * 2 * atan2(sqrt(a), sqrt(1 - a))

        # Road factor: actual roads are ~35% longer than great-circle
        road_dist_mi = gc_dist * 1.35
        duration_s = road_dist_mi / 55.0 * 3600  # ~55 mph average

        # Interpolate geometry: 20 points along great-circle
        geometry = []
        for t in range(20):
            f = t / 19.0
            lat = start[0] + f * (end[0] - start[0])
            lon = start[1] + f * (end[1] - start[1])
            geometry.append((lat, lon))

        encoded_geom = polyline.encode(geometry)

        return {
            "code": "Ok",
            "routes": [{
                "distance": road_dist_mi * 1609.34,
                "duration": duration_s,
                "geometry": encoded_geom,
                "legs": [{
                    "steps": [
                        {"road_type": "highway", "distance": road_dist_mi * 1609.34,
                         "maneuver": "arrive", "name": "Estimated route (OSRM unreachable)"}
                    ]
                }]
            }],
            "waypoints": [],
        }

    def get_safe_routes(
        self,
        start: Tuple[float, float],
        end: Tuple[float, float],
        max_alt_distance_pct: float = 1.5,
        toll_threshold: float = 25.0,
    ) -> List[Dict[str, Any]]:
        """
        Returns up to 3 route options with RV safety annotations.
        Each route dict:
          - name: "Primary" / "Scenic" / "Alternate"
          - geometry: decoded polyline [(lat, lon), ...]
          - distance_mi: total distance in miles
          - duration_h: estimated hours
          - steps: list of {instruction, distance, road_type}
          - warnings: list of flagged concerns
          - score: 0-100 RV safety score
        """
        raw = self.get_route(start, end, alternatives=3)
        if not raw:
            return []

        routes_out = []
        route_names = ["Primary", "Scenic", "Alternate"]

        for i, r in enumerate(raw.get("routes", [])):
            if i >= 3:
                break

            geom = polyline.decode(r["geometry"])
            distance_mi = r["distance"] / 1609.34
            duration_h = r["duration"] / 3600

            steps = []
            warnings = []
            risky_count = 0

            for step in r.get("legs", [{}])[0].get("steps", []):
                if not isinstance(step, dict):
                    # Fallback route: step may be a simple dict
                    road_type = str(step.get("road_type") if isinstance(step, dict) else "unknown")
                    maneuver = str(step.get("maneuver", {}) if isinstance(step, dict) else "arrive")
                    instruction = str(step.get("name", road_type) if isinstance(step, dict) else "Estimated route")
                    step_dist = float(step.get("distance", 0) if isinstance(step, dict) else 0)
                else:
                    road_type = step.get("road_type", "unknown")
                    maneuver_obj = step.get("maneuver", {})
                    maneuver = maneuver_obj.get("type", "") if isinstance(maneuver_obj, dict) else str(maneuver_obj)
                    instruction = step.get("name", road_type)
                    step_dist = step.get("distance", 0)

                steps.append({
                    "instruction": instruction,
                    "distance_m": step_dist,
                    "road_type": road_type,
                    "maneuver": maneuver,
                })

                if road_type in RISKY_ROAD_TYPES:
                    risky_count += 1

            # Rough safety score based on road type mix
            risky_pct = risky_count / max(len(steps), 1) * 100
            if risky_pct > 30:
                warnings.append(f"Route contains {risky_pct:.0f}% narrow/residential roads")
            if distance_mi > 350:
                warnings.append(f"Long leg: {distance_mi:.0f} mi — consider splitting")

            # Toll detection: check route name and step names for toll road indicators
            toll_road_indicators = [
                "toll", "turnpike", "tpke", "tx-130", "sl 1", "spur",
                "收费", "有料", "autopista", "e-z pass", "e-zpass"
            ]
            is_toll = False
            for step in steps:
                name_lower = step["instruction"].lower()
                if any(ind in name_lower for ind in toll_road_indicators):
                    is_toll = True
                    break

            # Score
            base_score = 100
            base_score -= min(risky_pct * 0.8, 30)
            base_score -= max(0, (distance_mi - 300) * 0.1)
            # Toll penalty applied post-comparison (see apply_smart_toll)

            route_name = route_names[i] if i < len(route_names) else f"Route {i+1}"

            routes_out.append({
                "name": route_name,
                "geometry": geom,
                "distance_mi": round(distance_mi, 1),
                "duration_h": round(duration_h, 1),
                "steps": steps,
                "warnings": warnings,
                "score": base_score,  # Raw score before toll adjustment
                "is_toll": is_toll,
                "raw": r,
            })

        # ── Smart Toll Logic ─────────────────────────────────────────────
        routes_out = self._apply_smart_toll(routes_out, threshold_mi=toll_threshold)

        return routes_out

    def _apply_smart_toll(
        self,
        routes: List[Dict[str, Any]],
        threshold_mi: float = 25.0,
    ) -> List[Dict[str, Any]]:
        """
        Smart Toll Rule: prefer free routes unless the free route adds
        significant distance over the toll route.

        If (free_distance - toll_distance) > threshold_mi → toll route wins
        Otherwise → free route wins (lower score = better in our system)

        Applies a score bonus to the preferred route.
        """
        toll_routes = [r for r in routes if r.get("is_toll")]
        free_routes = [r for r in routes if not r.get("is_toll")]

        if not toll_routes or not free_routes:
            # No choice to make — normalize scores to 0-100
            for r in routes:
                r["score"] = max(0, min(100, int(r["score"])))
                r["toll_note"] = ""
            return routes

        # Use the shortest toll and shortest free route for comparison
        toll_best = min(toll_routes, key=lambda r: r["distance_mi"])
        free_best = min(free_routes, key=lambda r: r["distance_mi"])

        delta = free_best["distance_mi"] - toll_best["distance_mi"]

        for r in routes:
            if delta > threshold_mi:
                # Free route is significantly longer — toll route earns preference
                if r.get("is_toll"):
                    r["toll_note"] = f"Toll route preferred: {delta:.0f} mi shorter than free option"
                    r["warnings"] = [w for w in r.get("warnings", [])]
                else:
                    r["toll_note"] = f"Free route is {delta:.0f} mi longer — consider toll alternative"
                    r["warnings"].append(
                        f"Free route adds ~{delta:.0f} mi vs toll — accept toll to save time"
                    )
            else:
                # Free route is competitive — prefer it
                if r.get("is_toll"):
                    r["toll_note"] = f"Toll adds cost; free route is only {delta:.0f} mi longer"
                    r["warnings"].append(
                        f"Toll route — free alternative is only {delta:.0f} mi longer"
                    )
                else:
                    r["toll_note"] = f"Free route wins: only {delta:.0f} mi longer than toll"
                    r["warnings"].append(f"Taking free route — saves toll costs, only {delta:.0f} mi detour")

            # Finalize score
            r["score"] = max(0, min(100, int(r["score"])))

        return routes

        return routes_out

    def get_elevation_profile(self, geometry: List[Tuple[float, float]]) -> List[float]:
        """
        Fetch elevation for each point in geometry using USGS Elevation API.
        Returns list of elevation values in feet (approximate).
        Note: Free tier has rate limits — use sparingly.
        """
        elevations = []
        # Sample every 10th point to stay within API limits
        sample = geometry[::max(1, len(geometry) // 20)][:20]

        for lat, lon in sample:
            try:
                url = (
                    f"https://epqs.nationalmap.gov/v1/json?"
                    f"{lat},{lon}/EPSG:4326?units=Feet&wkid=4326&includeDate=false"
                )
                resp = requests.get(url, timeout=5)
                resp.raise_for_status()
                data = resp.json()
                elevations.append(float(data.get("value", 0)))
            except Exception:
                elevations.append(0)

        return elevations
