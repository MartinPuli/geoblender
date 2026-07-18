---
name: blender-mcp-loop
description: Constructs and iteratively refines editable block-based real-place scenes inside a live Blender connected through blender-mcp. Use when the user wants to convert a location, coordinates, or Google Maps link into a Blender scene and asks for Blender MCP, autonomous iteration, building/facade detail, color matching, visual comparison, or infrastructure modeling. Builds source-aware meshes and materials from normalized OSM data, then scores tuning and held-out views before accepting controlled corrections. Never substitutes Google Photorealistic 3D Tiles, screenshots, image planes, or provider imagery for constructed geometry.
---

# Blender MCP loop

Run a closed engineering loop until the scene passes its gates or the best
checkpoint is restored. “One shot” means the user does not micromanage internal
iterations; it does not mean a single internal call. Construct the deliverable
with editable blocks from OSM data, then use this skill to operate live Blender.

## Upstream attribution

This skill is built on [ahujasid/blender-mcp](https://github.com/ahujasid/blender-mcp),
created by Siddharth Ahuja and licensed under MIT. The upstream project provides
the Blender addon, MCP server, connection transport, and native tools. This
repository adds the geographic pipeline and the orchestration/evaluation skill;
do not claim authorship of the upstream Blender MCP implementation.

## Critical rules

- Start with `get_scene_info` or an equivalent query.
- Stop only if Blender MCP does not respond; explain how to connect the addon.
- Save a backup before clearing anything.
- Build the baseline through `blocks_build.build_from_scene`; require named
  `BLK_*` collections and actual editable meshes.
- Require `BLK_CamHoldout` and keep it unseen while choosing corrections.
- Never run `fetch_3dtiles.py` or `import_3dtiles.py` in this workflow.
- Never paste screenshots, image planes, projected imagery, or a provider mesh
  into Blender as a substitute for construction.
- Use `blocks_build.safe_clear()` directly or
  `blocks_build.build_from_scene(..., clear=True)`.
- Never call `bpy.ops.wm.read_factory_settings()` in live Blender: it unregisters
  the addon and breaks the MCP connection.
- Keep API keys in environment variables only. Never write them to files, logs,
  code, or responses. Recommend rotation if a key was pasted into chat.
- Never claim photographic accuracy when OSM provides only footprints and
  estimated heights.

## Generalization gate

Classify every proposed change before editing the skill or scripts:

- **General core:** triggered by schema, OSM tags, scene metrics, or Blender
  capabilities. It may enter the core.
- **Semantic profile:** airport, port, railway, campus, coast, and similar. It
  must depend on tags, never a place name.
- **Run-specific adjustment:** camera, material, or asset for one execution.
  Store it under `output/<slug>` or in `scene.json`.
- **Optional pack:** proprietary or local landmarks/assets. Load explicitly;
  never add their names or coordinates to a default registry.

Reject core rules based on city names, preinstalled geofences, landmark names,
or literal coordinates. Require a tag-driven synthetic test and an unrelated
counterexample before promoting a heuristic.

## MCP transport

Prefer native `get_scene_info`, `execute_code`/`execute_blender_code`, and
`get_viewport_screenshot` tools.

If those tools are not exposed but the addon is listening on `127.0.0.1:9876`,
use the client installed by upstream Blender MCP:

```python
from blender_mcp.server import BlenderConnection
c = BlenderConnection("127.0.0.1", 9876)
try:
    result = c.send_command("execute_code", {"code": code})
finally:
    c.disconnect()
```

Do not confuse a hidden client tool with an unavailable server. Check the port
before requesting user intervention.

## Required engineering loop

Always apply this state machine:

`preflight -> baseline -> split views -> observe -> score tuning+holdout -> rank defect -> hypothesize -> change one family -> checkpoint -> compare delta+gap -> accept/continue/restore best`

`one_shot_payload` creates only iteration zero.

### 1. Preflight and backup

1. Inspect the active scene and record file, objects, materials, and camera.
2. Create `<out>/pre_<slug>.blend` before clearing.
3. Confirm absolute paths for the repository, `scripts/`, textures, and HDRI.
4. Do not request confirmation when the place and live Blender connection are clear.

### 2. Choose radius; keep construction mode fixed

Use these initial radii unless the requested scope suggests otherwise:

| Scope | Radius |
|---|---:|
| Landmark or building | 250–350 m |
| Small neighborhood | 500–700 m |
| Airport, campus, or port | 900–1200 m |
| Large district | 1200–1800 m |

Always construct the deliverable as an editable block model from normalized OSM
data. Use authorized Google imagery only outside the scene as optional comparison
evidence. Even when visual similarity is prioritized, do not switch the
deliverable to Google Photorealistic 3D Tiles or photogrammetry.

### 3. Generate complete data

Run from the terminal:

```bash
python3 REPO/scripts/place_to_3d.py "<PLACE>" --radius <M> --no-render --out REPO/output/<slug>
```

Require buildings, roads, areas, and `special_features` in `scene.json` when
present in the source. Preserve runways, taxiways, aprons, and helipads as
semantic infrastructure. Use outdoor Street View only; use satellite imagery
as the aerial reference. References are judge inputs, never construction inputs.

- If `scene_kind=airport`, require `special_feature_count > 0` when the frame
  includes aviation infrastructure.
- If both buildings and roads are empty, widen the radius or fix geocoding.
- Use `data_quality.building_heights` to separate explicit from estimated heights.
- Never validate an exterior facade against an interior photograph.

### 4. Build the baseline

Generate the payload with `scripts/mcp_loop.py` and send it to Blender:

```python
from mcp_loop import one_shot_payload
code = one_shot_payload(
    scene_path="REPO/output/<slug>/scene.json",
    out_dir="REPO/output/<slug>",
    slug="<slug>",
    scripts_dir="REPO/scripts",
    style_path="REPO/output/<slug>/style.json",
    engine="AUTO",
    samples=48,
    res=(1400, 1000),
)
```

Require `BASELINE_READY` and verify `construction=blocks` and
`provider_mesh_imported=false` in its report. The payload performs backup, safe
clear, `blocks_build.build_from_scene`, compatible Eevee/Cycles selection,
aerial, oblique tuning, and holdout renders, camera restore, save, and validation.

By default the baseline already varies estimated/default building heights
(deterministically per `osm_id` and footprint area, never touching explicit OSM
height/levels), adds a thin darker roof band to individual buildings, and colors
each building with its own OSM/estimated tone (`color_mode=scene`). This is the
skill's normal look, not a per-run tweak. `style.json` can still tune or disable
it (`height_variation`, `roof_detail`, `color_mode`). Report reshaped heights
and colors as inferred. Explicit OSM colors and material tags outrank priors.
Authorized aerial samples populate roof color only; they never repaint facades.

Individual buildings use a tag-driven facade grammar. `building:levels`, height,
type/use, and material determine floor spacing, bay width, opening ratios, and
surface response. The procedural shader aligns to each face and excludes roofs;
near-field buildings also receive capped editable window-panel geometry. This
is a reusable LOD rule, not a building-name exception.

Honor OSM Simple 3D Buildings before adding inferred detail: render
`building:part` volumes instead of their containing outline, preserve per-part
height/min-height/material/roof attributes, and use explicit roof height,
levels, orientation, and direction. Within the construction-detail LOD radius,
add bounded inferred plinths, floor strings, cornices, and one grounded entrance
anchor. Record those layers as inferred and keep the source massing unchanged.

A `building=stadium`/`grandstand` footprint is built with a real interior —
outer wall plus concentric seating tiers raking down to the pitch
(`stadium_interior`, tag-driven) — instead of a hollow flat-topped box. The
tiers are inferred seating; never claim they are surveyed rows.

### 5. Initialize measurable state

```python
import loop_engineering as le
state = le.new_state(
    project="<slug>",
    references=["reference_oblique.png"],
    holdout_references=["reference_holdout.png"],
    max_iterations=6,
    target_score=85,
    min_dimension=70,
    min_delta=1.0,
    patience=2,
    max_generalization_gap=8.0,
)
le.save_state(state, "<out>/loop_state.json")
```

Persist state after every observation. Never rely only on conversational memory.

### 6. Observe and score

Open the aerial and oblique tuning renders plus the different-azimuth holdout.
Do not inspect the holdout while choosing a change. Score both sets separately:

1. `semantics`: critical layers are present and correctly typed.
2. `geometry`: footprints, scale, heights, density, and artifacts.
3. `silhouette`: skyline, roofline, massing, and landmark outline.
4. `facade_structure`: floor rhythm, bay rhythm, opening ratio, and LOD artifacts.
5. `color`: facade and roof palette inside matched building masks.
6. `framing`: subject readability, cropping, and reference pose.
7. `materials`: plausible roughness, glass, masonry, metal, asphalt, and water.
8. `lighting`: exposure, shadows, sky, and contrast.

Score color only after camera/framing passes. Exclude sky, vegetation, cast
shadows, and specular highlights from facade color comparisons. Use perceptual
color difference as a diagnostic, never as a single stopping criterion.

Record defects as `{category, severity, impact, fix}`. Treat missing semantics,
an empty scene, invalid camera, broken geometry, or black/burned renders as critical.

### 7. Apply one controlled change

Use `le.decision(state)`. When it returns `correct_one_family`, take only
`next_defect` and record:

- Verifiable observation.
- Causal hypothesis.
- One change family.
- Expected result and target metric.

Never mix camera, material, and lighting changes in one iteration. Apply the fix,
checkpoint it with `mcp_loop.iteration_payload`, open the new render, score it
against the same tuning reference, then score the frozen holdout separately via
`validation_scores`. Non-camera changes must keep the camera signature unchanged.

### 8. Decide from evidence

- `deliver`: tuning and holdout weighted scores >=85, every dimension on both
  sets >=70, generalization gap <=8, and no critical defects. Treat low-confidence
  color as an uncertainty to resolve, never as evidence of correctness.
- `correct_one_family`: continue automatically up to six iterations.
- `restore_best`: at the iteration limit or after two deltas below 1 point,
  restore `best_iteration` and verify MCP again.

Select the best checkpoint by the worse of tuning and holdout. A correction that
improves the tuned view but harms holdout is overfitting and must not become best.

## Deterministic corrections

| Symptom | Correction |
|---|---|
| View is too wide | Move the camera closer and target the subject; retain one broad aerial view |
| Grass dominates | Reduce saturation/luminance; never scatter trees on airport clear zones |
| Airport reads as a neighborhood | Use tag-driven flat roofs and an appropriate material profile |
| Runways are missing | Recheck radius and `aeroway` query coverage before inventing geometry |
| Engine identifier fails | Try `BLENDER_EEVEE_NEXT`, `BLENDER_EEVEE`, then `CYCLES` |
| Color look fails | Try `Medium High Contrast`, the AgX variant, then `None` |
| Camera is inside a building | Use `citycamera.safe_street_point` |
| Street View pose differs | Confirm outdoor source, location, heading, and FOV |
| Landmark is generic | Improve its block silhouette from verified measurements or a declared run-specific model |
| Facade color follows the roof | Restore facade source priority; aerial samples belong to `roof_color` |
| Windows run diagonally or appear on roofs | Rebuild the face-tangent facade shader and vertical-face mask |
| Tuned view improves but holdout falls | Reject the tweak and use a tag/source-driven correction |

## Acceptance contract

Do not declare completion until:

- MCP still responds.
- Backup, `.blend`, aerial, oblique, holdout renders, and report exist and are non-empty.
- The scene has an active camera, meshes, and materials.
- The root scene contains `BLK_*` collections produced by the block builder.
- The report says `construction=blocks` and `provider_mesh_imported=false`.
- The aerial camera is active when saving.
- Special scenes retain their critical semantic layers.
- Renders were opened and inspected, not merely generated.
- `loop_state.json` contains baseline, scores, deltas, changes, and `best_iteration`.
- Tuning and `validation_scores`, camera signatures, and generalization gaps are recorded.
- The delivered artifact is the best checkpoint, not necessarily the last one.
- The report separates observed data, estimates, and proxies.

Deliver absolute links to the `.blend`, all three PNGs, `scene.json`, and the report.
Show the best render in the response.

## Honest limits

- OSM provides real layout, but many heights and facades are estimated.
- Street View may lack outdoor coverage.
- Google imagery is comparison evidence only and is never the constructed output.
- Procedural aircraft, cars, and trees provide scale, not the real state of a place.
- “One shot” is an autonomous engineering loop, not a promise of literal
  perfection without sufficient source data. Optimize repeatable held-out
  quality, not one flattering camera.
