---
name: hospital-to-3d
description: Constructs detailed editable hospitals, clinics, medical centers, and healthcare campuses in Blender while preserving mapped building wings and adding recognizable entrances, emergency circulation, medical signage, rooftop plant, service access, ambulance markings, and suitable helipads. Use when the user requests a hospital or clinic, when OSM has `amenity=hospital|clinic`, `healthcare=hospital|clinic`, `building=hospital`, or a hospital building use, or automatically when `scene_kind=hospital` or the `hospital` specialization is present. Use architectural-building-to-3d alongside it for windows and visible interior depth.
---

# Hospital to 3D

Build healthcare identity from semantics and access logic, never from a venue
name. Preserve mapped wings and let `scripts/hospital_detail.py` add specialized
objects above the general architectural building layer.

## Required workflow

1. Normalize all hospital and clinic tags plus building parts, service roads,
   covered areas and helipads with `scripts/place_to_3d.py`.
2. Read [references/HOSPITAL_CONTRACT.md](references/HOSPITAL_CONTRACT.md).
3. Load `architectural-building-to-3d` for facade profiles, bilateral opening
   rhythm, mullions and shallow clinical interior depth.
4. Keep every mapped hospital footprint as authoritative. Do not replace a
   multi-wing campus with one generic slab.
5. Run `hospital_detail.build` automatically for semantically detected sites.
   Add entrance canopy, sliding-door glazing, emergency bay, medical cross,
   ambulance markings and rooftop equipment.
6. Add a rooftop helipad only when mapped or when the roof area passes the
   configured auto threshold. Mark an automatic helipad inferred.
7. Keep specialized objects in `BLK_03B_HOSPITAL`; preserve general walls and
   roofs in building collections so every layer remains editable.
8. Render oblique, aerial and held-out views. Evaluate hospital sites, canopies,
   emergency bays, signs, rooftop units and any required helipad.

## Fidelity boundaries

- Do not infer medical departments, operating rooms, wards or circulation as a
  factual plan without a verified source.
- Emergency access should read clearly but must not erase mapped roads or
  entrances.
- Add one coherent equipment family per roof rather than random rooftop noise.
- Require a non-name semantic trigger. A building named “Hospitality House” is
  not a hospital.
- Report every specialized count and the OSM building IDs used.

## Completion

A taller white building with a red cross is not sufficient. A completed
hospital retains its wings, uses a healthcare facade grammar, has legible public
and emergency access, rooftop service detail, source/inference labels, and
passes held-out gates without hiding the mapped architecture.

