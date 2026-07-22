"""Editable procedural details for semantically detected hospitals.

The mapped building footprints remain authoritative.  This specialization adds
recognizable access, medical signage, emergency circulation, rooftop plant and
optional helipads without replacing surveyed massing.
"""

import math

import bmesh
import bpy
from mathutils import Matrix


DEFAULT_CONFIG = {
    "enabled": "auto",
    "geometry_radius": 260.0,
    "max_sites": 8,
    "entrance_canopy": True,
    "emergency_bay": True,
    "medical_signage": True,
    "roof_equipment": True,
    "helipad": "auto",
    "helipad_min_area": 1200.0,
    "ambulance_markings": True,
}


def _tokens(item):
    return " ".join(str(item.get(key, "")) for key in (
        "type", "building_use", "amenity", "healthcare", "building_part",
    )).lower()


def is_hospital(item):
    tokens = _tokens(item)
    return any(value in tokens for value in (
        "hospital", "clinic", "healthcare", "medical_centre", "medical_center",
    ))


def detect(scene, style=None):
    cfg = (style or {}).get("hospital") or DEFAULT_CONFIG
    enabled = cfg.get("enabled", "auto")
    if enabled is False:
        return False
    semantic = (str(scene.get("scene_kind", "")).lower() == "hospital"
                or "hospital" in set(scene.get("specializations") or []))
    return bool(semantic or any(is_hospital(item) for item in scene.get("buildings", [])))


def _ring(points):
    result = list(points or [])
    if len(result) > 2 and result[0] == result[-1]:
        result = result[:-1]
    return result


def _area(points):
    points = _ring(points)
    return abs(sum(
        points[i][0] * points[(i + 1) % len(points)][1]
        - points[(i + 1) % len(points)][0] * points[i][1]
        for i in range(len(points)))) * 0.5 if len(points) >= 3 else 0.0


def _centroid(points):
    points = _ring(points)
    return ((sum(p[0] for p in points) / len(points),
             sum(p[1] for p in points) / len(points)) if points else (0.0, 0.0))


def _front_frame(points):
    points = _ring(points)
    if len(points) < 3:
        return None
    start, end = max(
        zip(points, points[1:] + points[:1]),
        key=lambda pair: math.hypot(pair[1][0] - pair[0][0],
                                    pair[1][1] - pair[0][1]))
    dx, dy = end[0] - start[0], end[1] - start[1]
    length = math.hypot(dx, dy)
    if length < 2.0:
        return None
    signed = sum(points[i][0] * points[(i + 1) % len(points)][1]
                 - points[(i + 1) % len(points)][0] * points[i][1]
                 for i in range(len(points)))
    orientation = 1.0 if signed >= 0.0 else -1.0
    tx, ty = dx / length, dy / length
    nx, ny = orientation * ty, orientation * -tx
    return {
        "center": ((start[0] + end[0]) * 0.5, (start[1] + end[1]) * 0.5),
        "length": length, "angle": math.atan2(dy, dx),
        "tangent": (tx, ty), "normal": (nx, ny),
    }


def resolve_sites(scene, style=None):
    cfg = dict(DEFAULT_CONFIG)
    cfg.update((style or {}).get("hospital") or {})
    radius = float(cfg.get("geometry_radius", 260.0))
    candidates = []
    for item in scene.get("buildings", []):
        footprint = item.get("footprint", [])
        if not is_hospital(item) or len(footprint) < 3:
            continue
        center = _centroid(footprint)
        if math.hypot(*center) > radius:
            continue
        frame = _front_frame(footprint)
        if frame:
            candidates.append({
                "building": item, "center": center, "area": _area(footprint),
                "frame": frame,
            })
    candidates.sort(key=lambda site: (-site["area"], math.hypot(*site["center"])))
    return candidates[:max(1, int(cfg.get("max_sites", 8)))]


def _add_box(bm, cx, cy, cz, sx, sy, sz, rotation=0.0):
    matrix = (Matrix.Translation((cx, cy, cz))
              @ Matrix.Rotation(rotation, 4, "Z")
              @ Matrix.Diagonal((sx, sy, sz, 1.0)))
    bmesh.ops.create_cube(bm, size=1.0, matrix=matrix)


def _add_cylinder(bm, cx, cy, base, radius, height, segments=16):
    matrix = Matrix.Translation((cx, cy, base + height * 0.5))
    bmesh.ops.create_cone(
        bm, cap_ends=True, cap_tris=False, segments=segments,
        radius1=radius, radius2=radius, depth=height, matrix=matrix)


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
    obj["provenance"] = "procedural_inference"
    return obj


def build(scene, style, parent_collection, ground_at, material_factory):
    if not detect(scene, style):
        return None
    cfg = dict(DEFAULT_CONFIG)
    cfg.update(style.get("hospital") or {})
    sites = resolve_sites(scene, style)
    if not sites:
        return None

    concrete = material_factory("BLK_HOSPITAL_CANOPY", [0.78, 0.80, 0.79], roughness=0.72)
    glass = material_factory("BLK_HOSPITAL_GLASS", [0.18, 0.32, 0.38], roughness=0.18)
    red = material_factory("BLK_HOSPITAL_MEDICAL_RED", [0.78, 0.035, 0.035], roughness=0.44)
    asphalt = material_factory("BLK_HOSPITAL_AMBULANCE_BAY", [0.25, 0.27, 0.29], roughness=0.90)
    white = material_factory("BLK_HOSPITAL_MARKING", [0.93, 0.93, 0.89], roughness=0.60)
    equipment = material_factory("BLK_HOSPITAL_ROOF_PLANT", [0.47, 0.50, 0.50], roughness=0.62)

    report = {
        "detected": True, "sites": len(sites), "entrance_canopies": 0,
        "canopy_supports": 0, "emergency_bays": 0, "medical_crosses": 0,
        "helipads": 0, "roof_units": 0, "ambulance_markings": 0,
        "building_ids": [], "source": "osm_semantics+procedural_detail",
    }
    for index, site in enumerate(sites):
        building = site["building"]
        frame = site["frame"]
        cx, cy = frame["center"]
        tx, ty = frame["tangent"]
        nx, ny = frame["normal"]
        angle = frame["angle"]
        ground = float(ground_at(*site["center"]))
        top = ground + float(building.get("height", 12.0))
        report["building_ids"].append(building.get("osm_id"))

        if cfg.get("entrance_canopy", True):
            canopy = bmesh.new()
            width = min(12.0, max(5.0, frame["length"] * 0.24))
            depth = min(5.0, max(3.0, width * 0.42))
            ccx, ccy = cx + nx * depth * 0.55, cy + ny * depth * 0.55
            _add_box(canopy, ccx, ccy, ground + 3.25, width, depth, 0.28, angle)
            for side in (-1.0, 1.0):
                px = ccx + tx * side * width * 0.43 + nx * depth * 0.36
                py = ccy + ty * side * width * 0.43 + ny * depth * 0.36
                _add_cylinder(canopy, px, py, ground, 0.14, 3.12, 10)
                report["canopy_supports"] += 1
            if _finalize("Hospital_Entrance_Canopy_%d" % index, canopy,
                         concrete, parent_collection, "hospital_entrance_canopy"):
                report["entrance_canopies"] += 1
            doors = bmesh.new()
            _add_box(doors, cx + nx * 0.10, cy + ny * 0.10, ground + 1.35,
                     min(4.2, width * 0.52), 0.14, 2.7, angle)
            _finalize("Hospital_Sliding_Doors_%d" % index, doors, glass,
                      parent_collection, "hospital_sliding_entrance")

        if cfg.get("medical_signage", True):
            sign = bmesh.new()
            sign_z = min(top - 1.2, ground + max(4.8, (top - ground) * 0.68))
            sx, sy = cx + nx * 0.18, cy + ny * 0.18
            _add_box(sign, sx, sy, sign_z, 2.7, 0.18, 0.72, angle)
            _add_box(sign, sx, sy, sign_z, 0.72, 0.18, 2.7, angle)
            _finalize("Hospital_Medical_Cross_%d" % index, sign, red,
                      parent_collection, "hospital_medical_signage")
            report["medical_crosses"] += 1

        if cfg.get("emergency_bay", True):
            bay = bmesh.new()
            offset = min(frame["length"] * 0.30, 18.0)
            bx = cx + tx * offset + nx * 6.5
            by = cy + ty * offset + ny * 6.5
            _add_box(bay, bx, by, ground + 0.055, 10.0, 6.0, 0.11, angle)
            _finalize("Hospital_Emergency_Bay_%d" % index, bay, asphalt,
                      parent_collection, "hospital_emergency_bay")
            report["emergency_bays"] += 1
            if cfg.get("ambulance_markings", True):
                marks = bmesh.new()
                for lane in (-1.4, 1.4):
                    _add_box(marks, bx + nx * lane, by + ny * lane,
                             ground + 0.12, 8.2, 0.16, 0.035, angle)
                _add_box(marks, bx, by, ground + 0.12, 1.9, 0.15, 0.48, angle)
                _add_box(marks, bx, by, ground + 0.12, 0.48, 0.15, 1.9, angle)
                _finalize("Hospital_Ambulance_Marking_%d" % index, marks, white,
                          parent_collection, "hospital_ambulance_marking")
                report["ambulance_markings"] += 4

        if cfg.get("roof_equipment", True):
            units = bmesh.new()
            unit_count = max(2, min(8, int(site["area"] / 450.0) + 2))
            for unit in range(unit_count):
                along = (unit - (unit_count - 1) * 0.5) * 2.7
                ux = site["center"][0] + tx * along
                uy = site["center"][1] + ty * along
                _add_box(units, ux, uy, top + 0.65, 1.8, 1.25, 1.3, angle)
            _finalize("Hospital_Roof_Plant_%d" % index, units, equipment,
                      parent_collection, "hospital_rooftop_equipment")
            report["roof_units"] += unit_count

        want_helipad = cfg.get("helipad", "auto") is True or (
            cfg.get("helipad", "auto") == "auto"
            and site["area"] >= float(cfg.get("helipad_min_area", 1200.0)))
        if want_helipad:
            pad = bmesh.new()
            hx = site["center"][0] - tx * min(8.0, frame["length"] * 0.18)
            hy = site["center"][1] - ty * min(8.0, frame["length"] * 0.18)
            _add_cylinder(pad, hx, hy, top + 0.08, 4.3, 0.12, 32)
            _finalize("Hospital_Helipad_%d" % index, pad, asphalt,
                      parent_collection, "hospital_helipad")
            hmark = bmesh.new()
            _add_box(hmark, hx - tx * 1.2, hy - ty * 1.2, top + 0.22,
                     0.45, 3.0, 0.035, angle)
            _add_box(hmark, hx + tx * 1.2, hy + ty * 1.2, top + 0.22,
                     0.45, 3.0, 0.035, angle)
            _add_box(hmark, hx, hy, top + 0.22, 2.85, 0.45, 0.035, angle)
            _finalize("Hospital_Helipad_H_%d" % index, hmark, white,
                      parent_collection, "hospital_helipad_marking")
            report["helipads"] += 1
    report["building_ids"] = [value for value in report["building_ids"] if value is not None]
    return report
