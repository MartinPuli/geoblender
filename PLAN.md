# Plan: a robust open-source maps-to-3d tool

Preserve the Blender MCP loop:

`build -> capture -> compare with references -> detect errors -> correct -> repeat`

## Architecture audit

The original prototype mixed acquisition, normalization, rendering, camera logic,
and place-specific corrections in `scripts/`. The main risks were:

| Problem | Impact |
|---|---|
| Global landmark rules | A heuristic learned from one place could create a false landmark elsewhere |
| No per-building identity | Buildings could not retain OSM ID, provenance, confidence, or individual editability |
| Camera collision | Street views could start inside building footprints |
| Weak architectural inference | Uniform roofs and fixed-scale details produced false silhouettes |
| Coupled sources and renderer | Acquisition, geometry, materials, and cameras were difficult to test independently |
| No normalized intermediate model | There was no stable contract for provenance, confidence, or alternate renderers |
| No packaging or tests | The prototype was difficult to install, reproduce, and regression-test |
| Persistent Google tile extraction | This conflicts with render-only provider terms |

## Target architecture

```text
Sources            OSM / elevation / open imagery / optional Google render path
  ->
Normalized model   CityScene {buildings, roads, areas, features, provenance}
  ->
3D generators      Native procedural engine or optional OSM2World adapter
  ->
Backends           Headless Blender or live Blender through upstream Blender MCP
  ->
Evaluator          Render -> reference -> score -> one controlled fix -> repeat
```

Keep landmarks, materials, and cameras out of data acquisition. Run-specific
choices belong in output configuration, not global code.

## Incremental phases

### Phase 0: compatibility

Keep existing flows working while placing new behavior behind explicit adapters,
registries, or configuration.

### Phase 1: hard acceptance criteria

- Remove preinstalled location tuning from the core.
- Move street cameras outside building footprints.
- Add deterministic tests for clipping, heights, landmarks, camera collision,
  and meter scale without live Overpass or Blender dependencies.

### Phase 2: identity and fidelity

- Preserve `osm_id`, tags, `height_source`, provenance, and confidence per entity.
- Apply height precedence: explicit height, levels, then tagged estimates.
- Support OSM building and roof materials/colors when present.
- Build common `roof:shape` values with deterministic fallback variety.

### Phase 3: profiles and alternate engines

- Infer urban profiles from scene statistics, never city names.
- Keep the native procedural generator as default.
- Offer OSM2World as a fully opt-in alternate adapter.

### Phase 4: packaging and production

- Maintain `pyproject.toml`, CLI, configuration, structured logging, caching,
  and source/license reporting.
- Keep Google 3D Tiles in a separate, attribution-aware render-only pipeline.

### Phase 5: live loop as the primary experience

- Verify the upstream Blender MCP connection.
- Back up before mutation and use safe clear instead of factory reset.
- Capture views, evaluate one defect family, apply one controlled change,
  checkpoint, compare deltas, and restore the best result when needed.

## Acceptance tracking

- [x] No location-specific landmark rules in the core.
- [x] Street camera avoids building interiors.
- [x] Deterministic roof variety and profile-aware fallbacks.
- [x] Per-object provenance and confidence.
- [x] Special infrastructure remains semantically distinct.
- [x] Optional OSM2World adapter.
- [x] Installable package and pure-Python test suite.
- [x] Safe live-Blender loop with checkpoints and restore.
- [x] Generic block renderer and declarative per-run gates.
- [ ] Production-safe ephemeral 3D Tiles rendering with full attribution.
- [ ] Formal held-out perceptual benchmark and automated 2AFC dashboard.
