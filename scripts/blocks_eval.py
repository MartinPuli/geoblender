"""Declarative acceptance gates for block mode.

Defaults confirm that the scene produced objects and the expected renders.
Run-specific targets belong in ``output/<slug>/eval.json``; the evaluator has no
hard-coded knowledge of places, identities, or universal quantities.

Usage:
  blender -b output/<slug>/<slug>_blocks.blend \
    -P scripts/blocks_eval.py -- output/<slug> [--eval <eval.json>]
"""

import json
import os
import sys


DEFAULT_GATES = {
    "min_objects": 1,
    "required_files": ["blocks_oblique.png", "blocks_aerial.png", "blocks_holdout.png"],
    "max_black_pct": 0.4,
}


def load_gate_config(eval_path=None):
    config = dict(DEFAULT_GATES)
    if eval_path and os.path.exists(eval_path):
        with open(eval_path, encoding="utf-8") as stream:
            user = json.load(stream)
        config.update(user.get("gates", user))
    return config


def _png_black_pct(path):
    """Return the percentage of nearly black pixels using Blender's image API."""
    import bpy

    image = bpy.data.images.load(path)
    try:
        pixels = list(image.pixels)
        count = len(pixels) // 4
        if not count:
            return 100.0
        black = sum(
            1
            for index in range(0, len(pixels), 4)
            if pixels[index] < 0.04
            and pixels[index + 1] < 0.04
            and pixels[index + 2] < 0.04
        )
        return 100.0 * black / count
    finally:
        bpy.data.images.remove(image)


def _reported_feature_heights(report):
    """Index reported heights by ID and name, including legacy reports."""
    indexed = {}
    features = list(report.get("features", [])) + list(report.get("landmarks", []))
    for feature in features:
        height = feature.get("height")
        if height is None:
            continue
        for key in (feature.get("id"), feature.get("osm_id"), feature.get("name")):
            if key not in (None, ""):
                indexed[str(key)] = float(height)
    return indexed


def evaluate_report(report, config, file_metrics=None, material_names=()):
    """Evaluate measured data without Blender, for tests and CI."""
    file_metrics = file_metrics or {}
    gates = {}

    if "min_objects" in config:
        value = int(report.get("objects", 0))
        wanted = int(config["min_objects"])
        gates["objects_min"] = {"pass": value >= wanted, "value": value, "want": wanted}

    if "min_individual_buildings" in config:
        value = int(report.get("buildings_individual", 0))
        wanted = int(config["min_individual_buildings"])
        gates["individual_buildings_min"] = {
            "pass": value >= wanted,
            "value": value,
            "want": wanted,
        }

    if "min_distinct_colors" in config:
        value = len({name for name in material_names if name.startswith("BLK_C_")})
        wanted = int(config["min_distinct_colors"])
        gates["distinct_colors_min"] = {
            "pass": value >= wanted,
            "value": value,
            "want": wanted,
        }

    appearance = report.get("building_appearance", {})
    for config_key, report_key, gate_name in (
            ("min_facade_shader_buildings", "facade_shader_buildings", "facade_shader_min"),
            ("min_facade_geometry_buildings", "facade_geometry_buildings", "facade_geometry_min"),
            ("min_facade_window_panels", "facade_window_panels", "facade_panels_min")):
        if config_key in config:
            value = int(appearance.get(report_key, 0))
            wanted = int(config[config_key])
            gates[gate_name] = {"pass": value >= wanted, "value": value, "want": wanted}

    construction = report.get("construction_detail", {})
    for config_key, report_key, gate_name in (
            ("min_building_parts", "building_parts", "building_parts_min"),
            ("min_construction_bands", "bands", "construction_bands_min"),
            ("min_entrances", "entrances", "entrances_min")):
        if config_key in config:
            value = int(construction.get(report_key, 0))
            wanted = int(config[config_key])
            gates[gate_name] = {"pass": value >= wanted, "value": value, "want": wanted}

    if "required_color_sources" in config:
        actual = set((appearance.get("color_sources") or {}).keys())
        wanted = {str(value) for value in config["required_color_sources"]}
        gates["required_color_sources"] = {
            "pass": wanted <= actual,
            "value": sorted(actual),
            "want": sorted(wanted),
        }

    for config_key, report_key, gate_name in (
            ("min_facade_color_confidence_mean", "facade_color_confidence_mean",
             "facade_color_confidence_mean"),
            ("min_roof_color_confidence_mean", "roof_color_confidence_mean",
             "roof_color_confidence_mean")):
        if config_key in config:
            value = float(appearance.get(report_key, 0.0))
            wanted = float(config[config_key])
            gates[gate_name] = {"pass": value >= wanted,
                                "value": round(value, 3), "want": wanted}

    expected = config.get("expected_feature_heights", {})
    if expected:
        actual = _reported_feature_heights(report)
        tolerance = float(config.get("feature_height_tolerance", 0.5))
        for selector, wanted in expected.items():
            value = actual.get(str(selector))
            gates[f"feature_height:{selector}"] = {
                "pass": value is not None and abs(value - float(wanted)) <= tolerance,
                "value": value if value is not None else "missing",
                "want": {"height": float(wanted), "tolerance": tolerance},
            }

    for filename in config.get("required_files", []):
        metric = file_metrics.get(filename, {})
        exists = bool(metric.get("exists"))
        gate = {"pass": exists, "value": "exists" if exists else "missing", "want": "exists"}
        if exists and filename.lower().endswith(".png") and "max_black_pct" in config:
            black = metric.get("black_pct")
            limit = float(config["max_black_pct"])
            gate = {
                "pass": black is not None and float(black) <= limit,
                "value": round(float(black), 3) if black is not None else "unmeasured",
                "want": f"<={limit}% black pixels",
            }
        gates[f"file:{filename}"] = gate

    return {"complete": bool(gates) and all(gate["pass"] for gate in gates.values()),
            "gates": gates}


def run_checks(outdir, eval_path=None):
    import bpy

    eval_path = eval_path or os.path.join(outdir, "eval.json")
    config = load_gate_config(eval_path)
    report_path = os.path.join(outdir, "build_report.json")
    if os.path.exists(report_path):
        with open(report_path, encoding="utf-8") as stream:
            report = json.load(stream)
    else:
        report = {}

    metrics = {}
    for filename in config.get("required_files", []):
        path = os.path.join(outdir, filename)
        metrics[filename] = {"exists": os.path.exists(path)}
        if metrics[filename]["exists"] and filename.lower().endswith(".png"):
            metrics[filename]["black_pct"] = _png_black_pct(path)

    result = evaluate_report(
        report,
        config,
        file_metrics=metrics,
        material_names=(material.name for material in bpy.data.materials),
    )
    with open(os.path.join(outdir, "eval_report.json"), "w", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2, ensure_ascii=False)
    print("BLOCKS EVAL:", "COMPLETE" if result["complete"] else "INCOMPLETE",
          json.dumps(result, ensure_ascii=False))
    return result


def _cli():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    if not argv:
        print("usage: blender -b <blend> -P blocks_eval.py -- <outdir> [--eval f]")
        return
    eval_path = argv[argv.index("--eval") + 1] if "--eval" in argv else None
    run_checks(argv[0], eval_path)


if __name__ == "__main__":
    _cli()
