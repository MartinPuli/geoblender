#!/usr/bin/env python3
"""
render_view.py — render a specific scene view headlessly for comparison with a
Google Street View image, without depending on a live Blender MCP session.

Usage:
  # Street-level view for comparison with streetview/heading_XXX.jpg:
  blender -b -P render_view.py -- scene.json out.png \
          --street --heading 0 --x 0 --y 0 --height 2.5 --fov 78

  # Three-quarter aerial block-model view:
  blender -b -P render_view.py -- scene.json out.png

scene.json coordinates use meters: X=east, Y=north, Z=up.
"""
import json
import math
import sys
from pathlib import Path

import bpy  # noqa: F401  (ensures execution inside Blender)

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.append(str(HERE))
import blender_build as bb  # noqa: E402


def parse_argv():
    argv = sys.argv
    argv = argv[argv.index("--") + 1:] if "--" in argv else argv[1:]
    if len(argv) < 2:
        sys.exit("Usage: render_view.py scene.json out.png [--street --heading H --x X --y Y --height Z --fov F] [--samples N] [--res W H]")
    scene_path, out_path = argv[0], argv[1]
    o = {"street": False, "heading": 0.0, "x": 0.0, "y": 0.0, "height": 2.5,
         "fov": 78.0, "samples": None, "res": None, "sky": True}
    i = 2
    while i < len(argv):
        a = argv[i]
        if a == "--street":
            o["street"] = True
        elif a == "--no-sky":
            o["sky"] = False
        elif a in ("--heading", "--x", "--y", "--height", "--fov", "--samples"):
            o[a[2:]] = float(argv[i + 1]); i += 1
        elif a == "--res":
            o["res"] = (int(argv[i + 1]), int(argv[i + 2])); i += 2
        i += 1
    return scene_path, out_path, o


def main():
    scene_path, out_path, o = parse_argv()
    with open(scene_path) as f:
        scene = json.load(f)

    bpy.ops.wm.read_factory_settings(use_empty=True)

    cx, cy, R = bb.build_scene(scene)

    if o["street"]:
        bb.setup_world(sky=o["sky"])
        import citycamera
        (sx, sy), moved = citycamera.safe_street_point(scene, o["x"], o["y"])
        if moved:
            print(f"[render_view] moved camera outside building -> ({sx:.1f}, {sy:.1f})")
        bb.setup_streetview_camera(o["heading"], o["fov"], o["height"], sx, sy)
        bb.apply_street_view_settings()   # AgX, punchy look, photographic exposure
        bb.setup_compositor(bpy.context.scene, haze_end=460.0,
                            haze_strength=0.7)  # distance haze and vignette
    else:
        bb.setup_world(sky=False)
        bb.setup_sun()
        bb.setup_camera(cx, cy, R)
        vs = bpy.context.scene.view_settings
        try:
            vs.view_transform = "Standard"
            vs.exposure = bb.EXPOSURE
        except Exception:
            pass

    scn = bpy.context.scene
    try:
        scn.render.engine = "CYCLES"
        scn.cycles.samples = int(o["samples"]) if o["samples"] else bb.CYCLES_SAMPLES
        scn.cycles.device = "CPU"
        try:
            scn.cycles.use_denoising = True
        except Exception:
            pass
    except Exception:
        scn.render.engine = "BLENDER_EEVEE_NEXT"
    if o["res"]:
        scn.render.resolution_x, scn.render.resolution_y = o["res"]
    else:
        scn.render.resolution_x, scn.render.resolution_y = bb.RES_X, bb.RES_Y
    scn.render.resolution_percentage = 100
    scn.render.filepath = out_path

    print(f"[render_view] {'street' if o['street'] else 'aerial'} "
          f"buildings={len(scene.get('buildings', []))} R={R:.0f}m -> {out_path}")
    bpy.ops.render.render(write_still=True)
    print(f"[render_view] done: {out_path}")


if __name__ == "__main__":
    main()
