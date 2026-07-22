#!/usr/bin/env python3
"""One-command normalized OSM -> editable Blender blocks -> evaluation.

This wrapper keeps the individual scripts available for debugging while making
the normal skill path difficult to misuse.  Provider imagery remains optional
reference evidence and is never imported into the Blender scene.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from place_to_3d import slugify


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent


def find_blender(explicit=None):
    """Return an executable Blender path with useful cross-platform fallbacks."""
    candidates = [
        explicit,
        os.environ.get("BLENDER_BIN"),
        shutil.which("blender"),
        "/Applications/Blender.app/Contents/MacOS/Blender",
        r"C:\Program Files\Blender Foundation\Blender\blender.exe",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).is_file() and os.access(candidate, os.X_OK):
            return str(Path(candidate).resolve())
    raise SystemExit(
        "Blender was not found. Pass --blender /absolute/path/to/blender or set BLENDER_BIN."
    )


def default_output(place):
    return ROOT / "output" / slugify(place)


def run_step(label, command):
    print(f"\n▶ {label}\n  {' '.join(map(str, command))}", flush=True)
    result = subprocess.run([str(item) for item in command])
    if result.returncode:
        raise SystemExit(f"{label} failed with exit code {result.returncode}")


def require_complete_evaluation(report_path):
    """Fail the one-command workflow when declarative acceptance gates fail."""
    report_path = Path(report_path)
    if not report_path.is_file():
        raise SystemExit(f"Evaluation did not produce {report_path}")
    with report_path.open(encoding="utf-8") as stream:
        evaluation = json.load(stream)
    if not evaluation.get("complete"):
        failed = [name for name, gate in evaluation.get("gates", {}).items()
                  if not gate.get("pass")]
        raise SystemExit(
            "Maps-to-3D evaluation incomplete; failed gates: "
            + ", ".join(failed))
    return evaluation


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Build and evaluate editable real-place Blender blocks in one command")
    parser.add_argument("place", nargs="?",
                        help="address, coordinates, Google Maps link, or place name")
    parser.add_argument("--scene", help="reuse an existing normalized scene.json")
    parser.add_argument("--out", help="output directory")
    parser.add_argument("--slug", help="safe output/blend filename stem")
    parser.add_argument("--radius", type=float, default=350.0,
                        help="construction radius in meters (default: 350)")
    parser.add_argument("--terrain", action="store_true", help="fetch SRTM/DEM terrain")
    parser.add_argument("--terrain-res", type=int, default=20)
    parser.add_argument("--no-references", action="store_true",
                        help="skip optional Google comparison references")
    parser.add_argument("--style", help="optional per-run style.json")
    parser.add_argument("--samples", type=int, default=48)
    parser.add_argument("--blender", help="absolute Blender executable path")
    parser.add_argument("--data-only", action="store_true",
                        help="normalize scene.json but do not open Blender")
    parser.add_argument("--no-eval", action="store_true",
                        help="build and render but skip acceptance evaluation")
    parser.add_argument("--eval", dest="eval_path",
                        help="optional eval.json with run-specific gates")
    args = parser.parse_args(argv)

    if not args.place and not args.scene:
        parser.error("provide a place or --scene /path/to/scene.json")
    if args.place and args.scene:
        parser.error("use either a place or --scene, not both")

    if args.scene:
        scene_path = Path(args.scene).expanduser().resolve()
        if not scene_path.is_file():
            parser.error(f"scene does not exist: {scene_path}")
        out_dir = Path(args.out).expanduser().resolve() if args.out else scene_path.parent
        slug = args.slug or slugify(out_dir.name)
    else:
        out_dir = (Path(args.out).expanduser().resolve()
                   if args.out else default_output(args.place).resolve())
        slug = args.slug or slugify(out_dir.name)
        out_dir.mkdir(parents=True, exist_ok=True)
        acquire = [
            sys.executable, HERE / "place_to_3d.py", args.place,
            "--radius", str(args.radius), "--out", out_dir, "--no-render",
        ]
        if args.terrain:
            acquire += ["--terrain", "--terrain-res", str(args.terrain_res)]
        if args.no_references:
            acquire.append("--no-streetview")
        run_step("Normalize OpenStreetMap construction data", acquire)
        scene_path = out_dir / "scene.json"

    if args.data_only:
        print(f"\n✓ Normalized scene: {scene_path}")
        return 0

    blender = find_blender(args.blender)
    out_dir.mkdir(parents=True, exist_ok=True)
    build = [
        blender, "-b", "-P", HERE / "blocks_build.py", "--",
        scene_path, out_dir, slug, "--render", "--samples", str(args.samples),
    ]
    if args.style:
        build += ["--style", str(Path(args.style).expanduser().resolve())]
    run_step("Build editable blocks and render three views", build)

    blend_path = out_dir / f"{slug}_blocks.blend"
    if not args.no_eval:
        evaluate = [
            blender, "-b", blend_path, "-P", HERE / "blocks_eval.py", "--", out_dir,
        ]
        if args.eval_path:
            evaluate += ["--eval", str(Path(args.eval_path).expanduser().resolve())]
        run_step("Evaluate build and render gates", evaluate)
        require_complete_evaluation(out_dir / "eval_report.json")

    print("\n✓ Maps-to-3D complete")
    print(f"  Blend:  {blend_path}")
    print(f"  Views:  {out_dir / 'blocks_oblique.png'}")
    print(f"  Report: {out_dir / 'build_report.json'}")
    if not args.no_eval:
        print(f"  Eval:   {out_dir / 'eval_report.json'}")
    return 0


if __name__ == "__main__":
    main()
