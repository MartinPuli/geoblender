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


def test_generic_osm_obelisk_becomes_landmark_without_place_name():
    data = {"elements": [{
        "type": "node", "id": 77, "lat": 10.0, "lon": 20.0,
        "tags": {"memorial": "obelisk", "height": "42 m", "name": "Any Name"},
    }]}
    features = p.parse_special_features(data, p.make_projector(10.0, 20.0))
    landmark = next(f for f in features if f.get("family") == "landmark")
    assert landmark["kind"] == "obelisk"
    assert landmark["height"] == 42.0
    assert landmark["height_source"] == "explicit"
    assert landmark["point"] == [0.0, 0.0]


def test_generic_landmark_query_is_tag_driven():
    query = p.build_overpass_query(-1, -1, 1, 1)
    assert '"memorial"="obelisk"' in query
    assert '"man_made"' in query
    assert "Buenos Aires" not in query and "Ezeiza" not in query


def test_scene_profile_cannot_be_triggered_by_place_name():
    empty_osm = {"elements": []}
    assert p.classify_scene_kind(empty_osm, "International Airport") == "urban"
    tagged = {"elements": [{"tags": {"aeroway": "runway"}}]}
    assert p.classify_scene_kind(tagged, "Unrelated Label") == "airport"
