---
name: maps-to-3d
description: Constructs and refines an editable block-based Blender scene from an address, coordinates, Google Maps link, or place name. Uses normalized OpenStreetMap geometry and source-aware building appearance, then evaluates silhouette, facade structure, and color on tuning and held-out views. Use when the user wants to reconstruct, inspect, measure, detail, or render a real place in 3D through Blender or blender-mcp. This skill never uses Google Photorealistic 3D Tiles, screenshots, image planes, or provider imagery as construction geometry.
---

# Maps to 3D

Construct a georeferenced, editable block scene in meters and preserve the
provenance of every value. Never replace construction with a provider mesh,
photogrammetry import, screenshot, image plane, or texture projection.

## Construction contract

- Use **blocks as the required default deliverable**. Build them from normalized
  OSM footprints, paths, areas, heights, and semantic infrastructure.
- Produce actual Blender meshes in named `BLK_*` collections. The scene must
  remain selectable, measurable, editable, and independently renderable.
- Use Street View, satellite imagery, or other authorized images only as
  external comparison references. Never paste them into the scene to imitate a
  completed reconstruction.
- Do not run `fetch_3dtiles.py` or `import_3dtiles.py` during the normal skill
  workflow. Google Photorealistic 3D Tiles are not construction blocks.
- Use the more detailed procedural OSM renderer only when the user explicitly
  asks for it after the block deliverable exists.
- Use `blender-mcp-loop` when the work must happen inside a live Blender session.

If the request simply says “build it,” construct the editable block scene. Never
infer permission to substitute a photogrammetric render because it looks closer.

## Generalization contract

Keep the core independent from any single run:

- Trigger behavior from normalized tags, geometry, provenance, and metrics;
  never from city names, landmark names, organizations, coordinates, or
  preinstalled geofences.
- Store colors, verified measurements, camera focus, assets, and exceptions in
  `output/<slug>/style.json` or an explicit opt-in pack.
- Do not promote a one-place correction to a global default without a synthetic
  test and an unrelated counterexample.
- Preserve `source`, `confidence`, and `height_source`. Explicit OSM height is
  input data; level-derived or default height remains an estimate.
- Preserve appearance provenance independently for facade and roof. Never let
  an aerial roof sample overwrite an explicit or inferred facade color.
- Prefer declarative per-feature configuration (`osm_id`, tag, or selector) to
  new constructor branches.

Concrete OSM categories such as `aeroway=runway`, `building=grandstand`, or
`memorial=obelisk` are reusable domain semantics; a specific identity is not.

## Preflight

1. Resolve the place to latitude/longitude and choose a radius suitable for the
   requested scope.
2. Confirm Blender and Python. Do not require a Google API key for construction.
3. Create a new `output/<slug>` directory. Never write run-specific tuning into
   `scripts/`.
4. Record sources and attribution. Never print or persist API keys.

## Acquire normalized OSM data

```bash
python3 scripts/place_to_3d.py "<place>" --radius <meters> --no-render --out output/<slug>
```

`place_to_3d.py` writes the normalized `scene.json` contract: buildings, roads,
areas, special infrastructure, provenance, quality, and available visual
references. Treat OSM as the construction source and references as evaluation
evidence only.

If a dense full-bbox Overpass request fails, keep the requested radius: allow
the acquisition layer to retry deduplicated quadrants and then the official OSM
map API with recursive subdivision. Do not remove `building:part` or shrink the
scope merely to make a public endpoint pass.

Resolve building appearance in this priority order:

1. Explicit OSM facade/roof color and material tags.
2. Verified run-specific measurements supplied by the user.
3. Material-class priors such as brick, concrete, glass, metal, or stone.
4. Tag/statistics-driven semantic priors.
5. Deterministic neutral fallback.

Treat a georeferenced aerial sample as roof evidence. Do not apply it to the
facade unless a separate street-level observation supports that decision.

Add `--terrain` to also fetch a real SRTM/DEM elevation grid (OpenTopoData, no
API key) into `scene.json`; the builder then drapes the scene over a displaced
ground mesh. Elevation is real data (attribute NASA SRTM); it is opt-in so
flat-ground runs stay reproducible.

Do not invent facade detail as though it came from OSM. Procedural materials,
vegetation, and traffic may improve readability, but report them as inferred.

## Build the required block model

```bash
blender -b -P scripts/blocks_build.py -- \
  output/<slug>/scene.json output/<slug> <slug> \
  --style output/<slug>/style.json --render --samples 96
```

Use `style.json` only for decisions belonging to that run: palette, focus,
editable radius, camera, verified heights, and optional decoration. If a value
is missing, keep the generic fallback and expose uncertainty in the report.

By default the block builder now renders buildings as a varied neighborhood
rather than a field of identical default boxes:

- **Varied heights.** Estimated/default heights are reshaped deterministically
  per `osm_id` and footprint area. Explicit OSM `height`/`building:levels` are
  never touched, so provenance is preserved — the variation only applies where
  the height was already an estimate, and it stays an estimate in the report.
- **Roof detail.** Individual buildings get a thin, darker roof/parapet band.
- **Source-aware colors.** `color_mode` defaults to `scene`. Explicit OSM colors
  outrank material/semantic priors; aerial sampling fills `roof_color` only.
  Convert display-sRGB inputs to scene-linear values before feeding Principled
  BSDF and retain source plus confidence independently for facade and roof.
- **Stadium interior.** A `building=stadium`/`grandstand` footprint is built
  with a real interior — an outer wall plus concentric seating tiers that rake
  down toward the pitch — instead of a hollow flat-topped box. This is
  tag-driven reusable geometry; `stadium_interior.seat_color`/`wall_color` are
  optional per-run overrides. The tiers are inferred seating, not surveyed.
- **Roof shapes.** `roof:shape` (gabled, hipped, pyramidal, dome, skillion, …)
  is built as a real pitched roof — non-rectangular plans use the footprint's
  principal axis as an oriented-bounding-box ridge, as in blender-osm/OSM2World.
  Buildings without the tag keep the flat cap. (`roof_shapes`)
- **Building parts and form.** Treat `building:part` as the rendered 3D volumes
  and suppress the containing `building` outline. Preserve each part's
  `height`, `min_height` / `building:min_level`, color, material, roof height,
  roof levels, orientation, and direction. Never render outline and parts as
  duplicate solids.
- **Facade grammar.** Derive floor height, bay width, opening ratios, and PBR
  roughness from `building:levels`, height, building/use class, and material.
  Align the shader grid to each face tangent and mask horizontal roof faces.
  Add bounded editable window panels only inside `facade.geometry_radius`;
  merged/distant buildings keep the shader or flat LOD.
- **Construction-detail LOD.** Inside `construction_detail.geometry_radius`,
  add bounded inferred plinths, floor strings, cornices, and one entrance on
  the grounded detail anchor. Keep these layers identity-free, cap them per
  building, label them inferred, and never let them change source massing.

See `docs/REALWORLD_TECHNIQUES.md` for the full survey of real-place-to-Blender
techniques (with sources) and what is implemented versus on the roadmap
(notably DEM/SRTM terrain).

These are general, provenance/geometry-driven defaults, reversible per run via
`height_variation.enabled`, `roof_detail.enabled`, and `color_mode` in
`style.json`. Report the reshaped heights and colors as inferred, not measured.

Define completion criteria in `output/<slug>/eval.json`. Omit irrelevant gates
instead of imposing a threshold designed for a different scene.

```bash
blender -b output/<slug>/<slug>_blocks.blend \
  -P scripts/blocks_eval.py -- output/<slug>
```

The evaluator writes `eval_report.json`. Fix the highest-impact failed gate,
rebuild, and evaluate again. Never relax the objective merely to pass.

## Reference-only sources

Use authorized Street View, satellite, or user-provided images beside the
Blender render during evaluation. Keep them outside the constructed scene.

Deriving a per-feature **roof color attribute** by sampling the authorized
aerial reference (`image_colors`, active only with a Google API key) is
permitted. The image is never pasted into the scene as geometry or texture, and
sampled colors are reported as `imagery_aerial`, not facade measurements.

The repository contains experimental Google 3D Tiles utilities, but they are
outside this skill. If the user explicitly requests that separate workflow, do
not mix its outputs with the block project or present its render as work
constructed by this skill.

## Visual validation loop

1. Freeze camera poses and split references into tuning and held-out views.
2. Render aerial, oblique tuning, and a different-azimuth holdout view.
3. Score semantics, geometry, silhouette, facade structure, color, framing,
   materials, and lighting separately on both sets.
4. Correct one defect family per iteration. Keep the camera frozen unless the
   declared change family is camera/framing.
5. Re-render both sets. Select checkpoints by the worse of tuning and holdout,
   and reject a generalization gap above eight points.
6. Stop when both sets pass, progress stalls, or the iteration budget is exhausted;
   restore the best checkpoint if the result regresses.

Do not optimize raw pixels across unmatched views or use a subjective impression
as the sole criterion. Compare masks/silhouettes before materials; compare color
inside matched building masks and ignore sky, cast shadows, and specular highlights.
No single-view improvement may be promoted to the core if holdout quality falls.

## Resources

- `scripts/place_to_3d.py`: place to `scene.json` and available references.
- `scripts/world_scene.py`: optional detailed procedural OSM build and export.
- `scripts/blender_build.py`: OSM geometry and materials.
- `scripts/blocks_build.py`: editable block presentation.
- `scripts/blocks_eval.py`: declarative per-run gates.
- `scripts/fetch_3dtiles.py` and `import_3dtiles.py`: excluded experimental
  reference-only path; never use for the default construction workflow.
- `scripts/live_build.py`, `mcp_loop.py`, and `loop_engineering.py`: safe live
  execution, checkpoints, and iteration control.
- `scripts/render_view.py`: reproducible comparison views.

## Guardrails

- Never call `read_factory_settings` in live Blender. Clear only the scene-owned
  datablocks and create a backup before mutation.
- Never use Google 3D Tiles, image planes, screenshots, or projected provider
  imagery as a substitute for constructed block geometry.
- Never version `output/`, tiles, renders, caches, API keys, or downloaded assets
  with incompatible licenses.
- Attribute OpenStreetMap/ODbL, Google where applicable, Blender MCP upstream,
  and all third-party assets.
- Report observed, derived, and estimated values separately.
