---
name: urban-amenities-to-3d
description: Constructs editable mapped street furniture, smart-city utilities, public-space amenities, and recreation equipment in Blender, including trees, benches, lamps, bins, water points, bicycle racks, shelters, bollards, hydrants, post boxes, clocks, cabinets, utility poles, parking meters, EV charging stations, vending machines, parcel lockers, ATMs, defibrillators, picnic tables, recycling, outdoor fitness stations, and playground equipment. Use for plazas, parks, sidewalks, playgrounds, streetscapes, civic spaces, parking areas, or requests to add small urban objects and make an environment feel complete. Never scatter unmapped amenities as observed reality.
---

# Urban Amenities to 3D

Build small urban objects from explicit semantics with meter-scaled, readable
low-poly grammars. Keep them individually editable and bounded in dense scenes.

## Required workflow

1. Normalize explicit nodes and playground equipment with
   `scripts/place_to_3d.py`; preserve kind, height, width, direction, material,
   access and source tags.
2. Read [references/AMENITIES_CONTRACT.md](references/AMENITIES_CONTRACT.md).
3. Classify with `scripts/urban_detail.py`. Build mapped objects into
   `BLK_URBAN_OBJECTS` and playground equipment into `BLK_RECREATION`.
4. Preserve the feature point and ground height. Use explicit dimensions before
   semantic defaults and record `height_source`/`dimension_source`.
5. Align directional objects from `direction=*`; keep a neutral fallback when
   direction is absent rather than optimizing orientation for the camera.
6. Keep repetitive objects bounded by `urban_objects.geometry_radius` and
   `max_objects`. Batch meshes by semantic/material family where practical.
7. Allow procedural infill only through an explicit per-run switch, put it in a
   separate collection, and report it independently from mapped amenities.
8. Validate kind coverage, part counts, scale, grounding and held-out views.

Keep multi-component machines semantic: expose the body, screen/front panel,
controls or locker doors as separate editable meshes. Preserve `capacity`,
`vending`, `fitness_station`, socket/access tags and wall support when present;
do not invent brands, products, cables or utility networks. Route mapped
overhead line axes, poles/towers and conductor proxies through
`streetscape-infrastructure-to-3d`.

## Completion

Require distinctive geometry for every declared kind, source-aware dimensions,
separate editable collections, no floating/oversized objects, no silent random
scatter and a held-out view where important public-space objects remain legible.
