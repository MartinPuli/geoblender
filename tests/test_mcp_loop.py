"""
Smoke tests for the live Blender MCP loop without bpy. mcp_loop only generates
source strings, so it can be validated in pure CI.

Run: python3 -m pytest tests/test_mcp_loop.py -q
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import mcp_loop as ml   # noqa: E402


def test_build_payload_is_code_str():
    code = ml.build_payload("output/x/scene.json")
    assert isinstance(code, str) and code.strip()
    assert "build_scene" in code


def test_build_payload_uses_safe_clear():
    # Safe clear uses clear_scene() without restarting Blender.
    assert "clear_scene" in ml.build_payload("output/x/scene.json")


def test_loop_plan_list_of_dicts_with_code():
    plan = ml.loop_plan("output/x/scene.json")
    assert isinstance(plan, list) and len(plan) >= 3
    for step in plan:
        assert isinstance(step, dict)
        assert "code" in step and isinstance(step["code"], str) and step["code"].strip()
    assert "blocks_build.build_from_scene" in plan[1]["code"]
    assert "fetch_3dtiles" not in "\n".join(step["code"] for step in plan)


def test_render_payload_writes_still():
    code = ml.render_payload("output/x/render.png")
    assert isinstance(code, str) and "render.render" in code
    assert "output/x/render.png" in code


def test_render_payload_has_cross_version_engine_fallback():
    code = ml.render_payload("output/x/render.png")
    assert "BLENDER_EEVEE_NEXT" in code
    assert "BLENDER_EEVEE" in code
    assert "CYCLES" in code
    compile(code, "<render_payload>", "exec")


def test_one_shot_payload_is_single_safe_executable(tmp_path):
    code = ml.one_shot_payload(
        tmp_path / "scene.json", tmp_path, slug="airport",
        textures_dir=tmp_path / "textures", hdri_path=tmp_path / "sky.hdr")
    assert "ONE_SHOT_OK" in code
    assert "BASELINE_READY" in code
    assert "clear=True" in code
    assert "read_factory_settings" not in code
    assert "airport_aerial.png" in code
    assert "airport_oblique.png" in code
    assert "airport_holdout.png" in code
    assert "pre_airport.blend" in code
    assert "blocks_build.build_from_scene" in code
    assert "'construction': 'blocks'" in code
    assert "'provider_mesh_imported': False" in code
    assert "render_detail_views" in code
    assert "importlib.reload(_semantic_module)" in code
    assert "fetch_3dtiles" not in code and "import_3dtiles" not in code
    compile(code, "<one_shot_payload>", "exec")


def test_validation_payload_fails_loudly_and_checks_files():
    code = ml.validate_payload("render.png", "scene.blend", ["oblique.png"])
    assert "raise RuntimeError" in code
    assert "render_file" in code and "blend_file" in code and "extra_file_0" in code
    compile(code, "<validate_payload>", "exec")


def test_iteration_payload_freezes_comparable_artifacts(tmp_path):
    code = ml.iteration_payload(tmp_path, 3)
    assert "ITERATION_READY" in code
    assert "loop_03.png" in code and "loop_03_holdout.png" in code
    assert "BLK_CamHoldout" in code and "loop_03.blend" in code
    compile(code, "<iteration_payload>", "exec")


def test_restore_checkpoint_is_not_factory_reset(tmp_path):
    code = ml.restore_checkpoint_payload(tmp_path / "loop_02.blend")
    assert "open_mainfile" in code
    assert "read_factory_settings" not in code
    assert "BEST_CHECKPOINT_RESTORED" in code
    compile(code, "<restore_checkpoint_payload>", "exec")
