# Architectural detail contract

## Source precedence

1. Explicit OSM/BIM footprint, building parts, height, min-height and roof tags.
2. Explicit facade/roof material and color.
3. Semantic profile from building/use/amenity/material.
4. Deterministic footprint/OSM-driven facade variant.
5. Bounded presentation defaults.

## Geometry requirements

- Preserve the source footprint; do not mirror massing to force symmetry.
- Pair bays around the center of each face and sample capped windows as pairs.
- Use profile-specific bay width, opening ratio, mullion count and lighting.
- Place glass, room backing and partitions at different facade depths.
- Put inferred floor slabs, corridor walls, room partitions and service cores
  in `BLK_BUILDING_INTERIORS` so the source shell can be hidden independently.
- Keep balconies and interior bays capped per building and bounded by radius.
- Mark all non-source openings, rooms, balconies and bands `inferred`.

## Profiles and evidence

`type`, `building_use`, `building_material`, `building_part`, levels, height and
footprint metrics may select a profile. Names, city names and coordinates may
not. A stable OSM/geometry seed may choose a variant only inside that profile.

## Evaluation gates

Use the gates that match the fixture:

- `min_facade_profiles`
- `min_facade_variants`
- `min_facade_window_panels`
- `min_facade_window_frame_parts`
- `min_facade_window_mullions`
- `min_symmetric_window_pairs`
- `min_visible_interior_bays`
- `min_lit_interior_rooms`
- `min_balconies`
- `min_interior_layout_buildings`
- `min_interior_floor_slabs`
- `min_interior_corridor_segments`
- `min_interior_partitions`
- `min_interior_cores`

Always retain the standard render-existence and black-frame gates.
