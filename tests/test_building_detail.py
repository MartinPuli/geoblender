"""
Synthetic tests for the default building-detail heuristics in blocks_build
(varied estimated heights + roof caps + per-feature scene colors).

blocks_build imports bpy at module load, so the Blender-only modules are
stubbed to exercise the pure helpers in plain CI. These are the tag/provenance
driven synthetic checks the generalization contract requires before the
heuristic ships enabled by default.

Run: python3 -m pytest tests/test_building_detail.py -q
"""
import os
import sys
import types
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

# Stub Blender-only modules so the pure helpers import without a live Blender.
for _name in ("bpy", "bmesh"):
    sys.modules.setdefault(_name, mock.MagicMock())
_mathutils = types.ModuleType("mathutils")
_mathutils.Matrix = mock.MagicMock()
sys.modules.setdefault("mathutils", _mathutils)
_blender_build = types.ModuleType("blender_build")
_blender_build.add_flat_polygon = lambda *a, **k: None
_blender_build.add_prism = lambda *a, **k: None
_blender_build.dedupe_ring = lambda pts, closed=True: list(pts)
sys.modules.setdefault("blender_build", _blender_build)

import blocks_build as bb  # noqa: E402

SQUARE = [[0, 0], [40, 0], [40, 40], [0, 40]]  # 1600 m^2


def _bld(osm_id, height=9.0, source="default", footprint=None):
    return {"osm_id": osm_id, "height": height, "height_source": source,
            "footprint": footprint or SQUARE}


def test_detail_defaults_are_on():
    # The whole point of the update: these ship enabled by default.
    assert bb.DEFAULT_STYLE["height_variation"]["enabled"] is True
    assert bb.DEFAULT_STYLE["roof_detail"]["enabled"] is True
    assert bb.DEFAULT_STYLE["color_mode"] == "scene"


def test_variation_produces_a_varied_skyline():
    style = bb.load_style()
    hv = style["height_variation"]
    heights = {bb.varied_building_height(_bld(i), style, 9.0) for i in range(24)}
    assert len(heights) > 6
    for h in heights:
        assert hv["min"] <= h <= hv["max"]


def test_variation_is_deterministic():
    style = bb.load_style()
    assert bb.varied_building_height(_bld(123), style, 9.0) == \
        bb.varied_building_height(_bld(123), style, 9.0)


def test_explicit_heights_are_preserved():
    # Provenance guard: explicit OSM height/levels are never reshaped.
    style = bb.load_style()
    assert bb.varied_building_height(_bld(1, 30.0, "explicit"), style, 30.0) == 30.0
    assert bb.varied_building_height(_bld(2, 24.0, "levels"), style, 24.0) == 24.0


def test_disabled_flag_is_a_no_op():
    style = bb.load_style()
    style["height_variation"]["enabled"] = False
    assert bb.varied_building_height(_bld(9), style, 9.0) == 9.0


def test_larger_footprints_bias_taller():
    style = bb.load_style()
    small = bb.varied_building_height(
        _bld(7, footprint=[[0, 0], [6, 0], [6, 6], [0, 6]]), style, 9.0)
    big = bb.varied_building_height(
        _bld(7, footprint=[[0, 0], [80, 0], [80, 80], [0, 80]]), style, 9.0)
    assert big >= small


def test_stadium_interior_default_on():
    assert bb.DEFAULT_STYLE["stadium_interior"]["enabled"] is True


def test_is_stadium_is_tag_driven_not_name_driven():
    # Reusable domain semantics: driven by the OSM type/kind tag, never a name.
    assert bb.is_stadium({"type": "stadium"})
    assert bb.is_stadium({"type": "grandstand"})
    assert bb.is_stadium({"kind": "arena"})
    assert not bb.is_stadium({"type": "yes"})
    assert not bb.is_stadium({"type": "apartments", "name": "La Bombonera Cafe"})


def test_scale_ring_moves_points_toward_centroid():
    ring = [[0, 0], [10, 0], [10, 10], [0, 10]]  # centroid (5, 5)
    half = bb._scale_ring(ring, 5.0, 5.0, 0.5)
    assert half[0] == (2.5, 2.5) and half[2] == (7.5, 7.5)


def test_roof_shapes_default_on():
    assert bb.DEFAULT_STYLE["roof_shapes"]["enabled"] is True


def test_pitched_roof_shape_set_is_tag_driven():
    assert {"gabled", "hipped", "pyramidal", "skillion"} <= bb.PITCHED_ROOF_SHAPES
    assert "flat" not in bb.PITCHED_ROOF_SHAPES
    assert "" not in bb.PITCHED_ROOF_SHAPES


def test_principal_axis_of_long_rectangle_points_along_length():
    ring = [[0, 0], [100, 0], [100, 10], [0, 10]]  # long along X
    axis_x, axis_y = bb._principal_axis(ring, 50.0, 5.0)
    assert abs(abs(axis_x) - 1.0) < 0.05 and abs(axis_y) < 0.05


def test_terrain_default_on():
    assert bb.DEFAULT_STYLE["terrain"]["enabled"] is True


def test_terrain_sampler_bilinear_and_clamped():
    terrain = {"nx": 2, "ny": 2, "extent": 100.0, "zmin": 0.0,
               "z": [[0.0, 10.0], [20.0, 30.0]]}
    sample = bb.make_terrain_sampler(terrain)
    assert abs(sample(-100, -100) - 0.0) < 1e-6   # corner grid[0][0]
    assert abs(sample(100, 100) - 30.0) < 1e-6    # corner grid[1][1]
    assert abs(sample(0, 0) - 15.0) < 1e-6        # centre = mean of corners
    assert abs(sample(9999, 9999) - 30.0) < 1e-6  # clamps to nearest edge


def test_terrain_sampler_subtracts_zmin():
    terrain = {"nx": 2, "ny": 2, "extent": 100.0, "zmin": 100.0,
               "z": [[100.0, 100.0], [100.0, 140.0]]}
    sample = bb.make_terrain_sampler(terrain)
    assert abs(sample(-100, -100) - 0.0) < 1e-6   # base rides at 0
    assert abs(sample(100, 100) - 40.0) < 1e-6


def test_image_colors_default_on():
    assert bb.DEFAULT_STYLE["image_colors"]["enabled"] is True


def test_linear_to_srgb_endpoints_and_midtone():
    assert abs(bb._linear_to_srgb(0.0)) < 1e-6
    assert abs(bb._linear_to_srgb(1.0) - 1.0) < 1e-6
    assert bb._linear_to_srgb(0.5) > 0.5            # sRGB brightens midtones


def test_srgb_to_linear_endpoints_and_midtone():
    assert abs(bb._srgb_to_linear(0.0)) < 1e-6
    assert abs(bb._srgb_to_linear(1.0) - 1.0) < 1e-6
    assert bb._srgb_to_linear(0.5) < 0.5


def test_meters_to_pixel_center_east_north():
    px, py = bb._meters_to_pixel(0, 0, 640, 1.0)
    assert px == 320 and py == 320                  # scene origin -> centre
    px_e, py_e = bb._meters_to_pixel(10, 0, 640, 1.0)
    assert px_e == 330 and py_e == 320              # +x east -> right
    px_n, py_n = bb._meters_to_pixel(0, 10, 640, 1.0)
    assert px_n == 320 and py_n == 310              # +y north -> up (smaller py)


def test_facade_default_on():
    assert bb.DEFAULT_STYLE["facade"]["enabled"] is True
    assert bb.DEFAULT_STYLE["facade"]["frame_enabled"] is True
    assert bb.DEFAULT_STYLE["facade"]["frame_width"] > 0


def test_facade_name_buckets_similar_colors_and_splits_distinct():
    assert bb._facade_name([0.70, 0.68, 0.60]) == bb._facade_name([0.72, 0.69, 0.61])
    assert bb._facade_name([0.70, 0.68, 0.60]) != bb._facade_name([0.20, 0.30, 0.50])


def test_facade_parameters_use_levels_before_defaults():
    style = bb.load_style()
    spec = bb.facade_parameters(
        {"type": "apartments", "levels": 5, "building_material": "brick"},
        style, height=16.0, base=0.0)
    assert abs(spec["floor_height"] - 3.2) < 1e-6
    assert spec["profile"] == "residential"
    assert spec["wall_roughness"] > 0.8


def test_facade_profiles_are_semantic_not_identity_driven():
    style = bb.load_style()
    office = bb.facade_parameters({"type": "office", "name": "Any Name"}, style)
    unrelated_office = bb.facade_parameters(
        {"type": "office", "name": "Completely Different"}, style)
    warehouse = bb.facade_parameters({"type": "warehouse", "name": "Any Name"}, style)
    assert office == unrelated_office
    assert office["profile"] == "commercial"
    assert warehouse["profile"] == "industrial"
    assert office["bay"] != warehouse["bay"]


def test_aerial_color_defaults_to_roof_not_facade():
    assert bb.DEFAULT_STYLE["image_colors"]["target"] == "roof"


def test_construction_detail_default_on_and_bounded():
    cfg = bb.DEFAULT_STYLE["construction_detail"]
    assert cfg["enabled"] is True
    assert cfg["geometry_radius"] > bb.DEFAULT_STYLE["facade"]["geometry_radius"]
    assert 0 < cfg["max_floor_bands"] <= 16


def test_construction_detail_uses_grounded_anchor_not_identity():
    style = bb.load_style()
    facade = bb.facade_parameters({"type": "apartments"}, style,
                                  height=18.0, base=0.0)
    first = bb.construction_detail_spec(
        {"type": "apartments", "detail_anchor": True, "name": "Alpha"},
        style, facade, 0.0, 18.0)
    same = bb.construction_detail_spec(
        {"type": "apartments", "detail_anchor": True, "name": "Beta"},
        style, facade, 0.0, 18.0)
    suspended = bb.construction_detail_spec(
        {"type": "apartments", "detail_anchor": True, "min_height": 6.0},
        style, facade, 6.0, 18.0)
    assert first == same
    assert first["entrance"] and first["floor_bands"]
    assert not suspended["entrance"] and not suspended["plinth"]


def test_roof_height_prefers_explicit_osm_values():
    style = bb.load_style()
    assert bb.roof_height_for({"roof_height": 3.7}, style, 0.0, 20.0) == 3.7
    assert bb.roof_height_for({"roof_levels": 2}, style, 0.0, 20.0) == 6.0
    assert bb.roof_height_for({}, style, 0.0, 20.0) <= style["roof_shapes"]["max_height"]


def test_roof_orientation_across_rotates_the_general_axis():
    ring = [[0, 0], [100, 0], [100, 10], [0, 10]]
    along = bb._roof_axis(ring, 50.0, 5.0, "along", None, "gabled")
    across = bb._roof_axis(ring, 50.0, 5.0, "across", None, "gabled")
    dot = along[0] * across[0] + along[1] * across[1]
    assert abs(dot) < 1e-6


def test_sky_and_roof_props_defaults():
    # Physical sky (Eevee-compatible) and rooftop clutter ship on by default.
    assert bb.DEFAULT_STYLE["sky_model"] == "hosek_wilkie"
    assert bb.DEFAULT_STYLE["roof_props"]["enabled"] is True

def test_open_cover_defaults_are_on_and_bounded():
    cfg = bb.DEFAULT_STYLE["covered_structures"]
    assert cfg["enabled"] is True
    assert 0.1 <= cfg["roof_thickness"] <= 0.6
    assert 4 <= cfg["max_columns"] <= 40


def test_roof_only_classification_is_semantic_not_named():
    assert bb.is_roof_only({"type": "roof", "name": "Any Name"})
    assert bb.is_roof_only({"structure_mode": "roof_only", "name": "Other"})
    assert not bb.is_roof_only({"type": "apartments", "name": "Roof Cafe"})


def test_covered_structure_spec_preserves_clearance_and_thin_deck():
    spec = bb.covered_structure_spec(
        {"min_height": 3.2, "height": 3.55}, bb.load_style())
    assert spec["bottom"] == 3.2
    assert spec["top"] == 3.55
    assert spec["roof_bottom"] >= spec["bottom"]
    assert 0.12 <= spec["thickness"] <= 0.35


def test_cover_supports_are_deterministic_inset_and_capped():
    ring = [[0, 0], [40, 0], [40, 20], [0, 20], [0, 0]]
    first = bb.covered_support_points(ring, spacing=4.0, inset=0.3, max_columns=10)
    second = bb.covered_support_points(ring, spacing=4.0, inset=0.3, max_columns=10)
    assert first == second
    assert 4 <= len(first) <= 10
    assert all(0.0 < x < 40.0 and 0.0 < y < 20.0 for x, y in first)


def test_urban_object_specs_are_semantic_and_meter_scaled():
    style = bb.load_style()
    bench = bb.urban_object_spec(
        {"kind": "bench", "height": 0.85, "width": 1.8, "name": "Alpha"}, style)
    unrelated = bb.urban_object_spec(
        {"kind": "bench", "height": 0.85, "width": 1.8, "name": "Beta"}, style)
    tree = bb.urban_object_spec({"kind": "tree", "height": 8, "width": 5}, style)
    assert bench == unrelated
    assert bench["parts"] >= 4 and tree["parts"] >= 2
    assert bench["width"] == 1.8 and tree["height"] == 8


def _football_scene(angle=0.0):
    import math
    c, s = math.cos(angle), math.sin(angle)

    def point(u, v):
        return [u * c - v * s, u * s + v * c]

    return {
        "scene_kind": "football_stadium",
        "areas": [{"osm_id": 501, "type": "pitch", "sport": "soccer",
                   "polygon": [point(-52.5, -34), point(52.5, -34),
                               point(52.5, 34), point(-52.5, 34), point(-52.5, -34)]}],
        "buildings": [{"osm_id": 601, "type": "stadium",
                       "footprint": [point(-78, -60), point(78, -60),
                                     point(78, 60), point(-78, 60), point(-78, -60)]}],
    }


def test_football_stadium_detection_requires_semantics_not_name():
    sd = bb.stadium_detail
    assert sd.detect(_football_scene(), bb.load_style())
    assert not sd.detect({"scene_kind": "urban", "areas": [],
                          "buildings": [{"type": "yes", "name": "Famous Stadium"}]},
                         bb.load_style())


def test_football_stadium_layout_preserves_rotated_pitch_dimensions():
    import math
    sd = bb.stadium_detail
    layout = sd.resolve_layout(_football_scene(math.radians(28)), bb.load_style())
    assert abs(layout["pitch_length"] - 105.0) < 0.1
    assert abs(layout["pitch_width"] - 68.0) < 0.1
    assert layout["pitch_source"] == "osm"
    assert layout["suppressed_building_ids"] == [601]
    observed = math.degrees(layout["angle"]) % 180.0
    assert min(abs(observed - 28.0), 180.0 - abs(observed - 28.0)) < 1.0


def test_football_stadium_default_detail_is_substantial():
    cfg = bb.DEFAULT_STYLE["football_stadium"]
    assert cfg["enabled"] == "auto"
    assert cfg["rows_long"] >= 14 and cfg["rows_end"] >= 10
    assert cfg["max_seat_modules"] >= 5000
    assert cfg["roof_enabled"] is True and cfg["floodlights"] is True
    assert cfg["bowl_shape"] == "rectangular"
    assert cfg["lighting_mode"] == "towers"


def test_football_stadium_continuous_oval_is_run_configured_and_identity_free():
    sd = bb.stadium_detail
    style = bb.load_style()
    style["football_stadium"].update({
        "bowl_shape": "continuous_oval",
        "bowl_segments": 112,
        "bowl_exponent": 5.5,
        "lighting_mode": "roof_ring",
        "signage_text": "RUN SUPPLIED",
    })
    layout = sd.resolve_layout(_football_scene(), style)
    assert layout["config"]["bowl_shape"] == "continuous_oval"
    assert layout["config"]["bowl_segments"] == 112
    assert layout["config"]["lighting_mode"] == "roof_ring"
    assert layout["config"]["signage_text"] == "RUN SUPPLIED"
    assert sd.DEFAULT_CONFIG["signage_text"] is None


def test_stadium_bowl_height_is_independent_from_tall_structural_envelope():
    sd = bb.stadium_detail
    cfg = dict(sd.DEFAULT_CONFIG)
    cfg.update({"stand_height_long": 28.0, "bowl_height_long": 15.8,
                "first_row_height": 0.62, "rake_curve": 0.24})
    profiles = [sd.bowl_row_profile(cfg, 30, row, "long")
                for row in range(30)]
    assert abs(profiles[-1]["bowl_height"] - 15.8) < 1e-6
    assert max(item["rise"] for item in profiles) < 0.62
    assert all(a["top"] < b["top"] for a, b in zip(profiles, profiles[1:]))


def test_oval_access_mask_creates_narrow_aisles_and_real_vomitory_clearance():
    sd = bb.stadium_detail
    cfg = dict(sd.DEFAULT_CONFIG)
    cfg.update({"vomitory_count": 8, "vomitory_row_span": 4})
    segments, sections, rows = 144, 34, 30
    ordinary = [sd.oval_access_mask(i, segments, sections, 2, rows, cfg)
                for i in range(segments)]
    aisle_count = sum(item["aisle"] for item in ordinary)
    # Regression for the old modulo expression: it marked 34/144 of every
    # ring as full-height access wedges instead of one narrow cell per aisle.
    assert sections - 2 <= aisle_count <= sections + 2
    portal_row = round(rows * 0.38)
    portals = [sd.oval_access_mask(i, segments, sections, portal_row, rows, cfg)
               for i in range(segments)]
    assert sum(item["vomitory"] for item in portals) >= cfg["vomitory_count"]
    assert not any(item["vomitory"] for item in ordinary)


def test_multi_pitch_stadium_selects_nearest_and_suppresses_local_shell_only():
    sd = bb.stadium_detail
    scene = _football_scene()
    scene["areas"].append({
        "osm_id": 502, "type": "pitch", "sport": "soccer",
        "polygon": [[230, -40], [350, -40], [350, 40], [230, 40], [230, -40]],
    })
    scene["buildings"].append({
        "osm_id": 602, "type": "stadium",
        "footprint": [[205, -70], [375, -70], [375, 70], [205, 70], [205, -70]],
    })
    layout = sd.resolve_layout(scene, bb.load_style())
    assert layout["pitch_osm_id"] == 501
    assert layout["suppressed_building_ids"] == [601]


def test_multi_pitch_stadium_allows_explicit_pitch_id_override():
    sd = bb.stadium_detail
    scene = _football_scene()
    scene["areas"].append({
        "osm_id": 502, "type": "pitch", "sport": "soccer",
        "polygon": [[230, -34], [335, -34], [335, 34], [230, 34], [230, -34]],
    })
    style = bb.load_style()
    style["football_stadium"]["pitch_osm_id"] = 502
    assert sd.resolve_layout(scene, style)["pitch_osm_id"] == 502


def test_specialized_stadium_suppresses_sibling_simple_3d_parts():
    sd = bb.stadium_detail
    scene = _football_scene()
    scene["buildings"].extend([
        {"osm_id": 701, "type": "roof", "structure_mode": "roof_only",
         "is_building_part": True, "building_part": "yes",
         "outline_osm_id": 900,
         "footprint": [[-50, -30], [50, -30], [50, 30], [-50, 30]]},
        {"osm_id": 702, "type": "yes", "structure_mode": "enclosed",
         "is_building_part": True, "building_part": "yes",
         "outline_osm_id": 900,
         "footprint": [[55, -20], [72, -20], [72, -10], [55, -10]]},
        {"osm_id": 703, "type": "yes", "structure_mode": "enclosed",
         "is_building_part": True, "building_part": "yes",
         "outline_osm_id": 901,
         "footprint": [[160, -10], [170, -10], [170, 0], [160, 0]]},
    ])
    layout = sd.resolve_layout(scene, bb.load_style())
    suppressed = set(layout["suppressed_building_ids"])
    assert {601, 701, 702} <= suppressed
    assert 703 not in suppressed
    assert layout["suppressed_building_part_count"] == 2


def test_stadium_auto_roof_sides_use_nearby_open_roof_semantics():
    sd = bb.stadium_detail
    scene = _football_scene()
    scene["buildings"].append({
        "osm_id": 701, "type": "roof", "structure_mode": "roof_only",
        "footprint": [[-48, 48], [48, 48], [48, 63], [-48, 63], [-48, 48]],
    })
    layout = sd.resolve_layout(scene, bb.load_style())
    assert layout["config"]["roof_sides"] == ["north"]
    assert layout["roof_side_source"] == "osm_roof_footprints"


def test_specialized_roof_suppresses_only_large_cover_centered_on_pitch():
    sd = bb.stadium_detail
    scene = _football_scene()
    scene["buildings"].extend([
        {"osm_id": 701, "type": "roof", "structure_mode": "roof_only",
         "footprint": [[-70, -50], [70, -50], [70, 50], [-70, 50], [-70, -50]]},
        {"osm_id": 702, "type": "canopy", "structure_mode": "roof_only",
         "footprint": [[120, 0], [140, 0], [140, 10], [120, 10], [120, 0]]},
    ])
    layout = sd.resolve_layout(scene, bb.load_style())
    assert 701 in layout["suppressed_building_ids"]
    assert 702 not in layout["suppressed_building_ids"]


def test_architectural_profiles_are_semantic_and_cover_requested_building_types():
    ad = bb.architectural_detail
    assert ad.classify_profile({"type": "apartments"}) == "residential"
    assert ad.classify_profile({"type": "office", "building_material": "glass"}) == "curtain_wall"
    assert ad.classify_profile({"type": "yes", "building_use": "hospital"}) == "healthcare"
    assert ad.classify_profile({"type": "school"}) == "education"
    assert ad.classify_profile({"type": "warehouse"}) == "industrial"
    assert ad.classify_profile({"type": "yes", "name": "Hospitality House"}) == "mixed"


def test_architectural_variants_are_deterministic_varied_and_name_independent():
    ad = bb.architectural_detail
    style = bb.load_style()
    base = {"type": "apartments", "footprint": SQUARE, "osm_id": 70}
    first = ad.facade_parameters(dict(base, name="Alpha"), style)
    renamed = ad.facade_parameters(dict(base, name="Beta"), style)
    assert first == renamed
    variants = {
        ad.facade_parameters(dict(base, osm_id=osm_id), style)["variant"]
        for osm_id in range(70, 100)
    }
    assert len(variants) >= 4
    assert first["symmetry"] == "paired"


def test_healthcare_facade_has_bilateral_symmetry_and_clinical_interior():
    spec = bb.facade_parameters(
        {"type": "yes", "building_use": "hospital", "levels": 5,
         "footprint": SQUARE, "osm_id": 91}, bb.load_style(),
        height=18.0, base=0.0)
    assert spec["profile"] == "healthcare"
    assert spec["symmetry"] == "bilateral"
    assert spec["mullion_divisions"] >= 2
    assert spec["interior_palette"] == "clinical"


def test_editable_interior_layouts_are_profile_specific_bounded_and_inferred():
    ad = bb.architectural_detail
    style = bb.load_style()
    hospital = ad.interior_layout_spec(
        {"type": "hospital", "levels": 12, "footprint": SQUARE, "osm_id": 92},
        style, height=42.0, base=0.0)
    warehouse = ad.interior_layout_spec(
        {"type": "warehouse", "footprint": SQUARE, "osm_id": 93},
        style, height=10.0, base=0.0)
    assert hospital["layout"] == "double_loaded_corridor"
    assert warehouse["layout"] == "open_plan"
    assert hospital["modeled_floors"] <= style["architectural_detail"]["max_interior_floors"]
    assert hospital["provenance"] == "procedural_inference"


def test_hospital_specialization_requires_semantics_and_resolves_largest_site():
    hd = bb.hospital_detail
    scene = {"scene_kind": "urban", "buildings": [
        {"type": "yes", "name": "Hospitality House", "footprint": SQUARE},
        {"type": "hospital", "osm_id": 22, "height": 18,
         "footprint": [[-40, -25], [40, -25], [40, 25], [-40, 25], [-40, -25]]},
    ]}
    assert hd.detect(scene, bb.load_style())
    assert not hd.is_hospital(scene["buildings"][0])
    sites = hd.resolve_sites(scene, bb.load_style())
    assert len(sites) == 1 and sites[0]["building"]["osm_id"] == 22
    assert sites[0]["area"] == 4000


def test_highway_specialization_is_lane_aware_and_preserves_explicit_width():
    hw = bb.highway_detail
    style = bb.load_style()
    road = {"type": "motorway", "lanes": 3, "oneway": "yes",
            "width": 12.8, "width_source": "explicit", "bridge": True}
    spec = hw.road_spec(road, style)
    assert spec["lanes"] == 3 and spec["oneway"]
    assert spec["width"] == 12.8 and spec["bridge"]
    assert hw.detect({"roads": [road]}, style)
    assert not hw.detect({"roads": [{"type": "residential"}]}, style)
