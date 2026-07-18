# The Blender-MCP live loop (primary experience)

> **Upstream:** the Blender addon, MCP server, transport, and native tools come
> from [ahujasid/blender-mcp](https://github.com/ahujasid/blender-mcp) by
> Siddharth Ahuja (MIT). This repository contributes the geographic pipeline and
> the orchestration/evaluation loop described below.

The **primary** way to build and refine a scene is the live Blender-MCP block
loop: an actual Blender is running with the `blender-mcp` addon, and we send
Python through `execute_blender_code`. The deliverable is constructed from OSM
geometry in editable `BLK_*` collections. Reference images stay outside the
scene; Google 3D Tiles, screenshots, and image planes are never substitutes for
constructed geometry.

`scripts/mcp_loop.py` is a **pure** module (no `bpy` at import time) whose helpers
*return the code strings* to send through `execute_blender_code`. That keeps the
loop testable in plain CI (`tests/test_mcp_loop.py`) while the strings run inside
the live Blender.

`one_shot_payload(...)` creates the reproducible baseline. The primary engine is
`scripts/loop_engineering.py`: score the baseline, rank one failure family,
checkpoint a controlled change, measure the delta, then accept or restore the
best checkpoint. “One shot” means no user micromanagement, not one internal call.

## The loop at a glance

```
get_scene_info            inspect / backup (what's there before we touch it)
      |
      v
SAFE clear                blocks_build.safe_clear()   <-- NEVER factory reset
      |
      v
blocks_build.build_from_scene(...)     editable BLK_* geometry
      |
      v
setup_world / sun / camera
      |
      v
get_viewport_screenshot   (or a fast render_payload preview)
      |
      v
score tuning + holdout    8 weighted dimensions + generalization gap
      |
      v
change one family         hypothesis + expected metric
      |
      v
checkpoint + delta        loop_NN.png + loop_NN.blend + loop_state.json
      |
      +--------------------------------------------------+
      | accept gates / continue <= 6 / restore best      |
      +--------------------------------------------------+
      |
      v
save .blend  +  render final PNG  +  short report
```

## Why the SAFE clear matters (do NOT skip this)

**Never call `bpy.ops.wm.read_factory_settings()` in the live Blender.** Under
`blender-mcp` a factory reset reloads Blender, which **unregisters the addon and
kills the MCP server** — the loop dies mid-iteration and you lose the session.

Use the safe clear instead:

```python
blocks_build.safe_clear()   # removes scene data, leaves the addon/server intact
```

`safe_clear()` (in `scripts/blocks_build.py`) removes all objects, collections,
and unused scene data without resetting Blender. The headless renderer
(`render_view.py`) *can* use `read_factory_settings(use_empty=True)` because it
runs in its own throwaway `blender -b` process; the **live loop cannot**.

## The exact block-construction skeleton

This is the core of what `mcp_loop.one_shot_payload(...)` sends, so you normally
do not hand-write it:

```python
import sys, importlib
sys.path.insert(0, r"/Users/.../render/scripts")
import blocks_build
importlib.reload(blocks_build)

report = blocks_build.build_from_scene(
    r"/Users/.../render/output/<slug>/scene.json",
    r"/Users/.../render/output/<slug>",
    "<slug>",
    style_path=r"/Users/.../render/output/<slug>/style.json",
    do_render=False,
    samples=48,
    clear=True,
)
print('[mcp_loop] block build', report)
```

The `importlib.reload(blocks_build)` is the point of the loop: edit the generic
builder or the run-specific `style.json`, resend the payload, and rebuild without
restarting Blender or losing the MCP server.

## Driving it from `mcp_loop`

For the autonomous path:

```python
from mcp_loop import one_shot_payload
code = one_shot_payload(
    "output/airport-example/scene.json", "output/airport-example", slug="airport_mcp",
    scripts_dir="scripts", style_path="output/airport-example/style.json",
)
# execute_blender_code(code=code)
```

Require `ONE_SHOT_OK`, `construction=blocks`, and
`provider_mesh_imported=false`; treat it as `BASELINE_READY`, then open the
aerial and oblique tuning PNGs. Reserve the different-azimuth holdout PNG for
validation after selecting a correction.
`render_payload` automatically falls
back across `BLENDER_EEVEE_NEXT`, `BLENDER_EEVEE` and `CYCLES` and also handles
look-name differences between Blender releases.

Initialize `loop_engineering.new_state(...)` with separate `references` and
`holdout_references`, record eight tuning scores plus `validation_scores`, then
use `mcp_loop.iteration_payload(...)` for each controlled correction. Persist
every result with `loop_engineering.save_state(...)`. Accept only when both sets
score >=85, every dimension is >=70, the gap is <=8, and no critical defect
remains. Stop after six iterations or two deltas below one point and restore
`best_iteration`.

For manual/granular iteration:

`mcp_loop.loop_plan(scene_path, reference=...)` returns a list of steps, each a dict
`{"step", "purpose", "code"}`. Send each `code` through `execute_blender_code` in
order; loop over the `screenshot -> evaluate -> correct` steps only while the
score improves (maximum six controlled iterations) before the
final `save+render`:

```python
import mcp_loop
plan = mcp_loop.loop_plan("output/puerto-madero/scene.json",
                          reference="docs/example-puerto-madero.png")
for step in plan:
    print(step["step"], "-", step["purpose"])
    # execute_blender_code(code=step["code"])   # <-- via the blender-mcp tool
```

### The step helpers (all return code strings, no side effects)

| Helper | Loop step | What the returned code does |
| --- | --- | --- |
| `inspect_payload()` | inspect / backup | prints object/mesh/material counts of the *current* scene |
| `block_build_payload(scene_path, ...)` | SAFE clear + build | constructs the required editable `BLK_*` scene |
| `build_payload(scene_path, heading=None, ...)` | optional detailed OSM build | legacy granular helper; not the required block baseline |
| `render_payload(out_png, engine=..., samples=...)` | screenshot / render | sets engine + samples + resolution, `bpy.ops.render.render(write_still=True)` |
| `evaluate_payload()` | evaluate | prints engine / view_transform / exposure to compare vs the reference |
| `correct_payload(sun_energy=..., exposure=...)` | correct | nudges exposure and/or the sun's energy |
| `save_payload(blend_path)` | save | `bpy.ops.wm.save_as_mainfile(...)` |
| `one_shot_payload(...)` | block baseline | backup + `blocks_build` + aerial/oblique/holdout renders + save + report + validation |
| `iteration_payload(...)` | checkpoint | freezes tuning PNG + holdout PNG + BLEND for one scored iteration |
| `restore_checkpoint_payload(...)` | rollback | opens the best scored checkpoint |
| `validate_payload(...)` | acceptance | fails loudly for missing camera/content/files |

For a quick per-iteration preview, `get_viewport_screenshot` (the blender-mcp tool)
is fastest; use `render_payload(...)` when you want a real EEVEE/Cycles frame to
judge materials and lighting.

## What to correct each iteration

Evaluate the screenshot against the reference and adjust, roughly in this order:

1. **Camera** — heading/FOV/height; freeze its signature before appearance work.
2. **Mass and silhouette** — footprint, height, roofline, setback, and voids.
3. **Facade structure** — floor rhythm, bay rhythm, opening ratio, and near LOD.
4. **Color provenance** — explicit facade/roof tags before priors; aerial samples
   only roof color. Compare inside matched masks.
5. **Materials** — glass, masonry, metal, asphalt, water, and roughness.
6. **Exposure / sun** — adjust only after geometry/material comparisons are stable.

Re-send only the payload you changed (e.g. `correct_payload(exposure=-2.6)`), then
re-screenshot. Repeat until it matches.

## Finish

Once both tuning and holdout pass: `save_payload(...)` to write the `.blend`,
render all three final PNGs, and report center, radius, building count, appearance
sources, facade-detail counts, corrections, scores, and generalization gap. The
saved checkpoint plus frozen references make the next session reproducible.
