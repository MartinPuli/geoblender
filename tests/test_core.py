"""
Reproducible pytest checks without Overpass or Blender. They validate pure
landmark geofencing, radius clipping, and height parsing.

Run: python3 -m pytest tests/ -q
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import citylandmarks as cl   # noqa: E402
import place_to_3d as p      # noqa: E402


def test_core_has_no_preinstalled_location_tuning():
    scripts = os.path.join(os.path.dirname(__file__), "..", "scripts")
    core = "\n".join(open(os.path.join(scripts, name), encoding="utf-8").read().lower()
                     for name in ("citylandmarks.py", "place_to_3d.py", "blender_build.py",
                                  "blocks_build.py", "blocks_eval.py"))
    banned = ("golden gate bridge", "times square", "eiffel tower",
              "sydney opera house", "heathrow airport")
    assert not any(name in core for name in banned)


def test_skills_require_constructed_blocks_not_provider_meshes():
    root = os.path.join(os.path.dirname(__file__), "..")
    contracts = [
        open(os.path.join(root, "SKILL.md"), encoding="utf-8").read().lower(),
        open(os.path.join(root, "blender-mcp-loop", "SKILL.md"),
             encoding="utf-8").read().lower(),
    ]
    for contract in contracts:
        assert "blocks_build" in contract
        assert "never" in contract and "google photorealistic 3d tiles" in contract
        assert "constructed" in contract and "geometry" in contract


def test_maps_skills_route_football_stadiums_to_specialization():
    root = os.path.join(os.path.dirname(__file__), "..")
    main = open(os.path.join(root, "SKILL.md"), encoding="utf-8").read().lower()
    live = open(os.path.join(root, "blender-mcp-loop", "SKILL.md"),
                encoding="utf-8").read().lower()
    stadium = open(os.path.join(root, "football-stadium-to-3d", "SKILL.md"),
                   encoding="utf-8").read().lower()
    assert "football-stadium-to-3d" in main and "football-stadium-to-3d" in live
    assert "scene_kind=football_stadium" in main and "stadium_detail.py" in live
    for token in ("seat modules", "vomitories", "floodlight", "held-out"):
        assert token in stadium
        assert "todo" not in stadium


def test_maps_skills_route_new_urban_specializations():
    root = os.path.join(os.path.dirname(__file__), "..")
    main = open(os.path.join(root, "SKILL.md"), encoding="utf-8").read().lower()
    live = open(os.path.join(root, "blender-mcp-loop", "SKILL.md"),
                encoding="utf-8").read().lower()
    skills = (
        "residential-neighborhood-to-3d", "signage-wayfinding-to-3d",
        "monuments-public-art-to-3d", "urban-amenities-to-3d",
        "streetscape-infrastructure-to-3d",
    )
    for skill in skills:
        body = open(os.path.join(root, skill, "SKILL.md"), encoding="utf-8").read().lower()
        assert skill in main and skill in live
        assert "scripts/urban_detail.py" in body
        assert "todo" not in body


def test_maps_skills_route_buildings_hospitals_and_highways_to_specializations():
    root = os.path.join(os.path.dirname(__file__), "..")
    main = open(os.path.join(root, "SKILL.md"), encoding="utf-8").read().lower()
    live = open(os.path.join(root, "blender-mcp-loop", "SKILL.md"),
                encoding="utf-8").read().lower()
    expected = {
        "architectural-building-to-3d": "visible interior",
        "hospital-to-3d": "emergency",
        "highway-to-3d": "guardrail",
    }
    for skill, token in expected.items():
        text = open(os.path.join(root, skill, "SKILL.md"), encoding="utf-8").read().lower()
        assert skill in main and skill in live
        assert token in text and "todo" not in text


def test_blocks_eval_defaults_are_scene_agnostic():
    import blocks_eval

    assert "min_individual_buildings" not in blocks_eval.DEFAULT_GATES
    assert "expected_feature_heights" not in blocks_eval.DEFAULT_GATES
    result = blocks_eval.evaluate_report(
        {"objects": 1},
        {"min_objects": 1, "required_files": []},
    )
    assert result["complete"]


def test_blocks_eval_supports_per_run_feature_targets():
    import blocks_eval

    result = blocks_eval.evaluate_report(
        {"objects": 4, "features": [{"id": "feature-7", "height": 12.4}]},
        {"min_objects": 1, "required_files": [],
         "expected_feature_heights": {"feature-7": 12.5},
         "feature_height_tolerance": 0.2},
    )
    assert result["complete"]


def test_blocks_eval_supports_general_facade_and_color_gates():
    import blocks_eval

    result = blocks_eval.evaluate_report(
        {"objects": 8, "building_appearance": {
            "facade_shader_buildings": 4,
            "facade_geometry_buildings": 2,
            "facade_window_panels": 120,
            "color_sources": {"osm:building:colour": 1, "material_prior": 3},
            "facade_color_confidence_mean": 0.7,
            "roof_color_confidence_mean": 0.6,
        }, "construction_detail": {
            "building_parts": 3, "bands": 24, "entrances": 2,
        }},
        {"min_objects": 1, "required_files": [],
         "min_facade_shader_buildings": 4,
         "min_facade_geometry_buildings": 2,
         "min_facade_window_panels": 100,
         "required_color_sources": ["osm:building:colour", "material_prior"],
         "min_facade_color_confidence_mean": 0.65,
         "min_roof_color_confidence_mean": 0.55,
         "min_building_parts": 3,
         "min_construction_bands": 20,
         "min_entrances": 2},
    )
    assert result["complete"]


def test_blocks_eval_supports_covered_and_urban_detail_gates():
    import blocks_eval

    result = blocks_eval.evaluate_report(
        {"objects": 12,
         "covered_structures": {"count": 2, "columns": 12, "edge_beams": 8},
         "urban_objects": {"count": 4, "parts": 17,
                           "by_kind": {"tree": 2, "bench": 1, "street_lamp": 1}}},
        {"min_objects": 1, "required_files": [],
         "min_covered_structures": 2, "min_cover_columns": 8,
         "min_cover_edge_beams": 4, "min_urban_objects": 4,
         "min_urban_object_parts": 12,
         "required_urban_object_kinds": ["tree", "bench", "street_lamp"]},
    )
    assert result["complete"]


def test_blocks_eval_supports_new_urban_and_residential_gates():
    import blocks_eval

    report = {
        "objects": 80,
        "urban_detail": {
            "count": 12, "parts": 74, "text_objects": 3,
            "explicit_directions": 4, "explicit_dimensions": 2,
            "wall_hosted": 1, "road_hosted": 1,
            "by_sign_shape": {"octagon": 1, "circle": 1},
            "by_family": {"signage": 4, "public_art": 3, "recreation": 2,
                          "street_furniture": 3},
        },
        "residential": {"zone_count": 1, "zone_area_m2": 5400,
                        "building_count": 8, "mapped_boundary_segments": 14},
        "streetscape": {"lane_arrows": 5, "kerb_segments": 4,
                        "traffic_islands": 2, "tree_rows": 1,
                        "utility_lines": 1, "utility_conductors": 3,
                        "stop_lines": 2, "lane_dividers": 1,
                        "cycle_lanes": 2, "cycle_lane_m": 84.0,
                        "cycle_lane_separators": 2,
                        "cycle_protection_elements": 12},
        "utility_networks": {"substations": 1, "transformers": 2,
                             "telecom_poles": 2, "telecom_cabinets": 1,
                             "communication_lines": 1,
                             "communication_conductors": 2,
                             "metadata_only_lines": 1},
        "vegetation_areas": {"zones": 2, "instances": 28, "parts": 52,
                             "by_kind": {"woodland": 20, "tree_row": 8}},
    }
    gates = {
        "min_objects": 1, "required_files": [],
        "min_urban_detail_objects": 10, "min_urban_detail_parts": 60,
        "min_urban_text_objects": 2, "min_urban_explicit_directions": 3,
        "min_urban_explicit_dimensions": 2,
        "min_urban_wall_hosted": 1,
        "min_urban_road_hosted": 1,
        "required_urban_sign_shapes": ["octagon", "circle"],
        "required_urban_families": ["signage", "public_art", "recreation"],
        "min_residential_zones": 1, "min_residential_zone_area_m2": 5000,
        "min_residential_buildings": 6, "min_residential_boundary_segments": 10,
        "min_streetscape_lane_arrows": 4,
        "min_streetscape_kerb_segments": 3,
        "min_streetscape_traffic_islands": 2,
        "min_streetscape_tree_rows": 1,
        "min_streetscape_utility_lines": 1,
        "min_streetscape_utility_conductors": 3,
        "min_streetscape_stop_lines": 2,
        "min_streetscape_lane_dividers": 1,
        "min_streetscape_cycle_lanes": 2,
        "min_streetscape_cycle_lane_m": 80,
        "min_streetscape_cycle_lane_separators": 2,
        "min_streetscape_cycle_protection_elements": 10,
        "min_utility_substations": 1,
        "min_utility_transformers": 2,
        "min_utility_telecom_poles": 2,
        "min_utility_telecom_cabinets": 1,
        "min_utility_communication_lines": 1,
        "min_utility_communication_conductors": 2,
        "min_utility_metadata_only_lines": 1,
        "min_vegetation_area_zones": 2,
        "min_vegetation_area_instances": 20,
        "min_vegetation_area_parts": 40,
        "required_vegetation_area_kinds": ["woodland", "tree_row"],
    }
    assert blocks_eval.evaluate_report(report, gates)["complete"]


def test_blocks_eval_enforces_accessibility_counts_and_height_caps():
    import blocks_eval

    report = {"objects": 12, "streetscape": {
        "sidewalk_strips": 2, "sidewalk_m": 120.0,
        "sidewalk_metadata_profiles": 1, "sidewalk_kerb_edges": 2,
        "curb_ramps": 2, "raised_crossings": 1, "speed_tables": 1,
        "curb_ramp_max_height": 0.025,
        "raised_crossing_max_height": 0.10,
    }}
    config = {"min_objects": 1, "required_files": [],
              "min_streetscape_sidewalk_strips": 2,
              "min_streetscape_sidewalk_m": 100,
              "min_streetscape_sidewalk_metadata_profiles": 1,
              "min_streetscape_sidewalk_kerb_edges": 2,
              "min_streetscape_curb_ramps": 2,
              "min_streetscape_raised_crossings": 1,
              "min_streetscape_speed_tables": 1,
              "max_streetscape_curb_ramp_height": 0.03,
              "max_streetscape_raised_crossing_height": 0.12}
    assert blocks_eval.evaluate_report(report, config)["complete"]
    report["streetscape"]["curb_ramp_max_height"] = 0.08
    result = blocks_eval.evaluate_report(report, config)
    assert not result["complete"]
    assert not result["gates"]["streetscape_curb_ramp_height_max"]["pass"]


def test_blocks_eval_supports_football_stadium_detail_gates():
    import blocks_eval

    report = {"objects": 20, "football_stadium": {
        "stand_rows": 56, "stand_sections": 420, "seat_modules": 5200,
        "aisle_steps": 300,
        "vomitories": 6, "roof_panels": 2, "roof_supports": 16,
        "floodlight_towers": 4, "pitch_marking_segments": 80,
        "goals": 2, "stand_sides": ["north", "south", "east", "west"],
        "seat_aisle_overlap_cells": 0, "seat_vomitory_overlap_cells": 0,
        "max_row_rise": 0.56, "roof_support_seat_clearance": 0.45,
    }}
    gates = {"min_objects": 1, "required_files": [],
             "min_stadium_stand_rows": 50,
             "min_stadium_stand_sections": 300,
             "min_stadium_seat_modules": 5000,
             "min_stadium_aisle_steps": 200,
             "min_stadium_vomitories": 4,
             "min_stadium_roof_panels": 2,
             "min_stadium_roof_supports": 12,
             "min_stadium_floodlight_towers": 4,
             "min_stadium_pitch_markings": 70,
             "min_stadium_goals": 2,
             "max_stadium_seat_aisle_overlap_cells": 0,
             "max_stadium_seat_vomitory_overlap_cells": 0,
             "max_stadium_row_rise": 0.62,
             "min_stadium_roof_support_seat_clearance": 0.35,
             "required_stadium_sides": ["north", "south", "east", "west"]}
    assert blocks_eval.evaluate_report(report, gates)["complete"]


def test_blocks_eval_supports_architecture_hospital_and_highway_gates():
    import blocks_eval

    report = {
        "objects": 40,
        "building_appearance": {
            "facade_profiles": {"residential": 2, "commercial": 1},
            "facade_variants": ["residential:1", "residential:3", "commercial:2"],
            "facade_window_mullions": 90, "visible_interior_bays": 120,
            "lit_interior_rooms": 42, "symmetric_window_pairs": 60,
            "balconies": 12, "facade_accent_parts": 85,
        },
        "hospital": {"sites": 1, "entrance_canopies": 1, "emergency_bays": 1,
                     "medical_crosses": 1, "roof_units": 5, "helipads": 1},
        "highway": {"carriageways": 2, "lanes": 6, "lane_marking_dashes": 80,
                    "edge_lines": 8, "guardrail_segments": 8,
                    "guardrail_posts": 90, "bridge_piers": 4, "gantries": 2},
        "building_interiors": {"buildings": 6, "floor_slabs": 30,
                               "corridor_segments": 40, "partitions": 110,
                               "cores": 20},
    }
    gates = {
        "min_objects": 1, "required_files": [], "min_facade_profiles": 2,
        "min_facade_variants": 3, "min_facade_window_mullions": 80,
        "min_visible_interior_bays": 100, "min_lit_interior_rooms": 30,
        "min_symmetric_window_pairs": 50, "min_balconies": 10,
        "min_facade_accent_parts": 80,
        "min_interior_layout_buildings": 6, "min_interior_floor_slabs": 30,
        "min_interior_corridor_segments": 40, "min_interior_partitions": 100,
        "min_interior_cores": 20,
        "min_hospital_sites": 1, "min_hospital_canopies": 1,
        "min_hospital_emergency_bays": 1, "min_hospital_medical_crosses": 1,
        "min_hospital_roof_units": 4, "min_hospital_helipads": 1,
        "min_highway_carriageways": 2, "min_highway_lanes": 6,
        "min_highway_marking_dashes": 60, "min_highway_edge_lines": 8,
        "min_highway_guardrails": 8, "min_highway_guardrail_posts": 80,
        "min_highway_bridge_piers": 4, "min_highway_gantries": 2,
    }
    assert blocks_eval.evaluate_report(report, gates)["complete"]


def test_scene_kind_detects_football_stadium_from_osm_semantics():
    osm = {"elements": [
        {"tags": {"leisure": "stadium", "sport": "soccer"}},
        {"tags": {"leisure": "pitch", "sport": "soccer"}},
    ]}
    assert p.classify_scene_kind(osm) == "football_stadium"
    assert p.classify_scene_kind({"elements": [
        {"tags": {"leisure": "stadium"}}]}) == "stadium"
    assert p.classify_scene_kind({"elements": [
        {"tags": {"leisure": "pitch", "sport": "soccer"}}]}) == "urban"


def test_scene_specializations_detect_hospital_highway_and_architecture_semantically():
    osm = {"elements": [
        {"tags": {"building": "yes", "amenity": "hospital"}},
        {"tags": {"highway": "motorway", "lanes": "3"}},
    ]}
    kinds = p.classify_scene_specializations(osm)
    assert {"hospital", "highway", "architectural_buildings"} <= set(kinds)
    assert p.classify_scene_kind(osm) == "hospital"
    assert p.classify_scene_specializations({"elements": [
        {"tags": {"building": "yes", "name": "Hospitality House"}}]}) == [
            "architectural_buildings"]


def test_osm_highway_preserves_lane_bridge_and_width_provenance():
    project = p.make_projector(0.0, 0.0)
    data = {"elements": [{
        "type": "way", "id": 819,
        "tags": {"highway": "motorway", "lanes": "3", "oneway": "yes",
                 "bridge": "viaduct", "width": "13.2 m", "ref": "A1"},
        "geometry": [
            {"lat": 0.0, "lon": 0.0}, {"lat": 0.001, "lon": 0.001}],
    }]}
    _, roads, _ = p.parse_osm(data, project)
    road = roads[0]
    assert road["osm_id"] == 819 and road["lanes"] == 3
    assert road["oneway"] == "yes" and road["bridge"]
    assert road["width"] == 13.2 and road["width_source"] == "explicit"


def test_osm_pitch_area_preserves_sport_identity_and_provenance():
    project = p.make_projector(0.0, 0.0)
    data = {"elements": [{
        "type": "way", "id": 712,
        "tags": {"leisure": "pitch", "sport": "soccer", "surface": "grass"},
        "geometry": [
            {"lat": 0.0, "lon": 0.0}, {"lat": 0.0, "lon": 0.001},
            {"lat": 0.0006, "lon": 0.001}, {"lat": 0.0006, "lon": 0.0},
            {"lat": 0.0, "lon": 0.0}],
    }]}
    _, _, areas = p.parse_osm(data, project)
    assert areas[0]["type"] == "pitch" and areas[0]["sport"] == "soccer"
    assert areas[0]["osm_id"] == 712 and areas[0]["source"] == "osm"


def test_overpass_query_requests_stadium_sites_and_relations():
    query = p.build_overpass_query(-1, -1, 1, 1)
    assert "stadium" in query
    assert 'relation["leisure"~"^(pitch|stadium)$"]' in query


def test_overpass_query_requests_hospital_and_clinic_semantics():
    query = p.build_overpass_query(-1, -1, 1, 1)
    assert 'nwr["amenity"~"^(hospital|clinic)$"]' in query
    assert 'nwr["healthcare"~"^(hospital|clinic|centre|center)$"]' in query


def test_roof_only_height_keeps_open_clearance():
    top, underside = p.parse_height({"building": "roof"})
    assert p.structure_mode({"building": "roof"}) == "roof_only"
    assert underside >= 2.2
    assert 0.18 <= top - underside <= 0.6
    explicit_top, explicit_under = p.parse_height(
        {"building:part": "roof", "height": "5.2", "min_height": "4.8"})
    assert explicit_top == 5.2 and explicit_under == 4.8


def test_osm_parser_marks_open_cover_without_name_rules():
    project = p.make_projector(0.0, 0.0)
    data = {"elements": [{
        "type": "way", "id": 42,
        "tags": {"building": "roof", "name": "Arbitrary"},
        "geometry": [
            {"lat": 0.0, "lon": 0.0}, {"lat": 0.0, "lon": 0.0001},
            {"lat": 0.0001, "lon": 0.0001}, {"lat": 0.0001, "lon": 0.0},
            {"lat": 0.0, "lon": 0.0},
        ],
    }]}
    buildings, _, _ = p.parse_osm(data, project)
    assert buildings[0]["structure_mode"] == "roof_only"
    assert buildings[0]["covered"] is True
    assert buildings[0]["min_height"] > 0


def test_special_features_capture_covered_areas_and_urban_objects():
    project = p.make_projector(0.0, 0.0)
    data = {"elements": [
        {"type": "way", "id": 7, "tags": {"covered": "yes"},
         "geometry": [
             {"lat": 0.0, "lon": 0.0}, {"lat": 0.0, "lon": 0.0001},
             {"lat": 0.0001, "lon": 0.0001}, {"lat": 0.0001, "lon": 0.0},
             {"lat": 0.0, "lon": 0.0}]},
        {"type": "node", "id": 8, "lat": 0.0, "lon": 0.0,
         "tags": {"amenity": "bench"}},
        {"type": "node", "id": 9, "lat": 0.0, "lon": 0.0001,
         "tags": {"natural": "tree", "height": "9"}},
    ]}
    features = p.parse_special_features(data, project)
    cover = next(item for item in features if item.get("family") == "covered_structure")
    kinds = {item.get("kind") for item in features}
    assert cover["structure_mode"] == "roof_only" and cover["min_height"] > 0
    assert {"bench", "tree"} <= kinds


def test_open_covered_highway_is_not_misread_as_roof_polygon():
    project = p.make_projector(0.0, 0.0)
    data = {"elements": [{
        "type": "way", "id": 99,
        "tags": {"highway": "footway", "covered": "yes"},
        "geometry": [
            {"lat": 0.0, "lon": 0.0}, {"lat": 0.0, "lon": 0.0001},
            {"lat": 0.0, "lon": 0.0002}, {"lat": 0.0, "lon": 0.0003},
        ],
    }]}
    features = p.parse_special_features(data, project)
    assert not any(item.get("family") == "covered_structure" for item in features)


def test_overpass_query_requests_covered_areas_and_urban_objects():
    query = p.build_overpass_query(-1, -1, 1, 1)
    for token in ('["covered"', '"street_lamp"', 'bench', '"natural"="tree"'):
        assert token in query


def test_overpass_query_requests_residential_signage_art_and_amenities():
    query = p.build_overpass_query(-1, -1, 1, 1)
    for token in ('village_green|residential|allotments|garages',
                  '["traffic_sign"]', '["advertising"]', '["tourism"="artwork"]',
                  '["historic"~"^(memorial|monument)$"]',
                  '["emergency"~"^(fire_hydrant|defibrillator)$"]',
                  '["highway"~"^(traffic_signals|bus_stop|crossing)$"]',
                  'parking_meter|charging_station|vending_machine|parcel_locker|atm',
                  '["playground"]'):
        assert token in query


def test_overpass_query_requests_streetscape_vegetation_and_utility_evidence():
    query = p.build_overpass_query(-1, -1, 1, 1)
    for token in ('["barrier"="kerb"]', '["traffic_calming"',
                  '["area:highway"="traffic_island"]',
                  '["natural"="tree_row"]', 'forest|meadow|orchard',
                  '["power"~"^(line|minor_line)$"]',
                  '["power"~"^(pole|tower)$"]',
                  '["power"="substation"]', '["power"="transformer"]',
                  '["communication"="line"]', '["man_made"="utility_pole"]',
                  '["road_marking"]'):
        assert token in query


def test_overpass_query_and_normalizer_capture_fluid_network_evidence():
    query = p.build_overpass_query(-1, -1, 1, 1)
    for token in ('["man_made"="pipeline"]',
                  '["pipeline"~"^(valve|measurement)$"]',
                  '["man_made"="pumping_station"]',
                  '["man_made"="manhole"]', '["inlet"]',
                  'power|telecom|water|gas|sewerage|heating'):
        assert token in query
    project = p.make_projector(0.0, 0.0)
    data = {"elements": [
        {"type": "way", "id": 501,
         "tags": {"man_made": "pipeline", "location": "overhead",
                  "diameter": "450 mm", "substance": "water"},
         "geometry": [{"lat": 0.0, "lon": 0.0},
                      {"lat": 0.0, "lon": 0.001}]},
        {"type": "node", "id": 502, "lat": 0.0, "lon": 0.0,
         "tags": {"pipeline": "valve", "substance": "water"}},
        {"type": "node", "id": 504, "lat": 0.0, "lon": 0.0002,
         "tags": {"man_made": "manhole", "manhole": "drain",
                  "inlet": "grate", "utility": "sewerage"}},
        {"type": "node", "id": 505, "lat": 0.0, "lon": 0.0003,
         "tags": {"man_made": "street_cabinet", "utility": "water"}},
    ]}
    features = p.parse_special_features(data, project)
    pipeline = next(item for item in features if item.get("kind") == "pipeline")
    valve = next(item for item in features if item.get("kind") == "pipeline_valve")
    drain = next(item for item in features if item.get("kind") == "drainage_inlet")
    cabinet = next(item for item in features if item.get("kind") == "fluid_cabinet")
    assert pipeline["family"] == "fluid_network" and pipeline["location"] == "overhead"
    assert valve["family"] == "fluid_network" and valve["substance"] == "water"
    assert drain["inlet"] == "grate" and drain["utility"] == "sewerage"
    assert cabinet["family"] == "fluid_network" and cabinet["utility"] == "water"


def test_road_normalizer_preserves_bus_lane_and_street_parking_positions():
    project = p.make_projector(0.0, 0.0)
    data = {"elements": [{
        "type": "way", "id": 503,
         "tags": {"highway": "primary", "lanes": "3", "oneway": "yes",
                 "bus:lanes": "yes|yes|designated",
                 "parking:left": "lane",
                 "parking:left:orientation": "parallel",
                 "parking:left:width": "2.2", "sidewalk:both": "yes",
                 "sidewalk:left:width": "2.0",
                 "sidewalk:right:kerb": "lowered"},
        "geometry": [{"lat": 0.0, "lon": 0.0},
                     {"lat": 0.0, "lon": 0.001}],
    }]}
    _, roads, _ = p.parse_osm(data, project)
    assert roads[0]["bus_lanes"] == "yes|yes|designated"
    assert roads[0]["parking_left"] == "lane"
    assert roads[0]["parking_left_orientation"] == "parallel"
    assert roads[0]["parking_left_width"] == "2.2"
    assert roads[0]["sidewalk_both"] == "yes"
    assert roads[0]["sidewalk_left_width"] == "2.0"
    assert roads[0]["sidewalk_right_kerb"] == "lowered"


def test_accessibility_points_preserve_kerb_table_and_tactile_evidence():
    query = p.build_overpass_query(-1, -1, 1, 1)
    assert 'node["barrier"="kerb"]' in query
    assert 'island|painted_island|table' in query
    project = p.make_projector(0.0, 0.0)
    data = {"elements": [
        {"type": "node", "id": 506, "lat": 0.0, "lon": 0.0,
         "tags": {"barrier": "kerb", "kerb": "lowered",
                  "kerb:height": "2 cm", "tactile_paving": "yes"}},
        {"type": "node", "id": 507, "lat": 0.0, "lon": 0.0001,
         "tags": {"highway": "crossing", "traffic_calming": "table",
                  "crossing:markings": "zebra", "wheelchair": "yes"}},
    ]}
    features = p.parse_special_features(data, project)
    ramp = next(item for item in features if item.get("kind") == "curb_ramp")
    table = next(item for item in features if item.get("kind") == "raised_crossing")
    assert ramp["height"] == 0.02 and ramp["tactile_paving"] == "yes"
    assert table["traffic_calming"] == "table" and table["wheelchair"] == "yes"


def test_special_features_normalize_signage_art_amenities_and_dimensions():
    project = p.make_projector(0.0, 0.0)
    data = {"elements": [
        {"type": "node", "id": 101, "lat": 0, "lon": 0,
         "tags": {"advertising": "billboard", "size": "6*3", "height": "7",
                  "direction": "E", "name": "Explicit"}},
        {"type": "node", "id": 102, "lat": 0, "lon": 0.0001,
         "tags": {"historic": "memorial", "memorial": "statue", "height": "4.5"}},
        {"type": "node", "id": 103, "lat": 0, "lon": 0.0002,
         "tags": {"emergency": "fire_hydrant"}},
        {"type": "node", "id": 104, "lat": 0, "lon": 0.0003,
         "tags": {"playground": "slide"}},
        {"type": "node", "id": 105, "lat": 0, "lon": 0.0004,
         "tags": {"highway": "bus_stop", "ref": "42", "shelter": "yes",
                  "bench": "yes", "bin": "yes",
                  "passenger_information_display": "yes"}},
    ]}
    features = p.parse_special_features(data, project)
    by_kind = {item["kind"]: item for item in features}
    assert by_kind["billboard"]["panel_size"] == [6.0, 3.0]
    assert by_kind["billboard"]["direction"] == 90.0
    assert by_kind["statue"]["family"] == "public_art"
    assert by_kind["fire_hydrant"]["width"] < 0.5
    assert by_kind["slide"]["family"] == "recreation"
    assert by_kind["bus_stop"]["shelter"] == "yes"
    assert by_kind["bus_stop"]["passenger_information_display"] == "yes"


def test_only_physical_traffic_sign_nodes_become_sign_geometry():
    project = p.make_projector(0.0, 0.0)
    data = {"elements": [
        {"type": "node", "id": 201, "lat": 0, "lon": 0,
         "tags": {"traffic_sign": "maxspeed", "maxspeed": "40"}},
        {"type": "way", "id": 202,
         "geometry": [{"lat": 0, "lon": 0}, {"lat": 0, "lon": 0.001}],
         "tags": {"traffic_sign": "maxspeed", "maxspeed": "40"}},
    ]}
    features = p.parse_special_features(data, project)
    signs = [item for item in features if item.get("kind") == "traffic_sign"]
    assert len(signs) == 1 and signs[0]["osm_type"] == "node"
    assert signs[0]["traffic_sign"] == "maxspeed"


def test_special_features_normalize_streetscape_lines_and_islands():
    project = p.make_projector(0.0, 0.0)
    line = [{"lat": 0.0, "lon": 0.0}, {"lat": 0.0, "lon": 0.0001},
            {"lat": 0.0, "lon": 0.0002}]
    island = [{"lat": 0.00002, "lon": 0.00002},
              {"lat": 0.00002, "lon": 0.00005},
              {"lat": 0.00004, "lon": 0.00005},
              {"lat": 0.00004, "lon": 0.00002},
              {"lat": 0.00002, "lon": 0.00002}]
    data = {"elements": [
        {"type": "way", "id": 301, "geometry": line,
         "tags": {"barrier": "kerb", "kerb": "lowered"}},
        {"type": "way", "id": 302, "geometry": line,
         "tags": {"natural": "tree_row", "height": "9"}},
        {"type": "way", "id": 303, "geometry": line,
         "tags": {"power": "minor_line", "cables": "3"}},
        {"type": "way", "id": 304, "geometry": island,
         "tags": {"area:highway": "traffic_island", "surface": "paving_stones"}},
        {"type": "node", "id": 305, "lat": 0, "lon": 0.0003,
         "tags": {"traffic_calming": "island"}},
        {"type": "node", "id": 306, "lat": 0, "lon": 0.0004,
         "tags": {"power": "tower", "height": "28"}},
    ]}
    features = p.parse_special_features(data, project)
    by_kind = {}
    for item in features:
        by_kind.setdefault(item["kind"], []).append(item)
    assert by_kind["kerb"][0]["height"] == 0.0
    assert by_kind["tree_row"][0]["height"] == 9.0
    assert by_kind["overhead_power_line"][0]["cables"] == "3"
    assert by_kind["traffic_island"][0]["geometry"] == "surface"
    assert any(item["geometry"] == "point" for item in by_kind["traffic_island"])
    assert by_kind["power_tower"][0]["height"] == 28.0


def test_special_features_normalize_markings_and_technical_networks():
    project = p.make_projector(0.0, 0.0)
    line = [{"lat": 0.0, "lon": 0.0}, {"lat": 0.0, "lon": 0.0002}]
    cross = [{"lat": -0.00001, "lon": 0.00008},
             {"lat": 0.00001, "lon": 0.00008}]
    area = [{"lat": 0.0001, "lon": 0.0}, {"lat": 0.0001, "lon": 0.0001},
            {"lat": 0.0002, "lon": 0.0001}, {"lat": 0.0002, "lon": 0.0},
            {"lat": 0.0001, "lon": 0.0}]
    data = {"elements": [
        {"type": "way", "id": 501, "geometry": cross,
         "tags": {"road_marking": "stop_line", "stroke": "solid"}},
        {"type": "way", "id": 502, "geometry": line,
         "tags": {"road_marking": "lane_divider", "stroke": "dashed"}},
        {"type": "node", "id": 503, "lat": 0, "lon": 0.0001,
         "tags": {"road_marking": "stop_line", "direction": "forward"}},
        {"type": "way", "id": 504, "geometry": area,
         "tags": {"power": "substation", "substation": "distribution",
                  "voltage": "13200;400"}},
        {"type": "node", "id": 505, "lat": 0.00015, "lon": 0.00005,
         "tags": {"power": "transformer", "transformer": "distribution"}},
        {"type": "node", "id": 506, "lat": 0, "lon": 0.00025,
         "tags": {"man_made": "utility_pole", "utility": "telecom"}},
        {"type": "node", "id": 507, "lat": 0, "lon": 0.0003,
         "tags": {"man_made": "street_cabinet", "utility": "telecom"}},
        {"type": "way", "id": 508, "geometry": line,
         "tags": {"communication": "line", "location": "overhead",
                  "telecom:medium": "fibre", "cables": "2"}},
        {"type": "way", "id": 509, "geometry": line,
         "tags": {"communication": "line", "location": "underground"}},
    ]}
    features = p.parse_special_features(data, project)
    by_kind = {}
    for item in features:
        by_kind.setdefault(item["kind"], []).append(item)
    assert len(by_kind["stop_line"]) == 2
    assert {item["geometry"] for item in by_kind["stop_line"]} == {"line", "point"}
    assert by_kind["lane_divider"][0]["stroke"] == "dashed"
    assert by_kind["power_substation"][0]["geometry"] == "surface"
    assert by_kind["power_transformer"][0]["transformer"] == "distribution"
    assert by_kind["telecom_pole"][0]["utility"] == "telecom"
    assert by_kind["telecom_cabinet"][0]["utility"] == "telecom"
    assert {item["location"] for item in by_kind["communication_line"]} == {
        "overhead", "underground"}


def test_roads_keep_explicit_turn_lane_and_vegetation_area_semantics():
    project = p.make_projector(0.0, 0.0)
    road = [{"lat": 0.0, "lon": 0.0}, {"lat": 0.0, "lon": 0.0002}]
    orchard = [{"lat": 0.0001, "lon": 0.0}, {"lat": 0.0001, "lon": 0.0002},
               {"lat": 0.0003, "lon": 0.0002}, {"lat": 0.0003, "lon": 0.0},
               {"lat": 0.0001, "lon": 0.0}]
    data = {"elements": [
        {"type": "way", "id": 401, "geometry": road,
         "tags": {"highway": "primary", "lanes": "2", "oneway": "yes",
                  "turn:lanes": "left|through;right", "cycleway:right": "lane",
                  "cycleway:right:width": "1.8", "cycleway:right:buffer": "0.5",
                  "cycleway:right:separation": "bollard"}},
        {"type": "way", "id": 402, "geometry": orchard,
         "tags": {"landuse": "orchard", "leaf_type": "broadleaved"}},
    ]}
    _, roads, areas = p.parse_osm(data, project)
    assert roads[0]["turn_lanes"] == "left|through;right"
    assert roads[0]["lanes"] == 2
    assert roads[0]["cycleway_right"] == "lane"
    assert roads[0]["cycleway_right_width"] == "1.8"
    assert roads[0]["cycleway_right_buffer"] == "0.5"
    assert roads[0]["cycleway_right_separation"] == "bollard"
    assert areas[0]["type"] == "orchard"
    assert areas[0]["leaf_type"] == "broadleaved"


def test_scene_specializations_route_urban_families():
    osm = {"elements": [
        {"tags": {"landuse": "residential"}},
        {"tags": {"traffic_sign": "street_name"}},
        {"tags": {"tourism": "artwork", "artwork_type": "sculpture"}},
        {"tags": {"amenity": "bench"}},
        {"tags": {"barrier": "kerb"}},
        {"tags": {"power": "minor_line"}},
    ]}
    values = set(p.classify_scene_specializations(osm))
    assert {"residential_neighborhood", "signage_wayfinding",
            "monuments_public_art", "urban_amenities",
            "streetscape_infrastructure"} <= values


# --- F1a: core contains no cities; external packs are opt-in ---
def test_core_landmark_registry_is_empty():
    assert cl.LANDMARKS == []
    assert cl.landmarks_for_center(0.0, 0.0) == []


def test_explicit_landmark_pack_can_be_geofenced():
    pack = [{"key": "sample", "lat": 10.0, "lon": 20.0,
             "radius_m": 100.0, "match_names": ["sample monument"]}]
    assert [x["key"] for x in cl.landmarks_for_center(10.0, 20.0, pack)] == ["sample"]
    assert cl.landmarks_for_center(11.0, 20.0, pack) == []


def test_name_match_gate():
    lm = {"match_names": ["sample monument"]}
    assert cl.name_matches(lm, "Sample Monument")
    assert not cl.name_matches(lm, "Unrelated Feature")


# --- Clipping keeps geometry inside the requested radius ---
def test_clip_polygon_within_radius():
    H = 100.0
    clipped = p.clip_polygon([(-500, -500), (500, -500), (500, 500), (-500, 500)], H)
    assert clipped
    for x, y in clipped:
        assert -H - 1e-6 <= x <= H + 1e-6
        assert -H - 1e-6 <= y <= H + 1e-6


def test_clip_segment_outside_none():
    assert p.clip_segment((200, 200), (300, 300), 100.0) is None


def test_clip_segment_inside_kept():
    assert p.clip_segment((-10, 0), (10, 0), 100.0) is not None


# --- Heights use real scale: one unit equals one meter ---
def test_parse_height_levels():
    h, _ = p.parse_height({"building:levels": "4"})
    assert abs(h - 4 * p.LEVEL_HEIGHT) < 1e-6


def test_parse_height_explicit():
    h, _ = p.parse_height({"height": "25 m"})
    assert abs(h - 25.0) < 1e-6


# --- F1b: camera never starts inside a building ---
def test_camera_moves_out_of_building():
    import citycamera as cam
    scene = {
        "buildings": [{"footprint": [(-10, -10), (10, -10), (10, 10), (-10, 10)]}],
        "roads": [{"path": [[0, -40], [0, -15]], "z": 0.06}],
    }
    (x, y), moved = cam.safe_street_point(scene, 0.0, 0.0)  # origin is inside building
    assert moved
    assert not cam.inside_any_building(scene["buildings"], x, y)


def test_camera_stays_if_already_safe():
    import citycamera as cam
    scene = {"buildings": [{"footprint": [(-10, -10), (10, -10), (10, 10), (-10, 10)]}],
             "roads": []}
    (x, y), moved = cam.safe_street_point(scene, 50.0, 50.0)  # already outside
    assert not moved and (x, y) == (50.0, 50.0)


# --- F2a: per-building provenance and confidence ---
def test_height_source_classification():
    assert p.height_source({"height": "30 m"}) == "explicit"
    assert p.height_source({"building:levels": "5"}) == "levels"
    assert p.height_source({"building": "yes"}) == "default"


def test_confidence_ordering():
    c_expl = p.building_confidence({"height": "30 m"})
    c_lvl = p.building_confidence({"building:levels": "5"})
    c_def = p.building_confidence({"building": "yes"})
    assert c_expl > c_lvl > c_def          # better OSM data means higher confidence
    assert 0.0 <= c_def <= c_expl <= 1.0
    # A name adds a small amount of confidence.
    assert p.building_confidence({"height": "30 m", "name": "Tower X"}) > c_expl


def test_building_appearance_preserves_explicit_osm_color():
    appearance = p.building_appearance({
        "building": "office", "building:colour": "#336699",
        "building:material": "glass", "roof:colour": "#884422",
        "building:levels": "8", "roof:shape": "flat",
    })
    assert appearance["color_source"] == "osm:building:colour"
    assert appearance["roof_color_source"] == "osm:roof:colour"
    assert appearance["levels"] == 8
    assert appearance["building_material"] == "glass"
    assert appearance["color_confidence"] > 0.9
    assert appearance["roof_color_confidence"] > 0.9


def test_building_appearance_uses_material_then_semantic_prior():
    brick = p.building_appearance({"building": "yes", "building:material": "brick"})
    office = p.building_appearance({"building": "office"})
    assert brick["color_source"] == "material_prior"
    assert office["color_source"] == "semantic_prior"
    assert brick["color_confidence"] > office["color_confidence"]
    assert brick["color"] != office["color"]


# --- F2c: per-building roof variety from roof:shape plus fallback ---
def test_roof_tag_respected():
    import cityroofs as cr
    assert cr.choose_roof_kind("gabled", 8) == "gabled"
    assert cr.choose_roof_kind("onion", 40) == "dome"      # onion -> dome
    assert cr.choose_roof_kind("flat", 40) == "flat"
    assert cr.choose_roof_kind("skillion", 6) == "skillion"
    assert cr.choose_roof_kind("mansard", 9) == "hipped"


def test_roof_default_variety():
    import cityroofs as cr
    # Untagged low-rises receive at least two pitched-roof types across seeds.
    low = {cr.choose_roof_kind(None, 8, seed=s * 3.1) for s in range(80)}
    assert low <= set(cr.ROOF_KINDS)
    assert len(low & {"hipped", "gabled", "pyramidal", "skillion"}) >= 2
    # Untagged high-rises use flat roofs, never pitched roofs.
    tall = {cr.choose_roof_kind(None, 45, seed=s * 2.3) for s in range(80)}
    assert tall <= {"parapet", "flat"}


# --- F3a: architectural profiles ---
def test_profile_classification_synthetic():
    import cityprofiles as cp
    towers = [{"height": 90, "roof_shape": None, "type": "yes"} for _ in range(20)]
    assert cp.classify_profile(towers) == "modern_towers"
    historic = [{"height": 7, "roof_shape": "gabled", "type": "house"} for _ in range(20)]
    assert cp.classify_profile(historic) == "historic_center"
    informal = [{"height": 4, "roof_shape": None, "type": "yes"} for _ in range(20)]
    assert cp.classify_profile(informal) == "informal_dense"
    assert cp.classify_profile([]) == "mixed"
    d = cp.profile_defaults("modern_towers")
    assert d["roof_bias"] == "flat" and d["default_height"] > 15


def test_roof_bias_applies_without_tag():
    import cityroofs as cr
    # A historic profile biases untagged low-rise buildings toward gabled roofs.
    kinds = {cr.choose_roof_kind(None, 8, seed=s * 1.7, bias="gabled") for s in range(40)}
    assert "gabled" in kinds
    # Explicit OSM tags always override the profile bias.
    assert cr.choose_roof_kind("hipped", 8, bias="gabled") == "hipped"


# --- Special airport layers do not degrade into generic roads ---
def test_overpass_query_requests_airport_layers():
    query = p.build_overpass_query(-1, -1, 1, 1)
    assert '"aeroway"' in query
    assert "runway" in query and "taxiway" in query and "apron" in query


def test_overpass_query_requests_simple_3d_building_parts():
    query = p.build_overpass_query(-1, -1, 1, 1)
    assert 'way["building:part"]' in query
    assert 'relation["building:part"]' in query


def test_building_parts_replace_containing_outline():
    outline = {"footprint": [[0, 0], [20, 0], [20, 20], [0, 20]],
               "osm_id": 1, "is_building_part": False}
    low_part = {"footprint": [[0, 0], [12, 0], [12, 20], [0, 20]],
                "osm_id": 2, "is_building_part": True,
                "building_part": "yes", "min_height": 0.0}
    tower_part = {"footprint": [[12, 0], [20, 0], [20, 20], [12, 20]],
                  "osm_id": 3, "is_building_part": True,
                  "building_part": "yes", "min_height": 4.0}
    resolved, suppressed = p.resolve_building_parts(
        [outline, low_part, tower_part])
    assert suppressed == 1
    assert outline not in resolved
    assert {item["osm_id"] for item in resolved} == {2, 3}
    assert low_part["outline_osm_id"] == 1
    assert low_part["detail_anchor"] is True
    assert not tower_part.get("detail_anchor", False)


def test_building_part_rule_does_not_suppress_unrelated_outline():
    outline = {"footprint": [[0, 0], [10, 0], [10, 10], [0, 10]],
               "osm_id": 10, "is_building_part": False}
    unrelated = {"footprint": [[100, 100], [110, 100], [110, 110], [100, 110]],
                 "osm_id": 11, "is_building_part": True,
                 "building_part": "yes", "min_height": 0.0}
    resolved, suppressed = p.resolve_building_parts([outline, unrelated])
    assert suppressed == 0
    assert {item["osm_id"] for item in resolved} == {10, 11}
    assert outline["detail_anchor"] is True


def test_sharded_overpass_merge_deduplicates_boundary_features():
    left = {"elements": [
        {"type": "way", "id": 1, "geometry": [{"lat": 0, "lon": 0}]},
        {"type": "node", "id": 2, "lat": 0, "lon": 0},
    ]}
    right = {"elements": [
        {"type": "way", "id": 1,
         "geometry": [{"lat": 0, "lon": 0}, {"lat": 0, "lon": 1}]},
        {"type": "way", "id": 3, "geometry": []},
    ]}
    merged = p.merge_overpass_results([left, right])
    assert {(item["type"], item["id"]) for item in merged["elements"]} == {
        ("way", 1), ("node", 2), ("way", 3),
    }
    boundary = next(item for item in merged["elements"] if item["id"] == 1)
    assert len(boundary["geometry"]) == 2


def test_osm_map_xml_adapter_preserves_way_and_relation_geometry():
    xml = b'''<osm version="0.6">
      <node id="1" lat="10" lon="20"/><node id="2" lat="10" lon="21"/>
      <node id="3" lat="11" lon="21"/><node id="4" lat="10" lon="20"/>
      <way id="7"><nd ref="1"/><nd ref="2"/><nd ref="3"/><nd ref="4"/>
        <tag k="building:part" v="yes"/><tag k="height" v="12"/></way>
      <relation id="8"><member type="way" ref="7" role="outer"/>
        <tag k="type" v="multipolygon"/><tag k="building" v="yes"/></relation>
    </osm>'''
    result = p.osm_xml_to_overpass(xml)
    way = next(item for item in result["elements"] if item["type"] == "way")
    relation = next(item for item in result["elements"] if item["type"] == "relation")
    assert way["tags"]["building:part"] == "yes"
    assert len(way["geometry"]) == 4
    assert relation["members"][0]["geometry"] == way["geometry"]


def test_parse_airport_special_features_and_widths():
    project = p.make_projector(0.0, 0.0)
    data = {"elements": [
        {"type": "way", "id": 1,
         "tags": {"aeroway": "runway", "width": "150 ft", "ref": "11/29"},
         "geometry": [{"lat": 0.0, "lon": 0.0},
                      {"lat": 0.001, "lon": 0.0}]},
        {"type": "way", "id": 2, "tags": {"aeroway": "apron"},
         "geometry": [{"lat": 0.0, "lon": 0.0},
                      {"lat": 0.0, "lon": 0.001},
                      {"lat": 0.001, "lon": 0.001},
                      {"lat": 0.0, "lon": 0.0}]},
    ]}
    features = p.parse_special_features(data, project)
    runway = next(f for f in features if f["kind"] == "runway")
    apron = next(f for f in features if f["kind"] == "apron")
    assert runway["geometry"] == "line"
    assert abs(runway["width"] - 45.72) < 0.02
    assert apron["geometry"] == "surface"
    assert p.classify_scene_kind(data, "anything") == "airport"


def test_clip_special_features_stays_inside_radius():
    features = [{"geometry": "line", "kind": "runway", "width": 45,
                 "path": [[-500, 0], [500, 0]]},
                {"geometry": "surface", "kind": "apron",
                 "polygon": [[-300, -300], [300, -300], [300, 300], [-300, 300]]}]
    clipped = p.clip_special_features(features, 100)
    assert clipped
    for feature in clipped:
        points = feature.get("path") or feature.get("polygon")
        assert all(-100.0001 <= x <= 100.0001 and -100.0001 <= y <= 100.0001
                   for x, y in points)


def test_duplicate_apron_way_and_relation_is_removed():
    ring = [{"lat": 0.0, "lon": 0.0}, {"lat": 0.0, "lon": 0.001},
            {"lat": 0.001, "lon": 0.001}, {"lat": 0.0, "lon": 0.0}]
    data = {"elements": [
        {"type": "way", "id": 10, "tags": {"aeroway": "apron"},
         "geometry": ring},
        {"type": "relation", "id": 20,
         "tags": {"aeroway": "apron", "type": "multipolygon"},
         "members": [{"role": "outer", "geometry": ring}]},
    ]}
    features = p.parse_special_features(data, p.make_projector(0.0, 0.0))
    assert len([f for f in features if f["kind"] == "apron"]) == 1


def test_generic_osm_obelisk_becomes_public_art_without_place_name():
    data = {"elements": [{
        "type": "node", "id": 77, "lat": 10.0, "lon": 20.0,
        "tags": {"memorial": "obelisk", "height": "42 m", "name": "Any Name"},
    }]}
    features = p.parse_special_features(data, p.make_projector(10.0, 20.0))
    artwork = next(f for f in features if f.get("family") == "public_art")
    assert artwork["kind"] == "obelisk"
    assert artwork["height"] == 42.0
    assert artwork["height_source"] == "explicit"
    assert artwork["point"] == [0.0, 0.0]


def test_generic_landmark_query_is_tag_driven():
    query = p.build_overpass_query(-1, -1, 1, 1)
    assert 'nwr["memorial"]' in query
    assert '"man_made"' in query
    assert "Buenos Aires" not in query and "Ezeiza" not in query


def test_scene_profile_cannot_be_triggered_by_place_name():
    empty_osm = {"elements": []}
    assert p.classify_scene_kind(empty_osm, "International Airport") == "urban"
    tagged = {"elements": [{"tags": {"aeroway": "runway"}}]}
    assert p.classify_scene_kind(tagged, "Unrelated Label") == "airport"
