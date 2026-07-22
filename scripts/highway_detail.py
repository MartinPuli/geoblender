"""Lane-aware editable highway, bridge and interchange geometry."""

import math
import re

import bmesh
import bpy
from mathutils import Matrix


DEFAULT_CONFIG = {
    "enabled": "auto",
    "types": ["motorway", "motorway_link", "trunk", "trunk_link"],
    "lane_width": 3.5,
    "shoulder_width": 1.1,
    "deck_thickness": 0.18,
    "marking_width": 0.14,
    "dash_length": 3.6,
    "dash_gap": 5.4,
    "guardrails": True,
    "guardrail_height": 0.72,
    "guardrail_posts": True,
    "bridge_piers": True,
    "pier_spacing": 24.0,
    "gantries": True,
    "max_gantries": 12,
}


def is_highway(road, config=None):
    config = config or DEFAULT_CONFIG
    return str(road.get("type", "")).lower() in set(config.get("types") or [])


def detect(scene, style=None):
    cfg = dict(DEFAULT_CONFIG)
    cfg.update((style or {}).get("highway") or {})
    if cfg.get("enabled") is False:
        return False
    return any(is_highway(road, cfg) for road in scene.get("roads", []))


def _int(value, default):
    match = re.search(r"\d+", str(value or ""))
    return max(1, int(match.group(0))) if match else int(default)


def road_spec(road, style=None):
    cfg = dict(DEFAULT_CONFIG)
    cfg.update((style or {}).get("highway") or {})
    oneway = str(road.get("oneway", "")).lower() in ("yes", "true", "1", "-1")
    default_lanes = 2 if oneway else 4
    lanes = _int(road.get("lanes"), default_lanes)
    lane_width = float(cfg.get("lane_width", 3.5))
    shoulder = float(cfg.get("shoulder_width", 1.1))
    mapped_width = float(road.get("width", 0.0) or 0.0)
    inferred_width = lanes * lane_width + shoulder * 2.0
    width = mapped_width if road.get("width_source") == "explicit" else max(mapped_width, inferred_width)
    return {
        "type": str(road.get("type", "")), "lanes": lanes, "oneway": oneway,
        "lane_width": lane_width, "shoulder_width": shoulder,
        "width": round(width, 3), "bridge": bool(road.get("bridge")),
        "tunnel": bool(road.get("tunnel")), "layer": float(road.get("layer") or 0.0),
        "ref": road.get("ref"), "surface": road.get("surface") or "asphalt",
    }


def _add_box(bm, cx, cy, cz, sx, sy, sz, rotation=0.0):
    matrix = (Matrix.Translation((cx, cy, cz))
              @ Matrix.Rotation(rotation, 4, "Z")
              @ Matrix.Diagonal((sx, sy, sz, 1.0)))
    bmesh.ops.create_cube(bm, size=1.0, matrix=matrix)


def _add_cylinder(bm, cx, cy, base, radius, height, segments=10):
    matrix = Matrix.Translation((cx, cy, base + height * 0.5))
    bmesh.ops.create_cone(
        bm, cap_ends=True, cap_tris=False, segments=segments,
        radius1=radius, radius2=radius * 0.86, depth=height, matrix=matrix)


def _finalize(name, bm, material, collection, kind):
    if not bm.verts:
        bm.free()
        return None
    mesh = bpy.data.meshes.new(name + "_Mesh")
    bm.to_mesh(mesh)
    bm.free()
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    collection.objects.link(obj)
    obj.data.materials.append(material)
    obj["detail_kind"] = kind
    obj["provenance"] = "osm_geometry+procedural_detail"
    return obj


def _segment_frame(start, end):
    dx, dy = end[0] - start[0], end[1] - start[1]
    length = math.hypot(dx, dy)
    if length < 0.3:
        return None
    tx, ty = dx / length, dy / length
    return {
        "cx": (start[0] + end[0]) * 0.5,
        "cy": (start[1] + end[1]) * 0.5,
        "length": length, "angle": math.atan2(dy, dx),
        "tangent": (tx, ty), "normal": (-ty, tx),
    }


def _offset(frame, lateral, along=0.0):
    tx, ty = frame["tangent"]
    nx, ny = frame["normal"]
    return (frame["cx"] + nx * lateral + tx * along,
            frame["cy"] + ny * lateral + ty * along)


def build(scene, style, parent_collection, ground_at, material_factory):
    if not detect(scene, style):
        return None
    cfg = dict(DEFAULT_CONFIG)
    cfg.update(style.get("highway") or {})
    asphalt = material_factory("BLK_HIGHWAY_ASPHALT", [0.19, 0.20, 0.22], roughness=0.94)
    white = material_factory("BLK_HIGHWAY_WHITE", [0.92, 0.92, 0.86], roughness=0.62)
    yellow = material_factory("BLK_HIGHWAY_YELLOW", [0.92, 0.67, 0.10], roughness=0.62)
    steel = material_factory("BLK_HIGHWAY_GUARDRAIL", [0.48, 0.51, 0.53], roughness=0.48, metallic=0.55)
    concrete = material_factory("BLK_HIGHWAY_CONCRETE", [0.52, 0.51, 0.48], roughness=0.90)
    sign = material_factory("BLK_HIGHWAY_SIGN", [0.05, 0.31, 0.19], roughness=0.52)

    report = {
        "detected": True, "carriageways": 0, "lanes": 0,
        "lane_marking_dashes": 0, "edge_lines": 0, "guardrail_segments": 0,
        "guardrail_posts": 0, "median_barriers": 0, "bridge_piers": 0,
        "gantries": 0, "suppressed_road_indices": [], "road_ids": [],
        "source": "osm_road_tags+procedural_detail",
    }
    gantry_budget = max(0, int(cfg.get("max_gantries", 12)))
    for road_index, road in enumerate(scene.get("roads", [])):
        if not is_highway(road, cfg):
            continue
        path = road.get("path") or []
        if len(path) < 2:
            continue
        spec = road_spec(road, style)
        report["suppressed_road_indices"].append(road_index)
        if road.get("osm_id") is not None:
            report["road_ids"].append(road.get("osm_id"))
        report["carriageways"] += 1
        report["lanes"] += spec["lanes"]
        deck = bmesh.new()
        marks = bmesh.new()
        rails = bmesh.new()
        piers = bmesh.new()
        base_z = float(road.get("z", 0.06))
        for segment_index, (start, end) in enumerate(zip(path, path[1:])):
            frame = _segment_frame(start, end)
            if not frame:
                continue
            ground = float(ground_at(frame["cx"], frame["cy"]))
            z = ground + base_z
            thickness = float(cfg.get("deck_thickness", 0.18))
            _add_box(deck, frame["cx"], frame["cy"], z + thickness * 0.5,
                     frame["length"] + 0.35, spec["width"], thickness,
                     frame["angle"])

            usable = max(spec["lane_width"], spec["width"] - 2.0 * spec["shoulder_width"])
            for divider in range(1, spec["lanes"]):
                lateral = -usable * 0.5 + usable * divider / spec["lanes"]
                period = float(cfg.get("dash_length", 3.6)) + float(cfg.get("dash_gap", 5.4))
                count = max(1, int(frame["length"] / period))
                for dash_index in range(count):
                    along = -frame["length"] * 0.5 + (dash_index + 0.5) * frame["length"] / count
                    length = min(float(cfg.get("dash_length", 3.6)), frame["length"] / count * 0.72)
                    mx, my = _offset(frame, lateral, along)
                    _add_box(marks, mx, my, z + thickness + 0.015,
                             length, float(cfg.get("marking_width", 0.14)), 0.03,
                             frame["angle"])
                    report["lane_marking_dashes"] += 1
            for side in (-1.0, 1.0):
                lateral = side * (spec["width"] * 0.5 - spec["shoulder_width"] * 0.42)
                ex, ey = _offset(frame, lateral)
                _add_box(marks, ex, ey, z + thickness + 0.016,
                         frame["length"], float(cfg.get("marking_width", 0.14)), 0.032,
                         frame["angle"])
                report["edge_lines"] += 1
                if cfg.get("guardrails", True) and not spec["tunnel"]:
                    rail_lateral = side * (spec["width"] * 0.5 + 0.12)
                    rx, ry = _offset(frame, rail_lateral)
                    _add_box(rails, rx, ry, z + thickness + float(cfg.get("guardrail_height", 0.72)),
                             frame["length"], 0.12, 0.16, frame["angle"])
                    report["guardrail_segments"] += 1
                    if cfg.get("guardrail_posts", True):
                        posts = max(2, int(frame["length"] / 3.6) + 1)
                        for post_index in range(posts):
                            along = -frame["length"] * 0.5 + post_index * frame["length"] / max(1, posts - 1)
                            px, py = _offset(frame, rail_lateral, along)
                            _add_box(rails, px, py,
                                     z + thickness + float(cfg.get("guardrail_height", 0.72)) * 0.5,
                                     0.10, 0.12, float(cfg.get("guardrail_height", 0.72)),
                                     frame["angle"])
                            report["guardrail_posts"] += 1
            if not spec["oneway"] and spec["lanes"] >= 4:
                _add_box(rails, frame["cx"], frame["cy"], z + thickness + 0.34,
                         frame["length"], 0.34, 0.68, frame["angle"])
                report["median_barriers"] += 1
            if spec["bridge"] and cfg.get("bridge_piers", True):
                spacing = max(10.0, float(cfg.get("pier_spacing", 24.0)))
                pier_count = max(1, int(frame["length"] / spacing))
                deck_elevation = max(2.0, base_z)
                for pier_index in range(pier_count):
                    along = -frame["length"] * 0.5 + (pier_index + 0.5) * frame["length"] / pier_count
                    px, py = _offset(frame, 0.0, along)
                    _add_cylinder(piers, px, py, ground, 0.68, deck_elevation, 10)
                    report["bridge_piers"] += 1

        _finalize("Highway_Deck_%d" % road_index, deck, asphalt,
                  parent_collection, "highway_carriageway")
        _finalize("Highway_Markings_%d" % road_index, marks,
                  yellow if spec["type"].endswith("_link") else white,
                  parent_collection, "highway_lane_markings")
        _finalize("Highway_Guardrails_%d" % road_index, rails, steel,
                  parent_collection, "highway_guardrails")
        _finalize("Highway_Bridge_Piers_%d" % road_index, piers, concrete,
                  parent_collection, "highway_bridge_piers")

        if cfg.get("gantries", True) and gantry_budget > 0 and path:
            first = _segment_frame(path[0], path[1])
            if first and first["length"] >= 8.0:
                z = float(ground_at(first["cx"], first["cy"])) + float(road.get("z", 0.06))
                gantry = bmesh.new()
                for side in (-1.0, 1.0):
                    gx, gy = _offset(first, side * spec["width"] * 0.56)
                    _add_box(gantry, gx, gy, z + 2.8, 0.22, 0.22, 5.6, first["angle"])
                _add_box(gantry, first["cx"], first["cy"], z + 5.45,
                         0.20, spec["width"] * 1.18, 0.20, first["angle"])
                _finalize("Highway_Gantry_%d" % road_index, gantry, steel,
                          parent_collection, "highway_sign_gantry")
                board = bmesh.new()
                bx, by = _offset(first, -spec["width"] * 0.18)
                _add_box(board, bx, by, z + 4.75, 0.16, min(5.2, spec["width"] * 0.42),
                         1.15, first["angle"])
                _finalize("Highway_Sign_%d" % road_index, board, sign,
                          parent_collection, "highway_direction_sign")
                report["gantries"] += 1
                gantry_budget -= 1
    return report if report["carriageways"] else None

