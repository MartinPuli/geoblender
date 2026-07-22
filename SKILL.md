---
name: geoblender
description: Constructs and refines an editable block-based Blender scene from an address, coordinates, Google Maps link, or place name. Uses normalized OpenStreetMap geometry for source-aware buildings, residential zones, roads, terrain, vegetation, signage, transit details, monuments, public art, playgrounds, amenities, streetscape infrastructure, and covered structures, then routes difficult semantic features to architectural, stadium, hospital, highway, residential-neighborhood, signage-wayfinding, monuments-public-art, urban-amenities, or streetscape-infrastructure specializations, and evaluates silhouette, facade structure, and color on tuning and held-out views. Use when the user wants to reconstruct, inspect, measure, detail, or render a real place in 3D through Blender or blender-mcp. This skill never uses Google Photorealistic 3D Tiles, screenshots, image planes, or provider imagery as construction geometry.
---

# GeoBlender

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
- Load and follow `football-stadium-to-3d` when the user explicitly requests a
  football stadium or normalized data reports `scene_kind=football_stadium` or
  `stadium_profile.football=true`. Do not accept the generic bowl as completion.
- Load `architectural-building-to-3d` whenever buildings are present or the
  user asks for facade variety, symmetry, windows, balconies, or interiors.
- Load `hospital-to-3d` for hospital/clinic semantics or `scene_kind=hospital`.
  Use it alongside the architectural specialization rather than replacing it.
- Load `highway-to-3d` for motorway/trunk/link semantics or
  `scene_kind=highway`. Ordinary streets stay in the generic road builder.
- Load `residential-neighborhood-to-3d` for `landuse=residential`, residential
  building districts, housing estates, subdivisions or neighborhood detail.
- Load `signage-wayfinding-to-3d` for traffic signs, information/guideposts,
  public-transport stops, advertising boards, billboards, columns or flags.
- Load `monuments-public-art-to-3d` for memorials, monuments, statues, busts,
  sculptures, murals, installations, obelisks or fountains.
- Load `urban-amenities-to-3d` for mapped street furniture, utilities,
  vegetation, shelters and playground equipment.
- Load `streetscape-infrastructure-to-3d` for lane arrows, explicit road
  markings, on-road cycle lanes/protection, kerbs/islands, vegetation-cover
  areas/tree rows, substations/transformers, poles/cabinets, power lines and
  explicitly overhead communication lines.

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

## Preferred one-command workflow

Use the safe wrapper for normal runs. It normalizes OSM, constructs editable
blocks, renders oblique/aerial/holdout views, and evaluates the artifacts:

```bash
python3 scripts/blocks_pipeline.py "<place>" --radius <meters> \
  --out output/<slug> --terrain
```

Pass `--no-references` when optional Google comparison references are unwanted,
`--style output/<slug>/style.json` for run-specific choices, or `--scene
output/<slug>/scene.json` to rebuild without downloading data. Use the separate
commands below only for inspection, debugging, or live-Blender iteration.

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
- **Stadium routing.** Football stadiums use `football-stadium-to-3d` and the
  scene-level `stadium_detail` builder: mapped pitch orientation, four stands,
  modular seating, aisles, vomitories, open rear structure, roofs, goals, access,
  and lighting. Keep `stadium_interior` only as a fallback for non-football
  arenas or incomplete generic stadium data.
- **Architectural routing.** Buildings use `architectural-building-to-3d` and
  `architectural_detail.py` for semantic profiles, deterministic variants,
  centered/symmetric opening arrays, recessed glass, mullions, balconies and
  shallow visible room depth, plus toggleable inferred floor plates, corridors,
  partitions and cores. Preserve mapped massing and label inferred rooms.
- **Hospital routing.** Hospital and clinic semantics use `hospital-to-3d` and
  `hospital_detail.py` for public canopy, emergency bay, medical signage,
  ambulance markings, rooftop plant and evidence-bounded helipads.
- **Highway routing.** Motorway/trunk carriageways and links use
  `highway-to-3d` and `highway_detail.py` for lanes, shoulders, markings,
  guardrails, median barriers, bridge piers and bounded sign gantries.
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
  Add bounded editable window panels with recessed glass and four-piece frames
  only inside `facade.geometry_radius`; merged/distant buildings keep the shader
  or flat LOD.
- **Construction-detail LOD.** Inside `construction_detail.geometry_radius`,
  add bounded inferred plinths, floor strings, cornices, and one entrance on
  the grounded detail anchor. Keep these layers identity-free, cap them per
  building, label them inferred, and never let them change source massing.
- **Open covered structures.** Render `building=roof`, `building:part=roof`,
  canopies, carports, shelters, and non-building `covered=yes` polygons as thin
  roof decks with open clearance, perimeter beams, and bounded supports. Never
  turn a mapped open cover into an enclosed solid. Keep roof/support objects in
  `BLK_COVERED_STRUCTURES` and report inferred clearance/support geometry.
- **Urban objects.** Convert explicit OSM trees, benches, street lamps, waste
  baskets, drinking water, bicycle parking, shelters, bollards, and gates into
  semantic low-poly objects inside `urban_objects.geometry_radius`. Keep them
  in `BLK_URBAN_OBJECTS`, cap their count, and never scatter unmapped objects as
  though they were observed.
- **Residential routing.** Preserve `landuse=residential` as zone evidence,
  optional `residential=*` as a zone subtype, mapped gardens, driveways and
  barriers, then combine neighborhood structure with architectural building
  grammars. Never reinterpret a residential zone boundary as cadastral parcels.
- **Signage routing.** Build physical sign supports, plates and explicit text for
  mapped traffic-sign nodes, information/guideposts, transit stops and
  advertising devices. Preserve `direction`, `size`, `support`, `sides` and
  lighting tags; never invent physical signs from a road-wide regulation. Use
  semantic octagon/triangle/circle/diamond proxies for known human-readable
  regulatory values and preserve unknown national codes without guessing glyphs.
- **Crossing routing.** Host `highway=crossing` paint to the nearest mapped road
  axis/width, preserve `crossing:markings=*`, and add tactile pads only from
  explicit `tactile_paving=yes`. Unmarked crossings remain unpainted.
- **Streetscape routing.** Preserve `turn:lanes*` direction/lane order and add
  generic editable arrows only from those explicit tags. Build mapped kerb axes,
  raised/painted/refuge islands, tree rows, bounded deterministic forest/orchard/
  scrub instances and overhead power conductors from their mapped axes. Keep
  ambiguous two-way arrows and all area instances labeled as inference; never
  connect unrelated poles or expose underground cables overhead.
- **Public-art routing.** Build semantic editable fallbacks for statues, busts,
  steles, plaques, stones, obelisks, monuments, sculptures, installations,
  murals and fountains. Report symbolic massing separately from verified or
  licensed identity geometry.
- **Amenity routing.** Build distinctive grammars for hydrants, post boxes,
  phones, clocks, cabinets, parking meters, charging stations, vending
  machines, parcel lockers, ATMs, defibrillators, fitness stations, picnic
  tables, recycling and mapped playground equipment alongside the existing
  furniture/vegetation set.

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
For relevant scenes, use run-specific gates such as `min_covered_structures`,
`min_cover_columns`, `min_urban_objects`, `required_urban_object_kinds`, and
`min_urban_wall_hosted`, `min_residential_boundary_segments`, and
`min_facade_window_frame_parts`.

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
- `scripts/blocks_pipeline.py`: preferred one-command acquire/build/render/eval flow.
- `scripts/stadium_detail.py`: detailed football-stadium specialization used
  automatically by `football-stadium-to-3d`.
- `scripts/architectural_detail.py`: semantic building profiles and variants
  used automatically by `architectural-building-to-3d`.
- `scripts/hospital_detail.py`: hospital access, signage and roof specialization.
- `scripts/highway_detail.py`: lane-aware motorway, ramp and bridge specialization.
- `scripts/urban_detail.py`: shared residential/signage/public-art/amenity/
  streetscape taxonomy, deterministic sampling, dimension defaults and
  provenance-aware normalized object specs.
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
