# Urban-detail system

The urban layer is a tag-driven extension of the normalized `scene.json`
contract. `scripts/urban_detail.py` classifies physical features without using
place names; `scripts/place_to_3d.py` preserves explicit dimensions, direction,
text and component tags; `scripts/blocks_build.py` produces editable geometry.

## Implemented coverage

| Family | OSM evidence | Editable output |
|---|---|---|
| Residential zones | `landuse=residential`, optional `residential=*` | Separate zone mesh and metrics; never treated as a parcel or individual building |
| Residential fabric | mapped residential building types, gardens, roads and driveways | Building grammar, facade detail, roofs, entrances and bounded interior scaffolds |
| Boundaries | mapped `barrier=fence/wall/hedge` ways | Separate fence rails/posts, walls or hedge volumes |
| Traffic and wayfinding | physical `traffic_sign=*` nodes, street names, `tourism=information`, `information=guidepost/map` | Direction-aware supports, semantic regulatory shapes, panels/blades and explicit editable text; way-level regulations do not invent signs |
| Pedestrian crossings | `highway=crossing`, `crossing:markings=*`, `tactile_paving=*`, nearest mapped road | Hosted zebra paint and explicit tactile pads; unmarked crossings remain unpainted |
| Lane arrows | `turn:lanes=*`, `turn:lanes:forward/backward=*`, road direction and lanes | Generic editable arrows preserving lane order and combined movements; ambiguous generic two-way values are reported |
| Explicit road markings | separate `road_marking=stop_line/lane_divider` nodes or ways, optional `stroke`, `width`, `colour`, `direction` | Hosted or mapped-axis paint above the road surface; solid/dashed patterns remain editable and avoid coplanar z-fighting |
| On-road cycle lanes | `cycleway=lane` or side-specific lane tags, optional width/buffer/separation | Side-aware editable surface strips, dividers and explicit bollard/kerb protection; tracks/separate ways are never duplicated from the motor-road axis |
| Bus lanes | positional `bus:lanes*`/`psv:lanes*`; count-only `lanes:bus/psv` retained separately | Direction-aware editable strips only where a designated lane position is explicit; ambiguous and count-only profiles remain metadata-only |
| Street parking | modern `parking:left/right/both=*`, orientation and width | Side/position-aware parking surface and separator proxies without invented cars, occupancy or duplicated `separate` facilities |
| Sidewalks | `sidewalk=both/left/right/yes`, side-specific width/surface/kerb; `separate` retained distinctly | Integrated editable strips placed beyond explicit parking; separately mapped sidewalks are never duplicated from the road axis |
| Accessible kerbs and tables | `kerb=flush/lowered`, `kerb:height`, tactile/wheelchair tags, `traffic_calming=table`, optional crossing semantics | True sloped curb ramps and speed/raised-crossing tables with bounded heights, open refuge paths and optional tactile pads |
| Kerbs and islands | `barrier=kerb`, `kerb=*`, `area:highway=traffic_island`, `traffic_calming=island/painted_island`, `crossing:island=*` | Line kerbs, authoritative outlined islands, bounded point proxies, flat painted islands and pedestrian refuge gaps |
| Advertising | `advertising=*`, `size`, `support`, `sides`, `lit`, `luminous` | Boards, billboards, columns, screens, totems and flags |
| Transit stops | bus-stop/platform nodes plus `shelter`, `bench`, `bin`, `passenger_information_display` | Pole/route panel and only the explicitly declared stop components |
| Memorials and public art | `historic=memorial/monument`, `memorial=*`, `tourism=artwork`, `artwork_type=*` | Statues, busts, steles, plaques, stones, obelisks, monuments, sculpture, installations, murals and fountains; wall art snaps to the nearest mapped facade within a bounded distance |
| Street amenities | mapped amenities/emergency/man-made/power/barrier tags | Benches, bins, water points, bicycle racks, shelters, bollards, gates, hydrants, post boxes, clocks, cabinets, poles, parking meters, EV chargers, vending machines, parcel lockers, ATMs, defibrillators, picnic tables and recycling |
| Recreation | individual `playground=*` equipment | Swings, slides, seesaws, climbing frames, roundabouts and sandboxes |
| Vegetation points/rows | explicit `natural=tree` nodes and `natural=tree_row` ways | Low-poly mapped trees and deterministic row instances along the mapped trunk axis |
| Vegetation cover | `natural=wood/scrub/shrubbery`, `landuse=forest/orchard` areas | Bounded deterministic tree/shrub instances in a separate collection; generic parks and residential areas do not invent trees |
| Overhead utilities | `power=line/minor_line` ways, `power=pole/tower` nodes, optional `cables/wires/voltage/height` | Separate conductor proxies and explicit supports; underground cables and unrelated amenities are never connected overhead |
| Power facilities | `power=substation` areas/nodes, `power=transformer`, power utility cabinets, optional `substation/location/voltage` | Mapped facility slab/perimeter, bounded reported equipment proxies, transformer or kiosk objects; devices and facility boundaries remain semantically distinct |
| Telecom infrastructure | `man_made=utility_pole + utility=telecom`, telecom street cabinets/distribution points, `communication=line + location=*` | Editable poles/cabinets and overhead conductors only for explicit `location=overhead`; underground, underwater and unspecified axes remain metadata-only |
| Fluid networks | `man_made=pipeline`, explicit `location`, diameter/substance, `pipeline=valve/measurement`, `man_made=pumping_station` | Visible overground/overhead pipeline axes, bounded overhead support proxies and distinctive equipment; buried/underwater/unspecified axes remain metadata-only |
| Drainage and fluid access | `man_made=manhole`, `manhole=drain`, `inlet=grate/kerb_grate`, fluid `utility=*` street cabinets | Flush editable covers/grates and distinct above-ground cabinets; no invented underground chamber or connection geometry |

## Evidence and honesty rules

- Explicit `height`, `width`, `depth`, advertising `size` and `direction` outrank
  semantic defaults and retain provenance in the build report.
- Names never select geometry. Text is used only when it is itself physical
  mapped content, such as a sign, route reference or plaque inscription.
- A residential land-use polygon is an area classification, not cadastral
  evidence. Synthetic parcel subdivision and building infill remain opt-in.
- Generic public-art geometry communicates type and scale. It does not claim to
  reproduce a particular person's likeness or an artwork's exact shape.
- Exact national traffic-sign glyph libraries, trademarks and custom sculpture
  assets remain external asset packs rather than hidden generic assumptions.

## Validation contract

Urban runs can gate object and part counts, required families/kinds, explicit
directions/dimensions, residential zone area/building/boundary counts and all
render files. `style.detail_views` adds repeatable close cameras for small
objects without weakening the standard aerial, oblique and holdout checks.
Streetscape runs additionally gate lane arrows, kerb segments, islands, tree
rows, stop lines, lane dividers, cycle-lane length/separation/protection, power
facilities, bus-lane and parking length/coverage, telecom devices/lines,
visible and metadata-only fluid axes, pipeline supports/equipment,
metadata-only subsurface axes, utility conductors, vegetation-cover zones,
instances and kinds. Accessibility gates additionally cap curb-ramp and raised
crossing heights while checking sidewalk length, separate-way metadata,
physical kerb edges, ramps and tables.

The synthetic fixture in `tests/fixtures/urban_system_scene.json` exercises all
major families in a live Blender scene. Its acceptance target is stored in
`tests/fixtures/urban_system_eval.json`.

## Source taxonomy

The semantic vocabulary follows the OpenStreetMap Wiki pages for
[`landuse=residential`](https://wiki.openstreetmap.org/wiki/Tag%3Alanduse%3Dresidential),
[`traffic_sign`](https://wiki.openstreetmap.org/wiki/Key%3Atraffic_sign),
[`advertising`](https://wiki.openstreetmap.org/wiki/Key%3Aadvertising),
[`memorial`](https://wiki.openstreetmap.org/wiki/Key%3Amemorial),
[`artwork_type`](https://wiki.openstreetmap.org/wiki/Key%3Aartwork_type),
[`amenity=bus_stop`](https://wiki.openstreetmap.org/wiki/Tag%3Aamenity%3Dbus_stop)
and [playground equipment](https://wiki.openstreetmap.org/wiki/Playground_equipment),
plus [`turn:lanes`](https://wiki.openstreetmap.org/wiki/Key%3Aturn%3Alanes),
[`barrier=kerb`](https://wiki.openstreetmap.org/wiki/Key%3Akerb),
[`area:highway=traffic_island`](https://wiki.openstreetmap.org/wiki/Tag%3Aarea%3Ahighway%3Dtraffic_island),
[`natural=tree_row`](https://wiki.openstreetmap.org/wiki/Tag%3Anatural%3Dtree_row),
[`natural=wood`](https://wiki.openstreetmap.org/wiki/Tag%3Anatural%3Dwood) and
[`power=line`](https://wiki.openstreetmap.org/wiki/Tag%3Apower%3Dline).
The technical-network extension also follows
[`road_marking`](https://wiki.openstreetmap.org/wiki/Road_marking),
[`cycleway`](https://wiki.openstreetmap.org/wiki/Key%3Acycleway),
[`cycleway:buffer`](https://wiki.openstreetmap.org/wiki/Key%3Acycleway%3Abuffer),
[`power=substation`](https://wiki.openstreetmap.org/wiki/Tag%3Apower%3Dsubstation),
[`power=transformer`](https://wiki.openstreetmap.org/wiki/Tag%3Apower%3Dtransformer),
[`man_made=utility_pole`](https://wiki.openstreetmap.org/wiki/Tag%3Aman_made%3Dutility_pole),
[`utility=telecom`](https://wiki.openstreetmap.org/wiki/Tag%3Autility%3Dtelecom),
[`communication=line`](https://wiki.openstreetmap.org/wiki/Tag%3Acommunication%3Dline)
and the [telecommunication mapping guide](https://wiki.openstreetmap.org/wiki/Telecommunication),
plus [bus lanes](https://wiki.openstreetmap.org/wiki/Bus_lanes),
[street parking](https://wiki.openstreetmap.org/wiki/Street_parking) and
[pipelines](https://wiki.openstreetmap.org/wiki/Pipeline),
[`inlet`](https://wiki.openstreetmap.org/wiki/Key%3Ainlet),
[`manhole=drain`](https://wiki.openstreetmap.org/wiki/Tag%3Amanhole%3Ddrain) and
[`man_made=street_cabinet`](https://wiki.openstreetmap.org/wiki/Tag%3Aman_made%3Dstreet_cabinet).
Accessibility semantics follow [Sidewalks](https://wiki.openstreetmap.org/wiki/Sidewalks),
[`kerb`](https://wiki.openstreetmap.org/wiki/Key%3Akerb),
[`footway=crossing`](https://wiki.openstreetmap.org/wiki/Tag%3Afootway%3Dcrossing)
and [`traffic_calming=table`](https://wiki.openstreetmap.org/wiki/Tag%3Atraffic_calming%3Dtable).
Vertical pedestrian access additionally follows [Stairs](https://wiki.openstreetmap.org/wiki/Stairs),
[Elevator](https://wiki.openstreetmap.org/wiki/Elevator),
[Ramp](https://wiki.openstreetmap.org/wiki/Ramp),
[Incline](https://wiki.openstreetmap.org/wiki/Incline) and
[conveying](https://wiki.openstreetmap.org/wiki/Key%3Aconveying): steps, ramps,
escalators, moving walkways and lifts stay editable, retain provenance and
avoid duplicate generic footway meshes.

## Next high-value extensions

1. Licensed regulatory pictogram/glyph packs keyed by country and sign code.
2. Referenced surface assets for specific murals without inventing artwork.
3. Jurisdiction-aware surface-colour packs and licensed lane pictograms where
   stable run configuration exists.
4. Separately mapped substation switchgear, circuits and pole-mounted
   transformer attachment graphs without inferred topology.
5. Species-aware crown libraries and seasonal variants from explicit tags or
   licensed per-run asset packs.
