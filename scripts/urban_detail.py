"""Shared semantic registry for residential zones and explicit urban objects.

The module is Blender-free. Acquisition uses :func:`classify_tags` to create a
stable normalized feature contract; ``blocks_build`` turns that contract into
editable meshes. Rules depend only on OSM semantics, never names or locations.
"""

import math
import re


DEFAULT_CONFIG = {
    "enabled": "auto",
    "geometry_radius": 240.0,
    "max_objects": 1200,
    "object_segments": 10,
    "tree_segments": 12,
    "render_text": True,
}


# Meter-scale conservative fallbacks. They describe readable LOD, not surveyed
# dimensions. Explicit height/width/size tags always override these values.
OBJECT_SPECS = {
    "tree": ("vegetation", 7.0, 5.0, 5.0, 3),
    "street_lamp": ("street_furniture", 6.0, 0.18, 0.18, 3),
    "bench": ("street_furniture", 0.85, 1.8, 0.48, 4),
    "waste_basket": ("street_furniture", 0.9, 0.5, 0.5, 2),
    "drinking_water": ("street_furniture", 1.0, 0.4, 0.4, 3),
    "bicycle_parking": ("street_furniture", 1.0, 1.5, 0.7, 9),
    "shelter": ("covered_structure", 2.7, 3.0, 1.9, 7),
    "bollard": ("street_furniture", 0.9, 0.18, 0.18, 1),
    "gate": ("street_furniture", 1.2, 2.4, 0.12, 3),
    "traffic_signal": ("signage", 4.2, 0.34, 0.28, 6),
    "traffic_sign": ("signage", 2.6, 0.72, 0.08, 3),
    "street_name_sign": ("signage", 2.7, 1.1, 0.08, 4),
    "guidepost": ("signage", 2.4, 1.25, 0.10, 5),
    "information_board": ("signage", 2.0, 1.25, 0.10, 4),
    "map_board": ("signage", 1.75, 1.35, 0.12, 4),
    "billboard": ("signage", 6.5, 5.5, 0.22, 5),
    "advertising_board": ("signage", 2.2, 1.4, 0.12, 4),
    "poster_box": ("signage", 2.0, 1.1, 0.18, 4),
    "advertising_screen": ("signage", 2.6, 1.5, 0.18, 4),
    "advertising_column": ("signage", 3.2, 1.25, 1.25, 3),
    "advertising_totem": ("signage", 4.0, 1.25, 0.35, 3),
    "flag": ("signage", 7.0, 2.4, 0.05, 3),
    "bus_stop": ("transit", 3.0, 0.65, 0.10, 5),
    "pedestrian_crossing": ("road_surface", 0.04, 6.0, 4.0, 9),
    "traffic_island": ("road_surface", 0.22, 3.6, 1.35, 5),
    "painted_island": ("road_surface", 0.035, 3.8, 1.5, 6),
    "stop_line": ("road_surface", 0.035, 6.0, 0.42, 1),
    "fire_hydrant": ("street_furniture", 0.85, 0.32, 0.32, 6),
    "post_box": ("street_furniture", 1.25, 0.55, 0.42, 3),
    "telephone": ("street_furniture", 2.15, 0.9, 0.9, 5),
    "clock": ("street_furniture", 3.4, 0.75, 0.18, 4),
    "street_cabinet": ("street_furniture", 1.35, 0.85, 0.42, 3),
    "utility_pole": ("street_furniture", 8.0, 0.24, 0.24, 3),
    "power_tower": ("street_furniture", 24.0, 4.2, 4.2, 13),
    "power_transformer": ("utility_network", 1.65, 1.25, 0.95, 8),
    "power_substation_kiosk": ("utility_network", 2.6, 3.2, 2.2, 8),
    "telecom_pole": ("utility_network", 7.0, 0.22, 0.22, 3),
    "telecom_cabinet": ("utility_network", 1.35, 0.85, 0.42, 7),
    "telecom_distribution_point": ("utility_network", 0.46, 0.34, 0.18, 4),
    "pumping_station": ("fluid_network", 2.8, 3.4, 2.6, 10),
    "pipeline_valve": ("fluid_network", 0.85, 0.45, 0.45, 6),
    "pipeline_measurement": ("fluid_network", 1.15, 0.65, 0.55, 7),
    "fluid_cabinet": ("fluid_network", 1.35, 0.85, 0.42, 7),
    "manhole_cover": ("road_surface", 0.035, 0.72, 0.72, 3),
    "drainage_inlet": ("road_surface", 0.035, 0.72, 0.42, 8),
    "curb_ramp": ("road_surface", 0.035, 1.20, 1.0, 3),
    "raised_crossing": ("road_surface", 0.10, 6.0, 5.5, 12),
    "speed_table": ("road_surface", 0.10, 6.0, 5.5, 5),
    "pedestrian_elevator": ("pedestrian_access", 2.4, 1.6, 1.5, 10),
    "picnic_table": ("street_furniture", 0.78, 1.8, 1.45, 7),
    "recycling": ("street_furniture", 1.45, 1.2, 0.75, 4),
    "parking_meter": ("street_furniture", 1.45, 0.42, 0.34, 5),
    "charging_station": ("street_furniture", 1.65, 0.62, 0.42, 6),
    "charge_point": ("street_furniture", 1.45, 0.50, 0.38, 6),
    "vending_machine": ("street_furniture", 1.90, 0.95, 0.70, 8),
    "parcel_locker": ("street_furniture", 2.05, 2.40, 0.65, 16),
    "atm": ("street_furniture", 1.75, 0.85, 0.55, 7),
    "defibrillator": ("street_furniture", 0.55, 0.46, 0.20, 4),
    "fitness_station": ("recreation", 2.25, 2.40, 1.20, 8),
    "statue": ("public_art", 4.8, 1.5, 1.5, 8),
    "bust": ("public_art", 2.4, 0.9, 0.9, 6),
    "stele": ("public_art", 2.8, 1.3, 0.35, 4),
    "plaque": ("public_art", 1.2, 0.65, 0.05, 2),
    "memorial_stone": ("public_art", 1.35, 1.1, 0.8, 3),
    "obelisk": ("public_art", 12.0, 2.4, 2.4, 4),
    "monument": ("public_art", 7.5, 3.2, 3.2, 7),
    "sculpture": ("public_art", 4.0, 2.8, 2.8, 6),
    "installation": ("public_art", 3.5, 3.5, 3.5, 8),
    "mural": ("public_art", 3.0, 4.5, 0.05, 2),
    "fountain": ("public_art", 2.2, 4.0, 4.0, 8),
    "swing": ("recreation", 2.4, 3.2, 1.8, 9),
    "slide": ("recreation", 2.2, 3.6, 1.0, 7),
    "seesaw": ("recreation", 1.0, 3.0, 0.35, 4),
    "climbingframe": ("recreation", 2.5, 2.8, 2.8, 12),
    "roundabout": ("recreation", 0.75, 2.2, 2.2, 4),
    "sandbox": ("recreation", 0.32, 2.5, 2.5, 5),
}


TURN_TOKENS = {
    "left", "slight_left", "sharp_left", "through", "right",
    "slight_right", "sharp_right", "reverse", "merge_to_left",
    "merge_to_right", "none",
}


PLAYGROUND_ALIASES = {
    "swing": "swing", "basket_swing": "swing", "baby_swing": "swing",
    "slide": "slide", "seesaw": "seesaw", "springy": "seesaw",
    "climbingframe": "climbingframe", "climbing_frame": "climbingframe",
    "climbingwall": "climbingframe", "monkey_bars": "climbingframe",
    "roundabout": "roundabout", "carousel": "roundabout",
    "sandpit": "sandbox", "sandbox": "sandbox",
}


def parse_size(value):
    """Parse OSM advertising ``size=length*height`` into meters."""
    if value in (None, ""):
        return None
    numbers = re.findall(r"\d+(?:\.\d+)?", str(value).replace(",", "."))
    if len(numbers) < 2:
        return None
    width, height = float(numbers[0]), float(numbers[1])
    if not (0.05 <= width <= 100.0 and 0.05 <= height <= 100.0):
        return None
    return round(width, 3), round(height, 3)


def parse_bearing(value):
    if value in (None, ""):
        return None
    try:
        return float(value) % 360.0
    except (TypeError, ValueError):
        pass
    token = str(value).strip().upper()
    cardinals = {"N": 0.0, "NE": 45.0, "E": 90.0, "SE": 135.0,
                 "S": 180.0, "SW": 225.0, "W": 270.0, "NW": 315.0}
    return cardinals.get(token)


def parse_turn_lanes(value):
    """Parse ``turn:lanes`` while preserving lane order and combined arrows."""
    if value in (None, ""):
        return []
    lanes = []
    for raw_lane in str(value).lower().split("|"):
        values = []
        for token in raw_lane.split(";"):
            token = token.strip().replace("-", "_")
            if token in TURN_TOKENS and token not in values:
                values.append(token)
        lanes.append(values or ["none"])
    return lanes


def road_turn_profiles(road):
    """Return explicit directional lane-arrow profiles for a normalized road."""
    road = road or {}
    profiles = []
    oneway = str(road.get("oneway") or "").lower() in ("yes", "true", "1", "-1")
    generic = parse_turn_lanes(road.get("turn_lanes") or road.get("turn:lanes"))
    forward = parse_turn_lanes(
        road.get("turn_lanes_forward") or road.get("turn:lanes:forward"))
    backward = parse_turn_lanes(
        road.get("turn_lanes_backward") or road.get("turn:lanes:backward"))
    if generic:
        profiles.append({"direction": "backward" if str(road.get("oneway")) == "-1"
                         else "forward", "lanes": generic,
                         "source": "turn:lanes"})
    if forward:
        profiles.append({"direction": "forward", "lanes": forward,
                         "source": "turn:lanes:forward"})
    if backward:
        profiles.append({"direction": "backward", "lanes": backward,
                         "source": "turn:lanes:backward"})
    # A generic value on a two-way road is ambiguous in OSM. Preserve it, but
    # flag it so the builder can keep the proxy bounded and report uncertainty.
    for profile in profiles:
        profile["direction_confidence"] = (
            "explicit" if oneway or profile["source"] != "turn:lanes"
            else "ambiguous_two_way")
    return profiles


def _tag_distance(value, default=0.0):
    """Parse a conservative meter value used by cycleway width/buffer tags."""
    if value in (None, "", "no", "none"):
        return float(default)
    if str(value).strip().lower() in ("yes", "true"):
        return 0.6
    match = re.search(r"(-?\d+(?:\.\d+)?)", str(value).replace(",", "."))
    if not match:
        return float(default)
    distance = float(match.group(1))
    unit_value = str(value).lower()
    if "mm" in unit_value:
        distance *= 0.001
    elif "cm" in unit_value:
        distance *= 0.01
    elif "ft" in unit_value or "feet" in unit_value:
        distance *= 0.3048
    return max(0.0, min(8.0, distance))


def road_cycle_profiles(road, config=None):
    """Return side strips only for explicitly tagged on-road cycle lanes.

    ``cycleway=track`` and ``cycleway=separate`` deliberately do not become an
    offset strip: their geometry may be mapped independently and inventing an
    axis from the motor road can duplicate or misplace it.
    """
    road, config = road or {}, config or {}
    driving_side = str(config.get("driving_side") or "right").lower()
    generic = str(road.get("cycleway") or "").lower()
    left = str(road.get("cycleway_left") or "").lower()
    right = str(road.get("cycleway_right") or "").lower()
    both = str(road.get("cycleway_both") or "").lower()
    lanes = []
    if both == "lane":
        lanes.extend(("left", "right"))
    else:
        if left == "lane":
            lanes.append("left")
        if right == "lane":
            lanes.append("right")
    if not lanes and generic == "lane":
        oneway = str(road.get("oneway") or "").lower() in ("yes", "true", "1", "-1")
        lanes = [driving_side if driving_side in ("left", "right") else "right"] \
            if oneway else ["left", "right"]
    profiles = []
    for side in lanes:
        width = _tag_distance(
            road.get(f"cycleway_{side}_width") or road.get("cycleway_width"),
            float(config.get("cycle_lane_width", 1.6)))
        width = max(0.8, min(3.5, width))
        buffer_value = (road.get(f"cycleway_{side}_buffer")
                        or road.get("cycleway_both_buffer")
                        or road.get("cycleway_buffer"))
        buffer_width = _tag_distance(buffer_value, 0.0)
        separation = (road.get(f"cycleway_{side}_separation")
                      or road.get("cycleway_both_separation")
                      or road.get("cycleway_separation"))
        profiles.append({
            "side": side, "width": round(width, 3),
            "buffer": round(buffer_width, 3),
            "buffer_source": "explicit" if buffer_value not in (None, "") else "none",
            "separation": separation,
            "source": (f"cycleway:{side}=lane" if (left or right or both)
                       else "cycleway=lane"),
        })
    return profiles


def parse_access_lanes(value):
    """Parse an OSM ``*:lanes`` list without treating simple access as dedication."""
    if value in (None, ""):
        return []
    return [str(token).strip().lower() or "unspecified"
            for token in str(value).split("|")]


def road_bus_profiles(road):
    """Return positional dedicated bus/PSV lanes and metadata-only fallbacks."""
    road = road or {}
    oneway_value = str(road.get("oneway") or "").lower()
    oneway = oneway_value in ("yes", "true", "1", "-1")
    profiles = []
    candidates = (
        ("forward", road.get("bus_lanes_forward") or road.get("psv_lanes_forward"),
         "bus:lanes:forward/psv:lanes:forward"),
        ("backward", road.get("bus_lanes_backward") or road.get("psv_lanes_backward"),
         "bus:lanes:backward/psv:lanes:backward"),
    )
    for direction, value, source in candidates:
        lanes = parse_access_lanes(value)
        indices = [index for index, token in enumerate(lanes)
                   if token == "designated"]
        if indices:
            profiles.append({"direction": direction, "lanes": lanes,
                             "lane_indices": indices, "source": source,
                             "renderable": True, "confidence": "explicit_position"})
    generic_value = road.get("bus_lanes") or road.get("psv_lanes")
    generic = parse_access_lanes(generic_value)
    generic_indices = [index for index, token in enumerate(generic)
                       if token == "designated"]
    if generic_indices:
        profiles.append({
            "direction": "backward" if oneway_value == "-1" else "forward",
            "lanes": generic, "lane_indices": generic_indices,
            "source": "bus:lanes/psv:lanes", "renderable": oneway,
            "confidence": "explicit_position" if oneway else "ambiguous_two_way",
        })
    count_only = road.get("lanes_bus") or road.get("lanes_psv")
    if count_only not in (None, ""):
        profiles.append({"direction": None, "lanes": [], "lane_indices": [],
                         "source": "lanes:bus/lanes:psv", "renderable": False,
                         "confidence": "count_without_position",
                         "count": count_only})
    return profiles


def road_parking_profiles(road, config=None):
    """Return physical side strips from modern street-parking tags, never cars."""
    road, config = road or {}, config or {}
    result = []
    both = road.get("parking_both")
    for side in ("left", "right"):
        position = road.get(f"parking_{side}") or both
        position = str(position or "").lower()
        if position not in ("lane", "street_side", "on_kerb", "half_on_kerb"):
            continue
        orientation = str(road.get(f"parking_{side}_orientation")
                          or road.get("parking_both_orientation")
                          or "parallel").lower()
        defaults = {"parallel": 2.2, "diagonal": 4.2, "perpendicular": 5.0}
        default_width = defaults.get(orientation, 2.2)
        width = _tag_distance(road.get(f"parking_{side}_width")
                              or road.get("parking_both_width"), default_width)
        result.append({"side": side, "position": position,
                       "orientation": orientation,
                       "width": round(max(1.4, min(6.5, width)), 3),
                       "source": f"parking:{side}/{orientation}"})
    return result


def road_sidewalk_profiles(road, config=None):
    """Return only sidewalks represented as road-side properties.

    ``separate`` is deliberately metadata-only because its axis should be a
    separately mapped footway. Left/right always follow the OSM way direction.
    """
    road, config = road or {}, config or {}
    generic = str(road.get("sidewalk") or "").lower()
    both = str(road.get("sidewalk_both") or "").lower()
    explicit = {
        "left": str(road.get("sidewalk_left") or "").lower(),
        "right": str(road.get("sidewalk_right") or "").lower(),
    }
    result = []
    for side in ("left", "right"):
        value = explicit[side] or both
        if not value:
            if generic in ("both", "yes"):
                value = "yes"
            elif generic == side:
                value = "yes"
            elif generic == "separate":
                value = "separate"
        if value == "separate":
            result.append({"side": side, "renderable": False,
                           "source": f"sidewalk:{side}=separate",
                           "confidence": "separately_mapped_axis"})
            continue
        if value not in ("yes", "both", "left", "right"):
            continue
        width_value = (road.get(f"sidewalk_{side}_width")
                       or road.get("sidewalk_both_width"))
        width = _tag_distance(width_value,
                              float(config.get("sidewalk_width", 1.8)))
        surface = (road.get(f"sidewalk_{side}_surface")
                   or road.get("sidewalk_both_surface")
                   or "paving_stones")
        kerb = (road.get(f"sidewalk_{side}_kerb")
                or road.get("sidewalk_both_kerb"))
        result.append({
            "side": side, "renderable": True,
            "width": round(max(0.8, min(6.0, width)), 3),
            "surface": str(surface).lower(), "kerb": kerb,
            "source": f"sidewalk:{side}", "confidence": "explicit_side",
        })
    return result


def parse_incline(value):
    """Normalize an OSM incline into signed grade while retaining uncertainty."""
    token = str(value or "").strip().lower()
    if not token:
        return {"direction": "unknown", "grade": None, "source": "missing"}
    if token in ("up", "upwards"):
        return {"direction": "up", "grade": None, "source": "direction_only"}
    if token in ("down", "downwards"):
        return {"direction": "down", "grade": None, "source": "direction_only"}
    match = re.search(r"(-?\d+(?:\.\d+)?)", token.replace(",", "."))
    if not match:
        return {"direction": "unknown", "grade": None, "source": "unparsed"}
    number = float(match.group(1))
    if "°" in token or "deg" in token:
        grade = math.tan(math.radians(number)) * 100.0
    else:
        grade = number
    return {"direction": "up" if grade >= 0 else "down",
            "grade": max(-100.0, min(100.0, grade)),
            "source": "explicit_numeric"}


def pedestrian_access_profile(feature, config=None):
    """Resolve stairs, ramps, escalators and inclined elevators from line tags."""
    feature, config = feature or {}, config or {}
    kind = str(feature.get("kind") or "").lower()
    path = feature.get("path") or []
    length = sum(math.hypot(float(b[0]) - float(a[0]),
                            float(b[1]) - float(a[1]))
                 for a, b in zip(path, path[1:]))
    incline = parse_incline(feature.get("incline"))
    conveying = str(feature.get("conveying") or "").lower()
    try:
        explicit_steps = int(float(feature.get("step_count")))
    except (TypeError, ValueError):
        explicit_steps = 0
    step_count = max(2, min(120, explicit_steps or round(max(1.0, length) / 0.34)))
    step_height = _tag_distance(feature.get("step_height"), 0.16)
    step_height = max(0.08, min(0.24, step_height))
    if incline["grade"] is not None:
        rise = length * abs(incline["grade"]) / 100.0
        rise_source = "explicit_incline"
    elif kind in ("steps", "escalator"):
        rise = step_count * step_height
        rise_source = "explicit_step_count" if explicit_steps else "bounded_step_proxy"
    else:
        rise = min(4.0, max(0.20, length * 0.08))
        rise_source = "bounded_direction_only_proxy"
    direction_sign = -1.0 if incline["direction"] == "down" else 1.0
    handrail_value = str(feature.get("handrail") or "").lower()
    handrail_sides = []
    if handrail_value == "both":
        handrail_sides = ["left", "right"]
    for side in ("left", "right", "center"):
        if str(feature.get(f"handrail_{side}") or "").lower() in (
                "yes", "true", "1") and side not in handrail_sides:
            handrail_sides.append(side)
    return {
        "kind": kind, "length": length,
        "width": max(0.8, min(8.0, _tag_distance(feature.get("width"), 2.0))),
        "rise": max(0.05, min(18.0, abs(rise))),
        "direction_sign": direction_sign,
        "incline": incline, "rise_source": rise_source,
        "step_count": step_count,
        "step_count_source": "explicit" if explicit_steps else "bounded_proxy",
        "step_height": step_height,
        "handrail_sides": handrail_sides,
        "handrail_unspecified": handrail_value in ("yes", "true", "1"),
        "ramp_present_unspecified": str(feature.get("ramp") or "").lower()
                                     in ("yes", "true", "1"),
        "conveying": conveying,
        "wheelchair": feature.get("wheelchair"),
        "provenance": "osm_axis+explicit_access_semantics+bounded_geometry",
    }


def point_in_polygon(point, polygon):
    """Even-odd containment test used by deterministic vegetation placement."""
    if len(polygon or []) < 3:
        return False
    x, y = float(point[0]), float(point[1])
    inside = False
    ring = polygon[:-1] if polygon[0] == polygon[-1] else polygon
    previous = ring[-1]
    for current in ring:
        x1, y1 = float(previous[0]), float(previous[1])
        x2, y2 = float(current[0]), float(current[1])
        if ((y1 > y) != (y2 > y)):
            crossing = (x2 - x1) * (y - y1) / ((y2 - y1) or 1e-12) + x1
            if x < crossing:
                inside = not inside
        previous = current
    return inside


def deterministic_area_points(polygon, count, seed=0):
    """Generate stable bounded points inside an area without claiming surveys."""
    ring = polygon[:-1] if polygon and polygon[0] == polygon[-1] else polygon
    if len(ring or []) < 3 or int(count) <= 0:
        return []
    xs = [float(item[0]) for item in ring]
    ys = [float(item[1]) for item in ring]
    width, depth = max(xs) - min(xs), max(ys) - min(ys)
    if width <= 0.05 or depth <= 0.05:
        return []
    count = int(count)
    columns = max(1, int(math.ceil(math.sqrt(count * width / max(depth, 0.1)))))
    rows = max(1, int(math.ceil(count / columns)))
    state = int(seed or 0) & 0x7fffffff

    def jitter():
        nonlocal state
        state = (1103515245 * state + 12345) & 0x7fffffff
        return state / 0x7fffffff - 0.5

    candidates = []
    # Build a denser grid because concave polygons reject cells, then select
    # evenly through the full candidate sequence. Returning as soon as ``count``
    # was reached clustered every instance in the first rows of the bbox.
    for row in range(rows * 3):
        for column in range(columns * 3):
            gx = (column + 0.5) / (columns * 3)
            gy = (row + 0.5) / (rows * 3)
            px = min(xs) + width * min(0.985, max(0.015, gx + jitter() / (columns * 12)))
            py = min(ys) + depth * min(0.985, max(0.015, gy + jitter() / (rows * 12)))
            if point_in_polygon((px, py), ring):
                candidates.append([round(px, 4), round(py, 4)])
    if len(candidates) <= count:
        return candidates
    return [candidates[min(len(candidates) - 1,
                           int((index + 0.5) * len(candidates) / count))]
            for index in range(count)]


def line_sample_points(path, spacing=7.0):
    """Sample a mapped tree-row axis at a stable approximate spacing."""
    if len(path or []) < 2:
        return []
    spacing = max(1.5, float(spacing))
    result = [[float(path[0][0]), float(path[0][1])]]
    carry = 0.0
    for start, end in zip(path, path[1:]):
        ax, ay = float(start[0]), float(start[1])
        bx, by = float(end[0]), float(end[1])
        length = math.hypot(bx - ax, by - ay)
        if length <= 1e-6:
            continue
        distance = spacing - carry if carry > 1e-6 else spacing
        while distance < length:
            t = distance / length
            result.append([round(ax + (bx - ax) * t, 4),
                           round(ay + (by - ay) * t, 4)])
            distance += spacing
        carry = max(0.0, length - (distance - spacing))
    end = [float(path[-1][0]), float(path[-1][1])]
    if math.hypot(result[-1][0] - end[0], result[-1][1] - end[1]) > spacing * 0.4:
        result.append(end)
    return result


def vegetation_area_profile(area, config=None):
    """Resolve tree/shrub infill only where an area explicitly denotes cover."""
    config = config or {}
    kind = str(area.get("type") or "").lower()
    area_m2 = abs(float(area.get("area_m2") or 0.0))
    profiles = {
        "wood": ("woodland", float(config.get("woodland_m2_per_tree", 360.0)), 7.5),
        "forest": ("woodland", float(config.get("woodland_m2_per_tree", 360.0)), 7.5),
        "orchard": ("orchard", float(config.get("orchard_m2_per_tree", 150.0)), 5.0),
        "scrub": ("scrub", float(config.get("scrub_m2_per_shrub", 95.0)), 1.5),
        "shrubbery": ("scrub", float(config.get("scrub_m2_per_shrub", 95.0)), 1.5),
    }
    if kind not in profiles or area_m2 <= 1.0:
        return None
    cover_kind, per_instance, default_height = profiles[kind]
    maximum = max(0, int(config.get("max_instances_per_area", 90)))
    count = min(maximum, max(1, int(round(area_m2 / max(20.0, per_instance)))))
    return {"kind": cover_kind, "count": count, "area_m2": round(area_m2, 2),
            "height": float(area.get("height") or default_height),
            "placement_source": "area_semantic_inference"}


def utility_line_profile(feature):
    """Resolve a visible overhead-line proxy from explicit mapped line tags."""
    power = str(feature.get("power") or feature.get("kind") or "minor_line").lower()
    default_count = 6 if power == "line" else 3
    try:
        count = int(float(feature.get("cables") or default_count))
    except (TypeError, ValueError):
        count = default_count
    count = max(1, min(12, count))
    return {
        "power": power,
        "conductors": count,
        "conductor_source": "explicit" if feature.get("cables") else "semantic_default",
        "height": max(4.0, float(feature.get("height") or (22.0 if power == "line" else 9.0))),
        "spacing": 1.6 if power == "line" else 0.42,
        "provenance": "osm_axis+procedural_conductor_proxy",
    }


def communication_line_profile(feature):
    """Resolve only explicitly overhead communications lines as visible wire."""
    location = str(feature.get("location") or "").lower()
    visible = location == "overhead"
    try:
        count = int(float(feature.get("cables") or 1))
    except (TypeError, ValueError):
        count = 1
    return {
        "visible": visible,
        "location": location or "unspecified",
        "conductors": max(1, min(8, count)),
        "height": max(3.0, float(feature.get("height") or 6.3)),
        "spacing": 0.18,
        "medium": feature.get("telecom_medium"),
        "provenance": ("osm_axis+explicit_overhead+procedural_cable_proxy"
                       if visible else "osm_axis+metadata_only"),
    }


def fluid_line_profile(feature):
    """Resolve visible versus metadata-only pipeline geometry from location."""
    location = str(feature.get("location") or "").lower()
    visible = location in ("overground", "overhead")
    diameter = _tag_distance(feature.get("diameter"), 0.32)
    return {
        "visible": visible, "location": location or "unspecified",
        "diameter": max(0.08, min(3.0, diameter)),
        "height": (max(2.8, float(feature.get("height") or 4.5))
                   if location == "overhead" else max(0.1, diameter * 0.65)),
        "substance": str(feature.get("substance") or "unknown").lower(),
        "provenance": ("osm_axis+explicit_visible_location"
                       if visible else "osm_axis+metadata_only"),
    }


def resolve_wall_host(feature, buildings, max_distance=6.0):
    """Snap a wall-mounted point to the nearest mapped building edge.

    Returns a normalized point/direction update, or ``None`` when no mapped wall
    is close enough. The result is geometry-driven and independent of identity.
    """
    point = feature.get("point") or []
    if len(point) < 2:
        return None
    px, py = float(point[0]), float(point[1])
    best = None
    for building in buildings or []:
        ring = building.get("footprint") or building.get("polygon") or []
        if len(ring) < 2:
            continue
        usable = ring[:-1] if ring[0] == ring[-1] else ring
        if not usable:
            continue
        cx = sum(float(item[0]) for item in usable) / len(usable)
        cy = sum(float(item[1]) for item in usable) / len(usable)
        for start, end in zip(ring, ring[1:] + ring[:1]):
            ax, ay = float(start[0]), float(start[1])
            bx, by = float(end[0]), float(end[1])
            dx, dy = bx - ax, by - ay
            length2 = dx * dx + dy * dy
            if length2 <= 1e-9:
                continue
            t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / length2))
            qx, qy = ax + t * dx, ay + t * dy
            distance = math.hypot(px - qx, py - qy)
            if best is None or distance < best[0]:
                best = (distance, qx, qy, dx, dy, cx, cy, building)
    if best is None or best[0] > float(max_distance):
        return None
    distance, qx, qy, dx, dy, cx, cy, building = best
    outward_x, outward_y = qx - cx, qy - cy
    outward_len = math.hypot(outward_x, outward_y) or 1.0
    normal_x, normal_y = outward_x / outward_len, outward_y / outward_len
    offset = max(0.035, float(feature.get("depth", 0.05)) * 0.58)
    qx += normal_x * offset
    qy += normal_y * offset
    tangent_angle = math.degrees(math.atan2(dy, dx))
    return {
        "point": [round(qx, 4), round(qy, 4)],
        "direction": (90.0 - tangent_angle) % 360.0,
        "direction_source": "wall_host",
        "support": "wall_resolved",
        "front_normal": [round(normal_x, 6), round(normal_y, 6)],
        "host_building_id": building.get("osm_id", building.get("id")),
        "host_distance": round(distance, 3),
    }


def resolve_road_host(feature, roads, max_distance=15.0):
    """Return nearest road axis, width and bearing for a mapped surface point."""
    point = feature.get("point") or []
    if len(point) < 2:
        return None
    px, py = float(point[0]), float(point[1])
    best = None
    for road in roads or []:
        path = road.get("path") or []
        for start, end in zip(path, path[1:]):
            ax, ay = float(start[0]), float(start[1])
            bx, by = float(end[0]), float(end[1])
            dx, dy = bx - ax, by - ay
            length2 = dx * dx + dy * dy
            if length2 <= 1e-9:
                continue
            t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / length2))
            qx, qy = ax + t * dx, ay + t * dy
            distance = math.hypot(px - qx, py - qy)
            if best is None or distance < best[0]:
                best = (distance, qx, qy, dx, dy, road)
    if best is None or best[0] > float(max_distance):
        return None
    distance, qx, qy, dx, dy, road = best
    tangent_angle = math.degrees(math.atan2(dy, dx))
    return {
        "point": [round(qx, 4), round(qy, 4)],
        "direction": (90.0 - tangent_angle) % 360.0,
        "direction_source": "road_host",
        "road_width": max(2.0, float(road.get("width", feature.get("width", 6.0)))),
        "road_z": float(road.get("z", 0.06)),
        "host_road_id": road.get("osm_id", road.get("id")),
        "host_distance": round(distance, 3),
    }


def traffic_sign_profile(feature):
    """Resolve a generic physical sign family without claiming national artwork."""
    raw = str(feature.get("traffic_sign") or "").strip()
    if not raw:
        source_tag = str(feature.get("source_tag") or "")
        raw = source_tag.split("=", 1)[1] if source_tag.startswith("traffic_sign=") else ""
    primary = re.split(r"[;,]", raw, maxsplit=1)[0].strip()
    country = None
    code = primary
    if ":" in primary:
        prefix, suffix = primary.split(":", 1)
        if len(prefix) == 2 and prefix.isalpha():
            country, code = prefix.upper(), suffix
    token = code.lower().replace("-", "_").replace(" ", "_")
    maxspeed = feature.get("maxspeed")
    measure = (maxspeed or feature.get("maxheight") or feature.get("maxweight")
               or feature.get("maxwidth"))
    profile = {"shape": "rectangle", "role": "information", "label": None,
               "country": country, "code": code or None, "raw": raw or None,
               "stack_count": max(1, len([item for item in raw.split(";") if item.strip()]))}
    if token in ("stop", "r1_1") or token.endswith(":stop"):
        profile.update(shape="octagon", role="stop", label="STOP")
    elif token in ("give_way", "yield", "giveway"):
        profile.update(shape="triangle_down", role="give_way", label=None)
    elif token in ("maxspeed", "speed_limit") or maxspeed not in (None, ""):
        profile.update(shape="circle", role="restriction", label=str(maxspeed or ""))
    elif token in ("maxheight", "maxweight", "maxwidth", "overtaking"):
        profile.update(shape="circle", role="restriction",
                       label=str(measure or ""))
    elif token in ("no_entry", "do_not_enter"):
        profile.update(shape="circle", role="no_entry", label=None)
    elif token in ("hazard", "stop_ahead", "yield_ahead", "signal_ahead"):
        if country in {"AR", "AU", "CA", "NZ", "US"}:
            profile.update(shape="diamond", role="warning", label=None)
        else:
            profile.update(shape="triangle_up", role="warning", label=None)
    elif token in ("mandatory", "direction", "keep_right", "keep_left"):
        profile.update(shape="circle", role="mandatory", label=None)
    elif token == "variable_message":
        profile.update(shape="rectangle", role="variable_message",
                       label=str(feature.get("message") or ""))
    elif token == "city_limit":
        profile.update(shape="rectangle", role="information",
                       label=str(feature.get("name") or ""))
    return profile


def classify_tags(tags):
    """Return ``(family, kind)`` for explicit physical OSM semantics."""
    tags = tags or {}
    if tags.get("natural") == "tree":
        return "vegetation", "tree"
    if tags.get("highway") == "street_lamp":
        return "street_furniture", "street_lamp"
    if tags.get("highway") == "elevator":
        return "pedestrian_access", "pedestrian_elevator"
    if tags.get("highway") == "traffic_signals":
        return "signage", "traffic_signal"
    if tags.get("highway") == "crossing" and tags.get("traffic_calming") == "table":
        return "road_surface", "raised_crossing"
    if tags.get("highway") == "crossing":
        return "road_surface", "pedestrian_crossing"
    if tags.get("traffic_calming") == "table":
        return "road_surface", "speed_table"
    if tags.get("road_marking") == "stop_line":
        return "road_surface", "stop_line"
    if tags.get("traffic_calming") == "island":
        return "road_surface", "traffic_island"
    if tags.get("traffic_calming") == "painted_island":
        return "road_surface", "painted_island"
    if tags.get("traffic_sign"):
        return ("signage", "street_name_sign" if
                str(tags.get("traffic_sign")).lower() == "street_name"
                else "traffic_sign")
    if tags.get("highway") == "bus_stop" or (
            tags.get("public_transport") == "platform"
            and str(tags.get("bus", "")).lower() in ("yes", "designated")):
        return "transit", "bus_stop"
    advertising = str(tags.get("advertising") or "").lower().replace(" ", "_")
    if advertising:
        mapping = {"billboard": "billboard", "board": "advertising_board",
                   "poster_box": "poster_box", "screen": "advertising_screen",
                   "column": "advertising_column", "totem": "advertising_totem",
                   "sign": "advertising_totem", "flag": "flag"}
        return "signage", mapping.get(advertising, "advertising_board")
    if tags.get("tourism") == "information":
        info = str(tags.get("information") or "board").lower()
        if info == "guidepost":
            return "signage", "guidepost"
        if info in ("map", "visitor_centre_map"):
            return "signage", "map_board"
        return "signage", "information_board"

    artwork = str(tags.get("artwork_type") or "").lower().replace(" ", "_")
    memorial = str(tags.get("memorial") or "").lower().replace(" ", "_")
    if tags.get("tourism") == "artwork" or artwork:
        mapping = {"statue": "statue", "bust": "bust", "sculpture": "sculpture",
                   "installation": "installation", "mural": "mural",
                   "painting": "mural", "graffiti": "mural", "stone": "memorial_stone"}
        return "public_art", mapping.get(artwork, "sculpture")
    if tags.get("historic") == "memorial" or memorial:
        mapping = {"statue": "statue", "bust": "bust", "stele": "stele",
                   "plaque": "plaque", "blue_plaque": "plaque",
                   "stone": "memorial_stone", "obelisk": "obelisk",
                   "sculpture": "sculpture", "war_memorial": "monument"}
        return "public_art", mapping.get(memorial, "monument")
    if tags.get("historic") == "monument":
        return "public_art", "monument"
    if tags.get("man_made") == "obelisk":
        return "public_art", "obelisk"
    if tags.get("amenity") == "fountain" or tags.get("man_made") == "fountain":
        return "public_art", "fountain"

    playground = str(tags.get("playground") or "").lower().replace(" ", "_")
    if playground:
        return "recreation", PLAYGROUND_ALIASES.get(playground, "climbingframe")

    amenity_map = {
        "bench": "bench", "waste_basket": "waste_basket",
        "drinking_water": "drinking_water", "bicycle_parking": "bicycle_parking",
        "shelter": "shelter", "post_box": "post_box", "telephone": "telephone",
        "clock": "clock", "recycling": "recycling",
        "parking_meter": "parking_meter", "charging_station": "charging_station",
        "vending_machine": "vending_machine", "parcel_locker": "parcel_locker",
        "atm": "atm",
    }
    if tags.get("amenity") in amenity_map:
        kind = amenity_map[tags["amenity"]]
        family = "covered_structure" if kind == "shelter" else "street_furniture"
        return family, kind
    if tags.get("emergency") == "fire_hydrant":
        return "street_furniture", "fire_hydrant"
    if tags.get("kerb") in ("flush", "lowered") and (
            tags.get("barrier") == "kerb" or tags.get("highway") in ("crossing", "footway")):
        return "road_surface", "curb_ramp"
    if tags.get("man_made") == "manhole" and (
            tags.get("manhole") == "drain" or tags.get("inlet")):
        return "road_surface", "drainage_inlet"
    if tags.get("inlet") in ("grate", "kerb_grate"):
        return "road_surface", "drainage_inlet"
    if tags.get("man_made") == "manhole":
        return "road_surface", "manhole_cover"
    if tags.get("man_made") == "street_cabinet" and tags.get("utility") == "telecom":
        return "utility_network", "telecom_cabinet"
    if tags.get("man_made") == "street_cabinet" and tags.get("utility") == "power":
        return "utility_network", "power_transformer"
    if tags.get("man_made") == "street_cabinet" and tags.get("utility") in (
            "water", "gas", "sewerage", "heating"):
        return "fluid_network", "fluid_cabinet"
    if tags.get("man_made") == "street_cabinet":
        return "street_furniture", "street_cabinet"
    if tags.get("man_made") == "charge_point":
        return "street_furniture", "charge_point"
    if tags.get("emergency") == "defibrillator":
        return "street_furniture", "defibrillator"
    if tags.get("power") == "pole":
        return "street_furniture", "utility_pole"
    if tags.get("power") == "tower":
        return "street_furniture", "power_tower"
    if tags.get("power") == "transformer":
        return "utility_network", "power_transformer"
    if tags.get("power") == "substation":
        return "utility_network", "power_substation_kiosk"
    if tags.get("man_made") == "utility_pole" and tags.get("utility") == "telecom":
        return "utility_network", "telecom_pole"
    if tags.get("telecom") == "distribution_point":
        return "utility_network", "telecom_distribution_point"
    if tags.get("telecom") == "connection_point":
        return "utility_network", "telecom_cabinet"
    if tags.get("man_made") == "pumping_station":
        return "fluid_network", "pumping_station"
    if tags.get("pipeline") == "valve":
        return "fluid_network", "pipeline_valve"
    if tags.get("pipeline") == "measurement":
        return "fluid_network", "pipeline_measurement"
    if tags.get("leisure") == "picnic_table":
        return "street_furniture", "picnic_table"
    if tags.get("leisure") == "fitness_station":
        return "recreation", "fitness_station"
    if tags.get("man_made") == "flagpole":
        return "signage", "flag"
    if tags.get("barrier") in ("bollard", "block"):
        return "street_furniture", "bollard"
    if tags.get("barrier") in ("gate", "lift_gate", "swing_gate"):
        return "street_furniture", "gate"
    return None


def normalized_defaults(kind):
    family, height, width, depth, parts = OBJECT_SPECS[kind]
    return {"family": family, "kind": kind, "height": height,
            "width": width, "depth": depth, "parts": parts}


def object_spec(feature, style=None):
    """Resolve a normalized object's build spec without using its identity."""
    style = style or {}
    kind = str(feature.get("kind") or "object").lower()
    base = OBJECT_SPECS.get(kind, (str(feature.get("family") or "urban"),
                                  1.0, 0.5, 0.5, 1))
    family, default_h, default_w, default_d, parts = base
    resolved_family = str(feature.get("family") or family)
    size = feature.get("panel_size") or parse_size(feature.get("size"))
    width = float(feature.get("width", default_w))
    height = float(feature.get("height", default_h))
    panel_width, panel_height = (size if size else
                                 (float(feature.get("panel_width", width)),
                                  float(feature.get("panel_height", min(height * 0.42, default_h * 0.42)))))
    truthy = lambda value: str(value or "").lower() in ("yes", "true", "1", "designated")
    component_parts = 0
    if kind == "bus_stop":
        component_parts += 7 if truthy(feature.get("shelter")) else 0
        component_parts += 4 if truthy(feature.get("bench")) else 0
        component_parts += 2 if truthy(feature.get("bin")) else 0
        component_parts += 2 if truthy(feature.get("passenger_information_display")) else 0
    sign_profile = traffic_sign_profile(feature) if kind == "traffic_sign" else {}
    markings = str(feature.get("crossing_markings") or feature.get("crossing:markings")
                   or ("no" if feature.get("crossing") == "unmarked" else "yes")).lower()
    tactile = str(feature.get("tactile_paving") or "no").lower() in ("yes", "true", "1")
    if kind == "pedestrian_crossing":
        parts = (0 if markings == "no" else 7) + (2 if tactile else 0)
        if str(feature.get("crossing_island") or feature.get("crossing:island")
               or "").lower() in ("yes", "true", "1"):
            parts += 2
    return {
        "enabled": bool((style.get("urban_objects") or DEFAULT_CONFIG).get("enabled", True)),
        "family": resolved_family, "kind": kind,
        "height": max(0.015 if resolved_family == "road_surface" else 0.08, height),
        "width": max(0.05, width),
        "depth": max(0.02, float(feature.get("depth", default_d))),
        "panel_width": max(0.08, panel_width),
        "panel_height": max(0.08, panel_height),
        "parts": int(feature.get("parts", parts)) + component_parts,
        "direction": parse_bearing(feature.get("direction")),
        "direction_source": (feature.get("direction_source") or
                             ("explicit" if parse_bearing(feature.get("direction")) is not None
                              else "fallback")),
        "support": str(feature.get("support") or "ground"),
        "sides": max(1, int(float(feature.get("sides", 1) or 1))),
        "lit": str(feature.get("lit") or feature.get("luminous") or "no").lower() in ("yes", "true", "1"),
        "has_shelter": truthy(feature.get("shelter")),
        "has_bench": truthy(feature.get("bench")),
        "has_bin": truthy(feature.get("bin")),
        "has_display": truthy(feature.get("passenger_information_display")),
        "sign_shape": sign_profile.get("shape"),
        "sign_role": sign_profile.get("role"),
        "sign_country": sign_profile.get("country"),
        "sign_code": sign_profile.get("code"),
        "sign_stack_count": sign_profile.get("stack_count", 1),
        "crossing_markings": markings,
        "tactile_paving": tactile,
        "crossing_island": str(feature.get("crossing_island")
                               or feature.get("crossing:island") or "").lower()
                           in ("yes", "true", "1"),
        "road_width": max(2.0, float(feature.get("road_width", width))),
        "road_z": float(feature.get("road_z", 0.06)),
        "vending": feature.get("vending"),
        "fitness_station": feature.get("fitness_station"),
        "text": ((sign_profile.get("label") or feature.get("text") or
                  feature.get("name") or feature.get("ref"))
                 if resolved_family in ("signage", "transit")
                 else feature.get("inscription") if kind == "plaque" else None),
        "provenance": feature.get("detail_source", "procedural_inference"),
    }


def residential_profile(scene):
    areas = [item for item in scene.get("areas", [])
             if str(item.get("type") or "").lower() == "residential"]
    buildings = [item for item in scene.get("buildings", []) if any(
        token in str(item.get("type") or "").lower()
        for token in ("house", "detached", "terrace", "bungalow",
                      "apartments", "residential", "dormitory"))]
    return {
        "detected": bool(areas or buildings),
        "zone_count": len(areas),
        "building_count": len(buildings),
        "subtypes": sorted({str(item.get("residential")) for item in areas
                            if item.get("residential")}),
        "source": "osm_tags",
    }


def detect(scene, style=None):
    cfg = (style or {}).get("urban_detail") or DEFAULT_CONFIG
    if cfg.get("enabled") is False:
        return False
    return bool(residential_profile(scene)["detected"] or any(
        item.get("kind") in OBJECT_SPECS for item in scene.get("special_features", [])))
