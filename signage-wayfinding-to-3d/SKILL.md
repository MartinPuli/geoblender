---
name: signage-wayfinding-to-3d
description: Constructs editable physical signage, regulatory sign proxies, crossings, and wayfinding in Blender from OpenStreetMap traffic-sign nodes, street-name signs, guideposts, information boards and maps, public-transport stops, advertising devices, crossing markings, tactile paving, and explicit orientation/dimension tags. Use when users ask for carteles, señalética, señales de tránsito, cruces peatonales, letreros, marquesinas, paradas, publicidad, wayfinding, traffic signs, billboards, boards, pylons, or more detailed streets. Do not turn regulatory tags on an entire road into invented physical signs or claim generic shapes reproduce exact national artwork.
---

# Signage and Wayfinding to 3D

Construct the physical support, plate, frame and optional explicit content of
mapped signs. Keep national glyph artwork and brand graphics separate from the
generic geometry grammar.

## Required workflow

1. Normalize physical nodes with `scripts/place_to_3d.py`. Preserve
   `traffic_sign`, `direction`, `information`, `advertising`, `support`, `size`,
   `height`, `width`, `sides`, `lit`, `luminous`, `name`, `ref` and transit tags.
2. Read [references/SIGNAGE_CONTRACT.md](references/SIGNAGE_CONTRACT.md).
3. Classify with `scripts/urban_detail.py`; use `family=signage` or `transit`
   and keep the source tag in the normalized feature.
4. Build editable supports, frames and plates in `BLK_SIGNAGE`; build bus-stop
   poles, flags, timetable boards and optional mapped shelters in
   `BLK_TRANSIT_DETAILS`.
   Build crossing paint/tactile pads in `BLK_ROAD_SURFACE_DETAILS` only from a
   physical crossing node/way and host them to the nearest mapped road axis.
5. Orient the visible face from `direction=*`. If orientation is absent, use a
   neutral reported fallback; do not silently rotate signs toward the camera.
6. Use explicit `size=length*height`, height and width before semantic defaults.
   Respect `support=wall` by requiring a host or reporting an unresolved host.
7. Render text only from explicit `name`, `ref`, `destination` or user-supplied
   style. Keep it separate and editable; never invent advertising copy.
8. Validate readability in oblique and held-out views, support/plate counts,
   orientation/shape coverage, crossing hosts and absence of floating or
   road-centered signs.

## Fidelity rules

- A `traffic_sign=*` node may represent a physical sign. A value on a way can
  describe regulation over the way and is not automatically a physical object.
- A generic traffic plate is a geometry proxy. Use a licensed national sign
  asset pack only when exact glyph fidelity is requested and provenance allows.
- Use semantic shapes for human-readable values: octagon for stop, inverted
  triangle for give-way, circle for restrictions/mandatory signs, and a
  country-aware generic warning triangle or diamond. Unknown national codes
  stay neutral rectangles instead of guessed artwork.
- `direction=*` controls the face direction; `orientation=*` describes relation
  to traffic flow and is not a substitute bearing.
- Keep billboard content, logos and trademarks out of the generic core.

## Completion

Require source-aware sign classes, meter-scaled supports and plates, distinct
regulatory shapes, explicit orientation where available, separate editable
text/content, hosted crossings/transit detail where mapped, and held-out views
that remain legible without oversized signs.
