# Residential neighborhood contract

## Source semantics

| Evidence | Meaning | Geometry consequence |
|---|---|---|
| `landuse=residential` | Predominantly residential area | Zone ground/material only |
| `residential=*` | Optional zone subtype | Style/profile hint, not a building type |
| `building=house/detached/semidetached_house/terrace/bungalow` | Low-rise dwelling | Domestic facade and roof grammar |
| `building=apartments/residential/dormitory` | Multi-unit dwelling | Repeated bays, balconies where supported |
| `leisure=garden`, `garden:type=*` | Mapped garden | Garden ground and explicit vegetation only |
| `barrier=fence/wall/hedge` | Physical boundary | Editable line structure |
| `highway=service` + `service=driveway` | Mapped driveway | Preserve access corridor |

## Source precedence

Use explicit OSM geometry/tags, then verified run facts, then deterministic
procedural inference. Never derive cadastral ownership, private access, exact
yard layout or exact household count from `landuse=residential` alone.

## Style keys

- `residential.enabled`: `auto`, `true`, or `false`.
- `residential.zone_material`: run palette for residential ground.
- `residential.boundaries`: build explicit mapped barriers.
- `residential.infill.enabled`: opt-in inferred presentation layer.
- `residential.infill.street_trees`, `street_lamps`, `yard_dividers`: bounded
  deterministic infill switches, all off by default.
- `residential.infill.spacing`: minimum spacing in meters.

## Acceptance evidence

Report residential zones, zone area, residential buildings by profile, mapped
boundary segments, mapped gardens, mapped amenities and inferred infill objects
separately. A valid scene must not count inferred infill toward mapped-object
gates.
