# Contributing

Thanks for your interest in improving maps-to-3d. This project turns a place (via
OpenStreetMap) into a procedural 3D city scene in Blender. Below is everything you need to
get set up, run the tests, and extend the three main content systems.

## Setup

You only need Python 3.9+ and `requests`. Two ways to install:

```bash
# Option A: editable install of the package
python3 -m pip install -e .

# Option B: just the one runtime dependency
python3 -m pip install requests
```

Blender is only required to *render* a scene. The "pure" modules (see conventions below)
are importable and testable without Blender or a network connection.

## Running the tests

```bash
python3 -m pytest tests/ -q
```

Each test file adds `scripts/` to `sys.path`, so the `city*` modules import as top-level
packages. New pure logic should ship with a matching test under `tests/`.

## Conventions

- **1 Blender unit = 1 meter.** All geometry is authored in meters.
- **Pure modules are named `city*.py`** and live in `scripts/` (flat layout). A "pure"
  module **must not `import bpy` at the top level** — it should be unit-testable without
  Blender or Overpass. If a function needs `bpy`, import it *inside* the function, or keep
  the `bpy`-touching code in `blender_build.py`.
- **Python 3.9 compatible.** Avoid syntax/stdlib newer than 3.9.
- Spanish comments are fine.
- Keep the open-source procedural pipeline (OSM + PolyHaven) separate from the opt-in
  Google 3D Tiles pipeline — see `docs/SOURCES_LICENSES.md`.

## How-tos

### Add a landmark

1. Open `scripts/citylandmarks.py` and add an entry to the `LANDMARKS` table (name,
   coordinates/match rule, and shape/size parameters).
2. The pure module decides *which* landmarks apply and *what* their parameters are; the
   `bpy`-side builder in `blender_build.py` turns those parameters into mesh.
3. Add a test in `tests/` that asserts your new entry resolves with the expected
   parameters.

### Add a roof shape

1. Add the shape's descriptor/logic to `scripts/cityroofs.py` (this is the pure part:
   given footprint + tags, decide roof type and its parameters).
2. Add a matching **builder in `blender_build.py`** that consumes those parameters and
   generates the roof geometry with `bpy`.
3. Cover the pure decision logic with a test under `tests/`.

### Add an architectural profile

1. Add the profile to `scripts/cityprofiles.py` — a profile bundles the style parameters
   (heights, materials, roof tendencies, facade rules) for a class of buildings.
2. Wire it in where profiles are selected, and let `blender_build.py` read the profile
   parameters during the build.
3. Add a test under `tests/` for the new profile's resolved parameters.

## Before you open a PR

- Run `python3 -m pytest tests/ -q` and make sure it is green.
- Keep pure modules free of top-level `bpy` imports.
- If you added an external data source, document it in `docs/SOURCES_LICENSES.md`.
