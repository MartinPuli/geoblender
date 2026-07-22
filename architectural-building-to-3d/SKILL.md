---
name: architectural-building-to-3d
description: Constructs varied editable architectural buildings in Blender with semantic facade profiles, bilateral or paired symmetry, different window grammars, mullions, balconies, entrances, roof detail, and shallow visible interior depth. Use for real-place or synthetic scenes containing houses, apartments, offices, hotels, schools, civic buildings, warehouses, curtain walls, or healthcare buildings; when the user says buildings look identical, asks for better facades, symmetry, windows, glass walls, interiors, rooms, balconies, or architectural detail; or automatically when normalized data contains buildings or the `architectural_buildings` specialization. Do not use it to claim an inferred interior is a surveyed floor plan.
---

# Architectural Building to 3D

Construct differentiated architecture while preserving mapped footprints,
parts, heights, roof tags, materials, and provenance. Use
`scripts/architectural_detail.py` through `scripts/blocks_build.py`; never invent
identity-specific architecture from a building name.

## Required workflow

1. Normalize the source with `scripts/place_to_3d.py`. Preserve `building`,
   `building:use`, `amenity`, material, levels, parts, min-height, and roof tags.
2. Read [references/ARCHITECTURAL_CONTRACT.md](references/ARCHITECTURAL_CONTRACT.md).
3. Resolve the semantic profile with `architectural_detail.facade_parameters`.
   Profiles must depend on tags and footprint metrics, not organization names.
4. Build source massing first. Render `building:part` volumes instead of a
   duplicate containing outline.
5. Inside the editable LOD radius, add face-aligned symmetric opening arrays,
   recessed glazing, frames and profile-specific mullions.
6. Add shallow room backings, sills and partitions behind glazing so interiors
   read from exterior views. Also create editable floor plates, corridors,
   partitions and service cores in `BLK_BUILDING_INTERIORS`; label them inferred
   and do not call them surveyed floor plans.
7. Add balconies only for profiles that normally support them and keep their
   count bounded. Preserve explicit mapped entrances and roof geometry.
8. Render oblique, aerial and held-out views, then run `scripts/blocks_eval.py`.
   Require profile variety, window depth, symmetry, editable interior-layout
   gates and held-out quality appropriate to the scene.

## Architectural grammar

- `house`: paired domestic openings and restrained facade detail.
- `residential`: repeated bays, balconies and warm/dark room variation.
- `commercial`: larger office windows and stronger mullion grids.
- `curtain_wall`: dense glass bays, high opening ratio and cool interiors.
- `hotel`: bilateral rhythm, repeatable room modules and optional balconies.
- `healthcare`: bilateral windows, clinical light and hospital specialization.
- `education`: broad classroom windows with repeated transoms.
- `civic`: centered bilateral composition and larger structural bays.
- `industrial`: wide bays, clerestory glazing and minimal floor bands.

Use deterministic footprint/OSM-driven variants within a profile. Two unrelated
buildings may share a grammar, but a neighborhood must not collapse into one
identical bay width, opening ratio, height and facade material.

## Fidelity boundaries

- Treat explicit height, levels, parts, roof geometry and facade color as source
  data. Deterministic variation may change defaults only.
- Keep visible interiors shallow and facade-readable. Keep editable inferred
  layouts in their own toggleable collection unless BIM, plans or verified
  interior measurements are supplied.
- Never infer symmetry by mirroring the mapped footprint. Symmetry controls
  opening placement within each source face, not the authoritative massing.
- Keep distant buildings cheap. Use facade shaders or merged geometry outside
  the architectural LOD radius.
- Record profile, variant, symmetric pairs, windows, mullions, visible bays,
  floor slabs, corridors, partitions, cores and balconies in `build_report.json`.

## Completion

Do not accept “many windows” alone. Completion requires multiple semantic
profiles or deterministic variants where the input supports them, symmetric
opening pairs, framed/mullioned windows, visible room depth, a toggleable
editable interior scaffold near the focus, and held-out renders without severe
black frames or geometry explosions.
