---
name: football-stadium-to-3d
description: Constructs and iteratively refines detailed, editable football/soccer stadiums in Blender from normalized OpenStreetMap geometry. Use when the user asks to model an estadio de fútbol, soccer stadium, football ground, cancha con tribunas, club stadium, grandstands, terraces, or arena centered on a football pitch; also use automatically when maps-to-3d produces scene_kind=football_stadium or stadium_profile.football=true. Builds the pitch, markings, goals, seating, aisles, vomitories, rear structure, roofs, access, dugouts, tunnel, scoreboard, fencing, and floodlights, then validates tuning and held-out views. Do not use for an isolated community pitch with no stadium semantics.
---

# Football Stadium to 3D

Construct a source-aware stadium complex instead of accepting a generic bowl.
Keep all components editable and distinguish mapped geometry, verified run data,
and procedural inference.

## Activation and delegation

- Activate immediately for explicit football-stadium requests, including Spanish
  terms such as `estadio`, `cancha con tribunas`, `popular`, `platea`, or `gradas`.
- Activate after acquisition when `scene_kind=football_stadium` or
  `stadium_profile.football=true`.
- Do not activate from a venue name alone or for `leisure=pitch` without stadium,
  grandstand, or arena semantics.
- When activated from `maps-to-3d` or `blender-mcp-loop`, keep their source,
  safety, reference, and held-out-evaluation contracts. Replace only the generic
  stadium treatment with this specialized workflow.

## Construction contract

Require actual meshes in these collections:

- `BLK_STADIUM_PITCH`: turf, mowing bands, regulation markings, goals, and nets.
- `BLK_STADIUM_STANDS`: four directional stands, rows, seat modules, aisles, and
  vomitories.
- `BLK_STADIUM_STRUCTURE`: open rear columns, concourse beams, and supports.
- `BLK_STADIUM_ROOFS`: roof sheets, columns, and trusses for configured sides.
- `BLK_STADIUM_DETAILS`: railings, pitch fence, dugouts, player tunnel, and
  scoreboard.
- `BLK_STADIUM_LIGHTING`: floodlight towers and lamp banks.

Orient the whole complex from the mapped pitch principal axis. Preserve mapped
pitch dimensions when plausible; otherwise use a per-run verified dimension or
the reported inferred football fallback. Suppress the generic stadium shell only
after the specialized build succeeds.

Never hard-code a club, city, stadium name, crest, text, palette, cardinal stand
identity, or local correction in the generator. Put those choices in
`output/<slug>/style.json` with provenance.

## Workflow

### 1. Normalize and detect

```bash
python3 scripts/blocks_pipeline.py "<stadium or coordinates>" \
  --radius 350 --out output/<slug> --data-only
```

Inspect `scene.json`. Require a football pitch plus stadium semantics for auto
mode. If the user explicitly requested a football stadium but OSM is incomplete,
set `football_stadium.enabled=true` in `style.json` and report the missing source
geometry rather than pretending it was mapped.

### 2. Configure only the run-specific facts

```json
{
  "focus": {"match": "stadium", "span": 260},
  "football_stadium": {
    "enabled": true,
    "primary_color": [0.08, 0.20, 0.62],
    "secondary_color": [0.80, 0.10, 0.08],
    "seat_pattern": "alternating_sections",
    "roof_sides": ["north", "south"],
    "rows_long": 16,
    "rows_end": 12
  }
}
```

Treat side names as local pitch-frame sides, not geographic claims. Use explicit
measurements or observed references to assign real cardinal identities.

### 3. Build the specialized stadium

```bash
python3 scripts/blocks_pipeline.py --scene output/<slug>/scene.json \
  --out output/<slug> --slug <slug> --style output/<slug>/style.json \
  --eval output/<slug>/eval.json
```

`blocks_build.py` calls `scripts/stadium_detail.py` automatically. Keep individual
seat modules bounded with `seat_spacing` and `max_seat_modules`; reduce that LOD
only when scene scale or hardware requires it.

### 4. Evaluate and refine

Require relevant stadium gates in `eval.json`:

```json
{
  "gates": {
    "min_stadium_stand_rows": 40,
    "min_stadium_seat_modules": 3000,
    "min_stadium_aisle_steps": 180,
    "min_stadium_vomitories": 4,
    "min_stadium_goals": 2,
    "required_stadium_sides": ["north", "south", "east", "west"]
  }
}
```

Evaluate in this order: pitch orientation/dimensions, stand footprint and height,
cardinal layout, seating/aisles, roof silhouette, rear openness, access details,
club colors/identity, then materials and lighting. Freeze a different-azimuth
holdout view before tuning.

## Live Blender

When Blender MCP is active, use `blender-mcp-loop` for backup, execution,
checkpoints, screenshots, and best-result restoration. Rebuild through
`stadium_detail` instead of pasting run-specific Blender code into the core.
Never reset factory settings or replace the stadium with provider photogrammetry.

## Completion

Deliver the editable `.blend`, oblique/aerial/holdout renders,
`build_report.json`, and `eval_report.json`. Require all declared gates to pass
and visually inspect both tuning and holdout views. Report inferred seat rows,
roofs, supports, and microdetail honestly.

Read [references/STADIUM_CONTRACT.md](references/STADIUM_CONTRACT.md) before
changing detection, layout, style keys, or stadium acceptance gates.
