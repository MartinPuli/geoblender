"""Generic, source-aware football-stadium detail for the editable block build.

The module is identity-free: detection and layout use normalized OSM semantics,
geometry, and per-run style only.  Club colors, text, crests, verified stand
dimensions, and cardinal exceptions belong in output/<slug>/style.json.
"""

import math

import bmesh
import bpy
from mathutils import Matrix


FOOTBALL_SPORTS = {"soccer", "football", "futsal"}
STADIUM_TYPES = {"stadium", "grandstand", "arena"}


DEFAULT_CONFIG = {
    "enabled": "auto",
    "pitch_length": None,
    "pitch_width": None,
    "pitch_osm_id": None,
    "rows_long": 16,
    "rows_end": 12,
    "stand_depth_long": 22.0,
    "stand_depth_end": 17.0,
    "stand_height_long": 18.0,
    "stand_height_end": 13.0,
    # The stand envelope/roof height is not the same thing as the seating rake.
    # When unset, bowl height is derived from a realistic row rise and capped by
    # the stand envelope.  Per-run verified values may override either side.
    "bowl_height_long": None,
    "bowl_height_end": None,
    "first_row_height": 0.55,
    "row_rise": 0.46,
    "rake_curve": 0.20,
    "runoff": 6.0,
    "sections_long": 8,
    "sections_end": 5,
    "aisle_width": 1.25,
    "roof_enabled": True,
    "roof_sides": "auto",
    "roof_coverage": 0.78,
    "roof_alpha": 1.0,
    "floodlights": True,
    "floodlight_height": 34.0,
    "seat_pattern": "alternating_sections",
    "seat_spacing": 0.82,
    "max_seat_modules": 8000,
    "bowl_shape": "rectangular",
    "bowl_segments": 96,
    "bowl_exponent": 6.0,
    "tier_break_rows": [],
    "vomitory_count": 8,
    "vomitory_width": 4.2,
    "vomitory_row_span": 4,
    "exterior_skin": False,
    "exterior_skin_height": 10.5,
    "exterior_skin_offset": 1.8,
    "lighting_mode": "towers",
    "roof_ring_lights": 48,
    "signage_text": None,
    "primary_color": [0.10, 0.22, 0.55],
    "secondary_color": [0.78, 0.12, 0.10],
    "seat_color": [0.16, 0.28, 0.62],
    "concrete_color": [0.43, 0.44, 0.43],
    "roof_color": [0.28, 0.31, 0.34],
    "steel_color": [0.12, 0.14, 0.16],
    "safety_color": [0.86, 0.55, 0.05],
    "grass_color": [0.06, 0.31, 0.08],
    "grass_alt_color": [0.08, 0.39, 0.10],
}


def _deep_update(base, override):
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _deep_update(base[key], value)
        else:
            base[key] = value
    return base


def config_for(style):
    config = _deep_update(dict(DEFAULT_CONFIG), style.get("football_stadium") or {})
    return config


def _ring(points):
    result = [tuple(map(float, point[:2])) for point in (points or [])]
    if len(result) > 1 and math.hypot(result[0][0] - result[-1][0],
                                      result[0][1] - result[-1][1]) < 1e-6:
        result.pop()
    return result


def polygon_area(points):
    ring = _ring(points)
    if len(ring) < 3:
        return 0.0
    return abs(sum(
        ring[index][0] * ring[(index + 1) % len(ring)][1]
        - ring[(index + 1) % len(ring)][0] * ring[index][1]
        for index in range(len(ring)))) * 0.5


def centroid(points):
    ring = _ring(points)
    if not ring:
        return 0.0, 0.0
    return (sum(point[0] for point in ring) / len(ring),
            sum(point[1] for point in ring) / len(ring))


def principal_axis(points):
    ring = _ring(points)
    cx, cy = centroid(ring)
    xx = sum((x - cx) ** 2 for x, _ in ring)
    yy = sum((y - cy) ** 2 for _, y in ring)
    xy = sum((x - cx) * (y - cy) for x, y in ring)
    angle = 0.5 * math.atan2(2.0 * xy, xx - yy)
    return math.cos(angle), math.sin(angle)


def is_football_pitch(area):
    return (str(area.get("type") or "").lower() == "pitch"
            and str(area.get("sport") or "").lower() in FOOTBALL_SPORTS)


def is_stadium_building(building):
    tokens = {str(building.get(key) or "").lower()
              for key in ("type", "kind", "building_part")}
    return bool(tokens & STADIUM_TYPES)


def detect(scene, style=None):
    """Detect a football-stadium task from normalized semantics, not identity."""
    style = style or {}
    config = config_for(style)
    mode = config.get("enabled", "auto")
    if mode is False:
        return False
    if mode is True:
        return True
    if scene.get("scene_kind") == "football_stadium":
        return True
    profile = scene.get("stadium_profile") or {}
    if profile.get("football"):
        return True
    pitches = [area for area in scene.get("areas", []) if is_football_pitch(area)]
    stadiums = [item for item in scene.get("buildings", []) if is_stadium_building(item)]
    stadium_sites = [area for area in scene.get("areas", [])
                     if str(area.get("type") or "").lower() == "stadium"]
    return bool(pitches and (stadiums or stadium_sites))


def resolve_layout(scene, style=None):
    """Resolve a metric local stadium frame from the mapped pitch/site."""
    style = style or {}
    config = config_for(style)
    pitches = [area for area in scene.get("areas", []) if is_football_pitch(area)]
    stadium_buildings = [
        item for item in scene.get("buildings", []) if is_stadium_building(item)]
    stadium_sites = [
        area for area in scene.get("areas", [])
        if str(area.get("type") or "").lower() == "stadium"]

    focus = (style.get("focus") or {}).get("point") or [0.0, 0.0]
    focus = float(focus[0]), float(focus[1])
    preferred_id = config.get("pitch_osm_id")
    pitch = next((item for item in pitches
                  if preferred_id is not None
                  and str(item.get("osm_id")) == str(preferred_id)), None)
    if pitch is None and pitches:
        def pitch_score(item):
            c = centroid(item.get("polygon", []))
            distance = math.hypot(c[0] - focus[0], c[1] - focus[1])
            area = polygon_area(item.get("polygon", []))
            # Penalize tiny training/futsal fields when a full-size pitch is
            # available nearby, but keep proximity as the dominant selector.
            size_penalty = 120.0 if area < 2500.0 else 0.0
            return distance + size_penalty
        pitch = min(pitches, key=pitch_score)

    pitch_center = centroid((pitch or {}).get("polygon", [])) if pitch else focus
    site_candidates = stadium_sites or stadium_buildings
    site = min(
        site_candidates,
        key=lambda item: math.hypot(
            centroid(item.get("polygon") or item.get("footprint") or [])[0] - pitch_center[0],
            centroid(item.get("polygon") or item.get("footprint") or [])[1] - pitch_center[1]),
    ) if site_candidates else None
    pitch_points = ((pitch or {}).get("polygon") or
                    (site or {}).get("polygon") or
                    (site or {}).get("footprint") or [])
    if len(_ring(pitch_points)) < 3:
        return None

    center = centroid(pitch_points)
    ux, uy = principal_axis(pitch_points)
    vx, vy = -uy, ux
    projections_u = [(x - center[0]) * ux + (y - center[1]) * uy
                     for x, y in _ring(pitch_points)]
    projections_v = [(x - center[0]) * vx + (y - center[1]) * vy
                     for x, y in _ring(pitch_points)]
    extent_u = max(projections_u) - min(projections_u)
    extent_v = max(projections_v) - min(projections_v)
    if extent_v > extent_u:
        ux, uy, vx, vy = vx, vy, -ux, -uy
        extent_u, extent_v = extent_v, extent_u

    measured_length = extent_u if pitch else 0.0
    measured_width = extent_v if pitch else 0.0
    length = config.get("pitch_length")
    width = config.get("pitch_width")
    length = float(length) if length else (measured_length if 80.0 <= measured_length <= 125.0 else 105.0)
    width = float(width) if width else (measured_width if 45.0 <= measured_width <= 90.0 else 68.0)

    roof_setting = config.get("roof_sides", "auto")
    roof_side_source = "style"
    if isinstance(roof_setting, str) and roof_setting.lower() == "auto":
        mapped_sides = set()
        max_distance = max(length, width) * 0.5 + max(
            float(config["stand_depth_long"]), float(config["stand_depth_end"])) + 30.0
        for item in scene.get("buildings", []):
            open_roof = (str(item.get("structure_mode") or "").lower() == "roof_only"
                         or str(item.get("type") or "").lower() in
                         {"roof", "canopy", "carport"})
            if not open_roof or polygon_area(item.get("footprint", [])) < 120.0:
                continue
            roof_center = centroid(item.get("footprint", []))
            dx, dy = roof_center[0] - center[0], roof_center[1] - center[1]
            du, dv = dx * ux + dy * uy, dx * vx + dy * vy
            if math.hypot(du, dv) > max_distance:
                continue
            if abs(dv) / max(1.0, width) >= abs(du) / max(1.0, length):
                mapped_sides.add("north" if dv >= 0 else "south")
            else:
                mapped_sides.add("east" if du >= 0 else "west")
        if mapped_sides:
            config["roof_sides"] = sorted(mapped_sides)
            roof_side_source = "osm_roof_footprints"
        else:
            config["roof_sides"] = ["north", "south"]
            roof_side_source = "procedural_default"

    suppression_radius = (max(length, width) * 0.5
                          + max(float(config["stand_depth_long"]),
                                float(config["stand_depth_end"])) + 35.0)
    suppressed = []
    for item in stadium_buildings:
        item_center = centroid(item.get("footprint", []))
        if (item.get("osm_id") is not None
                and math.hypot(item_center[0] - center[0],
                               item_center[1] - center[1]) <= suppression_radius
                and item.get("osm_id") not in suppressed):
            suppressed.append(item.get("osm_id"))
    # When the specialized build supplies its own verified/configured roof,
    # suppress only large mapped open-cover footprints centered on this pitch.
    # Otherwise a generic filled roof slab can incorrectly cap the field.
    if config.get("roof_enabled", True):
        pitch_area = max(1.0, length * width)
        for item in scene.get("buildings", []):
            open_roof = (str(item.get("structure_mode") or "").lower() == "roof_only"
                         or str(item.get("type") or "").lower() in
                         {"roof", "canopy", "carport"})
            footprint = item.get("footprint", [])
            item_center = centroid(footprint)
            if (open_roof and item.get("osm_id") is not None
                    and polygon_area(footprint) >= pitch_area * 0.35
                    and math.hypot(item_center[0] - center[0],
                                   item_center[1] - center[1]) <= max(length, width) * 0.35
                    and item.get("osm_id") not in suppressed):
                suppressed.append(item.get("osm_id"))
    # OSM Simple 3D stadiums often contain hundreds of building:part wedges
    # under one outline.  If the specialized stadium replaces one mapped roof
    # or shell part, it must replace its siblings too; otherwise both systems
    # occupy the bowl and the generic parts hide the generated seats.
    suppressed_outline_ids = {
        str(item.get("outline_osm_id"))
        for item in scene.get("buildings", [])
        if item.get("outline_osm_id") is not None
        and str(item.get("osm_id")) in {str(value) for value in suppressed}
    }
    if suppressed_outline_ids:
        for item in scene.get("buildings", []):
            if (item.get("is_building_part")
                    and str(item.get("outline_osm_id")) in suppressed_outline_ids
                    and item.get("osm_id") is not None
                    and item.get("osm_id") not in suppressed):
                suppressed.append(item.get("osm_id"))
    return {
        "center": center,
        "axis_u": (ux, uy),
        "axis_v": (vx, vy),
        "angle": math.atan2(uy, ux),
        "pitch_length": round(length, 3),
        "pitch_width": round(width, 3),
        "pitch_osm_id": (pitch or {}).get("osm_id"),
        "pitch_source": "osm" if pitch else "inferred_football_standard",
        "site_osm_id": (site or {}).get("osm_id"),
        "suppressed_building_ids": suppressed,
        "suppressed_building_part_count": sum(
            1 for item in scene.get("buildings", [])
            if item.get("is_building_part")
            and item.get("osm_id") in suppressed),
        "roof_side_source": roof_side_source,
        "config": config,
    }


def _world(layout, u, v):
    cx, cy = layout["center"]
    ux, uy = layout["axis_u"]
    vx, vy = layout["axis_v"]
    return cx + ux * u + vx * v, cy + uy * u + vy * v


def _add_box(bm, layout, u, v, z, du, dv, dz, yaw=0.0):
    x, y = _world(layout, u, v)
    matrix = (Matrix.Translation((x, y, z))
              @ Matrix.Rotation(layout["angle"] + yaw, 4, "Z")
              @ Matrix.Diagonal((du, dv, dz, 1.0)))
    bmesh.ops.create_cube(bm, size=1.0, matrix=matrix)


def _add_cylinder(bm, layout, u, v, base, radius, height, segments=10):
    x, y = _world(layout, u, v)
    bmesh.ops.create_cone(
        bm, cap_ends=True, cap_tris=False, segments=max(6, int(segments)),
        radius1=radius, radius2=radius, depth=height,
        matrix=Matrix.Translation((x, y, base + height / 2.0)))


def _superellipse_point(a, b, angle, exponent):
    """Return a rounded-rectangle/oval point in the local pitch frame."""
    power = 2.0 / max(2.0, float(exponent))
    c, s = math.cos(angle), math.sin(angle)
    return (a * math.copysign(abs(c) ** power, c),
            b * math.copysign(abs(s) ** power, s))


def bowl_row_profile(config, rows, row, side="long"):
    """Return terrace top/rise using a bounded, progressively steeper rake.

    ``stand_height_*`` remains the structural envelope.  The bowl gets its own
    height so a tall facade or roof does not turn every seating row into a wall.
    This helper is pure on purpose: CI can regression-test the geometry policy.
    """
    rows = max(1, int(rows))
    row = min(rows - 1, max(0, int(row)))
    first = max(0.20, float(config.get("first_row_height", 0.55)))
    curve = min(0.65, max(0.0, float(config.get("rake_curve", 0.20))))
    nominal_rise = min(0.62, max(0.30, float(config.get("row_rise", 0.46))))
    envelope = max(1.0, float(config.get("stand_height_%s" % side, 18.0)))
    configured = config.get("bowl_height_%s" % side)
    if configured is None:
        target = min(envelope, first + nominal_rise * rows * (1.0 + curve * 0.5))
    else:
        target = min(envelope, max(first + rows * 0.30, float(configured)))
    available = max(rows * 0.30, target - first)
    weights = [1.0 + curve * (index / max(1, rows - 1))
               for index in range(rows)]
    scale = available / sum(weights)
    rises = [weight * scale for weight in weights]
    top = first + sum(rises[:row + 1])
    return {"top": top, "rise": rises[row], "bowl_height": first + sum(rises)}


def oval_access_mask(index, segments, section_count, row, rows, config):
    """Classify an oval terrace cell without allowing access/seat overlap."""
    section_phase = (index * section_count / max(1, segments)) % 1.0
    # One mesh segment is the minimum editable aisle at this LOD.  Selecting
    # the closest segment to each section boundary avoids the old modulo bug
    # that turned roughly a quarter of the entire bowl into giant wedges.
    aisle = min(section_phase, 1.0 - section_phase) <= (
        0.5 * section_count / max(1, segments))
    tier_break = int(row) in {int(v) for v in (config.get("tier_break_rows") or [])}

    count = max(0, int(config.get("vomitory_count", 8)))
    span = max(1, int(config.get("vomitory_row_span", 4)))
    center_row = min(rows - 1, max(0, int(round(rows * 0.38))))
    in_rows = abs(int(row) - center_row) <= span // 2
    t = 2.0 * math.pi * (index + 0.5) / max(1, segments)
    vomitory = False
    if count and in_rows:
        half_angle = math.pi / max(1, segments)
        for portal in range(count):
            center = 2.0 * math.pi * (portal + 0.5) / count
            delta = abs((t - center + math.pi) % (2.0 * math.pi) - math.pi)
            if delta <= half_angle:
                vomitory = True
                break
    return {"aisle": aisle, "tier_break": tier_break, "vomitory": vomitory}


def _add_ring_segment(bm, layout, a, b, t0, t1, exponent,
                      z, radial_depth, height, inset=0.0):
    p0 = _superellipse_point(a - inset, b - inset, t0, exponent)
    p1 = _superellipse_point(a - inset, b - inset, t1, exponent)
    u, v = (p0[0] + p1[0]) * 0.5, (p0[1] + p1[1]) * 0.5
    du, dv = p1[0] - p0[0], p1[1] - p0[1]
    chord = max(0.08, math.hypot(du, dv))
    yaw = math.atan2(dv, du)
    _add_box(bm, layout, u, v, z, chord + 0.05,
             max(0.04, radial_depth), height, yaw=yaw)
    return (u, v, yaw, chord)


def _finalize(name, bm, material, collection):
    if not bm.faces:
        bm.free()
        return None
    mesh = bpy.data.meshes.new(name)
    bm.to_mesh(mesh)
    bm.free()
    obj = bpy.data.objects.new(name, mesh)
    obj.data.materials.append(material)
    obj["stadium_detail"] = True
    obj["provenance"] = "osm_or_procedural_inference"
    collection.objects.link(obj)
    return obj


def _collection(name, parent):
    collection = bpy.data.collections.get(name) or bpy.data.collections.new(name)
    if collection.name not in parent.children:
        try:
            parent.children.link(collection)
        except RuntimeError:
            pass
    return collection


def _material(factory, name, rgb, roughness=0.75, metallic=0.0):
    return factory(name, rgb, roughness=roughness, metallic=metallic)


def _pitch_geometry(layout, ground, mats, collection, report):
    length, width = layout["pitch_length"], layout["pitch_width"]
    turf = bmesh.new()
    stripe_count = 12
    stripe_length = length / stripe_count
    for index in range(stripe_count):
        _add_box(turf, layout, -length / 2 + stripe_length * (index + 0.5), 0,
                 ground + 0.06, stripe_length + 0.02, width, 0.12)
    turf_obj = _finalize("Stadium_Turf_Stripes", turf, mats["grass"], collection)

    alt = bmesh.new()
    for index in range(0, stripe_count, 2):
        _add_box(alt, layout, -length / 2 + stripe_length * (index + 0.5), 0,
                 ground + 0.125, stripe_length - 0.04, width - 0.08, 0.015)
    _finalize("Stadium_Turf_Alternate", alt, mats["grass_alt"], collection)

    line = 0.11
    markings = bmesh.new()
    for u, v, du, dv in (
            (0, -width / 2, length, line), (0, width / 2, length, line),
            (-length / 2, 0, line, width), (length / 2, 0, line, width),
            (0, 0, line, width)):
        _add_box(markings, layout, u, v, ground + 0.142, du, dv, 0.018)
    for side in (-1, 1):
        goal_u = side * length / 2
        for depth, box_width in ((16.5, 40.32), (5.5, 18.32)):
            inner_u = goal_u - side * depth
            _add_box(markings, layout, inner_u, 0, ground + 0.142,
                     line, box_width, 0.018)
            for v in (-box_width / 2, box_width / 2):
                _add_box(markings, layout, goal_u - side * depth / 2, v,
                         ground + 0.142, depth, line, 0.018)
        _add_cylinder(markings, layout, goal_u - side * 11.0, 0,
                      ground + 0.14, 0.10, 0.025, 10)

    segments = 64
    radius = 9.15
    for index in range(segments):
        a = 2.0 * math.pi * index / segments
        b = 2.0 * math.pi * (index + 1) / segments
        u = radius * (math.cos(a) + math.cos(b)) / 2.0
        v = radius * (math.sin(a) + math.sin(b)) / 2.0
        chord = 2.0 * radius * math.sin(math.pi / segments)
        _add_box(markings, layout, u, v, ground + 0.142, chord, line, 0.018,
                 yaw=(a + b) / 2.0 + math.pi / 2.0)
    _add_cylinder(markings, layout, 0, 0, ground + 0.14, 0.10, 0.025, 10)
    _finalize("Stadium_Pitch_Markings", markings, mats["white"], collection)

    goals = bmesh.new()
    nets = bmesh.new()
    goal_width, goal_height, goal_depth = 7.32, 2.44, 2.0
    for side in (-1, 1):
        u = side * (length / 2 + 0.03)
        for v in (-goal_width / 2, goal_width / 2):
            _add_cylinder(goals, layout, u, v, ground + 0.15, 0.055,
                          goal_height, 8)
        _add_box(goals, layout, u, 0, ground + 0.15 + goal_height,
                 0.10, goal_width + 0.10, 0.10)
        back_u = u + side * goal_depth
        for v in (-goal_width / 2, goal_width / 2):
            _add_cylinder(goals, layout, back_u, v, ground + 0.15, 0.04,
                          goal_height, 8)
        for index in range(9):
            v = -goal_width / 2 + goal_width * index / 8.0
            _add_box(nets, layout, u + side * goal_depth / 2, v,
                     ground + 0.15 + goal_height / 2,
                     goal_depth, 0.018, goal_height)
        for index in range(5):
            z = ground + 0.15 + goal_height * index / 4.0
            _add_box(nets, layout, u + side * goal_depth / 2, 0, z,
                     goal_depth, goal_width, 0.014)
    _finalize("Stadium_Goals", goals, mats["white"], collection)
    _finalize("Stadium_Goal_Nets", nets, mats["net"], collection)
    report.update({"pitch_stripes": stripe_count, "pitch_marking_segments": segments + 16,
                   "goals": 2, "goal_net_lines": 28,
                   "pitch_source": layout["pitch_source"]})


def _stand_rows(layout, ground, mats, collection, report):
    cfg = layout["config"]
    if str(cfg.get("bowl_shape", "rectangular")).lower() in {
            "oval", "elliptical", "continuous_oval"}:
        return _continuous_oval_stands(layout, ground, mats, collection, report)
    length, width = layout["pitch_length"], layout["pitch_width"]
    runoff = float(cfg["runoff"])
    concrete, seats_primary, seats_secondary, safety, dark = (
        bmesh.new(), bmesh.new(), bmesh.new(), bmesh.new(), bmesh.new())
    rows_built = sections_built = aisle_steps = vomitories = seat_modules = 0
    cleared_seat_cells = 0
    max_row_rise = bowl_top_height = 0.0
    seat_spacing = max(0.65, float(cfg.get("seat_spacing", 0.82)))
    seat_cap = max(100, int(cfg.get("max_seat_modules", 8000)))

    def seat_target(section):
        if str(cfg.get("seat_pattern", "")).lower() == "alternating_sections":
            return seats_secondary if section % 2 else seats_primary
        return seats_primary

    def long_stand(side, side_name):
        nonlocal rows_built, sections_built, aisle_steps, vomitories, seat_modules
        nonlocal cleared_seat_cells, max_row_rise, bowl_top_height
        rows = max(6, int(cfg["rows_long"]))
        depth = float(cfg["stand_depth_long"])
        height = float(cfg["stand_height_long"])
        sections = max(3, int(cfg["sections_long"]))
        total = length + 18.0
        aisle = min(2.0, float(cfg["aisle_width"]))
        section_width = (total - aisle * (sections - 1)) / sections
        row_depth = depth / rows
        inner = width / 2 + runoff
        portal_centers = (-total * 0.24, total * 0.24)
        portal_width = max(2.4, float(cfg.get("vomitory_width", 4.2)))
        portal_span = max(1, int(cfg.get("vomitory_row_span", 4)))
        portal_row = min(rows - 1, max(0, int(round(rows * 0.34))))
        for row in range(rows):
            profile = bowl_row_profile(cfg, rows, row, "long")
            rise = profile["rise"]
            terrace_top = ground + profile["top"]
            z = terrace_top - rise * 0.5
            max_row_rise = max(max_row_rise, rise)
            bowl_top_height = max(bowl_top_height, profile["bowl_height"])
            v = side * (inner + row_depth * (row + 0.5))
            for section in range(sections):
                u = -total / 2 + section_width / 2 + section * (section_width + aisle)
                _add_box(concrete, layout, u, v, z, section_width,
                         row_depth - 0.04, rise)
                count = max(1, int(section_width / seat_spacing))
                seat_w = min(seat_spacing * 0.76, section_width / count * 0.82)
                target = seat_target(section)
                for seat_index in range(count):
                    if seat_modules >= seat_cap:
                        break
                    seat_u = u - section_width / 2 + section_width * (seat_index + 0.5) / count
                    blocked = (abs(row - portal_row) <= portal_span // 2
                               and any(abs(seat_u - center) <= portal_width * 0.5
                                       for center in portal_centers))
                    if blocked:
                        cleared_seat_cells += 1
                        continue
                    seat_v = v - side * row_depth * 0.18
                    _add_box(target, layout, seat_u, seat_v, terrace_top + 0.07,
                             seat_w, row_depth * 0.42, 0.12)
                    _add_box(target, layout, seat_u,
                             seat_v + side * row_depth * 0.18,
                             terrace_top + 0.26, seat_w,
                             max(0.07, row_depth * 0.10), 0.38)
                    seat_modules += 1
                sections_built += 1
            for aisle_index in range(1, sections):
                u = -total / 2 + aisle_index * (section_width + aisle) - aisle / 2
                _add_box(safety, layout, u, v, terrace_top + 0.025,
                         aisle * 0.70, row_depth * 0.82, 0.06)
                aisle_steps += 1
            rows_built += 1
        portal_profile = bowl_row_profile(cfg, rows, portal_row, "long")
        portal_floor = ground + portal_profile["top"] - portal_profile["rise"]
        for u in portal_centers:
            v = side * (inner + depth * 0.34)
            _add_box(dark, layout, u, v, portal_floor - 0.08,
                     portal_width, row_depth * portal_span, 0.14)
            for offset in (-1.0, 1.0):
                _add_box(dark, layout, u + offset * portal_width * 0.48, v,
                         portal_floor + 1.45, 0.16,
                         row_depth * portal_span, 2.9)
            _add_box(dark, layout, u, v, portal_floor + 2.92,
                     portal_width, row_depth * portal_span, 0.18)
            vomitories += 1
        report["stand_sides"].append(side_name)

    def end_stand(side, side_name):
        nonlocal rows_built, sections_built, aisle_steps, vomitories, seat_modules
        nonlocal cleared_seat_cells, max_row_rise, bowl_top_height
        rows = max(5, int(cfg["rows_end"]))
        depth = float(cfg["stand_depth_end"])
        height = float(cfg["stand_height_end"])
        sections = max(3, int(cfg["sections_end"]))
        total = width + 16.0
        aisle = min(2.0, float(cfg["aisle_width"]))
        section_width = (total - aisle * (sections - 1)) / sections
        row_depth = depth / rows
        inner = length / 2 + runoff
        portal_width = max(2.4, float(cfg.get("vomitory_width", 4.2)))
        portal_span = max(1, int(cfg.get("vomitory_row_span", 4)))
        portal_row = min(rows - 1, max(0, int(round(rows * 0.34))))
        for row in range(rows):
            profile = bowl_row_profile(cfg, rows, row, "end")
            rise = profile["rise"]
            terrace_top = ground + profile["top"]
            z = terrace_top - rise * 0.5
            max_row_rise = max(max_row_rise, rise)
            bowl_top_height = max(bowl_top_height, profile["bowl_height"])
            u = side * (inner + row_depth * (row + 0.5))
            for section in range(sections):
                v = -total / 2 + section_width / 2 + section * (section_width + aisle)
                _add_box(concrete, layout, u, v, z,
                         row_depth - 0.04, section_width, rise)
                count = max(1, int(section_width / seat_spacing))
                seat_w = min(seat_spacing * 0.76, section_width / count * 0.82)
                target = seat_target(section)
                for seat_index in range(count):
                    if seat_modules >= seat_cap:
                        break
                    seat_v = v - section_width / 2 + section_width * (seat_index + 0.5) / count
                    if (abs(row - portal_row) <= portal_span // 2
                            and abs(seat_v) <= portal_width * 0.5):
                        cleared_seat_cells += 1
                        continue
                    seat_u = u - side * row_depth * 0.18
                    _add_box(target, layout, seat_u, seat_v, terrace_top + 0.07,
                             row_depth * 0.42, seat_w, 0.12)
                    _add_box(target, layout,
                             seat_u + side * row_depth * 0.18, seat_v,
                             terrace_top + 0.26,
                             max(0.07, row_depth * 0.10), seat_w, 0.38)
                    seat_modules += 1
                sections_built += 1
            for aisle_index in range(1, sections):
                v = -total / 2 + aisle_index * (section_width + aisle) - aisle / 2
                _add_box(safety, layout, u, v, terrace_top + 0.025,
                         row_depth * 0.82, aisle * 0.70, 0.06)
                aisle_steps += 1
            rows_built += 1
        portal_profile = bowl_row_profile(cfg, rows, portal_row, "end")
        portal_floor = ground + portal_profile["top"] - portal_profile["rise"]
        portal_u = side * (inner + depth * 0.34)
        _add_box(dark, layout, portal_u, 0, portal_floor - 0.08,
                 row_depth * portal_span, portal_width, 0.14)
        for offset in (-1.0, 1.0):
            _add_box(dark, layout, portal_u, offset * portal_width * 0.48,
                     portal_floor + 1.45, row_depth * portal_span, 0.16, 2.9)
        _add_box(dark, layout, portal_u, 0, portal_floor + 2.92,
                 row_depth * portal_span, portal_width, 0.18)
        vomitories += 1
        report["stand_sides"].append(side_name)

    long_stand(1, "north")
    long_stand(-1, "south")
    end_stand(1, "east")
    end_stand(-1, "west")
    _finalize("Stadium_Concrete_Terraces", concrete, mats["concrete"], collection)
    _finalize("Stadium_Seats_Primary", seats_primary, mats["seat_primary"], collection)
    _finalize("Stadium_Seats_Secondary", seats_secondary, mats["seat_secondary"], collection)
    _finalize("Stadium_Safety_Aisles", safety, mats["safety"], collection)
    _finalize("Stadium_Vomitories", dark, mats["dark"], collection)
    report.update({"stand_rows": rows_built, "stand_sections": sections_built,
                   "seat_modules": seat_modules,
                   "aisle_steps": aisle_steps, "vomitories": vomitories,
                   "seat_clearance_cells": cleared_seat_cells,
                   "seat_aisle_overlap_cells": 0,
                   "seat_vomitory_overlap_cells": 0,
                   "bowl_top_height": round(bowl_top_height, 3),
                   "structure_height": round(max(float(cfg["stand_height_long"]),
                                                 float(cfg["stand_height_end"])), 3),
                   "max_row_rise": round(max_row_rise, 3)})


def _continuous_oval_stands(layout, ground, mats, collection, report):
    """Build a continuous superelliptical seating bowl around the pitch."""
    cfg = layout["config"]
    length, width = layout["pitch_length"], layout["pitch_width"]
    runoff = float(cfg["runoff"])
    rows = max(10, int(max(cfg["rows_long"], cfg["rows_end"])))
    depth = float(max(cfg["stand_depth_long"], cfg["stand_depth_end"]))
    structure_height = float(max(cfg["stand_height_long"], cfg["stand_height_end"]))
    section_count = max(12, int(cfg["sections_long"]) * 2
                        + int(cfg["sections_end"]) * 2)
    # Seating needs finer tangential resolution than the roof shell.  Eight
    # cells per section keeps a 1-2 m aisle from swallowing a 4 m mesh wedge.
    segments = max(96, int(cfg.get("bowl_segments", 96)), section_count * 8)
    exponent = max(2.0, float(cfg.get("bowl_exponent", 6.0)))
    row_depth = depth / rows
    seat_spacing = max(0.65, float(cfg.get("seat_spacing", 0.82)))
    seat_cap = max(100, int(cfg.get("max_seat_modules", 8000)))
    tier_breaks = {int(value) for value in (cfg.get("tier_break_rows") or [])}
    concrete, seats_primary, seats_secondary = bmesh.new(), bmesh.new(), bmesh.new()
    safety, dark = bmesh.new(), bmesh.new()
    seat_modules = aisle_steps = cleared_seat_cells = 0
    max_row_rise = bowl_top_height = 0.0

    for row in range(rows):
        profile = bowl_row_profile(cfg, rows, row, "long")
        rise = profile["rise"]
        terrace_top = ground + profile["top"]
        z = terrace_top - rise * 0.5
        max_row_rise = max(max_row_rise, rise)
        bowl_top_height = max(bowl_top_height, profile["bowl_height"])
        a = length / 2 + runoff + row_depth * (row + 0.5)
        b = width / 2 + runoff + row_depth * (row + 0.5)
        for index in range(segments):
            t0 = 2.0 * math.pi * index / segments
            t1 = 2.0 * math.pi * (index + 1) / segments
            section = int(index * section_count / segments)
            access = oval_access_mask(index, segments, section_count,
                                      row, rows, cfg)
            aisle = access["aisle"]
            tier_break = access["tier_break"]
            vomitory = access["vomitory"]
            # A vomitory is an actual opening: no terrace prism and no seats.
            if vomitory:
                cleared_seat_cells += 1
                continue
            u, v, yaw, chord = _add_ring_segment(
                concrete, layout, a, b, t0, t1, exponent, z,
                row_depth - 0.035, rise)
            # Access surfaces are thin overlays on the concrete rake, never
            # full-height wedges capable of hiding neighboring seat modules.
            if aisle:
                _add_ring_segment(safety, layout, a, b, t0, t1, exponent,
                                  terrace_top + 0.025,
                                  row_depth * 0.72, 0.05)
                aisle_steps += 1
            if tier_break:
                _add_ring_segment(dark, layout, a, b, t0, t1, exponent,
                                  terrace_top + 0.02,
                                  row_depth - 0.07, 0.04)
            if aisle or tier_break:
                continue
            seat_target = (seats_secondary if
                           str(cfg.get("seat_pattern", "")).lower()
                           == "alternating_sections" and section % 2
                           else seats_primary)
            count = max(1, int(chord / seat_spacing))
            tangent = (math.cos(yaw), math.sin(yaw))
            seat_w = min(seat_spacing * 0.74, chord / count * 0.82)
            for seat_index in range(count):
                if seat_modules >= seat_cap:
                    break
                offset = chord * ((seat_index + 0.5) / count - 0.5)
                su, sv = u + tangent[0] * offset, v + tangent[1] * offset
                _add_box(seat_target, layout, su, sv, terrace_top + 0.07,
                         seat_w, row_depth * 0.40, 0.12, yaw=yaw)
                _add_box(seat_target, layout, su, sv, terrace_top + 0.26,
                         seat_w, max(0.07, row_depth * 0.10), 0.38, yaw=yaw)
                seat_modules += 1

    vomitories = 0
    portal_count = max(0, int(cfg.get("vomitory_count", 8)))
    portal_width = max(2.4, float(cfg.get("vomitory_width", 4.2)))
    portal_span = max(1, int(cfg.get("vomitory_row_span", 4)))
    portal_row = min(rows - 1, max(0, int(round(rows * 0.38))))
    portal_profile = bowl_row_profile(cfg, rows, portal_row, "long")
    portal_floor = ground + portal_profile["top"] - portal_profile["rise"]
    portal_depth = max(2.2, row_depth * portal_span)
    portal_a = length / 2 + runoff + depth * 0.38
    portal_b = width / 2 + runoff + depth * 0.38
    for index in range(portal_count):
        t = 2.0 * math.pi * (index + 0.5) / max(1, portal_count)
        u, v = _superellipse_point(portal_a, portal_b, t, exponent)
        yaw = t + math.pi / 2.0
        # Recessed floor, slim jambs, and lintel describe the opening while
        # leaving the cleared seating volume physically empty.
        _add_box(dark, layout, u, v, portal_floor - 0.08,
                 portal_width, portal_depth, 0.14, yaw=yaw)
        for offset in (-1.0, 1.0):
            tangent_u, tangent_v = math.cos(yaw), math.sin(yaw)
            ju = u + tangent_u * offset * portal_width * 0.48
            jv = v + tangent_v * offset * portal_width * 0.48
            _add_box(dark, layout, ju, jv, portal_floor + 1.45,
                     0.16, portal_depth, 2.9, yaw=yaw)
        _add_box(dark, layout, u, v, portal_floor + 2.92,
                 portal_width, portal_depth, 0.18, yaw=yaw)
        vomitories += 1

    _finalize("Stadium_Continuous_Terraces", concrete, mats["concrete"], collection)
    _finalize("Stadium_Seats_Primary", seats_primary, mats["seat_primary"], collection)
    _finalize("Stadium_Seats_Secondary", seats_secondary, mats["seat_secondary"], collection)
    _finalize("Stadium_Safety_Aisles", safety, mats["safety"], collection)
    _finalize("Stadium_Vomitories", dark, mats["dark"], collection)
    report["stand_sides"].extend(["north", "south", "east", "west"])
    report.update({
        "bowl_shape": "continuous_oval",
        "continuous_rows": rows,
        "tier_break_rows": sorted(tier_breaks),
        "bowl_segments": segments,
        "stand_rows": rows * 4,
        "stand_sections": rows * section_count,
        "seat_modules": seat_modules,
        "aisle_steps": aisle_steps,
        "vomitories": vomitories,
        "seat_clearance_cells": cleared_seat_cells,
        "seat_aisle_overlap_cells": 0,
        "seat_vomitory_overlap_cells": 0,
        "bowl_top_height": round(bowl_top_height, 3),
        "structure_height": round(structure_height, 3),
        "max_row_rise": round(max_row_rise, 3),
    })


def _structure_and_roofs(layout, ground, mats, collections, report):
    cfg = layout["config"]
    if str(cfg.get("bowl_shape", "rectangular")).lower() in {
            "oval", "elliptical", "continuous_oval"}:
        return _continuous_oval_structure(layout, ground, mats, collections, report)
    length, width = layout["pitch_length"], layout["pitch_width"]
    runoff = float(cfg["runoff"])
    frames, rails, roofs, trusses = (bmesh.new(), bmesh.new(),
                                     bmesh.new(), bmesh.new())
    columns = beams = rail_segments = roof_panels = roof_supports = 0

    for side in (-1, 1):
        depth, height = float(cfg["stand_depth_long"]), float(cfg["stand_height_long"])
        outer_v = side * (width / 2 + runoff + depth)
        total = length + 18.0
        bays = max(6, int(total / 12.0))
        for index in range(bays + 1):
            u = -total / 2 + total * index / bays
            _add_box(frames, layout, u, outer_v, ground + height / 2,
                     0.42, 0.42, height)
            columns += 1
        for level in (0.28, 0.55, 0.82):
            _add_box(frames, layout, 0, outer_v, ground + height * level,
                     total, 0.38, 0.38)
            beams += 1
        inner_v = side * (width / 2 + runoff - 0.45)
        for z in (ground + 1.1, ground + 2.25):
            _add_box(rails, layout, 0, inner_v, z, total, 0.08, 0.08)
            rail_segments += 1

    for side in (-1, 1):
        depth, height = float(cfg["stand_depth_end"]), float(cfg["stand_height_end"])
        outer_u = side * (length / 2 + runoff + depth)
        total = width + 16.0
        bays = max(5, int(total / 11.0))
        for index in range(bays + 1):
            v = -total / 2 + total * index / bays
            _add_box(frames, layout, outer_u, v, ground + height / 2,
                     0.42, 0.42, height)
            columns += 1
        for level in (0.34, 0.68):
            _add_box(frames, layout, outer_u, 0, ground + height * level,
                     0.38, total, 0.38)
            beams += 1
        inner_u = side * (length / 2 + runoff - 0.45)
        for z in (ground + 1.1, ground + 2.25):
            _add_box(rails, layout, inner_u, 0, z, 0.08, total, 0.08)
            rail_segments += 1

    roof_sides = set(str(value).lower() for value in cfg.get("roof_sides", []))
    if cfg.get("roof_enabled", True):
        for side, name in ((1, "north"), (-1, "south")):
            if name not in roof_sides:
                continue
            depth = float(cfg["stand_depth_long"])
            height = float(cfg["stand_height_long"])
            total = length + 20.0
            roof_depth = depth * float(cfg.get("roof_coverage", 0.78))
            v = side * (width / 2 + runoff + depth * 0.56)
            _add_box(roofs, layout, 0, v, ground + height + 4.2,
                     total, roof_depth, 0.36)
            roof_panels += 1
            bays = max(5, int(total / 18.0))
            outer_v = side * (width / 2 + runoff + depth * 0.94)
            for index in range(bays + 1):
                u = -total / 2 + total * index / bays
                _add_box(trusses, layout, u, outer_v,
                         ground + (height + 4.2) / 2,
                         0.34, 0.34, height + 4.2)
                _add_box(trusses, layout, u, v, ground + height + 3.8,
                         0.26, roof_depth, 0.26)
                roof_supports += 1

    _finalize("Stadium_Rear_Structure", frames, mats["concrete"], collections["structure"])
    _finalize("Stadium_Railings", rails, mats["steel"], collections["details"])
    _finalize("Stadium_Stand_Roofs", roofs, mats["roof"], collections["roof"])
    _finalize("Stadium_Roof_Trusses", trusses, mats["steel"], collections["roof"])
    report.update({"rear_columns": columns, "rear_beams": beams,
                   "railing_segments": rail_segments, "roof_panels": roof_panels,
                   "roof_supports": roof_supports})


def _continuous_oval_structure(layout, ground, mats, collections, report):
    """Build the exposed frame, patterned outer drum, and continuous roof ring."""
    cfg = layout["config"]
    length, width = layout["pitch_length"], layout["pitch_width"]
    runoff = float(cfg["runoff"])
    depth = float(max(cfg["stand_depth_long"], cfg["stand_depth_end"]))
    height = float(max(cfg["stand_height_long"], cfg["stand_height_end"]))
    segments = max(48, int(cfg.get("bowl_segments", 96)))
    exponent = max(2.0, float(cfg.get("bowl_exponent", 6.0)))
    outer_a, outer_b = length / 2 + runoff + depth, width / 2 + runoff + depth
    frames, rails, roofs, trusses = bmesh.new(), bmesh.new(), bmesh.new(), bmesh.new()
    skin_primary, skin_secondary, portals = bmesh.new(), bmesh.new(), bmesh.new()
    columns = beams = rail_segments = roof_panels = roof_supports = skin_panels = 0

    # A continuous exposed concrete skeleton around the outer perimeter.
    for index in range(segments):
        t0 = 2.0 * math.pi * index / segments
        t1 = 2.0 * math.pi * (index + 1) / segments
        if index % 3 == 0:
            u, v = _superellipse_point(outer_a, outer_b, t0, exponent)
            _add_box(frames, layout, u, v, ground + height / 2,
                     0.46, 0.46, height, yaw=t0)
            columns += 1
        for level in (0.28, 0.55, 0.82):
            _add_ring_segment(frames, layout, outer_a, outer_b, t0, t1,
                              exponent, ground + height * level,
                              0.34, 0.34)
            beams += 1
        inner_a, inner_b = length / 2 + runoff - 0.45, width / 2 + runoff - 0.45
        for z in (ground + 1.1, ground + 2.25):
            _add_ring_segment(rails, layout, inner_a, inner_b, t0, t1,
                              exponent, z, 0.07, 0.07)
            rail_segments += 1

        if cfg.get("exterior_skin", False):
            skin_h = min(height * 0.72, float(cfg.get("exterior_skin_height", 10.5)))
            skin_offset = max(0.35, float(cfg.get("exterior_skin_offset", 1.8)))
            # Keep regular dark access portals between groups of facade fins.
            if index % max(8, segments // 12) == 0:
                _add_ring_segment(portals, layout, outer_a + skin_offset,
                                  outer_b + skin_offset,
                                  t0, t1, exponent, ground + 2.2,
                                  0.28, 4.4)
            else:
                target = skin_secondary if (index // 3) % 2 else skin_primary
                _add_ring_segment(target, layout, outer_a + skin_offset,
                                  outer_b + skin_offset,
                                  t0, t1, exponent, ground + skin_h / 2,
                                  0.22, skin_h)
                skin_panels += 1

    if cfg.get("roof_enabled", True):
        coverage = min(1.0, max(0.2, float(cfg.get("roof_coverage", 0.78))))
        roof_depth = depth * coverage
        roof_a = outer_a - roof_depth * 0.48
        roof_b = outer_b - roof_depth * 0.48
        roof_z = ground + height + 4.2
        for index in range(segments):
            t0 = 2.0 * math.pi * index / segments
            t1 = 2.0 * math.pi * (index + 1) / segments
            _add_ring_segment(roofs, layout, roof_a, roof_b, t0, t1,
                              exponent, roof_z, roof_depth, 0.36)
            roof_panels += 1
            if index % 4 == 0:
                # Rear roof columns sit outside the last terrace.  The old
                # negative offset pierced the top seating row every four bays.
                u, v = _superellipse_point(outer_a + 0.45, outer_b + 0.45,
                                            t0, exponent)
                _add_box(trusses, layout, u, v, ground + (height + 4.2) / 2,
                         0.34, 0.34, height + 4.2, yaw=t0)
                inner_u, inner_v = _superellipse_point(
                    outer_a - roof_depth, outer_b - roof_depth, t0, exponent)
                mid_u, mid_v = (u + inner_u) / 2, (v + inner_v) / 2
                yaw = math.atan2(inner_v - v, inner_u - u)
                _add_box(trusses, layout, mid_u, mid_v, roof_z - 0.42,
                         math.hypot(inner_u - u, inner_v - v), 0.26, 0.26,
                         yaw=yaw)
                roof_supports += 1

    _finalize("Stadium_Rear_Structure", frames, mats["concrete"], collections["structure"])
    _finalize("Stadium_Railings", rails, mats["steel"], collections["details"])
    _finalize("Stadium_Continuous_Roof", roofs, mats["roof"], collections["roof"])
    _finalize("Stadium_Roof_Trusses", trusses, mats["steel"], collections["roof"])
    _finalize("Stadium_Exterior_Primary", skin_primary, mats["seat_primary"], collections["structure"])
    _finalize("Stadium_Exterior_Secondary", skin_secondary, mats["seat_secondary"], collections["structure"])
    _finalize("Stadium_Exterior_Portals", portals, mats["dark"], collections["structure"])
    report.update({
        "rear_columns": columns, "rear_beams": beams,
        "railing_segments": rail_segments, "roof_panels": roof_panels,
        "roof_supports": roof_supports, "exterior_skin_panels": skin_panels,
        "roof_support_seat_clearance": 0.45,
    })


def _field_furniture_and_lighting(layout, ground, mats, collections, report):
    cfg = layout["config"]
    length, width = layout["pitch_length"], layout["pitch_width"]
    details, lights, light_heads = bmesh.new(), bmesh.new(), bmesh.new()

    # Two dugouts, a centered player tunnel, perimeter fence, and scoreboard.
    for u in (-17.0, 17.0):
        v = width / 2 + 3.0
        _add_box(details, layout, u, v, ground + 1.35, 11.0, 2.2, 0.18)
        for offset in (-5.0, 0.0, 5.0):
            _add_box(details, layout, u + offset, v + 0.85,
                     ground + 0.72, 0.12, 0.12, 1.35)
    _add_box(details, layout, 0, -(width / 2 + float(cfg["runoff"]) + 2.0),
             ground + 1.6, 5.0, 5.5, 3.2)
    fence_offset = 2.3
    for v in (-width / 2 - fence_offset, width / 2 + fence_offset):
        for z in (ground + 0.8, ground + 1.8):
            _add_box(details, layout, 0, v, z, length + 5.0, 0.07, 0.07)
    for u in (-length / 2 - fence_offset, length / 2 + fence_offset):
        for z in (ground + 0.8, ground + 1.8):
            _add_box(details, layout, u, 0, z, 0.07, width + 5.0, 0.07)
    score_u = length / 2 + float(cfg["runoff"]) + float(cfg["stand_depth_end"]) + 3.0
    _add_box(details, layout, score_u, 0, ground + 10.5, 0.8, 13.0, 7.0)
    _add_box(details, layout, score_u - 0.45, 0, ground + 11.0, 0.25, 11.5, 5.4)

    towers = lamps = 0
    lighting_mode = str(cfg.get("lighting_mode", "towers")).lower()
    if cfg.get("floodlights", True) and lighting_mode == "towers":
        tower_h = float(cfg.get("floodlight_height", 34.0))
        u = length / 2 + float(cfg["runoff"]) + float(cfg["stand_depth_end"]) + 7.0
        v = width / 2 + float(cfg["runoff"]) + float(cfg["stand_depth_long"]) + 7.0
        for su in (-1, 1):
            for sv in (-1, 1):
                _add_cylinder(lights, layout, su * u, sv * v, ground,
                              0.38, tower_h, 10)
                _add_box(light_heads, layout, su * u, sv * v,
                         ground + tower_h + 0.8, 1.2, 8.0, 2.3)
                towers += 1
                lamps += 12
    elif lighting_mode == "roof_ring":
        depth = float(max(cfg["stand_depth_long"], cfg["stand_depth_end"]))
        height = float(max(cfg["stand_height_long"], cfg["stand_height_end"]))
        count = max(16, int(cfg.get("roof_ring_lights", 48)))
        exponent = max(2.0, float(cfg.get("bowl_exponent", 6.0)))
        a = length / 2 + float(cfg["runoff"]) + depth * 0.18
        b = width / 2 + float(cfg["runoff"]) + depth * 0.18
        for index in range(count):
            t = 2.0 * math.pi * index / count
            u, v = _superellipse_point(a, b, t, exponent)
            _add_box(light_heads, layout, u, v, ground + height + 3.7,
                     1.25, 0.34, 0.24, yaw=t + math.pi / 2.0)
            lamps += 1
    _finalize("Stadium_Field_Furniture", details, mats["steel"], collections["details"])
    _finalize("Stadium_Floodlight_Towers", lights, mats["steel"], collections["lighting"])
    _finalize("Stadium_Floodlight_Banks", light_heads, mats["light"], collections["lighting"])
    report.update({"dugouts": 2, "player_tunnels": 1, "scoreboards": 1,
                   "fence_segments": 8, "floodlight_towers": towers,
                   "floodlight_lamps": lamps, "lighting_mode": lighting_mode})


def _run_identity(layout, ground, mats, collection, report):
    """Add optional run-configured signage without hard-coding venue identity."""
    text = str(layout["config"].get("signage_text") or "").strip()
    if not text:
        report["signage_objects"] = 0
        return
    cfg = layout["config"]
    depth = float(max(cfg["stand_depth_long"], cfg["stand_depth_end"]))
    height = float(max(cfg["stand_height_long"], cfg["stand_height_end"]))
    made = 0
    for side in (-1, 1):
        u, v = _world(layout, 0, side * (
            layout["pitch_width"] / 2 + float(cfg["runoff"]) + depth + 0.62))
        curve = bpy.data.curves.new("Stadium_Run_Signage_%s" % side, "FONT")
        curve.body = text
        curve.align_x = "CENTER"
        curve.align_y = "CENTER"
        curve.size = max(2.2, min(4.8, 42.0 / max(8, len(text))))
        curve.extrude = 0.055
        curve.bevel_depth = 0.012
        obj = bpy.data.objects.new("Stadium_Run_Signage_%s" % side, curve)
        obj.location = (u, v, ground + min(height * 0.50, 7.6))
        obj.rotation_euler = (math.radians(-90.0 if side > 0 else 90.0),
                              0.0, layout["angle"])
        obj.data.materials.append(mats["signage"])
        obj["stadium_detail"] = True
        obj["provenance"] = "per_run_style"
        collection.objects.link(obj)
        made += 1
    report["signage_objects"] = made


def build(scene, style, parent_collection, ground_at, material_factory):
    """Build the detected stadium and return measurable component counts."""
    if not detect(scene, style):
        return None
    layout = resolve_layout(scene, style)
    if layout is None:
        return None
    ground = float(ground_at(*layout["center"]))
    collections = {
        "pitch": _collection("BLK_STADIUM_PITCH", parent_collection),
        "stands": _collection("BLK_STADIUM_STANDS", parent_collection),
        "structure": _collection("BLK_STADIUM_STRUCTURE", parent_collection),
        "roof": _collection("BLK_STADIUM_ROOFS", parent_collection),
        "details": _collection("BLK_STADIUM_DETAILS", parent_collection),
        "lighting": _collection("BLK_STADIUM_LIGHTING", parent_collection),
    }
    cfg = layout["config"]
    mats = {
        "grass": _material(material_factory, "BLK_STADIUM_GRASS_A", cfg.get("grass_color", [0.06, 0.31, 0.08]), 0.92),
        "grass_alt": _material(material_factory, "BLK_STADIUM_GRASS_B", cfg.get("grass_alt_color", [0.08, 0.39, 0.10]), 0.92),
        "white": _material(material_factory, "BLK_STADIUM_LINE", [0.92, 0.94, 0.90], 0.72),
        "net": _material(material_factory, "BLK_STADIUM_NET", [0.70, 0.73, 0.76], 0.80),
        "concrete": _material(material_factory, "BLK_STADIUM_CONCRETE", cfg["concrete_color"], 0.90),
        "seat_primary": _material(
            material_factory, "BLK_STADIUM_SEATS_PRIMARY",
            cfg.get("seat_color") or cfg["primary_color"], 0.56),
        "seat_secondary": _material(
            material_factory, "BLK_STADIUM_SEATS_SECONDARY",
            cfg["secondary_color"], 0.56),
        "safety": _material(material_factory, "BLK_STADIUM_SAFETY", cfg.get("safety_color", [0.86, 0.55, 0.05]), 0.68),
        "steel": _material(material_factory, "BLK_STADIUM_STEEL", cfg["steel_color"], 0.35, 0.72),
        "roof": _material(material_factory, "BLK_STADIUM_ROOF", cfg["roof_color"], 0.58, 0.32),
        "dark": _material(material_factory, "BLK_STADIUM_VOID", [0.025, 0.03, 0.035], 0.80),
        "light": _material(material_factory, "BLK_STADIUM_LIGHT", [0.95, 0.88, 0.63], 0.24),
        "signage": _material(material_factory, "BLK_STADIUM_SIGNAGE", [0.94, 0.97, 1.0], 0.34),
    }
    roof_alpha = min(1.0, max(0.08, float(cfg.get("roof_alpha", 1.0))))
    if roof_alpha < 1.0:
        roof_mat = mats["roof"]
        roof_mat.diffuse_color = (*roof_mat.diffuse_color[:3], roof_alpha)
        bsdf = roof_mat.node_tree.nodes.get("Principled BSDF") if roof_mat.use_nodes else None
        if bsdf:
            bsdf.inputs["Base Color"].default_value[3] = roof_alpha
            transmission = bsdf.inputs.get("Transmission Weight") or bsdf.inputs.get("Transmission")
            if transmission:
                transmission.default_value = min(0.45, 1.0 - roof_alpha + 0.12)
        if hasattr(roof_mat, "surface_render_method"):
            roof_mat.surface_render_method = "DITHERED"
    report = {
        "detected": True,
        "layout_source": "osm_pitch" if layout["pitch_osm_id"] is not None else "inferred",
        "pitch_osm_id": layout["pitch_osm_id"],
        "site_osm_id": layout["site_osm_id"],
        "pitch_dimensions_m": [layout["pitch_length"], layout["pitch_width"]],
        "orientation_deg": round(math.degrees(layout["angle"]), 3),
        "suppressed_building_ids": layout["suppressed_building_ids"],
        "suppressed_building_part_count": layout.get(
            "suppressed_building_part_count", 0),
        "roof_sides": list(layout["config"].get("roof_sides", [])),
        "roof_side_source": layout["roof_side_source"],
        "stand_sides": [],
        "provenance": {"massing": "osm_or_metric_inference",
                       "microdetail": "procedural_inference"},
    }
    _pitch_geometry(layout, ground, mats, collections["pitch"], report)
    _stand_rows(layout, ground, mats, collections["stands"], report)
    _structure_and_roofs(layout, ground, mats, collections, report)
    _field_furniture_and_lighting(layout, ground, mats, collections, report)
    _run_identity(layout, ground, mats, collections["details"], report)
    return report
