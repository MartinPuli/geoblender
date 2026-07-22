"""Build an editable block model from the normalized ``scene.json`` contract.

The builder only understands reusable geometry and categories: buildings,
roads, areas, and point/line/surface features. Run-specific identities,
verified measurements, and visual choices belong in style.json.

Usage:
  blender -b -P scripts/blocks_build.py -- <scene.json> <outdir> <slug> \
    [--style <style.json>] [--render] [--samples 96]
"""

import colorsys
import json
import math
import os
import sys
import zlib

import bmesh
import bpy
from mathutils import Matrix
try:
    from mathutils import Vector
except ImportError:  # lightweight test stubs only expose Matrix
    class Vector:  # pragma: no cover - exercised only outside Blender
        def __init__(self, value):
            self.x, self.y, self.z = map(float, value)
        def __sub__(self, other):
            return Vector((self.x - other.x, self.y - other.y, self.z - other.z))
        def __add__(self, other):
            return Vector((self.x + other.x, self.y + other.y, self.z + other.z))
        def __mul__(self, scalar):
            return Vector((self.x * scalar, self.y * scalar, self.z * scalar))
        @property
        def length(self):
            return math.sqrt(self.x * self.x + self.y * self.y + self.z * self.z)


_HERE = os.path.dirname(os.path.abspath(__file__)) if "__file__" in globals() else None
if _HERE and _HERE not in sys.path:
    sys.path.append(_HERE)
from blender_build import add_flat_polygon, add_prism, dedupe_ring  # noqa: E402
import architectural_detail  # noqa: E402
import highway_detail  # noqa: E402
import hospital_detail  # noqa: E402
import stadium_detail  # noqa: E402
import urban_detail  # noqa: E402


DEFAULT_STYLE = {
    # Use each feature's own OSM/estimated color by default so buildings read
    # as a real, varied neighborhood; the saturation/value caps keep the
    # per-building palette from turning garish.
    "color_mode": "scene",
    "color_boost": 1.0,
    "building_max_sat": 0.72,
    "building_max_val": 0.93,
    "editable_radius": 200.0,
    "merge_distant_buildings": True,
    "focus": {"point": None, "match": None, "span": None},
    "feature_overrides": {},
    # Default building detail (general, provenance/geometry-driven, and per-run
    # reversible with enabled:false). height_variation only reshapes
    # estimated/default heights — never explicit OSM height/levels —
    # deterministically per osm_id and footprint area, so the skyline reads as
    # a varied neighborhood instead of a field of identical default boxes.
    "height_variation": {"enabled": True, "factor_min": 0.8, "factor_max": 1.8,
                         "min": 4.0, "max": 42.0, "area_full": 1600.0},
    # roof_detail adds a thin, darker roof/parapet band to individual buildings.
    "roof_detail": {"enabled": True, "band": 1.1, "darken": 0.7},
    # roof_shapes builds real pitched roofs from OSM roof:shape (gabled, hipped,
    # pyramidal, skillion, ...). Tag-driven; buildings without the tag keep the
    # flat roof_detail cap. max_height caps how tall the roof rises.
    "roof_shapes": {"enabled": True, "max_height": 5.0},
    # terrain drapes the scene over a real SRTM/DEM grid when scene.json carries
    # a "terrain" block (from place_to_3d --terrain): the ground is displaced and
    # buildings/roads/areas are lifted to the sampled elevation. No-op on flat or
    # terrain-less scenes, so runs without a terrain block stay reproducible.
    "terrain": {"enabled": True},
    # image_colors samples roof/area color from an authorized aerial reference.
    # Aerial evidence never overwrites facade color. The image stays external:
    # only a sourced attribute is derived, never pasted as geometry or texture.
    "image_colors": {"enabled": True, "patch": 3, "boost": 1.0,
                     "target": "roof"},
    # facade adds a face-aligned shader grid and bounded near-field window-panel
    # geometry. Merged/distant buildings remain cheap; parameters come from
    # levels, height, semantic type/use, and material rather than identity.
    "facade": {"enabled": True, "floor_height": 3.2, "bay": 3.6,
               "window_color": [0.05, 0.08, 0.13],
               "window_width_ratio": 0.66, "window_height_ratio": 0.62,
               "geometry_enabled": True, "geometry_radius": 95.0,
               "geometry_depth": 0.06, "max_windows_per_building": 240,
               "frame_enabled": True, "frame_width": 0.10,
               "frame_depth": 0.09, "frame_color": [0.72, 0.70, 0.66]},
    # construction_detail adds readable near-field architectural hierarchy:
    # plinth, floor strings, cornice/parapet and one entry on the selected
    # grounded volume. It is a bounded inferred LOD grammar. Explicit OSM
    # building:part/min_height/roof tags always control the actual massing.
    "construction_detail": {
        "enabled": True, "geometry_radius": 125.0,
        "base_height": 0.42, "base_outset": 0.10,
        "cornice_height": 0.24, "cornice_outset": 0.14,
        "floor_bands": True, "floor_band_height": 0.08,
        "floor_band_outset": 0.07, "max_floor_bands": 12,
        "entrances": True, "entrance_width": 1.55,
        "entrance_height": 2.45, "entrance_depth": 0.12,
    },
    # Open roofs/canopies remain open underneath.  A thin roof deck, perimeter
    # beams, and bounded supports make the covered area legible and editable
    # without inventing enclosing walls.
    "covered_structures": {
        "enabled": True, "roof_thickness": 0.28,
        "column_spacing": 7.0, "column_size": 0.22,
        "column_inset": 0.35, "max_columns": 24,
        "edge_beams": True, "edge_beam_width": 0.16,
        "edge_beam_height": 0.20,
    },
    # Reusable low-poly street objects are created only for explicit semantic
    # OSM points and stay bounded by radius/count for dense city scenes.
    "urban_objects": {
        "enabled": True, "geometry_radius": 240.0, "max_objects": 1200,
        "tree_segments": 12, "object_segments": 10, "render_text": True,
        "wall_host_max_distance": 6.0,
        "road_host_max_distance": 15.0,
    },
    # Explicit street semantics drive these details. Lane arrows require
    # turn:lanes, kerbs/islands require mapped features, and area vegetation is
    # generated only for cover semantics such as wood/forest/orchard/scrub.
    "streetscape": {
        "enabled": True, "driving_side": "right",
        "lane_arrow_length": 2.8, "lane_arrow_width": 0.18,
        "utility_wire_width": 0.035,
        "telecom_wire_width": 0.025,
        "cycle_lane_width": 1.6,
        "sidewalk_width": 1.8,
        "sidewalk_height": 0.10,
        "cycle_protection_spacing": 7.0,
    },
    "vegetation_areas": {
        "enabled": True, "geometry_radius": 300.0,
        "max_instances": 500, "max_instances_per_area": 90,
        "woodland_m2_per_tree": 360.0,
        "orchard_m2_per_tree": 150.0,
        "scrub_m2_per_shrub": 95.0,
    },
    # stadium_interior. Tag-driven (building=stadium/grandstand): replace the
    # hollow flat-topped box with an outer wall plus raked seating tiers that
    # descend to the pitch. Geometry-only reusable semantics; seat_color and
    # wall_color are optional per-run overrides.
    "stadium_interior": {"enabled": True, "tiers": 7, "inner_scale": 0.32,
                         "pitch_height": 2.0, "seat_color": None, "wall_color": None},
    # Scene-level football specialization. In auto mode it activates only when
    # normalized OSM data contains a football pitch plus stadium semantics.
    "football_stadium": dict(stadium_detail.DEFAULT_CONFIG),
    # Semantic building grammar adds deterministic variation, symmetric opening
    # layouts, mullions, balconies and shallow visible room depth near camera.
    "architectural_detail": dict(architectural_detail.DEFAULT_CONFIG),
    # Scene-level semantic specializations preserve mapped massing/paths and add
    # domain details without relying on venue names.
    "hospital": dict(hospital_detail.DEFAULT_CONFIG),
    "highway": dict(highway_detail.DEFAULT_CONFIG),
    "samples": 96,
    "resolution": [1600, 1000],
    "camera": {"azimuth_deg": 225.0, "elev_deg": 33.0, "margin": 1.85,
               "aerial_height_factor": 2.2,
               "holdout_azimuth_offset_deg": 110.0,
               "holdout_elev_deg": 28.0},
    # Optional close views make small urban details auditable without changing
    # the three standard whole-scene evaluation cameras. Each entry accepts
    # name, point, span, azimuth_deg, elev_deg, margin, lens and target_z.
    "detail_views": [],
    "sun": {"energy": 3.0, "angle_deg": 14.0, "rot_deg": [52, 6, 35]},
    "sky": [0.60, 0.68, 0.78, 1.3],
    # sky_model renders a physical sky gradient (Eevee-compatible Hosek/Wilkie,
    # falling back to Preetham) aligned to the sun, instead of a flat background
    # colour. Set to "flat" to fall back to the solid `sky` colour above.
    "sky_model": "hosek_wilkie",
    "sky_turbidity": 2.6,
    "sky_ground_albedo": 0.3,
    "sky_strength": 1.0,
    # roof_props scatters small deterministic rooftop clutter (chimneys, vents,
    # AC/stairwell boxes) on individual buildings for silhouette detail.
    "roof_props": {"enabled": True, "density": 1.0},
    "palette": {
        "GROUND": [0.79, 0.78, 0.73],
        "ASPHALT": [0.44, 0.44, 0.47],
        "FOOTWAY": [0.60, 0.59, 0.56],
        "GREEN": [0.30, 0.49, 0.25],
        "WATER": [0.23, 0.48, 0.62],
        "AREA": [0.62, 0.61, 0.57],
        "FEATURE": [0.72, 0.71, 0.67],
        "METAL": [0.24, 0.27, 0.29],
        "WOOD": [0.42, 0.25, 0.12],
        "TRUNK": [0.29, 0.18, 0.09],
        "FOLIAGE": [0.18, 0.42, 0.16],
        "LIGHT": [0.95, 0.86, 0.55],
        "SIGN_FACE": [0.88, 0.91, 0.92],
        "SIGN_DARK": [0.08, 0.12, 0.16],
        "SIGN_RED": [0.72, 0.03, 0.025],
        "SIGN_BLUE": [0.03, 0.20, 0.62],
        "SIGN_YELLOW": [0.95, 0.68, 0.04],
        "TACTILE": [0.93, 0.67, 0.08],
        "CROSSING": [0.92, 0.93, 0.90],
        "KERB": [0.69, 0.68, 0.64],
        "UTILITY_WIRE": [0.075, 0.085, 0.09],
        "TELECOM_WIRE": [0.12, 0.12, 0.11],
        "CYCLEWAY": [0.45, 0.18, 0.15],
        "BUS_LANE": [0.48, 0.12, 0.10],
        "PARKING": [0.25, 0.27, 0.30],
        "PIPE_WATER": [0.12, 0.42, 0.72],
        "PIPE_GAS": [0.88, 0.67, 0.08],
        "PIPE_OIL": [0.24, 0.20, 0.16],
        "PIPE_GENERIC": [0.48, 0.52, 0.54],
        "POWER_EQUIPMENT": [0.30, 0.34, 0.31],
        "SHRUB": [0.22, 0.38, 0.15],
        "ART_STONE": [0.58, 0.57, 0.54],
        "ART_METAL": [0.22, 0.25, 0.27],
        "PLAY": [0.86, 0.34, 0.12],
        "RESIDENTIAL_ZONE": [0.53, 0.49, 0.41],
        "BLD_A": [0.70, 0.66, 0.60],
        "BLD_B": [0.62, 0.64, 0.68],
        "BLD_C": [0.74, 0.70, 0.64],
        "BLD_D": [0.58, 0.60, 0.63],
        "ROOF": [0.34, 0.30, 0.28],
    },
}


def _deep_update(base, override):
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _deep_update(base[key], value)
        else:
            base[key] = value
    return base


def load_style(style_path=None):
    style = json.loads(json.dumps(DEFAULT_STYLE))
    if style_path and os.path.exists(style_path):
        with open(style_path, encoding="utf-8") as stream:
            _deep_update(style, json.load(stream))
    return style


def feature_matches(feature, selector):
    selector = str(selector or "").strip().lower()
    if not selector:
        return False
    exact = (feature.get("osm_id"), feature.get("id"))
    if any(selector == str(value).lower() for value in exact if value not in (None, "")):
        return True
    searchable = (feature.get("name"), feature.get("type"), feature.get("kind"),
                  feature.get("family"))
    return any(selector in str(value).lower() for value in searchable
               if value not in (None, ""))


def feature_override(feature, style):
    merged = {}
    for selector, values in style.get("feature_overrides", {}).items():
        if feature_matches(feature, selector):
            _deep_update(merged, values)
    return merged


def safe_name(value):
    text = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in str(value))
    return text.strip("_")[:80] or "anonymous"


def poly_area(points):
    if len(points) < 3:
        return 0.0
    return abs(sum(
        points[index][0] * points[(index + 1) % len(points)][1]
        - points[(index + 1) % len(points)][0] * points[index][1]
        for index in range(len(points))
    )) * 0.5


def centroid(points):
    if not points:
        return 0.0, 0.0
    return (sum(point[0] for point in points) / len(points),
            sum(point[1] for point in points) / len(points))


def feature_points(feature):
    if feature.get("point"):
        return [feature["point"]]
    for key in ("footprint", "polygon", "path"):
        if feature.get(key):
            return feature[key]
    return []


def _srgb_to_linear(value):
    """Convert a display-sRGB channel to Blender scene-linear space."""
    value = max(0.0, min(1.0, float(value)))
    if value <= 0.04045:
        return value / 12.92
    return ((value + 0.055) / 1.055) ** 2.4


def make_material(name, rgb, roughness=0.85, metallic=0.0):
    material = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    material.use_nodes = True
    bsdf = material.node_tree.nodes.get("Principled BSDF")
    if bsdf is None:
        bsdf = material.node_tree.nodes.new("ShaderNodeBsdfPrincipled")
        output = (material.node_tree.nodes.get("Material Output")
                  or material.node_tree.nodes.new("ShaderNodeOutputMaterial"))
        material.node_tree.links.new(bsdf.outputs[0], output.inputs[0])
    linear = tuple(_srgb_to_linear(channel) for channel in rgb[:3])
    bsdf.inputs["Base Color"].default_value = (*linear, 1.0)
    bsdf.inputs["Roughness"].default_value = roughness
    bsdf.inputs["Metallic"].default_value = metallic
    if "Specular IOR Level" in bsdf.inputs:
        bsdf.inputs["Specular IOR Level"].default_value = 0.05
    material.diffuse_color = (*linear, 1.0)
    return material


def make_glass_material(name, rgb, roughness=0.18):
    """Create readable glazing with modest transmission and stable Eevee alpha."""
    material = make_material(name, rgb, roughness=roughness)
    bsdf = material.node_tree.nodes.get("Principled BSDF")
    if bsdf is not None:
        if "Transmission Weight" in bsdf.inputs:
            bsdf.inputs["Transmission Weight"].default_value = 0.22
        if "Coat Weight" in bsdf.inputs:
            bsdf.inputs["Coat Weight"].default_value = 0.18
        if "Alpha" in bsdf.inputs:
            bsdf.inputs["Alpha"].default_value = 0.82
    material.diffuse_color = (*tuple(_srgb_to_linear(channel) for channel in rgb[:3]), 0.82)
    if hasattr(material, "surface_render_method"):
        material.surface_render_method = "DITHERED"
    elif hasattr(material, "blend_method"):
        material.blend_method = "BLEND"
    return material


def make_interior_material(name, rgb, strength=0.0):
    material = make_material(name, rgb, roughness=0.72)
    bsdf = material.node_tree.nodes.get("Principled BSDF")
    if bsdf is not None and strength > 0.0:
        if "Emission Color" in bsdf.inputs:
            bsdf.inputs["Emission Color"].default_value = (
                *tuple(_srgb_to_linear(channel) for channel in rgb[:3]), 1.0)
        elif "Emission" in bsdf.inputs:
            bsdf.inputs["Emission"].default_value = (
                *tuple(_srgb_to_linear(channel) for channel in rgb[:3]), 1.0)
        if "Emission Strength" in bsdf.inputs:
            bsdf.inputs["Emission Strength"].default_value = strength
    return material


def material_for_color(rgb, style):
    rgb = [float(channel) for channel in rgb[:3]]
    boost = float(style.get("color_boost", 1.0))
    if boost != 1.0:
        grey = sum(rgb) / 3.0
        rgb = [min(1.0, max(0.0, grey + (channel - grey) * boost)) for channel in rgb]
    hue, sat, val = colorsys.rgb_to_hsv(*rgb)
    if style.get("building_max_sat") is not None:
        sat = min(sat, float(style["building_max_sat"]))
    if style.get("building_max_val") is not None:
        val = min(val, float(style["building_max_val"]))
    rgb = colorsys.hsv_to_rgb(hue, sat, val)
    quantized = [min(20, max(0, int(round(channel * 20)))) for channel in rgb]
    name = "BLK_C_%02d%02d%02d" % tuple(quantized)
    return make_material(name, [channel / 20.0 for channel in quantized])


def build_materials(style):
    return {key: make_material("BLK_" + key, rgb)
            for key, rgb in style["palette"].items()}


def new_collection(name, parent=None):
    collection = bpy.data.collections.get(name)
    if collection is None:
        collection = bpy.data.collections.new(name)
        (parent or bpy.context.scene.collection).children.link(collection)
    return collection


def safe_clear():
    """Clear the scene without resetting preferences or disconnecting add-ons."""
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    for collection in list(bpy.data.collections):
        bpy.data.collections.remove(collection)
    for datablocks in (bpy.data.meshes, bpy.data.curves, bpy.data.lights,
                       bpy.data.cameras, bpy.data.materials, bpy.data.images):
        for datablock in list(datablocks):
            if datablock.users == 0:
                datablocks.remove(datablock)


def add_box(bm, cx, cy, cz, sx, sy, sz, rotation=0.0):
    matrix = (Matrix.Translation((cx, cy, cz))
              @ Matrix.Rotation(rotation, 4, "Z")
              @ Matrix.Diagonal((sx, sy, sz, 1.0)))
    bmesh.ops.create_cube(bm, size=1.0, matrix=matrix)


def add_wedge(bm, cx, cy, base_z, length, width, height, rotation=0.0,
              high_at_positive=True):
    """Add a rectangular ramp with a true sloped top, not a blocking step."""
    half_l, half_w = length * 0.5, width * 0.5
    low, high = (0.0, height) if high_at_positive else (height, 0.0)
    local = [(-half_l, -half_w, 0.0), (half_l, -half_w, 0.0),
             (half_l, half_w, 0.0), (-half_l, half_w, 0.0),
             (-half_l, -half_w, low), (half_l, -half_w, high),
             (half_l, half_w, high), (-half_l, half_w, low)]
    cosine, sine = math.cos(rotation), math.sin(rotation)
    verts = [bm.verts.new((cx + px * cosine - py * sine,
                           cy + px * sine + py * cosine,
                           base_z + pz)) for px, py, pz in local]
    for indices in ((0, 1, 2, 3), (4, 7, 6, 5), (0, 4, 5, 1),
                    (1, 5, 6, 2), (2, 6, 7, 3), (3, 7, 4, 0)):
        try:
            bm.faces.new([verts[index] for index in indices])
        except ValueError:
            pass


def add_beam_between(bm, start, end, width, thickness):
    """Create a rectangular beam aligned between two arbitrary 3D points."""
    start_v, end_v = Vector(start), Vector(end)
    delta = end_v - start_v
    length = delta.length
    if length <= 1e-5:
        return False
    midpoint = (start_v + end_v) * 0.5
    rotation = delta.to_track_quat("X", "Z").to_matrix().to_4x4()
    matrix = (Matrix.Translation(midpoint) @ rotation
              @ Matrix.Diagonal((length, width, thickness, 1.0)))
    bmesh.ops.create_cube(bm, size=1.0, matrix=matrix)
    return True


def point_tangent_at_distance(path, distance):
    """Return a stable XY point and tangent along a polyline distance."""
    remaining = max(0.0, float(distance))
    for start, end in zip(path, path[1:]):
        ax, ay = float(start[0]), float(start[1])
        bx, by = float(end[0]), float(end[1])
        dx, dy = bx - ax, by - ay
        length = math.hypot(dx, dy)
        if length <= 1e-8:
            continue
        if remaining <= length:
            t = remaining / length
            return (ax + dx * t, ay + dy * t, dx / length, dy / length)
        remaining -= length
    if len(path or []) >= 2:
        ax, ay = map(float, path[-2][:2])
        bx, by = map(float, path[-1][:2])
        length = math.hypot(bx - ax, by - ay) or 1.0
        return bx, by, (bx - ax) / length, (by - ay) / length
    return 0.0, 0.0, 1.0, 0.0


def add_prism_checked(bm, footprint, base, top):
    points = dedupe_ring(footprint, closed=True)
    if len(points) < 3 or top <= base:
        return False
    signed = sum(
        points[index][0] * points[(index + 1) % len(points)][1]
        - points[(index + 1) % len(points)][0] * points[index][1]
        for index in range(len(points))
    )
    if signed < 0:
        points.reverse()
    add_prism(bm, points, base, top)
    return True


def add_path(bm, path, width, z, height=0.04):
    made = False
    for start, end in zip(path, path[1:]):
        dx, dy = end[0] - start[0], end[1] - start[1]
        length = math.hypot(dx, dy)
        if length < 0.2:
            continue
        add_box(bm, (start[0] + end[0]) / 2, (start[1] + end[1]) / 2,
                z + height / 2, length + width * 0.25, width, height,
                math.atan2(dy, dx))
        made = True
    return made


def add_dashed_path(bm, path, width, z, dash=2.0, gap=2.0, height=0.025):
    """Add stable dash geometry along a mapped line without extending its axis."""
    made = False
    dash, gap = max(0.2, float(dash)), max(0.1, float(gap))
    phase = 0.0
    for start, end in zip(path, path[1:]):
        ax, ay = float(start[0]), float(start[1])
        bx, by = float(end[0]), float(end[1])
        dx, dy = bx - ax, by - ay
        length = math.hypot(dx, dy)
        if length < 0.2:
            continue
        angle, cursor = math.atan2(dy, dx), -phase
        while cursor < length:
            begin, finish = max(0.0, cursor), min(length, cursor + dash)
            if finish - begin >= 0.08:
                middle = (begin + finish) * 0.5 / length
                add_box(bm, ax + dx * middle, ay + dy * middle,
                        z + height / 2.0, finish - begin, width, height, angle)
                made = True
            cursor += dash + gap
        phase = (phase + length) % (dash + gap)
    return made


def offset_polyline(path, distance):
    """Offset a road axis using averaged adjacent segment normals."""
    if len(path or []) < 2:
        return []
    normals = []
    for start, end in zip(path, path[1:]):
        dx, dy = float(end[0]) - float(start[0]), float(end[1]) - float(start[1])
        length = math.hypot(dx, dy) or 1.0
        normals.append((-dy / length, dx / length))
    result = []
    for index, point in enumerate(path):
        before = normals[max(0, index - 1)]
        after = normals[min(len(normals) - 1, index)]
        nx, ny = before[0] + after[0], before[1] + after[1]
        norm = math.hypot(nx, ny) or 1.0
        result.append([float(point[0]) + nx / norm * distance,
                       float(point[1]) + ny / norm * distance])
    return result


def path_length(path):
    return sum(math.hypot(float(end[0]) - float(start[0]),
                          float(end[1]) - float(start[1]))
               for start, end in zip(path or [], (path or [])[1:]))


def add_cylinder(bm, cx, cy, base, radius, height, segments=8):
    """Add a small low-poly cylinder using meter dimensions."""
    if height <= 0.0 or radius <= 0.0:
        return False
    matrix = Matrix.Translation((cx, cy, base + height / 2.0))
    bmesh.ops.create_cone(
        bm, cap_ends=True, cap_tris=False, segments=max(5, int(segments)),
        radius1=radius, radius2=radius, depth=height, matrix=matrix)
    return True


def add_road_arrow(bm, x, y, z, angle, lane_width, directions,
                   length=2.8, stroke=0.18):
    """Add a compact editable road-arrow proxy for explicit turn:lanes data."""
    directions = {str(value).lower() for value in directions if value != "none"}
    if not directions:
        return False
    length = min(max(1.4, float(length)), max(1.6, lane_width * 1.15))
    stroke = min(max(0.10, float(stroke)), lane_width * 0.16)
    fx, fy = math.cos(angle), math.sin(angle)
    lx, ly = -fy, fx
    add_box(bm, x - fx * length * 0.14, y - fy * length * 0.14, z,
            length * 0.72, stroke, 0.025, angle)

    def head(tip_x, tip_y, heading):
        for sign in (-1, 1):
            branch_angle = heading + math.pi + sign * math.radians(36.0)
            branch_length = length * 0.30
            bx = tip_x + math.cos(branch_angle) * branch_length * 0.42
            by = tip_y + math.sin(branch_angle) * branch_length * 0.42
            add_box(bm, bx, by, z, branch_length, stroke, 0.025, branch_angle)

    through = "through" in directions or not directions & {
        "left", "slight_left", "sharp_left", "right", "slight_right",
        "sharp_right", "reverse", "merge_to_left", "merge_to_right"}
    if through:
        head(x + fx * length * 0.34, y + fy * length * 0.34, angle)
    for side, tokens in (
            (1.0, {"left", "slight_left", "sharp_left", "merge_to_left"}),
            (-1.0, {"right", "slight_right", "sharp_right", "merge_to_right"})):
        if directions & tokens:
            joint_x, joint_y = x + fx * length * 0.05, y + fy * length * 0.05
            tip_x = joint_x + lx * side * length * 0.38 + fx * length * 0.18
            tip_y = joint_y + ly * side * length * 0.38 + fy * length * 0.18
            branch_angle = math.atan2(tip_y - joint_y, tip_x - joint_x)
            add_box(bm, (joint_x + tip_x) / 2.0, (joint_y + tip_y) / 2.0,
                    z, math.hypot(tip_x - joint_x, tip_y - joint_y), stroke,
                    0.025, branch_angle)
            head(tip_x, tip_y, branch_angle)
    if "reverse" in directions:
        tip_x, tip_y = x + lx * length * 0.42, y + ly * length * 0.42
        add_box(bm, (x + tip_x) / 2.0, (y + tip_y) / 2.0, z,
                length * 0.42, stroke, 0.025, angle + math.pi / 2.0)
        head(tip_x, tip_y, angle + math.pi / 2.0)
    return True


def road_arrow_placements(road, config=None):
    """Place lane arrows from explicit turn tags without inventing junctions."""
    config = config or {}
    path = road.get("path") or []
    segments = []
    for start, end in zip(path, path[1:]):
        dx, dy = float(end[0]) - float(start[0]), float(end[1]) - float(start[1])
        length = math.hypot(dx, dy)
        if length >= 2.5:
            segments.append((start, end, dx, dy, length))
    if not segments:
        return []
    width = max(2.0, float(road.get("width", 6.0)))
    oneway = str(road.get("oneway") or "").lower() in ("yes", "true", "1", "-1")
    driving_side = str(config.get("driving_side") or "right").lower()
    placements = []
    for profile in urban_detail.road_turn_profiles(road):
        backward = profile["direction"] == "backward"
        start, end, dx, dy, length = segments[0] if backward else segments[-1]
        travel_angle = math.atan2(dy, dx) + (math.pi if backward else 0.0)
        t = 0.42 if backward else 0.58
        cx = float(start[0]) + dx * t
        cy = float(start[1]) + dy * t
        lanes = profile["lanes"]
        use_full_width = oneway or profile["direction_confidence"] == "ambiguous_two_way"
        available_width = width * (0.88 if use_full_width else 0.44)
        lane_width = available_width / max(1, len(lanes))
        left_x, left_y = -math.sin(travel_angle), math.cos(travel_angle)
        if not use_full_width:
            side = -1.0 if driving_side != "left" else 1.0
            cx += left_x * side * width * 0.25
            cy += left_y * side * width * 0.25
        for index, directions in enumerate(lanes):
            lane_offset = ((len(lanes) - 1) / 2.0 - index) * lane_width
            placements.append({
                "point": [cx + left_x * lane_offset, cy + left_y * lane_offset],
                "angle": travel_angle, "lane_width": lane_width,
                "directions": directions, "source": profile["source"],
                "direction_confidence": profile["direction_confidence"],
            })
    return placements


def add_vegetation_instances(points, kind, height, identity, materials,
                             collection, ground_at):
    """Build grouped trunks/crowns for inferred cover or a mapped tree row."""
    trunks, crowns = bmesh.new(), bmesh.new()
    parts = 0
    for index, point in enumerate(points):
        x, y = float(point[0]), float(point[1])
        ground_z = ground_at(x, y)
        variation = 0.84 + ((index * 37 + len(str(identity)) * 11) % 29) / 100.0
        local_h = max(0.5, float(height) * variation)
        if kind == "scrub":
            radius = max(0.35, local_h * 0.42)
            bmesh.ops.create_cone(
                crowns, cap_ends=True, cap_tris=False, segments=7,
                radius1=radius, radius2=radius * 0.42, depth=local_h,
                matrix=Matrix.Translation((x, y, ground_z + local_h / 2.0)))
            parts += 1
            continue
        trunk_h = local_h * 0.48
        add_cylinder(trunks, x, y, ground_z, max(0.07, local_h * 0.025),
                     trunk_h, segments=7)
        crown_h = local_h * 0.62
        crown_radius = local_h * (0.22 if kind == "orchard" else 0.27)
        bmesh.ops.create_cone(
            crowns, cap_ends=True, cap_tris=False, segments=8,
            radius1=crown_radius, radius2=crown_radius * 0.38,
            depth=crown_h,
            matrix=Matrix.Translation((x, y, ground_z + trunk_h + crown_h * 0.34)))
        parts += 2
    first = finalize("VegetationTrunks_" + safe_name(identity), trunks,
                     materials["TRUNK"], collection)
    second = finalize("VegetationCrowns_" + safe_name(identity), crowns,
                      materials["SHRUB"] if kind == "scrub" else materials["FOLIAGE"],
                      collection)
    return {"objects": int(bool(first)) + int(bool(second)),
            "instances": len(points), "parts": parts}


def add_plate_shape(bm, cx, cy, cz, width, height, depth, angle,
                    shape="rectangle", scale=1.0):
    """Add an editable extruded sign plate in a vertical oriented plane."""
    shape = str(shape or "rectangle").lower()
    if shape == "circle":
        points = [(math.cos(2 * math.pi * i / 16) * 0.5,
                   math.sin(2 * math.pi * i / 16) * 0.5) for i in range(16)]
    elif shape == "octagon":
        points = [(math.cos(math.radians(22.5 + 45 * i)) * 0.5,
                   math.sin(math.radians(22.5 + 45 * i)) * 0.5) for i in range(8)]
    elif shape == "triangle_down":
        points = [(-0.50, 0.42), (0.50, 0.42), (0.0, -0.50)]
    elif shape == "triangle_up":
        points = [(-0.50, -0.42), (0.50, -0.42), (0.0, 0.50)]
    elif shape == "diamond":
        points = [(0.0, 0.50), (0.50, 0.0), (0.0, -0.50), (-0.50, 0.0)]
    else:
        points = [(-0.50, -0.50), (0.50, -0.50), (0.50, 0.50), (-0.50, 0.50)]
    tangent = (math.cos(angle), math.sin(angle), 0.0)
    normal = (-math.sin(angle), math.cos(angle), 0.0)
    vertices = []
    for side in (-1.0, 1.0):
        layer = []
        for u, v in points:
            layer.append(bm.verts.new((
                cx + tangent[0] * u * width * scale + normal[0] * side * depth * 0.5,
                cy + tangent[1] * u * width * scale + normal[1] * side * depth * 0.5,
                cz + v * height * scale,
            )))
        vertices.append(layer)
    bm.faces.new(list(reversed(vertices[0])))
    bm.faces.new(vertices[1])
    for index in range(len(points)):
        nxt = (index + 1) % len(points)
        bm.faces.new((vertices[0][index], vertices[0][nxt],
                      vertices[1][nxt], vertices[1][index]))
    return True


def is_roof_only(feature):
    """Return whether a footprint represents cover without enclosing walls."""
    if str(feature.get("structure_mode", "")).lower() == "roof_only":
        return True
    return str(feature.get("type") or feature.get("building_part") or "").lower() \
        in {"roof", "canopy", "carport"}


def covered_structure_spec(feature, style):
    """Resolve bounded procedural cover detail from geometry and style."""
    cfg = style.get("covered_structures") or {}
    bottom = float(feature.get("min_height", 3.0))
    top = max(bottom + 0.18, float(feature.get("height", bottom + 0.35)))
    thickness = min(top - bottom, max(0.12, float(cfg.get("roof_thickness", 0.28))))
    spacing = max(2.0, float(cfg.get("column_spacing", 7.0)))
    return {
        "enabled": bool(cfg.get("enabled", True)),
        "bottom": bottom,
        "top": top,
        "roof_bottom": top - thickness,
        "thickness": thickness,
        "column_spacing": spacing,
        "column_size": max(0.12, float(cfg.get("column_size", 0.22))),
        "column_inset": max(0.0, float(cfg.get("column_inset", 0.35))),
        "max_columns": max(4, int(cfg.get("max_columns", 24))),
        "edge_beams": bool(cfg.get("edge_beams", True)),
        "edge_beam_width": max(0.08, float(cfg.get("edge_beam_width", 0.16))),
        "edge_beam_height": max(0.08, float(cfg.get("edge_beam_height", 0.20))),
    }


def covered_support_points(points, spacing=7.0, inset=0.35, max_columns=24):
    """Sample support locations around a roof perimeter deterministically."""
    ring = [tuple(map(float, point[:2])) for point in points]
    if len(ring) > 1 and math.hypot(ring[0][0] - ring[-1][0],
                                    ring[0][1] - ring[-1][1]) < 1e-6:
        ring.pop()
    if len(ring) < 3:
        return []
    cx, cy = centroid(ring)
    candidates = []
    for start, end in zip(ring, ring[1:] + ring[:1]):
        dx, dy = end[0] - start[0], end[1] - start[1]
        length = math.hypot(dx, dy)
        count = max(1, int(math.ceil(length / max(2.0, spacing))))
        for index in range(count):
            t = index / count
            x, y = start[0] + dx * t, start[1] + dy * t
            vx, vy = cx - x, cy - y
            distance = math.hypot(vx, vy)
            if distance > 1e-6:
                x += inset * vx / distance
                y += inset * vy / distance
            if not candidates or math.hypot(x - candidates[-1][0],
                                            y - candidates[-1][1]) > 0.25:
                candidates.append((x, y))
    if len(candidates) <= max_columns:
        return candidates
    step = len(candidates) / float(max_columns)
    return [candidates[min(len(candidates) - 1, int(index * step))]
            for index in range(max_columns)]


def add_covered_structure(footprint, feature, identity, style, roof_material,
                          support_material, collection, ground_z=0.0):
    """Build an open cover as roof slab + beams + supports, never as walls."""
    spec = covered_structure_spec(feature, style)
    if not spec["enabled"]:
        return {"objects": 0, "columns": 0, "edge_beams": 0}
    bottom = ground_z + spec["bottom"]
    top = ground_z + spec["top"]
    roof_bottom = ground_z + spec["roof_bottom"]
    roof = bmesh.new()
    if not add_prism_checked(roof, footprint, roof_bottom, top):
        roof.free()
        return {"objects": 0, "columns": 0, "edge_beams": 0}
    roof_obj = finalize("CoverRoof_" + safe_name(identity), roof,
                        roof_material, collection)
    if roof_obj:
        roof_obj["detail_kind"] = "open_cover_roof"
        roof_obj["source"] = feature.get("source", "osm")

    supports = bmesh.new()
    points = covered_support_points(
        footprint, spec["column_spacing"], spec["column_inset"],
        spec["max_columns"])
    column_height = max(0.2, bottom - ground_z)
    for x, y in points:
        add_cylinder(supports, x, y, ground_z, spec["column_size"] / 2.0,
                     column_height, segments=8)
    support_obj = finalize("CoverSupports_" + safe_name(identity), supports,
                           support_material, collection)
    if support_obj:
        support_obj["detail_kind"] = "inferred_cover_supports"

    beam_count = 0
    if spec["edge_beams"]:
        beams = bmesh.new()
        beam_z = max(ground_z, bottom - spec["edge_beam_height"])
        if add_path(beams, footprint, spec["edge_beam_width"], beam_z,
                    spec["edge_beam_height"]):
            beam_obj = finalize("CoverBeams_" + safe_name(identity), beams,
                                support_material, collection)
            if beam_obj:
                beam_obj["detail_kind"] = "inferred_cover_edge_beams"
                beam_count = max(0, len(footprint) - 1)
        else:
            beams.free()
    return {"objects": int(bool(roof_obj)) + int(bool(support_obj)) + int(bool(beam_count)),
            "columns": len(points), "edge_beams": beam_count}


def urban_object_spec(feature, style):
    """Return semantic dimensions for an explicit OSM point object."""
    return urban_detail.object_spec(feature, style)


def add_urban_object(feature, identity, style, materials, collection,
                     ground_z=0.0):
    """Build a readable low-poly object from its semantic OSM kind."""
    spec = urban_object_spec(feature, style)
    if not spec["enabled"] or not feature.get("point"):
        return {"objects": 0, "parts": 0}
    x, y = map(float, feature["point"][:2])
    h, w, depth, kind = spec["height"], spec["width"], spec["depth"], spec["kind"]
    bearing = spec["direction"] if spec["direction"] is not None else 0.0
    angle = math.radians(90.0 - bearing)
    segments = int((style.get("urban_objects") or {}).get("object_segments", 8))
    main, secondary, accent = bmesh.new(), bmesh.new(), bmesh.new()
    main_material, secondary_material = materials["METAL"], materials["FEATURE"]
    accent_material = materials["SIGN_DARK"]
    text_material = materials["SIGN_DARK"]
    text_anchor = None

    if kind == "pedestrian_elevator":
        # Compact, legible lift shaft proxy.  The point is authoritative; the
        # cabin/roof/door are bounded geometry, never an invented building.
        base_z = ground_z + 0.04
        add_box(main, x, y, base_z + 0.06, w * 1.10, depth * 1.10, 0.12, angle)
        add_box(main, x, y, base_z + h * 0.52, w, depth, h, angle)
        add_box(secondary, x, y, base_z + h + 0.06, w * 1.10, depth * 1.10, 0.12, angle)
        add_box(accent, x + math.cos(angle) * depth * 0.51,
                y + math.sin(angle) * depth * 0.51,
                base_z + h * 0.48, 0.035, max(0.65, w * 0.55), h * 0.70,
                angle + math.pi / 2.0)
        main_material, secondary_material = materials["METAL"], materials["SIGN_FACE"]
        accent_material = materials["SIGN_DARK"]
    elif kind == "manhole_cover":
        surface_z = ground_z + spec.get("road_z", 0.06) + 0.05
        add_cylinder(main, x, y, surface_z, w * 0.5, h,
                     segments=max(16, segments))
        add_cylinder(secondary, x, y, surface_z + h,
                     w * 0.34, 0.012, segments=max(16, segments))
        main_material, secondary_material = materials["METAL"], materials["SIGN_DARK"]
    elif kind == "drainage_inlet":
        surface_z = ground_z + spec.get("road_z", 0.06) + 0.05
        add_box(main, x, y, surface_z, w, depth, h, angle)
        for index in range(6):
            offset = (index - 2.5) * w / 7.0
            bx = x + math.cos(angle) * offset
            by = y + math.sin(angle) * offset
            add_box(secondary, bx, by, surface_z + h,
                    max(0.025, w * 0.045), depth * 0.78, 0.018, angle)
        main_material, secondary_material = materials["SIGN_DARK"], materials["METAL"]
    elif kind == "curb_ramp":
        surface_z = ground_z + spec.get("road_z", 0.06) + 0.045
        add_wedge(main, x, y, surface_z, max(0.65, depth), max(0.8, w),
                  min(0.08, max(0.02, h)), angle, high_at_positive=True)
        if spec["tactile_paving"]:
            tx = x + math.cos(angle) * depth * 0.28
            ty = y + math.sin(angle) * depth * 0.28
            add_box(secondary, tx, ty, surface_z + min(0.08, h) + 0.012,
                    max(0.65, w * 0.82), max(0.30, depth * 0.28), 0.025,
                    angle + math.pi / 2.0)
        main_material, secondary_material = materials["FOOTWAY"], materials["TACTILE"]
    elif kind in ("raised_crossing", "speed_table"):
        road_width = spec["road_width"]
        total_length = max(3.2, depth)
        table_height = min(0.16, max(0.055, h))
        ramp_length = min(1.4, total_length * 0.25)
        deck_length = max(1.2, total_length - ramp_length * 2.0)
        tangent = (math.cos(angle), math.sin(angle))
        add_box(main, x, y, ground_z + spec.get("road_z", 0.06)
                + 0.045 + table_height * 0.5,
                deck_length, road_width * 0.96, table_height, angle)
        for side in (-1, 1):
            offset = side * (deck_length * 0.5 + ramp_length * 0.5)
            add_wedge(main, x + tangent[0] * offset, y + tangent[1] * offset,
                      ground_z + spec.get("road_z", 0.06) + 0.045,
                      ramp_length, road_width * 0.96, table_height, angle,
                      high_at_positive=(side < 0))
        if kind == "raised_crossing" and spec["crossing_markings"] != "no":
            for index in range(7):
                offset = (index - 3) * deck_length / 8.0
                add_box(secondary, x + tangent[0] * offset,
                        y + tangent[1] * offset,
                        ground_z + spec.get("road_z", 0.06) + 0.055
                        + table_height,
                        max(0.16, deck_length / 13.0), road_width * 0.88,
                        0.025, angle)
        if kind == "raised_crossing" and spec["tactile_paving"]:
            normal = (-math.sin(angle), math.cos(angle))
            for side in (-1, 1):
                pad_x = x + normal[0] * side * road_width * 0.54
                pad_y = y + normal[1] * side * road_width * 0.54
                add_box(accent, pad_x, pad_y,
                        ground_z + spec.get("road_z", 0.06) + 0.055
                        + table_height,
                        max(0.85, deck_length * 0.55), 0.62, 0.025, angle)
        main_material, secondary_material = materials["ASPHALT"], materials["CROSSING"]
        accent_material = materials["TACTILE"]
    elif kind == "pedestrian_crossing":
        road_width = spec["road_width"]
        crossing_depth = max(2.0, depth)
        surface_z = ground_z + spec.get("road_z", 0.06) + 0.055
        stripe_count = 7
        if spec["crossing_markings"] != "no":
            stripe_width = crossing_depth / (stripe_count * 1.75)
            for index in range(stripe_count):
                offset = (index - (stripe_count - 1) / 2.0) * crossing_depth / stripe_count
                sx = x + math.cos(angle) * offset
                sy = y + math.sin(angle) * offset
                add_box(main, sx, sy, surface_z,
                        road_width * 0.92, stripe_width, 0.035,
                        angle + math.pi / 2.0)
        if spec["tactile_paving"]:
            normal = (-math.sin(angle), math.cos(angle))
            for side in (-1, 1):
                tx = x + normal[0] * side * road_width * 0.56
                ty = y + normal[1] * side * road_width * 0.56
                add_box(secondary, tx, ty, surface_z + 0.01,
                        crossing_depth * 0.78, 0.65, 0.055, angle)
        if spec.get("crossing_island"):
            island_length = max(0.65, min(1.35, road_width * 0.13))
            for side in (-1, 1):
                offset = crossing_depth * 0.5 + island_length * 0.5 + 0.22
                ix = x + math.cos(angle) * side * offset
                iy = y + math.sin(angle) * side * offset
                add_box(accent, ix, iy, surface_z + 0.055,
                        island_length, 0.72, 0.10, angle)
            accent_material = materials["KERB"]
        main_material, secondary_material = materials["CROSSING"], materials["TACTILE"]
    elif kind == "stop_line":
        surface_z = ground_z + spec.get("road_z", 0.06) + 0.055
        add_box(main, x, y, surface_z,
                spec["road_width"] * 0.92, max(0.18, depth), 0.03,
                angle + math.pi / 2.0)
        main_material = materials["CROSSING"]
    elif kind == "traffic_island":
        island_width = max(0.75, depth)
        body_length = max(0.25, w - island_width)
        add_box(main, x, y, ground_z + h * 0.5,
                body_length, island_width, h, angle)
        for side in (-1, 1):
            cx = x + math.cos(angle) * side * body_length * 0.5
            cy = y + math.sin(angle) * side * body_length * 0.5
            add_cylinder(main, cx, cy, ground_z, island_width * 0.5, h,
                         segments=max(10, segments))
        add_box(secondary, x, y, ground_z + h + 0.025,
                max(0.2, body_length * 0.92), island_width * 0.72, 0.05, angle)
        main_material, secondary_material = materials["KERB"], materials["GREEN"]
    elif kind == "painted_island":
        stripe_count = 6
        for index in range(stripe_count):
            along = (index - (stripe_count - 1) / 2.0) * w / stripe_count
            sx = x + math.cos(angle) * along
            sy = y + math.sin(angle) * along
            add_box(main, sx, sy, ground_z + 0.095,
                    max(0.20, w / (stripe_count * 1.7)), depth, 0.025,
                    angle + math.radians(24.0))
        main_material = materials["CROSSING"]
    elif kind == "tree":
        trunk_h = h * 0.48
        add_cylinder(main, x, y, ground_z, max(0.10, w * 0.07), trunk_h,
                     segments=segments)
        crown_h = max(1.0, h - trunk_h * 0.72)
        crown_center = ground_z + trunk_h + crown_h * 0.38
        bmesh.ops.create_cone(
            secondary, cap_ends=True, cap_tris=False,
            segments=max(7, int((style.get("urban_objects") or {}).get(
                "tree_segments", 10))), radius1=w * 0.48, radius2=w * 0.16,
            depth=crown_h,
            matrix=Matrix.Translation((x, y, crown_center)))
        main_material, secondary_material = materials["TRUNK"], materials["FOLIAGE"]
    elif kind == "street_lamp":
        pole_r = max(0.045, w * 0.32)
        add_cylinder(main, x, y, ground_z, pole_r, h * 0.93, segments=segments)
        arm = max(0.45, h * 0.11)
        add_box(main, x + math.cos(angle) * arm * 0.42,
                y + math.sin(angle) * arm * 0.42,
                ground_z + h * 0.92, arm, pole_r * 1.5, pole_r * 1.5, angle)
        add_box(secondary, x + math.cos(angle) * arm * 0.88,
                y + math.sin(angle) * arm * 0.88,
                ground_z + h * 0.89, max(0.22, w * 1.8), max(0.12, w),
                max(0.08, w * 0.45), angle)
        secondary_material = materials["LIGHT"]
    elif kind == "bench":
        length, depth = max(1.2, w), 0.48
        add_box(main, x, y, ground_z + h * 0.55,
                length, depth, 0.10, angle)
        bx = x - math.sin(angle) * depth * 0.44
        by = y + math.cos(angle) * depth * 0.44
        add_box(main, bx, by, ground_z + h * 0.78,
                length, 0.08, h * 0.42, angle)
        for sign in (-1, 1):
            lx = x + math.cos(angle) * length * 0.34 * sign
            ly = y + math.sin(angle) * length * 0.34 * sign
            add_box(secondary, lx, ly, ground_z + h * 0.27,
                    0.09, 0.34, h * 0.54, angle)
        main_material, secondary_material = materials["WOOD"], materials["METAL"]
    elif kind == "waste_basket":
        add_box(main, x, y, ground_z + h * 0.5, w, w, h)
        add_box(secondary, x, y, ground_z + h + 0.025, w * 1.06, w * 1.06, 0.05)
    elif kind == "drinking_water":
        add_cylinder(main, x, y, ground_z, w * 0.35, h * 0.82, segments=segments)
        add_box(main, x, y, ground_z + h * 0.82, w, w * 0.72, h * 0.14)
        add_cylinder(secondary, x + w * 0.22, y, ground_z + h * 0.90,
                     max(0.02, w * 0.05), h * 0.10, segments=6)
    elif kind == "bicycle_parking":
        rack_count = 3
        for index in range(rack_count):
            offset = (index - 1) * max(0.55, w * 0.45)
            rx = x + math.cos(angle) * offset
            ry = y + math.sin(angle) * offset
            for side in (-1, 1):
                px = rx - math.sin(angle) * side * 0.32
                py = ry + math.cos(angle) * side * 0.32
                add_cylinder(main, px, py, ground_z, 0.025, h * 0.72, segments=6)
            add_box(main, rx, ry, ground_z + h * 0.72,
                    0.05, 0.68, 0.05, angle)
    elif kind == "shelter":
        depth, roof_h = max(1.6, w * 0.62), 0.16
        add_box(main, x, y, ground_z + h - roof_h / 2.0,
                w, depth, roof_h, angle)
        for along in (-1, 1):
            for across in (-1, 1):
                ox = math.cos(angle) * along * w * 0.43 - math.sin(angle) * across * depth * 0.38
                oy = math.sin(angle) * along * w * 0.43 + math.cos(angle) * across * depth * 0.38
                add_cylinder(secondary, x + ox, y + oy, ground_z, 0.055,
                             h - roof_h, segments=6)
        add_box(secondary, x - math.sin(angle) * depth * 0.42,
                y + math.cos(angle) * depth * 0.42,
                ground_z + h * 0.52, w * 0.82, 0.06, h * 0.72, angle)
    elif kind == "bollard":
        add_cylinder(main, x, y, ground_z, w * 0.5, h, segments=segments)
    elif kind == "gate":
        for side in (-1, 1):
            px = x + math.cos(angle) * side * w * 0.5
            py = y + math.sin(angle) * side * w * 0.5
            add_cylinder(main, px, py, ground_z, 0.07, h, segments=segments)
        add_box(main, x, y, ground_z + h * 0.62, w, 0.08, 0.10, angle)
    elif kind == "traffic_signal":
        pole_h = h * 0.84
        add_cylinder(main, x, y, ground_z, max(0.045, w * 0.18), pole_h,
                     segments=segments)
        nx, ny = -math.sin(angle), math.cos(angle)
        hx, hy = x + nx * depth * 0.9, y + ny * depth * 0.9
        add_box(main, hx, hy, ground_z + h * 0.82, w, depth, h * 0.34, angle)
        for offset in (-0.095, 0.0, 0.095):
            add_box(secondary, hx + nx * (depth * 0.56), hy + ny * (depth * 0.56),
                    ground_z + h * 0.82 + offset * h,
                    w * 0.48, 0.035, h * 0.055, angle)
        secondary_material = materials["LIGHT"]
    elif kind in ("traffic_sign", "street_name_sign", "guidepost",
                  "information_board", "map_board", "billboard",
                  "advertising_board", "poster_box", "advertising_screen",
                  "bus_stop"):
        panel_w = spec["panel_width"]
        panel_h = spec["panel_height"]
        plate_z = ground_z + max(panel_h * 0.58, h - panel_h * 0.55)
        supports = 2 if kind in ("billboard", "information_board", "map_board") else 1
        support_span = panel_w * 0.34
        for index in range(supports):
            offset = 0.0 if supports == 1 else (-support_span if index == 0 else support_span)
            px, py = x + math.cos(angle) * offset, y + math.sin(angle) * offset
            add_cylinder(main, px, py, ground_z, max(0.035, depth * 0.32),
                         max(0.15, plate_z - ground_z), segments=segments)
        if kind == "traffic_sign":
            role = spec.get("sign_role") or "information"
            shape = spec.get("sign_shape") or "rectangle"
            if role in ("stop", "give_way", "restriction", "no_entry"):
                secondary_material = materials["SIGN_RED"]
            elif role == "mandatory":
                secondary_material = materials["SIGN_BLUE"]
            elif role == "warning" and shape == "diamond":
                secondary_material = materials["SIGN_YELLOW"]
            elif role == "warning":
                secondary_material = materials["SIGN_RED"]
            elif role == "variable_message":
                secondary_material = materials["SIGN_DARK"]
            else:
                secondary_material = materials["SIGN_FACE"]
            add_plate_shape(secondary, x, y, plate_z, panel_w, panel_h,
                            max(0.05, depth), angle, shape)
            if role in ("give_way", "restriction"):
                add_plate_shape(accent, x - math.sin(angle) * depth * 0.58,
                                y + math.cos(angle) * depth * 0.58, plate_z,
                                panel_w, panel_h, 0.025, angle, shape,
                                scale=0.74 if role == "give_way" else 0.72)
                accent_material = materials["SIGN_FACE"]
            elif role == "warning" and shape == "triangle_up":
                add_plate_shape(accent, x - math.sin(angle) * depth * 0.58,
                                y + math.cos(angle) * depth * 0.58, plate_z,
                                panel_w, panel_h, 0.025, angle, shape, scale=0.72)
                accent_material = materials["SIGN_FACE"]
            elif role == "no_entry":
                add_box(accent, x - math.sin(angle) * depth * 0.58,
                        y + math.cos(angle) * depth * 0.58, plate_z,
                        panel_w * 0.70, 0.025, panel_h * 0.18, angle)
                accent_material = materials["SIGN_FACE"]
            text_material = (materials["SIGN_FACE"] if role in
                             ("stop", "mandatory", "variable_message")
                             else materials["SIGN_DARK"])
        elif kind == "guidepost":
            for index, sign in enumerate((-1, 0, 1)):
                blade_z = ground_z + h * (0.64 + index * 0.09)
                blade_angle = angle + (0.28 * sign)
                bx = x + math.cos(blade_angle) * panel_w * 0.12
                by = y + math.sin(blade_angle) * panel_w * 0.12
                add_box(secondary, bx, by, blade_z,
                        panel_w, max(0.05, depth), panel_h * 0.28, blade_angle)
        elif kind == "street_name_sign":
            for blade_angle in (angle, angle + math.pi / 2.0):
                add_box(secondary, x, y, plate_z, panel_w,
                        max(0.05, depth), panel_h * 0.52, blade_angle)
        else:
            add_box(secondary, x, y, plate_z, panel_w,
                    max(0.05, depth), panel_h, angle)
        if kind == "bus_stop":
            tangent = (math.cos(angle), math.sin(angle))
            normal = (-math.sin(angle), math.cos(angle))
            if spec.get("has_shelter"):
                shelter_w, shelter_d = max(2.8, panel_w * 2.8), 1.55
                sx, sy = x - normal[0] * 1.25, y - normal[1] * 1.25
                add_box(main, sx, sy, ground_z + h * 0.94,
                        shelter_w, shelter_d, 0.14, angle)
                for along in (-1, 1):
                    for across in (-1, 1):
                        px = sx + tangent[0] * along * shelter_w * 0.43 + normal[0] * across * shelter_d * 0.38
                        py = sy + tangent[1] * along * shelter_w * 0.43 + normal[1] * across * shelter_d * 0.38
                        add_cylinder(main, px, py, ground_z, 0.045, h * 0.90,
                                     segments=6)
                add_box(secondary, sx - normal[0] * shelter_d * 0.43,
                        sy - normal[1] * shelter_d * 0.43,
                        ground_z + h * 0.52, shelter_w * 0.82, 0.04,
                        h * 0.66, angle)
            if spec.get("has_bench"):
                bx, by = x - normal[0] * 1.28, y - normal[1] * 1.28
                add_box(main, bx, by, ground_z + 0.50,
                        max(1.45, panel_w * 1.9), 0.42, 0.10, angle)
                for side in (-1, 1):
                    lx = bx + tangent[0] * side * max(0.45, panel_w * 0.55)
                    ly = by + tangent[1] * side * max(0.45, panel_w * 0.55)
                    add_box(main, lx, ly, ground_z + 0.26, 0.08, 0.30, 0.52, angle)
            if spec.get("has_bin"):
                bx = x + tangent[0] * max(1.0, panel_w)
                by = y + tangent[1] * max(1.0, panel_w)
                add_box(main, bx, by, ground_z + 0.42, 0.38, 0.38, 0.84, angle)
                add_box(secondary, bx, by, ground_z + 0.86, 0.41, 0.41, 0.05, angle)
            if spec.get("has_display"):
                dx = x + tangent[0] * panel_w * 0.62
                dy = y + tangent[1] * panel_w * 0.62
                add_box(secondary, dx, dy, ground_z + h * 0.64,
                        panel_w * 0.62, max(0.04, depth), panel_h * 0.72, angle)
        if kind != "traffic_sign":
            secondary_material = (materials["LIGHT"] if spec["lit"]
                                  else materials["SIGN_FACE"])
        text_anchor = (x - math.sin(angle) * (depth * 0.65 + 0.025),
                       y + math.cos(angle) * (depth * 0.65 + 0.025), plate_z)
    elif kind == "advertising_column":
        add_cylinder(main, x, y, ground_z, w * 0.5, h * 0.94,
                     segments=max(12, segments))
        add_cylinder(secondary, x, y, ground_z + h * 0.94,
                     w * 0.55, h * 0.06, segments=max(12, segments))
        secondary_material = materials["SIGN_FACE"]
    elif kind == "advertising_totem":
        add_box(main, x, y, ground_z + h * 0.5, w, depth, h, angle)
        add_box(secondary, x - math.sin(angle) * depth * 0.52,
                y + math.cos(angle) * depth * 0.52, ground_z + h * 0.62,
                w * 0.82, 0.035, h * 0.62, angle)
        secondary_material = materials["SIGN_FACE"]
        text_anchor = (x - math.sin(angle) * (depth * 0.56 + 0.025),
                       y + math.cos(angle) * (depth * 0.56 + 0.025),
                       ground_z + h * 0.62)
    elif kind == "flag":
        add_cylinder(main, x, y, ground_z, max(0.045, depth * 0.65), h,
                     segments=segments)
        fx = x + math.cos(angle) * w * 0.48
        fy = y + math.sin(angle) * w * 0.48
        add_box(secondary, fx, fy, ground_z + h * 0.78,
                w, max(0.025, depth), h * 0.30, angle)
        secondary_material = materials["SIGN_FACE"]
    elif kind == "fire_hydrant":
        add_cylinder(main, x, y, ground_z, w * 0.34, h * 0.76,
                     segments=max(8, segments))
        add_cylinder(main, x, y, ground_z + h * 0.76, w * 0.42, h * 0.12,
                     segments=max(8, segments))
        for side in (-1, 1):
            add_box(secondary, x + side * w * 0.38, y,
                    ground_z + h * 0.55, w * 0.26, w * 0.26, w * 0.26)
        secondary_material = materials["PLAY"]
    elif kind in ("post_box", "street_cabinet", "recycling"):
        add_box(main, x, y, ground_z + h * 0.5, w, depth, h, angle)
        add_box(secondary, x, y, ground_z + h * 0.94,
                w * 1.04, depth * 1.04, h * 0.08, angle)
    elif kind == "telephone":
        add_box(main, x, y, ground_z + h * 0.5, w, depth, h, angle)
        add_box(secondary, x - math.sin(angle) * depth * 0.51,
                y + math.cos(angle) * depth * 0.51, ground_z + h * 0.58,
                w * 0.76, 0.035, h * 0.54, angle)
        secondary_material = materials["SIGN_FACE"]
    elif kind == "clock":
        add_cylinder(main, x, y, ground_z, max(0.05, depth * 0.25), h * 0.76,
                     segments=segments)
        add_box(secondary, x, y, ground_z + h * 0.86,
                w, depth, w, angle)
        secondary_material = materials["SIGN_FACE"]
    elif kind == "utility_pole":
        add_cylinder(main, x, y, ground_z, max(0.06, w * 0.38), h,
                     segments=segments)
        add_box(secondary, x, y, ground_z + h * 0.86,
                max(1.2, w * 5.0), w * 0.35, w * 0.35, angle)
    elif kind == "telecom_pole":
        add_cylinder(main, x, y, ground_z, max(0.055, w * 0.38), h,
                     segments=segments)
        add_box(secondary, x, y, ground_z + h * 0.90,
                max(0.75, w * 3.6), w * 0.28, w * 0.28, angle)
        main_material = secondary_material = materials["METAL"]
    elif kind == "fluid_cabinet":
        add_box(main, x, y, ground_z + h * 0.5, w, depth, h, angle)
        add_box(secondary, x, y, ground_z + h * 0.96,
                w * 1.04, depth * 1.04, h * 0.08, angle)
        normal = (-math.sin(angle), math.cos(angle))
        for row in range(3):
            add_box(accent, x + normal[0] * depth * 0.52,
                    y + normal[1] * depth * 0.52,
                    ground_z + h * (0.28 + row * 0.20),
                    w * 0.62, 0.025, h * 0.045, angle)
        utility = str(feature.get("utility") or "").lower()
        main_material = secondary_material = (
            materials["PIPE_GAS"] if utility == "gas" else materials["PIPE_WATER"])
        accent_material = materials["METAL"]
    elif kind == "pumping_station":
        add_box(main, x, y, ground_z + 0.10, w * 1.15, depth * 1.15, 0.20, angle)
        housing_h = h * 0.72
        add_box(main, x, y, ground_z + 0.20 + housing_h * 0.5,
                w, depth, housing_h, angle)
        for side in (-1, 1):
            offset = side * w * 0.24
            px = x + math.cos(angle) * offset
            py = y + math.sin(angle) * offset
            add_cylinder(secondary, px, py, ground_z + 0.20,
                         max(0.16, w * 0.09), housing_h * 0.68,
                         segments=max(10, segments))
            add_box(accent, px, py, ground_z + housing_h * 0.58,
                    w * 0.20, depth * 0.18, h * 0.16, angle)
        main_material = materials["POWER_EQUIPMENT"]
        secondary_material, accent_material = materials["PIPE_WATER"], materials["METAL"]
    elif kind == "pipeline_valve":
        pipe_r = max(0.08, w * 0.18)
        add_cylinder(main, x, y, ground_z, pipe_r, h * 0.72,
                     segments=max(10, segments))
        add_box(main, x, y, ground_z + h * 0.54,
                w * 0.62, depth, h * 0.20, angle)
        wheel_z = ground_z + h * 0.84
        add_cylinder(secondary, x, y, wheel_z - depth * 0.18,
                     w * 0.42, depth * 0.36, segments=max(12, segments))
        add_box(accent, x, y, wheel_z, w * 0.78, 0.06, 0.06, angle)
        add_box(accent, x, y, wheel_z, w * 0.78, 0.06, 0.06,
                angle + math.pi / 2.0)
        main_material, secondary_material = materials["PIPE_GENERIC"], materials["SIGN_RED"]
        accent_material = materials["METAL"]
    elif kind == "pipeline_measurement":
        add_cylinder(main, x, y, ground_z, max(0.08, w * 0.14), h * 0.68,
                     segments=max(10, segments))
        panel_z = ground_z + h * 0.76
        add_box(secondary, x, y, panel_z, w, depth, h * 0.34, angle)
        normal = (-math.sin(angle), math.cos(angle))
        add_cylinder(accent, x + normal[0] * depth * 0.58,
                     y + normal[1] * depth * 0.58,
                     panel_z - w * 0.30, w * 0.27, depth * 0.18,
                     segments=max(12, segments))
        main_material, secondary_material = materials["PIPE_GENERIC"], materials["METAL"]
        accent_material = materials["SIGN_FACE"]
    elif kind in ("power_transformer", "power_substation_kiosk"):
        body_h = h * (0.92 if kind == "power_substation_kiosk" else 0.78)
        add_box(main, x, y, ground_z + body_h * 0.5, w, depth, body_h, angle)
        add_box(secondary, x, y, ground_z + body_h + h * 0.035,
                w * 1.05, depth * 1.05, h * 0.07, angle)
        normal = (-math.sin(angle), math.cos(angle))
        for side in (-0.24, 0.0, 0.24):
            vx = x + math.cos(angle) * side * w + normal[0] * depth * 0.515
            vy = y + math.sin(angle) * side * w + normal[1] * depth * 0.515
            add_box(accent, vx, vy, ground_z + body_h * 0.53,
                    w * 0.13, 0.025, body_h * 0.46, angle)
        main_material = secondary_material = materials["POWER_EQUIPMENT"]
        accent_material = materials["METAL"]
    elif kind in ("telecom_cabinet", "telecom_distribution_point"):
        add_box(main, x, y, ground_z + h * 0.5, w, depth, h, angle)
        add_box(secondary, x, y, ground_z + h * 0.96,
                w * 1.04, depth * 1.04, h * 0.08, angle)
        normal = (-math.sin(angle), math.cos(angle))
        for row in range(3):
            vx = x + normal[0] * depth * 0.515
            vy = y + normal[1] * depth * 0.515
            add_box(accent, vx, vy, ground_z + h * (0.28 + row * 0.18),
                    w * 0.58, 0.02, max(0.018, h * 0.035), angle)
        main_material = secondary_material = materials["METAL"]
        accent_material = materials["SIGN_DARK"]
    elif kind == "power_tower":
        leg_span = max(1.5, w * 0.62)
        for along in (-1, 1):
            for across in (-1, 1):
                ox = math.cos(angle) * along * leg_span * 0.5 \
                    - math.sin(angle) * across * leg_span * 0.32
                oy = math.sin(angle) * along * leg_span * 0.5 \
                    + math.cos(angle) * across * leg_span * 0.32
                add_cylinder(main, x + ox, y + oy, ground_z,
                             max(0.08, w * 0.035), h * 0.92, segments=6)
        for level, span in ((0.54, 0.74), (0.72, 0.92), (0.88, 1.08)):
            add_box(secondary, x, y, ground_z + h * level,
                    max(2.5, w * span), max(0.12, w * 0.055),
                    max(0.12, w * 0.055), angle)
        main_material = secondary_material = materials["METAL"]
    elif kind == "picnic_table":
        add_box(main, x, y, ground_z + h * 0.72, w, depth * 0.42, 0.10, angle)
        for side in (-1, 1):
            ox, oy = -math.sin(angle) * side * depth * 0.36, math.cos(angle) * side * depth * 0.36
            add_box(main, x + ox, y + oy, ground_z + h * 0.48,
                    w, depth * 0.16, 0.09, angle)
        for along in (-1, 1):
            for across in (-1, 1):
                ox = math.cos(angle) * along * w * 0.32 - math.sin(angle) * across * depth * 0.18
                oy = math.sin(angle) * along * w * 0.32 + math.cos(angle) * across * depth * 0.18
                add_box(secondary, x + ox, y + oy, ground_z + h * 0.30,
                        0.09, 0.09, h * 0.60, angle)
        main_material, secondary_material = materials["WOOD"], materials["METAL"]
    elif kind == "parking_meter":
        add_cylinder(main, x, y, ground_z, max(0.045, w * 0.12), h * 0.62,
                     segments=segments)
        add_box(secondary, x, y, ground_z + h * 0.78,
                w, depth, h * 0.36, angle)
        normal = (-math.sin(angle), math.cos(angle))
        add_box(accent, x + normal[0] * depth * 0.53,
                y + normal[1] * depth * 0.53, ground_z + h * 0.82,
                w * 0.58, 0.025, h * 0.14, angle)
        accent_material = materials["LIGHT"]
    elif kind in ("charging_station", "charge_point"):
        add_box(main, x, y, ground_z + h * 0.5, w, depth, h, angle)
        normal = (-math.sin(angle), math.cos(angle))
        add_box(secondary, x + normal[0] * depth * 0.52,
                y + normal[1] * depth * 0.52, ground_z + h * 0.67,
                w * 0.66, 0.035, h * 0.34, angle)
        add_box(accent, x + normal[0] * depth * 0.56,
                y + normal[1] * depth * 0.56, ground_z + h * 0.78,
                w * 0.42, 0.025, h * 0.11, angle)
        for side in (-1, 1):
            hx = x + math.cos(angle) * side * w * 0.44
            hy = y + math.sin(angle) * side * w * 0.44
            add_box(secondary, hx, hy, ground_z + h * 0.52,
                    w * 0.16, depth * 0.36, h * 0.30, angle)
        secondary_material, accent_material = materials["SIGN_FACE"], materials["LIGHT"]
    elif kind in ("vending_machine", "parcel_locker", "atm"):
        add_box(main, x, y, ground_z + h * 0.5, w, depth, h, angle)
        normal = (-math.sin(angle), math.cos(angle))
        front_x = x + normal[0] * depth * 0.52
        front_y = y + normal[1] * depth * 0.52
        accent_x = front_x + normal[0] * 0.035
        accent_y = front_y + normal[1] * 0.035
        add_box(secondary, front_x, front_y, ground_z + h * 0.56,
                w * 0.88, 0.035, h * 0.76, angle)
        if kind == "parcel_locker":
            columns, rows = 6, 4
            for col in range(columns):
                for row in range(rows):
                    offset = (col - (columns - 1) / 2.0) * w * 0.14
                    door_x = accent_x + math.cos(angle) * offset
                    door_y = accent_y + math.sin(angle) * offset
                    add_box(accent, door_x, door_y,
                            ground_z + h * (0.25 + row * 0.18),
                            w * 0.125, 0.022, h * 0.14, angle)
        elif kind == "vending_machine":
            for col in range(3):
                for row in range(4):
                    offset = (col - 1) * w * 0.23
                    item_x = accent_x + math.cos(angle) * offset
                    item_y = accent_y + math.sin(angle) * offset
                    add_box(accent, item_x, item_y,
                            ground_z + h * (0.40 + row * 0.12),
                            w * 0.17, 0.022, h * 0.075, angle)
        else:
            add_box(accent, accent_x, accent_y, ground_z + h * 0.66,
                    w * 0.55, 0.022, h * 0.26, angle)
            add_box(accent, accent_x, accent_y, ground_z + h * 0.43,
                    w * 0.46, 0.024, h * 0.08, angle)
        secondary_material, accent_material = materials["SIGN_DARK"], materials["LIGHT"]
    elif kind == "defibrillator":
        mount_base = ground_z + max(1.0, float(feature.get("min_height", 1.25)))
        add_box(main, x, y, mount_base + h * 0.5, w, depth, h, angle)
        normal = feature.get("front_normal") or [-math.sin(angle), math.cos(angle)]
        add_box(secondary, x + float(normal[0]) * depth * 0.56,
                y + float(normal[1]) * depth * 0.56, mount_base + h * 0.54,
                w * 0.80, 0.025, h * 0.72, angle)
        secondary_material = materials["PLAY"]
    elif kind == "fitness_station":
        station_type = str(spec.get("fitness_station") or "").lower()
        span = max(1.4, w)
        if station_type in ("parallel_bars", "parallel_bars_push_up"):
            for across in (-1, 1):
                oy = -math.sin(angle) * across * depth * 0.34
                ox = math.cos(angle) * 0.0
                add_box(main, x + ox + oy, y + math.sin(angle) * 0.0 + math.cos(angle) * across * depth * 0.34,
                        ground_z + h * 0.48, span, 0.07, 0.07, angle)
                for along in (-1, 1):
                    px = x + math.cos(angle) * along * span * 0.42 - math.sin(angle) * across * depth * 0.34
                    py = y + math.sin(angle) * along * span * 0.42 + math.cos(angle) * across * depth * 0.34
                    add_cylinder(secondary, px, py, ground_z, 0.045, h * 0.48, segments=6)
        else:
            for side in (-1, 1):
                px = x + math.cos(angle) * side * span * 0.45
                py = y + math.sin(angle) * side * span * 0.45
                add_cylinder(main, px, py, ground_z, 0.055, h, segments=6)
            for level in (0.55, 0.98):
                add_box(secondary, x, y, ground_z + h * level,
                        span, 0.07, 0.07, angle)
        main_material, secondary_material = materials["METAL"], materials["PLAY"]
    elif kind in ("statue", "bust"):
        base_h = h * (0.42 if kind == "statue" else 0.55)
        add_box(main, x, y, ground_z + base_h * 0.5, w, depth, base_h, angle)
        torso_h = h * (0.34 if kind == "statue" else 0.25)
        add_cylinder(secondary, x, y, ground_z + base_h,
                     w * 0.24, torso_h, segments=max(8, segments))
        bmesh.ops.create_icosphere(
            secondary, subdivisions=1, radius=w * 0.18,
            matrix=Matrix.Translation((x, y, ground_z + base_h + torso_h + w * 0.16)))
        if kind == "statue":
            for side in (-1, 1):
                add_box(secondary, x + side * w * 0.16, y,
                        ground_z + base_h + torso_h * 0.48,
                        w * 0.18, w * 0.18, torso_h * 1.08, angle)
        main_material, secondary_material = materials["ART_STONE"], materials["ART_METAL"]
    elif kind == "plaque" and spec.get("support") == "wall_resolved":
        mount_base = ground_z + max(0.0, float(feature.get("min_height", 0.0)))
        add_box(secondary, x, y, mount_base + h * 0.5, w, depth, h, angle)
        main_material = secondary_material = materials["ART_STONE"]
    elif kind in ("stele", "plaque", "memorial_stone"):
        base_h = h * 0.16
        add_box(main, x, y, ground_z + base_h * 0.5,
                w * 1.16, depth * 1.25, base_h, angle)
        if kind == "memorial_stone":
            bmesh.ops.create_icosphere(secondary, subdivisions=1, radius=w * 0.5,
                                       matrix=Matrix.Translation((x, y, ground_z + h * 0.55)))
        else:
            add_box(secondary, x, y, ground_z + base_h + (h - base_h) * 0.5,
                    w, depth, h - base_h, angle)
        main_material = secondary_material = materials["ART_STONE"]
    elif kind == "obelisk":
        base_h = h * 0.16
        add_box(main, x, y, ground_z + base_h * 0.5,
                w * 1.35, depth * 1.35, base_h, angle)
        bmesh.ops.create_cone(secondary, cap_ends=True, cap_tris=False, segments=4,
            radius1=w * 0.40, radius2=w * 0.18, depth=h * 0.72,
            matrix=Matrix.Translation((x, y, ground_z + base_h + h * 0.36)))
        bmesh.ops.create_cone(secondary, cap_ends=True, cap_tris=True, segments=4,
            radius1=w * 0.18, radius2=0.0, depth=h * 0.12,
            matrix=Matrix.Translation((x, y, ground_z + h * 0.94)))
        main_material = secondary_material = materials["ART_STONE"]
    elif kind in ("monument", "sculpture", "installation"):
        add_box(main, x, y, ground_z + h * 0.08, w * 1.2, depth * 1.2, h * 0.16, angle)
        if kind == "monument":
            add_box(secondary, x, y, ground_z + h * 0.55,
                    w * 0.42, depth * 0.42, h * 0.78, angle)
        else:
            for index, rotation in enumerate((angle - 0.55, angle + 0.15, angle + 0.72)):
                offset = (index - 1) * w * 0.18
                add_box(secondary, x + math.cos(angle) * offset,
                        y + math.sin(angle) * offset, ground_z + h * (0.42 + index * 0.10),
                        w * 0.28, depth * 0.28, h * (0.60 - index * 0.08), rotation)
        main_material, secondary_material = materials["ART_STONE"], materials["ART_METAL"]
    elif kind == "mural":
        mount_base = ground_z + max(0.0, float(feature.get("min_height", 0.0)))
        add_box(main, x, y, mount_base + h * 0.5, w, depth, h, angle)
        front_normal = feature.get("front_normal") or [-math.sin(angle), math.cos(angle)]
        add_box(secondary, x + float(front_normal[0]) * (depth * 0.55 + 0.014),
                y + float(front_normal[1]) * (depth * 0.55 + 0.014), mount_base + h * 0.52,
                w * 0.94, 0.025, h * 0.90, angle)
        main_material, secondary_material = materials["ART_STONE"], materials["PLAY"]
    elif kind == "fountain":
        basin_h = max(0.22, h * 0.20)
        add_cylinder(main, x, y, ground_z, w * 0.5, basin_h,
                     segments=max(16, segments))
        add_cylinder(secondary, x, y, ground_z + basin_h,
                     w * 0.42, 0.035, segments=max(16, segments))
        add_cylinder(main, x, y, ground_z + basin_h, w * 0.08,
                     max(0.25, h * 0.62), segments=segments)
        main_material, secondary_material = materials["ART_STONE"], materials["WATER"]
    elif kind in ("swing", "slide", "seesaw", "climbingframe", "roundabout", "sandbox"):
        if kind == "swing":
            for side in (-1, 1):
                add_box(main, x + side * w * 0.38, y, ground_z + h * 0.5,
                        0.10, depth, h, angle)
            add_box(main, x, y, ground_z + h, w, 0.10, 0.10, angle)
            for side in (-1, 1):
                add_box(secondary, x + side * w * 0.18, y, ground_z + h * 0.58,
                        0.035, 0.035, h * 0.74, angle)
        elif kind == "slide":
            add_box(main, x - math.cos(angle) * w * 0.28,
                    y - math.sin(angle) * w * 0.28, ground_z + h * 0.62,
                    w * 0.32, depth, h * 0.76, angle)
            add_box(secondary, x + math.cos(angle) * w * 0.18,
                    y + math.sin(angle) * w * 0.18, ground_z + h * 0.38,
                    w * 0.82, depth * 0.52, 0.12, angle)
        elif kind == "seesaw":
            add_cylinder(main, x, y, ground_z, depth * 0.36, h * 0.62, segments=8)
            add_box(secondary, x, y, ground_z + h * 0.72, w, depth, 0.14, angle + 0.10)
        elif kind == "climbingframe":
            for along in (-1, 1):
                for across in (-1, 1):
                    ox = math.cos(angle) * along * w * 0.36 - math.sin(angle) * across * depth * 0.36
                    oy = math.sin(angle) * along * w * 0.36 + math.cos(angle) * across * depth * 0.36
                    add_cylinder(main, x + ox, y + oy, ground_z, 0.045, h, segments=6)
            for level in (0.35, 0.65, 0.95):
                add_box(secondary, x, y, ground_z + h * level, w * 0.78, 0.06, 0.06, angle)
                add_box(secondary, x, y, ground_z + h * level, depth * 0.78, 0.06, 0.06,
                        angle + math.pi / 2.0)
        elif kind == "roundabout":
            add_cylinder(main, x, y, ground_z, w * 0.5, h * 0.18, segments=max(12, segments))
            add_cylinder(secondary, x, y, ground_z + h * 0.18, w * 0.08,
                         h * 0.72, segments=8)
        else:
            add_box(main, x, y, ground_z + h * 0.5, w, depth, h, angle)
            add_box(secondary, x, y, ground_z + h, w * 0.92, depth * 0.92, 0.06, angle)
        main_material, secondary_material = materials["PLAY"], materials["METAL"]
    else:
        add_box(main, x, y, ground_z + h / 2.0, w, w, h, angle)

    first = finalize("Object_" + safe_name(kind) + "_" + safe_name(identity),
                     main, main_material, collection)
    second = finalize("ObjectDetail_" + safe_name(kind) + "_" + safe_name(identity),
                      secondary, secondary_material, collection)
    third = finalize("ObjectAccent_" + safe_name(kind) + "_" + safe_name(identity),
                     accent, accent_material, collection)
    text_obj = None
    text_value = str(spec.get("text") or "").strip()
    if (text_anchor and text_value
            and (style.get("urban_objects") or {}).get("render_text", True)):
        curve = bpy.data.curves.new("UrbanText_" + safe_name(identity), "FONT")
        curve.body = text_value[:80]
        curve.align_x = "CENTER"
        curve.align_y = "CENTER"
        curve.size = max(0.08, min(spec["panel_height"] * 0.28,
                                  spec["panel_width"] / max(3.0, len(text_value) * 0.62)))
        curve.extrude = 0.008
        text_obj = bpy.data.objects.new("UrbanText_" + safe_name(identity), curve)
        text_obj.location = text_anchor
        # Blender font curves are single-sided. +90 degrees presents the glyph
        # face toward the same explicit bearing as the sign panel; -90 made
        # otherwise-correct text appear mirrored from the road-facing camera.
        text_obj.rotation_euler = (math.radians(90.0), 0.0, angle)
        text_obj.scale.x = -1.0
        text_obj.data.materials.append(text_material)
        collection.objects.link(text_obj)
        text_obj["detail_kind"] = "explicit_text"
        text_obj["source"] = feature.get("source", "osm")
    for obj in (first, second, third):
        if obj:
            obj["detail_kind"] = "procedural_" + kind
            obj["source"] = feature.get("source", "osm")
    return {"objects": int(bool(first)) + int(bool(second)) + int(bool(third)) + int(bool(text_obj)),
            "parts": spec["parts"], "text_objects": int(bool(text_obj)),
            "direction_source": spec["direction_source"],
            "dimension_source": feature.get("dimension_source", "semantic_default"),
            "sign_shape": spec.get("sign_shape"),
            "sign_role": spec.get("sign_role"),
            "crossing_markings": spec.get("crossing_markings")}


def finalize(name, bm, material, collection):
    if not bm.faces:
        bm.free()
        return None
    mesh = bpy.data.meshes.new(name)
    bm.to_mesh(mesh)
    bm.free()
    obj = bpy.data.objects.new(name, mesh)
    obj.data.materials.append(material)
    collection.objects.link(obj)
    return obj


def choose_focus(scene, style):
    focus = style.get("focus") or {}
    if focus.get("point") and len(focus["point"]) >= 2:
        point = focus["point"]
        center = float(point[0]), float(point[1])
        source = "style.point"
    else:
        match = focus.get("match")
        candidates = (list(scene.get("special_features", []))
                      + list(scene.get("buildings", []))
                      + list(scene.get("areas", [])))
        selected = next((item for item in candidates if feature_matches(item, match)), None)
        center = centroid(feature_points(selected)) if selected else (0.0, 0.0)
        source = "style.match" if selected else "scene_origin"
    default_span = max(80.0, min(float(scene.get("radius", 350.0)) * 0.7, 320.0))
    return center, float(focus.get("span") or default_span), source


def _road_material(road, materials):
    vehicle_types = {"motorway", "trunk", "primary", "secondary", "tertiary",
                     "residential", "living_street", "unclassified", "service"}
    return materials["ASPHALT"] if road.get("type") in vehicle_types else materials["FOOTWAY"]


def _area_material(area, materials, style):
    if style.get("color_mode") == "scene" and area.get("color"):
        return material_for_color(area["color"], style)
    area_type = str(area.get("type", "")).lower()
    if any(token in area_type for token in ("water", "river", "basin")):
        return materials["WATER"]
    if any(token in area_type for token in ("green", "grass", "park", "garden", "pitch")):
        return materials["GREEN"]
    return materials["AREA"]


def _building_material(building, materials, style):
    if style.get("color_mode") == "scene" and building.get("color"):
        return material_for_color(building["color"], style)
    keys = ("BLD_A", "BLD_B", "BLD_C", "BLD_D")
    seed = zlib.crc32(str(building.get("osm_id", building.get("id", 0))).encode())
    return materials[keys[seed % len(keys)]]


def varied_building_height(building, style, fallback):
    """Reshape only estimated/default heights into a varied but deterministic
    value, driven by osm_id and footprint area. Explicit OSM height/levels are
    left untouched so provenance is preserved. Opt-in via style.height_variation.
    """
    config = style.get("height_variation") or {}
    if not config.get("enabled"):
        return fallback
    source = str(building.get("height_source", "")).lower()
    if source not in ("", "default", "estimate", "estimated"):
        return fallback
    seed = zlib.crc32(("h:" + str(building.get("osm_id", building.get("id", 0)))).encode())
    jitter = (seed % 10007) / 10007.0
    area = poly_area(building.get("footprint", []))
    area_factor = max(0.0, min(1.0, area / float(config.get("area_full", 1600.0))))
    low = float(config.get("factor_min", 0.75))
    high = float(config.get("factor_max", 1.6))
    factor = low + (high - low) * (0.6 * jitter + 0.4 * area_factor)
    varied = float(fallback) * factor
    return max(float(config.get("min", 4.0)), min(float(config.get("max", 60.0)), varied))


def roof_material_for(building, override, style, materials):
    """Return explicit/aerial roof colour before deriving it from the wall."""
    darken = float((style.get("roof_detail") or {}).get("darken", 0.7))
    rgb = override.get("roof_color") or building.get("roof_color")
    if rgb:
        return material_for_color(rgb, style)
    rgb = override.get("color")
    if rgb is None and style.get("color_mode") == "scene":
        rgb = building.get("color")
    if rgb:
        return material_for_color([max(0.0, channel * darken) for channel in rgb[:3]], style)
    return materials.get("ROOF") or materials.get("AREA")


def surface_parameters(material_name):
    """Return conservative PBR parameters from a reusable material class."""
    token = str(material_name or "").strip().lower().replace(" ", "_")
    if "glass" in token:
        return {"roughness": 0.24, "metallic": 0.0}
    if any(value in token for value in ("metal", "steel", "copper", "zinc")):
        return {"roughness": 0.38, "metallic": 0.55}
    if any(value in token for value in ("brick", "stone", "sandstone")):
        return {"roughness": 0.88, "metallic": 0.0}
    if any(value in token for value in ("concrete", "cement", "plaster", "render")):
        return {"roughness": 0.82, "metallic": 0.0}
    if "wood" in token:
        return {"roughness": 0.72, "metallic": 0.0}
    return {"roughness": 0.80, "metallic": 0.0}


def facade_parameters(building, style, height=None, base=0.0):
    """Derive a varied semantic facade/interior grammar from normalized data."""
    return architectural_detail.facade_parameters(
        building, style, height=height, base=base,
        surface=surface_parameters(building.get("building_material")))


def _facade_name(rgb, spec=None):
    quant = tuple(min(9, max(0, int(round(channel * 9)))) for channel in rgb[:3])
    spec = spec or {}
    signature = (int(round(float(spec.get("floor_height", 3.2)) * 10)),
                 int(round(float(spec.get("bay", 3.6)) * 10)),
                 int(round(float(spec.get("window_width_ratio", 0.66)) * 10)),
                 int(round(float(spec.get("window_height_ratio", 0.62)) * 10)))
    return "FACADE_%d%d%d_%02d_%02d_%d%d" % (quant + signature)


def make_facade_material(wall_rgb, style, spec=None):
    """Procedural window/floor facade (shader only, no extra geometry). Windows
    align to each face tangent and are masked off horizontal roof faces."""
    cfg = style.get("facade") or {}
    spec = dict(spec or {})
    name = _facade_name(wall_rgb, spec)
    existing = bpy.data.materials.get(name)
    if existing is not None:
        return existing
    window = list(cfg.get("window_color", [0.05, 0.08, 0.13]))[:3]
    wall = list(wall_rgb[:3])
    wall_linear = [_srgb_to_linear(value) for value in wall]
    window_linear = [_srgb_to_linear(value) for value in window]
    floor_h = max(2.2, float(spec.get("floor_height", cfg.get("floor_height", 3.2))))
    bay = max(2.0, float(spec.get("bay", cfg.get("bay", 3.6))))
    width_ratio = float(spec.get("window_width_ratio", cfg.get("window_width_ratio", 0.66)))
    height_ratio = float(spec.get("window_height_ratio", cfg.get("window_height_ratio", 0.62)))
    material = bpy.data.materials.new(name)
    material.use_nodes = True
    tree = material.node_tree
    tree.nodes.clear()
    nodes, links = tree.nodes, tree.links
    out = nodes.new("ShaderNodeOutputMaterial")
    bsdf = nodes.new("ShaderNodeBsdfPrincipled")
    links.new(bsdf.outputs[0], out.inputs["Surface"])
    geometry = nodes.new("ShaderNodeNewGeometry")
    pos_sep = nodes.new("ShaderNodeSeparateXYZ")
    normal_sep = nodes.new("ShaderNodeSeparateXYZ")
    links.new(geometry.outputs["Position"], pos_sep.inputs[0])
    links.new(geometry.outputs["Normal"], normal_sep.inputs[0])

    z_axis = nodes.new("ShaderNodeCombineXYZ")
    z_axis.inputs["Z"].default_value = 1.0
    tangent = nodes.new("ShaderNodeVectorMath")
    tangent.operation = "CROSS_PRODUCT"
    links.new(z_axis.outputs[0], tangent.inputs[0])
    links.new(geometry.outputs["Normal"], tangent.inputs[1])
    horizontal = nodes.new("ShaderNodeVectorMath")
    horizontal.operation = "DOT_PRODUCT"
    links.new(geometry.outputs["Position"], horizontal.inputs[0])
    links.new(tangent.outputs["Vector"], horizontal.inputs[1])

    def math(op, in0=None, in1=None, a=None, b=None):
        node = nodes.new("ShaderNodeMath")
        node.operation = op
        if a is not None:
            node.inputs[0].default_value = a
        if b is not None:
            node.inputs[1].default_value = b
        if in0 is not None:
            links.new(in0, node.inputs[0])
        if in1 is not None:
            links.new(in1, node.inputs[1])
        return node.outputs[0]

    zf = math("FRACT", in0=math("DIVIDE", in0=pos_sep.outputs["Z"], b=floor_h))
    hf = math("FRACT", in0=math("DIVIDE", in0=horizontal.outputs["Value"], b=bay))
    z_margin = max(0.04, (1.0 - height_ratio) * 0.5)
    h_margin = max(0.04, (1.0 - width_ratio) * 0.5)
    zmask = math("MULTIPLY", in0=math("GREATER_THAN", in0=zf, b=z_margin),
                 in1=math("LESS_THAN", in0=zf, b=1.0 - z_margin))
    hmask = math("MULTIPLY", in0=math("GREATER_THAN", in0=hf, b=h_margin),
                 in1=math("LESS_THAN", in0=hf, b=1.0 - h_margin))
    wall_mask = math("LESS_THAN", in0=math("ABSOLUTE", in0=normal_sep.outputs["Z"]),
                     b=0.55)
    mask = math("MULTIPLY", in0=math("MULTIPLY", in0=zmask, in1=hmask),
                in1=wall_mask)

    mix = nodes.new("ShaderNodeMixRGB")
    mix.blend_type = "MIX"
    links.new(mask, mix.inputs[0])
    mix.inputs[1].default_value = (*wall_linear, 1.0)
    mix.inputs[2].default_value = (*window_linear, 1.0)
    links.new(mix.outputs["Color"], bsdf.inputs["Base Color"])

    rough = math("SUBTRACT", a=float(spec.get("wall_roughness", 0.80)),
                 in1=math("MULTIPLY", in0=mask,
                          b=max(0.0, float(spec.get("wall_roughness", 0.80))
                                - float(spec.get("window_roughness", 0.20)))))
    links.new(rough, bsdf.inputs["Roughness"])
    bsdf.inputs["Metallic"].default_value = float(spec.get("wall_metallic", 0.0))
    return material


def add_facade_panels(footprint, base, top, identity, style, spec, collection):
    """Add symmetric windows, frames, mullions and shallow visible room depth."""
    cfg = style.get("facade") or {}
    empty = {"panels": 0, "frame_parts": 0, "mullions": 0,
             "interior_bays": 0, "lit_rooms": 0, "symmetry_pairs": 0,
             "balconies": 0, "accent_parts": 0}
    if not cfg.get("geometry_enabled", True) or top - base < 2.4:
        return empty
    ring = dedupe_ring(footprint, closed=True)
    if len(ring) < 3:
        return empty
    floor_h = max(2.2, float(spec.get("floor_height", 3.2)))
    bay = max(2.0, float(spec.get("bay", 3.6)))
    floors = max(1, int((top - base) / floor_h))
    width_ratio = float(spec.get("window_width_ratio", 0.66))
    height_ratio = float(spec.get("window_height_ratio", 0.62))
    depth = max(0.02, float(cfg.get("geometry_depth", 0.08)))
    candidates = []
    signed = sum(
        ring[index][0] * ring[(index + 1) % len(ring)][1]
        - ring[(index + 1) % len(ring)][0] * ring[index][1]
        for index in range(len(ring))
    )
    orientation = 1.0 if signed >= 0.0 else -1.0
    for face_index, (start, end) in enumerate(zip(ring, ring[1:] + ring[:1])):
        dx, dy = end[0] - start[0], end[1] - start[1]
        length = math.hypot(dx, dy)
        if length < 1.5:
            continue
        bays = max(1, int(round(length / bay)))
        slot = length / bays
        window_w = min(slot * width_ratio, max(0.6, bay * 0.88))
        nx, ny = orientation * dy / length, orientation * -dx / length
        angle = math.atan2(dy, dx)
        for floor in range(floors):
            cz = base + (floor + 0.5) * ((top - base) / floors)
            window_h = min((top - base) / floors * height_ratio,
                           max(0.8, floor_h * 0.82))
            for bay_index in range(bays):
                position = (bay_index + 0.5) / bays
                candidates.append((
                    start[0] + dx * position + nx * (depth * 0.15),
                    start[1] + dy * position + ny * (depth * 0.15),
                    cz, window_w, window_h, angle, nx, ny,
                    face_index, floor, bay_index, bays,
                ))
    if not candidates:
        return empty
    if str(spec.get("symmetry")) == "clerestory":
        candidates = [item for item in candidates if item[9] == floors - 1]
        if not candidates:
            return empty
    limit = max(1, int(cfg.get("max_windows_per_building", 240)))
    groups = {}
    for candidate in candidates:
        groups.setdefault((candidate[8], candidate[9]), []).append(candidate)
    symmetric_units = []
    for key in sorted(groups):
        row = sorted(groups[key], key=lambda item: item[10])
        for left in range((len(row) + 1) // 2):
            right = len(row) - 1 - left
            unit = [row[left]] if left == right else [row[left], row[right]]
            symmetric_units.append(unit)
    if sum(len(unit) for unit in symmetric_units) <= limit:
        selected = [item for unit in symmetric_units for item in unit]
    else:
        wanted_units = max(1, limit // 2)
        stride = max(1, int(math.ceil(len(symmetric_units) / wanted_units)))
        selected = []
        for unit in symmetric_units[::stride]:
            if len(selected) + len(unit) <= limit:
                selected.extend(unit)
        if not selected:
            selected = [candidates[0]]
    selected_keys = {(item[8], item[9], item[10], item[11]) for item in selected}
    symmetry_pairs = sum(
        1 for item in selected
        if item[10] < item[11] - 1 - item[10]
        and (item[8], item[9], item[11] - 1 - item[10], item[11]) in selected_keys)
    bm = bmesh.new()
    for cx, cy, cz, width, height, angle, _nx, _ny, *_meta in selected:
        add_box(bm, cx, cy, cz, width, depth, height, angle)
    window_rgb = list(cfg.get("window_color", [0.05, 0.08, 0.13]))[:3]
    material = make_glass_material(
        "BLK_FACADE_GLASS_" + safe_name(spec.get("profile", "mixed")), window_rgb,
        roughness=float(spec.get("window_roughness", 0.20)))
    obj = finalize("FacadeWindows_" + safe_name(identity), bm, material, collection)
    if obj is None:
        return empty
    obj["detail_kind"] = "procedural_facade_windows"
    obj["provenance"] = "inferred"
    obj["facade_profile"] = str(spec.get("profile", "mixed"))
    obj["symmetry"] = str(spec.get("symmetry", "grid"))

    frame_parts = 0
    mullion_count = 0
    frames = None
    if cfg.get("frame_enabled", True):
        frame_width = max(0.04, float(cfg.get("frame_width", 0.10)))
        frame_depth = max(depth + 0.01, float(cfg.get("frame_depth", 0.09)))
        frames = bmesh.new()
        divisions = max(1, int(spec.get("mullion_divisions", 1)))
        for cx, cy, cz, width, height, angle, nx, ny, *_meta in selected:
            fx, fy = cx + nx * depth * 0.40, cy + ny * depth * 0.40
            add_box(frames, fx, fy, cz + height / 2.0,
                    width + frame_width * 2.0, frame_depth, frame_width, angle)
            add_box(frames, fx, fy, cz - height / 2.0,
                    width + frame_width * 2.0, frame_depth, frame_width, angle)
            tangent_x, tangent_y = math.cos(angle), math.sin(angle)
            for side in (-1.0, 1.0):
                sx = fx + tangent_x * side * (width + frame_width) / 2.0
                sy = fy + tangent_y * side * (width + frame_width) / 2.0
                add_box(frames, sx, sy, cz, frame_width, frame_depth,
                        height, angle)
            for division in range(1, divisions):
                offset = -width * 0.5 + width * division / divisions
                mx = fx + math.cos(angle) * offset
                my = fy + math.sin(angle) * offset
                add_box(frames, mx, my, cz, frame_width * 0.72,
                        frame_depth, height, angle)
                mullion_count += 1
        frame_rgb = list(cfg.get("frame_color", [0.72, 0.70, 0.66]))[:3]
        frame_obj = finalize("FacadeFrames_" + safe_name(identity), frames,
                             make_material("BLK_FACADE_FRAME", frame_rgb,
                                           roughness=0.55), collection)
        if frame_obj:
            frame_obj["detail_kind"] = "procedural_facade_window_frames"
            frame_obj["provenance"] = "inferred"
            frame_parts = len(selected) * 4
            obj["frame_parts"] = frame_parts
            obj["mullions"] = mullion_count

    arch_cfg = style.get("architectural_detail") or {}
    interior_bays = lit_rooms = 0
    interior_enabled = bool(arch_cfg.get("visible_interiors", True))
    if interior_enabled:
        interior_limit = max(0, int(arch_cfg.get(
            "max_interior_bays_per_building", 180)))
        interior_selected = selected[:interior_limit]
        lit_bm, dark_bm, partitions = bmesh.new(), bmesh.new(), bmesh.new()
        lit_ratio = max(0.0, min(1.0, float(arch_cfg.get("lit_ratio", 0.38))))
        seed = int(spec.get("seed", 0))
        for item_index, candidate in enumerate(interior_selected):
            cx, cy, cz, width, height, angle, nx, ny = candidate[:8]
            ix, iy = cx - nx * depth * 0.10, cy - ny * depth * 0.10
            # Light adjacent bays in small room clusters rather than producing
            # an implausible checkerboard of unrelated pixels.
            cluster = candidate[10] // 2
            is_lit = ((seed + candidate[8] * 131 + candidate[9] * 47
                       + cluster * 19) % 1000) < lit_ratio * 1000
            target = lit_bm if is_lit else dark_bm
            add_box(target, ix, iy, cz, width * 0.90, depth * 0.18,
                    height * 0.88, angle)
            # A sill and offset divider give each opening readable room depth.
            add_box(partitions, ix + nx * depth * 0.12, iy + ny * depth * 0.12,
                    cz - height * 0.46, width * 0.92, depth * 0.32,
                    max(0.04, height * 0.035), angle)
            divider = -0.22 if (seed + item_index) % 2 else 0.22
            dx = ix + math.cos(angle) * width * divider
            dy = iy + math.sin(angle) * width * divider
            add_box(partitions, dx, dy, cz, max(0.035, width * 0.025),
                    depth * 0.30, height * 0.82, angle)
            interior_bays += 1
            lit_rooms += int(is_lit)
        lit_rgb = list(spec.get("interior_lit_color", [0.90, 0.72, 0.45]))[:3]
        dark_rgb = list(spec.get("interior_dark_color", [0.08, 0.10, 0.13]))[:3]
        _lit = finalize("InteriorLit_" + safe_name(identity), lit_bm,
                        make_interior_material(
                            "BLK_INTERIOR_LIT_" + safe_name(spec.get("interior_palette", "neutral")),
                            lit_rgb, strength=0.55), collection)
        _dark = finalize("InteriorDark_" + safe_name(identity), dark_bm,
                         make_interior_material(
                             "BLK_INTERIOR_DARK_" + safe_name(spec.get("interior_palette", "neutral")),
                             dark_rgb), collection)
        _parts = finalize("InteriorPartitions_" + safe_name(identity), partitions,
                          make_material("BLK_INTERIOR_PARTITIONS", [0.30, 0.31, 0.31],
                                        roughness=0.82), collection)
        for interior_obj in (_lit, _dark, _parts):
            if interior_obj:
                interior_obj["detail_kind"] = "visible_interior_depth"
                interior_obj["provenance"] = "inferred"

    balcony_count = 0
    balcony_every = int(spec.get("balcony_every", 0) or 0)
    if arch_cfg.get("balconies", True) and balcony_every > 0:
        max_balconies = max(0, int(arch_cfg.get("max_balconies_per_building", 36)))
        balconies = bmesh.new()
        for candidate in selected:
            if balcony_count >= max_balconies:
                break
            cx, cy, cz, width, height, angle, nx, ny = candidate[:8]
            floor = candidate[9]
            if floor <= 0 or floor % balcony_every:
                continue
            slab_depth = 0.82
            bx, by = cx + nx * slab_depth * 0.42, cy + ny * slab_depth * 0.42
            add_box(balconies, bx, by, cz - height * 0.50,
                    width + 0.48, slab_depth, 0.10, angle)
            rx, ry = cx + nx * slab_depth * 0.82, cy + ny * slab_depth * 0.82
            add_box(balconies, rx, ry, cz - height * 0.34,
                    width + 0.44, 0.06, 0.54, angle)
            balcony_count += 1
        balcony_obj = finalize("Balconies_" + safe_name(identity), balconies,
                               make_material("BLK_BALCONY", [0.47, 0.48, 0.47],
                                             roughness=0.72), collection)
        if balcony_obj:
            balcony_obj["detail_kind"] = "procedural_balconies"
            balcony_obj["provenance"] = "inferred"

    accent_parts = 0
    profile = str(spec.get("profile", "mixed"))
    accents = bmesh.new()
    if profile in ("education", "healthcare"):
        for candidate in selected:
            cx, cy, cz, width, height, angle, nx, ny = candidate[:8]
            ax, ay = cx + nx * 0.24, cy + ny * 0.24
            add_box(accents, ax, ay, cz + height * 0.51,
                    width + 0.28, 0.42, 0.08, angle)
            accent_parts += 1
    elif profile == "civic":
        for candidate in selected:
            if candidate[9] != 0 or candidate[10] not in (0, candidate[11] - 1):
                continue
            cx, cy, cz, width, height, angle, nx, ny = candidate[:8]
            ax, ay = cx + nx * 0.18, cy + ny * 0.18
            add_box(accents, ax, ay, cz + height * 0.22,
                    max(0.12, width * 0.10), 0.24, height * 1.55, angle)
            accent_parts += 1
    elif profile == "industrial":
        edge = _longest_edge(ring)
        if edge:
            start, end = edge
            dx, dy = end[0] - start[0], end[1] - start[1]
            length = math.hypot(dx, dy)
            signed_ring = sum(
                ring[i][0] * ring[(i + 1) % len(ring)][1]
                - ring[(i + 1) % len(ring)][0] * ring[i][1]
                for i in range(len(ring)))
            orient = 1.0 if signed_ring >= 0 else -1.0
            nx, ny = orient * dy / length, orient * -dx / length
            angle = math.atan2(dy, dx)
            for door_index in range(3):
                position = (door_index + 1) / 4.0
                cx = start[0] + dx * position + nx * 0.10
                cy = start[1] + dy * position + ny * 0.10
                add_box(accents, cx, cy, base + 1.75,
                        min(4.2, length * 0.18), 0.18, 3.5, angle)
                accent_parts += 1
    accent_obj = finalize("FacadeAccents_" + safe_name(identity), accents,
                          make_material("BLK_FACADE_ACCENT", [0.36, 0.38, 0.38],
                                        roughness=0.64), collection)
    if accent_obj:
        accent_obj["detail_kind"] = "semantic_facade_accents"
        accent_obj["facade_profile"] = profile
        accent_obj["provenance"] = "inferred"

    return {"panels": len(selected), "frame_parts": frame_parts,
            "mullions": mullion_count, "interior_bays": interior_bays,
            "lit_rooms": lit_rooms, "symmetry_pairs": symmetry_pairs,
            "balconies": balcony_count, "accent_parts": accent_parts}


def record_facade_detail(appearance, detail, spec):
    if not detail.get("panels"):
        return
    appearance["facade_geometry_buildings"] += 1
    for report_key, detail_key in (
            ("facade_window_panels", "panels"),
            ("facade_window_frame_parts", "frame_parts"),
            ("facade_window_mullions", "mullions"),
            ("visible_interior_bays", "interior_bays"),
            ("lit_interior_rooms", "lit_rooms"),
            ("symmetric_window_pairs", "symmetry_pairs"),
            ("balconies", "balconies"),
            ("facade_accent_parts", "accent_parts")):
        appearance[report_key] += int(detail.get(detail_key, 0))
    profile = str(spec.get("profile", "mixed"))
    appearance["facade_profiles"][profile] = (
        appearance["facade_profiles"].get(profile, 0) + 1)
    appearance["facade_variants"].add(
        "%s:%s" % (profile, spec.get("variant", 0)))


def add_editable_interior_layout(footprint, base, top, identity, building,
                                 style, collection):
    """Add inferred floor plates, corridors, partitions and a service core.

    The shell remains authoritative and this geometry lives in a separately
    toggleable collection.  It is an editable planning scaffold, never a claim
    about the real building's floor plan.
    """
    spec = architectural_detail.interior_layout_spec(
        building, style, height=top, base=base)
    empty = {"objects": 0, "buildings": 0, "floor_slabs": 0,
             "modeled_floors": 0, "corridor_segments": 0,
             "partitions": 0, "cores": 0}
    if not spec["enabled"] or top - base < 2.6:
        return empty
    ring = dedupe_ring(footprint, closed=True)
    edge = _longest_edge(ring)
    if len(ring) < 3 or not edge:
        return empty
    start, end = edge
    dx, dy = end[0] - start[0], end[1] - start[1]
    length = math.hypot(dx, dy)
    if length < 4.0:
        return empty
    angle = math.atan2(dy, dx)
    tx, ty = dx / length, dy / length
    nx, ny = -ty, tx
    cx, cy = centroid(ring)
    area = poly_area(ring)
    depth = max(3.0, min(length * 0.72, area / max(1.0, length) * 0.74))
    inner_length = max(3.0, length * 0.72)
    total_floors = int(spec["total_floors"])
    modeled = int(spec["modeled_floors"])
    selected_floors = sorted(set(
        int(round(index * max(0, total_floors - 1) / max(1, modeled - 1)))
        for index in range(modeled)))
    slab_bm, wall_bm, core_bm = bmesh.new(), bmesh.new(), bmesh.new()
    slabs = corridors = partitions = cores = 0
    max_partitions = int(spec["max_partitions"])
    layout = spec["layout"]
    for floor_index in selected_floors:
        floor_base = base + floor_index * (top - base) / max(1, total_floors)
        floor_top = min(top - 0.04, floor_base + float(spec["slab_thickness"]))
        if add_prism_checked(slab_bm, _scale_ring(ring, cx, cy, 0.94),
                             floor_base + 0.02, floor_top + 0.02):
            slabs += 1
        room_height = min(2.75, max(2.0, (top - base) / max(1, total_floors) - 0.22))
        wall_z = floor_top + room_height * 0.5
        if layout != "open_plan":
            corridor = float(spec["corridor_width"])
            thickness = float(spec["partition_thickness"])
            for side in (-1.0, 1.0):
                wx = cx + nx * side * corridor * 0.5
                wy = cy + ny * side * corridor * 0.5
                add_box(wall_bm, wx, wy, wall_z, inner_length,
                        thickness, room_height, angle)
                corridors += 1
            spacing = 4.2 if layout == "double_loaded_corridor" else 5.4
            room_count = max(2, int(inner_length / spacing))
            for room_index in range(1, room_count):
                if partitions >= max_partitions:
                    break
                along = -inner_length * 0.5 + room_index * inner_length / room_count
                rx = cx + tx * along
                ry = cy + ty * along
                add_box(wall_bm, rx, ry, wall_z, thickness,
                        depth, room_height, angle)
                partitions += 1
        if layout != "open_plan":
            core_along = -inner_length * 0.22
            kx = cx + tx * core_along
            ky = cy + ty * core_along
            add_box(core_bm, kx, ky, wall_z, 3.1, 3.1,
                    room_height, angle)
            cores += 1
    slab_obj = finalize("InteriorSlabs_" + safe_name(identity), slab_bm,
                        make_material("BLK_INTERIOR_SLAB", [0.47, 0.46, 0.43],
                                      roughness=0.88), collection)
    wall_obj = finalize("InteriorPartitionsFull_" + safe_name(identity), wall_bm,
                        make_material("BLK_INTERIOR_WALL", [0.76, 0.75, 0.70],
                                      roughness=0.86), collection)
    core_obj = finalize("InteriorCore_" + safe_name(identity), core_bm,
                        make_material("BLK_INTERIOR_CORE", [0.36, 0.37, 0.38],
                                      roughness=0.82), collection)
    objects = 0
    for obj in (slab_obj, wall_obj, core_obj):
        if obj:
            obj["detail_kind"] = "editable_interior_layout"
            obj["layout"] = layout
            obj["provenance"] = "procedural_inference"
            objects += 1
    if not objects:
        return empty
    return {"objects": objects, "buildings": 1, "floor_slabs": slabs,
            "modeled_floors": len(selected_floors),
            "corridor_segments": corridors, "partitions": partitions,
            "cores": cores}


def record_interior_detail(report, detail):
    for key in ("objects", "buildings", "floor_slabs", "modeled_floors",
                "corridor_segments", "partitions", "cores"):
        report[key] += int(detail.get(key, 0))


def construction_detail_spec(building, style, facade_spec, base, top):
    """Choose bounded construction layers from tags and facade metrics.

    The result never changes the source massing. It only controls inferred
    near-field readability and is therefore safe to disable per run.
    """
    cfg = style.get("construction_detail") or {}
    height = max(0.0, float(top) - float(base))
    part_kind = str(building.get("building_part") or "").lower()
    enabled = bool(cfg.get("enabled", True)) and height >= 3.0 and part_kind != "roof"
    floor_h = max(2.2, float(facade_spec.get("floor_height", 3.2)))
    floors = max(1, int(round(height / floor_h)))
    profile = str(facade_spec.get("profile", "mixed"))
    max_bands = max(0, int(cfg.get("max_floor_bands", 12)))
    possible_bands = max(0, floors - 1)
    band_count = min(possible_bands, max_bands)
    grounded = float(building.get("min_height", base)) <= 0.15
    anchor = bool(building.get("detail_anchor", not building.get("is_building_part")))
    return {
        "enabled": enabled,
        "plinth": enabled and grounded,
        "cornice": enabled,
        "floor_bands": (enabled and bool(cfg.get("floor_bands", True))
                        and profile not in ("industrial",) and band_count > 0),
        "floor_band_count": band_count,
        "floors": floors,
        "entrance": (enabled and grounded and anchor
                     and bool(cfg.get("entrances", True))),
    }


def _outset_ring(points, meters):
    ring = dedupe_ring(points, closed=True)
    if len(ring) < 3 or meters <= 0.0:
        return ring
    cx, cy = centroid(ring)
    radius = sum(math.hypot(p[0] - cx, p[1] - cy) for p in ring) / len(ring)
    return _scale_ring(ring, cx, cy, 1.0 + float(meters) / max(1.0, radius))


def _longest_edge(points):
    ring = dedupe_ring(points, closed=True)
    if len(ring) < 3:
        return None
    return max(zip(ring, ring[1:] + ring[:1]),
               key=lambda pair: math.hypot(pair[1][0] - pair[0][0],
                                           pair[1][1] - pair[0][1]))


def add_construction_details(footprint, base, top, identity, building, style,
                             facade_spec, wall_rgb, collection):
    """Add a plinth, floor strings, cornice and a single inferred entrance.

    All bands for a building share one mesh and are capped by LOD settings.
    Values are labeled as inferred so OSM parts and measured dimensions remain
    distinguishable from presentation geometry.
    """
    cfg = style.get("construction_detail") or {}
    spec = construction_detail_spec(building, style, facade_spec, base, top)
    if not spec["enabled"]:
        return {"objects": 0, "bands": 0, "entrances": 0}
    detail_rgb = [max(0.0, min(1.0, float(value) * 0.90))
                  for value in list(wall_rgb[:3])]
    detail_material = material_for_color(detail_rgb, style)
    ornaments = bmesh.new()
    band_count = 0

    if spec["plinth"]:
        plinth_h = min(float(cfg.get("base_height", 0.42)), (top - base) * 0.16)
        ring = _outset_ring(footprint, float(cfg.get("base_outset", 0.10)))
        if add_prism_checked(ornaments, ring, base, base + plinth_h):
            band_count += 1

    if spec["floor_bands"]:
        wanted = spec["floor_band_count"]
        possible = max(1, spec["floors"] - 1)
        selected = sorted(set(
            max(1, min(possible, int(round((index + 1) * possible / (wanted + 1)))))
            for index in range(wanted)
        ))
        band_h = max(0.03, float(cfg.get("floor_band_height", 0.08)))
        ring = _outset_ring(footprint, float(cfg.get("floor_band_outset", 0.07)))
        floor_step = (top - base) / spec["floors"]
        for floor in selected:
            z = base + floor * floor_step
            if z + band_h < top - 0.15 and add_prism_checked(
                    ornaments, ring, z, z + band_h):
                band_count += 1

    if spec["cornice"]:
        cornice_h = min(max(0.08, float(cfg.get("cornice_height", 0.24))),
                        (top - base) * 0.08)
        ring = _outset_ring(footprint, float(cfg.get("cornice_outset", 0.14)))
        if add_prism_checked(ornaments, ring, top - cornice_h, top):
            band_count += 1

    objects = 0
    obj = finalize("Detail_" + safe_name(identity), ornaments,
                   detail_material, collection)
    if obj is not None:
        obj["detail_kind"] = "procedural_construction_bands"
        obj["provenance"] = "inferred"
        objects += 1

    entrances = 0
    edge = _longest_edge(footprint) if spec["entrance"] else None
    if edge:
        start, end = edge
        dx, dy = end[0] - start[0], end[1] - start[1]
        length = math.hypot(dx, dy)
        if length >= 1.2:
            signed = sum(
                footprint[index][0] * footprint[(index + 1) % len(footprint)][1]
                - footprint[(index + 1) % len(footprint)][0] * footprint[index][1]
                for index in range(len(footprint))
            )
            orientation = 1.0 if signed >= 0.0 else -1.0
            nx, ny = orientation * dy / length, orientation * -dx / length
            width = min(length * 0.38, max(1.0, float(cfg.get("entrance_width", 1.55))))
            height = min(top - base - 0.2, max(1.9, float(cfg.get("entrance_height", 2.45))))
            depth = max(0.04, float(cfg.get("entrance_depth", 0.12)))
            entry = bmesh.new()
            add_box(entry, (start[0] + end[0]) * 0.5 + nx * depth * 0.65,
                    (start[1] + end[1]) * 0.5 + ny * depth * 0.65,
                    base + height * 0.5, width, depth, height,
                    math.atan2(dy, dx))
            entry_material = make_material("BLK_ENTRY", [0.12, 0.10, 0.08],
                                           roughness=0.45)
            entry_obj = finalize("Entry_" + safe_name(identity), entry,
                                 entry_material, collection)
            if entry_obj is not None:
                entry_obj["detail_kind"] = "procedural_entrance"
                entry_obj["provenance"] = "inferred"
                objects += 1
                entrances = 1
    return {"objects": objects, "bands": band_count, "entrances": entrances}


def _scale_ring(points, cx, cy, scale):
    return [(cx + (point[0] - cx) * scale, cy + (point[1] - cy) * scale)
            for point in points]


def is_stadium(building):
    """Tag-driven detection of stadium/grandstand footprints (reusable domain
    semantics, never a specific venue name)."""
    token = " ".join(str(building.get(key, "")) for key in ("type", "kind")).lower()
    return "stadium" in token or "grandstand" in token or "arena" in token


def add_stadium_bowl(footprint, base, height, style, materials, collection,
                     seat_material, wall_material):
    """Replace a stadium's hollow flat-topped extrusion with a real interior:
    an outer perimeter wall plus concentric seating tiers that rake down toward
    the pitch. Geometry-only and reusable for any stadium-tagged footprint.
    """
    cfg = style.get("stadium_interior") or {}
    ring = dedupe_ring(footprint, closed=True)
    if len(ring) < 3:
        return False
    tiers = max(2, int(cfg.get("tiers", 7)))
    inner_scale = float(cfg.get("inner_scale", 0.32))
    pitch_gap = float(cfg.get("pitch_height", 2.0))
    cx, cy = centroid(ring)

    wall = bmesh.new()
    if add_prism_checked(wall, footprint, base, height):
        finalize("Stadium_Wall", wall, wall_material, collection)
    else:
        wall.free()

    span = max(0.5, height - base - pitch_gap)
    seating = bmesh.new()
    count = len(ring)
    for tier in range(tiers):
        scale_outer = 1.0 - (1.0 - inner_scale) * (tier / tiers)
        scale_inner = 1.0 - (1.0 - inner_scale) * ((tier + 1) / tiers)
        z_outer = base + pitch_gap + span * (1.0 - tier / tiers)
        z_inner = base + pitch_gap + span * (1.0 - (tier + 1) / tiers)
        outer = _scale_ring(ring, cx, cy, scale_outer)
        inner = _scale_ring(ring, cx, cy, scale_inner)
        v_outer = [seating.verts.new((p[0], p[1], z_outer)) for p in outer]
        v_tread = [seating.verts.new((p[0], p[1], z_outer)) for p in inner]
        v_riser = [seating.verts.new((p[0], p[1], z_inner)) for p in inner]
        for i in range(count):
            j = (i + 1) % count
            try:  # horizontal seating tread
                seating.faces.new((v_outer[i], v_outer[j], v_tread[j], v_tread[i]))
            except ValueError:
                pass
            try:  # vertical riser down to the next tier
                seating.faces.new((v_tread[i], v_tread[j], v_riser[j], v_riser[i]))
            except ValueError:
                pass
    if not seating.faces:
        seating.free()
        return True
    seating.normal_update()
    mesh = bpy.data.meshes.new("Stadium_Seating")
    seating.to_mesh(mesh)
    seating.free()
    obj = bpy.data.objects.new("Stadium_Seating", mesh)
    obj.data.materials.append(seat_material)
    collection.objects.link(obj)
    return True


# OSM roof:shape values built as real pitched roofs (rest fall back to flat).
# Apex-type shapes converge to a single top point; ridge-type shapes build a
# ridge along the footprint's principal axis (an oriented-bounding-box proxy,
# the standard approach in blender-osm / osm2world for non-rectangular plans).
APEX_ROOF_SHAPES = {"pyramidal", "dome", "onion", "conical", "cone", "round"}
RIDGE_ROOF_SHAPES = {"gabled", "hipped", "half-hipped", "half_hipped",
                     "gambrel", "mansard", "saltbox"}
SLOPE_ROOF_SHAPES = {"skillion", "mono_pitched", "mono-pitched", "lean_to", "shed"}
PITCHED_ROOF_SHAPES = APEX_ROOF_SHAPES | RIDGE_ROOF_SHAPES | SLOPE_ROOF_SHAPES


def _principal_axis(points, cx, cy):
    """Dominant 2D direction of a footprint via the 2x2 covariance eigenvector
    (a lightweight oriented-bounding-box proxy for the roof ridge)."""
    sxx = sum((p[0] - cx) ** 2 for p in points)
    syy = sum((p[1] - cy) ** 2 for p in points)
    sxy = sum((p[0] - cx) * (p[1] - cy) for p in points)
    trace = sxx + syy
    disc = max(0.0, (trace * 0.5) ** 2 - (sxx * syy - sxy * sxy))
    lam = trace * 0.5 + math.sqrt(disc)
    if abs(sxy) > 1e-9:
        vx, vy = lam - syy, sxy
    else:
        vx, vy = (1.0, 0.0) if sxx >= syy else (0.0, 1.0)
    norm = math.hypot(vx, vy) or 1.0
    return vx / norm, vy / norm


def _roof_axis(points, cx, cy, orientation=None, direction=None, shape=None):
    """Resolve a roof axis from OSM orientation/direction before fallback PCA."""
    axis_x, axis_y = _principal_axis(points, cx, cy)
    orientation = str(orientation or "").strip().lower()
    if orientation == "across":
        axis_x, axis_y = -axis_y, axis_x
    if direction is not None and shape in SLOPE_ROOF_SHAPES:
        # OSM bearings are clockwise from north; local +Y is north.
        angle = math.radians(float(direction))
        axis_x, axis_y = math.sin(angle), math.cos(angle)
    return axis_x, axis_y


def roof_height_for(building, style, base, height):
    """Use explicit OSM roof height/levels before a bounded inferred fallback."""
    available = max(0.2, float(height) - float(base))
    explicit = building.get("roof_height")
    if explicit is not None and float(explicit) > 0.05:
        return min(float(explicit), available * 0.85)
    roof_levels = building.get("roof_levels")
    if roof_levels not in (None, 0):
        return min(float(roof_levels) * 3.0, available * 0.85)
    cfg = style.get("roof_shapes") or {}
    return max(1.0, min(float(cfg.get("max_height", 5.0)), 0.28 * available))


def add_pitched_roof(bm, footprint, wall_top, roof_height, shape,
                     orientation=None, direction=None):
    """Build a real roof of the given OSM shape on top of the walls. Robust for
    any footprint; faces that would be degenerate are skipped."""
    ring = dedupe_ring(footprint, closed=True)
    count = len(ring)
    if count < 3 or roof_height <= 0.05:
        return False
    cx, cy = centroid(ring)
    base_z = wall_top
    apex_z = wall_top + roof_height
    base = [bm.verts.new((p[0], p[1], base_z)) for p in ring]

    if shape in APEX_ROOF_SHAPES:
        apex = bm.verts.new((cx, cy, apex_z))
        for i in range(count):
            try:
                bm.faces.new((base[i], base[(i + 1) % count], apex))
            except ValueError:
                pass
        return True

    axis_x, axis_y = _roof_axis(ring, cx, cy, orientation, direction, shape)
    proj = [(p[0] - cx) * axis_x + (p[1] - cy) * axis_y for p in ring]
    lo, hi = min(proj), max(proj)
    mid = (lo + hi) * 0.5

    if shape in SLOPE_ROOF_SHAPES:
        span = (hi - lo) or 1.0
        top = [bm.verts.new((ring[i][0], ring[i][1],
                             base_z + roof_height * ((proj[i] - lo) / span)))
               for i in range(count)]
        for i in range(count):
            j = (i + 1) % count
            try:
                bm.faces.new((base[i], base[j], top[j], top[i]))
            except ValueError:
                pass
        try:
            bm.faces.new(list(reversed(top)))
        except ValueError:
            pass
        return True

    # ridge family (gabled/hipped/...): ridge segment along the principal axis
    inset = 0.15 * (hi - lo)
    r0 = bm.verts.new((cx + axis_x * (lo + inset), cy + axis_y * (lo + inset), apex_z))
    r1 = bm.verts.new((cx + axis_x * (hi - inset), cy + axis_y * (hi - inset), apex_z))
    for i in range(count):
        j = (i + 1) % count
        ridge_i = r0 if proj[i] < mid else r1
        ridge_j = r0 if proj[j] < mid else r1
        try:
            if ridge_i is ridge_j:
                bm.faces.new((base[i], base[j], ridge_i))
            else:
                bm.faces.new((base[i], base[j], ridge_j, ridge_i))
        except ValueError:
            pass
    return True


def make_terrain_sampler(terrain):
    """Return sample(x, y) -> elevation (meters, base at 0) via bilinear
    interpolation over the SRTM/DEM grid. Coordinates are in the scene's local
    meter frame; out-of-range points clamp to the nearest edge."""
    grid = terrain["z"]
    ny = len(grid)
    nx = len(grid[0]) if ny else 0
    extent = float(terrain.get("extent", 1.0)) or 1.0
    zmin = float(terrain.get("zmin", 0.0))
    if nx < 2 or ny < 2:
        return lambda x, y: 0.0

    def sample(x, y):
        fx = min(max((x + extent) / (2.0 * extent) * (nx - 1), 0.0), nx - 1)
        fy = min(max((y + extent) / (2.0 * extent) * (ny - 1), 0.0), ny - 1)
        ix, iy = int(fx), int(fy)
        ix2, iy2 = min(ix + 1, nx - 1), min(iy + 1, ny - 1)
        tx, ty = fx - ix, fy - iy
        top = grid[iy][ix] * (1 - tx) + grid[iy][ix2] * tx
        bottom = grid[iy2][ix] * (1 - tx) + grid[iy2][ix2] * tx
        return (top * (1 - ty) + bottom * ty) - zmin

    return sample


def build_terrain_ground(terrain, material, collection, pad=1.12):
    """Build a displaced ground mesh from the SRTM/DEM grid instead of a flat
    plane. Returns True on success."""
    grid = terrain["z"]
    ny = len(grid)
    nx = len(grid[0]) if ny else 0
    if nx < 2 or ny < 2:
        return False
    extent = float(terrain.get("extent", 1.0))
    zmin = float(terrain.get("zmin", 0.0))
    bm = bmesh.new()
    verts = [[None] * nx for _ in range(ny)]
    for j in range(ny):
        for i in range(nx):
            x = (-extent + 2.0 * extent * i / (nx - 1)) * pad
            y = (-extent + 2.0 * extent * j / (ny - 1)) * pad
            verts[j][i] = bm.verts.new((x, y, grid[j][i] - zmin - 0.05))
    for j in range(ny - 1):
        for i in range(nx - 1):
            try:
                bm.faces.new((verts[j][i], verts[j][i + 1],
                              verts[j + 1][i + 1], verts[j + 1][i]))
            except ValueError:
                pass
    bm.normal_update()
    mesh = bpy.data.meshes.new("BLK_Terrain")
    bm.to_mesh(mesh)
    bm.free()
    obj = bpy.data.objects.new("BLK_Terrain", mesh)
    obj.data.materials.append(material)
    collection.objects.link(obj)
    return True


def _linear_to_srgb(value):
    """Convert a scene-linear channel (Blender image pixel) to display sRGB."""
    value = max(0.0, min(1.0, float(value)))
    if value <= 0.0031308:
        return 12.92 * value
    return 1.055 * (value ** (1.0 / 2.4)) - 0.055


def _meters_to_pixel(x, y, size, meters_per_px):
    """Local meters (origin at scene centre, +y north) -> pixel (from left,
    from top) of a north-up square aerial centred on the scene."""
    half = size * 0.5
    return half + x / meters_per_px, half - y / meters_per_px


def make_image_color_sampler(scene, style, base_dir=None):
    """Return sample(x, y) -> sRGB [r,g,b] read from the authorized aerial
    reference, or None when there is no usable reference. The image is only
    read for colour; it is never added to the scene as geometry or texture."""
    ref = scene.get("satellite_reference")
    cfg = style.get("image_colors") or {}
    if not cfg.get("enabled", True) or not isinstance(ref, dict):
        return None
    raw_path = ref.get("path")
    meters_per_px = ref.get("meters_per_px")
    if not raw_path or not meters_per_px:
        return None
    # scene.json may store a relative reference path; resolve against the run dir.
    candidates = [raw_path]
    if base_dir:
        candidates.append(os.path.join(base_dir, os.path.basename(raw_path)))
        if ref.get("filename"):
            candidates.append(os.path.join(base_dir, ref["filename"]))
    path = next((candidate for candidate in candidates if os.path.exists(candidate)), None)
    if not path:
        return None
    try:
        import numpy as np
        image = bpy.data.images.load(path, check_existing=True)
        width, height = image.size
        if width < 2 or height < 2:
            return None
        pixels = np.array(image.pixels[:], dtype="float32").reshape(height, width, 4)
    except Exception:
        return None
    declared = float(ref.get("size", width)) or width
    mpp = float(meters_per_px) * (declared / width)  # meters per loaded pixel
    patch = max(0, int(cfg.get("patch", 2)))
    boost = float(cfg.get("boost", 1.0))

    def sample(x, y):
        px, py = _meters_to_pixel(x, y, width, mpp)
        col = int(round(px))
        row = height - 1 - int(round(py))  # Blender pixels are bottom-up
        if col < 0 or col >= width or row < 0 or row >= height:
            return None
        c0, c1 = max(0, col - patch), min(width, col + patch + 1)
        r0, r1 = max(0, row - patch), min(height, row + patch + 1)
        block = pixels[r0:r1, c0:c1, :3].reshape(-1, 3)
        if block.size == 0:
            return None
        mean = block.mean(axis=0)
        rgb = [_linear_to_srgb(channel) for channel in mean]
        if boost != 1.0:
            grey = sum(rgb) / 3.0
            rgb = [min(1.0, max(0.0, grey + (c - grey) * boost)) for c in rgb]
        return rgb

    return sample


def setup_sky_world(world, style, sun=None):
    """Set the world to a physical sky gradient aligned to the sun. Uses
    Hosek/Wilkie (Eevee-compatible), falling back to Preetham, then to the flat
    `sky` colour. `sky_model == 'flat'` forces the solid colour."""
    world.use_nodes = True
    tree = world.node_tree
    background = tree.nodes.get("Background") or tree.nodes.new("ShaderNodeBackground")
    output = tree.nodes.get("World Output") or tree.nodes.new("ShaderNodeOutputWorld")
    try:
        tree.links.new(background.outputs[0], output.inputs[0])
    except Exception:
        pass
    for node in list(tree.nodes):
        if node.type == "TEX_SKY":
            tree.nodes.remove(node)
    flat = style.get("sky", [0.60, 0.68, 0.78, 1.3])
    if str(style.get("sky_model", "hosek_wilkie")).lower() in ("flat", "none", "solid"):
        background.inputs[0].default_value = (*flat[:3], 1.0)
        background.inputs[1].default_value = float(flat[3])
        return "flat"
    sky = tree.nodes.new("ShaderNodeTexSky")
    applied = "flat"
    for sky_type in ("HOSEK_WILKIE", "PREETHAM"):
        try:
            sky.sky_type = sky_type
            applied = sky_type.lower()
            break
        except Exception:
            continue
    if applied == "flat":
        tree.nodes.remove(sky)
        background.inputs[0].default_value = (*flat[:3], 1.0)
        background.inputs[1].default_value = float(flat[3])
        return "flat"
    if sun is not None:
        from mathutils import Vector
        light_dir = sun.rotation_euler.to_quaternion() @ Vector((0.0, 0.0, -1.0))
        try:
            sky.sun_direction = (-light_dir).normalized()
        except Exception:
            pass
    for attr, value in (("turbidity", float(style.get("sky_turbidity", 2.6))),
                        ("ground_albedo", float(style.get("sky_ground_albedo", 0.3)))):
        try:
            setattr(sky, attr, value)
        except Exception:
            pass
    try:
        tree.links.new(sky.outputs[0], background.inputs[0])
    except Exception:
        pass
    background.inputs[1].default_value = float(style.get("sky_strength", 1.0))
    return applied


def add_roof_props(style, collection=None):
    """Scatter small deterministic rooftop clutter (chimneys, vents, AC boxes)
    on individual buildings so roofs are not bare. Geometry-only, per-building
    deterministic; returns the number of buildings that received props."""
    cfg = style.get("roof_props") or {}
    if not cfg.get("enabled", True):
        return 0
    from mathutils import Vector
    density = float(cfg.get("density", 1.0))
    prop_mat = make_material("BLK_RoofProp", [0.40, 0.40, 0.42], roughness=0.85)
    if collection is None:
        collection = bpy.data.collections.get("BLK_09_ROOFPROPS")
        if collection is None:
            collection = bpy.data.collections.new("BLK_09_ROOFPROPS")
            bpy.context.scene.collection.children.link(collection)
    made = 0
    for obj in [o for o in bpy.data.objects if o.type == "MESH" and o.name.startswith("Bld_")]:
        corners = [obj.matrix_world @ Vector(corner) for corner in obj.bound_box]
        xs = [v.x for v in corners]
        ys = [v.y for v in corners]
        minx, maxx, miny, maxy = min(xs), max(xs), min(ys), max(ys)
        top = max(v.z for v in corners)
        width, depth = maxx - minx, maxy - miny
        area = width * depth
        if top < 5.0 or area < 60.0:
            continue
        seed = zlib.crc32(obj.name.encode())
        count = max(1, min(5, int(area / 380.0 * density)))
        bm = bmesh.new()
        for k in range(count):
            r1 = ((seed >> (k * 6)) % 1000) / 1000.0
            r2 = ((seed >> (k * 6 + 3)) % 1000) / 1000.0
            r3 = ((seed >> (k * 6 + 9)) % 100) / 100.0
            px = minx + width * (0.2 + 0.6 * r1)
            py = miny + depth * (0.2 + 0.6 * r2)
            prop_h = 1.2 + 2.4 * r3
            prop_s = 0.8 + 1.6 * r3
            add_box(bm, px, py, top + prop_h / 2.0, prop_s, prop_s, prop_h)
        if not bm.faces:
            bm.free()
            continue
        mesh = bpy.data.meshes.new("RoofProps_" + obj.name)
        bm.to_mesh(mesh)
        bm.free()
        prop_obj = bpy.data.objects.new("RoofProps_" + obj.name, mesh)
        prop_obj.data.materials.append(prop_mat)
        collection.objects.link(prop_obj)
        made += 1
    return made


def build_from_scene(scene_path, outdir, slug, style_path=None,
                     do_render=False, samples=None, clear=True):
    with open(scene_path, encoding="utf-8") as stream:
        source = json.load(stream)
    style = load_style(style_path)
    if samples is not None:
        style["samples"] = int(samples)
    os.makedirs(outdir, exist_ok=True)
    if clear:
        safe_clear()

    materials = build_materials(style)
    root = new_collection("BLOCKS_" + safe_name(slug).upper())
    terrain_collection = new_collection("BLK_00_TERRAIN", root)
    road_collection = new_collection("BLK_01_ROADS", root)
    highway_collection = new_collection("BLK_01A_HIGHWAY_DETAIL", root)
    area_collection = new_collection("BLK_02_AREAS", root)
    building_collection = new_collection("BLK_03_BUILDINGS", root)
    interior_collection = new_collection("BLK_BUILDING_INTERIORS", building_collection)
    stadium_collection = new_collection("BLK_03A_FOOTBALL_STADIUM", root)
    hospital_collection = new_collection("BLK_03B_HOSPITAL", root)
    feature_collection = new_collection("BLK_04_FEATURES", root)
    covered_collection = new_collection("BLK_COVERED_STRUCTURES", feature_collection)
    urban_collection = new_collection("BLK_URBAN_OBJECTS", feature_collection)
    signage_collection = new_collection("BLK_SIGNAGE", feature_collection)
    transit_collection = new_collection("BLK_TRANSIT_DETAILS", feature_collection)
    road_surface_collection = new_collection("BLK_ROAD_SURFACE_DETAILS", feature_collection)
    vegetation_area_collection = new_collection("BLK_VEGETATION_AREAS", feature_collection)
    utility_collection = new_collection("BLK_UTILITY_NETWORKS", feature_collection)
    fluid_collection = new_collection("BLK_FLUID_NETWORKS", feature_collection)
    art_collection = new_collection("BLK_MONUMENTS_PUBLIC_ART", feature_collection)
    recreation_collection = new_collection("BLK_RECREATION", feature_collection)
    pedestrian_access_collection = new_collection("BLK_PEDESTRIAN_ACCESS", feature_collection)
    residential_collection = new_collection("BLK_RESIDENTIAL_ZONES", root)
    residential_boundary_collection = new_collection("BLK_RESIDENTIAL_BOUNDARIES", root)
    infrastructure_collection = new_collection("BLK_INFRASTRUCTURE", feature_collection)
    rig_collection = new_collection("BLK_05_CAMERA_LIGHT", root)

    focus_center, focus_span, focus_source = choose_focus(source, style)
    report = {
        "slug": slug,
        "focus": {"center": [round(value, 2) for value in focus_center],
                  "span": round(focus_span, 2), "source": focus_source},
        "roads": 0,
        "areas": 0,
        "buildings_individual": 0,
        "buildings_merged": 0,
        "features": [],
        "covered_structures": {
            "count": 0, "objects": 0, "columns": 0, "edge_beams": 0,
        },
        "urban_objects": {"count": 0, "objects": 0, "parts": 0, "by_kind": {}},
        "urban_detail": {
            "detected": urban_detail.detect(source, style),
            "count": 0, "objects": 0, "parts": 0,
            "text_objects": 0, "explicit_directions": 0,
            "explicit_dimensions": 0, "wall_hosted": 0,
            "wall_host_unresolved": 0, "road_hosted": 0,
            "road_host_unresolved": 0, "by_sign_shape": {},
            "by_family": {}, "by_kind": {},
        },
        "streetscape": {
            "lane_arrow_roads": 0, "lane_arrows": 0,
            "ambiguous_lane_arrow_profiles": 0,
            "kerb_segments": 0, "traffic_islands": 0,
            "stop_lines": 0, "lane_dividers": 0,
            "cycle_lanes": 0, "cycle_lane_m": 0.0,
            "cycle_lane_separators": 0,
            "cycle_protection_elements": 0,
            "bus_lanes": 0, "bus_lane_m": 0.0,
            "bus_lane_metadata_profiles": 0,
            "parking_strips": 0, "parking_strip_m": 0.0,
            "parking_orientations": {},
            "manhole_covers": 0, "drainage_inlets": 0,
            "sidewalk_strips": 0, "sidewalk_m": 0.0,
            "sidewalk_metadata_profiles": 0, "sidewalk_kerb_edges": 0,
            "curb_ramps": 0, "raised_crossings": 0, "speed_tables": 0,
            "curb_ramp_max_height": 0.0,
            "raised_crossing_max_height": 0.0,
            "tree_rows": 0, "utility_lines": 0, "utility_conductors": 0,
        },
        "utility_networks": {
            "substations": 0, "substation_equipment_proxies": 0,
            "transformers": 0, "power_cabinets": 0,
            "telecom_poles": 0, "telecom_cabinets": 0,
            "communication_lines": 0, "communication_conductors": 0,
            "metadata_only_lines": 0,
            "provenance": "osm_geometry+bounded_semantic_proxy",
        },
        "fluid_networks": {
            "visible_lines": 0, "metadata_only_lines": 0,
            "visible_length_m": 0.0, "supports": 0,
            "pumping_stations": 0, "valves": 0, "measurement_points": 0,
            "fluid_cabinets": 0,
            "by_substance": {},
            "provenance": "osm_geometry+explicit_visibility+bounded_semantic_proxy",
        },
        "pedestrian_access": {
            "steps": 0, "step_m": 0.0, "step_count": 0,
            "ramps": 0, "ramp_m": 0.0,
            "escalators": 0, "moving_walkways": 0,
            "elevators": 0, "inclined_elevators": 0,
            "handrails": 0, "handrail_m": 0.0,
            "unspecified_handrails": 0, "max_rise_m": 0.0,
            "provenance": "osm_axis+explicit_access_semantics+bounded_geometry",
        },
        "vegetation_areas": {
            "zones": 0, "instances": 0, "objects": 0, "parts": 0,
            "area_m2": 0.0, "by_kind": {},
            "provenance": "osm_area+deterministic_semantic_inference",
        },
        "residential": {
            **urban_detail.residential_profile(source),
            "zone_area_m2": 0.0, "zone_meshes": 0,
            "mapped_boundary_segments": 0, "inferred_infill_objects": 0,
        },
        "football_stadium": {"detected": False},
        "hospital": {"detected": False},
        "highway": {"detected": False},
        "architectural_detail": {
            "detected": architectural_detail.detect(source, style),
        },
        "building_interiors": {
            "objects": 0, "buildings": 0, "floor_slabs": 0,
            "modeled_floors": 0, "corridor_segments": 0,
            "partitions": 0, "cores": 0,
            "provenance": "procedural_inference",
        },
        "construction_detail": {
            "building_parts": sum(1 for item in source.get("buildings", [])
                                  if item.get("is_building_part")),
            "detail_objects": 0,
            "bands": 0,
            "entrances": 0,
        },
        "building_appearance": {
            "color_sources": {},
            "roof_color_sources": {},
            "facade_shader_buildings": 0,
            "facade_geometry_buildings": 0,
            "facade_window_panels": 0,
            "facade_window_frame_parts": 0,
            "facade_window_mullions": 0,
            "visible_interior_bays": 0,
            "lit_interior_rooms": 0,
            "symmetric_window_pairs": 0,
            "balconies": 0,
            "facade_accent_parts": 0,
            "facade_profiles": {},
            "facade_variants": set(),
            "_facade_confidence_total": 0.0,
            "_roof_confidence_total": 0.0,
        },
    }

    terrain_data = source.get("terrain")
    terrain_on = bool(terrain_data) and bool((style.get("terrain") or {}).get("enabled", True))
    ground_at = make_terrain_sampler(terrain_data) if terrain_on else (lambda x, y: 0.0)
    if terrain_on and build_terrain_ground(terrain_data, materials["GROUND"], terrain_collection):
        report["terrain"] = {"source": terrain_data.get("source"),
                             "zmin": terrain_data.get("zmin"),
                             "zmax": terrain_data.get("zmax")}
    else:
        terrain_on = False
        ground_at = lambda x, y: 0.0
        bpy.ops.mesh.primitive_plane_add(size=max(4.0, 4.0 * float(source.get("radius", 350.0))),
                                         location=(0.0, 0.0, -0.05))
        ground = bpy.context.active_object
        ground.name = "BLK_Ground"
        for collection in list(ground.users_collection):
            collection.objects.unlink(ground)
        terrain_collection.objects.link(ground)
        ground.data.materials.append(materials["GROUND"])

    stadium_report = stadium_detail.build(
        source, style, stadium_collection, ground_at, make_material)
    if stadium_report:
        report["football_stadium"] = stadium_report
    suppressed_stadium_ids = {
        str(value) for value in (stadium_report or {}).get(
            "suppressed_building_ids", []) if value is not None
    }

    hospital_report = hospital_detail.build(
        source, style, hospital_collection, ground_at, make_material)
    if hospital_report:
        report["hospital"] = hospital_report

    highway_report = highway_detail.build(
        source, style, highway_collection, ground_at, make_material)
    if highway_report:
        report["highway"] = highway_report
    suppressed_road_indices = set(
        (highway_report or {}).get("suppressed_road_indices", []))

    image_target = str((style.get("image_colors") or {}).get("target", "roof")).lower()
    if image_target != "roof":
        raise ValueError("aerial image colors may target roofs only; use verified street-level facade evidence via feature_overrides")
    image_sampler = make_image_color_sampler(source, style, outdir)
    report["image_colored"] = 0

    road_meshes = {}
    arrow_mesh = bmesh.new()
    cycle_mesh = bmesh.new()
    cycle_separator_mesh = bmesh.new()
    cycle_protection_mesh = bmesh.new()
    bus_lane_mesh = bmesh.new()
    parking_mesh = bmesh.new()
    parking_separator_mesh = bmesh.new()
    sidewalk_mesh = bmesh.new()
    sidewalk_kerb_mesh = bmesh.new()
    streetscape_cfg = style.get("streetscape") or {}
    for index, road in enumerate(source.get("roads", [])):
        if index in suppressed_road_indices:
            continue
        if road.get("pedestrian_access_specialized"):
            continue
        path = road.get("path", [])
        if len(path) < 2:
            continue
        material = _road_material(road, materials)
        bm = road_meshes.setdefault(material.name, (material, bmesh.new()))[1]
        width = max(0.5, float(road.get("width", 3.0)))
        z = float(road.get("z", 0.0)) + 0.02 + (index % 200) * 0.0001
        if terrain_on:
            z += ground_at(*centroid(path))
        if add_path(bm, path, width, z):
            report["roads"] += 1
        arrow_count = 0
        if streetscape_cfg.get("enabled", True) and not str(
                road.get("type") or "").startswith("rail:"):
            for placement in road_arrow_placements(road, streetscape_cfg):
                point = placement["point"]
                arrow_z = z + 0.055
                if add_road_arrow(
                        arrow_mesh, point[0], point[1], arrow_z,
                        placement["angle"], placement["lane_width"],
                        placement["directions"],
                        length=streetscape_cfg.get("lane_arrow_length", 2.8),
                        stroke=streetscape_cfg.get("lane_arrow_width", 0.18)):
                    arrow_count += 1
                    if placement["direction_confidence"] == "ambiguous_two_way":
                        report["streetscape"]["ambiguous_lane_arrow_profiles"] += 1
        if arrow_count:
            report["streetscape"]["lane_arrow_roads"] += 1
            report["streetscape"]["lane_arrows"] += arrow_count
        if streetscape_cfg.get("enabled", True):
            for profile in urban_detail.road_cycle_profiles(road, streetscape_cfg):
                side_sign = 1.0 if profile["side"] == "left" else -1.0
                lane_width = profile["width"]
                buffer_width = profile["buffer"]
                center_offset = side_sign * max(
                    lane_width * 0.5,
                    width * 0.5 - lane_width * 0.5 - buffer_width)
                lane_path = offset_polyline(path, center_offset)
                if add_path(cycle_mesh, lane_path, lane_width, z + 0.045, 0.025):
                    report["streetscape"]["cycle_lanes"] += 1
                    report["streetscape"]["cycle_lane_m"] += path_length(lane_path)
                    divider_offset = center_offset - side_sign * (
                        lane_width * 0.5 + buffer_width * 0.5)
                    divider_path = offset_polyline(path, divider_offset)
                    if add_dashed_path(cycle_separator_mesh, divider_path, 0.11,
                                       z + 0.078, dash=2.0, gap=1.8):
                        report["streetscape"]["cycle_lane_separators"] += 1
                    separation = str(profile.get("separation") or "").lower()
                    if any(token in separation for token in
                           ("bollard", "flex_post", "flexible_post")):
                        protection_points = urban_detail.line_sample_points(
                            divider_path, streetscape_cfg.get(
                                "cycle_protection_spacing", 7.0))
                        for protection_point in protection_points:
                            add_cylinder(cycle_protection_mesh,
                                         float(protection_point[0]),
                                         float(protection_point[1]), z + 0.06,
                                         0.075, 0.72, segments=8)
                        report["streetscape"]["cycle_protection_elements"] += len(
                            protection_points)
                    elif any(token in separation for token in ("kerb", "curb")):
                        if add_path(cycle_protection_mesh, divider_path, 0.18,
                                    z + 0.06, 0.12):
                            report["streetscape"]["cycle_protection_elements"] += max(
                                1, len(divider_path) - 1)
            for profile in urban_detail.road_bus_profiles(road):
                if not profile.get("renderable"):
                    report["streetscape"]["bus_lane_metadata_profiles"] += 1
                    continue
                direction_path = list(reversed(path)) \
                    if profile["direction"] == "backward" else path
                lane_count = max(1, len(profile.get("lanes") or []))
                lane_width = width / lane_count
                for lane_index in profile.get("lane_indices", []):
                    center_offset = width * 0.5 - lane_width * (lane_index + 0.5)
                    lane_path = offset_polyline(direction_path, center_offset)
                    if add_path(bus_lane_mesh, lane_path, lane_width * 0.94,
                                z + 0.047, 0.026):
                        report["streetscape"]["bus_lanes"] += 1
                        report["streetscape"]["bus_lane_m"] += path_length(lane_path)
            for profile in urban_detail.road_parking_profiles(road, streetscape_cfg):
                side_sign = 1.0 if profile["side"] == "left" else -1.0
                park_width = float(profile["width"])
                position = profile["position"]
                if position == "lane":
                    center_offset = side_sign * max(park_width * 0.5,
                                                    width * 0.5 - park_width * 0.5)
                elif position == "street_side":
                    center_offset = side_sign * (width * 0.5 + park_width * 0.5)
                else:
                    center_offset = side_sign * width * 0.5
                parking_path = offset_polyline(path, center_offset)
                if add_path(parking_mesh, parking_path, park_width,
                            z + 0.038, 0.018):
                    report["streetscape"]["parking_strips"] += 1
                    report["streetscape"]["parking_strip_m"] += path_length(parking_path)
                    orientation = profile["orientation"]
                    orientations = report["streetscape"]["parking_orientations"]
                    orientations[orientation] = orientations.get(orientation, 0) + 1
                    separator_offset = center_offset - side_sign * park_width * 0.5
                    add_dashed_path(parking_separator_mesh,
                                    offset_polyline(path, separator_offset),
                                    0.09, z + 0.07, dash=4.8, gap=0.8)
            parking_profiles = urban_detail.road_parking_profiles(
                road, streetscape_cfg)
            for profile in urban_detail.road_sidewalk_profiles(
                    road, streetscape_cfg):
                if not profile.get("renderable"):
                    report["streetscape"]["sidewalk_metadata_profiles"] += 1
                    continue
                side_sign = 1.0 if profile["side"] == "left" else -1.0
                sidewalk_width = float(profile["width"])
                outside_parking = 0.0
                for parking_profile in parking_profiles:
                    if parking_profile["side"] != profile["side"]:
                        continue
                    if parking_profile["position"] == "street_side":
                        outside_parking = max(outside_parking,
                                              float(parking_profile["width"]))
                    elif parking_profile["position"] in ("on_kerb", "half_on_kerb"):
                        outside_parking = max(outside_parking,
                                              float(parking_profile["width"]) * 0.5)
                center_offset = side_sign * (
                    width * 0.5 + outside_parking + sidewalk_width * 0.5)
                sidewalk_path = offset_polyline(path, center_offset)
                kerb_value = str(profile.get("kerb") or "").lower()
                sidewalk_height = float(streetscape_cfg.get("sidewalk_height", 0.10))
                if kerb_value == "flush":
                    sidewalk_height = 0.025
                elif kerb_value == "lowered":
                    sidewalk_height = min(sidewalk_height, 0.04)
                if add_path(sidewalk_mesh, sidewalk_path, sidewalk_width,
                            z + 0.04, sidewalk_height):
                    report["streetscape"]["sidewalk_strips"] += 1
                    report["streetscape"]["sidewalk_m"] += path_length(sidewalk_path)
                    if kerb_value and kerb_value not in ("no", "none", "flush"):
                        inner_offset = center_offset - side_sign * sidewalk_width * 0.5
                        if add_path(sidewalk_kerb_mesh,
                                    offset_polyline(path, inner_offset),
                                    0.14, z + 0.04,
                                    max(0.025, sidewalk_height)):
                            report["streetscape"]["sidewalk_kerb_edges"] += 1
    for name, (material, bm) in road_meshes.items():
        finalize("BLK_Roads_" + safe_name(name), bm, material, road_collection)
    finalize("BLK_ExplicitTurnLaneArrows", arrow_mesh,
             materials["CROSSING"], road_surface_collection)
    finalize("BLK_ExplicitCycleLanes", cycle_mesh,
             materials["CYCLEWAY"], road_surface_collection)
    finalize("BLK_CycleLaneSeparators", cycle_separator_mesh,
             materials["CROSSING"], road_surface_collection)
    finalize("BLK_CycleLaneProtection", cycle_protection_mesh,
             materials["SIGN_RED"], road_surface_collection)
    finalize("BLK_ExplicitBusLanes", bus_lane_mesh,
             materials["BUS_LANE"], road_surface_collection)
    finalize("BLK_StreetParkingStrips", parking_mesh,
             materials["PARKING"], road_surface_collection)
    finalize("BLK_StreetParkingSeparators", parking_separator_mesh,
             materials["CROSSING"], road_surface_collection)
    finalize("BLK_ExplicitSidewalkStrips", sidewalk_mesh,
             materials["FOOTWAY"], road_surface_collection)
    finalize("BLK_ExplicitSidewalkKerbEdges", sidewalk_kerb_mesh,
             materials["KERB"], road_surface_collection)
    report["streetscape"]["cycle_lane_m"] = round(
        report["streetscape"]["cycle_lane_m"], 2)
    report["streetscape"]["bus_lane_m"] = round(
        report["streetscape"]["bus_lane_m"], 2)
    report["streetscape"]["parking_strip_m"] = round(
        report["streetscape"]["parking_strip_m"], 2)
    report["streetscape"]["sidewalk_m"] = round(
        report["streetscape"]["sidewalk_m"], 2)

    area_meshes = {}
    residential_area_meshes = {}
    vegetation_cfg = style.get("vegetation_areas") or {}
    for index, area in enumerate(source.get("areas", [])):
        polygon = area.get("polygon", [])
        if len(polygon) < 3:
            continue
        if image_sampler is not None:
            sampled = image_sampler(*centroid(polygon))
            if sampled is not None:
                area["color"] = sampled
                report["image_colored"] += 1
        is_residential = str(area.get("type") or "").lower() == "residential"
        material = (materials["RESIDENTIAL_ZONE"] if is_residential
                    else _area_material(area, materials, style))
        target_meshes = residential_area_meshes if is_residential else area_meshes
        bm = target_meshes.setdefault(material.name, (material, bmesh.new()))[1]
        z = float(area.get("z", 0.0)) + 0.03 + (index % 200) * 0.0001
        if terrain_on:
            z += ground_at(*centroid(polygon))
        add_flat_polygon(bm, polygon, z)
        report["areas"] += 1
        area_m2 = poly_area(polygon)
        area_with_measure = dict(area)
        area_with_measure["area_m2"] = area_m2
        vegetation_profile = urban_detail.vegetation_area_profile(
            area_with_measure, vegetation_cfg)
        remaining = max(0, int(vegetation_cfg.get("max_instances", 500))
                        - report["vegetation_areas"]["instances"])
        area_center = centroid(polygon)
        within_vegetation_radius = math.hypot(
            area_center[0] - focus_center[0],
            area_center[1] - focus_center[1]) <= float(
                vegetation_cfg.get("geometry_radius", 300.0))
        if (vegetation_cfg.get("enabled", True) and vegetation_profile
                and remaining and within_vegetation_radius):
            wanted = min(remaining, vegetation_profile["count"])
            seed_text = str(area.get("osm_id") or area.get("name") or index)
            seed = sum((position + 1) * ord(char)
                       for position, char in enumerate(seed_text))
            placements = urban_detail.deterministic_area_points(
                polygon, wanted, seed=seed)
            detail = add_vegetation_instances(
                placements, vegetation_profile["kind"],
                vegetation_profile["height"], seed_text, materials,
                vegetation_area_collection, ground_at)
            if detail["instances"]:
                vegetation_report = report["vegetation_areas"]
                vegetation_report["zones"] += 1
                vegetation_report["instances"] += detail["instances"]
                vegetation_report["objects"] += detail["objects"]
                vegetation_report["parts"] += detail["parts"]
                vegetation_report["area_m2"] += area_m2
                kind_counts = vegetation_report["by_kind"]
                cover_kind = vegetation_profile["kind"]
                kind_counts[cover_kind] = kind_counts.get(cover_kind, 0) + detail["instances"]
        if is_residential:
            report["residential"]["zone_area_m2"] += poly_area(polygon)
    for name, (material, bm) in area_meshes.items():
        finalize("BLK_Areas_" + safe_name(name), bm, material, area_collection)
    for name, (material, bm) in residential_area_meshes.items():
        if finalize("BLK_ResidentialZones_" + safe_name(name), bm, material,
                    residential_collection):
            report["residential"]["zone_meshes"] += 1
    report["residential"]["zone_area_m2"] = round(
        report["residential"]["zone_area_m2"], 2)
    report["vegetation_areas"]["area_m2"] = round(
        report["vegetation_areas"]["area_m2"], 2)

    merged = {}
    editable_radius = float(style.get("editable_radius", 200.0))
    merge_distant = bool(style.get("merge_distant_buildings", True))
    appearance = report["building_appearance"]
    for building in source.get("buildings", []):
        if str(building.get("osm_id")) in suppressed_stadium_ids:
            continue
        footprint = building.get("footprint", [])
        if len(footprint) < 3:
            continue
        if image_sampler is not None:
            sampled = image_sampler(*centroid(footprint))
            if sampled is not None and not str(building.get("roof_color_source", "")).startswith("osm:"):
                # A north-up aerial observes the roof, not the facade.  Keeping
                # the channels separate prevents a roof pixel from repainting
                # every wall of the building.
                building["roof_color"] = sampled
                building["roof_color_source"] = "imagery_aerial"
                building["roof_color_confidence"] = 0.65
                report["image_colored"] += 1
        color_source = str(building.get("color_source") or "legacy_prior")
        roof_source = str(building.get("roof_color_source") or "derived_from_facade")
        appearance["color_sources"][color_source] = appearance["color_sources"].get(color_source, 0) + 1
        appearance["roof_color_sources"][roof_source] = appearance["roof_color_sources"].get(roof_source, 0) + 1
        facade_confidence = float(building.get("color_confidence", 0.25))
        roof_confidence = float(building.get(
            "roof_color_confidence", facade_confidence * 0.60))
        appearance["_facade_confidence_total"] += facade_confidence
        appearance["_roof_confidence_total"] += roof_confidence
        override = feature_override(building, style)
        local_base = float(override.get("min_height", building.get("min_height", 0.0)))
        raw_height = float(override.get("height", building.get("height", 9.0)))
        if not override.get("height") and not is_roof_only(building):
            raw_height = varied_building_height(building, style, raw_height)
        local_height = max(local_base + 0.2, raw_height)
        center = centroid(footprint)
        lift = ground_at(center[0], center[1]) if terrain_on else 0.0
        base, height = local_base + lift, local_height + lift
        distance = math.hypot(center[0] - focus_center[0], center[1] - focus_center[1])
        identity = building.get("name") or building.get("osm_id") or report["buildings_individual"]

        if is_roof_only(building):
            cover_feature = dict(building)
            cover_feature.update({"min_height": local_base, "height": local_height})
            detail = add_covered_structure(
                footprint, cover_feature, identity, style,
                roof_material_for(building, override, style, materials),
                materials["METAL"], covered_collection, ground_z=lift)
            if detail["objects"]:
                report["buildings_individual"] += 1
                report["covered_structures"]["count"] += 1
                for key in ("objects", "columns", "edge_beams"):
                    report["covered_structures"][key] += detail[key]
            continue

        stadium_cfg = style.get("stadium_interior") or {}
        if stadium_cfg.get("enabled", True) and is_stadium(building):
            seat_rgb = stadium_cfg.get("seat_color") or override.get("color")
            seat_material = (material_for_color(seat_rgb, style) if seat_rgb
                             else materials.get("FEATURE") or materials["AREA"])
            wall_rgb = stadium_cfg.get("wall_color") or override.get("color")
            wall_material = (material_for_color(wall_rgb, style) if wall_rgb
                             else materials.get("FEATURE") or materials["AREA"])
            if add_stadium_bowl(footprint, base, height, style, materials,
                                building_collection, seat_material, wall_material):
                report["buildings_individual"] += 1
                continue
        material = (material_for_color(override["color"], style)
                    if override.get("color") else _building_material(building, materials, style))
        individual = (not merge_distant or distance <= editable_radius
                      or building.get("name") or override.get("individual"))
        if individual:
            facade_spec = facade_parameters(building, style, height=height, base=base)
            facade_shader = False
            wall_rgb = (override.get("color")
                        or (building.get("color") if style.get("color_mode") == "scene" else None)
                        or style["palette"]["BLD_A"])
            if (style.get("facade") or {}).get("enabled", True):
                material = make_facade_material(wall_rgb, style, facade_spec)
                facade_shader = True
                appearance["facade_shader_buildings"] += 1
            shape = str(building.get("roof_shape") or "").strip().lower().replace(" ", "_")
            rs_cfg = style.get("roof_shapes") or {}
            if rs_cfg.get("enabled", True) and shape in PITCHED_ROOF_SHAPES and (height - base) > 3.0:
                roof_h = roof_height_for(building, style, base, height)
                wall_top = max(base + 0.2, height - roof_h)
                bm = bmesh.new()
                if add_prism_checked(bm, footprint, base, wall_top):
                    finalize("Bld_" + safe_name(identity), bm, material, building_collection)
                    report["buildings_individual"] += 1
                    roof = bmesh.new()
                    if add_pitched_roof(
                            roof, footprint, wall_top, height - wall_top, shape,
                            building.get("roof_orientation"),
                            building.get("roof_direction")):
                        finalize("Roof_" + safe_name(identity), roof,
                                 roof_material_for(building, override, style, materials),
                                 building_collection)
                    else:
                        roof.free()
                    geometry_radius = float((style.get("facade") or {}).get(
                        "geometry_radius", 95.0))
                    if (style.get("architectural_detail") or {}).get(
                            "visible_interiors", True):
                        geometry_radius = max(
                            geometry_radius,
                            float((style.get("architectural_detail") or {}).get(
                                "interior_radius", 115.0)))
                    if facade_shader and distance <= geometry_radius:
                        facade_detail = add_facade_panels(
                            footprint, base, wall_top, identity, style,
                            facade_spec, building_collection)
                        record_facade_detail(appearance, facade_detail, facade_spec)
                    construction_radius = float((style.get("construction_detail") or {}).get(
                        "geometry_radius", 125.0))
                    if distance <= construction_radius:
                        detail = add_construction_details(
                            footprint, base, wall_top, identity, building, style,
                            facade_spec, wall_rgb, building_collection)
                        for key, source_key in (("detail_objects", "objects"),
                                                ("bands", "bands"),
                                                ("entrances", "entrances")):
                            report["construction_detail"][key] += detail[source_key]
                    interior_cfg = style.get("architectural_detail") or {}
                    if (interior_cfg.get("editable_interior_layouts", True)
                            and distance <= float(interior_cfg.get(
                                "interior_radius", 115.0))):
                        record_interior_detail(
                            report["building_interiors"],
                            add_editable_interior_layout(
                                footprint, base, wall_top, identity, building,
                                style, interior_collection))
                    continue
                bm.free()
            roof_cfg = style.get("roof_detail") or {}
            band = float(roof_cfg.get("band", 1.1)) if roof_cfg.get("enabled") else 0.0
            body_top = height - band if band > 0.0 and (height - base) > band + 1.0 else height
            bm = bmesh.new()
            if add_prism_checked(bm, footprint, base, body_top):
                identity = building.get("name") or building.get("osm_id") or report["buildings_individual"]
                finalize("Bld_" + safe_name(identity), bm, material, building_collection)
                report["buildings_individual"] += 1
                if body_top < height:
                    cap = bmesh.new()
                    if add_prism_checked(cap, footprint, body_top, height):
                        finalize("Roof_" + safe_name(identity),
                                 cap, roof_material_for(building, override, style, materials),
                                 building_collection)
                    else:
                        cap.free()
                geometry_radius = float((style.get("facade") or {}).get(
                    "geometry_radius", 95.0))
                if (style.get("architectural_detail") or {}).get(
                        "visible_interiors", True):
                    geometry_radius = max(
                        geometry_radius,
                        float((style.get("architectural_detail") or {}).get(
                            "interior_radius", 115.0)))
                if facade_shader and distance <= geometry_radius:
                    facade_detail = add_facade_panels(
                        footprint, base, body_top, identity, style,
                        facade_spec, building_collection)
                    record_facade_detail(appearance, facade_detail, facade_spec)
                construction_radius = float((style.get("construction_detail") or {}).get(
                    "geometry_radius", 125.0))
                if distance <= construction_radius:
                    detail = add_construction_details(
                        footprint, base, body_top, identity, building, style,
                        facade_spec, wall_rgb, building_collection)
                    for key, source_key in (("detail_objects", "objects"),
                                            ("bands", "bands"),
                                            ("entrances", "entrances")):
                        report["construction_detail"][key] += detail[source_key]
                interior_cfg = style.get("architectural_detail") or {}
                if (interior_cfg.get("editable_interior_layouts", True)
                        and distance <= float(interior_cfg.get(
                            "interior_radius", 115.0))):
                    record_interior_detail(
                        report["building_interiors"],
                        add_editable_interior_layout(
                            footprint, base, body_top, identity, building,
                            style, interior_collection))
            else:
                bm.free()
        else:
            bm = merged.setdefault(material.name, (material, bmesh.new()))[1]
            if add_prism_checked(bm, footprint, base, height):
                report["buildings_merged"] += 1
    for name, (material, bm) in merged.items():
        finalize("BLK_Buildings_" + safe_name(name), bm, material, building_collection)

    appearance_count = sum(appearance["color_sources"].values())
    appearance["facade_color_confidence_mean"] = round(
        appearance.pop("_facade_confidence_total") / max(1, appearance_count), 3)
    appearance["roof_color_confidence_mean"] = round(
        appearance.pop("_roof_confidence_total") / max(1, appearance_count), 3)
    appearance["facade_variants"] = sorted(appearance["facade_variants"])
    report["architectural_detail"].update({
        "profile_count": len(appearance["facade_profiles"]),
        "variant_count": len(appearance["facade_variants"]),
        "visible_interior_bays": appearance["visible_interior_bays"],
        "symmetric_window_pairs": appearance["symmetric_window_pairs"],
        "balconies": appearance["balconies"],
        "facade_accent_parts": appearance["facade_accent_parts"],
        "source": "osm_semantics+geometry_driven_procedural_detail",
    })

    for index, feature in enumerate(source.get("special_features", [])):
        override = feature_override(feature, style)
        identity = feature.get("name") or feature.get("osm_id") or feature.get("id") or index
        effective = dict(feature)
        for key in ("height", "min_height", "width", "depth", "direction", "z",
                    "panel_width", "panel_height", "panel_size", "text", "support"):
            if key in override:
                effective[key] = override[key]
        family = str(feature.get("family") or "").lower()
        kind = str(feature.get("kind") or "").lower()
        wants_wall = (str(effective.get("support") or "").lower() in
                      ("wall", "building", "facade", "façade")
                      or kind in ("mural", "plaque"))
        if (family == "public_art" or kind in ("defibrillator", "atm")) \
                and wants_wall and effective.get("geometry") == "point":
            host = urban_detail.resolve_wall_host(
                effective, source.get("buildings", []),
                max_distance=float((style.get("urban_objects") or {}).get(
                    "wall_host_max_distance", 6.0)))
            if host:
                effective.update(host)
                report["urban_detail"]["wall_hosted"] += 1
            else:
                report["urban_detail"]["wall_host_unresolved"] += 1
        if family == "road_surface" and kind in (
                "pedestrian_crossing", "traffic_island", "painted_island",
                "stop_line", "raised_crossing", "speed_table") \
                and effective.get("geometry") == "point":
            host = urban_detail.resolve_road_host(
                effective, source.get("roads", []),
                max_distance=float((style.get("urban_objects") or {}).get(
                    "road_host_max_distance", 15.0)))
            if host:
                effective.update(host)
                report["urban_detail"]["road_hosted"] += 1
            else:
                report["urban_detail"]["road_host_unresolved"] += 1
        points = feature_points(effective)
        feature_center = centroid(points)
        ground_z = ground_at(*feature_center) if terrain_on and points else 0.0
        feature_height = float(effective.get("height") or 0.0)

        if family == "road_surface" and kind in ("stop_line", "lane_divider") \
                and effective.get("geometry") == "line":
            path = effective.get("path", [])
            marking_mesh = bmesh.new()
            width = max(0.03, float(effective.get("width", 0.42 if kind == "stop_line" else 0.14)))
            stroke = str(effective.get("stroke") or "solid").lower()
            if stroke in ("dashed", "broken"):
                made = add_dashed_path(marking_mesh, path, width,
                                       ground_z + 0.128, dash=2.0, gap=2.0)
            else:
                made = add_path(marking_mesh, path, width,
                                ground_z + 0.128, 0.025)
            obj = finalize(("StopLine_" if kind == "stop_line" else "LaneDivider_")
                           + safe_name(identity), marking_mesh,
                           materials["CROSSING"], road_surface_collection)
            if made and obj:
                report["streetscape"]["stop_lines" if kind == "stop_line"
                                      else "lane_dividers"] += 1
                report["features"].append({
                    "id": str(feature.get("osm_id", identity)), "name": obj.name,
                    "kind": kind, "family": family, "height": 0.025,
                    "provenance": effective.get("detail_source"),
                })
            continue

        if family == "road_surface" and kind == "kerb" \
                and effective.get("geometry") == "line":
            path = effective.get("path", [])
            height = max(0.018, float(effective.get("height", 0.12)))
            width = max(0.05, float(effective.get("width", 0.22)))
            kerb_mesh = bmesh.new()
            made = add_path(kerb_mesh, path, width, ground_z + 0.065, height)
            obj = finalize("Kerb_" + safe_name(identity), kerb_mesh,
                           materials["KERB"], road_surface_collection)
            if made and obj:
                segments = max(0, len(path) - 1)
                report["streetscape"]["kerb_segments"] += segments
                report["features"].append({
                    "id": str(feature.get("osm_id", identity)), "name": obj.name,
                    "kind": kind, "family": family, "height": height,
                })
            continue

        if family == "road_surface" and kind == "traffic_island" \
                and effective.get("geometry") == "surface":
            island_mesh = bmesh.new()
            island_top = bmesh.new()
            polygon = effective.get("polygon", [])
            height = max(0.04, float(effective.get("height", 0.18)))
            made = add_prism_checked(
                island_mesh, polygon, ground_z + 0.075,
                ground_z + 0.075 + height)
            obj = finalize("TrafficIsland_" + safe_name(identity), island_mesh,
                           materials["KERB"], road_surface_collection)
            center_x, center_y = centroid(polygon)
            inset = [[center_x + (float(point[0]) - center_x) * 0.78,
                      center_y + (float(point[1]) - center_y) * 0.62]
                     for point in polygon]
            add_flat_polygon(island_top, inset, ground_z + 0.075 + height + 0.012)
            top_obj = finalize("TrafficIslandTop_" + safe_name(identity), island_top,
                               materials["GREEN"], road_surface_collection)
            if made and (obj or top_obj):
                report["streetscape"]["traffic_islands"] += 1
                report["features"].append({
                    "id": str(feature.get("osm_id", identity)),
                    "name": (obj or top_obj).name,
                    "kind": kind, "family": family, "height": height,
                })
            continue

        if family == "vegetation" and kind == "tree_row" \
                and effective.get("geometry") == "line":
            points = urban_detail.line_sample_points(
                effective.get("path", []), effective.get("tree_spacing", 7.0))
            vegetation_cfg = style.get("vegetation_areas") or {}
            remaining = max(0, int(vegetation_cfg.get("max_instances", 500))
                            - report["vegetation_areas"]["instances"])
            points = points[:remaining]
            detail = add_vegetation_instances(
                points, "tree_row", max(1.0, feature_height or 7.5), identity,
                materials, vegetation_area_collection, ground_at)
            if detail["instances"]:
                report["streetscape"]["tree_rows"] += 1
                vegetation_report = report["vegetation_areas"]
                vegetation_report["instances"] += detail["instances"]
                vegetation_report["objects"] += detail["objects"]
                vegetation_report["parts"] += detail["parts"]
                by_kind = vegetation_report["by_kind"]
                by_kind["tree_row"] = by_kind.get("tree_row", 0) + detail["instances"]
                report["features"].append({
                    "id": str(feature.get("osm_id", identity)),
                    "name": "TreeRow_" + safe_name(identity), "kind": kind,
                    "family": family, "height": feature_height,
                })
            continue

        if family == "utility_network" and kind == "overhead_power_line" \
                and effective.get("geometry") == "line":
            path = effective.get("path", [])
            profile = urban_detail.utility_line_profile(effective)
            wires = bmesh.new()
            if len(path) >= 2:
                dx = float(path[-1][0]) - float(path[0][0])
                dy = float(path[-1][1]) - float(path[0][1])
                length = math.hypot(dx, dy) or 1.0
                nx, ny = -dy / length, dx / length
                for conductor in range(profile["conductors"]):
                    offset = (conductor - (profile["conductors"] - 1) / 2.0) \
                        * profile["spacing"]
                    conductor_path = [[float(point[0]) + nx * offset,
                                       float(point[1]) + ny * offset]
                                      for point in path]
                    add_path(
                        wires, conductor_path,
                        max(0.015, float(streetscape_cfg.get(
                            "utility_wire_width", 0.035))),
                        ground_z + profile["height"], 0.025)
            obj = finalize("UtilityLine_" + safe_name(identity), wires,
                           materials["UTILITY_WIRE"], utility_collection)
            if obj:
                report["streetscape"]["utility_lines"] += 1
                report["streetscape"]["utility_conductors"] += profile["conductors"]
                report["features"].append({
                    "id": str(feature.get("osm_id", identity)), "name": obj.name,
                    "kind": kind, "family": family,
                    "height": profile["height"],
                })
            continue

        if family == "pedestrian_access" and effective.get("geometry") == "line":
            profile = urban_detail.pedestrian_access_profile(effective, streetscape_cfg)
            path = effective.get("path", [])
            access_mesh, detail_mesh, rail_mesh = bmesh.new(), bmesh.new(), bmesh.new()
            length, width, rise = profile["length"], profile["width"], profile["rise"]
            base_z = ground_z + 0.04
            made = False
            kind = profile["kind"]
            if len(path) >= 2 and length > 0.01:
                if kind in ("steps", "escalator"):
                    count = profile["step_count"]
                    run = length / max(1, count)
                    for step in range(count):
                        d = (step + 0.5) * run
                        px, py, tx, ty = point_tangent_at_distance(path, d)
                        top = base_z + profile["direction_sign"] * rise * (step + 1) / count
                        add_box(access_mesh, px, py, top - profile["step_height"] * 0.5,
                                run * 1.12, width, profile["step_height"], math.atan2(ty, tx))
                    made = True
                else:
                    cumulative = 0.0
                    for a, b in zip(path, path[1:]):
                        ax, ay = float(a[0]), float(a[1]); bx, by = float(b[0]), float(b[1])
                        seg = math.hypot(bx - ax, by - ay) or 1.0
                        z0 = base_z + profile["direction_sign"] * rise * (cumulative / max(length, 1e-6))
                        z1 = z0 + profile["direction_sign"] * rise * (seg / max(length, 1e-6))
                        made |= add_beam_between(access_mesh, (ax, ay, z0), (bx, by, z1), width, 0.12)
                        cumulative += seg
                    # A simple continuous strip is more robust than per-segment z reset.
                    if made and len(path) == 2:
                        access_mesh.clear()
                        ax, ay = map(float, path[0][:2]); bx, by = map(float, path[-1][:2])
                        add_beam_between(access_mesh, (ax, ay, base_z),
                                         (bx, by, base_z + profile["direction_sign"] * rise), width, 0.12)
                if kind in ("escalator", "moving_walkway", "inclined_elevator"):
                    for side in (-1, 1):
                        pts = []
                        for i in range(2):
                            px, py, tx, ty = point_tangent_at_distance(path, length * i)
                            nx, ny = -ty, tx
                            z = base_z + profile["direction_sign"] * rise * i + 0.9
                            pts.append((px + nx * side * (width * 0.5 + 0.10),
                                        py + ny * side * (width * 0.5 + 0.10), z))
                        add_beam_between(rail_mesh, pts[0], pts[1], 0.07, 0.07)
                    made = True
                for side in profile["handrail_sides"]:
                    if side == "center":
                        side_signs = (0,)
                    else:
                        side_signs = (1 if side == "left" else -1,)
                    for side_sign in side_signs:
                        pts = []
                        for i in range(2):
                            px, py, tx, ty = point_tangent_at_distance(path, length * i)
                            nx, ny = -ty, tx
                            z = base_z + profile["direction_sign"] * rise * i + 0.95
                            pts.append((px + nx * side_sign * (width * 0.5 + 0.14),
                                        py + ny * side_sign * (width * 0.5 + 0.14), z))
                        add_beam_between(rail_mesh, pts[0], pts[1], 0.055, 0.055)
                        report["pedestrian_access"]["handrails"] += 1
                        report["pedestrian_access"]["handrail_m"] += length
            obj = finalize("PedestrianAccess_" + safe_name(identity), access_mesh,
                           materials["FOOTWAY"], pedestrian_access_collection)
            detail_obj = finalize("PedestrianAccessDetail_" + safe_name(identity), detail_mesh,
                                  materials["METAL"], pedestrian_access_collection)
            rail_obj = finalize("PedestrianAccessRails_" + safe_name(identity), rail_mesh,
                                materials["METAL"], pedestrian_access_collection)
            if made and (obj or detail_obj or rail_obj):
                access_report = report["pedestrian_access"]
                if kind == "steps":
                    access_report["steps"] += 1; access_report["step_m"] += length
                    access_report["step_count"] += profile["step_count"]
                elif kind == "escalator":
                    access_report["escalators"] += 1
                elif kind == "moving_walkway":
                    access_report["moving_walkways"] += 1
                elif kind == "inclined_elevator":
                    access_report["inclined_elevators"] += 1
                else:
                    access_report["ramps"] += 1; access_report["ramp_m"] += length
                if profile["handrail_unspecified"]:
                    access_report["unspecified_handrails"] += 1
                access_report["max_rise_m"] = max(access_report["max_rise_m"], rise)
                report["features"].append({"id": str(feature.get("osm_id", identity)),
                    "name": (obj or rail_obj).name, "kind": kind,
                    "family": family, "length": length, "rise": rise,
                    "provenance": profile["provenance"]})
            continue

        if family == "utility_network" and kind == "communication_line" \
                and effective.get("geometry") == "line":
            profile = urban_detail.communication_line_profile(effective)
            if not profile["visible"]:
                report["utility_networks"]["metadata_only_lines"] += 1
                report["features"].append({
                    "id": str(feature.get("osm_id", identity)),
                    "name": "CommunicationLineMetadata_" + safe_name(identity),
                    "kind": kind, "family": family, "rendered": False,
                    "location": profile["location"],
                    "provenance": profile["provenance"],
                })
                continue
            path = effective.get("path", [])
            cables = bmesh.new()
            if len(path) >= 2:
                dx = float(path[-1][0]) - float(path[0][0])
                dy = float(path[-1][1]) - float(path[0][1])
                length = math.hypot(dx, dy) or 1.0
                nx, ny = -dy / length, dx / length
                for conductor in range(profile["conductors"]):
                    offset = (conductor - (profile["conductors"] - 1) / 2.0) \
                        * profile["spacing"]
                    conductor_path = [[float(point[0]) + nx * offset,
                                       float(point[1]) + ny * offset]
                                      for point in path]
                    add_path(cables, conductor_path,
                             max(0.012, float(streetscape_cfg.get(
                                 "telecom_wire_width", 0.025))),
                             ground_z + profile["height"], 0.018)
            obj = finalize("CommunicationLine_" + safe_name(identity), cables,
                           materials["TELECOM_WIRE"], utility_collection)
            if obj:
                report["utility_networks"]["communication_lines"] += 1
                report["utility_networks"]["communication_conductors"] += profile["conductors"]
                report["features"].append({
                    "id": str(feature.get("osm_id", identity)), "name": obj.name,
                    "kind": kind, "family": family, "height": profile["height"],
                    "location": profile["location"],
                    "provenance": profile["provenance"],
                })
            continue

        if family == "fluid_network" and kind == "pipeline" \
                and effective.get("geometry") == "line":
            profile = urban_detail.fluid_line_profile(effective)
            if not profile["visible"]:
                report["fluid_networks"]["metadata_only_lines"] += 1
                report["features"].append({
                    "id": str(feature.get("osm_id", identity)),
                    "name": "PipelineMetadata_" + safe_name(identity),
                    "kind": kind, "family": family, "rendered": False,
                    "location": profile["location"],
                    "substance": profile["substance"],
                    "provenance": profile["provenance"],
                })
                continue
            path = effective.get("path", [])
            pipe_mesh, support_mesh = bmesh.new(), bmesh.new()
            diameter = profile["diameter"]
            pipe_z = ground_z + profile["height"]
            made = add_path(pipe_mesh, path, diameter, pipe_z, diameter)
            supports = 0
            if profile["location"] == "overhead":
                for support_point in urban_detail.line_sample_points(path, 11.0):
                    support_height = max(0.25, profile["height"] - diameter * 0.5)
                    add_cylinder(support_mesh, float(support_point[0]),
                                 float(support_point[1]), ground_z,
                                 max(0.06, diameter * 0.18), support_height,
                                 segments=8)
                    add_box(support_mesh, float(support_point[0]),
                            float(support_point[1]), ground_z + support_height,
                            diameter * 2.1, max(0.10, diameter * 0.28),
                            max(0.10, diameter * 0.28))
                    supports += 1
            substance = profile["substance"]
            material_key = ("PIPE_WATER" if substance in ("water", "sewage")
                            else "PIPE_GAS" if "gas" in substance
                            else "PIPE_OIL" if substance in ("oil", "petroleum")
                            else "PIPE_GENERIC")
            pipe_obj = finalize("Pipeline_" + safe_name(identity), pipe_mesh,
                                materials[material_key], fluid_collection)
            support_obj = finalize("PipelineSupports_" + safe_name(identity),
                                   support_mesh, materials["METAL"], fluid_collection)
            if made and (pipe_obj or support_obj):
                length_m = path_length(path)
                fluid_report = report["fluid_networks"]
                fluid_report["visible_lines"] += 1
                fluid_report["visible_length_m"] += length_m
                fluid_report["supports"] += supports
                by_substance = fluid_report["by_substance"]
                by_substance[substance] = by_substance.get(substance, 0) + 1
                report["features"].append({
                    "id": str(feature.get("osm_id", identity)),
                    "name": (pipe_obj or support_obj).name,
                    "kind": kind, "family": family,
                    "height": profile["height"], "diameter": diameter,
                    "location": profile["location"], "substance": substance,
                    "provenance": profile["provenance"],
                })
            continue

        if family == "utility_network" and kind == "power_substation" \
                and effective.get("geometry") == "surface":
            polygon = effective.get("polygon", [])
            base_mesh, fence_mesh, equipment_mesh = bmesh.new(), bmesh.new(), bmesh.new()
            made = add_prism_checked(base_mesh, polygon, ground_z + 0.04,
                                     ground_z + 0.16)
            ring = list(polygon)
            if ring and ring[0] != ring[-1]:
                ring.append(ring[0])
            for rail_height in (0.48, 1.42):
                add_path(fence_mesh, ring, 0.065,
                         ground_z + 0.16 + rail_height, 0.065)
            fence_points = urban_detail.line_sample_points(ring, 3.2)
            for fence_point in fence_points:
                add_cylinder(fence_mesh, float(fence_point[0]),
                             float(fence_point[1]), ground_z + 0.16,
                             0.055, 1.72, segments=6)
            location = str(effective.get("location") or "outdoor").lower()
            equipment_count = 0
            if made and location not in ("indoor", "underground"):
                xs = [float(point[0]) for point in polygon]
                ys = [float(point[1]) for point in polygon]
                min_x, max_x, min_y, max_y = min(xs), max(xs), min(ys), max(ys)
                span_x, span_y = max_x - min_x, max_y - min_y
                cx, cy = (min_x + max_x) * 0.5, (min_y + max_y) * 0.5
                equipment_count = 2 if max(span_x, span_y) >= 9.0 else 1
                for index in range(equipment_count):
                    offset = (index - (equipment_count - 1) / 2.0) * min(3.2, max(span_x, span_y) * 0.22)
                    ex = cx + (offset if span_x >= span_y else 0.0)
                    ey = cy + (offset if span_y > span_x else 0.0)
                    add_box(equipment_mesh, ex, ey, ground_z + 1.05,
                            min(2.4, max(1.1, span_x * 0.18)),
                            min(1.7, max(0.8, span_y * 0.18)), 1.8)
                    unit_w = min(2.4, max(1.1, span_x * 0.18))
                    unit_d = min(1.7, max(0.8, span_y * 0.18))
                    for bushing in (-0.28, 0.0, 0.28):
                        add_cylinder(equipment_mesh, ex + bushing * unit_w, ey,
                                     ground_z + 1.95, 0.075, 0.42, segments=8)
                    for fin in (-0.30, -0.10, 0.10, 0.30):
                        add_box(equipment_mesh, ex, ey + unit_d * 0.53,
                                ground_z + 1.02 + fin * 0.15,
                                unit_w * 0.72, 0.055, 0.13)
            base_obj = finalize("SubstationBase_" + safe_name(identity), base_mesh,
                                materials["POWER_EQUIPMENT"], utility_collection)
            fence_obj = finalize("SubstationFence_" + safe_name(identity), fence_mesh,
                                 materials["METAL"], utility_collection)
            equipment_obj = finalize("SubstationEquipment_" + safe_name(identity),
                                     equipment_mesh, materials["POWER_EQUIPMENT"],
                                     utility_collection)
            if base_obj or fence_obj or equipment_obj:
                report["utility_networks"]["substations"] += 1
                report["utility_networks"]["substation_equipment_proxies"] += equipment_count
                report["features"].append({
                    "id": str(feature.get("osm_id", identity)),
                    "name": (base_obj or fence_obj or equipment_obj).name,
                    "kind": kind, "family": family,
                    "location": location,
                    "equipment_proxies": equipment_count,
                    "provenance": "mapped_outline+bounded_semantic_proxy",
                })
            continue

        if family == "residential_boundary" and effective.get("geometry") == "line":
            path = effective.get("path", [])
            height = max(0.15, float(effective.get("height", 1.4)))
            width = max(0.04, float(effective.get("width", 0.10)))
            body, posts = bmesh.new(), bmesh.new()
            kind = str(effective.get("kind") or "fence").lower()
            if kind == "fence":
                for level in (0.32, 0.72):
                    add_path(body, path, width, ground_z + height * level,
                             max(0.05, width * 0.85))
                for point in path:
                    add_cylinder(posts, float(point[0]), float(point[1]), ground_z,
                                 max(0.035, width * 0.65), height, segments=6)
                body_material, post_material = materials["METAL"], materials["METAL"]
            else:
                add_path(body, path, width, ground_z, height)
                body_material = materials["FOLIAGE"] if kind == "hedge" else materials["ART_STONE"]
                post_material = body_material
            first = finalize("ResidentialBoundary_" + safe_name(identity), body,
                             body_material, residential_boundary_collection)
            second = finalize("ResidentialBoundaryPosts_" + safe_name(identity), posts,
                              post_material, residential_boundary_collection)
            if first or second:
                report["residential"]["mapped_boundary_segments"] += max(0, len(path) - 1)
                report["features"].append({
                    "id": str(feature.get("osm_id", identity)),
                    "name": (first or second).name, "kind": kind,
                    "family": family, "height": height,
                })
            continue

        if family == "covered_structure" and effective.get("geometry") == "surface":
            detail = add_covered_structure(
                effective.get("polygon", []), effective, identity, style,
                material_for_color(override["color"], style)
                if override.get("color") else materials["FEATURE"],
                materials["METAL"], covered_collection, ground_z=ground_z)
            if detail["objects"]:
                report["covered_structures"]["count"] += 1
                for key in ("objects", "columns", "edge_beams"):
                    report["covered_structures"][key] += detail[key]
                report["features"].append({
                    "id": str(feature.get("id", feature.get("osm_id", identity))),
                    "name": "Cover_" + safe_name(identity), "kind": feature.get("kind"),
                    "family": family, "height": feature_height,
                })
            continue

        if family in ("street_furniture", "vegetation", "covered_structure",
                      "signage", "transit", "public_art", "recreation",
                      "road_surface", "utility_network", "fluid_network",
                      "pedestrian_access") \
                and effective.get("geometry") == "point":
            urban_cfg = style.get("urban_objects") or {}
            object_distance = math.hypot(feature_center[0] - focus_center[0],
                                         feature_center[1] - focus_center[1])
            within_radius = object_distance <= float(urban_cfg.get("geometry_radius", 220.0))
            below_cap = report["urban_objects"]["count"] < int(urban_cfg.get("max_objects", 900))
            if within_radius and below_cap:
                target_collection = {
                    "signage": signage_collection,
                    "transit": transit_collection,
                    "road_surface": road_surface_collection,
                    "utility_network": utility_collection,
                    "fluid_network": fluid_collection,
                    "pedestrian_access": pedestrian_access_collection,
                    "public_art": art_collection,
                    "recreation": recreation_collection,
                }.get(family, urban_collection)
                detail = add_urban_object(effective, identity, style, materials,
                                          target_collection, ground_z=ground_z)
                if detail["objects"]:
                    report["urban_objects"]["count"] += 1
                    report["urban_objects"]["objects"] += detail["objects"]
                    report["urban_objects"]["parts"] += detail["parts"]
                    kind = str(feature.get("kind") or "object")
                    by_kind = report["urban_objects"]["by_kind"]
                    by_kind[kind] = by_kind.get(kind, 0) + 1
                    urban_report = report["urban_detail"]
                    urban_report["count"] += 1
                    urban_report["objects"] += detail["objects"]
                    urban_report["parts"] += detail["parts"]
                    urban_report["text_objects"] += detail.get("text_objects", 0)
                    if detail.get("direction_source") == "explicit":
                        urban_report["explicit_directions"] += 1
                    if str(detail.get("dimension_source", "")).startswith("explicit"):
                        urban_report["explicit_dimensions"] += 1
                    by_family = urban_report["by_family"]
                    by_family[family] = by_family.get(family, 0) + 1
                    detail_by_kind = urban_report["by_kind"]
                    detail_by_kind[kind] = detail_by_kind.get(kind, 0) + 1
                    if detail.get("sign_shape"):
                        by_shape = urban_report["by_sign_shape"]
                        shape = str(detail["sign_shape"])
                        by_shape[shape] = by_shape.get(shape, 0) + 1
                    if family == "covered_structure":
                        report["covered_structures"]["count"] += 1
                    if kind in ("traffic_island", "painted_island"):
                        report["streetscape"]["traffic_islands"] += 1
                    if kind == "stop_line":
                        report["streetscape"]["stop_lines"] += 1
                    elif kind == "manhole_cover":
                        report["streetscape"]["manhole_covers"] += 1
                    elif kind == "drainage_inlet":
                        report["streetscape"]["drainage_inlets"] += 1
                    elif kind == "curb_ramp":
                        report["streetscape"]["curb_ramps"] += 1
                        report["streetscape"]["curb_ramp_max_height"] = max(
                            report["streetscape"]["curb_ramp_max_height"],
                            float(feature_height))
                    elif kind == "raised_crossing":
                        report["streetscape"]["raised_crossings"] += 1
                        report["streetscape"]["raised_crossing_max_height"] = max(
                            report["streetscape"]["raised_crossing_max_height"],
                            float(feature_height))
                    elif kind == "speed_table":
                        report["streetscape"]["speed_tables"] += 1
                    elif kind == "pedestrian_elevator":
                        report["pedestrian_access"]["elevators"] += 1
                    utility_report = report["utility_networks"]
                    if kind == "power_transformer":
                        utility_report["transformers"] += 1
                    elif kind == "power_substation_kiosk":
                        utility_report["substations"] += 1
                    elif kind == "telecom_pole":
                        utility_report["telecom_poles"] += 1
                    elif kind in ("telecom_cabinet", "telecom_distribution_point"):
                        utility_report["telecom_cabinets"] += 1
                    fluid_report = report["fluid_networks"]
                    if kind == "pumping_station":
                        fluid_report["pumping_stations"] += 1
                    elif kind == "pipeline_valve":
                        fluid_report["valves"] += 1
                    elif kind == "pipeline_measurement":
                        fluid_report["measurement_points"] += 1
                    elif kind == "fluid_cabinet":
                        fluid_report["fluid_cabinets"] += 1
                    report["features"].append({
                        "id": str(feature.get("id", feature.get("osm_id", identity))),
                        "name": "Object_" + safe_name(identity), "kind": feature.get("kind"),
                        "family": family, "height": feature_height,
                    })
            continue

        material = (material_for_color(override["color"], style)
                    if override.get("color") else materials["FEATURE"])
        geometry = feature.get("geometry")
        bm = bmesh.new()
        made = False
        if geometry == "surface" and feature.get("polygon"):
            add_flat_polygon(bm, feature["polygon"],
                             ground_z + float(effective.get("z", 0.06)))
            made = True
        elif geometry == "line" and feature.get("path"):
            width = max(0.5, float(effective.get("width", 3.0)))
            made = add_path(bm, feature["path"], width,
                            ground_z + float(effective.get("z", 0.06)))
        elif feature.get("point"):
            point = feature["point"]
            width = max(0.5, float(effective.get("width", 3.0)))
            height = max(0.2, float(effective.get("height", 10.0)))
            add_box(bm, float(point[0]), float(point[1]), ground_z + height / 2,
                    width, width, height)
            made = True
        if not made:
            bm.free()
            continue
        obj = finalize("Feature_" + safe_name(identity), bm, material,
                       infrastructure_collection)
        if obj:
            report["features"].append({
                "id": str(feature.get("id", feature.get("osm_id", identity))),
                "name": obj.name,
                "kind": feature.get("kind"),
                "family": family or feature.get("family"),
                "height": feature_height,
            })

    camera_cfg = style["camera"]
    azimuth = math.radians(float(camera_cfg["azimuth_deg"]))
    elevation = math.radians(float(camera_cfg["elev_deg"]))
    distance = focus_span * float(camera_cfg["margin"])
    oblique_data = bpy.data.cameras.new("BLK_CamOblique")
    oblique_data.lens = 42
    oblique = bpy.data.objects.new("BLK_CamOblique", oblique_data)
    oblique.location = (
        focus_center[0] + distance * math.cos(azimuth) * math.cos(elevation),
        focus_center[1] + distance * math.sin(azimuth) * math.cos(elevation),
        distance * math.sin(elevation),
    )
    rig_collection.objects.link(oblique)

    holdout_azimuth = azimuth + math.radians(float(
        camera_cfg.get("holdout_azimuth_offset_deg", 110.0)))
    holdout_elevation = math.radians(float(camera_cfg.get("holdout_elev_deg", 28.0)))
    holdout_distance = distance * 1.05
    holdout_data = bpy.data.cameras.new("BLK_CamHoldout")
    holdout_data.lens = 45
    holdout = bpy.data.objects.new("BLK_CamHoldout", holdout_data)
    holdout.location = (
        focus_center[0] + holdout_distance * math.cos(holdout_azimuth) * math.cos(holdout_elevation),
        focus_center[1] + holdout_distance * math.sin(holdout_azimuth) * math.cos(holdout_elevation),
        holdout_distance * math.sin(holdout_elevation),
    )
    rig_collection.objects.link(holdout)

    aerial_data = bpy.data.cameras.new("BLK_CamAerial")
    aerial_data.lens = 50
    aerial = bpy.data.objects.new("BLK_CamAerial", aerial_data)
    aerial.location = (focus_center[0], focus_center[1] - focus_span * 0.12,
                       focus_span * float(camera_cfg["aerial_height_factor"]))
    rig_collection.objects.link(aerial)

    target = bpy.data.objects.new("BLK_Target", None)
    target.location = (focus_center[0], focus_center[1], min(12.0, focus_span * 0.06))
    rig_collection.objects.link(target)
    for camera in (oblique, aerial, holdout):
        constraint = camera.constraints.new("TRACK_TO")
        constraint.target = target
        constraint.track_axis = "TRACK_NEGATIVE_Z"
        constraint.up_axis = "UP_Y"

    detail_views = []
    for index, view in enumerate(style.get("detail_views") or []):
        if not isinstance(view, dict):
            continue
        raw_name = str(view.get("name") or f"detail_{index + 1}")
        view_name = safe_name(raw_name).lower()
        point = view.get("point") or focus_center
        if len(point) < 2:
            point = focus_center
        view_center = (float(point[0]), float(point[1]))
        view_span = max(5.0, float(view.get("span") or focus_span * 0.3))
        view_azimuth = math.radians(float(view.get("azimuth_deg", camera_cfg["azimuth_deg"])))
        view_elevation = math.radians(float(view.get("elev_deg", 24.0)))
        view_distance = view_span * float(view.get("margin", 1.25))
        camera_data = bpy.data.cameras.new("BLK_CamDetail_" + safe_name(raw_name))
        camera_data.lens = float(view.get("lens", 52.0))
        camera_obj = bpy.data.objects.new(camera_data.name, camera_data)
        camera_obj.location = (
            view_center[0] + view_distance * math.cos(view_azimuth) * math.cos(view_elevation),
            view_center[1] + view_distance * math.sin(view_azimuth) * math.cos(view_elevation),
            view_distance * math.sin(view_elevation),
        )
        camera_obj["detail_render_filename"] = view_name + ".png"
        rig_collection.objects.link(camera_obj)
        detail_target = bpy.data.objects.new("BLK_TargetDetail_" + safe_name(raw_name), None)
        detail_target.location = (view_center[0], view_center[1],
                                  float(view.get("target_z", min(4.0, view_span * 0.08))))
        rig_collection.objects.link(detail_target)
        constraint = camera_obj.constraints.new("TRACK_TO")
        constraint.target = detail_target
        constraint.track_axis = "TRACK_NEGATIVE_Z"
        constraint.up_axis = "UP_Y"
        detail_views.append({"name": raw_name, "camera": camera_obj.name,
                             "filename": view_name + ".png", "span": view_span})
    report["detail_views"] = detail_views

    sun_cfg = style["sun"]
    sun_data = bpy.data.lights.new("BLK_Sun", "SUN")
    sun_data.energy = float(sun_cfg["energy"])
    sun_data.angle = math.radians(float(sun_cfg["angle_deg"]))
    sun = bpy.data.objects.new("BLK_Sun", sun_data)
    sun.rotation_euler = tuple(math.radians(value) for value in sun_cfg["rot_deg"])
    rig_collection.objects.link(sun)

    world = bpy.context.scene.world or bpy.data.worlds.new("World")
    bpy.context.scene.world = world
    setup_sky_world(world, style, sun)
    add_roof_props(style)

    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.cycles.samples = int(style["samples"])
    scene.cycles.use_denoising = True
    scene.render.resolution_x, scene.render.resolution_y = map(int, style["resolution"])
    scene.render.resolution_percentage = 100
    scene.camera = oblique
    try:
        scene.view_settings.view_transform = "AgX"
    except Exception:
        pass
    for look in ("Medium High Contrast", "AgX - Medium High Contrast", "None"):
        try:
            scene.view_settings.look = look
            break
        except Exception:
            continue

    report["fluid_networks"]["visible_length_m"] = round(
        report["fluid_networks"]["visible_length_m"], 2)
    report["objects"] = len(bpy.data.objects)
    report_path = os.path.join(outdir, "build_report.json")
    with open(report_path, "w", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2, ensure_ascii=False)

    blend_path = os.path.join(outdir, f"{slug}_blocks.blend")
    bpy.ops.wm.save_as_mainfile(filepath=os.path.abspath(blend_path))
    if do_render:
        render_views(outdir)
    print("BLOCKS BUILD OK:", json.dumps(report, ensure_ascii=False))
    return report


def render_views(outdir):
    scene = bpy.context.scene
    for camera_name, filename in (("BLK_CamOblique", "blocks_oblique.png"),
                                  ("BLK_CamAerial", "blocks_aerial.png"),
                                  ("BLK_CamHoldout", "blocks_holdout.png")):
        camera = bpy.data.objects.get(camera_name)
        if camera is None:
            continue
        scene.camera = camera
        scene.render.filepath = os.path.abspath(os.path.join(outdir, filename))
        bpy.ops.render.render(write_still=True)


def render_detail_views(outdir, filename_prefix="", resolution=None):
    """Render optional style-defined close cameras and return their paths."""
    scene = bpy.context.scene
    if resolution:
        scene.render.resolution_x, scene.render.resolution_y = map(int, resolution)
    rendered = []
    prefix = (str(filename_prefix).strip() + "_") if filename_prefix else ""
    for camera in sorted(bpy.data.objects, key=lambda item: item.name):
        filename = camera.get("detail_render_filename")
        if camera.type != "CAMERA" or not filename:
            continue
        path = os.path.abspath(os.path.join(outdir, prefix + str(filename)))
        scene.camera = camera
        scene.render.filepath = path
        bpy.ops.render.render(write_still=True)
        rendered.append(path)
    return rendered


def _cli():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    if len(argv) < 3:
        print("usage: blender -b -P blocks_build.py -- <scene.json> <outdir> <slug> "
              "[--style f] [--render] [--samples n]")
        return
    scene_path, outdir, slug = argv[:3]
    style_path = argv[argv.index("--style") + 1] if "--style" in argv else None
    samples = int(argv[argv.index("--samples") + 1]) if "--samples" in argv else None
    build_from_scene(scene_path, outdir, slug, style_path,
                     do_render="--render" in argv, samples=samples)


if __name__ == "__main__":
    _cli()
