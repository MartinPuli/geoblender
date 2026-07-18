#!/usr/bin/env python3
"""
blender_build.py — build and render a Blender 3D scene from scene.json.

It can run in two ways:
  A) With the Blender binary:
       blender -b -P blender_build.py -- scene.json model.blend render.png
  B) With the Python ``bpy`` module (pip install bpy):
       python3 blender_build.py scene.json model.blend render.png

scene.json coordinates use meters: X=east, Y=north, Z=up. One Blender unit is one meter.
"""
import json
import math
import os
import sys

import bpy
import bmesh

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from cityroofs import choose_roof_kind  # noqa: E402  (pure roof-type selection)

# Directory containing CC0 textures. When configured and populated, real
# photographic textures are used for ground and roads; otherwise use flat colors.
TEXTURE_DIR = os.environ.get("MAPS3D_TEXTURES", "")
# Real-sky HDRI for lighting and photorealistic reflections.
HDRI_PATH = os.environ.get("MAPS3D_HDRI", "")


def _tex(name):
    if TEXTURE_DIR:
        p = os.path.join(TEXTURE_DIR, name)
        if os.path.isfile(p):
            return p
    return None


def _texset(base):
    """Return PBR texture paths for ``<base>_*``, or None without a diffuse map."""
    if not TEXTURE_DIR:
        return None
    out = {}
    for suffix in ("diff", "rough", "nor"):
        for ext in ("jpg", "png", "exr"):
            p = os.path.join(TEXTURE_DIR, f"{base}_{suffix}.{ext}")
            if os.path.isfile(p):
                out[suffix] = p
                break
    return out if out.get("diff") else None


def using_hdri():
    return bool(HDRI_PATH and os.path.isfile(HDRI_PATH))

# --- Render and camera parameters ---
RES_X, RES_Y = 1280, 960
CYCLES_SAMPLES = 48
SUN_ENERGY = 2.4
WORLD_STRENGTH = 0.18   # low ambient strength preserves saturation
EXPOSURE = -0.5         # exposure compensation prevents clipped whites
CAM_ELEV_DEG = 38.0     # three-quarter aerial camera elevation
CAM_AZIM_DEG = 45.0     # azimut
CAM_DIST_FACTOR = 2.15  # distance = scene radius * factor
CAM_FRAME_FACTOR = 1.05  # framing margin around the scene
GROUND_COLOR = (0.30, 0.31, 0.32)   # light concrete sidewalk/plaza
ASPHALT_COLOR = (0.075, 0.075, 0.085)  # low-albedo asphalt
MARKING_COLOR = (0.82, 0.82, 0.78)     # weathered road markings
SIDEWALK_COLOR = (0.46, 0.45, 0.44)    # concrete sidewalk
BRIDGE_MAT_COLOR = (0.46, 0.45, 0.43)  # concrete bridge deck
WATER_COLOR = (0.020, 0.055, 0.085)    # deep water reflecting the sky
ROOF_HOUSE_COLOR = (0.62, 0.30, 0.24)  # terracotta roof tiles
ROOF_FLAT_COLOR = (0.44, 0.45, 0.48)   # gray flat roof
ROOF_SMALL_MAX_H = 11.0  # lower buildings may receive pitched roofs
BEVEL = 0.18             # building-edge bevel in meters

# --- Height-based material classification ---
# Modern high-rises use reflective curtain walls; mid-rise buildings use modern
# façades; low-rise buildings use masonry.
GLASS_MIN_HEIGHT = 36.0     # reflective glass tower threshold
MODERN_MIN_HEIGHT = 20.0    # mid-rises also use mostly glass below GLASS_MIN_HEIGHT
GLASS_TINTS = [
    (0.030, 0.055, 0.075),  # azul noche
    (0.035, 0.070, 0.080),  # azul verdoso
    (0.045, 0.080, 0.095),  # turquesa oscuro
    (0.030, 0.050, 0.070),  # gris azulado
    (0.050, 0.075, 0.085),  # petroleo
]
MULLION_COLOR = (0.62, 0.65, 0.68)   # aluminum mullions and spandrels

# Photographic tone mapping for street-level views with a physical sky.
STREET_EXPOSURE = -3.0        # bright physical Nishita sky
STREET_EXPOSURE_HDRI = -0.5   # real HDRI uses a different calibration
HDRI_ROT_DEG = 40.0           # HDRI rotation used to orient the sun
STREET_LOOKS = ("AgX - High Contrast", "AgX - Punchy", "AgX - Medium High Contrast",
                "High Contrast", "None")


# ---------------------------------------------------------------------------
# Arguments for both ``blender --`` and direct Python execution.
# ---------------------------------------------------------------------------

def parse_args():
    argv = sys.argv
    if "--" in argv:
        argv = argv[argv.index("--") + 1:]
    else:
        argv = argv[1:]
    if len(argv) < 3:
        sys.exit("Usage: blender_build.py scene.json model.blend render.png")
    return argv[0], argv[1], argv[2]


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------

def dedupe_ring(pts, closed=True, eps=1e-4):
    """Remove consecutive duplicates and the repeated closing ring point."""
    out = []
    for p in pts:
        if not out or abs(p[0] - out[-1][0]) > eps or abs(p[1] - out[-1][1]) > eps:
            out.append((p[0], p[1]))
    if closed and len(out) > 1 and abs(out[0][0] - out[-1][0]) < eps and abs(out[0][1] - out[-1][1]) < eps:
        out.pop()
    return out


def add_prism(bm, footprint, base_z, top_z):
    """Add a closed building prism to a bmesh."""
    pts = dedupe_ring(footprint, closed=True)
    if len(pts) < 3:
        return
    try:
        verts = [bm.verts.new((x, y, base_z)) for (x, y) in pts]
        face = bm.faces.new(verts)
    except ValueError:
        return
    res = bmesh.ops.extrude_face_region(bm, geom=[face])
    top_verts = [g for g in res["geom"] if isinstance(g, bmesh.types.BMVert)]
    bmesh.ops.translate(bm, vec=(0.0, 0.0, top_z - base_z), verts=top_verts)


def add_flat_polygon(bm, poly, z):
    """Add a flat polygon such as water or green space to a bmesh."""
    pts = dedupe_ring(poly, closed=True)
    if len(pts) < 3:
        return
    # OSM does not guarantee outer-ring winding. Force CCW so normals face +Z;
    # otherwise some aprons or areas render black in Cycles.
    signed_area = sum(
        pts[i][0] * pts[(i + 1) % len(pts)][1] -
        pts[(i + 1) % len(pts)][0] * pts[i][1]
        for i in range(len(pts))
    )
    if signed_area < 0:
        pts.reverse()
    # Triangulate before creating faces with robust ear clipping. Passing a
    # concave or slightly self-intersecting ngon through bm.faces.new followed by
    # triangulation can produce overlapping coplanar triangles and black patches.
    import mathutils
    poly_vectors = [mathutils.Vector((x, y, 0.0)) for (x, y) in pts]
    verts = [bm.verts.new((x, y, z)) for (x, y) in pts]
    try:
        tris = mathutils.geometry.tessellate_polygon([poly_vectors])
    except Exception:
        tris = []
    if not tris:
        try:
            bm.faces.new(verts)
        except ValueError:
            pass
        return
    # Blender versions may return indices or original vectors. Accept both, with
    # coordinate matching as a fallback when Blender returns copies.
    by_identity = {id(v): i for i, v in enumerate(poly_vectors)}
    by_coordinate = {(round(v.x, 9), round(v.y, 9)): i
                     for i, v in enumerate(poly_vectors)}

    def vertex_index(value):
        if isinstance(value, int):
            return value if 0 <= value < len(verts) else None
        return by_identity.get(
            id(value),
            by_coordinate.get((round(value.x, 9), round(value.y, 9))),
        )

    for tri in tris:
        indices = [vertex_index(value) for value in tri]
        if any(i is None for i in indices):
            continue
        a, b, c = indices
        pa, pb, pc = pts[a], pts[b], pts[c]
        cross = (pb[0] - pa[0]) * (pc[1] - pa[1]) - (pb[1] - pa[1]) * (pc[0] - pa[0])
        if abs(cross) < 1e-9:
            continue
        order = (verts[a], verts[b], verts[c]) if cross > 0 else \
                (verts[a], verts[c], verts[b])
        try:
            bm.faces.new(order)
        except ValueError:
            pass


def _centroid_bbox(pts):
    cx = sum(p[0] for p in pts) / len(pts)
    cy = sum(p[1] for p in pts) / len(pts)
    sx = max(p[0] for p in pts) - min(p[0] for p in pts)
    sy = max(p[1] for p in pts) - min(p[1] for p in pts)
    return cx, cy, sx, sy


def add_hip_roof(bm, footprint, top_z):
    """Add a hipped roof from the original ring and a smaller elevated ring."""
    pts = dedupe_ring(footprint, closed=True)
    if len(pts) < 3:
        return
    cx, cy, sx, sy = _centroid_bbox(pts)
    roof_h = max(1.5, min(4.5, 0.35 * min(sx, sy)))
    shrink = 0.62
    try:
        base = [bm.verts.new((x, y, top_z)) for (x, y) in pts]
        top = [bm.verts.new((cx + (x - cx) * (1 - shrink),
                             cy + (y - cy) * (1 - shrink),
                             top_z + roof_h)) for (x, y) in pts]
    except ValueError:
        return
    n = len(pts)
    for i in range(n):
        j = (i + 1) % n
        try:
            bm.faces.new((base[i], base[j], top[j], top[i]))
        except ValueError:
            pass
    try:
        bm.faces.new(top)   # tapa superior
    except ValueError:
        pass


def add_rooftop_detail(bm, footprint, top_z):
    """Add a rooftop utility box for tower detail."""
    pts = dedupe_ring(footprint, closed=True)
    if len(pts) < 3:
        return
    cx, cy, sx, sy = _centroid_bbox(pts)
    w = max(1.6, min(6.0, 0.32 * min(sx, sy)))
    h = 2.6
    box = [(cx - w / 2, cy - w / 2), (cx + w / 2, cy - w / 2),
           (cx + w / 2, cy + w / 2), (cx - w / 2, cy + w / 2)]
    add_prism(bm, box, top_z, top_z + h)


def _bbox_major_x(pts):
    _, _, sx, sy = _centroid_bbox(pts)
    return sx >= sy


def add_gabled_roof(bm, footprint, top_z):
    """Add a gabled roof with its ridge along the longer bounding-box axis."""
    pts = dedupe_ring(footprint, closed=True)
    if len(pts) < 3:
        return
    cx, cy, sx, sy = _centroid_bbox(pts)
    roof_h = max(1.5, min(4.5, 0.30 * min(sx, sy)))
    if sx >= sy:
        ra, rb = (cx - sx * 0.5, cy), (cx + sx * 0.5, cy)
    else:
        ra, rb = (cx, cy - sy * 0.5), (cx, cy + sy * 0.5)
    try:
        base = [bm.verts.new((x, y, top_z)) for (x, y) in pts]
        va = bm.verts.new((ra[0], ra[1], top_z + roof_h))
        vb = bm.verts.new((rb[0], rb[1], top_z + roof_h))
    except ValueError:
        return

    def nearest(x, y):
        da = (x - ra[0]) ** 2 + (y - ra[1]) ** 2
        db = (x - rb[0]) ** 2 + (y - rb[1]) ** 2
        return va if da <= db else vb

    n = len(pts)
    for i in range(n):
        j = (i + 1) % n
        ni, nj = nearest(*pts[i]), nearest(*pts[j])
        try:
            if ni is nj:
                bm.faces.new((base[i], base[j], ni))
            else:
                bm.faces.new((base[i], base[j], nj, ni))
        except ValueError:
            pass


def add_pyramidal_roof(bm, footprint, top_z):
    """Add a pyramidal roof whose edges rise to a central apex."""
    pts = dedupe_ring(footprint, closed=True)
    if len(pts) < 3:
        return
    cx, cy, sx, sy = _centroid_bbox(pts)
    roof_h = max(1.6, min(6.0, 0.5 * min(sx, sy)))
    try:
        base = [bm.verts.new((x, y, top_z)) for (x, y) in pts]
        apex = bm.verts.new((cx, cy, top_z + roof_h))
    except ValueError:
        return
    n = len(pts)
    for i in range(n):
        j = (i + 1) % n
        try:
            bm.faces.new((base[i], base[j], apex))
        except ValueError:
            pass


def add_dome_roof(bm, footprint, top_z):
    """Add a flattened icosphere dome fitted to the footprint bounds."""
    pts = dedupe_ring(footprint, closed=True)
    if len(pts) < 3:
        return
    cx, cy, sx, sy = _centroid_bbox(pts)
    r = max(1.5, 0.5 * min(sx, sy))
    res = _icosphere(bm, radius=r, subdivisions=2)
    verts = list(res["verts"])
    for v in verts:
        if v.co.z < 0:
            v.co.z *= 0.10   # flatten the lower half inside the building
        v.co.z *= 0.9
    bmesh.ops.translate(bm, verts=verts, vec=(cx, cy, top_z))


def add_skillion_roof(bm, footprint, top_z):
    """Add a mono-pitch roof with one side higher than the other."""
    pts = dedupe_ring(footprint, closed=True)
    if len(pts) < 3:
        return
    major_x = _bbox_major_x(pts)
    roof_h = max(1.2, min(4.0, 0.25 * min(*_centroid_bbox(pts)[2:])))
    lo = min((p[0] if major_x else p[1]) for p in pts)
    hi = max((p[0] if major_x else p[1]) for p in pts)
    span = (hi - lo) or 1.0
    try:
        top = [bm.verts.new((x, y, top_z + roof_h * (((x if major_x else y) - lo) / span)))
               for (x, y) in pts]
        bm.faces.new(top)   # sloped plane
    except ValueError:
        return


def add_parapet(bm, footprint, top_z, h=1.1):
    """Add a perimeter parapet to a flat roof."""
    pts = dedupe_ring(footprint, closed=True)
    if len(pts) < 3:
        return
    n = len(pts)
    try:
        low = [bm.verts.new((x, y, top_z)) for (x, y) in pts]
        high = [bm.verts.new((x, y, top_z + h)) for (x, y) in pts]
    except ValueError:
        return
    for i in range(n):
        j = (i + 1) % n
        try:
            bm.faces.new((low[i], low[j], high[j], high[i]))
        except ValueError:
            pass


def build_roof(kind, footprint, top_z, house_bm, flat_bm):
    """Build the selected roof into the appropriate tile or flat-roof bmesh."""
    if kind == "hipped":
        add_hip_roof(house_bm, footprint, top_z)
    elif kind == "gabled":
        add_gabled_roof(house_bm, footprint, top_z)
    elif kind == "pyramidal":
        add_pyramidal_roof(house_bm, footprint, top_z)
    elif kind == "skillion":
        add_skillion_roof(house_bm, footprint, top_z)
    elif kind == "dome":
        add_dome_roof(flat_bm, footprint, top_z)
    elif kind == "parapet":
        add_parapet(flat_bm, footprint, top_z)
        add_rooftop_detail(flat_bm, footprint, top_z)
    else:  # flat
        add_rooftop_detail(flat_bm, footprint, top_z)


LANDMARK_TYPES = {"obelisk", "tower", "monument", "mast", "chimney"}


def add_spire(bm, footprint, base_z, top_z):
    """Add a tapered spire or tower with a pyramidal tip."""
    pts = dedupe_ring(footprint, closed=True)
    if len(pts) < 3:
        return
    cx, cy, sx, sy = _centroid_bbox(pts)
    shaft_top = base_z + (top_z - base_z) * 0.85
    taper = 0.25  # narrows toward the top
    try:
        bottom = [bm.verts.new((x, y, base_z)) for (x, y) in pts]
        ring = [bm.verts.new((cx + (x - cx) * (1 - taper),
                              cy + (y - cy) * (1 - taper), shaft_top))
                for (x, y) in pts]
        apex = bm.verts.new((cx, cy, top_z))
    except ValueError:
        return
    n = len(pts)
    for i in range(n):
        j = (i + 1) % n
        try:
            bm.faces.new((bottom[i], bottom[j], ring[j], ring[i]))  # fuste
        except ValueError:
            pass
        try:
            bm.faces.new((ring[i], ring[j], apex))                  # punta
        except ValueError:
            pass
    try:
        bm.faces.new(bottom)  # base
    except ValueError:
        pass


def _icosphere(bm, radius, subdivisions=2):
    try:
        return bmesh.ops.create_icosphere(bm, subdivisions=subdivisions, radius=radius)
    except TypeError:
        return bmesh.ops.create_icosphere(bm, subdivisions=subdivisions, diameter=radius * 2)


def _hash01(seed):
    n = math.sin(seed * 127.1 + 311.7) * 43758.5453
    return n - math.floor(n)


def add_tree(trunk_bm, fol_bm, cards_bm, x, y, height=6.0):
    """Add a tree with a slender trunk, multilobed opaque core, and leaf-card shell
    (alpha quads) that breaks the silhouette and reveals sky between leaves."""
    seed = x * 12.9898 + y * 4.1414
    tw = max(0.16, height * 0.032)
    box = [(x - tw, y - tw), (x + tw, y - tw), (x + tw, y + tw), (x - tw, y + tw)]
    add_prism(trunk_bm, box, 0.0, height * 0.55)
    base_r = height * 0.30
    # Opaque core with smaller lobes; leaf cards extend the volume.
    lobes = [(0.0, 0.0, 0.02, 0.85, 2),
             (0.50, 0.18, -0.05, 0.55, 1),
             (-0.35, -0.40, 0.06, 0.50, 1)]
    for li, (ox, oy, zoff, rf, sub) in enumerate(lobes):
        jr = 0.85 + 0.30 * _hash01(seed + li * 3.7)
        res = _icosphere(fol_bm, radius=base_r * rf * jr, subdivisions=sub)
        verts = [v for v in res["verts"]]
        s2 = seed + li * 7.3
        for v in verts:
            n = math.sin(v.co.x * 3.1 + v.co.y * 5.7 + v.co.z * 2.3 + s2) * 43758.5453
            f = 0.74 + 0.40 * (n - math.floor(n))
            v.co.x *= f
            v.co.y *= f
            v.co.z *= f * 0.82
        bmesh.ops.translate(fol_bm, verts=verts,
                            vec=(x + ox * base_r, y + oy * base_r, height * 0.80 + zoff * height))
    # Vertical leaf-card shell over the canopy for a broken silhouette and gaps.
    for c in range(40):
        u = _hash01(seed + c * 1.13)
        vv = _hash01(seed + c * 2.71)
        ww = _hash01(seed + c * 3.97)
        theta = u * 6.28318
        phi = math.acos(2.0 * vv - 1.0)
        rr = base_r * (0.80 + 0.55 * ww)
        px = x + rr * math.sin(phi) * math.cos(theta)
        py = y + rr * math.sin(phi) * math.sin(theta)
        pz = height * 0.80 + rr * math.cos(phi) * 0.82
        a1 = _hash01(seed + c * 5.13) * 6.28318
        ax, ay = math.cos(a1), math.sin(a1)
        s = base_r * 0.45
        try:
            v1 = cards_bm.verts.new((px - ax * s, py - ay * s, pz - s))
            v2 = cards_bm.verts.new((px + ax * s, py + ay * s, pz - s))
            v3 = cards_bm.verts.new((px + ax * s, py + ay * s, pz + s))
            v4 = cards_bm.verts.new((px - ax * s, py - ay * s, pz + s))
            cards_bm.faces.new((v1, v2, v3, v4))
        except ValueError:
            pass


def scatter_trees(areas, roads, cap=900):
    """Return trunk, opaque foliage cores, leaf cards, and the tree count with a
    leaf-card shell for trees in plazas and along wide avenues."""
    trunk_bm = bmesh.new()
    fol_bm = bmesh.new()
    cards_bm = bmesh.new()
    count = 0

    # Trees in green areas.
    for a in areas:
        if a.get("type") in ("water",) or a["color"][2] > a["color"][1]:
            continue  # never place trees in water
        pts = dedupe_ring(a["polygon"], closed=True)
        if len(pts) < 3:
            continue
        cx, cy, sx, sy = _centroid_bbox(pts)
        n = min(10, max(1, int(sx * sy / 500)))
        for i in range(n):
            if count >= cap:
                break
            jx = (((i * 37) % 100) / 100.0 - 0.5) * sx * 0.6
            jy = (((i * 61) % 100) / 100.0 - 0.5) * sy * 0.6
            add_tree(trunk_bm, fol_bm, cards_bm, cx + jx, cy + jy, 5.5 + (i % 3))
            count += 1

    # Sidewalk trees at regular intervals along both sides of avenues.
    spacing = 13.0
    for r in roads:
        if count >= cap:
            break
        if float(r.get("width", 0)) < 7.0 or r.get("z", 0) > 1:
            continue
        pts = dedupe_ring(r["path"], closed=False)
        off = float(r["width"]) / 2 + 3.6
        for i in range(len(pts) - 1):
            x1, y1 = pts[i]
            x2, y2 = pts[i + 1]
            dx, dy = x2 - x1, y2 - y1
            L = math.hypot(dx, dy)
            if L < 6:
                continue
            ux, uy = dx / L, dy / L
            nx, ny = -uy, ux
            d = spacing * 0.5
            while d < L and count < cap:
                # Add axial jitter to break up perfectly regular rows.
                dj = d + (_hash01(x1 + y1 + d) - 0.5) * spacing * 0.4
                bx, by = x1 + ux * dj, y1 + uy * dj
                for side in (1, -1):
                    if count >= cap:
                        break
                    if _hash01(bx * 1.7 + by * 2.3 + side) < 0.12:
                        continue   # skip about 12% to avoid perfect tree rows
                    offj = off + (_hash01(bx * 3.1 + by) - 0.5) * 1.2
                    h = 6.6 + _hash01(bx + by) * 2.6
                    add_tree(trunk_bm, fol_bm, cards_bm, bx + nx * offj * side,
                             by + ny * offj * side, h)
                    count += 1
                d += spacing
    return trunk_bm, fol_bm, cards_bm, count


def scatter_streetlights(roads, cap=140, spacing=32.0, height=9.0):
    """Scatter slender streetlights along avenues."""
    bm = bmesh.new()
    count = 0
    for r in roads:
        if count >= cap:
            break
        if float(r.get("width", 0)) < 8.0 or r.get("z", 0) > 1:
            continue
        pts = dedupe_ring(r["path"], closed=False)
        off = float(r["width"]) / 2 + 1.2
        for i in range(len(pts) - 1):
            x1, y1 = pts[i]
            x2, y2 = pts[i + 1]
            dx, dy = x2 - x1, y2 - y1
            L = math.hypot(dx, dy)
            if L < 8:
                continue
            ux, uy = dx / L, dy / L
            nx, ny = -uy, ux
            d = spacing * 0.5
            while d < L and count < cap:
                bx, by = x1 + ux * d, y1 + uy * d
                for side in (1, -1):
                    if count >= cap:
                        break
                    px, py = bx + nx * off * side, by + ny * off * side
                    s = 0.12
                    box = [(px - s, py - s), (px + s, py - s),
                           (px + s, py + s), (px - s, py + s)]
                    add_prism(bm, box, 0.0, height)
                    count += 1
                d += spacing
    return bm


# Colores de auto realistas (mayoria blanco/gris/negro/plata en BA).
CAR_COLORS = [
    (0.72, 0.72, 0.73),  # blanco
    (0.72, 0.72, 0.73),  # blanco
    (0.66, 0.67, 0.69),  # plata
    (0.045, 0.045, 0.05),  # negro
    (0.045, 0.045, 0.05),  # negro
    (0.20, 0.21, 0.23),  # gris oscuro
    (0.32, 0.11, 0.11),  # bordo
    (0.10, 0.16, 0.30),  # azul
]


def _oriented_rect(cx, cy, ux, uy, length, width):
    """Return four corners of a centered rectangle aligned to (ux, uy)."""
    px, py = -uy, ux
    hl, hw = length / 2.0, width / 2.0
    return [
        (cx - ux * hl - px * hw, cy - uy * hl - py * hw),
        (cx + ux * hl - px * hw, cy + uy * hl - py * hw),
        (cx + ux * hl + px * hw, cy + uy * hl + py * hw),
        (cx - ux * hl + px * hw, cy - uy * hl + py * hw),
    ]


def add_car(body_bm, glass_bm, cx, cy, ux, uy):
    """Add a two-tone car body, dark glazed cabin, and four dark wheels."""
    body = _oriented_rect(cx, cy, ux, uy, 4.2, 1.74)
    add_prism(body_bm, body, 0.24, 0.78)          # body raised by wheels
    cab = _oriented_rect(cx - ux * 0.15, cy - uy * 0.15, ux, uy, 2.1, 1.55)
    add_prism(glass_bm, cab, 0.78, 1.28)          # dark glazed cabin
    for a in (1.25, -1.25):                        # 4 ruedas
        for b in (0.80, -0.80):
            wx = cx + ux * a - uy * b
            wy = cy + uy * a + ux * b
            add_prism(glass_bm, _oriented_rect(wx, wy, ux, uy, 0.7, 0.32), 0.0, 0.34)


def scatter_cars(roads, cap=520, spacing=7.5):
    """Scatter parked cars and return color buckets, dark parts, and count."""
    buckets = {i: bmesh.new() for i in range(len(CAR_COLORS))}
    glass_bm = bmesh.new()
    count = 0
    for r in roads:
        if count >= cap:
            break
        w = float(r.get("width", 0))
        if w < 6.0 or r.get("z", 0) > 1:
            continue
        pts = dedupe_ring(r["path"], closed=False)
        off = w / 2.0 - 1.1   # parking lane near the curb
        for i in range(len(pts) - 1):
            x1, y1 = pts[i]
            x2, y2 = pts[i + 1]
            dx, dy = x2 - x1, y2 - y1
            L = math.hypot(dx, dy)
            if L < 8:
                continue
            ux, uy = dx / L, dy / L
            nx, ny = -uy, ux
            d = spacing
            while d < L - 3 and count < cap:
                bx, by = x1 + ux * d, y1 + uy * d
                for side in (1, -1):
                    if count >= cap:
                        break
                    key = int(abs(round(bx * 7.0 + by * 3.0)))
                    if key % 3 != 0:      # occupy about one-third of spaces
                        continue
                    idx = key % len(CAR_COLORS)
                    ccx = bx + nx * off * side
                    ccy = by + ny * off * side
                    if ccx * ccx + ccy * ccy < 49.0:
                        continue   # keep about 7 m clear around the street camera
                    add_car(buckets[idx], glass_bm, ccx, ccy, ux, uy)
                    count += 1
                d += spacing
    return buckets, glass_bm, count


def _add_boundary(coll, minx, miny, maxx, maxy, z=0.2):
    """Add an edge-loop boundary for the requested area in 00_REFERENCE."""
    me = bpy.data.meshes.new("Area_boundary")
    verts = [(minx, miny, z), (maxx, miny, z), (maxx, maxy, z), (minx, maxy, z)]
    edges = [(0, 1), (1, 2), (2, 3), (3, 0)]
    me.from_pydata(verts, edges, [])
    me.update()
    ob = bpy.data.objects.new("Area_boundary", me)
    coll.objects.link(ob)
    return ob


def add_bridge_piers(bm, path, deck_z, spacing=18.0, size=1.4):
    """Add support piers from the ground to an elevated bridge deck."""
    pts = dedupe_ring(path, closed=False)
    s = size / 2.0
    placed = 0
    for i in range(len(pts) - 1):
        x1, y1 = pts[i]
        x2, y2 = pts[i + 1]
        dx, dy = x2 - x1, y2 - y1
        L = math.hypot(dx, dy)
        if L < 1e-6:
            continue
        d = 0.0
        while d <= L and placed < 40:
            t = d / L
            cx, cy = x1 + dx * t, y1 + dy * t
            box = [(cx - s, cy - s), (cx + s, cy - s), (cx + s, cy + s), (cx - s, cy + s)]
            add_prism(bm, box, 0.0, deck_z)
            placed += 1
            d += spacing


def add_lane_markings(bm, path, width, z, dash=3.5, gap=5.0, mw=0.16):
    """Add a dashed white center line along a road."""
    pts = dedupe_ring(path, closed=False)
    zz = z + 0.02
    for i in range(len(pts) - 1):
        x1, y1 = pts[i]
        x2, y2 = pts[i + 1]
        dx, dy = x2 - x1, y2 - y1
        L = math.hypot(dx, dy)
        if L < 1e-6:
            continue
        ux, uy = dx / L, dy / L
        nx, ny = -uy * mw, ux * mw
        d = 0.0
        while d < L:
            a, bpos = d, min(L, d + dash)
            ax, ay = x1 + ux * a, y1 + uy * a
            bx, by = x1 + ux * bpos, y1 + uy * bpos
            try:
                v1 = bm.verts.new((ax + nx, ay + ny, zz))
                v2 = bm.verts.new((ax - nx, ay - ny, zz))
                v3 = bm.verts.new((bx - nx, by - ny, zz))
                v4 = bm.verts.new((bx + nx, by + ny, zz))
                bm.faces.new((v1, v2, v3, v4))
            except ValueError:
                pass
            d += dash + gap


def add_sidewalks(bm, path, road_width, z, sw=3.6, curb_h=0.15):
    """Add a raised concrete sidewalk beside the road, including an inner curb
    vertical inner curb that provides a real step for cars and trees."""
    pts = dedupe_ring(path, closed=False)
    inner = road_width / 2.0
    outer = inner + sw
    top = z + curb_h
    for i in range(len(pts) - 1):
        x1, y1 = pts[i]
        x2, y2 = pts[i + 1]
        dx, dy = x2 - x1, y2 - y1
        L = math.hypot(dx, dy)
        if L < 1e-6:
            continue
        nx, ny = -dy / L, dx / L
        for side in (1, -1):
            iax, iay = x1 + nx * inner * side, y1 + ny * inner * side
            ibx, iby = x2 + nx * inner * side, y2 + ny * inner * side
            oax, oay = x1 + nx * outer * side, y1 + ny * outer * side
            obx, oby = x2 + nx * outer * side, y2 + ny * outer * side
            try:
                # Sidewalk top face.
                a = bm.verts.new((iax, iay, top))
                b = bm.verts.new((oax, oay, top))
                c = bm.verts.new((obx, oby, top))
                d = bm.verts.new((ibx, iby, top))
                bm.faces.new((a, b, c, d))
                # Vertical curb face along the inner edge.
                e = bm.verts.new((iax, iay, z))
                f = bm.verts.new((ibx, iby, z))
                bm.faces.new((e, f, d, a))
            except ValueError:
                pass


def add_road_strip(bm, path, width, z):
    """Add a road as a quad strip along a polyline."""
    hw = width / 2.0
    pts = dedupe_ring(path, closed=False)
    for i in range(len(pts) - 1):
        x1, y1 = pts[i]
        x2, y2 = pts[i + 1]
        dx, dy = x2 - x1, y2 - y1
        L = math.hypot(dx, dy)
        if L < 1e-6:
            continue
        nx, ny = -dy / L * hw, dx / L * hw
        try:
            v1 = bm.verts.new((x1 + nx, y1 + ny, z))
            v2 = bm.verts.new((x1 - nx, y1 - ny, z))
            v3 = bm.verts.new((x2 - nx, y2 - ny, z))
            v4 = bm.verts.new((x2 + nx, y2 + ny, z))
            bm.faces.new((v1, v2, v3, v4))
        except ValueError:
            pass


# ---------------------------------------------------------------------------
# Materials and objects
# ---------------------------------------------------------------------------

def make_material(name, rgb, roughness=0.85, metallic=0.0, specular=0.15, coat=0.0):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    if bsdf:
        bsdf.inputs["Base Color"].default_value = (rgb[0], rgb[1], rgb[2], 1.0)
        if "Roughness" in bsdf.inputs:
            bsdf.inputs["Roughness"].default_value = roughness
        if "Metallic" in bsdf.inputs:
            bsdf.inputs["Metallic"].default_value = metallic
        for spec in ("Specular IOR Level", "Specular"):
            if spec in bsdf.inputs:
                bsdf.inputs[spec].default_value = specular
                break
        if coat > 0:  # clearcoat for glossy sky reflections on car paint
            for ck in ("Coat Weight", "Coat"):
                if ck in bsdf.inputs:
                    bsdf.inputs[ck].default_value = coat
                    break
            if "Coat Roughness" in bsdf.inputs:
                bsdf.inputs["Coat Roughness"].default_value = 0.05
    else:
        mat.diffuse_color = (rgb[0], rgb[1], rgb[2], 1.0)
    return mat


def make_windowed_material(name, wall_rgb):
    """Create a façade material with a procedural glass window grid.
    Use world coordinates in meters so windows retain real-world scale."""
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    bsdf = nt.nodes.get("Principled BSDF")
    if not bsdf:
        return mat
    try:
        geom = nt.nodes.new("ShaderNodeNewGeometry")
        sep = nt.nodes.new("ShaderNodeSeparateXYZ")
        addn = nt.nodes.new("ShaderNodeMath"); addn.operation = "ADD"
        comb = nt.nodes.new("ShaderNodeCombineXYZ")
        brick = nt.nodes.new("ShaderNodeTexBrick")
        # Façade coordinate: X_horizontal = X+Y, advancing across any wall.
        # Y_vertical = Z, making a wall grid instead of stripes.
        nt.links.new(geom.outputs["Position"], sep.inputs["Vector"])
        nt.links.new(sep.outputs["X"], addn.inputs[0])
        nt.links.new(sep.outputs["Y"], addn.inputs[1])
        nt.links.new(addn.outputs["Value"], comb.inputs["X"])
        nt.links.new(sep.outputs["Z"], comb.inputs["Y"])
        nt.links.new(comb.outputs["Vector"], brick.inputs["Vector"])
        # Windows use dark blue glass; mortar carries the wall color.
        brick.inputs["Color1"].default_value = (0.10, 0.13, 0.18, 1.0)
        brick.inputs["Color2"].default_value = (0.14, 0.18, 0.25, 1.0)
        brick.inputs["Mortar"].default_value = (wall_rgb[0], wall_rgb[1], wall_rgb[2], 1.0)
        params = {"Scale": 1.0, "Mortar Size": 0.28, "Mortar Smooth": 0.1,
                  "Bias": 0.0, "Brick Width": 3.4, "Row Height": 3.0}
        for nm, val in params.items():
            if nm in brick.inputs:
                brick.inputs[nm].default_value = val
        # Vertical grime creates dark streaks across the façade.
        # Break up flat albedo from one panel to the next.
        strk = nt.nodes.new("ShaderNodeTexNoise")
        smap = nt.nodes.new("ShaderNodeMapping")
        smap.inputs["Scale"].default_value = (2.5, 0.05, 1.0)  # estira vertical -> rayas
        if "Scale" in strk.inputs:
            strk.inputs["Scale"].default_value = 5.0
        if "Detail" in strk.inputs:
            strk.inputs["Detail"].default_value = 4.0
        sfac = nt.nodes.new("ShaderNodeMapRange")
        sfac.inputs["To Min"].default_value = 0.0
        sfac.inputs["To Max"].default_value = 0.28
        gmix, gf, gA, gB, gout = _mix_rgb_node(nt)
        gB.default_value = (wall_rgb[0] * 0.45, wall_rgb[1] * 0.45, wall_rgb[2] * 0.42, 1.0)
        nt.links.new(comb.outputs["Vector"], smap.inputs["Vector"])
        nt.links.new(smap.outputs["Vector"], strk.inputs["Vector"])
        nt.links.new(strk.outputs["Fac"], sfac.inputs["Value"])
        nt.links.new(brick.outputs["Color"], gA)
        nt.links.new(sfac.outputs["Result"], gf)
        nt.links.new(gout, bsdf.inputs["Base Color"])
        if "Roughness" in bsdf.inputs:
            bsdf.inputs["Roughness"].default_value = 0.55
        # Recess windows relative to the wall using grid bump.
        try:
            bump = nt.nodes.new("ShaderNodeBump")
            bump.inputs["Strength"].default_value = 0.30
            bump.inputs["Distance"].default_value = 0.25
            fout = brick.outputs.get("Fac") or brick.outputs["Color"]
            nt.links.new(fout, bump.inputs["Height"])
            nt.links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])
        except Exception:
            pass
    except Exception:
        bsdf.inputs["Base Color"].default_value = (wall_rgb[0], wall_rgb[1], wall_rgb[2], 1.0)
    return mat


def _set_spec(bsdf, val):
    for spec in ("Specular IOR Level", "Specular"):
        if spec in bsdf.inputs:
            bsdf.inputs[spec].default_value = val
            return


def make_glass_material(name, tint, mullion=MULLION_COLOR):
    """Create a reflective curtain wall with a mullion grid and horizontal spandrels
    plus vertical mullions). The glass is dark and smooth, reflecting the sky,
    so it appears blue and mirrored in full light like real curtain-wall glass."""
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    bsdf = nt.nodes.get("Principled BSDF")
    if not bsdf:
        return mat
    try:
        geom = nt.nodes.new("ShaderNodeNewGeometry")
        sep = nt.nodes.new("ShaderNodeSeparateXYZ")
        addn = nt.nodes.new("ShaderNodeMath"); addn.operation = "ADD"
        comb = nt.nodes.new("ShaderNodeCombineXYZ")
        brick = nt.nodes.new("ShaderNodeTexBrick")
        # Façade coordinates: X_horizontal = X+Y, Y_vertical = Z for a wall grid.
        nt.links.new(geom.outputs["Position"], sep.inputs["Vector"])
        nt.links.new(sep.outputs["X"], addn.inputs[0])
        nt.links.new(sep.outputs["Y"], addn.inputs[1])
        nt.links.new(addn.outputs["Value"], comb.inputs["X"])
        nt.links.new(sep.outputs["Z"], comb.inputs["Y"])
        nt.links.new(comb.outputs["Vector"], brick.inputs["Vector"])
        t2 = (min(1.0, tint[0] * 1.5 + 0.02), min(1.0, tint[1] * 1.4 + 0.02),
              min(1.0, tint[2] * 1.4 + 0.03))
        brick.inputs["Color1"].default_value = (tint[0], tint[1], tint[2], 1.0)
        brick.inputs["Color2"].default_value = (t2[0], t2[1], t2[2], 1.0)
        brick.inputs["Mortar"].default_value = (mullion[0], mullion[1], mullion[2], 1.0)
        params = {"Scale": 1.0, "Mortar Size": 0.055, "Mortar Smooth": 0.05,
                  "Bias": 0.0, "Brick Width": 1.75, "Row Height": 3.6}
        for nm, val in params.items():
            if nm in brick.inputs:
                brick.inputs[nm].default_value = val
        nt.links.new(brick.outputs["Color"], bsdf.inputs["Base Color"])
        # Recess mullions with depth from grid bump.
        gbump = nt.nodes.new("ShaderNodeBump")
        gbump.inputs["Strength"].default_value = 0.4
        gbump.inputs["Distance"].default_value = 0.15
        fout = brick.outputs.get("Fac") or brick.outputs["Color"]
        nt.links.new(fout, gbump.inputs["Height"])
        nt.links.new(gbump.outputs["Normal"], bsdf.inputs["Normal"])
        # Vary panel roughness so some panels reflect more strongly.
        vor = nt.nodes.new("ShaderNodeTexVoronoi")
        if "Scale" in vor.inputs:
            vor.inputs["Scale"].default_value = 0.5
        rr = nt.nodes.new("ShaderNodeMapRange")
        rr.inputs["To Min"].default_value = 0.02
        rr.inputs["To Max"].default_value = 0.11
        nt.links.new(comb.outputs["Vector"], vor.inputs["Vector"])
        vd = vor.outputs.get("Distance") or vor.outputs[0]
        nt.links.new(vd, rr.inputs["Value"])
        if "Roughness" in bsdf.inputs:
            nt.links.new(rr.outputs["Result"], bsdf.inputs["Roughness"])
    except Exception:
        bsdf.inputs["Base Color"].default_value = (tint[0], tint[1], tint[2], 1.0)
        if "Roughness" in bsdf.inputs:
            bsdf.inputs["Roughness"].default_value = 0.05
    if "Metallic" in bsdf.inputs:
        bsdf.inputs["Metallic"].default_value = 0.0
    _set_spec(bsdf, 0.7)
    return mat


def make_water_material(name, tint=WATER_COLOR):
    """Realistic dark, smooth water with sky reflections and subtle ripples
    generated with noise bump. It appears mirrored blue in canals and docks."""
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    bsdf = nt.nodes.get("Principled BSDF")
    if not bsdf:
        return mat
    bsdf.inputs["Base Color"].default_value = (tint[0], tint[1], tint[2], 1.0)
    if "Roughness" in bsdf.inputs:
        bsdf.inputs["Roughness"].default_value = 0.05
    if "Metallic" in bsdf.inputs:
        bsdf.inputs["Metallic"].default_value = 0.0
    _set_spec(bsdf, 0.7)
    try:
        noise = nt.nodes.new("ShaderNodeTexNoise")
        bump = nt.nodes.new("ShaderNodeBump")
        geom = nt.nodes.new("ShaderNodeNewGeometry")
        mapping = nt.nodes.new("ShaderNodeMapping")
        mapping.inputs["Scale"].default_value = (0.35, 0.35, 0.35)
        nt.links.new(geom.outputs["Position"], mapping.inputs["Vector"])
        nt.links.new(mapping.outputs["Vector"], noise.inputs["Vector"])
        if "Scale" in noise.inputs:
            noise.inputs["Scale"].default_value = 2.5
        if "Detail" in noise.inputs:
            noise.inputs["Detail"].default_value = 3.0
        nt.links.new(noise.outputs["Fac"], bump.inputs["Height"])
        bump.inputs["Strength"].default_value = 0.10
        nt.links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])
    except Exception:
        pass
    return mat


def make_foliage_material(name, base=(0.18, 0.29, 0.14)):
    """Create foliage with noise-driven green variation and natural roughness."""
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    bsdf = nt.nodes.get("Principled BSDF")
    if not bsdf:
        return mat
    try:
        geom = nt.nodes.new("ShaderNodeNewGeometry")
        mapping = nt.nodes.new("ShaderNodeMapping")
        mapping.inputs["Scale"].default_value = (0.5, 0.5, 0.5)
        noise = nt.nodes.new("ShaderNodeTexNoise")
        if "Scale" in noise.inputs:
            noise.inputs["Scale"].default_value = 3.5
        if "Detail" in noise.inputs:
            noise.inputs["Detail"].default_value = 6.0
        ramp = nt.nodes.new("ShaderNodeValToRGB")
        e = ramp.color_ramp.elements
        e[0].position = 0.35
        e[0].color = (base[0] * 0.55, base[1] * 0.6, base[2] * 0.5, 1.0)
        e[1].position = 0.78
        e[1].color = (min(1, base[0] * 1.6 + 0.05), min(1, base[1] * 1.4 + 0.07),
                      min(1, base[2] * 1.2 + 0.02), 1.0)
        nt.links.new(geom.outputs["Position"], mapping.inputs["Vector"])
        nt.links.new(mapping.outputs["Vector"], noise.inputs["Vector"])
        nt.links.new(noise.outputs["Fac"], ramp.inputs["Fac"])
        nt.links.new(ramp.outputs["Color"], bsdf.inputs["Base Color"])
        # Subtle foliage bump breaks up the flat sheen.
        # No alpha here: gaps exposed the dark interior and looked mottled.
        fnoise = nt.nodes.new("ShaderNodeTexNoise")
        if "Scale" in fnoise.inputs:
            fnoise.inputs["Scale"].default_value = 9.0
        if "Detail" in fnoise.inputs:
            fnoise.inputs["Detail"].default_value = 6.0
        fbump = nt.nodes.new("ShaderNodeBump")
        fbump.inputs["Strength"].default_value = 0.18
        nt.links.new(mapping.outputs["Vector"], fnoise.inputs["Vector"])
        nt.links.new(fnoise.outputs["Fac"], fbump.inputs["Height"])
        nt.links.new(fbump.outputs["Normal"], bsdf.inputs["Normal"])
    except Exception:
        bsdf.inputs["Base Color"].default_value = (base[0], base[1], base[2], 1.0)
    if "Roughness" in bsdf.inputs:
        bsdf.inputs["Roughness"].default_value = 0.5   # brillo ceroso de hoja
    # Translucency lets some light pass through leaves for a backlit glow.
    # Missing translucency is the clearest source of a plastic foliage look.
    if "Subsurface Weight" in bsdf.inputs:
        bsdf.inputs["Subsurface Weight"].default_value = 0.18
        if "Subsurface Radius" in bsdf.inputs:
            bsdf.inputs["Subsurface Radius"].default_value = (0.30, 0.55, 0.20)
    return mat


def make_leafcard_material(name, base=(0.20, 0.30, 0.15)):
    """Create leaf-card foliage with green variation, irregular alpha gaps,
    sky gaps, broken silhouette, and translucency for the canopy card shell."""
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    bsdf = nt.nodes.get("Principled BSDF")
    if not bsdf:
        return mat
    try:
        geom = nt.nodes.new("ShaderNodeNewGeometry")
        mapping = nt.nodes.new("ShaderNodeMapping")
        mapping.inputs["Scale"].default_value = (0.6, 0.6, 0.6)
        noise = nt.nodes.new("ShaderNodeTexNoise")
        if "Scale" in noise.inputs:
            noise.inputs["Scale"].default_value = 4.0
        if "Detail" in noise.inputs:
            noise.inputs["Detail"].default_value = 6.0
        ramp = nt.nodes.new("ShaderNodeValToRGB")
        e = ramp.color_ramp.elements
        e[0].position = 0.35
        e[0].color = (base[0] * 0.5, base[1] * 0.55, base[2] * 0.45, 1.0)
        e[1].position = 0.80
        e[1].color = (min(1, base[0] * 1.7 + 0.06), min(1, base[1] * 1.4 + 0.08),
                      min(1, base[2] * 1.2 + 0.02), 1.0)
        nt.links.new(geom.outputs["Position"], mapping.inputs["Vector"])
        nt.links.new(mapping.outputs["Vector"], noise.inputs["Vector"])
        nt.links.new(noise.outputs["Fac"], ramp.inputs["Fac"])
        nt.links.new(ramp.outputs["Color"], bsdf.inputs["Base Color"])
        # Irregular alpha breaks the silhouette and reveals sky between leaves.
        anoise = nt.nodes.new("ShaderNodeTexNoise")
        if "Scale" in anoise.inputs:
            anoise.inputs["Scale"].default_value = 7.0
        if "Detail" in anoise.inputs:
            anoise.inputs["Detail"].default_value = 8.0
        aramp = nt.nodes.new("ShaderNodeValToRGB")
        ae = aramp.color_ramp.elements
        ae[0].position = 0.44
        ae[0].color = (0.0, 0.0, 0.0, 1.0)
        ae[1].position = 0.56
        ae[1].color = (1.0, 1.0, 1.0, 1.0)
        nt.links.new(mapping.outputs["Vector"], anoise.inputs["Vector"])
        nt.links.new(anoise.outputs["Fac"], aramp.inputs["Fac"])
        if "Alpha" in bsdf.inputs:
            nt.links.new(aramp.outputs["Color"], bsdf.inputs["Alpha"])
    except Exception:
        bsdf.inputs["Base Color"].default_value = (base[0], base[1], base[2], 1.0)
    if "Roughness" in bsdf.inputs:
        bsdf.inputs["Roughness"].default_value = 0.55
    if "Subsurface Weight" in bsdf.inputs:
        bsdf.inputs["Subsurface Weight"].default_value = 0.2
        if "Subsurface Radius" in bsdf.inputs:
            bsdf.inputs["Subsurface Radius"].default_value = (0.30, 0.55, 0.20)
    return mat


def make_asphalt_material(name, base=ASPHALT_COLOR):
    """Procedural asphalt with color variation, tar patches, and fine grain
    bump detail, and variable roughness instead of uniform plastic gray."""
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    bsdf = nt.nodes.get("Principled BSDF")
    if not bsdf:
        return mat
    try:
        geo = nt.nodes.new("ShaderNodeNewGeometry")
        mp = nt.nodes.new("ShaderNodeMapping")
        mp.inputs["Scale"].default_value = (0.25, 0.25, 0.25)
        n1 = nt.nodes.new("ShaderNodeTexNoise")
        for k, v in (("Scale", 1.4), ("Detail", 4.0)):
            if k in n1.inputs:
                n1.inputs[k].default_value = v
        ramp = nt.nodes.new("ShaderNodeValToRGB")
        e = ramp.color_ramp.elements
        e[0].position = 0.30
        e[0].color = (base[0] * 0.55, base[1] * 0.55, base[2] * 0.55, 1.0)
        e[1].position = 0.75
        e[1].color = (min(1, base[0] * 1.35 + 0.01), min(1, base[1] * 1.35 + 0.01),
                      min(1, base[2] * 1.35 + 0.02), 1.0)
        n2 = nt.nodes.new("ShaderNodeTexNoise")
        for k, v in (("Scale", 45.0), ("Detail", 6.0)):
            if k in n2.inputs:
                n2.inputs[k].default_value = v
        bump = nt.nodes.new("ShaderNodeBump")
        bump.inputs["Strength"].default_value = 0.14
        rr = nt.nodes.new("ShaderNodeMapRange")
        rr.inputs["To Min"].default_value = 0.72
        rr.inputs["To Max"].default_value = 0.95
        nt.links.new(geo.outputs["Position"], mp.inputs["Vector"])
        nt.links.new(mp.outputs["Vector"], n1.inputs["Vector"])
        nt.links.new(mp.outputs["Vector"], n2.inputs["Vector"])
        nt.links.new(n1.outputs["Fac"], ramp.inputs["Fac"])
        nt.links.new(ramp.outputs["Color"], bsdf.inputs["Base Color"])
        nt.links.new(n2.outputs["Fac"], bump.inputs["Height"])
        nt.links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])
        nt.links.new(n1.outputs["Fac"], rr.inputs["Value"])
        if "Roughness" in bsdf.inputs:
            nt.links.new(rr.outputs["Result"], bsdf.inputs["Roughness"])
    except Exception:
        bsdf.inputs["Base Color"].default_value = (base[0], base[1], base[2], 1.0)
        if "Roughness" in bsdf.inputs:
            bsdf.inputs["Roughness"].default_value = 0.85
    _set_spec(bsdf, 0.2)
    return mat


def make_concrete_material(name, base=SIDEWALK_COLOR):
    """Procedural concrete with Voronoi panels, bump grain, and color variation."""
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    bsdf = nt.nodes.get("Principled BSDF")
    if not bsdf:
        return mat
    try:
        geo = nt.nodes.new("ShaderNodeNewGeometry")
        mp = nt.nodes.new("ShaderNodeMapping")
        mp.inputs["Scale"].default_value = (0.18, 0.18, 0.18)
        vor = nt.nodes.new("ShaderNodeTexVoronoi")
        if "Scale" in vor.inputs:
            vor.inputs["Scale"].default_value = 0.5
        ng = nt.nodes.new("ShaderNodeTexNoise")
        for k, v in (("Scale", 8.0), ("Detail", 5.0)):
            if k in ng.inputs:
                ng.inputs[k].default_value = v
        mixn, f_in, cA, cB, out = _mix_rgb_node(nt)
        cA.default_value = (base[0] * 0.82, base[1] * 0.82, base[2] * 0.8, 1.0)
        cB.default_value = (min(1, base[0] * 1.1), min(1, base[1] * 1.1),
                            min(1, base[2] * 1.1), 1.0)
        bump = nt.nodes.new("ShaderNodeBump")
        bump.inputs["Strength"].default_value = 0.06
        nt.links.new(geo.outputs["Position"], mp.inputs["Vector"])
        nt.links.new(mp.outputs["Vector"], vor.inputs["Vector"])
        nt.links.new(mp.outputs["Vector"], ng.inputs["Vector"])
        vout = vor.outputs.get("Distance") or vor.outputs[0]
        nt.links.new(vout, f_in)
        nt.links.new(out, bsdf.inputs["Base Color"])
        nt.links.new(ng.outputs["Fac"], bump.inputs["Height"])
        nt.links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])
    except Exception:
        bsdf.inputs["Base Color"].default_value = (base[0], base[1], base[2], 1.0)
    if "Roughness" in bsdf.inputs:
        bsdf.inputs["Roughness"].default_value = 0.9
    _set_spec(bsdf, 0.1)
    return mat


def apply_street_view_settings(scn=None):
    """Apply photographic AgX tone mapping to street-level physical-sky views."""
    scn = scn or bpy.context.scene
    vs = scn.view_settings
    for vt in ("AgX", "Filmic", "Standard"):
        try:
            vs.view_transform = vt
            break
        except TypeError:
            continue
    for lk in STREET_LOOKS:
        try:
            vs.look = lk
            break
        except TypeError:
            continue
    try:
        vs.exposure = STREET_EXPOSURE_HDRI if using_hdri() else STREET_EXPOSURE
    except Exception:
        pass


def setup_compositor(scn=None, haze_color=(0.60, 0.70, 0.84), haze_start=70.0,
                     haze_end=700.0, haze_strength=0.55, vignette=0.20):
    """Apply compositor haze from depth plus a subtle vignette for photographic
    distant towers and trees fade into blue instead of ending abruptly."""
    scn = scn or bpy.context.scene
    try:
        scn.use_nodes = True
        nt = scn.node_tree
        for n in list(nt.nodes):
            nt.nodes.remove(n)
        rl = nt.nodes.new("CompositorNodeRLayers")
        comp = nt.nodes.new("CompositorNodeComposite")
        last = rl.outputs["Image"]
        depth = rl.outputs.get("Depth") or rl.outputs.get("Z")
        if depth is not None and haze_strength > 0:
            mr = nt.nodes.new("CompositorNodeMapRange")
            mr.inputs["From Min"].default_value = haze_start
            mr.inputs["From Max"].default_value = haze_end
            mr.inputs["To Min"].default_value = 0.0
            mr.inputs["To Max"].default_value = haze_strength
            try:
                mr.use_clamp = True
            except Exception:
                pass
            nt.links.new(depth, mr.inputs["Value"])
            # Exclude the sky from haze. Its huge depth would otherwise cover the
            # HDRI with flat gray. Mask geometry as 1 and the distant sky as 0.
            skym = nt.nodes.new("CompositorNodeMapRange")
            skym.inputs["From Min"].default_value = haze_end * 2.5
            skym.inputs["From Max"].default_value = haze_end * 4.0
            skym.inputs["To Min"].default_value = 1.0
            skym.inputs["To Max"].default_value = 0.0
            try:
                skym.use_clamp = True
            except Exception:
                pass
            nt.links.new(depth, skym.inputs["Value"])
            hfac = nt.nodes.new("CompositorNodeMath")
            hfac.operation = "MULTIPLY"
            nt.links.new(mr.outputs["Value"], hfac.inputs[0])
            nt.links.new(skym.outputs["Value"], hfac.inputs[1])
            mix = nt.nodes.new("CompositorNodeMixRGB")
            mix.blend_type = "MIX"
            mix.inputs[2].default_value = (haze_color[0], haze_color[1], haze_color[2], 1.0)
            nt.links.new(hfac.outputs["Value"], mix.inputs[0])
            nt.links.new(last, mix.inputs[1])
            last = mix.outputs["Image"]
        if vignette > 0:
            mask = nt.nodes.new("CompositorNodeEllipseMask")
            try:
                mask.width = 1.15
                mask.height = 1.15
            except Exception:
                pass
            blur = nt.nodes.new("CompositorNodeBlur")
            try:
                blur.size_x = 160
                blur.size_y = 160
                blur.use_relative = False
            except Exception:
                pass
            nt.links.new(mask.outputs[0], blur.inputs["Image"])
            vmix = nt.nodes.new("CompositorNodeMixRGB")
            vmix.blend_type = "MULTIPLY"
            vmix.inputs[0].default_value = vignette
            nt.links.new(last, vmix.inputs[1])
            nt.links.new(blur.outputs["Image"], vmix.inputs[2])
            last = vmix.outputs["Image"]
        # Subtle bloom on bright glass and sky highlights adds a photographic feel.
        try:
            glare = nt.nodes.new("CompositorNodeGlare")
            for gt in ("BLOOM", "FOG_GLOW"):
                try:
                    glare.glare_type = gt
                    break
                except Exception:
                    continue
            try:
                glare.mix = -0.72
            except Exception:
                pass
            try:
                glare.threshold = 1.0
            except Exception:
                pass
            nt.links.new(last, glare.inputs["Image"])
            last = glare.outputs["Image"]
        except Exception:
            pass
        nt.links.new(last, comp.inputs["Image"])
    except Exception:
        try:
            for n in list(nt.nodes):
                nt.nodes.remove(n)
            rl = nt.nodes.new("CompositorNodeRLayers")
            comp = nt.nodes.new("CompositorNodeComposite")
            nt.links.new(rl.outputs["Image"], comp.inputs["Image"])
        except Exception:
            scn.use_nodes = False


def make_textured_material(name, image_path, tile_m=4.0, roughness=0.9):
    """Create an image-textured material tiled at real scale in world space."""
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    bsdf = nt.nodes.get("Principled BSDF")
    if not bsdf:
        return mat
    try:
        img = bpy.data.images.load(image_path, check_existing=True)
        tex = nt.nodes.new("ShaderNodeTexImage")
        tex.image = img
        tex.extension = "REPEAT"
        geom = nt.nodes.new("ShaderNodeNewGeometry")
        mapping = nt.nodes.new("ShaderNodeMapping")
        s = 1.0 / max(0.5, tile_m)
        mapping.inputs["Scale"].default_value = (s, s, s)
        nt.links.new(geom.outputs["Position"], mapping.inputs["Vector"])
        nt.links.new(mapping.outputs["Vector"], tex.inputs["Vector"])
        nt.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
        if "Roughness" in bsdf.inputs:
            bsdf.inputs["Roughness"].default_value = roughness
    except Exception:
        bsdf.inputs["Base Color"].default_value = (0.5, 0.5, 0.5, 1.0)
    return mat


def make_pbr_material(name, base, tile_m=6.0, rough_boost=1.0):
    """Create a real-scale PBR material from CC0 diffuse/roughness/normal maps.

    Return None when maps are unavailable so callers can use procedural material.
    """
    ts = _texset(base)
    if not ts:
        return None
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    bsdf = nt.nodes.get("Principled BSDF")
    if not bsdf:
        return mat
    try:
        geo = nt.nodes.new("ShaderNodeNewGeometry")
        mp = nt.nodes.new("ShaderNodeMapping")
        s = 1.0 / max(0.25, tile_m)
        mp.inputs["Scale"].default_value = (s, s, s)
        nt.links.new(geo.outputs["Position"], mp.inputs["Vector"])

        def img(path, colorspace):
            t = nt.nodes.new("ShaderNodeTexImage")
            t.image = bpy.data.images.load(path, check_existing=True)
            t.extension = "REPEAT"
            try:
                t.image.colorspace_settings.name = colorspace
            except Exception:
                pass
            nt.links.new(mp.outputs["Vector"], t.inputs["Vector"])
            return t

        d = img(ts["diff"], "sRGB")
        nt.links.new(d.outputs["Color"], bsdf.inputs["Base Color"])
        if ts.get("rough") and "Roughness" in bsdf.inputs:
            r = img(ts["rough"], "Non-Color")
            if rough_boost != 1.0:
                mul = nt.nodes.new("ShaderNodeMath")
                mul.operation = "MULTIPLY"
                mul.inputs[1].default_value = rough_boost
                nt.links.new(r.outputs["Color"], mul.inputs[0])
                nt.links.new(mul.outputs["Value"], bsdf.inputs["Roughness"])
            else:
                nt.links.new(r.outputs["Color"], bsdf.inputs["Roughness"])
        if ts.get("nor"):
            n = img(ts["nor"], "Non-Color")
            nmap = nt.nodes.new("ShaderNodeNormalMap")
            nt.links.new(n.outputs["Color"], nmap.inputs["Color"])
            nt.links.new(nmap.outputs["Normal"], bsdf.inputs["Normal"])
    except Exception:
        bsdf.inputs["Base Color"].default_value = (0.5, 0.5, 0.5, 1.0)
    return mat


def bm_to_object(bm, name, mat, coll=None, merge=0.01, smooth=False,
                 recalc_normals=True):
    """Convert a bmesh into an object, cleaning geometry and merging vertices
    by merging duplicates and recalculating normals, then link it to ``coll``
    (or the master collection when None). ``smooth=True`` applies smooth shading
    without adding polygons.
    """
    if merge and len(bm.verts) > 0:
        try:
            bmesh.ops.remove_doubles(bm, verts=list(bm.verts), dist=merge)
        except Exception:
            pass
    if recalc_normals:
        try:
            bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
        except Exception:
            pass
    me = bpy.data.meshes.new(name)
    bm.normal_update()
    bm.to_mesh(me)
    bm.free()
    if smooth:
        for p in me.polygons:
            p.use_smooth = True
    ob = bpy.data.objects.new(name, me)
    if mat:
        ob.data.materials.append(mat)
    (coll or bpy.context.scene.collection).objects.link(ob)
    return ob


# Collection names from the world-to-blender specification.
COLLECTION_NAMES = [
    "00_REFERENCE", "01_TERRAIN", "02_BUILDINGS", "03_ROADS", "04_SIDEWALKS",
    "05_VEGETATION", "06_WATER", "07_LANDMARKS", "08_BRIDGES", "09_RAILWAYS",
    "10_STREET_FURNITURE", "11_LIGHTING", "12_CAMERAS", "13_EXPORT",
    "14_SPECIAL_INFRA",
]


def clear_scene():
    """Clear objects and data without resetting Blender or unregistering MCP.

    Always use this function in a live Blender MCP session.
    """
    for ob in list(bpy.data.objects):
        try:
            bpy.data.objects.remove(ob, do_unlink=True)
        except Exception:
            pass
    for coll in list(bpy.data.collections):
        try:
            bpy.data.collections.remove(coll)
        except Exception:
            pass
    for block in (bpy.data.meshes, bpy.data.materials, bpy.data.lights,
                  bpy.data.cameras, bpy.data.images, bpy.data.worlds,
                  bpy.data.curves, bpy.data.node_groups):
        for b in list(block):
            if getattr(b, "users", 0) == 0:
                try:
                    block.remove(b)
                except Exception:
                    pass


def make_collections():
    """Create or return the named specification collections under the scene.
    Return a name-to-Collection dictionary reusable in headless and live MCP modes."""
    master = bpy.context.scene.collection
    existing = {ch.name for ch in master.children}
    out = {}
    for n in COLLECTION_NAMES:
        c = bpy.data.collections.get(n) or bpy.data.collections.new(n)
        if n not in existing:
            try:
                master.children.link(c)
            except Exception:
                pass
        out[n] = c
    return out


def color_key(rgb):
    return (round(rgb[0], 3), round(rgb[1], 3), round(rgb[2], 3))


def _polygon_centroid(poly):
    if not poly:
        return (0.0, 0.0)
    pts = poly[:-1] if len(poly) > 2 and poly[0] == poly[-1] else poly
    return (sum(p[0] for p in pts) / len(pts),
            sum(p[1] for p in pts) / len(pts))


def _add_aircraft_silhouette(bm, cx, cy, heading_deg=0.0, scale=1.0):
    """Add a lightweight aircraft proxy so an apron does not remain empty.

    It is deliberately procedural: it adds airport scale and readability without
    claiming to represent an aircraft observed at that location.
    """
    shape = [
        (-18, 0), (-6, -1.5), (-2.0, -13), (2.0, -13), (4.5, -2.0),
        (15, -1.2), (18, 0), (15, 1.2), (4.5, 2.0), (2.0, 13),
        (-2.0, 13), (-6, 1.5),
    ]
    a = math.radians(heading_deg)
    ca, sa = math.cos(a), math.sin(a)
    poly = []
    for x, y in shape:
        x *= scale
        y *= scale
        poly.append((cx + x * ca - y * sa, cy + x * sa + y * ca))
    add_prism(bm, poly, 0.22, 0.95)


def build_special_features(scene, collections):
    """Build OSM infrastructure that requires its own semantics.

    Currently covers ``aeroway`` with appropriate materials, widths, and marks.
    Return a summary for diagnostics and one-shot reports.
    """
    features = scene.get("special_features", [])
    if not features:
        return {"features": 0, "aircraft": 0}

    runway_bm, taxi_bm = bmesh.new(), bmesh.new()
    white_bm, yellow_bm = bmesh.new(), bmesh.new()
    apron_bm, helipad_bm = bmesh.new(), bmesh.new()
    landmark_bm = bmesh.new()
    aprons = []
    landmark_count = 0
    for feature in features:
        kind = str(feature.get("kind", ""))
        geometry = feature.get("geometry")
        z = float(feature.get("z", 0.09))
        if geometry == "line" and len(feature.get("path", [])) >= 2:
            path = feature["path"]
            width = float(feature.get("width", 45.0 if kind == "runway" else 18.0))
            if kind == "runway":
                add_road_strip(runway_bm, path, width, z)
                add_lane_markings(white_bm, path, width, z, dash=18.0,
                                  gap=12.0, mw=max(0.35, width * 0.012))
            elif kind == "taxiway":
                add_road_strip(taxi_bm, path, width, z)
                add_lane_markings(yellow_bm, path, width, z, dash=1000.0,
                                  gap=0.0, mw=max(0.16, width * 0.012))
        elif geometry == "surface" and len(feature.get("polygon", [])) >= 3:
            if kind == "apron":
                add_flat_polygon(apron_bm, feature["polygon"], z)
                aprons.append(feature["polygon"])
            elif kind == "helipad":
                add_flat_polygon(helipad_bm, feature["polygon"], z)
        elif geometry == "point" and feature.get("family") == "landmark":
            x, y = feature.get("point", (0.0, 0.0))
            height = max(3.0, float(feature.get("height", 25.0)))
            width = max(1.2, float(feature.get("width", 6.0)))
            half = width * 0.5
            footprint = [(x-half, y-half), (x+half, y-half),
                         (x+half, y+half), (x-half, y+half)]
            add_spire(landmark_bm, footprint, 0.0, height)
            landmark_count += 1

    coll = collections["14_SPECIAL_INFRA"]
    if len(apron_bm.faces):
        bm_to_object(apron_bm, "Airport_aprons",
                     make_concrete_material("airport_apron", (0.42, 0.44, 0.45)),
                     coll=coll, merge=0.0, recalc_normals=False)
    else:
        apron_bm.free()
    if len(helipad_bm.faces):
        bm_to_object(helipad_bm, "Airport_helipads",
                     make_concrete_material("airport_helipad", (0.48, 0.50, 0.51)),
                     coll=coll, merge=0.0, recalc_normals=False)
    else:
        helipad_bm.free()
    if len(runway_bm.faces):
        bm_to_object(runway_bm, "Airport_runways",
                     make_asphalt_material("airport_runway"), coll=coll)
    else:
        runway_bm.free()
    if len(taxi_bm.faces):
        bm_to_object(taxi_bm, "Airport_taxiways",
                     make_asphalt_material("airport_taxiway", (0.12, 0.125, 0.135)),
                     coll=coll)
    else:
        taxi_bm.free()
    if len(white_bm.faces):
        bm_to_object(white_bm, "Airport_runway_markings",
                     make_material("runway_white", (0.94, 0.95, 0.96),
                                   roughness=0.65), coll=coll, merge=0.0)
    else:
        white_bm.free()
    if len(yellow_bm.faces):
        bm_to_object(yellow_bm, "Airport_taxiway_centerlines",
                     make_material("taxi_yellow", (0.95, 0.58, 0.035),
                                   roughness=0.65), coll=coll, merge=0.0)
    else:
        yellow_bm.free()

    if len(landmark_bm.faces):
        bm_to_object(landmark_bm, "OSM_landmarks",
                     make_material("landmark_stone", (0.79, 0.78, 0.74),
                                   roughness=0.62, specular=0.22),
                     coll=collections["07_LANDMARKS"], merge=0.0)
    else:
        landmark_bm.free()

    aircraft_bm = bmesh.new()
    for idx, polygon in enumerate(aprons[:8]):
        x, y = _polygon_centroid(polygon)
        _add_aircraft_silhouette(aircraft_bm, x, y,
                                 heading_deg=(idx * 47 + 20) % 360,
                                 scale=0.82 + 0.07 * (idx % 4))
    aircraft_count = min(8, len(aprons))
    if len(aircraft_bm.faces):
        bm_to_object(aircraft_bm, "Airport_aircraft_proxies",
                     make_material("aircraft_white", (0.88, 0.91, 0.93),
                                   roughness=0.48, metallic=0.06), coll=coll)
    else:
        aircraft_bm.free()
    return {"features": len(features), "aircraft": aircraft_count,
            "landmarks": landmark_count}


# ---------------------------------------------------------------------------
# Scene construction
# ---------------------------------------------------------------------------

def build_scene(scene):
    buildings = scene.get("buildings", [])
    roads = scene.get("roads", [])
    areas = scene.get("areas", [])
    roof_bias = (scene.get("profile_defaults") or {}).get("roof_bias")  # profile bias
    C = make_collections()

    # --- Buildings: color-grouped walls plus pitched or flat roofs ---
    def _bevel(bm):
        if BEVEL > 0:
            try:
                bmesh.ops.bevel(bm, geom=list(bm.edges) + list(bm.verts),
                                offset=BEVEL, segments=1, affect="EDGES",
                                clamp_overlap=True)
            except Exception:
                pass

    # Classify high-rises as reflective curtain walls, remaining buildings as
    # windowed masonry, and vertical landmarks as spires.
    glass_groups = {}    # tint_idx -> [b]
    masonry_groups = {}  # color_key -> [b]
    spires = []
    for b in buildings:
        base = float(b.get("min_height", 0.0))
        top = float(b["height"])
        if b.get("type") in LANDMARK_TYPES:
            spires.append(b)
        elif (top - base) >= MODERN_MIN_HEIGHT:
            fp = b["footprint"][0]  # stable glass tint by position
            idx = int(abs(round(fp[0] * 3.1 + fp[1] * 5.7))) % len(GLASS_TINTS)
            glass_groups.setdefault(idx, []).append(b)
        else:
            masonry_groups.setdefault(color_key(b["color"]), []).append(b)

    roof_house_bm = bmesh.new()  # tiled roofs for low-rise buildings
    roof_flat_bm = bmesh.new()   # flat-roof detail for towers

    # Torres de vidrio
    for idx, items in glass_groups.items():
        bm = bmesh.new()
        for b in items:
            base = float(b.get("min_height", 0.0))
            top = float(b["height"])
            add_prism(bm, b["footprint"], base, top)
            fp0 = b["footprint"][0]
            kind = choose_roof_kind(b.get("roof_shape"), top - base,
                                    fp0[0] * 1.3 + fp0[1] * 2.7, bias=roof_bias)
            build_roof(kind, b["footprint"], top, roof_house_bm, roof_flat_bm)
        _bevel(bm)
        bm_to_object(bm, f"Glass_tower_{idx}",
                     make_glass_material(f"glass_{idx}", GLASS_TINTS[idx]),
                     coll=C["02_BUILDINGS"])

    # Windowed masonry façades and roofs.
    for i, (k, items) in enumerate(masonry_groups.items()):
        bm = bmesh.new()
        for b in items:
            base = float(b.get("min_height", 0.0))
            top = float(b["height"])
            add_prism(bm, b["footprint"], base, top)
            fp0 = b["footprint"][0]
            kind = choose_roof_kind(b.get("roof_shape"), top - base,
                                    fp0[0] * 1.3 + fp0[1] * 2.7, bias=roof_bias)
            build_roof(kind, b["footprint"], top, roof_house_bm, roof_flat_bm)
        _bevel(bm)
        bm_to_object(bm, f"Building_{i}", make_windowed_material(f"bld_{i}", k),
                     coll=C["02_BUILDINGS"])

    C = make_collections()

    # Landmarks verticales (obeliscos/agujas): piedra clara -> 07
    if spires:
        bm = bmesh.new()
        for b in spires:
            add_spire(bm, b["footprint"], float(b.get("min_height", 0.0)),
                      float(b["height"]))
        bm_to_object(bm, "Landmark_spires",
                     make_material("landmark", (0.86, 0.84, 0.80),
                                   roughness=0.6, specular=0.2),
                     coll=C["07_LANDMARKS"])
    if len(roof_house_bm.faces) > 0:
        bm_to_object(roof_house_bm, "Tiled_roofs",
                     make_material("roof_tile", ROOF_HOUSE_COLOR, roughness=0.7, specular=0.15),
                     coll=C["02_BUILDINGS"])
    else:
        roof_house_bm.free()
    if len(roof_flat_bm.faces) > 0:
        bm_to_object(roof_flat_bm, "Flat_roofs",
                     make_material("flat_roof", ROOF_FLAT_COLOR, roughness=0.85, specular=0.1),
                     coll=C["02_BUILDINGS"])
    else:
        roof_flat_bm.free()

    # --- Water areas (-> 06) and green areas (-> 05) ---
    area_groups = {}
    for a in areas:
        k = color_key(a["color"])
        area_groups.setdefault(k, []).append(a)
    for i, (k, items) in enumerate(area_groups.items()):
        bm = bmesh.new()
        for a in items:
            add_flat_polygon(bm, a["polygon"], float(a.get("z", 0.03)))
        is_water = k[2] > k[1]  # azulado
        if is_water:
            bm_to_object(bm, f"Water_{i}", make_water_material(f"water_{i}"),
                         coll=C["06_WATER"], merge=0.0)
        else:
            bm_to_object(bm, f"Green_{i}",
                         make_material(f"green_{i}", k, roughness=0.9, specular=0.1),
                         coll=C["05_VEGETATION"], merge=0.0)

    # --- Roads and markings -> 03, sidewalks -> 04, railways -> 09, bridges -> 08 ---
    veh_bm = bmesh.new()      # calzada asfaltada
    mark_bm = bmesh.new()     # white center markings
    side_bm = bmesh.new()     # concrete sidewalks
    ped_groups = {}           # peatonal / footway
    rail_groups = {}          # vias de tren
    bridge_items = []         # puentes elevados
    for r in roads:
        k = color_key(r["color"])
        z = float(r.get("z", 0.06))
        p0 = r["path"][0]
        jitter = 0.001 * (int(abs(p0[0] * 5.1 + p0[1] * 9.7)) % 40)
        width = float(r["width"])
        rtype = str(r.get("type", ""))
        if z > 1.0:
            bridge_items.append((r, z + jitter))
            continue
        if rtype.startswith("rail"):
            rail_groups.setdefault(k, []).append((r, z + jitter))
            continue
        greyish = (max(k) - min(k) < 0.06 and sum(k) / 3 < 0.4)
        if greyish and width >= 4.5:   # vehicular
            add_road_strip(veh_bm, r["path"], width, z + jitter)
            if width >= 7.0:
                add_lane_markings(mark_bm, r["path"], width, z + jitter)
                add_sidewalks(side_bm, r["path"], width, 0.05)
        else:                           # pedestrian path, sidewalk, or cycleway
            ped_groups.setdefault(k, []).append((r, z + jitter))
    if len(side_bm.faces) > 0:
        bm_to_object(side_bm, "Sidewalks",
                     make_pbr_material("sidewalk", "concrete", tile_m=4.0)
                     or make_concrete_material("sidewalk", SIDEWALK_COLOR),
                     coll=C["04_SIDEWALKS"], smooth=False)
    else:
        side_bm.free()
    if len(veh_bm.faces) > 0:
        bm_to_object(veh_bm, "Roadway",
                     make_pbr_material("asphalt", "asphalt", tile_m=8.0)
                     or make_asphalt_material("asphalt"),
                     coll=C["03_ROADS"])
    else:
        veh_bm.free()
    if len(mark_bm.faces) > 0:
        bm_to_object(mark_bm, "Road_markings",
                     make_material("road_markings", MARKING_COLOR, roughness=0.7, specular=0.1),
                     coll=C["03_ROADS"])
    else:
        mark_bm.free()
    for i, (k, items) in enumerate(ped_groups.items()):
        bm = bmesh.new()
        for r, zz in items:
            add_road_strip(bm, r["path"], float(r["width"]), zz)
        bm_to_object(bm, f"Pedestrian_{i}",
                     make_material(f"pedestrian_{i}", k, roughness=0.9, specular=0.06),
                     coll=C["04_SIDEWALKS"])
    for i, (k, items) in enumerate(rail_groups.items()):
        bm = bmesh.new()
        for r, zz in items:
            add_road_strip(bm, r["path"], float(r["width"]), zz)
        bm_to_object(bm, f"Railways_{i}",
                     make_material(f"railway_{i}", k, roughness=0.85, specular=0.1),
                     coll=C["09_RAILWAYS"])
    if bridge_items:
        bm = bmesh.new()
        for r, zz in bridge_items:
            add_road_strip(bm, r["path"], float(r["width"]), zz)
            add_bridge_piers(bm, r["path"], zz)
        bm_to_object(bm, "Bridges",
                     make_material("bridge", BRIDGE_MAT_COLOR, roughness=0.8, specular=0.1),
                     coll=C["08_BRIDGES"])

    # --- Infraestructura especial (aeropuertos, etc.) -> 14 ---
    special_summary = build_special_features(scene, C)

    # --- Trees in plazas and along avenues -> 05 ---
    # Do not scatter trees on airport grass or meadows beside runways.
    tree_areas = areas
    if scene.get("scene_kind") == "airport":
        tree_areas = [a for a in areas if str(a.get("type", "")) in
                      ("park", "garden", "forest", "wood", "scrub")]
    trunk_bm, fol_bm, cards_bm, ntrees = scatter_trees(tree_areas, roads)
    if len(trunk_bm.faces) > 0:
        bm_to_object(trunk_bm, "Trunks",
                     make_pbr_material("bark", "bark", tile_m=2.2)
                     or make_material("trunk", (0.34, 0.23, 0.15), roughness=0.95),
                     coll=C["05_VEGETATION"])
    else:
        trunk_bm.free()
    if len(fol_bm.faces) > 0:
        bm_to_object(fol_bm, "Copas_nucleo", make_foliage_material("copa"),
                     coll=C["05_VEGETATION"], smooth=True)
    else:
        fol_bm.free()
    if len(cards_bm.faces) > 0:
        bm_to_object(cards_bm, "Hojas", make_leafcard_material("hojas"),
                     coll=C["05_VEGETATION"], merge=0.0)
    else:
        cards_bm.free()

    # --- Farolas -> 10 (street furniture) ---
    lamp_bm = scatter_streetlights(roads)
    if lamp_bm and len(lamp_bm.faces) > 0:
        bm_to_object(lamp_bm, "Farolas",
                     make_material("farola", (0.22, 0.22, 0.24), roughness=0.5, metallic=0.6),
                     coll=C["10_STREET_FURNITURE"])
    elif lamp_bm:
        lamp_bm.free()

    # --- Parked cars -> 10 (color-grouped bodies plus dark glass and wheels) ---
    car_buckets, car_glass, ncars = scatter_cars(roads)
    for idx, cbm in car_buckets.items():
        if len(cbm.faces) > 0:
            col = CAR_COLORS[idx]
            metal = 0.35 if max(col) > 0.4 else 0.5
            bm_to_object(cbm, f"Autos_carroceria_{idx}",
                         make_material(f"auto_{idx}", col, roughness=0.30,
                                       metallic=metal, specular=0.6, coat=1.0),
                         coll=C["10_STREET_FURNITURE"])
        else:
            cbm.free()
    if car_glass and len(car_glass.faces) > 0:
        bm_to_object(car_glass, "Autos_vidrios",
                     make_material("auto_glass", (0.045, 0.05, 0.07),
                                   roughness=0.18, metallic=0.0, specular=0.6),
                     coll=C["10_STREET_FURNITURE"])
    elif car_glass:
        car_glass.free()

    # --- Bounds / centro ---
    bnd = scene.get("bounds", {})
    minx = bnd.get("minx", -scene.get("radius", 250))
    miny = bnd.get("miny", -scene.get("radius", 250))
    maxx = bnd.get("maxx", scene.get("radius", 250))
    maxy = bnd.get("maxy", scene.get("radius", 250))
    cx = (minx + maxx) / 2.0
    cy = (miny + maxy) / 2.0
    R = max(0.5 * max(maxx - minx, maxy - miny), 50.0)

    # --- Terreno -> 01 ---
    margin = R * 0.15
    bm = bmesh.new()
    v1 = bm.verts.new((minx - margin, miny - margin, 0.0))
    v2 = bm.verts.new((maxx + margin, miny - margin, 0.0))
    v3 = bm.verts.new((maxx + margin, maxy + margin, 0.0))
    v4 = bm.verts.new((minx - margin, maxy + margin, 0.0))
    bm.faces.new((v1, v2, v3, v4))
    piso_mat = (make_pbr_material("Terreno", "concrete", tile_m=8.0)
                or make_concrete_material("Terreno", GROUND_COLOR))
    bm_to_object(bm, "Terreno", piso_mat, coll=C["01_TERRAIN"], merge=0.0)

    # --- Requested-area boundary -> 00_REFERENCE ---
    _add_boundary(C["00_REFERENCE"], minx, miny, maxx, maxy)

    try:
        bpy.context.scene["maps3d_scene_kind"] = scene.get("scene_kind", "urban")
        bpy.context.scene["maps3d_special_features"] = special_summary["features"]
        bpy.context.scene["maps3d_aircraft_proxies"] = special_summary["aircraft"]
        bpy.context.scene["maps3d_landmarks"] = special_summary["landmarks"]
    except Exception:
        pass

    return cx, cy, R


# ---------------------------------------------------------------------------
# Lighting, world, camera, and rendering
# ---------------------------------------------------------------------------

def _mix_rgb_node(nt):
    """Create a Blender-version-safe RGB mix node and return its key sockets."""
    try:
        m = nt.nodes.new("ShaderNodeMixRGB")
        return m, m.inputs["Fac"], m.inputs["Color1"], m.inputs["Color2"], m.outputs["Color"]
    except Exception:
        m = nt.nodes.new("ShaderNodeMix")
        try:
            m.data_type = "RGBA"
        except Exception:
            pass
        # ShaderNodeMix uses input 0 for factor and duplicated names for A/B colors.
        col_ins = [s for s in m.inputs if s.type == "RGBA"]
        out = [s for s in m.outputs if s.type == "RGBA"][0]
        return m, m.inputs[0], col_ins[0], col_ins[1], out


def _add_clouds(nt, sky_node):
    """Mix procedural cirrus clouds over the physical sky's upper hemisphere."""
    try:
        geo = nt.nodes.new("ShaderNodeNewGeometry")
        mapping = nt.nodes.new("ShaderNodeMapping")
        mapping.inputs["Scale"].default_value = (2.0, 2.0, 5.0)
        noise = nt.nodes.new("ShaderNodeTexNoise")
        for nm, val in (("Scale", 2.2), ("Detail", 7.0), ("Roughness", 0.72)):
            if nm in noise.inputs:
                noise.inputs[nm].default_value = val
        cmask = nt.nodes.new("ShaderNodeMapRange")
        cmask.inputs["From Min"].default_value = 0.52
        cmask.inputs["From Max"].default_value = 0.72
        hemi = nt.nodes.new("ShaderNodeSeparateXYZ")
        hmax = nt.nodes.new("ShaderNodeMath"); hmax.operation = "MAXIMUM"
        hmax.inputs[1].default_value = 0.0
        hamp = nt.nodes.new("ShaderNodeMath"); hamp.operation = "MULTIPLY"
        hamp.inputs[1].default_value = 5.0
        fac = nt.nodes.new("ShaderNodeMath"); fac.operation = "MULTIPLY"
        m, f_in, cA, cB, out = _mix_rgb_node(nt)
        cB.default_value = (1.25, 1.27, 1.35, 1.0)   # slightly bright cloud
        nt.links.new(geo.outputs["Incoming"], mapping.inputs["Vector"])
        nt.links.new(mapping.outputs["Vector"], noise.inputs["Vector"])
        nt.links.new(noise.outputs["Fac"], cmask.inputs["Value"])
        nt.links.new(geo.outputs["Incoming"], hemi.inputs["Vector"])
        nt.links.new(hemi.outputs["Z"], hmax.inputs[0])
        nt.links.new(hmax.outputs["Value"], hamp.inputs[0])
        nt.links.new(cmask.outputs["Result"], fac.inputs[0])
        nt.links.new(hamp.outputs["Value"], fac.inputs[1])
        nt.links.new(fac.outputs["Value"], f_in)
        nt.links.new(sky_node.outputs[0], cA)
        return out
    except Exception:
        return sky_node.outputs[0]


def setup_world(sky=False, clouds=True):
    """Use a physical sky with clouds when True, or a flat blue sky when False."""
    scn = bpy.context.scene
    world = bpy.data.worlds.new("Sky")
    scn.world = world
    world.use_nodes = True
    nt = world.node_tree
    bg = nt.nodes.get("Background")
    if not bg:
        return
    # 1) A real cloudy HDRI gives the most realistic lighting and reflections.
    if sky and using_hdri():
        try:
            env = nt.nodes.new("ShaderNodeTexEnvironment")
            env.image = bpy.data.images.load(HDRI_PATH, check_existing=True)
            tc = nt.nodes.new("ShaderNodeTexCoord")
            mpp = nt.nodes.new("ShaderNodeMapping")
            try:
                mpp.inputs["Rotation"].default_value = (0.0, 0.0, math.radians(HDRI_ROT_DEG))
            except Exception:
                pass
            nt.links.new(tc.outputs["Generated"], mpp.inputs["Vector"])
            nt.links.new(mpp.outputs["Vector"], env.inputs["Vector"])
            nt.links.new(env.outputs["Color"], bg.inputs[0])
            bg.inputs[1].default_value = 1.0
            return
        except Exception:
            pass
    # 2) Nishita physical sky with procedural clouds.
    if sky:
        try:
            sky_node = nt.nodes.new("ShaderNodeTexSky")
            for stype in ("MULTIPLE_SCATTERING", "NISHITA", "SINGLE_SCATTERING",
                          "HOSEK_WILKIE"):
                try:
                    sky_node.sky_type = stype
                    break
                except TypeError:
                    continue
            for attr, val in (("sun_elevation", math.radians(62)),  # mediodia de verano BA
                              ("sun_rotation", math.radians(150)),
                              ("sun_intensity", 1.0),
                              ("sun_size", math.radians(0.7)),
                              ("altitude", 120.0),
                              ("air_density", 1.0),
                              ("dust_density", 0.4)):
                if hasattr(sky_node, attr):
                    try:
                        setattr(sky_node, attr, val)
                    except Exception:
                        pass
            out = _add_clouds(nt, sky_node) if clouds else sky_node.outputs[0]
            nt.links.new(out, bg.inputs[0])
            bg.inputs[1].default_value = 1.0   # full-strength physical sky
            return
        except Exception:
            pass
    bg.inputs[0].default_value = (0.62, 0.74, 0.92, 1.0)
    bg.inputs[1].default_value = WORLD_STRENGTH


def setup_sun():
    data = bpy.data.lights.new("Sun", "SUN")
    data.energy = SUN_ENERGY
    try:
        data.angle = 0.09  # sombras suaves
    except Exception:
        pass
    sun = bpy.data.objects.new("Sun", data)
    sun.rotation_euler = (math.radians(52), math.radians(6), math.radians(40))
    bpy.context.scene.collection.objects.link(sun)


def setup_camera(cx, cy, R):
    scn = bpy.context.scene
    cam_data = bpy.data.cameras.new("Camera")
    cam = bpy.data.objects.new("Camera", cam_data)
    scn.collection.objects.link(cam)
    scn.camera = cam

    d = R * CAM_DIST_FACTOR
    elev = math.radians(CAM_ELEV_DEG)
    azim = math.radians(CAM_AZIM_DEG)
    cam.location = (
        cx + d * math.cos(elev) * math.sin(azim),
        cy - d * math.cos(elev) * math.cos(azim),
        d * math.sin(elev),
    )
    cam_data.clip_end = d * 5.0
    try:
        cam_data.sensor_fit = "VERTICAL"
    except Exception:
        pass
    cam_data.angle = 2.0 * math.atan((R * CAM_FRAME_FACTOR) / d)

    target = bpy.data.objects.new("Target", None)
    target.location = (cx, cy, min(R * 0.12, 25.0))
    scn.collection.objects.link(target)
    con = cam.constraints.new("TRACK_TO")
    con.target = target
    con.track_axis = "TRACK_NEGATIVE_Z"
    con.up_axis = "UP_Y"


def setup_streetview_camera(heading_deg=0.0, fov_deg=90.0, height=2.5, cx=0.0, cy=0.0):
    """Create a street camera at (cx, cy), facing 0=north or 90=east.

    This supports comparison with Street View at the same position, bearing, and FOV.
    """
    scn = bpy.context.scene
    cam_data = bpy.data.cameras.new("CamCalle")
    cam = bpy.data.objects.new("CamCalle", cam_data)
    scn.collection.objects.link(cam)
    scn.camera = cam
    cam.location = (cx, cy, height)
    # Heading: 0=north (+Y), 90=east (+X). Blender cameras look toward -Z;
    # X rotation points at the horizon and Z rotation changes bearing clockwise.
    cam.rotation_euler = (math.radians(90.0), 0.0, math.radians(-heading_deg))
    cam_data.clip_end = 5000.0
    try:
        cam_data.sensor_fit = "HORIZONTAL"
    except Exception:
        pass
    cam_data.angle = math.radians(fov_deg)
    return cam


def setup_render(render_path):
    scn = bpy.context.scene
    try:
        scn.render.engine = "CYCLES"
        scn.cycles.samples = CYCLES_SAMPLES
        scn.cycles.device = "CPU"
        try:
            scn.cycles.use_denoising = True
            scn.cycles.denoiser = "OPENIMAGEDENOISE"
        except Exception:
            pass
    except Exception:
        selected = None
        for engine in ("BLENDER_EEVEE_NEXT", "BLENDER_EEVEE", "BLENDER_WORKBENCH"):
            try:
                scn.render.engine = engine
                selected = engine
                break
            except Exception:
                pass
        if selected is None:
            raise RuntimeError("No compatible Blender render engine found")
    scn.render.resolution_x = RES_X
    scn.render.resolution_y = RES_Y
    scn.render.resolution_percentage = 100
    scn.render.film_transparent = False
    # Saturated flat colors suit a color-coded 3D map.
    try:
        scn.view_settings.view_transform = "Standard"
        scn.view_settings.exposure = EXPOSURE
    except Exception:
        pass
    scn.render.filepath = render_path


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    scene_path, blend_path, render_path = parse_args()
    with open(scene_path) as f:
        scene = json.load(f)

    # Start with an empty scene and no default cube, camera, or light.
    bpy.ops.wm.read_factory_settings(use_empty=True)

    cx, cy, R = build_scene(scene)
    setup_world(sky=False)
    setup_sun()
    setup_camera(cx, cy, R)
    setup_render(render_path)

    n_obj = len(bpy.data.objects)
    print(f"[blender] scene: {len(scene.get('buildings', []))} buildings, "
          f"{len(scene.get('roads', []))} roads, {len(scene.get('areas', []))} areas, "
          f"{n_obj} objects, radius {R:.0f} m")

    try:
        bpy.ops.wm.save_as_mainfile(filepath=blend_path)
        print(f"[blender] saved: {blend_path}")
    except Exception as e:
        print(f"[blender] could not save .blend: {e}")

    print("[blender] rendering...")
    bpy.ops.render.render(write_still=True)
    print(f"[blender] render: {render_path}")


if __name__ == "__main__":
    main()
