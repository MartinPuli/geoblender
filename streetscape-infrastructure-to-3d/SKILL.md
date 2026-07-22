---
name: streetscape-infrastructure-to-3d
description: Constructs editable evidence-based streetscape infrastructure in Blender from OpenStreetMap turn/bus lanes, street parking, sidewalks and accessible crossings, explicit road markings, cycle lanes and protection, kerbs/islands, vegetation cover, power/telecom networks, and visible fluid pipelines with mapped equipment. Use for detailed streets, veredas, rampas, cruces elevados, carriles de colectivo, estacionamiento, ciclovías, cordones, arbolado, cableado, gabinetes, cañerías, utility networks, road edges, or a more complete public realm. Do not infer exact lane position, sidewalks, markings, parked cars, trees, supports, connections, underground visibility, or equipment layouts without corresponding evidence.
---

# Streetscape Infrastructure to 3D

Build the connective tissue between roads, buildings and small urban objects.
Keep mapped geometry separate from deterministic semantic infill and expose the
confidence of every proxy.

## Required workflow

1. Normalize with `scripts/place_to_3d.py`. Preserve road direction, lanes,
   `turn:lanes*`, `bus:lanes*`/`psv:lanes*`, `parking:left/right/both*`,
   `sidewalk*`, kerb type/height, tactile paving, wheelchair access,
   raised-table semantics, island outline, vegetation-cover type,
   tree-row axis, `road_marking=*` geometry, `cycleway*` side/width/buffer/
   separation, power/communication/pipeline axes, `location`, substance,
   diameter, cables, voltage and dimensions.
2. Read
   [references/STREETSCAPE_CONTRACT.md](references/STREETSCAPE_CONTRACT.md).
3. Classify and sample with `scripts/urban_detail.py`; construct through
   `scripts/blocks_build.py`.
4. Put arrows, markings, cycle strips/protection, kerbs and islands in
   `BLK_ROAD_SURFACE_DETAILS`; vegetation in `BLK_VEGETATION_AREAS`; and power
   or telecom facilities, devices, supports and visible conductors in
   `BLK_UTILITY_NETWORKS`; and visible pipelines/equipment in
   `BLK_FLUID_NETWORKS`.
5. Use `turn:lanes=*` only as explicit arrow evidence. Respect forward/backward
   direction and configured driving side; report ambiguous generic values on
   two-way roads instead of presenting them as surveyed placement.
6. Prefer a mapped `area:highway=traffic_island` outline over a centroid proxy.
   Build `traffic_calming=island` as a bounded semantic object only when no
   outline exists. Keep painted islands flat.
7. Instantiate rows from `natural=tree_row`. Add deterministic area vegetation
   only for semantics that assert cover: wood/forest, orchard, scrub/shrubbery.
   A generic park or residential area does not prove individual trees.
8. Build separate stop-line/lane-divider geometry from mapped
   `road_marking=*`. Derive an offset cycle strip only from explicit
   `cycleway=lane` or side-specific lane tags. Render physical protection only
   when `cycleway*:separation=*` declares it.
9. Build mapped substation outlines and transformer/telecom devices as distinct
   semantic objects. Build communications conductors only when
   `communication=line` also has `location=overhead`; preserve underground or
   unspecified lines as metadata-only evidence.
10. Render a bus lane only when `bus:lanes*` or `psv:lanes*` identifies its
    exact lane position. Keep `lanes:bus=*`/`lanes:psv=*` count-only evidence
    as metadata. Render parking surface/bay proxies from modern
    `parking:left/right/both=*` tags, but never invent parked vehicles or offset
    `parking=separate` from the road axis.
11. Render `man_made=pipeline` only for explicit `location=overground` or
    `location=overhead`. Preserve buried, underwater and unspecified axes as
    metadata. Build mapped `pipeline=valve`, `pipeline=measurement` and
    `man_made=pumping_station` nodes as distinct editable equipment.
12. Build `man_made=manhole` covers and `inlet=grate/kerb_grate` drainage
    points as flush road-surface objects. Route water/gas/sewerage/heating
    `man_made=street_cabinet` points to fluid equipment without inventing their
    underground connections.
13. Derive sidewalk strips only from explicit `sidewalk=both/left/right/yes`
    or side-specific equivalents. Treat `sidewalk*=separate` as metadata because
    its geometry should be a separately mapped footway. Place integrated
    sidewalks beyond explicit street-side parking instead of overlapping it.
14. Build `kerb=flush/lowered` nodes as low true-slope curb ramps, preserve
    tactile paving, and build `traffic_calming=table` with ramped approaches.
    A table plus `highway=crossing` receives crossing paint and optional tactile
    pads; a table alone remains a speed table.
15. Normalize `highway=steps` as stepped editable axes with `step_count`,
    `step:height`, `incline` and explicit handrail sides. Normalize wheelchair
    footway/path ramps only when incline and wheelchair semantics are present;
    keep `ramp=yes` without side/shape evidence as metadata. Preserve
    `conveying=*` direction for escalators and moving walkways, and map
    `highway=elevator` nodes/ways as lift proxies without duplicating generic
    footways. Never fabricate a handrail when only `handrail=yes` is present.
16. Validate explicit-source coverage, generated parts, caps, grounding,
   direction, collection separation and dedicated held-out views.

## Fidelity rules

- Keep lane-arrow glyphs generic and editable; do not claim exact national
  paint artwork or precise longitudinal placement without mapped markings.
- `cycleway=track` and `cycleway=separate` do not justify an offset strip from
  the motor-road axis; use their independently mapped geometry instead.
- The default cycle-lane colour is a style token, not a jurisdictional claim.
- Bus-lane and parking colours are style tokens. Positional lane lists are
  ordered relative to their travel direction; reverse backward paths before
  applying left-to-right offsets.
- Parking orientation changes the bounded strip width but does not prove
  occupancy, stall count, markings or vehicle placement.
- Sidewalk left/right follows the mapped way direction. Never duplicate
  `sidewalk=separate`, and never offset a sidewalk through explicit parking.
- Keep `kerb=flush` near zero and `kerb=lowered` wheelchair-traversable. Use
  sloped faces for ramps/tables; a vertical block is not an accessible proxy.
- A crossing refuge must keep the marked pedestrian path open and must not
  cover zebra paint or tactile pads.
- A mapped substation area proves a facility boundary, not exact internal
  switchgear placement. Label bounded equipment as semantic proxies.
- Treat `barrier=kerb` as the physical kerb axis. Preserve flush/lowered kerbs
  at negligible height instead of turning them into barriers.
- Treat area tree/shrub positions as inferred instances. Preserve the mapped
  polygon as the observed evidence and use deterministic placement for stable
  rebuilds.
- Use explicit `cables=*` when available. Otherwise expose the conductor count
  as a semantic fallback derived from line class.
- Apply geometry radius and count caps so dense forests or networks cannot
  overwhelm the Blender scene.
- Pipeline supports may be generated only for an explicit overhead location;
  label them as procedural support proxies. Substance selects a style material,
  not an engineering certification.

## Completion

Require the relevant `streetscape`, `vegetation_areas`, `utility_networks` and
`fluid_networks`
metrics, source-aware provenance, no duplicate point/outline features, no
randomly changing vegetation placement, no visible subsurface line, and
readable marking/cycle/facility/network close views plus a held-out render.
