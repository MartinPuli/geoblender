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

## The gates are blind

A green `eval_report.json` does not mean the stadium looks like the stadium. The
gates count objects, seat modules, steps and overlaps; not one of them compares
two parts of the build against each other.

At Racing's Cilindro every declared gate passed while the canopy floated 15.3 m
above the last row, the sign read mirrored, the turf was buried under an OSM
landuse polygon, the light banks hung in mid-air, the bowl was an oval where the
real ground is a circle, and four stair-core boxes stood 4 m inside the seating.
Counting gates were satisfied by all of it.

So: pass the gates, then run the fidelity checklist below against a render.

## Fidelity checklist

Each item is a defect the current gates cannot see. Measure and print the number;
do not eyeball it.

1. **Plan shape.** Decide first whether the real ground is circular, oval,
   rectangular, or four separate stands. `bowl_shape: continuous_oval` derives
   both semi-axes from the pitch (`length/2 + runoff + depth` and
   `width/2 + runoff + depth`), so it can only produce an oval with the pitch's
   own eccentricity. A circular ground needs the outer radius as an independent
   value, with the stand *depth* absorbing the difference: shallow at the
   corners, deep behind the touchlines. Audit by printing the ratio of the two
   envelope half-extents — 1.000 is a true circle.
2. **Inner profile is not the outer profile.** The inner lip is cut from the same
   superellipse as the outer envelope, so the terrace has constant depth all the
   way round. Real bowls are typically a polygon (often an octagon with chamfered
   corners) inside a smooth shell. Print the depth behind the goal, on the
   chamfer, and at the touchline; three equal numbers mean the profile is wrong.
   Sample the chamfer at its true midpoint, not at 45 deg — the straight
   touchline run reaches further round than that.
3. **Roof height above the last row.** `roof_z` is derived from `stand_height_*`
   (the structural envelope) instead of `bowl_height_*` (the seating rake). The
   leading edge belongs roughly 4-10 m above the back of the top tier. Target
   `top_of_last_seat_row + clearance` as an absolute height, then re-anchor
   everything mounted on the roof — light banks, fascias, visor soffits — to the
   corrected underside instead of leaving them at their own heights.
4. **Standing sectors vs seated sectors.** Published capacity minus published
   numbered seats is the standing terrace (at the Cilindro, ~55,880 against
   41,400). Those sectors are painted concrete steps with no seat modules,
   usually the lower tiers behind the goals while the upper tier is seated. A
   bowl where every square metre carries butacas reads wrong.
5. **Club color banding.** `seat_pattern: "solid"` leaves the bowl monochrome.
   Alternating vertical bands in the club's colors are the visual identity of a
   ground: use `alternating_sections` and set both `primary_color` and
   `secondary_color`. Remember AgX desaturates — push the style values well past
   the nominal club hex.
6. **Z order of the ground layers.** OSM area polygons, turf, mow bands and pitch
   markings are near-coplanar. Turf must sit above the OSM area layer (around
   z = 0.06) and markings above the turf, or the pitch vanishes under a landuse
   polygon. Size the turf to the inner face of the stands, not to the markings,
   or a pale band shows through the entire run-off.
7. **Nothing hangs, nothing intrudes.** Floodlights, screens and scoreboards are
   positioned relative to their support, never at an absolute height that a later
   change invalidates. Every added volume — stair cores, broadcast platforms,
   towers — must start outside the outer envelope radius; a box that starts
   inside shows through the seating as a grey blotch.
8. **Signage reads correctly.** A text object at rot X = -90 deg renders mirrored
   from outside. Judge the glyphs in a render, not the object's transform.
9. **Cameras clear the structure.** After any roof or rake change, re-check every
   frozen camera: one inside the canopy renders pure black.

Known generator trap: `Stadium_Vomitories` does not contain only vomitories. The
`tier_break` branch emits the tier-break overlay plates into the same bmesh, so
the object holds hundreds of flat 0.04 m plates wrapping most of the ring
alongside the real portals. Any consumer that takes the object's global min/max
z or the union of its vertex angles will mask ~295 deg of the bowl. Split it into
connected islands and discard the ones too flat to be a portal.

## Per-run polish

Fixing the checklist items belongs in a per-run polish script applied to the
saved `.blend`, not in `scripts/stadium_detail.py`. Read the "Per-run polish
pass" and "Iteration craft" sections of the root `SKILL.md` for the rules
(numbered sections, an absolute target per section, idempotency, working in the
pitch's `(u, v)` frame rather than world axes).

Worked example, ~23 sections against one stadium:
`/Users/martinezequielpulitano/martinpulitano/render/output/racing-cilindro-one-shot/stadium_polish.py`.

Reference evidence for the checklist: the Wikipedia infobox gives capacity, seat
count and year through the MediaWiki API over `curl`; Wikimedia Commons gives
licensed photographs of the real roof line and seat banding; Esri World Imagery
at ~0.24 m/px is good enough to measure the outer diameter and the pitch axis by
color segmentation. Google Images does not load in the sandbox. Store everything
measured in `style.json` with its source.

## Live Blender

When Blender MCP is active, use `blender-mcp-loop` for backup, execution,
checkpoints, screenshots, and best-result restoration. Rebuild through
`stadium_detail` instead of pasting run-specific Blender code into the core.
Never reset factory settings or replace the stadium with provider photogrammetry.

## Completion

Deliver the editable `.blend`, oblique/aerial/holdout renders,
`build_report.json`, and `eval_report.json`. Require all declared gates to pass,
walk the fidelity checklist with its measured numbers, and visually inspect both
tuning and holdout views. Report inferred seat rows, roofs, supports, and
microdetail honestly, and report the per-run polish pass as a run-specific
correction rather than as generator output.

Read [references/STADIUM_CONTRACT.md](references/STADIUM_CONTRACT.md) before
changing detection, layout, style keys, or stadium acceptance gates.
