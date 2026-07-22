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
            ("min_facade_window_panels", "facade_window_panels", "facade_panels_min"),
            ("min_facade_window_frame_parts", "facade_window_frame_parts",
             "facade_window_frame_parts_min"),
            ("min_facade_window_mullions", "facade_window_mullions",
             "facade_window_mullions_min"),
            ("min_visible_interior_bays", "visible_interior_bays",
             "visible_interior_bays_min"),
            ("min_lit_interior_rooms", "lit_interior_rooms",
             "lit_interior_rooms_min"),
            ("min_symmetric_window_pairs", "symmetric_window_pairs",
             "symmetric_window_pairs_min"),
            ("min_balconies", "balconies", "balconies_min"),
            ("min_facade_accent_parts", "facade_accent_parts",
             "facade_accent_parts_min")):
        if config_key in config:
            value = int(appearance.get(report_key, 0))
            wanted = int(config[config_key])
            gates[gate_name] = {"pass": value >= wanted, "value": value, "want": wanted}
    for config_key, report_key, gate_name in (
            ("min_facade_profiles", "facade_profiles", "facade_profiles_min"),
            ("min_facade_variants", "facade_variants", "facade_variants_min")):
        if config_key in config:
            raw = appearance.get(report_key, {})
            value = len(raw)
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

    interiors = report.get("building_interiors", {})
    for config_key, report_key, gate_name in (
            ("min_interior_layout_buildings", "buildings", "interior_layout_buildings_min"),
            ("min_interior_floor_slabs", "floor_slabs", "interior_floor_slabs_min"),
            ("min_interior_corridor_segments", "corridor_segments", "interior_corridors_min"),
            ("min_interior_partitions", "partitions", "interior_partitions_min"),
            ("min_interior_cores", "cores", "interior_cores_min")):
        if config_key in config:
            value = int(interiors.get(report_key, 0))
            wanted = int(config[config_key])
            gates[gate_name] = {"pass": value >= wanted, "value": value, "want": wanted}

    covered = report.get("covered_structures", {})
    for config_key, report_key, gate_name in (
            ("min_covered_structures", "count", "covered_structures_min"),
            ("min_cover_columns", "columns", "cover_columns_min"),
            ("min_cover_edge_beams", "edge_beams", "cover_edge_beams_min")):
        if config_key in config:
            value = int(covered.get(report_key, 0))
            wanted = int(config[config_key])
            gates[gate_name] = {"pass": value >= wanted, "value": value, "want": wanted}

    urban = report.get("urban_objects", {})
    for config_key, report_key, gate_name in (
            ("min_urban_objects", "count", "urban_objects_min"),
            ("min_urban_object_parts", "parts", "urban_object_parts_min")):
        if config_key in config:
            value = int(urban.get(report_key, 0))
            wanted = int(config[config_key])
            gates[gate_name] = {"pass": value >= wanted, "value": value, "want": wanted}

    if "required_urban_object_kinds" in config:
        actual = set((urban.get("by_kind") or {}).keys())
        wanted = {str(value) for value in config["required_urban_object_kinds"]}
        gates["required_urban_object_kinds"] = {
            "pass": wanted <= actual, "value": sorted(actual), "want": sorted(wanted),
        }

    urban_detail = report.get("urban_detail", {})
    for config_key, report_key, gate_name in (
            ("min_urban_detail_objects", "count", "urban_detail_objects_min"),
            ("min_urban_detail_parts", "parts", "urban_detail_parts_min"),
            ("min_urban_text_objects", "text_objects", "urban_text_objects_min"),
            ("min_urban_explicit_directions", "explicit_directions",
             "urban_explicit_directions_min"),
            ("min_urban_explicit_dimensions", "explicit_dimensions",
             "urban_explicit_dimensions_min"),
            ("min_urban_wall_hosted", "wall_hosted", "urban_wall_hosted_min")):
        if config_key in config:
            value = int(urban_detail.get(report_key, 0))
            wanted = int(config[config_key])
            gates[gate_name] = {"pass": value >= wanted, "value": value, "want": wanted}

    if "min_urban_road_hosted" in config:
        value = int(urban_detail.get("road_hosted", 0))
        wanted = int(config["min_urban_road_hosted"])
        gates["urban_road_hosted_min"] = {
            "pass": value >= wanted, "value": value, "want": wanted,
        }

    if "required_urban_sign_shapes" in config:
        actual = set((urban_detail.get("by_sign_shape") or {}).keys())
        wanted = {str(value) for value in config["required_urban_sign_shapes"]}
        gates["required_urban_sign_shapes"] = {
            "pass": wanted <= actual, "value": sorted(actual), "want": sorted(wanted),
        }

    if "required_urban_families" in config:
        actual = set((urban_detail.get("by_family") or {}).keys())
        wanted = {str(value) for value in config["required_urban_families"]}
        gates["required_urban_families"] = {
            "pass": wanted <= actual, "value": sorted(actual), "want": sorted(wanted),
        }

    streetscape = report.get("streetscape", {})
    for config_key, report_key, gate_name in (
            ("min_streetscape_lane_arrows", "lane_arrows", "streetscape_lane_arrows_min"),
            ("min_streetscape_kerb_segments", "kerb_segments", "streetscape_kerbs_min"),
            ("min_streetscape_traffic_islands", "traffic_islands", "streetscape_islands_min"),
            ("min_streetscape_stop_lines", "stop_lines", "streetscape_stop_lines_min"),
            ("min_streetscape_lane_dividers", "lane_dividers", "streetscape_lane_dividers_min"),
            ("min_streetscape_cycle_lanes", "cycle_lanes", "streetscape_cycle_lanes_min"),
            ("min_streetscape_cycle_lane_separators", "cycle_lane_separators",
             "streetscape_cycle_lane_separators_min"),
            ("min_streetscape_cycle_protection_elements", "cycle_protection_elements",
             "streetscape_cycle_protection_elements_min"),
            ("min_streetscape_bus_lanes", "bus_lanes", "streetscape_bus_lanes_min"),
            ("min_streetscape_bus_lane_metadata_profiles", "bus_lane_metadata_profiles",
             "streetscape_bus_lane_metadata_profiles_min"),
            ("min_streetscape_parking_strips", "parking_strips",
             "streetscape_parking_strips_min"),
            ("min_streetscape_manhole_covers", "manhole_covers",
             "streetscape_manhole_covers_min"),
            ("min_streetscape_drainage_inlets", "drainage_inlets",
             "streetscape_drainage_inlets_min"),
            ("min_streetscape_sidewalk_strips", "sidewalk_strips",
             "streetscape_sidewalk_strips_min"),
            ("min_streetscape_sidewalk_metadata_profiles", "sidewalk_metadata_profiles",
             "streetscape_sidewalk_metadata_profiles_min"),
            ("min_streetscape_sidewalk_kerb_edges", "sidewalk_kerb_edges",
             "streetscape_sidewalk_kerb_edges_min"),
            ("min_streetscape_curb_ramps", "curb_ramps",
             "streetscape_curb_ramps_min"),
            ("min_streetscape_raised_crossings", "raised_crossings",
             "streetscape_raised_crossings_min"),
            ("min_streetscape_speed_tables", "speed_tables",
             "streetscape_speed_tables_min"),
            ("min_streetscape_tree_rows", "tree_rows", "streetscape_tree_rows_min"),
            ("min_streetscape_utility_lines", "utility_lines", "streetscape_utility_lines_min"),
            ("min_streetscape_utility_conductors", "utility_conductors",
             "streetscape_utility_conductors_min")):
        if config_key in config:
            value = int(streetscape.get(report_key, 0))
            wanted = int(config[config_key])
            gates[gate_name] = {"pass": value >= wanted, "value": value, "want": wanted}

    if "min_streetscape_cycle_lane_m" in config:
        value = float(streetscape.get("cycle_lane_m", 0.0))
        wanted = float(config["min_streetscape_cycle_lane_m"])
        gates["streetscape_cycle_lane_m_min"] = {
            "pass": value >= wanted, "value": value, "want": wanted,
        }
    for config_key, report_key, gate_name in (
            ("min_streetscape_bus_lane_m", "bus_lane_m", "streetscape_bus_lane_m_min"),
            ("min_streetscape_parking_strip_m", "parking_strip_m",
             "streetscape_parking_strip_m_min"),
            ("min_streetscape_sidewalk_m", "sidewalk_m",
             "streetscape_sidewalk_m_min")):
        if config_key in config:
            value = float(streetscape.get(report_key, 0.0))
            wanted = float(config[config_key])
            gates[gate_name] = {"pass": value >= wanted, "value": value, "want": wanted}
    for config_key, report_key, gate_name in (
            ("max_streetscape_curb_ramp_height", "curb_ramp_max_height",
             "streetscape_curb_ramp_height_max"),
            ("max_streetscape_raised_crossing_height", "raised_crossing_max_height",
             "streetscape_raised_crossing_height_max")):
        if config_key in config:
            value = float(streetscape.get(report_key, 0.0))
            wanted = float(config[config_key])
            gates[gate_name] = {"pass": value <= wanted, "value": value, "want": wanted}

    utility = report.get("utility_networks", {})
    for config_key, report_key, gate_name in (
            ("min_utility_substations", "substations", "utility_substations_min"),
            ("min_utility_transformers", "transformers", "utility_transformers_min"),
            ("min_utility_telecom_poles", "telecom_poles", "utility_telecom_poles_min"),
            ("min_utility_telecom_cabinets", "telecom_cabinets", "utility_telecom_cabinets_min"),
            ("min_utility_communication_lines", "communication_lines",
             "utility_communication_lines_min"),
            ("min_utility_communication_conductors", "communication_conductors",
             "utility_communication_conductors_min"),
            ("min_utility_metadata_only_lines", "metadata_only_lines",
             "utility_metadata_only_lines_min")):
        if config_key in config:
            value = int(utility.get(report_key, 0))
            wanted = int(config[config_key])
            gates[gate_name] = {"pass": value >= wanted, "value": value, "want": wanted}

    fluid = report.get("fluid_networks", {})
    for config_key, report_key, gate_name in (
            ("min_fluid_visible_lines", "visible_lines", "fluid_visible_lines_min"),
            ("min_fluid_metadata_only_lines", "metadata_only_lines",
             "fluid_metadata_only_lines_min"),
            ("min_fluid_supports", "supports", "fluid_supports_min"),
            ("min_fluid_pumping_stations", "pumping_stations",
             "fluid_pumping_stations_min"),
            ("min_fluid_valves", "valves", "fluid_valves_min"),
            ("min_fluid_measurement_points", "measurement_points",
             "fluid_measurement_points_min"),
            ("min_fluid_cabinets", "fluid_cabinets", "fluid_cabinets_min")):
        if config_key in config:
            value = int(fluid.get(report_key, 0))
            wanted = int(config[config_key])
            gates[gate_name] = {"pass": value >= wanted, "value": value, "want": wanted}
    if "min_fluid_visible_length_m" in config:
        value = float(fluid.get("visible_length_m", 0.0))
        wanted = float(config["min_fluid_visible_length_m"])
        gates["fluid_visible_length_m_min"] = {
            "pass": value >= wanted, "value": value, "want": wanted,
        }

    access = report.get("pedestrian_access", {})
    for config_key, report_key, gate_name in (
            ("min_pedestrian_steps", "steps", "pedestrian_steps_min"),
            ("min_pedestrian_ramps", "ramps", "pedestrian_ramps_min"),
            ("min_pedestrian_escalators", "escalators", "pedestrian_escalators_min"),
            ("min_pedestrian_moving_walkways", "moving_walkways", "pedestrian_moving_walkways_min"),
            ("min_pedestrian_elevators", "elevators", "pedestrian_elevators_min"),
            ("min_pedestrian_inclined_elevators", "inclined_elevators", "pedestrian_inclined_elevators_min"),
            ("min_pedestrian_handrails", "handrails", "pedestrian_handrails_min"),
            ("min_pedestrian_unspecified_handrails", "unspecified_handrails", "pedestrian_unspecified_handrails_min"),
            ("min_pedestrian_step_count", "step_count", "pedestrian_step_count_min")):
        if config_key in config:
            value = int(access.get(report_key, 0)); wanted = int(config[config_key])
            gates[gate_name] = {"pass": value >= wanted, "value": value, "want": wanted}
    for config_key, report_key, gate_name in (
            ("min_pedestrian_step_m", "step_m", "pedestrian_step_m_min"),
            ("min_pedestrian_ramp_m", "ramp_m", "pedestrian_ramp_m_min"),
            ("min_pedestrian_handrail_m", "handrail_m", "pedestrian_handrail_m_min")):
        if config_key in config:
            value = float(access.get(report_key, 0.0)); wanted = float(config[config_key])
            gates[gate_name] = {"pass": value >= wanted, "value": value, "want": wanted}
    if "max_pedestrian_rise_m" in config:
        value = float(access.get("max_rise_m", 0.0)); wanted = float(config["max_pedestrian_rise_m"])
        gates["pedestrian_rise_m_max"] = {"pass": value <= wanted, "value": value, "want": wanted}

    vegetation = report.get("vegetation_areas", {})
    for config_key, report_key, gate_name in (
            ("min_vegetation_area_zones", "zones", "vegetation_area_zones_min"),
            ("min_vegetation_area_instances", "instances", "vegetation_instances_min"),
            ("min_vegetation_area_parts", "parts", "vegetation_parts_min")):
        if config_key in config:
            value = int(vegetation.get(report_key, 0))
            wanted = int(config[config_key])
            gates[gate_name] = {"pass": value >= wanted, "value": value, "want": wanted}
    if "required_vegetation_area_kinds" in config:
        actual = set((vegetation.get("by_kind") or {}).keys())
        wanted = {str(value) for value in config["required_vegetation_area_kinds"]}
        gates["required_vegetation_area_kinds"] = {
            "pass": wanted <= actual, "value": sorted(actual), "want": sorted(wanted),
        }

    residential = report.get("residential", {})
    for config_key, report_key, gate_name, cast in (
            ("min_residential_zones", "zone_count", "residential_zones_min", int),
            ("min_residential_zone_area_m2", "zone_area_m2",
             "residential_zone_area_min", float),
            ("min_residential_buildings", "building_count",
             "residential_buildings_min", int),
            ("min_residential_boundary_segments", "mapped_boundary_segments",
             "residential_boundary_segments_min", int)):
        if config_key in config:
            value = cast(residential.get(report_key, 0))
            wanted = cast(config[config_key])
            gates[gate_name] = {"pass": value >= wanted, "value": value, "want": wanted}

    stadium = report.get("football_stadium", {})
    for config_key, report_key, gate_name in (
            ("min_stadium_stand_rows", "stand_rows", "stadium_stand_rows_min"),
            ("min_stadium_stand_sections", "stand_sections", "stadium_stand_sections_min"),
            ("min_stadium_seat_modules", "seat_modules", "stadium_seat_modules_min"),
            ("min_stadium_aisle_steps", "aisle_steps", "stadium_aisle_steps_min"),
            ("min_stadium_vomitories", "vomitories", "stadium_vomitories_min"),
            ("min_stadium_roof_panels", "roof_panels", "stadium_roof_panels_min"),
            ("min_stadium_roof_supports", "roof_supports", "stadium_roof_supports_min"),
            ("min_stadium_floodlight_towers", "floodlight_towers", "stadium_floodlights_min"),
            ("min_stadium_pitch_markings", "pitch_marking_segments", "stadium_pitch_markings_min"),
            ("min_stadium_goals", "goals", "stadium_goals_min")):
        if config_key in config:
            value = int(stadium.get(report_key, 0))
            wanted = int(config[config_key])
            gates[gate_name] = {"pass": value >= wanted, "value": value, "want": wanted}

    for config_key, report_key, gate_name in (
            ("max_stadium_seat_aisle_overlap_cells", "seat_aisle_overlap_cells",
             "stadium_seat_aisle_overlap_max"),
            ("max_stadium_seat_vomitory_overlap_cells", "seat_vomitory_overlap_cells",
             "stadium_seat_vomitory_overlap_max"),
            ("max_stadium_row_rise", "max_row_rise", "stadium_row_rise_max")):
        if config_key in config:
            value = float(stadium.get(report_key, float("inf")))
            wanted = float(config[config_key])
            gates[gate_name] = {"pass": value <= wanted, "value": value, "want": wanted}

    if "min_stadium_roof_support_seat_clearance" in config:
        value = float(stadium.get("roof_support_seat_clearance", 0.0))
        wanted = float(config["min_stadium_roof_support_seat_clearance"])
        gates["stadium_roof_support_seat_clearance_min"] = {
            "pass": value >= wanted, "value": value, "want": wanted,
        }

    if "required_stadium_sides" in config:
        actual = set(stadium.get("stand_sides") or [])
        wanted = {str(value).lower() for value in config["required_stadium_sides"]}
        gates["required_stadium_sides"] = {
            "pass": wanted <= actual, "value": sorted(actual), "want": sorted(wanted),
        }

    hospital = report.get("hospital", {})
    for config_key, report_key, gate_name in (
            ("min_hospital_sites", "sites", "hospital_sites_min"),
            ("min_hospital_canopies", "entrance_canopies", "hospital_canopies_min"),
            ("min_hospital_emergency_bays", "emergency_bays", "hospital_emergency_bays_min"),
            ("min_hospital_medical_crosses", "medical_crosses", "hospital_medical_crosses_min"),
            ("min_hospital_roof_units", "roof_units", "hospital_roof_units_min"),
            ("min_hospital_helipads", "helipads", "hospital_helipads_min")):
        if config_key in config:
            value = int(hospital.get(report_key, 0))
            wanted = int(config[config_key])
            gates[gate_name] = {"pass": value >= wanted, "value": value, "want": wanted}

    highway = report.get("highway", {})
    for config_key, report_key, gate_name in (
            ("min_highway_carriageways", "carriageways", "highway_carriageways_min"),
            ("min_highway_lanes", "lanes", "highway_lanes_min"),
            ("min_highway_marking_dashes", "lane_marking_dashes", "highway_markings_min"),
            ("min_highway_edge_lines", "edge_lines", "highway_edge_lines_min"),
            ("min_highway_guardrails", "guardrail_segments", "highway_guardrails_min"),
            ("min_highway_guardrail_posts", "guardrail_posts", "highway_guardrail_posts_min"),
            ("min_highway_bridge_piers", "bridge_piers", "highway_bridge_piers_min"),
            ("min_highway_gantries", "gantries", "highway_gantries_min")):
        if config_key in config:
            value = int(highway.get(report_key, 0))
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
