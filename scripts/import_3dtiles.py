#!/usr/bin/env python3
"""
import_3dtiles.py — import Google's real 3D mesh downloaded by fetch_3dtiles.py,
transform it from ECEF into local ENU meters, preserve photogrammetry textures,
and configure lighting, cameras, tone mapping, and rendering.

Usage:
  blender -b -P import_3dtiles.py -- TILES_DIR OUT_DIR [--samples 48] [--res 1280 800]

TILES_DIR must contain manifest.json and tiles/*.glb from fetch_3dtiles.py.
"""
import json
import math
import os
import sys
from pathlib import Path

import bpy
import mathutils

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.append(str(HERE))
import blender_build as bb  # noqa: E402


def enu_matrix(manifest):
    e, n, u = manifest["enu"]
    ox, oy, oz = manifest["ecef_origin"]

    def dot(a, b):
        return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]
    o = (ox, oy, oz)
    return mathutils.Matrix((
        (e[0], e[1], e[2], -dot(e, o)),
        (n[0], n[1], n[2], -dot(n, o)),
        (u[0], u[1], u[2], -dot(u, o)),
        (0.0, 0.0, 0.0, 1.0),
    ))


def parse_argv():
    argv = sys.argv
    argv = argv[argv.index("--") + 1:] if "--" in argv else argv[1:]
    if len(argv) < 2:
        sys.exit("Usage: import_3dtiles.py TILES_DIR OUT_DIR [--samples N] [--res W H]")
    o = {"tiles": argv[0], "out": argv[1], "samples": 48, "res": (1280, 800)}
    i = 2
    while i < len(argv):
        if argv[i] == "--samples":
            o["samples"] = int(argv[i + 1]); i += 1
        elif argv[i] == "--res":
            o["res"] = (int(argv[i + 1]), int(argv[i + 2])); i += 2
        i += 1
    return o


def main():
    o = parse_argv()
    manifest = json.load(open(os.path.join(o["tiles"], "manifest.json")))
    M = enu_matrix(manifest)

    bpy.ops.wm.read_factory_settings(use_empty=True)
    coll = bpy.data.collections.new("02_GOOGLE_3DTILES")
    bpy.context.scene.collection.children.link(coll)

    tiles_dir = o["tiles"]
    n_obj = 0
    for t in manifest["tiles"]:
        path = os.path.join(tiles_dir, t["file"])
        if not os.path.isfile(path):
            continue
        before = set(bpy.data.objects)
        try:
            bpy.ops.import_scene.gltf(filepath=path)
        except Exception as e:
            print(f"  (import {t['file']} failed: {e})")
            continue
        for ob in [x for x in bpy.data.objects if x not in before]:
            if ob.type == "MESH":
                ob.matrix_world = M @ ob.matrix_world
                n_obj += 1
            for c in list(ob.users_collection):
                c.objects.unlink(ob)
            coll.objects.link(ob)

    print(f"[3dtiles] imported {n_obj} meshes")

    xs, ys, zs = [], [], []
    for ob in coll.objects:
        if ob.type != "MESH":
            continue
        for corner in ob.bound_box:
            p = ob.matrix_world @ mathutils.Vector(corner)
            xs.append(p.x); ys.append(p.y); zs.append(p.z)
    if not xs:
        sys.exit("No geometry was imported.")
    cx = (min(xs) + max(xs)) / 2
    cy = (min(ys) + max(ys)) / 2
    R = max(max(xs) - min(xs), max(ys) - min(ys)) / 2
    # Estimate local ground near the center, excluding deep distant-tile outliers.
    near_z = [z for (x, y, z) in zip(xs, ys, zs)
              if (x - cx) ** 2 + (y - cy) ** 2 < (R * 0.3) ** 2]
    near_z = sorted(near_z or zs)
    center_ground = near_z[len(near_z) // 8] if near_z else 0.0
    print("[3dtiles] ZSTATS all[min=%.0f max=%.0f] center[n=%d p12=%.0f p50=%.0f] cg=%.0f R=%.0f"
          % (min(zs), max(zs), len(near_z), near_z[len(near_z) // 8] if near_z else 0,
             near_z[len(near_z) // 2] if near_z else 0, center_ground, R))

    # Re-shade water from OSM polygons in the same local ENU frame. This marks the
    # river or dock without flooding lower plazas and adds reflective micro-ripples.
    import json as _json
    waters = []
    osm_path = os.path.join(o["tiles"], "..", "scene.json")
    if os.path.isfile(osm_path):
        try:
            _sc = _json.load(open(osm_path))
            waters = [a["polygon"] for a in _sc.get("areas", [])
                      if a["color"][2] > a["color"][1]]
        except Exception:
            waters = []
    if waters:
        meshes_w = [x for x in coll.objects if x.type == "MESH"]
        # OSM water bounds with a margin to fill the complete dock level.
        wxs = [p[0] for w in waters for p in w]
        wys = [p[1] for w in waters for p in w]
        wb = (min(wxs) - 12, min(wys) - 12, max(wxs) + 12, max(wys) + 12)
        # Pass 1: infer water level from horizontal faces inside OSM polygons.
        zmark = []
        for ob in meshes_w:
            rot = ob.matrix_world.to_3x3()
            for poly in ob.data.polygons:
                if (rot @ poly.normal).z > 0.85:
                    c = ob.matrix_world @ poly.center
                    if any(bb._point_in_poly(w, c.x, c.y) for w in waters):
                        zmark.append(c.z)
        zmark.sort()
        water_z = zmark[len(zmark) // 2] if zmark else None
        # Pass 2: apply water to polygon faces and nearby faces at the inferred
        # level, filling seams at OSM boundary gaps.
        water_mat = bb.make_water_material("dock_water")
        n_water = 0
        for ob in meshes_w:
            rot = ob.matrix_world.to_3x3()
            widx = len(ob.data.materials)
            ob.data.materials.append(water_mat)
            for poly in ob.data.polygons:
                if (rot @ poly.normal).z <= 0.85:
                    continue
                c = ob.matrix_world @ poly.center
                in_poly = any(bb._point_in_poly(w, c.x, c.y) for w in waters)
                in_fill = (water_z is not None and abs(c.z - water_z) < 1.6
                           and wb[0] < c.x < wb[2] and wb[1] < c.y < wb[3])
                if in_poly or in_fill:
                    poly.material_index = widx
                    n_water += 1
        print(f"[3dtiles] reflective water (OSM+fill z={water_z}): {n_water} faces")

    # Large base plane at local ground level hides the floating slab underside and
    # creates a horizon instead of a hard world cutoff.
    base_z = center_ground - 3.0
    bmesh_base = bpy.data.meshes.new("Horizon_base")
    s = R * 12
    bmesh_base.from_pydata(
        [(cx - s, cy - s, base_z), (cx + s, cy - s, base_z),
         (cx + s, cy + s, base_z), (cx - s, cy + s, base_z)], [], [(0, 1, 2, 3)])
    bmesh_base.update()
    base_ob = bpy.data.objects.new("Horizon_base", bmesh_base)
    # Match the plane to haze so the distant edge blends into the horizon.
    base_ob.data.materials.append(bb.make_material("horizon_base", (0.60, 0.68, 0.78),
                                                    roughness=0.95, specular=0.03))
    coll.objects.link(base_ob)

    bb.setup_world(sky=True)
    # A soft directional sun adds contact shadows without duplicating baked light.
    sun = bpy.data.lights.new("Sun", "SUN")
    sun.energy = 0.8 if bb.using_hdri() else 2.2
    try:
        sun.angle = 0.05
    except Exception:
        pass
    so = bpy.data.objects.new("Sun", sun)
    so.rotation_euler = (math.radians(50), math.radians(8), math.radians(150))
    bpy.context.scene.collection.objects.link(so)

    scn = bpy.context.scene
    scn.render.engine = "CYCLES"
    scn.cycles.samples = o["samples"]
    scn.cycles.device = "CPU"
    try:
        scn.cycles.use_denoising = True
    except Exception:
        pass
    scn.render.resolution_x, scn.render.resolution_y = o["res"]
    bb.apply_street_view_settings()
    # Lower exposure keeps the sky saturated; tile textures already contain light.
    try:
        scn.view_settings.exposure = -1.0
    except Exception:
        pass
    # Distance haze dissolves tile edges while excluding the sky to retain clouds.
    bb.setup_compositor(scn, haze_color=(0.56, 0.68, 0.85),
                        haze_start=R * 0.4, haze_end=R * 1.9,
                        haze_strength=0.9, vignette=0.16)

    out_dir = Path(o["out"]); out_dir.mkdir(parents=True, exist_ok=True)

    def render_cam(name, elev, azim, dist_f, tag, tz=None, frame=1.05, tgt_z=None):
        cd = bpy.data.cameras.new(name)
        cam = bpy.data.objects.new(name, cd)
        scn.collection.objects.link(cam)
        d = R * dist_f
        elev, azim = math.radians(elev), math.radians(azim)
        if tz is None:
            tz = min(R * 0.15, 40)
        cam.location = (cx + d * math.cos(elev) * math.sin(azim),
                        cy - d * math.cos(elev) * math.cos(azim),
                        tz + d * math.sin(elev))
        cd.clip_end = d * 10
        cd.angle = 2.0 * math.atan((R * frame) / d)
        tgt = bpy.data.objects.new(name + "_t", None)
        tgt.location = (cx, cy, tgt_z if tgt_z is not None else tz)
        scn.collection.objects.link(tgt)
        con = cam.constraints.new("TRACK_TO")
        con.target = tgt; con.track_axis = "TRACK_NEGATIVE_Z"; con.up_axis = "UP_Y"
        scn.camera = cam
        p = str(out_dir / f"tiles3d_{tag}.png")
        scn.render.filepath = p
        bpy.ops.render.render(write_still=True)
        print(f"[3dtiles] render {tag} -> {p}")

    render_cam("Camera_aerial", 34, 135, 2.0, "aerial", frame=0.95)
    render_cam("Camera_oblique", 15, 205, 1.55, "oblique", frame=0.8)
    # Low eye-level view aimed at the local ground median near the center.
    render_cam("Camera_low", 7, 150, 0.62, "street", frame=1.15, tgt_z=center_ground)

    blend = str(out_dir / "google_3dtiles.blend")
    try:
        bpy.ops.wm.save_as_mainfile(filepath=blend)
        print(f"[3dtiles] .blend -> {blend}")
    except Exception as e:
        print(f"[3dtiles] could not save .blend: {e}")


if __name__ == "__main__":
    main()
