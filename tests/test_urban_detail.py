"""Pure semantic checks for the shared urban-detail registry."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import urban_detail as ud  # noqa: E402


def test_signage_classes_are_tag_driven_and_name_independent():
    assert ud.classify_tags({"traffic_sign": "AR:stop", "name": "Alpha"}) == (
        "signage", "traffic_sign")
    assert ud.classify_tags({"traffic_sign": "AR:stop", "name": "Beta"}) == (
        "signage", "traffic_sign")
    assert ud.classify_tags({"advertising": "billboard"}) == ("signage", "billboard")
    assert ud.classify_tags({"tourism": "information", "information": "guidepost"}) == (
        "signage", "guidepost")


def test_regulatory_sign_profiles_choose_reusable_shapes_and_content():
    assert ud.traffic_sign_profile({"traffic_sign": "stop"})["shape"] == "octagon"
    assert ud.traffic_sign_profile({"traffic_sign": "give_way"})["shape"] == "triangle_down"
    speed = ud.traffic_sign_profile({"traffic_sign": "maxspeed", "maxspeed": "40"})
    assert speed["shape"] == "circle" and speed["label"] == "40"
    warning = ud.traffic_sign_profile({"traffic_sign": "AR:hazard"})
    assert warning["shape"] == "diamond" and warning["country"] == "AR"
    unknown = ud.traffic_sign_profile({"traffic_sign": "AR:custom_code"})
    assert unknown["shape"] == "rectangle" and unknown["code"] == "custom_code"


def test_public_art_classes_cover_memorial_and_artwork_vocabularies():
    cases = {
        ("historic", "memorial", "memorial", "statue"): "statue",
        ("historic", "memorial", "memorial", "bust"): "bust",
        ("historic", "memorial", "memorial", "stele"): "stele",
        ("tourism", "artwork", "artwork_type", "sculpture"): "sculpture",
        ("tourism", "artwork", "artwork_type", "mural"): "mural",
    }
    for (key, value, subtype_key, subtype), expected in cases.items():
        family, kind = ud.classify_tags({key: value, subtype_key: subtype})
        assert family == "public_art" and kind == expected


def test_amenity_and_playground_grammars_are_distinct():
    assert ud.classify_tags({"emergency": "fire_hydrant"}) == (
        "street_furniture", "fire_hydrant")
    assert ud.classify_tags({"man_made": "street_cabinet"}) == (
        "street_furniture", "street_cabinet")
    assert ud.classify_tags({"playground": "slide"}) == ("recreation", "slide")
    assert ud.classify_tags({"playground": "monkey_bars"}) == (
        "recreation", "climbingframe")
    assert ud.classify_tags({"amenity": "charging_station"}) == (
        "street_furniture", "charging_station")
    assert ud.classify_tags({"amenity": "parcel_locker"}) == (
        "street_furniture", "parcel_locker")
    assert ud.classify_tags({"leisure": "fitness_station"}) == (
        "recreation", "fitness_station")
    assert ud.classify_tags({"highway": "crossing"}) == (
        "road_surface", "pedestrian_crossing")
    assert ud.classify_tags({"traffic_calming": "island"}) == (
        "road_surface", "traffic_island")
    assert ud.classify_tags({"traffic_calming": "painted_island"}) == (
        "road_surface", "painted_island")
    assert ud.classify_tags({"power": "tower"}) == (
        "street_furniture", "power_tower")


def test_advertising_size_and_cardinal_direction_parse_safely():
    assert ud.parse_size("5.5*3 m") == (5.5, 3.0)
    assert ud.parse_size("bad") is None
    assert ud.parse_bearing("SW") == 225.0
    assert ud.parse_bearing("450") == 90.0


def test_object_spec_preserves_explicit_dimensions_and_ignores_unrelated_names():
    alpha = ud.object_spec({"family": "street_furniture", "kind": "bench",
                            "height": 0.9, "width": 2.0, "name": "Alpha"})
    beta = ud.object_spec({"family": "street_furniture", "kind": "bench",
                           "height": 0.9, "width": 2.0, "name": "Beta"})
    assert alpha == beta
    sign = ud.object_spec({"family": "signage", "kind": "billboard",
                           "height": 7, "panel_size": [8, 3], "direction": "E",
                           "name": "Mapped content"})
    assert sign["panel_width"] == 8 and sign["panel_height"] == 3
    assert sign["direction"] == 90 and sign["text"] == "Mapped content"


def test_bus_stop_components_are_built_only_from_explicit_tags():
    pole = ud.object_spec({"family": "transit", "kind": "bus_stop"})
    complete = ud.object_spec({
        "family": "transit", "kind": "bus_stop", "shelter": "yes",
        "bench": "yes", "bin": "yes", "passenger_information_display": "yes",
    })
    assert not pole["has_shelter"] and not pole["has_bench"]
    assert complete["has_shelter"] and complete["has_bench"]
    assert complete["has_bin"] and complete["has_display"]
    assert complete["parts"] == pole["parts"] + 15


def test_wall_host_resolution_uses_nearest_mapped_building_edge():
    host = ud.resolve_wall_host(
        {"point": [10.2, 4.0], "depth": 0.08},
        [{"osm_id": 77, "footprint": [[0, 0], [10, 0], [10, 8], [0, 8], [0, 0]]}],
        max_distance=1.0,
    )
    assert host is not None and host["host_building_id"] == 77
    assert host["support"] == "wall_resolved"
    assert host["direction_source"] == "wall_host"
    assert host["front_normal"][0] > 0.9
    assert host["host_distance"] == 0.2
    assert ud.resolve_wall_host(
        {"point": [30, 30]},
        [{"footprint": [[0, 0], [10, 0], [10, 8], [0, 8], [0, 0]]}],
        max_distance=1.0,
    ) is None


def test_crossing_resolves_nearest_road_and_keeps_accessibility_evidence():
    host = ud.resolve_road_host(
        {"point": [1.0, 0.4]},
        [{"osm_id": 9, "width": 7.0, "path": [[-10, 0], [10, 0]]}],
        max_distance=2.0,
    )
    assert host["host_road_id"] == 9 and host["road_width"] == 7.0
    assert host["direction"] == 90.0 and host["direction_source"] == "road_host"
    marked = ud.object_spec({"family": "road_surface", "kind": "pedestrian_crossing",
                             "crossing_markings": "zebra", "tactile_paving": "yes",
                             "road_width": 7.0})
    assert marked["parts"] == 9 and marked["tactile_paving"]
    unmarked = ud.object_spec({"family": "road_surface", "kind": "pedestrian_crossing",
                               "crossing": "unmarked"})
    assert unmarked["parts"] == 0
    refuge = ud.object_spec({"family": "road_surface", "kind": "pedestrian_crossing",
                             "crossing_markings": "zebra", "crossing_island": "yes"})
    assert refuge["crossing_island"] and refuge["parts"] == 9


def test_turn_lane_profiles_keep_lane_order_direction_and_uncertainty():
    assert ud.parse_turn_lanes("left|through;right|none") == [
        ["left"], ["through", "right"], ["none"]]
    oneway = ud.road_turn_profiles({"oneway": "yes", "turn_lanes": "left|through"})
    assert oneway == [{"direction": "forward", "lanes": [["left"], ["through"]],
                       "source": "turn:lanes", "direction_confidence": "explicit"}]
    directional = ud.road_turn_profiles({
        "turn_lanes_forward": "through|right",
        "turn_lanes_backward": "left|through",
    })
    assert [item["direction"] for item in directional] == ["forward", "backward"]
    ambiguous = ud.road_turn_profiles({"turn_lanes": "through|right"})
    assert ambiguous[0]["direction_confidence"] == "ambiguous_two_way"


def test_cycle_lane_profiles_require_explicit_on_road_lane_semantics():
    both = ud.road_cycle_profiles({"cycleway": "lane", "width": 8.0})
    assert [item["side"] for item in both] == ["left", "right"]
    right = ud.road_cycle_profiles({
        "cycleway_right": "lane", "cycleway_right_width": "1.8",
        "cycleway_right_buffer": "0.6", "cycleway_right_separation": "bollard",
    })
    assert len(right) == 1 and right[0]["side"] == "right"
    assert right[0]["width"] == 1.8 and right[0]["buffer"] == 0.6
    assert right[0]["separation"] == "bollard"
    assert ud.road_cycle_profiles({"cycleway": "track"}) == []
    assert ud.road_cycle_profiles({"cycleway": "separate"}) == []


def test_bus_lane_profiles_render_only_explicit_positions():
    explicit = ud.road_bus_profiles({
        "bus_lanes_forward": "yes|yes|designated",
        "bus_lanes_backward": "designated|yes",
    })
    assert [item["direction"] for item in explicit] == ["forward", "backward"]
    assert explicit[0]["lane_indices"] == [2] and explicit[1]["lane_indices"] == [0]
    assert all(item["renderable"] for item in explicit)
    ambiguous = ud.road_bus_profiles({"bus_lanes": "yes|designated"})
    assert not ambiguous[0]["renderable"]
    count_only = ud.road_bus_profiles({"lanes_bus": "1"})
    assert count_only[0]["confidence"] == "count_without_position"


def test_street_parking_profiles_keep_side_position_and_orientation():
    profiles = ud.road_parking_profiles({
        "parking_left": "lane", "parking_left_orientation": "parallel",
        "parking_right": "street_side", "parking_right_orientation": "diagonal",
        "parking_right_width": "4.4",
    })
    assert [item["side"] for item in profiles] == ["left", "right"]
    assert profiles[0]["width"] == 2.2
    assert profiles[1]["position"] == "street_side" and profiles[1]["width"] == 4.4
    assert ud.road_parking_profiles({"parking_both": "separate"}) == []


def test_sidewalk_profiles_render_integrated_sides_and_preserve_separate_metadata():
    profiles = ud.road_sidewalk_profiles({
        "sidewalk_both": "yes", "sidewalk_left_width": "2.2",
        "sidewalk_right_width": "1.6", "sidewalk_left_kerb": "raised",
    })
    assert [item["side"] for item in profiles] == ["left", "right"]
    assert profiles[0]["width"] == 2.2 and profiles[0]["kerb"] == "raised"
    separate = ud.road_sidewalk_profiles({"sidewalk": "separate"})
    assert len(separate) == 2 and not any(item["renderable"] for item in separate)
    assert ud.road_sidewalk_profiles({"sidewalk": "no"}) == []


def test_marking_and_technical_network_classes_are_semantic():
    assert ud.classify_tags({"road_marking": "stop_line"}) == (
        "road_surface", "stop_line")
    assert ud.classify_tags({"power": "transformer"}) == (
        "utility_network", "power_transformer")
    assert ud.classify_tags({"power": "substation"}) == (
        "utility_network", "power_substation_kiosk")
    assert ud.classify_tags({"man_made": "utility_pole", "utility": "telecom"}) == (
        "utility_network", "telecom_pole")
    assert ud.classify_tags({"man_made": "street_cabinet", "utility": "telecom"}) == (
        "utility_network", "telecom_cabinet")
    assert ud.classify_tags({"telecom": "distribution_point"}) == (
        "utility_network", "telecom_distribution_point")
    assert ud.classify_tags({"man_made": "manhole", "utility": "sewerage"}) == (
        "road_surface", "manhole_cover")
    assert ud.classify_tags({"man_made": "manhole", "manhole": "drain",
                             "inlet": "grate"}) == (
        "road_surface", "drainage_inlet")
    assert ud.classify_tags({"man_made": "street_cabinet", "utility": "water"}) == (
        "fluid_network", "fluid_cabinet")
    assert ud.classify_tags({"barrier": "kerb", "kerb": "lowered"}) == (
        "road_surface", "curb_ramp")
    assert ud.classify_tags({"highway": "crossing", "traffic_calming": "table"}) == (
        "road_surface", "raised_crossing")
    assert ud.classify_tags({"traffic_calming": "table"}) == (
        "road_surface", "speed_table")


def test_road_surface_specs_preserve_flush_heights():
    spec = ud.object_spec({"family": "road_surface", "kind": "curb_ramp",
                           "height": 0.025, "tactile_paving": "yes"})
    assert spec["height"] == 0.025 and spec["tactile_paving"]


def test_area_and_line_vegetation_placement_is_deterministic_and_bounded():
    polygon = [[0, 0], [20, 0], [20, 10], [0, 10], [0, 0]]
    first = ud.deterministic_area_points(polygon, 12, seed=77)
    second = ud.deterministic_area_points(polygon, 12, seed=77)
    assert first == second and len(first) == 12
    assert all(ud.point_in_polygon(point, polygon) for point in first)
    assert min(point[1] for point in first) < 2.5
    assert max(point[1] for point in first) > 7.5
    row = ud.line_sample_points([[0, 0], [20, 0]], spacing=5)
    assert row[0] == [0.0, 0.0] and row[-1] == [20.0, 0.0]
    assert len(row) == 5


def test_vegetation_and_utility_profiles_respect_explicit_semantics():
    wood = ud.vegetation_area_profile({"type": "wood", "area_m2": 3600})
    orchard = ud.vegetation_area_profile({"type": "orchard", "area_m2": 600})
    assert wood["kind"] == "woodland" and wood["count"] == 10
    assert orchard["kind"] == "orchard" and orchard["count"] == 4
    assert ud.vegetation_area_profile({"type": "park", "area_m2": 5000}) is None
    explicit = ud.utility_line_profile({"power": "minor_line", "cables": "4"})
    fallback = ud.utility_line_profile({"power": "line"})
    assert explicit["conductors"] == 4 and explicit["conductor_source"] == "explicit"
    assert fallback["conductors"] == 6 and fallback["height"] > explicit["height"]
    visible = ud.communication_line_profile({
        "location": "overhead", "cables": "2", "telecom_medium": "fibre"})
    hidden = ud.communication_line_profile({"location": "underground"})
    unknown = ud.communication_line_profile({})
    assert visible["visible"] and visible["conductors"] == 2
    assert not hidden["visible"] and hidden["location"] == "underground"
    assert not unknown["visible"] and unknown["location"] == "unspecified"
    water = ud.fluid_line_profile({
        "location": "overhead", "diameter": "450 mm", "substance": "water"})
    buried = ud.fluid_line_profile({"location": "underground", "substance": "gas"})
    unspecified = ud.fluid_line_profile({})
    assert water["visible"] and water["diameter"] == 0.45
    assert not buried["visible"] and buried["substance"] == "gas"
    assert not unspecified["visible"] and unspecified["location"] == "unspecified"


def test_residential_profile_separates_zone_and_building_evidence():
    profile = ud.residential_profile({
        "areas": [{"type": "residential", "residential": "apartments"}],
        "buildings": [{"type": "house"}, {"type": "apartments"}, {"type": "retail"}],
    })
    assert profile["detected"] and profile["zone_count"] == 1
    assert profile["building_count"] == 2
    assert profile["subtypes"] == ["apartments"]
