# Signage and wayfinding contract

## Normalized classes

| OSM semantics | Normalized kind | Default physical grammar |
|---|---|---|
| `traffic_sign=*` | `traffic_sign` | Pole plus framed plate |
| `traffic_sign=street_name` | `street_name_sign` | Narrow bilateral blade |
| `tourism=information` + `information=guidepost` | `guidepost` | Pole with directional blades |
| `information=board/map` | `information_board` / `map_board` | Pedestrian panel or lectern |
| `highway=bus_stop` or bus platform node | `bus_stop` | Pole, flag and timetable panel |
| `advertising=billboard` | `billboard` | Large panel on one/two supports |
| `advertising=board/poster_box/screen` | Corresponding kind | Framed pedestrian/display panel |
| `advertising=column` | `advertising_column` | Cylindrical display volume |
| `advertising=totem/sign` | `advertising_totem` | Grounded vertical pylon |
| `advertising=flag` or mapped flagpole | `flag` | Pole plus flexible planar flag proxy |

## Regulatory shape grammar

| Human-readable physical value | Generic shape | Generic face |
|---|---|---|
| `stop` | Octagon | Red with explicit STOP text |
| `give_way` | Inverted triangle | Red border and light interior |
| `maxspeed`, `maxheight`, `maxweight`, `maxwidth` | Circle | Red restriction border, light interior and explicit value |
| `no_entry` | Circle | Red face and light horizontal bar |
| `hazard`, `*_ahead` | Warning triangle; yellow diamond for known diamond-sign countries | No invented pictogram |
| mandatory/direction | Circle | Blue proxy; exact arrow requires mapped code/asset |
| unknown national code | Rectangle | Neutral proxy; preserve country/code in report |

Treat semicolon-separated codes as a sign stack and preserve the count even if
the current LOD builds only the primary plate. Never infer a physical support
from a way-level regulation.

## Crossings

Normalize `highway=crossing`, `crossing:markings=*`,
`crossing:markings:colour=*`, `tactile_paving=*` and `kerb=*` independently.
Resolve the nearest mapped road axis/width. Build paint only when markings are
not `no`; build tactile pads only when explicitly tagged.

## Dimensions and content

Parse `size=length*height` in meters when valid. Total `height=*` includes the
support; `width=*` is thickness for some advertising schemas, so keep normalized
`panel_width`, `panel_height` and `depth` separate. Preserve `sides`, `lit`,
`luminous`, `support`, `direction`, `name`, `ref`, `destination` and `message`.

## Acceptance evidence

Report counts by kind/family and sign shape, panels, supports, explicit
bearings, explicit dimension usage, hosted crossings, lit devices, text objects
and unresolved wall/road hosts. Exact national/brand artwork is outside generic
acceptance unless an asset pack is explicitly part of the run.
