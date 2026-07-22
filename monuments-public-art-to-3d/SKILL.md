---
name: monuments-public-art-to-3d
description: Constructs editable monuments and public-art objects in Blender from OpenStreetMap historic memorials and monuments, memorial statues, busts, steles, plaques, stones, obelisks, tourism artworks, sculptures, installations, murals, fountains, and explicit dimensions/material tags. Use when users ask for estatuas, esculturas, monumentos, memoriales, bustos, obeliscos, murales, fuentes, arte público, landmark plazas, or improved civic-space identity. Generic procedural figures are symbolic massing unless verified references or licensed assets support exact identity.
---

# Monuments and Public Art to 3D

Build recognizable semantic massing while separating mapped facts from artistic
identity. A tagged statue proves a statue exists; it rarely supplies enough
geometry to reconstruct the portrayed person.

## Required workflow

1. Normalize with `scripts/place_to_3d.py`; preserve `historic`, `memorial`,
   `tourism=artwork`, `artwork_type`, `artist_name`, `material`, `height`,
   `width`, `direction`, `support`, `inscription` and fountain semantics.
2. Read [references/MONUMENTS_CONTRACT.md](references/MONUMENTS_CONTRACT.md).
3. Classify with `scripts/urban_detail.py` and build into
   `BLK_MONUMENTS_PUBLIC_ART`, split into base, artwork and water/detail meshes.
4. Use semantic grammars for statue, bust, stele, plaque, stone, obelisk,
   abstract sculpture, installation, mural and fountain. Preserve explicit
   dimensions; otherwise use conservative category defaults.
5. Treat procedural human/animal figures and abstract art as symbolic LOD.
   For exact identity, use verified multi-view references or a licensed asset,
   record its provenance, and keep it replaceable.
6. Require a host surface for wall plaques and murals when mapped. If the host
   cannot be resolved, create no wall claim; report `unresolved_host` or use an
   explicit per-run freestanding display decision.
7. Build inscriptions only from explicit source text or user input. Do not
   fabricate dedications, dates, people or heraldry.
8. Validate silhouette, pedestal scale, orientation, material separation and
   held-out recognition before fine material tuning.

## Completion

Require the correct semantic class, editable component hierarchy, bounded
metric scale, source/procedural provenance, resolved host where needed and
held-out readability. Never call a symbolic statue an exact replica.
