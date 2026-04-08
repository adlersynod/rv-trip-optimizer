"""
leg_segmenter.py — Splits a long trip into ≤max_distance legs

Algorithm:
1. Get full route geometry from RouteEngine
2. Walk along the route cumulative distance
3. Find natural stopping points at ~max_distance intervals
4. Search for a suitable overnight stop near each split point
5. Return list of Leg objects
"""

import math
from dataclasses import dataclass
from typing import List, Tuple, Optional
from .geocoder import distance_haversine


@dataclass
class TripLeg:
    leg_index: int
    start: Tuple[float, float]  # (lat, lon)
    end: Tuple[float, float]     # (lat, lon)
    distance_mi: float
    route_geometry: List[Tuple[float, float]]
    suggested_stop: Optional["StopRecommendation"] = None
    route_warnings: List[str] = None

    def __post_init__(self):
        if self.route_warnings is None:
            self.route_warnings = []


@dataclass
class StopRecommendation:
    name: str
    lat: float
    lon: float
    distance_from_route_mi: float
    starlink: bool = False
    cellular_carrier: str = ""  # e.g., "Verizon", "T-Mobile", "AT&T"
    cellular_bars: int = 0      # 1-5
    price_per_night: Optional[int] = None
    rating: Optional[float] = None
    review_count: int = 0
    amenities: List[str] = None
    url: str = ""
    connectivity_score: int = 0  # 0-10

    def __post_init__(self):
        if self.amenities is None:
            self.amenities = []


class LegSegmenter:
    """
    Takes a full route geometry and max leg distance,
    returns a list of TripLeg objects with suggested stops.
    """

    def __init__(self, max_leg_miles: float = 300.0):
        self.max_leg_miles = max_leg_miles

    def segment_route(
        self,
        full_geometry: List[Tuple[float, float]],
        route_distances: List[float],  # cumulative distance at each point in miles
    ) -> List[TripLeg]:
        """
        Split full geometry into legs of ≤max_leg_miles.
        route_distances: list of same length as full_geometry,
                         where route_distances[i] = cumulative distance in miles from start
        """
        legs = []
        leg_index = 0
        current_leg_points = [full_geometry[0]]
        current_dist_start = 0.0

        for i in range(1, len(full_geometry)):
            dist_at_i = route_distances[i]

            if dist_at_i - current_dist_start >= self.max_leg_miles:
                # Close current leg at previous point
                if len(current_leg_points) > 1:
                    legs.append(TripLeg(
                        leg_index=leg_index,
                        start=current_leg_points[0],
                        end=current_leg_points[-1],
                        distance_mi=round(dist_at_i - current_dist_start, 1),
                        route_geometry=current_leg_points.copy(),
                        route_warnings=[],
                    ))
                    leg_index += 1
                    current_leg_points = [full_geometry[i - 1], full_geometry[i]]
                    current_dist_start = route_distances[i - 1]
                else:
                    current_leg_points.append(full_geometry[i])
            else:
                current_leg_points.append(full_geometry[i])

        # Final leg
        if len(current_leg_points) > 1:
            final_dist = route_distances[-1] if route_distances else 0
            legs.append(TripLeg(
                leg_index=leg_index,
                start=current_leg_points[0],
                end=current_leg_points[-1],
                distance_mi=round(final_dist - current_dist_start, 1),
                route_geometry=current_leg_points.copy(),
                route_warnings=[],
            ))

        return legs

    def find_split_point(
        self,
        geometry: List[Tuple[float, float]],
        target_distance_mi: float,
        route_distances: List[float],
    ) -> Tuple[int, Tuple[float, float]]:
        """
        Find the index and coordinates closest to target_distance_mi
        along the route.
        """
        for i, d in enumerate(route_distances):
            if d >= target_distance_mi:
                return i, geometry[i]
        return len(geometry) - 1, geometry[-1]

    def estimate_drive_time(self, distance_mi: float, road_type: str = "highway") -> float:
        """
        Rough drive time estimate in hours.
        highway: 55 mph avg, secondary: 35 mph avg
        """
        if "highway" in road_type.lower() or "motorway" in road_type.lower():
            return distance_mi / 55.0
        return distance_mi / 35.0

    def get_midpoint(self, geometry: List[Tuple[float, float]]) -> Tuple[float, float]:
        """Return the midpoint of a route geometry."""
        n = len(geometry)
        if n == 0:
            return (0.0, 0.0)
        if n == 1:
            return geometry[0]
        mid = n // 2
        return geometry[mid]
