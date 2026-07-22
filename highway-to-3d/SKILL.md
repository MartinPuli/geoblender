---
name: highway-to-3d
description: Constructs detailed editable motorways, trunk roads, ramps, bridges, and interchange segments in Blender with lane-aware widths, shoulders, dashed lane markings, edge lines, guardrails, median barriers, bridge piers, and sign gantries. Use when the user requests a highway, freeway, motorway, autopista, autovía, interchange, ramp, viaduct, or road bridge; when OSM contains `highway=motorway|motorway_link|trunk|trunk_link`; or automatically when `scene_kind=highway` or the `highway` specialization is present. Do not use this specialization for ordinary residential streets.
---

# Highway to 3D

Convert mapped carriageway centerlines and tags into editable civil geometry.
Use `scripts/highway_detail.py` through the normal block pipeline; suppress only
the generic road strip for carriageways successfully rebuilt by this module.

## Required workflow

1. Normalize OSM path, width, lanes, oneway, bridge, tunnel, layer, surface,
   ref and maxspeed metadata with `scripts/place_to_3d.py`.
2. Read [references/HIGHWAY_CONTRACT.md](references/HIGHWAY_CONTRACT.md).
3. Resolve each carriageway with `highway_detail.road_spec`. Preserve explicit
   width; otherwise infer width from lane count plus bounded shoulders.
4. Build the deck, dashed lane separators and continuous edge lines from the
   same path. Keep markings slightly above the asphalt without z-fighting.
5. Add outer guardrails and regularly spaced posts. Add a center barrier only
   when a bidirectional multi-lane way actually needs one.
6. For bridges, preserve deck elevation and add bounded piers down to sampled
   terrain. Do not place piers on tunnels.
7. Add a limited number of editable sign gantries to motorway/trunk segments.
   Do not fabricate route text when no reliable `ref` exists.
8. Keep geometry in `BLK_01A_HIGHWAY_DETAIL`, render three views, and evaluate
   carriageways, lanes, markings, barriers, piers and gantries as applicable.

## Fidelity boundaries

- Treat separate OSM ways as separate carriageways; do not invent a median by
  merging them into one slab.
- Explicit width, lanes, oneway, bridge, tunnel and layer tags outrank defaults.
- A ramp uses the same lane-aware grammar but may have fewer lanes and yellow
  marking treatment.
- Do not generate guardrails through junctions or tunnel portals when the input
  makes that conflict detectable.
- Report the indices and OSM IDs of every generic road replaced.

## Completion

A flat gray ribbon is not a completed highway. Require readable lane structure,
shoulders/edges, safety barriers, bridge support where present, bounded signage,
editable separation from ordinary streets, and held-out renders that preserve
continuous alignment.

