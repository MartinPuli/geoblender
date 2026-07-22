"""
mcp_loop.py — pure helpers (no bpy) that return Python source strings for
Blender MCP's ``execute_blender_code`` tool at each live-loop step. See
docs/MCP_LOOP.md. Importing this module has no Blender side effects; it only
generates source code that runs inside the live Blender session.

Public API:
    build_payload(scene_path, heading=None, sv_xy=(0,0), height=2.5, fov=78.0,
                  scripts_dir=None) -> str
    block_build_payload(scene_path, out_dir=None, slug=None, ...) -> str
    render_payload(out_png, engine="BLENDER_EEVEE_NEXT", samples=None,
                   res=None) -> str
    camera_render_payload(camera_name, out_png, ...) -> str
    save_payload(blend_path) -> str
    inspect_payload() -> str
    evaluate_payload() -> str
    correct_payload(sun_energy=None, exposure=None) -> str
    backup_payload(path) -> str
    validate_payload(render_path=None, blend_path=None) -> str
    one_shot_payload(scene_path, out_dir, slug="scene", ...) -> str
    iteration_payload(out_dir, iteration, ...) -> str
    restore_checkpoint_payload(blend_path) -> str
    loop_plan(scene_path, reference=None, ...) -> list[dict]  # {step, purpose, code}

Core loop: inspect -> safe clear with blocks_build.safe_clear (never
bpy.ops.wm.read_factory_settings, which unregisters the add-on) -> build ->
world/sun/frozen cameras -> render tuning + holdout -> score separately ->
correct one family -> repeat three to six times -> restore the best held-out
checkpoint -> save the .blend, PNG renders, and report.
"""
import os


# ---------------------------------------------------------------------------
# Pure internal utilities
# ---------------------------------------------------------------------------

def _scripts_dir(scripts_dir=None):
    """Return the scripts directory to add to the live Blender sys.path."""
    if scripts_dir:
        return os.path.abspath(str(scripts_dir))
    return os.path.dirname(os.path.abspath(__file__))


def _lit(s):
    """Return a safe Python string literal for paths and other values."""
    return repr(str(s))


# ---------------------------------------------------------------------------
# Payloads: each function returns Python source ready for execute_blender_code.
# ---------------------------------------------------------------------------

def inspect_payload():
    """Inspect the current scene before clearing it, without changing anything."""
    return (
        "import bpy\n"
        "print('[mcp_loop] backup: objects=', len(bpy.data.objects),\n"
        "      'meshes=', len(bpy.data.meshes),\n"
        "      'materials=', len(bpy.data.materials),\n"
        "      'lights=', len(bpy.data.lights))\n"
        "for _o in list(bpy.data.objects)[:40]:\n"
        "    print('  -', _o.name, _o.type)\n"
    )


def build_payload(scene_path, heading=None, sv_xy=(0.0, 0.0), height=2.5,
                  fov=78.0, scripts_dir=None):
    """Build source for import, safe clear, scene construction, world, and camera.

    ``heading=None`` selects a three-quarter aerial camera. A numeric heading
    (0=N, 90=E) selects a street-level camera.
    """
    sp = _scripts_dir(scripts_dir)
    street = heading is not None
    lines = [
        "import sys, json, importlib",
        "sys.path.insert(0, %s)" % _lit(sp),
        "import blender_build as bb",
        "importlib.reload(bb)",
        "with open(%s) as _f:" % _lit(scene_path),
        "    scene = json.load(_f)",
        "# Safe clear: never use bpy.ops.wm.read_factory_settings; it unregisters",
        "# the Blender MCP add-on and terminates the server. clear_scene() is safe.",
        "bb.clear_scene()",
        "cx, cy, R = bb.build_scene(scene)",
    ]
    if street:
        lines += [
            "bb.setup_world(sky=True)",
            "bb.setup_streetview_camera(%r, %r, %r, %r, %r)" % (
                float(heading), float(fov), float(height),
                float(sv_xy[0]), float(sv_xy[1])),
            "bb.apply_street_view_settings()",
        ]
    else:
        lines += [
            "bb.setup_world(sky=False)",
            "bb.setup_sun()",
            "bb.setup_camera(cx, cy, R)",
        ]
    lines += [
        "print('[mcp_loop] built', len(scene.get('buildings', [])),",
        "      'buildings roads=', len(scene.get('roads', [])),",
        "      'R=%.1fm' % R)",
    ]
    return "\n".join(lines) + "\n"


def block_build_payload(scene_path, out_dir=None, slug=None, style_path=None,
                        samples=48, scripts_dir=None):
    """Build source for the required editable-block construction path."""
    sp = _scripts_dir(scripts_dir)
    scene_path = os.path.abspath(str(scene_path))
    out_dir = os.path.abspath(str(out_dir or os.path.dirname(scene_path) or "."))
    slug = str(slug or os.path.basename(out_dir) or "scene")
    style_path = os.path.abspath(str(style_path or os.path.join(out_dir, "style.json")))
    lines = [
        "import os, sys, json, importlib",
        "os.makedirs(%s, exist_ok=True)" % _lit(out_dir),
        "sys.path.insert(0, %s)" % _lit(sp),
        "import architectural_detail, highway_detail, hospital_detail, stadium_detail, urban_detail",
        "for _semantic_module in (architectural_detail, highway_detail, hospital_detail, stadium_detail, urban_detail):",
        "    importlib.reload(_semantic_module)",
        "import blocks_build",
        "importlib.reload(blocks_build)",
        "_info = blocks_build.build_from_scene(",
        "    %s, %s, %s, style_path=%s," % (
            _lit(scene_path), _lit(out_dir), _lit(slug), _lit(style_path)),
        "    do_render=False, samples=%d, clear=True)" % int(samples),
        "print('[mcp_loop] block build info', json.dumps(_info, sort_keys=True))",
    ]
    return "\n".join(lines) + "\n"


def render_payload(out_png, engine="AUTO", samples=None, res=None):
    """Build source that configures rendering and writes a still to out_png."""
    lines = [
        "import bpy",
        "scn = bpy.context.scene",
        "_preferred_engine = %s" % _lit(engine),
        "_engine_candidates = ([_preferred_engine] if _preferred_engine != 'AUTO' else []) + "
        "['BLENDER_EEVEE_NEXT', 'BLENDER_EEVEE', 'CYCLES']",
        "_selected_engine = None",
        "for _engine in _engine_candidates:",
        "    try:",
        "        scn.render.engine = _engine",
        "        _selected_engine = _engine",
        "        break",
        "    except Exception:",
        "        pass",
        "if _selected_engine is None:",
        "    raise RuntimeError('No compatible Blender render engine found')",
        "for _look in ('Medium High Contrast', 'AgX - Medium High Contrast', 'None'):",
        "    try:",
        "        scn.view_settings.look = _look",
        "        break",
        "    except Exception:",
        "        pass",
    ]
    if samples is not None:
        s = int(samples)
        lines += [
            "try:",
            "    scn.cycles.samples = %d" % s,
            "except Exception:",
            "    pass",
            "try:",
            "    scn.eevee.taa_render_samples = %d" % s,
            "except Exception:",
            "    pass",
        ]
    if res is not None:
        lines += [
            "scn.render.resolution_x = %d" % int(res[0]),
            "scn.render.resolution_y = %d" % int(res[1]),
        ]
    lines += [
        "scn.render.resolution_percentage = 100",
        "scn.render.filepath = %s" % _lit(out_png),
        "bpy.ops.render.render(write_still=True)",
        "print('[mcp_loop] rendered', _selected_engine, '->', %s)" % _lit(out_png),
    ]
    return "\n".join(lines) + "\n"


def camera_render_payload(camera_name, out_png, engine="AUTO", samples=None,
                          res=None, restore=True):
    """Render a named frozen camera, optionally restoring the active camera."""
    lines = [
        "import bpy",
        "_camera_before = bpy.context.scene.camera",
        "_named_camera = bpy.data.objects.get(%s)" % _lit(camera_name),
        "if _named_camera is None:",
        "    raise RuntimeError('required evaluation camera missing: %s')" % camera_name,
        "bpy.context.scene.camera = _named_camera",
        render_payload(out_png, engine=engine, samples=samples, res=res),
    ]
    if restore:
        lines.append("bpy.context.scene.camera = _camera_before")
    return "\n".join(lines) + "\n"


def save_payload(blend_path):
    """Build source that saves the current .blend and persists the loop result."""
    return (
        "import bpy\n"
        "bpy.ops.wm.save_as_mainfile(filepath=%s)\n"
        "print('[mcp_loop] saved ->', %s)\n" % (_lit(blend_path), _lit(blend_path))
    )


def backup_payload(backup_path):
    """Save the live scene before the safe clear as a recoverable backup."""
    return (
        "import bpy, os\n"
        "os.makedirs(os.path.dirname(%s) or '.', exist_ok=True)\n" % _lit(backup_path) +
        "bpy.ops.wm.save_as_mainfile(filepath=%s)\n" % _lit(backup_path) +
        "print('[mcp_loop] backup ->', %s)\n" % _lit(backup_path)
    )


def validate_payload(render_path=None, blend_path=None, extra_paths=None):
    """Build Blender-side validation that fails on non-deliverable output."""
    lines = [
        "import bpy, os, json",
        "_scene = bpy.context.scene",
        "_checks = {",
        "  'camera': _scene.camera is not None,",
        "  'objects': len(bpy.data.objects) >= 4,",
        "  'meshes': len(bpy.data.meshes) >= 1,",
        "  'materials': len(bpy.data.materials) >= 1,",
        "}",
    ]
    if render_path:
        lines.append("_checks['render_file'] = os.path.isfile(%s) and os.path.getsize(%s) > 4096" %
                     (_lit(render_path), _lit(render_path)))
    if blend_path:
        lines.append("_checks['blend_file'] = os.path.isfile(%s) and os.path.getsize(%s) > 4096" %
                     (_lit(blend_path), _lit(blend_path)))
    for idx, path in enumerate(extra_paths or []):
        lines.append("_checks['extra_file_%d'] = os.path.isfile(%s) and os.path.getsize(%s) > 4096" %
                     (idx, _lit(path), _lit(path)))
    lines += [
        "print('[mcp_loop] validation', json.dumps(_checks, sort_keys=True))",
        "if not all(_checks.values()):",
        "    raise RuntimeError('one-shot validation failed: %s' % _checks)",
    ]
    return "\n".join(lines) + "\n"


def one_shot_payload(scene_path, out_dir, slug="scene", scripts_dir=None,
                     textures_dir=None, hdri_path=None, engine="AUTO",
                     samples=48, res=(1400, 1000), backup=True,
                     style_path=None):
    """Build a self-contained editable-block baseline in the live Blender.

    ``textures_dir`` and ``hdri_path`` remain accepted for API compatibility,
    but the block builder intentionally does not import photogrammetry or use
    provider imagery as scene geometry.
    """
    sp = _scripts_dir(scripts_dir)
    out_dir = os.path.abspath(str(out_dir))
    scene_path = os.path.abspath(str(scene_path))
    slug = str(slug or "scene")
    blend_path = os.path.join(out_dir, slug + "_blocks.blend")
    render_path = os.path.join(out_dir, slug + "_aerial.png")
    oblique_path = os.path.join(out_dir, slug + "_oblique.png")
    holdout_path = os.path.join(out_dir, slug + "_holdout.png")
    backup_path = os.path.join(out_dir, "pre_" + slug + ".blend")
    report_path = os.path.join(out_dir, slug + "_report.json")

    lines = [
        "import bpy, os, sys, json, importlib",
        "os.makedirs(%s, exist_ok=True)" % _lit(out_dir),
        "sys.path.insert(0, %s)" % _lit(sp),
    ]
    if backup:
        lines.append(backup_payload(backup_path))
    lines += [
        "import architectural_detail, highway_detail, hospital_detail, stadium_detail, urban_detail",
        "for _semantic_module in (architectural_detail, highway_detail, hospital_detail, stadium_detail, urban_detail):",
        "    importlib.reload(_semantic_module)",
        "import blocks_build",
        "importlib.reload(blocks_build)",
        "_info = blocks_build.build_from_scene(",
        "    %s, %s, %s, style_path=%s," % (
            _lit(scene_path), _lit(out_dir), _lit(slug),
            _lit(os.path.abspath(str(style_path))) if style_path else "None"),
        "    do_render=False, samples=%d, clear=True)" % int(samples),
        "print('[mcp_loop] build info', json.dumps(_info, sort_keys=True))",
        "_aerial = bpy.data.objects.get('BLK_CamAerial')",
        "_oblique = bpy.data.objects.get('BLK_CamOblique')",
        "_holdout = bpy.data.objects.get('BLK_CamHoldout')",
        "if _aerial is None or _oblique is None or _holdout is None:",
        "    raise RuntimeError('block builder did not create all evaluation cameras')",
        "bpy.context.scene.camera = _aerial",
        render_payload(render_path, engine=engine, samples=samples, res=res),
        "bpy.context.scene.camera = _oblique",
        render_payload(oblique_path, engine=engine, samples=samples, res=(res[0], int(res[1] * 0.72))),
        "bpy.context.scene.camera = _holdout",
        render_payload(holdout_path, engine=engine, samples=samples, res=(res[0], int(res[1] * 0.72))),
        "_detail_renders = blocks_build.render_detail_views(%s, filename_prefix=%s, resolution=%s)" % (
            _lit(out_dir), _lit(slug), repr([int(res[0]), int(res[1] * 0.72)])),
        "bpy.context.scene.camera = _aerial",
        "bpy.context.scene.render.resolution_x = %d" % int(res[0]),
        "bpy.context.scene.render.resolution_y = %d" % int(res[1]),
        "bpy.context.scene.render.filepath = %s" % _lit(render_path),
        save_payload(blend_path),
        validate_payload(render_path, blend_path, extra_paths=[oblique_path, holdout_path]),
        "_report = dict(_info)",
        "_report.update({'role': 'editable-block-baseline', 'construction': 'blocks', "
        "'provider_mesh_imported': False, 'blend': %s, 'render': %s, 'oblique': %s, 'holdout': %s, 'engine': bpy.context.scene.render.engine, "
        "'detail_renders': _detail_renders, 'objects': len(bpy.data.objects), 'materials': len(bpy.data.materials)})" %
        (_lit(blend_path), _lit(render_path), _lit(oblique_path), _lit(holdout_path)),
        "with open(%s, 'w', encoding='utf-8') as _f:" % _lit(report_path),
        "    json.dump(_report, _f, indent=2, ensure_ascii=False)",
        "print('[mcp_loop] BASELINE_READY', json.dumps(_report, sort_keys=True))",
        "print('[mcp_loop] ONE_SHOT_OK', json.dumps(_report, sort_keys=True))",
    ]
    return "\n".join(lines) + "\n"


def iteration_payload(out_dir, iteration, engine="AUTO", samples=32,
                      res=(1400, 1000), prefix="loop", include_holdout=True):
    """Render and save a comparable checkpoint for one iteration.

    Scoring happens outside Blender through ``loop_engineering``; this payload
    preserves the exact artifact that received the score.
    """
    out_dir = os.path.abspath(str(out_dir))
    index = int(iteration)
    if index < 0:
        raise ValueError("iteration must be >= 0")
    stem = "%s_%02d" % (str(prefix), index)
    render_path = os.path.join(out_dir, stem + ".png")
    holdout_path = os.path.join(out_dir, stem + "_holdout.png")
    blend_path = os.path.join(out_dir, stem + ".blend")
    lines = [
        "import os, json, bpy",
        "os.makedirs(%s, exist_ok=True)" % _lit(out_dir),
        render_payload(render_path, engine=engine, samples=samples, res=res),
    ]
    if include_holdout:
        lines.append(camera_render_payload("BLK_CamHoldout", holdout_path,
                                           engine=engine, samples=samples,
                                           res=res, restore=True))
    lines += [
        save_payload(blend_path),
        validate_payload(render_path, blend_path,
                         extra_paths=[holdout_path] if include_holdout else []),
        "print('[mcp_loop] ITERATION_READY', json.dumps({"
        "'iteration': %d, 'render': %s, 'holdout': %s, 'blend': %s}, sort_keys=True))" %
        (index, _lit(render_path), _lit(holdout_path) if include_holdout else "None",
         _lit(blend_path)),
    ]
    return "\n".join(lines) + "\n"


def restore_checkpoint_payload(blend_path):
    """Restore the best checkpoint after stagnation or the iteration limit.

    Opening a .blend is not a factory reset, but the caller should immediately
    verify the MCP connection again.
    """
    return (
        "import bpy, os\n"
        "_checkpoint = %s\n" % _lit(os.path.abspath(str(blend_path))) +
        "if not os.path.isfile(_checkpoint):\n"
        "    raise RuntimeError('checkpoint not found: %s' % _checkpoint)\n"
        "bpy.ops.wm.open_mainfile(filepath=_checkpoint)\n"
        "print('[mcp_loop] BEST_CHECKPOINT_RESTORED', _checkpoint)\n"
    )


def evaluate_payload():
    """Build source that reports key render settings before correction."""
    return (
        "import bpy\n"
        "scn = bpy.context.scene\n"
        "vs = scn.view_settings\n"
        "print('[mcp_loop] evaluate: engine=', scn.render.engine,\n"
        "      'view_transform=', getattr(vs, 'view_transform', '?'),\n"
        "      'exposure=', round(getattr(vs, 'exposure', 0.0), 3))\n"
        "print('[mcp_loop] objects=', len(bpy.data.objects),\n"
        "      'materials=', len(bpy.data.materials))\n"
    )


def correct_payload(sun_energy=None, exposure=None):
    """Build source that applies an exposure and/or sun-energy correction."""
    lines = ["import bpy", "scn = bpy.context.scene"]
    if exposure is not None:
        lines += [
            "try:",
            "    scn.view_settings.exposure = %r" % float(exposure),
            "except Exception:",
            "    pass",
        ]
    if sun_energy is not None:
        lines += [
            "for _l in bpy.data.lights:",
            "    if _l.type == 'SUN':",
            "        _l.energy = %r" % float(sun_energy),
        ]
    lines += ["print('[mcp_loop] correction applied')"]
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Complete loop plan (three to six iterations)
# ---------------------------------------------------------------------------

def loop_plan(scene_path, reference=None, preview_png=None, final_png=None,
              blend_path=None, engine="AUTO", samples=48):
    """Return live-loop steps with ``step``, ``purpose``, and generated ``code``.

    ``reference`` is used only to describe the comparison target.
    """
    preview_png = preview_png or os.path.join("output", "preview.png")
    holdout_png = os.path.splitext(preview_png)[0] + "_holdout.png"
    final_png = final_png or os.path.join("output", "render.png")
    blend_path = blend_path or os.path.join("output", "scene.blend")
    ref_note = ("compare against %s" % reference) if reference else \
               "compare against the reference image"
    preview_samples = max(8, int(samples) // 4)

    return [
        {"step": "inspect",
         "purpose": "get_scene_info: inspect and back up the scene before changes",
         "code": inspect_payload()},
        {"step": "clear+build",
         "purpose": "safe clear plus required editable block construction",
         "code": block_build_payload(scene_path, samples=preview_samples)},
        {"step": "screenshot",
         "purpose": "quick preview render for screenshot-based evaluation",
         "code": render_payload(preview_png, engine=engine, samples=preview_samples)},
        {"step": "holdout",
         "purpose": "render the frozen holdout camera; do not tune against this view",
         "code": camera_render_payload("BLK_CamHoldout", holdout_png,
                                       engine=engine, samples=preview_samples)},
        {"step": "evaluate",
         "purpose": "score tuning and holdout views separately against %s" % ref_note,
         "code": evaluate_payload()},
        {"step": "correct",
         "purpose": "correct exposure or sun from evaluation; repeat three to six times",
         "code": correct_payload(exposure=-0.5)},
        {"step": "save+render",
         "purpose": "save the .blend, final PNG render, and concise report",
         "code": save_payload(blend_path) +
                 render_payload(final_png, engine=engine, samples=int(samples))},
    ]
