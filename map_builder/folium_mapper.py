"""
folium_mapper.py — Generates interactive route maps with Folium

Creates an HTML map with:
- 3 route polylines (Primary/Safe/Scenic) in different colors
- Stop markers with popups
- Elevation profile sidebar
- Route legend
"""

import folium
from folium import plugins
from typing import List, Tuple, Optional, Dict, Any
import os


# Route colors — distinct and visible
ROUTE_COLORS = {
    "Primary": "#2196F3",   # Blue
    "Scenic": "#4CAF50",    # Green
    "Alternate": "#FF9800", # Orange
}


class FoliumMapper:
    """
    Build interactive Folium maps for RV trip routes.
    """

    def __init__(self, start: Tuple[float, float], end: Tuple[float, float]):
        self.start = start
        self.end = end
        self.routes = []  # List of route dicts to render
        self.stops = []   # List of stop recommendation dicts
        self.fuel_stops = []  # List of fuel stop tuples (name, lat, lon)
        self._map = None

    def add_route(
        self,
        geometry: List[Tuple[float, float]],
        route_name: str = "Primary",
        distance_mi: float = 0.0,
        duration_h: float = 0.0,
        score: int = 0,
        warnings: List[str] = None,
    ):
        """Add a route option to the map."""
        color = ROUTE_COLORS.get(route_name, "#9E9E9E")
        self.routes.append({
            "geometry": geometry,
            "name": route_name,
            "distance_mi": distance_mi,
            "duration_h": duration_h,
            "score": score,
            "color": color,
            "warnings": warnings or [],
        })

    def add_stop(
        self,
        name: str,
        lat: float,
        lon: float,
        connectivity_badge: str = "",
        price: Optional[int] = None,
        rating: Optional[float] = None,
        url: str = "",
        stop_type: str = "RV Park",
        pet_friendly: bool = False,
        diesel_nearby: bool = False,
    ):
        """Add a stop marker to the map."""
        self.stops.append({
            "name": name,
            "lat": lat,
            "lon": lon,
            "connectivity_badge": connectivity_badge,
            "price": price,
            "rating": rating,
            "url": url,
            "stop_type": stop_type,
            "pet_friendly": pet_friendly,
            "diesel_nearby": diesel_nearby,
        })

    def add_fuel_stop(self, name: str, lat: float, lon: float):
        """Add a fuel/truck stop marker."""
        self.fuel_stops.append({"name": name, "lat": lat, "lon": lon})

    def build(self, output_path: Optional[str] = None) -> folium.Map:
        """
        Render the full map and return the Folium Map object.
        If output_path is provided, also saves to HTML file.
        """
        # Center map on midpoint of start/end
        center_lat = (self.start[0] + self.end[0]) / 2
        center_lon = (self.start[1] + self.end[1]) / 2

        self._map = folium.Map(
            location=[center_lat, center_lon],
            zoom_start=6,
            tiles="OpenStreetMap",
        )

        # Add route polylines
        for route in self.routes:
            if not route["geometry"]:
                continue
            coords = [[lat, lon] for lat, lon in route["geometry"]]
            popup_html = self._route_popup(route)

            folium.PolyLine(
                locations=coords,
                weight=5 if route["name"] == "Primary" else 3,
                color=route["color"],
                opacity=0.85 if route["name"] == "Primary" else 0.65,
                popup=folium.Popup(popup_html, max_width=300),
                tooltip=f"{route['name']}: {route['distance_mi']} mi",
            ).add_to(self._map)

        # Add start/end markers
        folium.Marker(
            self.start,
            tooltip="🚐 Start",
            icon=folium.Icon(color="green", icon="play", prefix="fa"),
        ).add_to(self._map)

        folium.Marker(
            self.end,
            tooltip="🏁 Destination",
            icon=folium.Icon(color="red", icon="flag-checkered", prefix="fa"),
        ).add_to(self._map)

        # Add stop markers
        for i, stop in enumerate(self.stops, 1):
            popup_html = self._stop_popup(stop)
            folium.Marker(
                [stop["lat"], stop["lon"]],
                tooltip=f"Stop {i}: {stop['name']}",
                popup=folium.Popup(popup_html, max_width=250),
                icon=folium.Icon(color="orange", icon="camera", prefix="fa"),
            ).add_to(self._map)

        # Add fuel stop markers
        for fuel in self.fuel_stops:
            folium.Marker(
                [fuel["lat"], fuel["lon"]],
                tooltip=f"⛽ {fuel['name']}",
                icon=folium.Icon(color="gray", icon="gas-pump", prefix="fa"),
            ).add_to(self._map)

        # Add layer control
        folium.LayerControl().add_to(self._map)

        # Add legend
        self._add_legend()

        # Add fullscreen option
        plugins.Fullscreen().add_to(self._map)

        # Add measure tool
        plugins.Measure().add_to(self._map)

        if output_path:
            self._map.save(output_path)

        return self._map

    def _route_popup(self, route: Dict[str, Any]) -> str:
        """Generate HTML popup for a route."""
        warnings_html = ""
        if route.get("warnings"):
            warnings_html = "<br>".join([
                f"<span style='color:orange'>⚠️ {w}</span>"
                for w in route["warnings"]
            ])

        return f"""
        <div style='font-family:Arial,sans-serif;min-width:220px'>
            <h4 style='margin:0 0 8px'>{route['name']} Route</h4>
            <b>Distance:</b> {route['distance_mi']} mi<br>
            <b>Est. Time:</b> {route['duration_h']:.1f} hrs<br>
            <b>RV Safety Score:</b> {route['score']}/100<br>
            {warnings_html}
        </div>
        """

    def _stop_popup(self, stop: Dict[str, Any]) -> str:
        """Generate HTML popup for a stop."""
        price_str = f"${stop['price']}/night" if stop.get("price") else "Price N/A"
        rating_str = f"★{stop['rating']:.1f}" if stop.get("rating") else "No rating"
        pet_icon = "🐾 Pet OK" if stop.get("pet_friendly") else "🚫 No Pets"
        diesel_icon = "⛽ Diesel nearby" if stop.get("diesel_nearby") else ""
        link_str = f"<a href='{stop['url']}' target='_blank'>View on Campendium</a>" if stop.get("url") else ""

        return f"""
        <div style='font-family:Arial,sans-serif;min-width:220px'>
            <h4 style='margin:0 0 6px'>{stop['name']}</h4>
            <b>Type:</b> {stop['stop_type']}<br>
            <b>Price:</b> {price_str}<br>
            {rating_str}<br>
            <b>Theo:</b> {pet_icon}<br>
            {diesel_icon}<br>
            <b>Connectivity:</b><br>{stop['connectivity_badge']}<br>
            {link_str}
        </div>
        """

    def _add_legend(self):
        """Add a route legend to the map."""
        legend_html = """
        <div style='position:fixed;bottom:50px;left:50px;z-index:1000;
                    background:white;padding:12px;border-radius:8px;
                    border:1px solid #ccc;font-family:Arial,sans-serif;font-size:13px;
                    box-shadow:0 2px 6px rgba(0,0,0,0.15)'>
            <b>RV Trip Optimizer</b><br>
            <span style='color:#2196F3'>━━━</span> Primary Route<br>
            <span style='color:#4CAF50'>━━━</span> Scenic Route<br>
            <span style='color:#FF9800'>━━━</span> Alternate Route<br>
            <span style='color:orange'>●</span> Overnight Stop<br>
            <span style='color:gray'>●</span> Fuel Stop
        </div>
        """
        self._map.get_root().html.add_child(folium.Element(legend_html))

    def save(self, output_path: str):
        """Save the map to an HTML file."""
        if self._map:
            self._map.save(output_path)

    def get_html(self) -> str:
        """Return the map as raw HTML string."""
        if self._map:
            return self._map._repr_html_()
        return ""
