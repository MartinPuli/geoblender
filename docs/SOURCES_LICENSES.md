# External Sources & Licenses

This project builds 3D city scenes from public data. Below is every external source it
touches, the license/terms that apply, and exactly what we store versus what we do not.

## Summary table

| Source | What we use it for | License / Terms | Attribution | Can we store / redistribute it? |
| --- | --- | --- | --- | --- |
| **[ahujasid/blender-mcp](https://github.com/ahujasid/blender-mcp)** by Siddharth Ahuja | Upstream Blender addon, MCP server, transport, and native Blender tools used by the live loop | **MIT License** | Credit the upstream project and retain its copyright/license notice when redistributing substantial portions | Yes, under MIT. The upstream addon/server is not vendored in this repository. |
| **OpenStreetMap** (via the [Overpass API](https://overpass-api.de/)) | Building footprints, roads, water, landuse, POIs that drive the procedural geometry | **ODbL 1.0** (Open Database License) | **"© OpenStreetMap contributors"** required on any derived output | Yes — derived geometry is a Produced Work; keep the ODbL attribution. Public Overpass servers are rate-limited, so cache responses politely. |
| **PolyHaven** textures & HDRIs | Ground/road PBR textures and sky/environment HDRIs used by the material and lighting pass | **CC0 1.0** (public domain dedication) | None required (a courtesy credit is appreciated) | Yes — CC0 assets may be stored, modified, and redistributed freely. |
| **Google Photorealistic 3D Tiles** ([Map Tiles API](https://developers.google.com/maps/documentation/tile/3d-tiles)) | Optional "exact-geometry" pipeline: real textured buildings/bridges | **PROPRIETARY** — Google Maps Platform Terms of Service | **Dynamic on-screen attribution required** while rendering | **No.** Render-only. Must NOT be stored, cached offline, redistributed, or exported. Kept as a separate, opt-in pipeline. |

## What we store vs. what we do NOT store

- **We store:** OpenStreetMap-derived procedural geometry (with "© OpenStreetMap contributors" attribution) and CC0 PolyHaven textures/HDRIs.
- **We do NOT store:** any Google Photorealistic 3D Tiles data — it is render-only, never written to disk, never exported, never cached offline.

## Details

### Blender MCP — MIT

- The live Blender integration depends on
  [ahujasid/blender-mcp](https://github.com/ahujasid/blender-mcp), created by
  Siddharth Ahuja.
- Upstream provides the Blender addon, MCP server, connection protocol, and native
  MCP tools. This repository provides the geographic pipeline and the
  `blender-mcp-loop` orchestration/evaluation skill that runs on top of it.
- The upstream addon/server is not copied into this repository. If downstream
  distribution includes substantial upstream code, retain its MIT copyright and
  permission notice.
- Upstream license: https://github.com/ahujasid/blender-mcp/blob/main/LICENSE

### OpenStreetMap (Overpass API) — ODbL 1.0
- OpenStreetMap data is licensed under the **Open Database License (ODbL) 1.0**.
- Any map, model, or render derived from OSM is a "Produced Work" and must carry the
  credit **"© OpenStreetMap contributors"**.
- We fetch data from **public Overpass API** endpoints, which are **rate-limited** and
  run on donated infrastructure. Query sparingly, respect `Retry-After`, and cache
  results locally rather than re-querying the same bounding box repeatedly.
- License text: https://opendatacommons.org/licenses/odbl/1-0/
- Attribution guidance: https://www.openstreetmap.org/copyright

### PolyHaven textures & HDRIs — CC0 1.0
- All PolyHaven assets are released under **CC0 1.0** (public domain dedication).
- This means we may use, modify, and redistribute them for any purpose, including
  commercial, with **no attribution required**. A credit is a nice courtesy.
- License: https://creativecommons.org/publicdomain/zero/1.0/
- Source: https://polyhaven.com/license

### Google Photorealistic 3D Tiles (Map Tiles API) — PROPRIETARY
- These tiles are served under the **Google Maps Platform Terms of Service** and are
  **proprietary** — they are NOT open data.
- **Render-only.** The tiles must **NOT** be stored, cached offline, redistributed,
  exported, or converted into a persistent asset.
- **Dynamic on-screen attribution is required**: the Google attribution string that
  accompanies the tiles must be displayed while the tiles are on screen.
- Because these terms are incompatible with an open-source, redistributable output, this
  pipeline is kept **strictly separate and opt-in**. It is **never mixed into the
  open-source procedural (OpenStreetMap + PolyHaven) output**.
- Terms: https://cloud.google.com/maps-platform/terms
- Tiles API: https://developers.google.com/maps/documentation/tile/3d-tiles

## Rule of thumb

Anything produced by the default **procedural pipeline** (OSM + PolyHaven) is safe to
store and share, provided the "© OpenStreetMap contributors" attribution is kept.
Anything from the **Google 3D Tiles** pipeline is display-only and must never end up in a
saved, exported, or redistributed artifact.
