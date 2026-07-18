# OSM2World: optional alternate engine

This project ships its own Blender procedural generator in `scripts/`. It is the
default engine and remains fully supported.

[OSM2World](https://osm2world.org/) is a mature external converter from
OpenStreetMap data to 3D geometry. This repository exposes it only as an opt-in
alternate engine. If it is not installed, the pipeline automatically falls back
to the native procedural generator.

## Why it is optional

Advantages:

- Mature OSM-to-3D conversion.
- Broad tag coverage, including roofs and roads.
- Ready-to-import OBJ output.

Tradeoffs:

- Requires a JVM and a separately downloaded JAR.
- Produces a baked mesh with less native Blender control.
- Uses a separate material pipeline that does not automatically share this
  project's profiles, CC0 textures, or procedural details.

## Installation

1. Download a stable release from [osm2world.org](https://osm2world.org/).
2. Extract `OSM2World.jar` to a location of your choice.
3. Install Java 17 or newer and verify it:

```bash
java -version
```

This repository never downloads OSM2World automatically.

## Configuration

Set `OSM2WORLD_JAR` to the JAR path. Optionally set `JAVA_BIN` when Java is not
available on `PATH`.

```bash
export OSM2WORLD_JAR="/absolute/path/to/OSM2World.jar"
export JAVA_BIN="/usr/bin/java"  # optional
```

The adapter considers OSM2World available only when the JAR exists and a Java
binary can be resolved.

## Use through the adapter

```python
import osm2world_adapter as o2w

if o2w.osm2world_available():
    obj = o2w.run_osm2world("area.osm", "area.obj")
else:
    ...  # use the native procedural generator
```

The adapter executes:

```text
java -jar $OSM2WORLD_JAR --input area.osm --output area.obj [extra_args...]
```

`run_osm2world` uses `subprocess.run(..., check=True)` and returns the resulting
OBJ path. When OSM2World is unavailable it raises `OSM2WorldUnavailable` with a
clear setup message; callers may catch that exception and fall back.

## Blender import

Import the generated OBJ into Blender through the normal OBJ importer, then place
it in the appropriate semantic collection. Preserve OSM attribution in any
derived output and follow OSM2World's own license requirements.

## Design rule

OSM2World is an adapter, never a hidden replacement for the native engine. Tests
must continue to pass without Java or the JAR installed.
