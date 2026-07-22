#!/usr/bin/env python3
"""
place_to_3d.py — turn a Google Maps place into a 3D model in Blender.

Pipeline:
  1. Resolve a Google Maps URL, coordinates, or name into latitude/longitude.
  2. Download local geometry from OpenStreetMap through the free Overpass API:
     buildings, roads, water, parks, and green areas.
  3. Optionally download Street View and place photos with a Google API key.
  4. Project the data into local meters and generate scene.json.
  5. Run blender_build.py to construct the 3D scene and render a PNG.

Usage:
  python3 scripts/place_to_3d.py "<Maps URL | lat,lng | name>" [options]

Options:
  --radius M       Reconstruction radius in meters (default 250)
  --out DIR        Output directory (default output/<slug>)
  --no-streetview  Do not download Google imagery
  --no-render      Generate data and scene.json without opening Blender
  --blender PATH   Path to the Blender binary (otherwise use the bpy module)

Env:
  GOOGLE_MAPS_API_KEY   Google Maps Platform API key
"""
import argparse
import json
import math
import os
import re
import subprocess
import sys
import time
import unicodedata
import xml.etree.ElementTree as ET
from pathlib import Path

try:
    import requests
except ImportError:
    sys.exit("Missing 'requests'. Install it with: python3 -m pip install requests")

HERE = Path(__file__).resolve().parent
BLENDER_BUILD = HERE / "blender_build.py"
import urban_detail

OVERPASS_ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
    "https://overpass.osm.jp/api/interpreter",
]
USER_AGENT = "geoblender-blender-skill/1.0 (OSM data; educational)"

# ---------------------------------------------------------------------------
# 1) Resolve the place -> (latitude, longitude, label)
# ---------------------------------------------------------------------------

COORD_RE = re.compile(r"(-?\d{1,3}\.\d+)\s*,\s*(-?\d{1,3}\.\d+)")


def _valid(lat, lon):
    return -90 <= lat <= 90 and -180 <= lon <= 180


def _extract_coords_from_url(url):
    """Return (latitude, longitude) parsed from a Google Maps URL, or None."""
    # The actual place pin is more precise than the viewport center.
    m = re.search(r"!3d(-?\d{1,3}\.\d+)!4d(-?\d{1,3}\.\d+)", url)
    if m:
        lat, lon = float(m.group(1)), float(m.group(2))
        if _valid(lat, lon):
            return lat, lon
    # Viewport center: @lat,lon,zoom
    m = re.search(r"@(-?\d{1,3}\.\d+),(-?\d{1,3}\.\d+)", url)
    if m:
        lat, lon = float(m.group(1)), float(m.group(2))
        if _valid(lat, lon):
            return lat, lon
    # Query parameters: q= / ll= / query= / center=
    for key in ("q", "query", "ll", "center", "sll", "daddr"):
        m = re.search(rf"[?&]{key}=(-?\d{{1,3}}\.\d+)[,%2C]+(-?\d{{1,3}}\.\d+)", url)
        if m:
            lat, lon = float(m.group(1)), float(m.group(2))
            if _valid(lat, lon):
                return lat, lon
    return None


def _geocode(query, api_key):
    """As a last resort, geocode a name with the Google API."""
    r = requests.get(
        "https://maps.googleapis.com/maps/api/geocode/json",
        params={"address": query, "key": api_key},
        timeout=30,
    )
    data = r.json()
    if data.get("status") == "OK" and data.get("results"):
        loc = data["results"][0]["geometry"]["location"]
        label = data["results"][0].get("formatted_address", query)
        return loc["lat"], loc["lng"], label
    raise SystemExit(f"Could not geocode '{query}': {data.get('status')} {data.get('error_message','')}")


def resolve_location(text, api_key=None):
    """text -> (lat, lon, label)."""
    text = text.strip()

    # Case 1: direct "lat,lng" coordinates.
    if COORD_RE.fullmatch(text):
        lat, lon = map(float, COORD_RE.fullmatch(text).groups())
        if _valid(lat, lon):
            return lat, lon, f"{lat:.5f},{lon:.5f}"

    # Case 2: URL.
    if text.startswith("http://") or text.startswith("https://"):
        # Follow shortened Maps URLs.
        final_url = text
        try:
            resp = requests.get(
                text, allow_redirects=True, timeout=30,
                headers={"User-Agent": "Mozilla/5.0 (compatible; geoblender/1.0)"},
            )
            final_url = resp.url
            body = resp.text
        except requests.RequestException:
            body = ""
        coords = _extract_coords_from_url(final_url)
        if not coords and body:
            coords = _extract_coords_from_url(body)
        if coords:
            return coords[0], coords[1], "google-maps-link"
        # If the URL has no coordinates, try geocoding its place name.
        m = re.search(r"/place/([^/@]+)", final_url)
        if m and api_key:
            name = requests.utils.unquote(m.group(1)).replace("+", " ")
            return _geocode(name, api_key)
        raise SystemExit(
            "Could not extract coordinates from the link. Provide the complete URL "
            "with @lat,lng, pass 'lat,lng' directly, or set GOOGLE_MAPS_API_KEY."
        )

    # Case 3: coordinates embedded in arbitrary text.
    m = COORD_RE.search(text)
    if m:
        lat, lon = float(m.group(1)), float(m.group(2))
        if _valid(lat, lon):
            return lat, lon, text[:40]

    # Case 4: free-form name -> geocode.
    if api_key:
        return _geocode(text, api_key)
    raise SystemExit(
        f"Could not understand '{text}'. Provide a Google Maps URL, 'lat,lng', "
        "or set GOOGLE_MAPS_API_KEY to search by name."
    )


# ---------------------------------------------------------------------------
# 2) Project latitude/longitude into local meters around the center.
# ---------------------------------------------------------------------------

def make_projector(lat0, lon0):
    m_per_deg_lat = 111320.0
    m_per_deg_lon = 111320.0 * math.cos(math.radians(lat0))

    def project(lat, lon):
        x = (lon - lon0) * m_per_deg_lon  # east (+)
        y = (lat - lat0) * m_per_deg_lat  # north (+)
        return (x, y)

    return project


def _intersect_axis(a, b, axis, val):
    """Return where segment a-b crosses the line coord[axis] == val."""
    other = 1 - axis
    denom = b[axis] - a[axis]
    t = 0.0 if abs(denom) < 1e-12 else (val - a[axis]) / denom
    o = a[other] + t * (b[other] - a[other])
    return (val, o) if axis == 0 else (o, val)


def clip_polygon(poly, H):
    """Clip a polygon to the square [-H,H]^2 with Sutherland-Hodgman."""
    pts = poly[:]
    if len(pts) > 1 and pts[0] == pts[-1]:
        pts = pts[:-1]
    edges = [
        (lambda p: p[0] >= -H, 0, -H),
        (lambda p: p[0] <= H, 0, H),
        (lambda p: p[1] >= -H, 1, -H),
        (lambda p: p[1] <= H, 1, H),
    ]
    for inside, axis, val in edges:
        if not pts:
            return []
        out = []
        n = len(pts)
        for i in range(n):
            a, b = pts[i], pts[(i + 1) % n]
            ina, inb = inside(a), inside(b)
            if ina:
                out.append(a)
                if not inb:
                    out.append(_intersect_axis(a, b, axis, val))
            elif inb:
                out.append(_intersect_axis(a, b, axis, val))
        pts = out
    return pts


def clip_segment(a, b, H):
    """Clip segment a-b to [-H,H]^2 with Liang-Barsky, or return None."""
    x1, y1 = a
    x2, y2 = b
    dx, dy = x2 - x1, y2 - y1
    t0, t1 = 0.0, 1.0
    for p, q in ((-dx, x1 + H), (dx, H - x1), (-dy, y1 + H), (dy, H - y1)):
        if abs(p) < 1e-12:
            if q < 0:
                return None
            continue
        r = q / p
        if p < 0:
            if r > t1:
                return None
            if r > t0:
                t0 = r
        else:
            if r < t0:
                return None
            if r < t1:
                t1 = r
    return ((x1 + t0 * dx, y1 + t0 * dy), (x1 + t1 * dx, y1 + t1 * dy))


def clip_scene(buildings, roads, areas, H):
    """Clip all geometry to the square defined by the requested radius."""
    b_out = []
    for b in buildings:
        fp = clip_polygon(b["footprint"], H)
        if len(fp) >= 3:
            b2 = dict(b); b2["footprint"] = fp
            b_out.append(b2)

    a_out = []
    for a in areas:
        pg = clip_polygon(a["polygon"], H)
        if len(pg) >= 3:
            a2 = dict(a); a2["polygon"] = pg
            a_out.append(a2)

    r_out = []
    for r in roads:
        path = r["path"]
        for i in range(len(path) - 1):
            seg = clip_segment(path[i], path[i + 1], H)
            if seg:
                r2 = dict(r); r2["path"] = [list(seg[0]), list(seg[1])]
                r_out.append(r2)
    return b_out, r_out, a_out


def bbox_around(lat0, lon0, radius_m):
    dlat = radius_m / 111320.0
    dlon = radius_m / (111320.0 * math.cos(math.radians(lat0)))
    south, north = lat0 - dlat, lat0 + dlat
    west, east = lon0 - dlon, lon0 + dlon
    return south, west, north, east


# ---------------------------------------------------------------------------
# 3) OpenStreetMap parsing, heights, and colors.
# ---------------------------------------------------------------------------

# Base colors by building type (RGB 0..1, sRGB gamma).
BUILDING_COLORS = {
    "house":        (0.87, 0.62, 0.45),  # terracota / adobe
    "detached":     (0.85, 0.67, 0.49),
    "residential":  (0.82, 0.69, 0.53),
    "apartments":   (0.60, 0.69, 0.80),  # azul empolvado
    "commercial":   (0.46, 0.67, 0.66),  # verde azulado
    "retail":       (0.88, 0.57, 0.49),  # coral
    "office":       (0.54, 0.60, 0.76),  # azul pizarra
    "industrial":   (0.68, 0.64, 0.58),
    "warehouse":    (0.68, 0.64, 0.58),
    "hotel":        (0.73, 0.55, 0.71),  # malva
    "church":       (0.90, 0.83, 0.62),  # crema dorado
    "cathedral":    (0.90, 0.83, 0.62),
    "school":       (0.90, 0.68, 0.44),  # naranja calido
    "university":   (0.87, 0.71, 0.50),
    "hospital":     (0.88, 0.75, 0.72),
    "public":       (0.74, 0.72, 0.82),
    "garage":       (0.66, 0.64, 0.60),
    "roof":         (0.70, 0.48, 0.38),
    "obelisk":      (0.86, 0.84, 0.80),  # piedra clara
    "tower":        (0.72, 0.70, 0.68),
    "monument":     (0.84, 0.82, 0.78),
    "_default":     (0.82, 0.72, 0.58),
}

# Conservative material priors used only when OSM has no explicit facade
# colour.  These are surface-class defaults, not location/style presets.
MATERIAL_COLORS = {
    "brick": (0.55, 0.24, 0.14),
    "concrete": (0.62, 0.61, 0.58),
    "cement_block": (0.58, 0.58, 0.56),
    "glass": (0.34, 0.48, 0.56),
    "metal": (0.48, 0.51, 0.53),
    "plaster": (0.82, 0.79, 0.70),
    "render": (0.82, 0.79, 0.70),
    "stone": (0.61, 0.57, 0.50),
    "wood": (0.45, 0.28, 0.16),
}

# Varied palette for buildings without a specific type.
VARIED_NEUTRALS = [
    (0.87, 0.58, 0.46),  # terracota
    (0.90, 0.75, 0.45),  # ocre
    (0.60, 0.73, 0.55),  # salvia
    (0.55, 0.67, 0.80),  # celeste
    (0.83, 0.64, 0.69),  # rosa viejo
    (0.47, 0.69, 0.67),  # verde azulado
    (0.74, 0.68, 0.85),  # lavanda
    (0.91, 0.83, 0.61),  # crema
]


def varied_default(x, y):
    idx = int(abs(round(x * 7.3 + y * 13.7))) % len(VARIED_NEUTRALS)
    return VARIED_NEUTRALS[idx]

# Default heights by type when neither height nor levels are available.
DEFAULT_HEIGHT = {
    "house": 6.0, "detached": 6.0, "garage": 3.0, "roof": 4.0,
    "apartments": 18.0, "residential": 9.0, "commercial": 12.0,
    "retail": 8.0, "office": 20.0, "industrial": 9.0, "warehouse": 9.0,
    "hotel": 22.0, "church": 15.0, "cathedral": 25.0, "hospital": 20.0,
    "school": 9.0, "university": 12.0, "_default": 9.0,
    # Vertical landmarks are built as spires instead of boxes.
    "obelisk": 67.0, "tower": 45.0, "monument": 28.0, "mast": 40.0, "chimney": 35.0,
}

# OSM uses these values for a roofed footprint that is intentionally open
# below.  Treating them as normal buildings creates a large false wall volume
# and hides the very covered area the map is describing.
OPEN_COVER_TYPES = {"roof", "canopy", "carport"}

# Types built as tapered spires or towers instead of roofed boxes.
LANDMARK_TYPES = {"obelisk", "tower", "monument", "mast", "chimney"}

LEVEL_HEIGHT = 3.2  # meters per floor

ROAD_WIDTH = {
    "motorway": 14, "trunk": 12, "primary": 10, "secondary": 8,
    "tertiary": 7, "residential": 5.5, "living_street": 5, "unclassified": 5.5,
    "service": 3.5, "pedestrian": 4, "footway": 2, "path": 1.5,
    "cycleway": 2, "track": 3, "_default": 5,
}
ROAD_COLOR = (0.28, 0.28, 0.30)
PED_COLOR = (0.55, 0.52, 0.48)
RAIL_COLOR = (0.32, 0.24, 0.19)   # rusty-brown railway tracks
BRIDGE_COLOR = (0.42, 0.40, 0.40)  # bridge deck
BRIDGE_Z = 5.0                     # elevated bridge-deck height


def _hex_to_rgb(s):
    s = s.strip().lstrip("#")
    named = {
        "white": (0.9, 0.9, 0.9), "black": (0.1, 0.1, 0.1), "red": (0.7, 0.2, 0.2),
        "blue": (0.3, 0.4, 0.7), "green": (0.3, 0.6, 0.3), "yellow": (0.85, 0.8, 0.4),
        "grey": (0.6, 0.6, 0.6), "gray": (0.6, 0.6, 0.6), "brown": (0.55, 0.4, 0.3),
        "beige": (0.85, 0.8, 0.68), "orange": (0.85, 0.55, 0.3), "sandstone": (0.82, 0.72, 0.55),
    }
    if s.lower() in named:
        return named[s.lower()]
    if re.fullmatch(r"[0-9a-fA-F]{6}", s):
        return tuple(int(s[i:i + 2], 16) / 255.0 for i in (0, 2, 4))
    return None


def structure_mode(tags):
    """Classify building massing without relying on a place or feature name."""
    part = str(tags.get("building:part", "")).strip().lower()
    building = str(tags.get("building", "")).strip().lower()
    if part in OPEN_COVER_TYPES or building in OPEN_COVER_TYPES:
        return "roof_only"
    return "enclosed"


def parse_height(tags):
    """Return (height_m, min_height_m)."""
    h = None
    if "height" in tags:
        m = re.search(r"(-?\d+(?:\.\d+)?)", tags["height"])
        if m:
            h = float(m.group(1))
    if h is None and "building:levels" in tags:
        m = re.search(r"(\d+(?:\.\d+)?)", tags["building:levels"])
        if m:
            h = float(m.group(1)) * LEVEL_HEIGHT
    mode = structure_mode(tags)
    if h is None and mode == "enclosed":
        btype = tags.get("building") or tags.get("building:part", "_default")
        if btype in ("yes", "true", "1"):
            btype = "_default"
        h = DEFAULT_HEIGHT.get(btype, DEFAULT_HEIGHT["_default"])

    min_h = 0.0
    if "min_height" in tags:
        m = re.search(r"(-?\d+(?:\.\d+)?)", tags["min_height"])
        if m:
            min_h = float(m.group(1))
    elif "building:min_level" in tags:
        m = re.search(r"(\d+(?:\.\d+)?)", tags["building:min_level"])
        if m:
            min_h = float(m.group(1)) * LEVEL_HEIGHT
    if mode == "roof_only":
        # In Simple 3D Buildings, height is the roof top and min_height is the
        # clear underside.  Sparse roof/canopy tagging commonly omits one or
        # both, so infer a conservative walkable clearance and thin roof deck.
        if min_h <= 0.0:
            min_h = max(2.2, h - 0.35) if h is not None else 3.0
        if h is None:
            h = min_h + 0.35
        h = max(h, min_h + 0.18)
    else:
        h = max(h, min_h + 2.0)
    return h, min_h


def height_source(tags):
    """Return whether height came from an explicit tag, levels, or a default."""
    if "height" in tags and re.search(r"\d", tags["height"]):
        return "explicit"
    if "building:levels" in tags and re.search(r"\d", tags["building:levels"]):
        return "levels"
    if structure_mode(tags) == "roof_only":
        return "inferred_clearance"
    return "default"


def building_confidence(tags):
    """Estimate building reconstruction confidence from OSM data quality."""
    src = height_source(tags)
    base = {"explicit": 0.9, "levels": 0.75, "default": 0.4,
            "inferred_clearance": 0.45}[src]
    if tags.get("name"):
        base = min(1.0, base + 0.05)
    return round(base, 2)


def building_color(tags):
    """Return the best facade-colour value for compatibility.

    New callers should use :func:`building_appearance` to retain provenance.
    """
    return building_appearance(tags)["color"]


def _numeric_tag(tags, key):
    value = tags.get(key)
    if value in (None, ""):
        return None
    match = re.search(r"(-?\d+(?:\.\d+)?)", str(value))
    return float(match.group(1)) if match else None


def building_appearance(tags):
    """Resolve facade/roof appearance with an explicit source hierarchy.

    Explicit OSM colour wins.  Material and semantic colours are declared
    priors, so downstream renderers and evaluators never confuse them with
    observed facade measurements.
    """
    for key in ("building:colour", "building:color"):
        if key in tags:
            c = _hex_to_rgb(tags[key])
            if c:
                facade_color, facade_source, facade_confidence = c, "osm:" + key, 0.95
                break
    else:
        material = (tags.get("building:material")
                    or tags.get("building:facade:material"))
        material_key = str(material or "").strip().lower().replace(" ", "_")
        if material_key in MATERIAL_COLORS:
            facade_color = MATERIAL_COLORS[material_key]
            facade_source = "material_prior"
            facade_confidence = 0.60
        else:
            btype = tags.get("building") or tags.get("building:part", "_default")
            if btype in ("yes", "true", "1"):
                btype = tags.get("amenity", "_default")
            facade_color = BUILDING_COLORS.get(btype)
            if facade_color is None:
                for semantic_key in ("amenity", "shop", "office", "tourism"):
                    if semantic_key in tags:
                        facade_color = BUILDING_COLORS.get(tags[semantic_key])
                        if facade_color is not None:
                            break
            facade_color = facade_color or BUILDING_COLORS["_default"]
            facade_source = "semantic_prior"
            facade_confidence = 0.40

    roof_color = None
    roof_color_source = None
    roof_color_confidence = None
    for key in ("roof:colour", "roof:color"):
        if key in tags:
            roof_color = _hex_to_rgb(tags[key])
            if roof_color:
                roof_color_source = "osm:" + key
                roof_color_confidence = 0.95
                break

    levels = _numeric_tag(tags, "building:levels")
    roof_levels = _numeric_tag(tags, "roof:levels")
    return {
        "color": facade_color,
        "color_source": facade_source,
        "color_confidence": facade_confidence,
        "building_material": (tags.get("building:material")
                              or tags.get("building:facade:material")),
        "roof_color": roof_color,
        "roof_color_source": roof_color_source,
        "roof_color_confidence": roof_color_confidence,
        "roof_material": tags.get("roof:material"),
        "levels": int(levels) if levels is not None and levels >= 0 else None,
        "roof_levels": int(roof_levels) if roof_levels is not None and roof_levels >= 0 else None,
        "roof_height": _numeric_tag(tags, "roof:height"),
        "roof_orientation": tags.get("roof:orientation"),
        "roof_direction": _numeric_tag(tags, "roof:direction"),
        "building_use": (tags.get("building:use") or tags.get("amenity")
                         or tags.get("office") or tags.get("shop")
                         or tags.get("tourism")),
    }


def build_overpass_query(south, west, north, east):
    b = f"{south},{west},{north},{east}"
    return f"""
[out:json][timeout:60];
(
  way["building"]({b});
  relation["building"]["type"="multipolygon"]({b});
  way["building:part"]({b});
  relation["building:part"]["type"="multipolygon"]({b});
  way["highway"]({b});
  way["railway"~"^(rail|light_rail|subway|tram|narrow_gauge|monorail)$"]({b});
  way["natural"="water"]({b});
  relation["natural"="water"]({b});
  way["waterway"="riverbank"]({b});
  way["leisure"~"park|garden|pitch|playground|stadium"]({b});
  relation["leisure"~"^(pitch|stadium)$"]["type"="multipolygon"]({b});
  way["landuse"~"grass|forest|meadow|orchard|recreation_ground|village_green|residential|allotments|garages"]({b});
  relation["landuse"~"^(residential|allotments|garages)$"]["type"="multipolygon"]({b});
  way["natural"~"wood|scrub|shrubbery|grassland"]({b});
  way["natural"="tree_row"]({b});
  way["barrier"="kerb"]({b});
  node["barrier"="kerb"]({b});
  nwr["traffic_calming"~"^(island|painted_island|table)$"]({b});
  way["area:highway"="traffic_island"]({b});
  relation["area:highway"="traffic_island"]["type"="multipolygon"]({b});
  way["power"~"^(line|minor_line)$"]({b});
  node["power"~"^(pole|tower)$"]({b});
  nwr["power"="substation"]({b});
  node["power"="transformer"]({b});
  node["man_made"="utility_pole"]({b});
  way["communication"="line"]({b});
  way["man_made"="pipeline"]({b});
  node["pipeline"~"^(valve|measurement)$"]({b});
  nwr["man_made"="pumping_station"]({b});
  node["telecom"~"^(distribution_point|connection_point)$"]({b});
  node["man_made"="street_cabinet"]["utility"~"^(power|telecom|water|gas|sewerage|heating)$"]({b});
  node["man_made"="manhole"]({b});
  node["inlet"]({b});
  nwr["road_marking"]({b});
  way["covered"~"^(yes|roof)$"]({b});
  relation["covered"~"^(yes|roof)$"]["type"="multipolygon"]({b});
  nwr["amenity"="shelter"]({b});
  nwr["amenity"~"^(hospital|clinic)$"]({b});
  nwr["healthcare"~"^(hospital|clinic|centre|center)$"]({b});
  node["natural"="tree"]({b});
  node["highway"="street_lamp"]({b});
  node["amenity"~"^(bench|waste_basket|drinking_water|bicycle_parking|post_box|telephone|clock|recycling|fountain|parking_meter|charging_station|vending_machine|parcel_locker|atm)$"]({b});
  node["barrier"~"^(bollard|block|gate|lift_gate|swing_gate)$"]({b});
  way["barrier"~"^(fence|wall|hedge)$"]({b});
  node["emergency"~"^(fire_hydrant|defibrillator)$"]({b});
  node["man_made"~"^(street_cabinet|flagpole|charge_point)$"]({b});
  node["leisure"~"^(picnic_table|fitness_station)$"]({b});
  node["highway"~"^(traffic_signals|bus_stop|crossing)$"]({b});
  node["highway"="elevator"]({b});
  node["public_transport"="platform"]["bus"]({b});
  nwr["traffic_sign"]({b});
  nwr["advertising"]({b});
  nwr["tourism"="information"]({b});
  nwr["tourism"="artwork"]({b});
  nwr["historic"~"^(memorial|monument)$"]({b});
  nwr["playground"]({b});
  way["aeroway"~"^(runway|taxiway|apron|helipad)$"]({b});
  relation["aeroway"="apron"]["type"="multipolygon"]({b});
  nwr["memorial"]({b});
  nwr["man_made"~"^(obelisk|tower|mast|chimney)$"]({b});
  nwr["amenity"="fountain"]({b});
);
out geom;
""".strip()


AIRPORT_LINE_WIDTH = {
    "runway": 45.0,
    # Ten meters prevents untagged taxilanes and gate lead-ins from merging into
    # large patches. Explicit widths on main taxiways are preserved.
    "taxiway": 10.0,
}


def _tag_meters(value, default, minimum=0.5):
    """Parse a simple OSM distance with common metric/imperial units."""
    if value is None:
        return float(default)
    m = re.search(r"(-?\d+(?:\.\d+)?)", str(value))
    if not m:
        return float(default)
    n = float(m.group(1))
    unit_value = str(value).lower()
    if "mm" in unit_value:
        n *= 0.001
    elif "cm" in unit_value:
        n *= 0.01
    elif "ft" in unit_value or "feet" in unit_value or "'" in unit_value:
        n *= 0.3048
    elif "inch" in unit_value or '"' in unit_value:
        n *= 0.0254
    return max(float(minimum), n)


def parse_special_features(data, project):
    """Extract infrastructure that must not degrade into a generic road.

    The first supported family is ``aeroway``: runways and taxiways retain real
    widths, while aprons and helipads remain surfaces. The schema stays generic
    enough for ports, stadiums, and other future layers.
    """
    features = []

    def to_xy(geom):
        return [project(p["lat"], p["lon"]) for p in geom
                if "lat" in p and "lon" in p]

    def add_surface(tags, geom, osm_id=None, osm_type=None):
        pts = to_xy(geom)
        if len(pts) < 4:
            return
        features.append({
            "geometry": "surface",
            "kind": tags.get("aeroway", "surface"),
            "polygon": pts,
            "z": 0.085,
            "name": tags.get("name") or tags.get("ref"),
            "osm_id": osm_id,
            "osm_type": osm_type,
            "source": "osm",
        })

    def add_covered_surface(tags, geom, osm_id=None, osm_type=None):
        """Normalize a non-building covered polygon as an open roof volume."""
        pts = to_xy(geom)
        if len(pts) < 4:
            return
        if math.hypot(pts[0][0] - pts[-1][0], pts[0][1] - pts[-1][1]) > 1.0:
            # covered=yes on an open highway/path describes passage semantics,
            # not a roof footprint. Only closed rings become cover geometry.
            return
        top = _tag_meters(tags.get("height"), 3.35)
        underside = _tag_meters(tags.get("min_height"), max(2.2, top - 0.35))
        top = max(top, underside + 0.18)
        features.append({
            "geometry": "surface",
            "family": "covered_structure",
            "kind": (tags.get("amenity") or tags.get("public_transport")
                     or tags.get("covered") or "canopy"),
            "structure_mode": "roof_only",
            "polygon": pts,
            "height": round(top, 2),
            "min_height": round(underside, 2),
            "height_source": "explicit" if tags.get("height") else "inferred_clearance",
            "name": tags.get("name") or tags.get("ref"),
            "osm_id": osm_id,
            "osm_type": osm_type,
            "source": "osm",
            "detail_source": "procedural_inference",
        })

    def add_point_object(tags, element):
        matched = urban_detail.classify_tags(tags)
        if matched is None:
            return
        family, kind = matched
        if kind == "traffic_sign" and element.get("type") != "node":
            # A sign value on a way/area may encode a regulation, not a mapped
            # physical support. Only explicit physical nodes become geometry.
            return
        if kind in ("stop_line", "power_substation_kiosk") \
                and element.get("type") != "node":
            # Ways/relations have stronger line/surface geometry normalized
            # below. A centroid proxy would duplicate and weaken that evidence.
            return
        if kind == "pedestrian_elevator" and element.get("type") != "node":
            # Open elevator ways are inclined-elevator axes; closed ways are
            # indoor cage outlines. Neither should degrade to a centroid box.
            return
        if kind in ("traffic_island", "painted_island") \
                and tags.get("area:highway") == "traffic_island":
            # The mapped outline below is stronger evidence than a centroid
            # proxy, so never build both representations.
            return
        defaults = urban_detail.normalized_defaults(kind)
        if "lat" in element and "lon" in element:
            xy = project(element["lat"], element["lon"])
        else:
            points = to_xy(element.get("geometry", []))
            if not points:
                return
            xy = (sum(point[0] for point in points) / len(points),
                  sum(point[1] for point in points) / len(points))
        size = urban_detail.parse_size(tags.get("size"))
        item = {
            "geometry": "point",
            "family": family,
            "kind": kind,
            "point": [xy[0], xy[1]],
            "height": round(_tag_meters(
                tags.get("height") or (tags.get("kerb:height")
                                       if kind == "curb_ramp" else None),
                defaults["height"], 0.015 if family == "road_surface" else 0.08), 3),
            "width": round(_tag_meters(tags.get("width"), defaults["width"], 0.05), 2),
            "depth": round(_tag_meters(tags.get("depth"), defaults["depth"], 0.02), 2),
            "min_height": round(_tag_meters(tags.get("min_height"), 0.0, 0.0), 2),
            "direction": urban_detail.parse_bearing(
                tags.get("direction") or tags.get("traffic_sign:direction")),
            "height_source": "explicit" if tags.get("height") else "semantic_default",
            "dimension_source": "explicit_size" if size else (
                "explicit_width" if tags.get("width") else "semantic_default"),
            "name": tags.get("name") or tags.get("ref"),
            "ref": tags.get("ref"),
            "destination": tags.get("destination"),
            "text": tags.get("name") or tags.get("ref") or tags.get("destination"),
            "inscription": tags.get("inscription"),
            "artist_name": tags.get("artist_name"),
            "material": tags.get("material"),
            "support": tags.get("support"),
            "location": tags.get("location"),
            "utility": tags.get("utility"),
            "transformer": tags.get("transformer"),
            "substation": tags.get("substation"),
            "telecom": tags.get("telecom"),
            "telecom_medium": tags.get("telecom:medium"),
            "pipeline": tags.get("pipeline"),
            "substance": tags.get("substance"),
            "diameter": tags.get("diameter"),
            "usage": tags.get("usage"),
            "pressure": tags.get("pressure"),
            "manhole": tags.get("manhole"),
            "inlet": tags.get("inlet"),
            "shape": tags.get("shape"),
            "colour": tags.get("colour"),
            "road_marking": tags.get("road_marking"),
            "stroke": tags.get("stroke"),
            "sides": tags.get("sides"),
            "lit": tags.get("lit"),
            "luminous": tags.get("luminous"),
            "shelter": tags.get("shelter"),
            "bench": tags.get("bench"),
            "bin": tags.get("bin"),
            "passenger_information_display": tags.get("passenger_information_display"),
            "departures_board": tags.get("departures_board"),
            "tactile_paving": tags.get("tactile_paving"),
            "crossing": tags.get("crossing"),
            "crossing_markings": tags.get("crossing:markings"),
            "crossing_markings_colour": tags.get("crossing:markings:colour"),
            "kerb": tags.get("kerb"),
            "kerb_height": tags.get("kerb:height"),
            "wheelchair": tags.get("wheelchair"),
            "incline": tags.get("incline"),
            "surface": tags.get("surface"),
            "traffic_calming": tags.get("traffic_calming"),
            "crossing_continuous": tags.get("crossing:continuous"),
            "level": tags.get("level"),
            "door_width": tags.get("door:width"),
            "door_height": tags.get("door:height"),
            "length": tags.get("length"),
            "goods": tags.get("goods"),
            "bicycle": tags.get("bicycle"),
            "handrail": tags.get("handrail"),
            "crossing_island": tags.get("crossing:island"),
            "traffic_sign": tags.get("traffic_sign"),
            "maxspeed": tags.get("maxspeed"),
            "maxheight": tags.get("maxheight"),
            "maxweight": tags.get("maxweight"),
            "maxwidth": tags.get("maxwidth"),
            "overtaking": tags.get("overtaking"),
            "hazard": tags.get("hazard"),
            "message": tags.get("message"),
            "vending": tags.get("vending"),
            "capacity": tags.get("capacity"),
            "fitness_station": tags.get("fitness_station"),
            "design": tags.get("design"),
            "cables": tags.get("cables"),
            "wires": tags.get("wires"),
            "voltage": tags.get("voltage"),
            "size": tags.get("size"),
            "source_tag": next((f"{key}={tags[key]}" for key in (
                "traffic_sign", "advertising", "information", "artwork_type",
                "memorial", "historic", "amenity", "playground", "emergency",
                "man_made", "highway", "traffic_calming", "power",
                "road_marking", "telecom", "pipeline", "substance", "kerb",
                "traffic_calming")
                if tags.get(key)), None),
            "osm_id": element.get("id"),
            "osm_type": element.get("type"),
            "source": "osm",
            "detail_source": "procedural_inference",
        }
        if size:
            item["panel_size"] = [size[0], size[1]]
            item["panel_width"], item["panel_height"] = size
        features.append(item)

    for el in data.get("elements", []):
        tags = el.get("tags", {}) or {}
        kind = tags.get("aeroway")
        etype = el.get("type")
        add_point_object(tags, el)
        if etype == "way" and tags.get("road_marking") in \
                ("stop_line", "lane_divider") and el.get("geometry"):
            path = to_xy(el["geometry"])
            if len(path) >= 2:
                marking_kind = str(tags["road_marking"])
                features.append({
                    "geometry": "line", "family": "road_surface",
                    "kind": marking_kind, "path": path,
                    "width": round(_tag_meters(tags.get("width"),
                                                0.42 if marking_kind == "stop_line" else 0.14,
                                                0.03), 3),
                    "stroke": tags.get("stroke") or "solid",
                    "colour": tags.get("colour"),
                    "direction": tags.get("direction"),
                    "osm_id": el.get("id"), "osm_type": etype,
                    "source": "osm", "detail_source": "mapped_marking_axis",
                })
        if (etype == "way" and tags.get("barrier") in ("fence", "wall", "hedge")
                and el.get("geometry")):
            path = to_xy(el["geometry"])
            if len(path) >= 2:
                kind_defaults = {
                    "fence": (1.5, 0.08), "wall": (1.8, 0.25),
                    "hedge": (1.4, 0.60),
                }
                default_h, default_w = kind_defaults[tags["barrier"]]
                features.append({
                    "geometry": "line", "family": "residential_boundary",
                    "kind": tags["barrier"], "path": path,
                    "height": round(_tag_meters(tags.get("height"), default_h, 0.15), 2),
                    "width": round(_tag_meters(tags.get("width"), default_w, 0.04), 2),
                    "height_source": "explicit" if tags.get("height") else "semantic_default",
                    "name": tags.get("name"), "osm_id": el.get("id"),
                    "osm_type": etype, "source": "osm",
                    "detail_source": "procedural_inference",
                })
        if etype == "way" and tags.get("barrier") == "kerb" and el.get("geometry"):
            path = to_xy(el["geometry"])
            if len(path) >= 2:
                kerb_kind = str(tags.get("kerb") or "regular").lower()
                default_height = 0.0 if kerb_kind in ("flush", "lowered") else 0.12
                features.append({
                    "geometry": "line", "family": "road_surface", "kind": "kerb",
                    "path": path, "height": round(_tag_meters(
                        tags.get("height") or tags.get("kerb:height"), default_height, 0.0), 3),
                    "width": round(_tag_meters(tags.get("width"), 0.22, 0.05), 2),
                    "kerb": kerb_kind, "surface": tags.get("surface"),
                    "osm_id": el.get("id"), "osm_type": etype, "source": "osm",
                    "detail_source": "mapped_axis+semantic_profile",
                })
        if etype == "way" and tags.get("natural") == "tree_row" and el.get("geometry"):
            path = to_xy(el["geometry"])
            if len(path) >= 2:
                features.append({
                    "geometry": "line", "family": "vegetation", "kind": "tree_row",
                    "path": path,
                    "height": round(_tag_meters(tags.get("height"), 7.5, 0.5), 2),
                    "tree_spacing": round(_tag_meters(tags.get("tree_spacing"), 7.0, 1.5), 2),
                    "leaf_type": tags.get("leaf_type"), "leaf_cycle": tags.get("leaf_cycle"),
                    "osm_id": el.get("id"), "osm_type": etype, "source": "osm",
                    "detail_source": "mapped_row_axis+procedural_instances",
                })
        if etype == "way" and tags.get("highway") in ("steps", "footway", "path", "elevator") \
                and el.get("geometry"):
            is_steps = tags.get("highway") == "steps"
            is_elevator = tags.get("highway") == "elevator"
            conveying = str(tags.get("conveying") or "").lower()
            is_moving = conveying in ("yes", "forward", "backward", "reversible")
            is_ramp = (tags.get("highway") in ("footway", "path")
                       and tags.get("incline") not in (None, "", "0", "0%")
                       and str(tags.get("wheelchair") or "").lower() in
                       ("yes", "designated", "limited"))
            if is_steps or is_elevator or is_moving or is_ramp:
                path = to_xy(el["geometry"])
                if len(path) >= 2:
                    kind = ("inclined_elevator" if is_elevator else
                            "escalator" if is_steps and is_moving else
                            "moving_walkway" if is_moving else
                            "steps" if is_steps else "pedestrian_ramp")
                    features.append({
                        "geometry": "line", "family": "pedestrian_access",
                        "kind": kind, "path": path,
                        "width": tags.get("width"),
                        "incline": tags.get("incline"),
                        "step_count": tags.get("step_count"),
                        "step_height": tags.get("step:height"),
                        "conveying": tags.get("conveying"),
                        "ramp": tags.get("ramp"),
                        "ramp_wheelchair": tags.get("ramp:wheelchair"),
                        "ramp_bicycle": tags.get("ramp:bicycle"),
                        "ramp_stroller": tags.get("ramp:stroller"),
                        "handrail": tags.get("handrail"),
                        "handrail_left": tags.get("handrail:left"),
                        "handrail_right": tags.get("handrail:right"),
                        "handrail_center": tags.get("handrail:center"),
                        "wheelchair": tags.get("wheelchair"),
                        "surface": tags.get("surface"),
                        "level": tags.get("level"),
                        "osm_id": el.get("id"), "osm_type": etype,
                        "source": "osm", "detail_source": "mapped_access_axis",
                    })
        if etype == "way" and tags.get("power") in ("line", "minor_line") \
                and el.get("geometry"):
            path = to_xy(el["geometry"])
            if len(path) >= 2:
                features.append({
                    "geometry": "line", "family": "utility_network",
                    "kind": "overhead_power_line", "power": tags.get("power"),
                    "path": path, "height": _numeric_tag(tags, "height"),
                    "cables": tags.get("cables"), "wires": tags.get("wires"),
                    "voltage": tags.get("voltage"), "circuits": tags.get("circuits"),
                    "osm_id": el.get("id"), "osm_type": etype, "source": "osm",
                    "detail_source": "mapped_axis+procedural_conductor_proxy",
                })
        if etype == "way" and tags.get("communication") == "line" \
                and el.get("geometry"):
            path = to_xy(el["geometry"])
            if len(path) >= 2:
                features.append({
                    "geometry": "line", "family": "utility_network",
                    "kind": "communication_line", "path": path,
                    "location": tags.get("location"),
                    "height": _numeric_tag(tags, "height"),
                    "cables": tags.get("cables"),
                    "telecom_medium": tags.get("telecom:medium"),
                    "operator": tags.get("operator"),
                    "osm_id": el.get("id"), "osm_type": etype,
                    "source": "osm", "detail_source": "mapped_communication_axis",
                })
        if etype == "way" and tags.get("man_made") == "pipeline" \
                and el.get("geometry"):
            path = to_xy(el["geometry"])
            if len(path) >= 2:
                features.append({
                    "geometry": "line", "family": "fluid_network",
                    "kind": "pipeline", "path": path,
                    "location": tags.get("location"),
                    "height": _numeric_tag(tags, "height"),
                    "diameter": tags.get("diameter"),
                    "substance": tags.get("substance"),
                    "usage": tags.get("usage"),
                    "pressure": tags.get("pressure"),
                    "operator": tags.get("operator"),
                    "osm_id": el.get("id"), "osm_type": etype,
                    "source": "osm", "detail_source": "mapped_pipeline_axis",
                })
        if etype == "way" and tags.get("power") == "substation" \
                and el.get("geometry"):
            polygon = to_xy(el["geometry"])
            if len(polygon) >= 4:
                features.append({
                    "geometry": "surface", "family": "utility_network",
                    "kind": "power_substation", "polygon": polygon,
                    "substation": tags.get("substation"),
                    "location": tags.get("location") or "outdoor",
                    "voltage": tags.get("voltage"),
                    "barrier": tags.get("barrier"),
                    "osm_id": el.get("id"), "osm_type": etype,
                    "source": "osm", "detail_source": "mapped_facility_outline",
                })
        elif etype == "relation" and tags.get("power") == "substation":
            for member in el.get("members", []):
                if member.get("role") == "outer" and member.get("geometry"):
                    polygon = to_xy(member["geometry"])
                    if len(polygon) >= 4:
                        features.append({
                            "geometry": "surface", "family": "utility_network",
                            "kind": "power_substation", "polygon": polygon,
                            "substation": tags.get("substation"),
                            "location": tags.get("location") or "outdoor",
                            "voltage": tags.get("voltage"),
                            "barrier": tags.get("barrier"),
                            "osm_id": el.get("id"), "osm_type": etype,
                            "source": "osm", "detail_source": "mapped_facility_outline",
                        })
        if etype == "way" and tags.get("area:highway") == "traffic_island" \
                and el.get("geometry"):
            polygon = to_xy(el["geometry"])
            if len(polygon) >= 4:
                features.append({
                    "geometry": "surface", "family": "road_surface",
                    "kind": "traffic_island", "polygon": polygon,
                    "height": round(_tag_meters(tags.get("height"), 0.18, 0.02), 2),
                    "surface": tags.get("surface"), "kerb": tags.get("kerb"),
                    "osm_id": el.get("id"), "osm_type": etype, "source": "osm",
                    "detail_source": "mapped_outline",
                })
        elif etype == "relation" and tags.get("area:highway") == "traffic_island":
            for member in el.get("members", []):
                if member.get("role") == "outer" and member.get("geometry"):
                    polygon = to_xy(member["geometry"])
                    if len(polygon) >= 4:
                        features.append({
                            "geometry": "surface", "family": "road_surface",
                            "kind": "traffic_island", "polygon": polygon,
                            "height": round(_tag_meters(tags.get("height"), 0.18, 0.02), 2),
                            "surface": tags.get("surface"), "kerb": tags.get("kerb"),
                            "osm_id": el.get("id"), "osm_type": etype,
                            "source": "osm", "detail_source": "mapped_outline",
                        })
        is_nonbuilding_cover = (tags.get("covered") in ("yes", "roof")
                                or tags.get("amenity") == "shelter") \
            and "building" not in tags and "building:part" not in tags
        if is_nonbuilding_cover:
            if etype == "way" and el.get("geometry"):
                add_covered_surface(tags, el["geometry"], el.get("id"), etype)
            elif etype == "relation":
                for mem in el.get("members", []):
                    if mem.get("role") == "outer" and mem.get("geometry"):
                        add_covered_surface(tags, mem["geometry"], el.get("id"), etype)
        if kind in AIRPORT_LINE_WIDTH and etype == "way" and el.get("geometry"):
            pts = to_xy(el["geometry"])
            if len(pts) >= 2:
                features.append({
                    "geometry": "line",
                    "kind": kind,
                    "path": pts,
                    "width": round(_tag_meters(tags.get("width"),
                                                AIRPORT_LINE_WIDTH[kind]), 2),
                    "z": 0.09 if kind == "runway" else 0.095,
                    "name": tags.get("name") or tags.get("ref"),
                    "surface": tags.get("surface"),
                    "osm_id": el.get("id"),
                    "osm_type": etype,
                    "source": "osm",
                })
        elif kind in ("apron", "helipad"):
            if etype == "way" and el.get("geometry"):
                add_surface(tags, el["geometry"], el.get("id"), etype)
            elif etype == "relation":
                for mem in el.get("members", []):
                    if mem.get("role") == "outer" and mem.get("geometry"):
                        add_surface(tags, mem["geometry"], el.get("id"), etype)

        # Generic landmarks get identity from tags, never from a hard-coded name or
        # embedded coordinates in core code.
        landmark_kind = None
        if tags.get("man_made") in ("tower", "mast", "chimney"):
            landmark_kind = tags["man_made"]
        if landmark_kind:
            xy = None
            if etype == "node" and "lat" in el and "lon" in el:
                xy = project(el["lat"], el["lon"])
            elif el.get("geometry"):
                points = to_xy(el["geometry"])
                if points:
                    xy = (sum(p[0] for p in points) / len(points),
                          sum(p[1] for p in points) / len(points))
            if xy is not None:
                default_h = {"tower": 45.0, "mast": 40.0,
                             "chimney": 35.0}[landmark_kind]
                features.append({
                    "geometry": "point",
                    "family": "landmark",
                    "kind": landmark_kind,
                    "point": [xy[0], xy[1]],
                    "height": round(_tag_meters(tags.get("height"), default_h), 2),
                    "width": round(_tag_meters(tags.get("width"), 6.0), 2),
                    "height_source": "explicit" if tags.get("height") else "default",
                    "name": tags.get("name"),
                    "osm_id": el.get("id"),
                    "osm_type": etype,
                    "source": "osm",
                })
    # Overpass may return the same apron as a tagged way and as a multipolygon
    # outer ring. Deduplication prevents coplanar faces and z-fighting.
    deduped, seen = [], set()
    for feature in features:
        if feature.get("geometry") == "surface":
            pts = feature.get("polygon", [])
            area = abs(sum(
                pts[i][0] * pts[(i + 1) % len(pts)][1] -
                pts[(i + 1) % len(pts)][0] * pts[i][1]
                for i in range(len(pts))
            )) * 0.5 if len(pts) >= 3 else 0.0
            cx = sum(p[0] for p in pts) / max(1, len(pts))
            cy = sum(p[1] for p in pts) / max(1, len(pts))
            key = (feature.get("kind"), "surface",
                   round(cx, 1), round(cy, 1), round(area, 0))
        elif feature.get("geometry") == "point":
            point = feature.get("point", [0, 0])
            key = (feature.get("kind"), "point", round(point[0], 1),
                   round(point[1], 1), feature.get("osm_id"))
        else:
            key = (feature.get("kind"), "line", feature.get("osm_id"))
        if key not in seen:
            seen.add(key)
            deduped.append(feature)
    return deduped


def clip_special_features(features, H):
    """Clip special lines and surfaces to the same boundary as the scene."""
    out = []
    for feature in features:
        if feature.get("geometry") == "surface":
            polygon = clip_polygon(feature.get("polygon", []), H)
            if len(polygon) >= 3:
                item = dict(feature)
                item["polygon"] = polygon
                out.append(item)
        elif feature.get("geometry") == "line":
            path = feature.get("path", [])
            for i in range(len(path) - 1):
                segment = clip_segment(path[i], path[i + 1], H)
                if segment:
                    item = dict(feature)
                    item["path"] = [list(segment[0]), list(segment[1])]
                    out.append(item)
        elif feature.get("geometry") == "point":
            x, y = feature.get("point", (0.0, 0.0))
            if -H <= x <= H and -H <= y <= H:
                out.append(dict(feature))
    return out


def classify_scene_specializations(osm):
    """Return every semantic specialization present in an OSM response."""
    tags = [(el.get("tags") or {}) for el in osm.get("elements", [])]
    aeroways = {item.get("aeroway") for item in tags}
    result = []
    if aeroways & {"runway", "taxiway", "apron", "aerodrome"}:
        result.append("airport")
    stadium = any(
        item.get("leisure") == "stadium"
        or item.get("building") in ("stadium", "grandstand")
        or item.get("building:part") == "grandstand"
        for item in tags)
    football = any(
        str(item.get("sport", "")).lower() in ("soccer", "football", "futsal")
        and item.get("leisure") in ("stadium", "pitch")
        for item in tags)
    if stadium and football:
        result.append("football_stadium")
    elif stadium:
        result.append("stadium")
    hospital = any(
        str(item.get("amenity", "")).lower() in ("hospital", "clinic")
        or str(item.get("healthcare", "")).lower() in (
            "hospital", "clinic", "centre", "center")
        or str(item.get("building", "")).lower() == "hospital"
        for item in tags)
    if hospital:
        result.append("hospital")
    if any(str(item.get("highway", "")).lower() in (
            "motorway", "motorway_link", "trunk", "trunk_link") for item in tags):
        result.append("highway")
    if any(item.get("landuse") == "residential" or str(item.get("building", "")).lower()
           in ("house", "detached", "semidetached_house", "terrace", "bungalow",
               "apartments", "residential", "dormitory") for item in tags):
        result.append("residential_neighborhood")
    urban_families = {matched[0] for item in tags
                      for matched in [urban_detail.classify_tags(item)] if matched}
    if urban_families & {"signage", "transit"}:
        result.append("signage_wayfinding")
    if "public_art" in urban_families:
        result.append("monuments_public_art")
    if urban_families & {"street_furniture", "vegetation", "recreation"}:
        result.append("urban_amenities")
    if any(
            item.get("barrier") == "kerb"
            or item.get("traffic_calming") in ("island", "painted_island")
            or item.get("traffic_calming") == "table"
            or item.get("highway") in ("steps", "elevator")
            or item.get("conveying") in ("yes", "forward", "backward", "reversible")
            or item.get("area:highway") == "traffic_island"
            or item.get("natural") in ("tree_row", "wood", "scrub", "shrubbery")
            or item.get("landuse") in ("forest", "orchard")
            or item.get("power") in (
                "line", "minor_line", "pole", "tower", "substation", "transformer")
            or item.get("road_marking") in ("stop_line", "lane_divider")
            or item.get("communication") == "line"
            or item.get("man_made") in ("pipeline", "pumping_station")
            or item.get("pipeline") in ("valve", "measurement")
            or (item.get("man_made") in ("utility_pole", "street_cabinet")
                and item.get("utility") in ("power", "telecom"))
            or item.get("cycleway") == "lane"
            or any(item.get(key) == "lane" for key in (
                "cycleway:left", "cycleway:right", "cycleway:both"))
            or any(key in item for key in (
                "turn:lanes", "turn:lanes:forward", "turn:lanes:backward",
                "bus:lanes", "bus:lanes:forward", "bus:lanes:backward",
                "parking:left", "parking:right", "parking:both",
                "sidewalk", "sidewalk:left", "sidewalk:right", "sidewalk:both"))
            for item in tags):
        result.append("streetscape_infrastructure")
    if any("building" in item or "building:part" in item for item in tags):
        result.append("architectural_buildings")
    return result


def classify_scene_kind(osm, label=""):
    """Choose a primary scene kind while retaining all specializations elsewhere."""
    specializations = classify_scene_specializations(osm)
    for kind in ("airport", "football_stadium", "stadium", "hospital", "highway"):
        if kind in specializations:
            return kind
    return "urban"


def fetch_overpass(query):
    # Local disk cache avoids repeated Overpass requests for identical runs.
    # Degrade silently when citycache is unavailable.
    ckey = _cache = None
    try:
        import citycache as _cache
        ckey = _cache.key_hash(query)
        hit = _cache.get(ckey)
        if hit:
            print("   (Overpass: response loaded from local cache)")
            return json.loads(hit)
    except Exception:
        _cache = ckey = None

    last_err = None
    for endpoint in OVERPASS_ENDPOINTS:
        try:
            r = requests.post(
                endpoint, data={"data": query},
                headers={"User-Agent": USER_AGENT}, timeout=90,
            )
            if r.status_code == 200:
                if ckey and _cache:
                    try:
                        _cache.put(ckey, r.text)
                    except Exception:
                        pass
                return r.json()
            last_err = f"HTTP {r.status_code} at {endpoint}"
            print(f"   (Overpass {last_err}; trying another server...)")
        except requests.RequestException as e:
            last_err = f"{type(e).__name__} at {endpoint}"
            print(f"   (Overpass failed at {endpoint}; trying another server...)")
    raise SystemExit(
        f"Could not query Overpass/OSM ({last_err}). Public OSM servers may be "
        "overloaded; retry later or provide another endpoint."
    )


def merge_overpass_results(results):
    """Merge sharded Overpass responses without duplicating OSM elements."""
    merged = {}
    for result in results:
        for element in result.get("elements", []):
            key = (element.get("type"), element.get("id"))
            previous = merged.get(key)
            if previous is None:
                merged[key] = element
                continue
            # Boundary features can appear in adjacent shards. Prefer the copy
            # carrying more geometry/members, while keeping stable identity.
            previous_size = len(previous.get("geometry", [])) + len(previous.get("members", []))
            candidate_size = len(element.get("geometry", [])) + len(element.get("members", []))
            if candidate_size > previous_size:
                merged[key] = element
    return {"elements": list(merged.values())}


def osm_xml_to_overpass(xml_bytes):
    """Convert the official OSM map API XML into the normalized parser shape."""
    root = ET.fromstring(xml_bytes)
    nodes = {}
    tagged_nodes = []
    for node in root.findall("node"):
        item = {
            "type": "node", "id": int(node.attrib["id"]),
            "lat": float(node.attrib["lat"]), "lon": float(node.attrib["lon"]),
        }
        tags = {tag.attrib["k"]: tag.attrib["v"] for tag in node.findall("tag")}
        if tags:
            item["tags"] = tags
            tagged_nodes.append(item)
        nodes[item["id"]] = item

    ways = {}
    tagged_ways = []
    for way in root.findall("way"):
        refs = [int(nd.attrib["ref"]) for nd in way.findall("nd")]
        tags = {tag.attrib["k"]: tag.attrib["v"] for tag in way.findall("tag")}
        item = {"type": "way", "id": int(way.attrib["id"]), "tags": tags,
                "geometry": [
                    {"lat": nodes[ref]["lat"], "lon": nodes[ref]["lon"]}
                    for ref in refs if ref in nodes
                ]}
        ways[item["id"]] = item
        if tags:
            tagged_ways.append(item)

    relations = []
    for relation in root.findall("relation"):
        tags = {tag.attrib["k"]: tag.attrib["v"] for tag in relation.findall("tag")}
        if not tags:
            continue
        members = []
        for member in relation.findall("member"):
            kind = member.attrib.get("type")
            ref = int(member.attrib["ref"])
            entry = {"type": kind, "ref": ref,
                     "role": member.attrib.get("role", "")}
            if kind == "way" and ref in ways:
                entry["geometry"] = ways[ref].get("geometry", [])
            members.append(entry)
        relations.append({"type": "relation", "id": int(relation.attrib["id"]),
                          "tags": tags, "members": members})
    return {"elements": tagged_nodes + tagged_ways + relations}


def fetch_osm_map_bbox(south, west, north, east, depth=0, max_depth=3):
    """Fetch official OSM map XML, subdividing when the 50k-node limit fires."""
    bbox = f"{west},{south},{east},{north}"
    response = requests.get("https://api.openstreetmap.org/api/0.6/map",
                            params={"bbox": bbox},
                            headers={"User-Agent": USER_AGENT}, timeout=120)
    too_many = response.status_code == 400 and b"too many nodes" in response.content.lower()
    if too_many and depth < max_depth:
        mid_lat = (south + north) * 0.5
        mid_lon = (west + east) * 0.5
        boxes = (
            (south, west, mid_lat, mid_lon),
            (south, mid_lon, mid_lat, east),
            (mid_lat, west, north, mid_lon),
            (mid_lat, mid_lon, north, east),
        )
        print(f"   (OSM map API node limit at depth {depth}; subdividing)")
        return merge_overpass_results([
            fetch_osm_map_bbox(*box, depth=depth + 1, max_depth=max_depth)
            for box in boxes
        ])
    response.raise_for_status()
    return osm_xml_to_overpass(response.content)


def fetch_overpass_bbox(south, west, north, east):
    """Fetch one bbox, falling back to four deduplicated quadrants on overload."""
    force_map_api = os.environ.get("MAPS3D_OSM_MAP_API", "").lower() in (
        "1", "true", "yes", "on")
    if force_map_api:
        print("   (official OSM map API forced by MAPS3D_OSM_MAP_API)")
        return fetch_osm_map_bbox(south, west, north, east)
    force_shards = os.environ.get("MAPS3D_OVERPASS_SHARDS", "").lower() in (
        "1", "true", "yes", "on")
    if not force_shards:
        try:
            return fetch_overpass(build_overpass_query(south, west, north, east))
        except SystemExit as full_error:
            print(f"   (full Overpass bbox failed: {full_error}; retrying four quadrants)")
    else:
        print("   (Overpass sharding forced by MAPS3D_OVERPASS_SHARDS)")
    mid_lat = (south + north) * 0.5
    mid_lon = (west + east) * 0.5
    boxes = (
        (south, west, mid_lat, mid_lon),
        (south, mid_lon, mid_lat, east),
        (mid_lat, west, north, mid_lon),
        (mid_lat, mid_lon, north, east),
    )
    shards = []
    try:
        for index, bbox in enumerate(boxes, 1):
            print(f"   (Overpass quadrant {index}/4)")
            shards.append(fetch_overpass(build_overpass_query(*bbox)))
        return merge_overpass_results(shards)
    except SystemExit as shard_error:
        print(f"   (Overpass quadrants failed: {shard_error}; using official OSM map API)")
        return fetch_osm_map_bbox(south, west, north, east)


def _ring_from_geometry(geom):
    return [(p["lon"], p["lat"]) for p in geom if "lat" in p and "lon" in p]


def _point_in_polygon(point, polygon):
    """Return whether a point is inside a polygon using an identity-free ray cast."""
    if len(polygon) < 3:
        return False
    x, y = point
    inside = False
    previous = polygon[-1]
    for current in polygon:
        x1, y1 = previous
        x2, y2 = current
        if ((y1 > y) != (y2 > y)):
            crossing = (x2 - x1) * (y - y1) / ((y2 - y1) or 1e-12) + x1
            if x < crossing:
                inside = not inside
        previous = current
    return inside


def resolve_building_parts(buildings):
    """Suppress 3D outlines covered by ``building:part`` geometry.

    OSM Simple 3D Buildings defines the outline as a 2D/backward-compatible
    envelope when parts exist. Rendering both produces duplicate walls and
    destroys stepped massing. Matching is purely geometric; no identity or
    place-name rule is involved. The largest grounded part becomes the detail
    anchor so inferred entrances are not repeated on every volume.
    """
    outlines = [item for item in buildings if not item.get("is_building_part")]
    parts = [item for item in buildings if item.get("is_building_part")]
    if not parts:
        for outline in outlines:
            outline["detail_anchor"] = True
        return buildings, 0

    suppressed = set()
    claimed_parts = set()
    for outline in outlines:
        polygon = outline.get("footprint", [])
        if len(polygon) < 3:
            continue
        minx = min(p[0] for p in polygon)
        maxx = max(p[0] for p in polygon)
        miny = min(p[1] for p in polygon)
        maxy = max(p[1] for p in polygon)
        contained = []
        for part_index, part in enumerate(parts):
            ring = part.get("footprint", [])
            if len(ring) < 3:
                continue
            center = (sum(p[0] for p in ring) / len(ring),
                      sum(p[1] for p in ring) / len(ring))
            if not (minx <= center[0] <= maxx and miny <= center[1] <= maxy):
                continue
            inside_vertices = sum(_point_in_polygon(point, polygon) for point in ring)
            if (_point_in_polygon(center, polygon)
                    or inside_vertices >= max(1, math.ceil(len(ring) * 0.5))):
                contained.append((part_index, part))
        if not contained:
            outline["detail_anchor"] = True
            continue
        suppressed.add(id(outline))
        grounded = [(index, part) for index, part in contained
                    if float(part.get("min_height", 0.0)) <= 0.15
                    and str(part.get("building_part", "")).lower() != "roof"]
        candidates = grounded or contained
        _, anchor = max(
            candidates,
            key=lambda pair: abs(sum(
                pair[1]["footprint"][i][0] * pair[1]["footprint"][(i + 1) % len(pair[1]["footprint"])][1]
                - pair[1]["footprint"][(i + 1) % len(pair[1]["footprint"])][0]
                * pair[1]["footprint"][i][1]
                for i in range(len(pair[1]["footprint"])))))
        anchor["detail_anchor"] = True
        for part_index, part in contained:
            claimed_parts.add(part_index)
            part["outline_osm_id"] = outline.get("osm_id")

    for part_index, part in enumerate(parts):
        if part_index not in claimed_parts:
            part["detail_anchor"] = float(part.get("min_height", 0.0)) <= 0.15
    return [item for item in buildings if id(item) not in suppressed], len(suppressed)


def parse_osm(data, project):
    """Convert an Overpass response into a scene dictionary in local meters."""
    buildings, roads, areas = [], [], []

    def to_xy(ring_lonlat):
        return [project(lat, lon) for (lon, lat) in ring_lonlat]

    def add_building(tags, ring_lonlat, osm_id=None, osm_type=None):
        pts = to_xy(ring_lonlat)
        if len(pts) < 4:  # closed ring: at least three unique points plus repeat
            return
        h, min_h = parse_height(tags)
        appearance = building_appearance(tags)
        color = appearance["color"]
        if appearance["color_source"] == "semantic_prior" and \
                tuple(round(c, 3) for c in color) == tuple(round(c, 3) for c in BUILDING_COLORS["_default"]):
            color = varied_default(pts[0][0], pts[0][1])  # varied warm tone
            appearance["color_source"] = "deterministic_prior"
            appearance["color_confidence"] = 0.30
        buildings.append({
            "footprint": pts,
            "height": round(h, 2),
            "min_height": round(min_h, 2),
            "color": [round(c, 3) for c in color],
            "type": tags.get("building") or tags.get("building:part", "yes"),
            "structure_mode": structure_mode(tags),
            "covered": (tags.get("covered") in ("yes", "roof")
                        or structure_mode(tags) == "roof_only"),
            "is_building_part": "building:part" in tags,
            "building_part": tags.get("building:part"),
            # --- F2a: per-building provenance and confidence ---
            "osm_id": osm_id,
            "osm_type": osm_type,
            "name": tags.get("name"),
            "roof_shape": tags.get("roof:shape"),
            "roof_angle": _numeric_tag(tags, "roof:angle"),
            "min_level": _numeric_tag(tags, "building:min_level"),
            "layer": _numeric_tag(tags, "layer"),
            "height_source": height_source(tags),
            "confidence": building_confidence(tags),
            "source": "osm",
            **{key: value for key, value in appearance.items()
               if key != "color" and value is not None},
        })

    def add_road(tags, ring_lonlat):
        pts = to_xy(ring_lonlat)
        if len(pts) < 2:
            return
        is_bridge = tags.get("bridge") in ("yes", "viaduct", "true", "1")
        if "railway" in tags:
            width, color, rtype, z = 4.5, RAIL_COLOR, "rail:" + tags["railway"], 0.05
        else:
            hw = tags.get("highway", "_default")
            default_width = ROAD_WIDTH.get(hw, ROAD_WIDTH["_default"])
            width = _tag_meters(tags.get("width"), default_width)
            color = PED_COLOR if hw in ("footway", "path", "pedestrian", "cycleway", "track") else ROAD_COLOR
            rtype, z = hw, 0.06
        if is_bridge:
            z = BRIDGE_Z                       # elevate the bridge deck
            color = BRIDGE_COLOR
            width = max(width, 8.0)
        roads.append({
            "path": pts, "width": width, "color": list(color), "type": rtype, "z": z,
            "osm_id": tags.get("_osm_id"), "osm_type": tags.get("_osm_type"),
            "lanes": _numeric_tag(tags, "lanes"),
            "oneway": tags.get("oneway"), "bridge": is_bridge,
            "tunnel": tags.get("tunnel") in ("yes", "true", "1"),
            "layer": _numeric_tag(tags, "layer"), "surface": tags.get("surface"),
            "ref": tags.get("ref"), "name": tags.get("name"),
            "maxspeed": tags.get("maxspeed"), "lit": tags.get("lit"),
            "turn_lanes": tags.get("turn:lanes"),
            "turn_lanes_forward": tags.get("turn:lanes:forward"),
            "turn_lanes_backward": tags.get("turn:lanes:backward"),
            "lane_markings": tags.get("lane_markings"),
            "placement": tags.get("placement"),
            "cycleway": tags.get("cycleway"),
            "cycleway_left": tags.get("cycleway:left"),
            "cycleway_right": tags.get("cycleway:right"),
            "cycleway_both": tags.get("cycleway:both"),
            "cycleway_width": tags.get("cycleway:width"),
            "cycleway_left_width": tags.get("cycleway:left:width"),
            "cycleway_right_width": tags.get("cycleway:right:width"),
            "cycleway_buffer": tags.get("cycleway:buffer"),
            "cycleway_both_buffer": tags.get("cycleway:both:buffer"),
            "cycleway_left_buffer": tags.get("cycleway:left:buffer"),
            "cycleway_right_buffer": tags.get("cycleway:right:buffer"),
            "cycleway_separation": tags.get("cycleway:separation"),
            "cycleway_both_separation": tags.get("cycleway:both:separation"),
            "cycleway_left_separation": tags.get("cycleway:left:separation"),
            "cycleway_right_separation": tags.get("cycleway:right:separation"),
            "bus_lanes": tags.get("bus:lanes"),
            "bus_lanes_forward": tags.get("bus:lanes:forward"),
            "bus_lanes_backward": tags.get("bus:lanes:backward"),
            "psv_lanes": tags.get("psv:lanes"),
            "psv_lanes_forward": tags.get("psv:lanes:forward"),
            "psv_lanes_backward": tags.get("psv:lanes:backward"),
            "lanes_bus": tags.get("lanes:bus"),
            "lanes_psv": tags.get("lanes:psv"),
            "parking_left": tags.get("parking:left"),
            "parking_right": tags.get("parking:right"),
            "parking_both": tags.get("parking:both"),
            "parking_left_orientation": tags.get("parking:left:orientation"),
            "parking_right_orientation": tags.get("parking:right:orientation"),
            "parking_both_orientation": tags.get("parking:both:orientation"),
            "parking_left_width": tags.get("parking:left:width"),
            "parking_right_width": tags.get("parking:right:width"),
            "parking_both_width": tags.get("parking:both:width"),
            "sidewalk": tags.get("sidewalk"),
            "sidewalk_left": tags.get("sidewalk:left"),
            "sidewalk_right": tags.get("sidewalk:right"),
            "sidewalk_both": tags.get("sidewalk:both"),
            "sidewalk_left_width": tags.get("sidewalk:left:width"),
            "sidewalk_right_width": tags.get("sidewalk:right:width"),
            "sidewalk_both_width": tags.get("sidewalk:both:width"),
            "sidewalk_left_surface": tags.get("sidewalk:left:surface"),
            "sidewalk_right_surface": tags.get("sidewalk:right:surface"),
            "sidewalk_both_surface": tags.get("sidewalk:both:surface"),
            "sidewalk_left_kerb": tags.get("sidewalk:left:kerb"),
            "sidewalk_right_kerb": tags.get("sidewalk:right:kerb"),
            "sidewalk_both_kerb": tags.get("sidewalk:both:kerb"),
            "pedestrian_access_specialized": (
                tags.get("highway") in ("steps", "elevator")
                or str(tags.get("conveying") or "").lower() in
                   ("yes", "forward", "backward", "reversible")
                or (tags.get("highway") in ("footway", "path")
                    and tags.get("incline") not in (None, "", "0", "0%")
                    and str(tags.get("wheelchair") or "").lower() in
                        ("yes", "designated", "limited"))),
            "width_source": "explicit" if tags.get("width") else "semantic_default",
            "source": "osm",
        })

    def add_area(tags, ring_lonlat, kind, osm_id=None, osm_type=None):
        pts = to_xy(ring_lonlat)
        if len(pts) < 4:
            return
        if kind == "water":
            color, z = [0.30, 0.48, 0.62], 0.04
        elif kind in ("stadium_site", "hospital_site"):
            color, z = [0.30, 0.32, 0.34], 0.025
        elif kind == "residential_zone":
            color, z = [0.58, 0.52, 0.43], 0.018
        else:  # green area
            color, z = [0.42, 0.58, 0.36], 0.03
        areas.append({
            "polygon": pts, "z": z, "color": color,
            "type": tags.get("leisure") or tags.get("landuse") or tags.get("natural") or kind,
            "sport": tags.get("sport"), "surface": tags.get("surface"),
            "residential": tags.get("residential"),
            "leaf_type": tags.get("leaf_type"), "leaf_cycle": tags.get("leaf_cycle"),
            "height": _numeric_tag(tags, "height"),
            "amenity": tags.get("amenity"), "healthcare": tags.get("healthcare"),
            "name": tags.get("name"), "osm_id": osm_id,
            "osm_type": osm_type, "source": "osm",
        })

    for el in data.get("elements", []):
        tags = el.get("tags", {}) or {}
        etype = el.get("type")

        if "building" in tags or "building:part" in tags:
            oid = el.get("id")
            if etype == "way" and el.get("geometry"):
                add_building(tags, _ring_from_geometry(el["geometry"]), oid, etype)
            elif etype == "relation":
                for mem in el.get("members", []):
                    if mem.get("role") == "outer" and mem.get("geometry"):
                        add_building(tags, _ring_from_geometry(mem["geometry"]), oid, etype)
            continue

        if ("highway" in tags or "railway" in tags) and etype == "way" and el.get("geometry"):
            road_tags = dict(tags)
            road_tags["_osm_id"] = el.get("id")
            road_tags["_osm_type"] = etype
            add_road(road_tags, _ring_from_geometry(el["geometry"]))
            continue

        is_water = tags.get("natural") == "water" or tags.get("waterway") == "riverbank"
        is_stadium_area = tags.get("leisure") == "stadium"
        is_hospital_area = (tags.get("amenity") in ("hospital", "clinic")
                            or tags.get("healthcare") in (
                                "hospital", "clinic", "centre", "center"))
        is_residential_area = tags.get("landuse") == "residential"
        is_green = (tags.get("leisure") in ("park", "garden", "pitch", "playground")
                    or tags.get("landuse") in ("grass", "forest", "meadow", "orchard",
                                               "recreation_ground", "village_green")
                    or tags.get("natural") in ("wood", "scrub", "shrubbery", "grassland"))
        if is_water or is_green or is_stadium_area or is_hospital_area or is_residential_area:
            kind = ("water" if is_water else
                    "stadium_site" if is_stadium_area else
                    "hospital_site" if is_hospital_area else "green")
            if is_residential_area:
                kind = "residential_zone"
            if etype == "way" and el.get("geometry"):
                add_area(tags, _ring_from_geometry(el["geometry"]), kind,
                         el.get("id"), etype)
            elif etype == "relation":
                for mem in el.get("members", []):
                    if mem.get("role") == "outer" and mem.get("geometry"):
                        add_area(tags, _ring_from_geometry(mem["geometry"]), kind,
                                 el.get("id"), etype)

    buildings, _ = resolve_building_parts(buildings)
    return buildings, roads, areas


# ---------------------------------------------------------------------------
# 4) Optional Google Street View and place photos.
# ---------------------------------------------------------------------------

def download_streetview(lat, lon, out_dir, api_key):
    saved = []
    meta = requests.get(
        "https://maps.googleapis.com/maps/api/streetview/metadata",
        params={"location": f"{lat},{lon}", "source": "outdoor", "key": api_key},
        timeout=30,
    ).json()
    if meta.get("status") != "OK":
        print(f"  Street View: no coverage here ({meta.get('status')}); skipping.")
        return saved
    sv_dir = out_dir / "streetview"
    sv_dir.mkdir(parents=True, exist_ok=True)
    for heading in (0, 90, 180, 270):
        r = requests.get(
            "https://maps.googleapis.com/maps/api/streetview",
            params={"size": "640x640", "location": f"{lat},{lon}",
                    "heading": heading, "pitch": 8, "fov": 90,
                    "source": "outdoor", "key": api_key},
            timeout=30,
        )
        if r.status_code == 200 and r.content[:3] != b"<ht":
            p = sv_dir / f"heading_{heading:03d}.jpg"
            p.write_bytes(r.content)
            saved.append(str(p))
    print(f"  Street View: saved {len(saved)} images to {sv_dir}")
    return saved


def download_satellite_reference(lat, lon, radius_m, out_dir, api_key):
    """Download an aerial reference comparable to the one-shot render.

    Select a zoom that fits the requested diameter in a 640-pixel image. If
    Static Maps is unavailable, degrade gracefully without aborting.
    """
    meters_per_px_z0 = 156543.03392 * max(0.05, math.cos(math.radians(lat)))
    diameter = max(50.0, float(radius_m) * 2.25)
    zoom = int(math.floor(math.log2(meters_per_px_z0 * 640.0 / diameter)))
    zoom = max(1, min(20, zoom))
    try:
        response = requests.get(
            "https://maps.googleapis.com/maps/api/staticmap",
            params={
                "center": f"{lat},{lon}", "zoom": zoom, "size": "640x640",
                "scale": 1, "maptype": "satellite", "key": api_key,
            },
            timeout=30,
        )
    except requests.RequestException:
        return None
    if response.status_code != 200 or response.content[:3] == b"<ht":
        return None
    path = out_dir / "reference_satellite.png"
    path.write_bytes(response.content)
    print(f"  Satellite reference: {path} (zoom {zoom})")
    # Return geo-referencing so the builder can sample per-feature colors from
    # this reference image (image stays a reference; only a color attribute is
    # derived, never pasted into the scene as geometry or texture).
    return {
        "path": str(path.resolve()),
        "filename": "reference_satellite.png",
        "size": 640,
        "zoom": zoom,
        "meters_per_px": meters_per_px_z0 / (2 ** zoom),
        "center": {"lat": lat, "lon": lon},
        "maptype": "satellite",
    }


def download_place_photos(lat, lon, out_dir, api_key, max_photos=4):
    saved = []
    try:
        nearby = requests.get(
            "https://maps.googleapis.com/maps/api/place/nearbysearch/json",
            params={"location": f"{lat},{lon}", "radius": 60, "key": api_key},
            timeout=30,
        ).json()
    except requests.RequestException:
        return saved
    if nearby.get("status") not in ("OK", "ZERO_RESULTS"):
        return saved
    refs = []
    for res in nearby.get("results", []):
        for ph in res.get("photos", []) or []:
            refs.append(ph["photo_reference"])
            if len(refs) >= max_photos:
                break
        if len(refs) >= max_photos:
            break
    if not refs:
        return saved
    ph_dir = out_dir / "photos"
    ph_dir.mkdir(parents=True, exist_ok=True)
    for i, ref in enumerate(refs):
        r = requests.get(
            "https://maps.googleapis.com/maps/api/place/photo",
            params={"maxwidth": 800, "photo_reference": ref, "key": api_key},
            timeout=30, allow_redirects=True,
        )
        if r.status_code == 200 and r.content[:3] != b"<ht":
            p = ph_dir / f"photo_{i:02d}.jpg"
            p.write_bytes(r.content)
            saved.append(str(p))
    print(f"  Place photos: saved {len(saved)} images to {ph_dir}")
    return saved


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def slugify(text):
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^\w\s-]", "", text).strip().lower()
    text = re.sub(r"[-\s]+", "-", text)
    return text[:40] or "place"


def run_blender(scene_path, blend_path, render_path, blender_bin):
    if blender_bin:
        cmd = [blender_bin, "-b", "-P", str(BLENDER_BUILD), "--",
               str(scene_path), str(blend_path), str(render_path)]
    else:
        cmd = [sys.executable, str(BLENDER_BUILD),
               str(scene_path), str(blend_path), str(render_path)]
    print(f"\n▶ Blender: {' '.join(cmd)}\n")
    return subprocess.run(cmd).returncode


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def _extract_place(argv):
    """Separate the place from flags so negative coordinates remain positional."""
    value_flags = {"--radius", "--out", "--blender"}
    place, rest = None, []
    i = 0
    while i < len(argv):
        a = argv[i]
        if a in value_flags:
            rest.append(a)
            if i + 1 < len(argv):
                rest.append(argv[i + 1])
                i += 1
        elif a.startswith("--") or a in ("-h",):
            rest.append(a)
        elif place is None:
            place = a           # first positional token: coordinates, URL, or name
        else:
            rest.append(a)
        i += 1
    return place, rest


def fetch_terrain(lat0, lon0, radius_m, resolution=20, dataset="srtm30m"):
    """Sample a real elevation grid over the scene bounds via OpenTopoData
    (public SRTM/DEM, no API key). Returns a terrain dict in the same local
    meter frame as the geometry, or None if the fetch fails. Elevation is real
    data; treat it as such (attribute NASA SRTM)."""
    n = max(4, int(resolution))
    m_per_deg_lat = 111320.0
    m_per_deg_lon = 111320.0 * math.cos(math.radians(lat0))
    coords = []
    for j in range(n):
        for i in range(n):
            x = -radius_m + 2.0 * radius_m * i / (n - 1)
            y = -radius_m + 2.0 * radius_m * j / (n - 1)
            coords.append((lat0 + y / m_per_deg_lat, lon0 + x / m_per_deg_lon))
    elevations = []
    try:
        for start in range(0, len(coords), 100):
            batch = coords[start:start + 100]
            locs = "|".join(f"{a:.6f},{b:.6f}" for a, b in batch)
            resp = requests.get(f"https://api.opentopodata.org/v1/{dataset}",
                                params={"locations": locs}, timeout=30)
            resp.raise_for_status()
            for result in resp.json().get("results", []):
                value = result.get("elevation")
                elevations.append(float(value) if value is not None else 0.0)
            time.sleep(1.0)  # OpenTopoData fair-use: max 1 call/second
    except (requests.RequestException, ValueError) as exc:
        print(f"   (terrain fetch failed: {exc})")
        return None
    if len(elevations) != n * n:
        print("   (terrain: incomplete grid, skipping)")
        return None
    grid = [elevations[j * n:(j + 1) * n] for j in range(n)]
    return {"nx": n, "ny": n, "extent": float(radius_m), "z": grid,
            "zmin": min(elevations), "zmax": max(elevations),
            "source": f"opentopodata/{dataset}",
            "attribution": "NASA SRTM via OpenTopoData"}


def main():
    ap = argparse.ArgumentParser(description="Google Maps -> 3D model in Blender")
    ap.add_argument("--radius", type=float, default=250, help="Radius in meters (default 250)")
    ap.add_argument("--out", default=None, help="Output directory")
    ap.add_argument("--no-streetview", action="store_true", help="Do not download Google imagery")
    ap.add_argument("--no-render", action="store_true", help="Generate data without running Blender")
    ap.add_argument("--blender", default=os.environ.get("BLENDER_BIN"), help="Path to the Blender binary")
    ap.add_argument("--terrain", action="store_true",
                    help="Fetch real SRTM/DEM elevation and add a terrain grid")
    ap.add_argument("--terrain-res", type=int, default=20,
                    help="Terrain grid resolution per side (default 20)")

    place, rest = _extract_place(sys.argv[1:])
    args = ap.parse_args(rest)
    if not place:
        ap.error("Missing place. Example: place_to_3d.py \"-34.6037,-58.3816\" --radius 200")
    args.place = place

    api_key = os.environ.get("GOOGLE_MAPS_API_KEY")

    print(f"➊ Resolving place: {args.place!r}")
    lat, lon, label = resolve_location(args.place, api_key)
    print(f"   -> {lat:.6f}, {lon:.6f}  ({label})")

    out_dir = Path(args.out) if args.out else HERE.parent / "output" / slugify(label)
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"➋ Downloading OpenStreetMap geometry (radius {args.radius:.0f} m)...")
    south, west, north, east = bbox_around(lat, lon, args.radius)
    project = make_projector(lat, lon)
    osm = fetch_overpass_bbox(south, west, north, east)
    buildings, roads, areas = parse_osm(osm, project)
    special_features = parse_special_features(osm, project)
    # Clip everything to the requested radius; Overpass returns entire long roads.
    buildings, roads, areas = clip_scene(buildings, roads, areas, args.radius)
    special_features = clip_special_features(special_features, args.radius)
    specializations = classify_scene_specializations(osm)
    scene_kind = classify_scene_kind(osm, label)
    print(f"   -> {len(buildings)} buildings, {len(roads)} roads, {len(areas)} areas "
          f"(water/green), {len(special_features)} special layers [{scene_kind}]")

    if not buildings and not roads:
        print("   ⚠ OSM returned no geometry here. Try another place or a larger radius.")

    xs = [p[0] for b in buildings for p in b["footprint"]] + [p[0] for r in roads for p in r["path"]]
    ys = [p[1] for b in buildings for p in b["footprint"]] + [p[1] for r in roads for p in r["path"]]
    if xs and ys:
        bounds = {"minx": min(xs), "miny": min(ys), "maxx": max(xs), "maxy": max(ys)}
    else:
        bounds = {"minx": -args.radius, "miny": -args.radius, "maxx": args.radius, "maxy": args.radius}

    terrain = None
    if args.terrain:
        print(f"➍ Fetching SRTM/DEM terrain ({args.terrain_res}x{args.terrain_res} grid)...")
        terrain = fetch_terrain(lat, lon, args.radius, args.terrain_res)
        if terrain:
            print(f"   -> elevation {terrain['zmin']:.0f}..{terrain['zmax']:.0f} m "
                  f"({terrain['source']})")

    streetview, photos, satellite_reference = [], [], None
    if api_key and not args.no_streetview:
        print("➌ Downloading Google Street View and place photos...")
        try:
            streetview = download_streetview(lat, lon, out_dir, api_key)
            photos = download_place_photos(lat, lon, out_dir, api_key)
            satellite_reference = download_satellite_reference(
                lat, lon, args.radius, out_dir, api_key)
        except requests.RequestException as e:
            print(f"   (Google request failed: {e})")
    elif not api_key and not args.no_streetview:
        print("➌ (No GOOGLE_MAPS_API_KEY: skipping Street View and photos)")

    import cityprofiles
    profile, profile_defaults = cityprofiles.classify(buildings)
    if scene_kind == "airport":
        # Airport terminals, hangars, and roofs are usually flat. Preserve any
        # explicit OSM roof:shape value.
        profile = "industrial"
        profile_defaults = {"default_height": 9.0,
                            "roof_bias": "flat",
                            "wall_hint": "concrete"}
        airport_palette = [
            [0.62, 0.67, 0.69],
            [0.73, 0.76, 0.76],
            [0.48, 0.56, 0.59],
            [0.80, 0.81, 0.78],
        ]
        for idx, building in enumerate(buildings):
            if not building.get("roof_shape"):
                building["roof_shape"] = "flat"
            # Neutral glass, steel, and concrete instead of a residential palette.
            building["color"] = airport_palette[idx % len(airport_palette)]
    print(f"   -> architectural profile: {profile}")

    height_sources = {"explicit": 0, "levels": 0, "default": 0,
                      "inferred_clearance": 0}
    for building in buildings:
        source = building.get("height_source", "default")
        height_sources[source] = height_sources.get(source, 0) + 1
    building_part_count = sum(1 for building in buildings
                              if building.get("is_building_part"))
    suppressed_outline_count = len({
        building.get("outline_osm_id") for building in buildings
        if building.get("outline_osm_id") is not None
    })
    covered_structure_count = sum(
        1 for building in buildings if building.get("structure_mode") == "roof_only")
    covered_structure_count += sum(
        1 for feature in special_features
        if feature.get("family") == "covered_structure")
    urban_object_count = sum(
        1 for feature in special_features
        if feature.get("family") in (
            "street_furniture", "vegetation", "signage", "transit",
            "public_art", "recreation"))
    urban_family_counts = {}
    for feature in special_features:
        family = str(feature.get("family") or "infrastructure")
        urban_family_counts[family] = urban_family_counts.get(family, 0) + 1
    football_pitches = [
        area for area in areas
        if area.get("type") == "pitch"
        and str(area.get("sport") or "").lower() in ("soccer", "football", "futsal")
    ]
    stadium_buildings = [
        building for building in buildings
        if str(building.get("type") or "").lower() in ("stadium", "grandstand")
        or str(building.get("building_part") or "").lower() == "grandstand"
    ]

    scene = {
        "center": {"lat": lat, "lon": lon, "label": label},
        "radius": args.radius,
        "bounds": bounds,
        "terrain": terrain,
        "profile": profile,
        "profile_defaults": profile_defaults,
        "scene_kind": scene_kind,
        "specializations": specializations,
        "stadium_profile": {
            "detected": scene_kind in ("football_stadium", "stadium"),
            "football": scene_kind == "football_stadium",
            "pitch_count": len(football_pitches),
            "stadium_building_count": len(stadium_buildings),
            "source": "osm_tags",
        },
        "hospital_profile": {
            "detected": "hospital" in specializations,
            "building_count": sum(
                1 for building in buildings
                if "hospital" in str(building.get("type", "")).lower()
                or "hospital" in str(building.get("building_use", "")).lower()
                or "clinic" in str(building.get("building_use", "")).lower()),
            "source": "osm_tags",
        },
        "highway_profile": {
            "detected": "highway" in specializations,
            "carriageway_count": sum(
                1 for road in roads if road.get("type") in (
                    "motorway", "motorway_link", "trunk", "trunk_link")),
            "source": "osm_tags",
        },
        "residential_profile": urban_detail.residential_profile({
            "areas": areas, "buildings": buildings,
        }),
        "urban_detail_profile": {
            "detected": bool(urban_object_count),
            "family_counts": urban_family_counts,
            "source": "osm_tags",
        },
        "buildings": buildings,
        "roads": roads,
        "areas": areas,
        "special_features": special_features,
        "streetview": streetview,
        "photos": photos,
        "satellite_reference": satellite_reference,
        "data_quality": {
            "building_heights": height_sources,
            "building_parts": building_part_count,
            "building_outlines_suppressed": suppressed_outline_count,
            "streetview_outdoor": bool(streetview),
            "satellite_reference": bool(satellite_reference),
            "special_feature_count": len(special_features),
            "covered_structure_count": covered_structure_count,
            "urban_object_count": urban_object_count,
            "urban_family_counts": urban_family_counts,
            "football_pitch_count": len(football_pitches),
            "stadium_building_count": len(stadium_buildings),
            "hospital_detected": "hospital" in specializations,
            "highway_carriageway_count": sum(
                1 for road in roads if road.get("type") in (
                    "motorway", "motorway_link", "trunk", "trunk_link")),
        },
        "sources": ["OpenStreetMap", "Google references" if api_key else "OpenStreetMap only"],
    }
    scene_path = out_dir / "scene.json"
    scene_path.write_text(json.dumps(scene))
    print(f"➍ scene.json -> {scene_path}  ({scene_path.stat().st_size // 1024} KB)")

    blend_path = out_dir / "model.blend"
    render_path = out_dir / "render.png"

    if args.no_render:
        print("   (--no-render: Blender will not be opened)")
        print(f"\n✅ Data ready in {out_dir}")
        return

    print("➎ Building and rendering in Blender...")
    rc = run_blender(scene_path, blend_path, render_path, args.blender)
    if rc != 0:
        sys.exit(f"Blender exited with code {rc}")

    print(f"\n✅ Done:")
    print(f"   Render : {render_path}")
    print(f"   Blend  : {blend_path}")
    if streetview:
        print(f"   Street View: {out_dir / 'streetview'}")
    if photos:
        print(f"   Photos : {out_dir / 'photos'}")


if __name__ == "__main__":
    main()
