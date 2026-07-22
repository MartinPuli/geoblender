# Football stadium contract

## Contents

1. Detection
2. Source precedence
3. Geometry and LOD
4. Style keys
5. Evaluation gates
6. Failure modes

## 1. Detection

Auto-activate only when normalized data supports both parts of the claim:

| Evidence | Meaning |
|---|---|
| `leisure=stadium`, `building=stadium`, or `building=grandstand` | Stadium semantics |
| `leisure=pitch` with `sport=soccer`, `football`, or `futsal` | Football semantics |
| `scene_kind=football_stadium` | Both were found during acquisition |
| `stadium_profile.football=true` | Normalized explicit routing signal |

Do not auto-activate for a pitch alone, a venue name containing “stadium,” or a
generic arena with no football evidence. Explicit user intent may force the
workflow even with incomplete OSM, but missing geometry must remain reported.

## 2. Source precedence

Resolve every dimension or identity in this order:

1. Explicit OSM geometry/tags.
2. Verified per-run measurements supplied by the user or a cited source.
3. Authorized visual observation stored in the run configuration.
4. Football-domain metric fallback marked `procedural_inference`.

Pitch orientation comes from the mapped polygon principal axis. A plausible
mapped pitch preserves its measured extent. The current fallback is 105 × 68 m;
it is not presented as the venue's surveyed dimension.

Club colors, stand names, crests, signage, and cardinal identities never enter
the general core. Store them in `output/<slug>/style.json` or an explicit pack.

## 3. Geometry and LOD

Build coarse-to-fine:

1. Pitch position, axis, dimensions, and runoff.
2. Four stand envelopes and height hierarchy.
3. Terrace rows and structural rear frames.
4. Aisles, vomitories, concourses, railings, and access.
5. Seat modules and section pattern.
6. Roof sheets, supports, and trusses.
7. Goals/nets, dugouts, tunnel, fence, scoreboard, and floodlights.
8. Run-specific identity and material weathering.

Keep seat geometry batched into a small number of editable meshes. Use
`seat_spacing` and `max_seat_modules` to bound complexity; do not degrade the
entire stadium back into a single seat-colored slab.

## 4. Style keys

| Key | Default | Purpose |
|---|---:|---|
| `enabled` | `auto` | Detect automatically, force on, or disable |
| `pitch_length`, `pitch_width` | `null` | Verified per-run pitch override |
| `pitch_osm_id` | `null` | Explicit pitch selection in multi-pitch sites |
| `rows_long`, `rows_end` | `16`, `12` | Stand row counts |
| `stand_depth_long`, `stand_depth_end` | `22`, `17` m | Stand depth |
| `stand_height_long`, `stand_height_end` | `18`, `13` m | Stand height |
| `sections_long`, `sections_end` | `8`, `5` | Section count before aisles |
| `aisle_width` | `1.25` m | Stair/aisle gap |
| `seat_spacing` | `0.82` m | Procedural seat module spacing |
| `max_seat_modules` | `8000` | Complexity cap |
| `bowl_shape` | `rectangular` | Four stands by default; `continuous_oval` builds a source/style-authorized continuous superelliptical bowl |
| `bowl_segments`, `bowl_exponent` | `96`, `6` | Smoothness and corner character for a continuous oval bowl |
| `tier_break_rows` | `[]` | Optional per-run concourse/tier breaks in a continuous bowl |
| `exterior_skin` | `false` | Add a reversible patterned outer drum with regular access portals |
| `roof_sides` | `auto` | Map nearby OSM roof footprints; otherwise use a reported inferred fallback |
| `roof_coverage` | `0.78` | Stand-depth coverage |
| `floodlight_height` | `34` m | Inferred tower height |
| `lighting_mode` | `towers` | Use conventional towers or a `roof_ring` when verified by run evidence |
| `signage_text` | `null` | Optional venue identity supplied only by the per-run style |
| `primary_color`, `secondary_color` | neutral defaults | Per-run palette |

Side labels are local to the pitch frame. Do not call them geographic north,
south, east, or west without a verified orientation mapping.

## 5. Evaluation gates

Available stadium-specific gates:

- `min_stadium_stand_rows`
- `min_stadium_stand_sections`
- `min_stadium_seat_modules`
- `min_stadium_aisle_steps`
- `min_stadium_vomitories`
- `min_stadium_roof_panels`
- `min_stadium_roof_supports`
- `min_stadium_floodlight_towers`
- `min_stadium_pitch_markings`
- `min_stadium_goals`
- `required_stadium_sides`

Omit gates for elements verified absent at the real venue. Never lower a gate
only because the current build failed it.

## 6. Failure modes

- **Pitch only:** keep the general maps skill; do not invent a stadium.
- **Stadium but sport unknown:** use the generic stadium fallback until football
  evidence or explicit user intent exists.
- **Multiple pitches:** select the plausible full-size football pitch nearest the
  requested/focus point, or set `pitch_osm_id`; record the chosen OSM ID.
- **Irregular/athletics stadium:** preserve the pitch axis, then use style
  measurements for stand offsets and depth; do not force the site polygon into a
  rectangular building shell.
- **Mapped separate grandstands:** specialized geometry may suppress their
  duplicate generic extrusion only after a successful build and must retain the
  suppressed IDs in `build_report.json`.
- **Missing roof:** disable or restrict `roof_sides` using evidence; do not assume
  every football stadium is fully covered.
- **Performance pressure:** increase seat spacing or lower the seat cap while
  preserving rows, aisles, vomitories, and structural hierarchy.
