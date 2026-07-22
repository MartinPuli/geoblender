---
name: residential-neighborhood-to-3d
description: Constructs detailed editable residential districts in Blender from normalized OpenStreetMap landuse, buildings, roads, gardens, access, barriers, and public-realm objects. Use for barrios, neighborhoods, housing estates, subdivisions, apartment complexes, gated communities, residential blocks, houses with yards, or when maps-to-3d reports residential zones/buildings and the user wants the surrounding neighborhood to feel inhabited and structurally varied. Never present inferred gardens, parcel lines, driveways, fences, or interiors as surveyed.
---

# Residential Neighborhood to 3D

Build a district system, not a random collection of houses. Preserve mapped
landuse, footprints, heights, roof tags, access ways, gardens, barriers, trees,
and amenities. Use `architectural-building-to-3d` for individual buildings and
this skill for their neighborhood-level relationships.

## Required workflow

1. Normalize with `scripts/place_to_3d.py`; retain `landuse=residential`, the
   optional `residential=*` subtype, building semantics, service/driveway roads,
   barriers, gardens, playgrounds, parking and explicit street objects.
2. Read [references/RESIDENTIAL_CONTRACT.md](references/RESIDENTIAL_CONTRACT.md).
3. Classify zones and buildings with `scripts/urban_detail.py`; never classify
   from a neighborhood or developer name.
4. Build mapped zone ground, buildings and explicit boundaries first. Keep
   residential area meshes in `BLK_RESIDENTIAL_ZONES` and boundary details in
   `BLK_RESIDENTIAL_BOUNDARIES`.
5. Route every building through `architectural-building-to-3d` for facade,
   roof, entrance, balcony and bounded inferred-interior detail.
6. Add only explicitly mapped gardens, fences, walls, hedges, gates, trees,
   driveways, parking, playgrounds and amenities by default.
7. Allow inferred yard subdivision or street-tree/lamp infill only through an
   explicit per-run style switch. Label it `procedural_inference`, keep it
   deterministic and avoid blocking mapped access.
8. Render oblique, aerial and held-out views. Evaluate zone coverage, building
   variety, mapped boundaries, explicit amenities and lack of geometry overlap.

## Fidelity rules

- `landuse=residential` describes predominant use, not parcel boundaries or an
  individual building. Do not fabricate cadastral lots from the zone outline.
- Treat `residential=*` as a zone subtype and `building=*` as building evidence.
- Preserve significant commercial, retail, school, park and playground areas
  inside or beside a residential zone rather than repainting them residential.
- Keep driveways/service roads navigable and gates aligned to mapped barriers.
- Infill is presentation detail, never observed reality. Report its object
  count separately and make it removable as one collection.

## Completion

Require a readable residential zone, differentiated architecture where the
source supports it, mapped access and boundaries, explicit public-realm objects,
and a held-out view without repetitive cloned houses, blocked roads, floating
yards or invented detail reported as OSM.
