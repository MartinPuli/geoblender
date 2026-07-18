#!/usr/bin/env python3
"""
world_scene.py — build a complete, deliverable Blender scene from scene.json
following the world-to-blender specification:

  - colored geometry in named collections (00_REFERENCE..13_EXPORT)
  - geographic metadata in the scene and a GEO_ORIGIN Empty
  - sun, physical sky, and aerial/oblique/street cameras
  - cleaned geometry and normals through bm_to_object
  - saved <slug>_world_scene.blend and preview renders
  - optional GLB/FBX/OBJ/STL exports and a report.json inventory

Headless usage with the Blender binary:
  blender -b -P world_scene.py -- scene.json OUT_DIR SLUG \
          [--engine CYCLES|EEVEE] [--samples N] [--export glb,fbx] \
          [--street-heading H --street-x X --street-y Y]

Coordinates use meters: X=east, Y=north, Z=up. One Blender unit is one meter.
"""
import json
import math
import os
import sys
from pathlib import Path

import bpy

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.append(str(HERE))
import blender_build as bb  # noqa: E402


def parse_argv():
    argv = sys.argv
    argv = argv[argv.index("--") + 1:] if "--" in argv else argv[1:]
    if len(argv) < 3:
        sys.exit("Usage: world_scene.py scene.json OUT_DIR SLUG [--engine CYCLES|EEVEE] "
                 "[--samples N] [--export glb,fbx] [--street-heading H --street-x X --street-y Y]")
    o = {"scene": argv[0], "out": argv[1], "slug": argv[2],
         "engine": "CYCLES", "samples": 64, "export": ["glb"],
         "sheading": 0.0, "sx": 0.0, "sy": 0.0, "res": (1600, 1000)}
    i = 3
    while i < len(argv):
        a = argv[i]
        if a == "--engine":
            o["engine"] = argv[i + 1].upper(); i += 1
        elif a == "--samples":
            o["samples"] = int(argv[i + 1]); i += 1
        elif a == "--export":
            o["export"] = [s.strip().lower() for s in argv[i + 1].split(",") if s.strip()]; i += 1
        elif a == "--street-heading":
            o["sheading"] = float(argv[i + 1]); i += 1
        elif a == "--street-x":
            o["sx"] = float(argv[i + 1]); i += 1
        elif a == "--street-y":
            o["sy"] = float(argv[i + 1]); i += 1
        elif a == "--res":
            o["res"] = (int(argv[i + 1]), int(argv[i + 2])); i += 2
        i += 1
    return o


def set_metadata(scene, coll):
    """Store geographic metadata on the scene and a GEO_ORIGIN Empty."""
    c = scene.get("center", {})
    scn = bpy.context.scene
    meta = {
        "geo_lat": float(c.get("lat", 0.0)),
        "geo_lon": float(c.get("lon", 0.0)),
        "geo_label": str(c.get("label", "")),
        "geo_radius_m": float(scene.get("radius", 0.0)),
        "geo_projection": "local equirectangular projection in meters around center",
        "geo_source": "OpenStreetMap (Overpass) + Google Street View reference",
    }
    for k, v in meta.items():
        scn[k] = v
    empty = bpy.data.objects.new("GEO_ORIGIN", None)
    empty.empty_display_size = 5.0
    empty.empty_display_type = "ARROWS"
    for k, v in meta.items():
        empty[k] = v
    coll.objects.link(empty)
    return meta


def _track(cam, cx, cy, cz):
    tgt = bpy.data.objects.new(cam.name + "_target", None)
    tgt.location = (cx, cy, cz)
    bpy.context.scene.collection.objects.link(tgt)
    con = cam.constraints.new("TRACK_TO")
    con.target = tgt
    con.track_axis = "TRACK_NEGATIVE_Z"
    con.up_axis = "UP_Y"
    return tgt


def make_cameras(cx, cy, R, coll, street=(0.0, 0.0, 0.0)):
    """Create aerial, oblique, and street cameras; return the active aerial camera."""
    scn = bpy.context.scene

    def cam_at(name, elev_deg, azim_deg, dist, frame_R, tz):
        cd = bpy.data.cameras.new(name)
        ob = bpy.data.objects.new(name, cd)
        coll.objects.link(ob)
        elev, azim = math.radians(elev_deg), math.radians(azim_deg)
        ob.location = (cx + dist * math.cos(elev) * math.sin(azim),
                       cy - dist * math.cos(elev) * math.cos(azim),
                       tz + dist * math.sin(elev))
        cd.clip_end = dist * 6.0
        try:
            cd.sensor_fit = "AUTO"
        except Exception:
            pass
        cd.angle = 2.0 * math.atan((frame_R) / dist)
        _track(ob, cx, cy, tz)
        return ob

    aerial = cam_at("Camera_aerial", 33.0, 135.0, R * 2.3, R * 1.02, min(R * 0.12, 30.0))
    cam_at("Camera_oblique", 15.0, 205.0, R * 1.7, R * 0.85, min(R * 0.10, 22.0))

    # Street camera.
    sx, sy, sh = street
    cd = bpy.data.cameras.new("Camera_street")
    ob = bpy.data.objects.new("Camera_street", cd)
    coll.objects.link(ob)
    ob.location = (sx, sy, 2.5)
    ob.rotation_euler = (math.radians(90.0), 0.0, math.radians(-sh))
    cd.clip_end = 5000.0
    try:
        cd.sensor_fit = "HORIZONTAL"
    except Exception:
        pass
    cd.angle = math.radians(74.0)

    scn.camera = aerial
    return aerial


def setup_lighting(coll):
    """Set a real HDRI or Nishita sky, avoiding duplicate sunlight with HDRI."""
    bb.setup_world(sky=True)
    if bb.using_hdri():
        return None
    data = bpy.data.lights.new("Sun", "SUN")
    data.energy = 2.2
    try:
        data.angle = 0.06
    except Exception:
        pass
    sun = bpy.data.objects.new("Sun", data)
    sun.rotation_euler = (math.radians(52), math.radians(8), math.radians(150))
    coll.objects.link(sun)
    return sun


def scene_stats():
    """Count objects, polygons, and materials globally and by collection."""
    total_obj = 0
    total_poly = 0
    per_coll = {}
    for coll in bpy.data.collections:
        if coll.name not in bb.COLLECTION_NAMES:
            continue
        n_obj = len(coll.objects)
        n_poly = sum(len(o.data.polygons) for o in coll.objects
                     if o.type == "MESH" and o.data)
        per_coll[coll.name] = {"objects": n_obj, "polygons": n_poly}
    for o in bpy.data.objects:
        total_obj += 1
        if o.type == "MESH" and o.data:
            total_poly += len(o.data.polygons)
    return {
        "total_objects": total_obj,
        "total_polygons": total_poly,
        "total_materials": len(bpy.data.materials),
        "per_collection": per_coll,
    }


def export_formats(out_dir, slug, formats):
    exported = {}
    exp_dir = Path(out_dir) / "export"
    exp_dir.mkdir(parents=True, exist_ok=True)
    for fmt in formats:
        path = str(exp_dir / f"{slug}.{fmt}")
        try:
            if fmt in ("glb", "gltf"):
                bpy.ops.export_scene.gltf(
                    filepath=path,
                    export_format="GLB" if fmt == "glb" else "GLTF_SEPARATE")
            elif fmt == "fbx":
                bpy.ops.export_scene.fbx(filepath=path)
            elif fmt == "obj":
                try:
                    bpy.ops.wm.obj_export(filepath=path)
                except Exception:
                    bpy.ops.export_scene.obj(filepath=path)
            elif fmt == "stl":
                try:
                    bpy.ops.wm.stl_export(filepath=path)
                except Exception:
                    bpy.ops.export_mesh.stl(filepath=path)
            else:
                continue
            exported[fmt] = path
            print(f"[world_scene] export {fmt} -> {path}")
        except Exception as e:
            print(f"[world_scene] export {fmt} FAILED: {e}")
    return exported


def main():
    o = parse_argv()
    with open(o["scene"]) as f:
        scene = json.load(f)

    bpy.ops.wm.read_factory_settings(use_empty=True)  # safe in headless mode without MCP

    cx, cy, R = bb.build_scene(scene)
    C = bb.make_collections()
    meta = set_metadata(scene, C["00_REFERENCE"])
    setup_lighting(C["11_LIGHTING"])
    make_cameras(cx, cy, R, C["12_CAMERAS"], street=(o["sx"], o["sy"], o["sheading"]))

    # Render settings
    scn = bpy.context.scene
    if o["engine"] == "EEVEE":
        try:
            scn.render.engine = "BLENDER_EEVEE_NEXT"
        except Exception:
            scn.render.engine = "BLENDER_EEVEE"
    else:
        scn.render.engine = "CYCLES"
        scn.cycles.samples = o["samples"]
        scn.cycles.device = "CPU"
        try:
            scn.cycles.use_denoising = True
        except Exception:
            pass
    scn.render.resolution_x, scn.render.resolution_y = o["res"]
    scn.render.resolution_percentage = 100
    bb.apply_street_view_settings()   # AgX look and photographic exposure
    # HDRI exposure is uniform. Nishita aerial views face a darker zenith and
    # need slightly more exposure.
    try:
        scn.view_settings.exposure = bb.STREET_EXPOSURE_HDRI if bb.using_hdri() else -1.7
    except Exception:
        pass
    bb.setup_compositor(scn, haze_end=max(700.0, R * 3.0))  # distance haze and vignette

    out_dir = Path(o["out"])
    out_dir.mkdir(parents=True, exist_ok=True)

    # Pack textures and HDRI into a self-contained .blend.
    try:
        bpy.ops.file.pack_all()
    except Exception as e:
        print(f"[world_scene] pack_all: {e}")

    # Save .blend.
    blend_path = str(out_dir / f"{o['slug']}_world_scene.blend")
    try:
        bpy.ops.wm.save_as_mainfile(filepath=blend_path)
        print(f"[world_scene] .blend -> {blend_path}")
    except Exception as e:
        print(f"[world_scene] could not save .blend: {e}")

    # Render aerial, oblique, and street previews.
    previews = {}
    for cam_name, tag in (("Camera_aerial", "aerial"), ("Camera_oblique", "oblique"),
                          ("Camera_street", "street")):
        cam = bpy.data.objects.get(cam_name)
        if not cam:
            continue
        scn.camera = cam
        p = str(out_dir / f"preview_{tag}.png")
        scn.render.filepath = p
        try:
            bpy.ops.render.render(write_still=True)
            previews[tag] = p
            print(f"[world_scene] preview {tag} -> {p}")
        except Exception as e:
            print(f"[world_scene] preview {tag} FAILED: {e}")

    exported = export_formats(o["out"], o["slug"], o["export"])
    stats = scene_stats()

    report = {
        "location": meta,
        "stats": stats,
        "blend": blend_path,
        "previews": previews,
        "exports": exported,
        "engine": o["engine"],
    }
    rp = str(out_dir / "report.json")
    with open(rp, "w") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    print(f"[world_scene] report -> {rp}")
    print("[world_scene] STATS " + json.dumps(stats))


if __name__ == "__main__":
    main()
