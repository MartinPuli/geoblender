# Streetscape infrastructure contract

## Evidence hierarchy

1. Mapped physical outline or axis with explicit dimensions.
2. Mapped semantic node/way with conservative dimensional defaults.
3. Deterministic instances inside an area whose tags explicitly assert
   vegetation cover.
4. No geometry when only a legal rule, broad land-use class, or unrelated
   nearby object suggests a possible feature.

## Roads and islands

- Preserve `turn:lanes=*`, `turn:lanes:forward=*` and
  `turn:lanes:backward=*` lane order. A `|` separates lanes; `;` combines
  movements within one lane.
- Render arrows only from those tags. A generic `turn:lanes=*` value on a
  two-way road is directionally ambiguous and must be reported as such.
- Build a mapped `barrier=kerb` way as the kerb axis. Preserve `kerb=*`,
  `height=*` or `kerb:height=*`; flush/lowered defaults remain effectively
  level.
- `area:highway=traffic_island` is authoritative outline geometry.
  `traffic_calming=island` is a bounded point/way proxy. A
  `traffic_calming=painted_island` remains paint, not a raised obstacle.
- `crossing:island=yes` may add a refuge proxy while keeping a passable opening
  through the pedestrian path.

## Markings and cycleways

- A separate `road_marking=stop_line` node/way or
  `road_marking=lane_divider` way is authoritative marking geometry. Preserve
  `stroke`, width, colour and direction; keep paint just above the road surface
  to avoid z-fighting.
- Do not expand `road_marking=*` into guessed classic longitudinal markings.
  Continue to use road-centerline lane/access/turn tags where they describe the
  road rather than an independently surveyed painted axis.
- Build an offset strip only for `cycleway=lane`, `cycleway:left=lane`,
  `cycleway:right=lane` or `cycleway:both=lane`. Preserve explicit width,
  buffer, separation and side.
- `cycleway=track` or `cycleway=separate` may describe physically independent
  geometry; never duplicate it by offsetting the motor-road axis.
- Add bollards/flexible posts or a kerb only when the corresponding
  `cycleway*:separation=*` value explicitly declares that protection. A buffer
  alone proves space, not a particular object.

## Bus lanes and street parking

- `bus:lanes=*` and `psv:lanes=*` are positional lists. Render only entries
  explicitly marked `designated`; preserve lane order relative to travel
  direction and reverse backward paths before calculating offsets.
- A generic positional list on a two-way road is directionally ambiguous and
  remains metadata-only. `lanes:bus=*` and `lanes:psv=*` provide a count, not a
  position, and therefore never justify offset geometry by themselves.
- Use modern `parking:left=*`, `parking:right=*` or `parking:both=*` physical
  positions. `lane`, `street_side`, `on_kerb` and `half_on_kerb` may become
  bounded surface/bay proxies; `separate` is presumed independently mapped and
  must not be duplicated from the road axis.
- Preserve `parking:*:orientation` and explicit widths. Orientation may select
  a conservative default width, but it does not prove stall paint, occupancy,
  vehicle count or exact longitudinal bay placement. Never generate cars from
  parking tags alone.

## Sidewalks and accessible crossings

- `sidewalk=both/left/right/yes` and side-specific `sidewalk:left/right/both`
  values may produce offset sidewalk strips. Preserve explicit width, surface
  and kerb properties; left/right is relative to the OSM way direction.
- `sidewalk*=separate` declares that a sidewalk axis is mapped independently.
  Keep it metadata-only on the road and never duplicate it as an offset strip.
- Position an integrated sidewalk beyond any explicit `parking=street_side` or
  on-kerb extent on the same side. A parking lane inside the carriageway does
  not add an external offset.
- A node at an actual kerb crossing with `kerb=flush` or `kerb=lowered` may
  become a true sloped curb-ramp surface. Preserve `kerb:height`, wheelchair,
  tactile paving and direction evidence. Do not turn `kerb=raised/yes` into a
  ramp.
- `traffic_calming=table` is a speed table with a flat deck and two sloped
  approaches. Add zebra paint only when the same physical feature is also a
  pedestrian crossing; preserve tactile paving separately.
- Crossing islands/refuges must leave the pedestrian path open. Island proxies
  remain outside the paint envelope and use bounded height/width defaults.
- Acceptance should cap curb-ramp and raised-crossing heights as well as count
  them, so small surface details cannot silently become blocking slabs.

## Vegetation

- `natural=tree` is an individual mapped tree and remains in urban amenities.
- `natural=tree_row` is a mapped row axis. Sample stable approximate trunk
  positions along it and identify them as procedural instances.
- `natural=wood` and `landuse=forest` permit woodland cover instances;
  `landuse=orchard` permits regular orchard-tree instances; `natural=scrub` or
  `natural=shrubbery` permits shrub instances.
- Park, garden, grass, meadow, residential and recreation polygons alone do not
  prove individual trees. Keep them as surfaces unless stronger tags exist.
- Cap instances globally and per area. Use deterministic seeds from feature
  identity so rebuilds do not reshuffle the scene.

## Utilities

- Build overhead conductors only from `power=line` or `power=minor_line` ways.
  Underground/underwater `power=cable` requires a separate subsurface workflow.
- Build supports from explicit `power=pole` or `power=tower` nodes. Do not add
  intermediate supports merely because a line is long.
- Preserve `cables`, `wires`, `circuits`, `voltage`, height and provenance.
  Semantic fallback conductor counts are visual proxies, never measurements.
- Do not connect chargers, cabinets, lamps or unrelated poles into a network.
- Treat `power=substation` area geometry as the mapped facility boundary.
  Preserve `substation`, `location` and `voltage`; internal equipment remains a
  bounded reported proxy unless separately mapped.
- `power=transformer` is a device, not automatically a whole substation.
  Pole-mounted `transformer=*` remains attached to its explicit support when
  that relationship is mapped.
- Use `man_made=utility_pole + utility=telecom` for telecom poles and
  `man_made=street_cabinet + utility=telecom` for accessible cabinets.
- A `communication=line` way becomes visible conductor geometry only with
  `location=overhead`. `location=underground/underwater/indoor` and unspecified
  location remain metadata-only in the surface scene.

## Fluid networks

- Preserve every `man_made=pipeline` mapped axis plus `location`, `substance`,
  `diameter`, `height`, `usage`, `pressure`, operator and provenance.
- Only `location=overground` and `location=overhead` are visible in a surface
  scene. Underground, underwater and unspecified pipelines remain metadata-only.
- `location=overhead` may receive deterministic support proxies sampled along
  the mapped axis. Report them as inferred supports; do not claim mapped
  structural spacing or engineering dimensions.
- `pipeline=valve`, `pipeline=measurement` and
  `man_made=pumping_station` are separate semantic devices. Use distinctive,
  editable grammars and preserve substance/dimension evidence. Do not connect
  nearby devices to unrelated pipelines or infer buried junction geometry.
- Substance may select a visual material token (water/gas/oil/generic), but it
  does not validate operating pressure, ownership, safety state or contents.
- `man_made=manhole` proves a surface access cover, not visible underground
  chambers. `manhole=drain` with `inlet=grate/kerb_grate` becomes a flush
  drainage grate; preserve shape, material, colour and explicit dimensions.
- A `man_made=street_cabinet` with `utility=water/gas/sewerage/heating` is an
  above-ground fluid cabinet. Keep it distinct from manholes and do not infer
  a connection to the nearest pipeline.

## Acceptance evidence

## Pedestrian vertical access

- `highway=steps` preserves the mapped axis plus `step_count`, `step:height`,
  `incline`, wheelchair status and explicit `handrail:left/right/center` tags.
- A wheelchair ramp is rendered from an inclined `footway`/`path` only when
  wheelchair access is explicitly asserted. `ramp=yes` alone does not prove
  its side, width or shape, so it remains metadata unless those facts are mapped.
- `conveying=yes/forward/backward/reversible` identifies escalators or moving
  walkways and keeps direction in the feature profile. `highway=elevator` may
  be a node or an inclined way; both become bounded lift proxies and never a
  duplicated generic road/footway mesh.
- Handrail geometry is emitted only for explicit side tags; an unqualified
  `handrail=yes` is counted as an unspecified requirement, not fabricated mesh.
- Run-specific gates may require `min_pedestrian_steps`,
  `min_pedestrian_step_count`, `min_pedestrian_ramps`,
  `min_pedestrian_escalators`, `min_pedestrian_moving_walkways`,
  `min_pedestrian_elevators`, `min_pedestrian_inclined_elevators`,
  `min_pedestrian_handrails`, length gates and `max_pedestrian_rise_m`.

Use run-specific gates where relevant:

- `min_streetscape_lane_arrows`
- `min_streetscape_kerb_segments`
- `min_streetscape_traffic_islands`
- `min_streetscape_stop_lines`
- `min_streetscape_lane_dividers`
- `min_streetscape_cycle_lanes`
- `min_streetscape_cycle_lane_m`
- `min_streetscape_cycle_lane_separators`
- `min_streetscape_cycle_protection_elements`
- `min_streetscape_bus_lanes`
- `min_streetscape_bus_lane_m`
- `min_streetscape_bus_lane_metadata_profiles`
- `min_streetscape_parking_strips`
- `min_streetscape_parking_strip_m`
- `min_streetscape_manhole_covers`
- `min_streetscape_drainage_inlets`
- `min_streetscape_sidewalk_strips`
- `min_streetscape_sidewalk_m`
- `min_streetscape_sidewalk_metadata_profiles`
- `min_streetscape_sidewalk_kerb_edges`
- `min_streetscape_curb_ramps`
- `min_streetscape_raised_crossings`
- `min_streetscape_speed_tables`
- `max_streetscape_curb_ramp_height`
- `max_streetscape_raised_crossing_height`
- `min_streetscape_tree_rows`
- `min_streetscape_utility_lines`
- `min_streetscape_utility_conductors`
- `min_utility_substations`
- `min_utility_transformers`
- `min_utility_telecom_poles`
- `min_utility_telecom_cabinets`
- `min_utility_communication_lines`
- `min_utility_communication_conductors`
- `min_utility_metadata_only_lines`
- `min_fluid_visible_lines`
- `min_fluid_metadata_only_lines`
- `min_fluid_visible_length_m`
- `min_fluid_supports`
- `min_fluid_pumping_stations`
- `min_fluid_valves`
- `min_fluid_measurement_points`
- `min_fluid_cabinets`
- `min_vegetation_area_zones`
- `min_vegetation_area_instances`
- `min_vegetation_area_parts`
- `required_vegetation_area_kinds`

Also inspect close sidewalk/ramp/raised-crossing, marking, bus/parking,
cycle protection, vegetation,
substation, telecom, pipeline and fluid-equipment views plus an independent
held-out camera for grounding, scale, collisions, z-fighting and excessive
density.
