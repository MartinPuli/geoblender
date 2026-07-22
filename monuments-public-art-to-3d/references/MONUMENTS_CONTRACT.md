# Monuments and public-art contract

## Normalized classes

| OSM semantics | Kind | Procedural fallback |
|---|---|---|
| `historic=memorial` + `memorial=statue` | `statue` | Plinth plus symbolic figure |
| `memorial=bust` or `artwork_type=bust` | `bust` | Pedestal, torso and head |
| `memorial=stele` | `stele` | Inscription slab on base |
| `memorial=plaque/blue_plaque` | `plaque` | Thin host-mounted plate |
| `memorial=stone` | `memorial_stone` | Low irregular stone proxy |
| `memorial=obelisk` / `man_made=obelisk` | `obelisk` | Tapered shaft and pyramid cap |
| `historic=monument` | `monument` | Base plus vertical civic massing |
| `tourism=artwork` + `artwork_type=sculpture` | `sculpture` | Abstract crossed/curved massing |
| `artwork_type=installation` | `installation` | Multi-part bounded composition |
| `artwork_type=mural/painting/graffiti` | `mural` | Thin host-mounted color panel |
| `amenity=fountain` or mapped fountain | `fountain` | Basin, jet core and water surface |

## Source precedence

Use explicit geometry/dimensions/materials, verified run references, licensed
assets, then semantic procedural fallback. Names, artist identity and Wikipedia
links may guide reference lookup but never select hard-coded geometry in core.

## Acceptance evidence

Report objects by kind, explicit versus inferred dimensions, bases, artwork
parts, water parts, inscriptions, resolved/unresolved hosts and external assets
with licenses. Held-out silhouette must match the semantic class even when exact
identity is unavailable.
