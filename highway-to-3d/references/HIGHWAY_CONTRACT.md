# Highway construction contract

## Detection and source precedence

Activate for motorway/trunk carriageways and their links. Explicit OSM width,
lanes, oneway, bridge, tunnel, layer, surface and ref tags outrank procedural
defaults. Do not specialize ordinary streets.

## Geometry requirements

- Build each mapped way as its own carriageway.
- Resolve inferred width as lanes × lane width plus bounded shoulders.
- Add dashed separators between lanes and continuous outer edge lines.
- Keep markings above the deck by a small stable offset.
- Add guardrails and regular posts outside the pavement edge.
- Add a median barrier only for a single bidirectional way with four or more
  lanes; separately mapped one-way carriageways stay separate.
- Add bridge piers at bounded spacing from terrain to deck; omit on tunnels.
- Cap sign gantries and never invent route text.

## Evaluation gates

- `min_highway_carriageways`
- `min_highway_lanes`
- `min_highway_marking_dashes`
- `min_highway_edge_lines`
- `min_highway_guardrails`
- `min_highway_guardrail_posts`
- `min_highway_bridge_piers` when bridges exist
- `min_highway_gantries` when signage is enabled

