"""
osm2world_adapter.py — optional adapter for the external OSM2World engine
(a pure module that can be imported without Java or bpy).

OSM2World evaluation as an alternative engine
---------------------------------------------
OSM2World (https://osm2world.org/) is a mature OpenStreetMap-to-3D converter.
It was evaluated as an alternative to this project's procedural generator.

Advantages:
  - Ready-to-use OSM-to-3D conversion of buildings, roofs, materials, roads,
    water, and vegetation.
  - Mature project with support for standard formats such as OBJ and glTF.
  - Broad OSM tag coverage beyond narrow custom rules.

Tradeoffs:
  - JVM dependency: Java and a separately downloaded .jar are required.
  - Less native Blender control because the output is a baked mesh.
  - A separate material pipeline that does not directly integrate with this
    project's profiles, CC0 textures, or procedural windows.

Decision:
  OSM2World remains opt-in. It is enabled only when OSM2WORLD_JAR (or ``jar=``)
  and Java are available. The procedural generator remains the default, and
  callers must fall back to it when OSM2World is unavailable.

Typical caller usage (for example, live_build/place_to_3d):
    import osm2world_adapter as o2w
    if o2w.osm2world_available():
        obj = o2w.run_osm2world("zona.osm", "zona.obj")   # importar OBJ luego
    else:
        ...  # fallback: generador procedural (default)
"""
import os
import shutil
import subprocess


class OSM2WorldUnavailable(RuntimeError):
    """OSM2World is unavailable because its .jar or Java binary is missing.

    Callers should catch this exception and use the default procedural engine.
    """


def _resolve_jar(jar=None):
    """Resolve the .jar from an explicit argument or OSM2WORLD_JAR."""
    return jar or os.environ.get("OSM2WORLD_JAR")


def _resolve_java(java=None):
    """Resolve Java from an explicit argument, JAVA_BIN, or the system PATH."""
    if java:
        return java
    return os.environ.get("JAVA_BIN") or shutil.which("java")


def osm2world_available(jar=None, java=None):
    """Return True only when both an existing .jar and Java are available.

    This pure check does not start a subprocess or download anything.
    """
    jar_path = _resolve_jar(jar)
    if not jar_path or not os.path.isfile(jar_path):
        return False
    java_bin = _resolve_java(java)
    return bool(java_bin)


def run_osm2world(osm_input, out_obj, jar=None, java=None, extra_args=None):
    """Convert ``osm_input`` (OSM/PBF) into ``out_obj`` (OBJ) with OSM2World.

    Raise OSM2WorldUnavailable when the optional engine is not configured.
    This function never downloads dependencies. Return ``out_obj`` on success.
    """
    if not osm2world_available(jar=jar, java=java):
        raise OSM2WorldUnavailable(
            "OSM2World is unavailable. Set OSM2WORLD_JAR to the .jar path and "
            "ensure Java is on PATH (or set JAVA_BIN). Use the built-in "
            "procedural generator in the meantime; it is the default engine."
        )
    jar_path = _resolve_jar(jar)
    java_bin = _resolve_java(java)
    cmd = [java_bin, "-jar", jar_path, "--input", osm_input, "--output", out_obj]
    if extra_args:
        cmd.extend(extra_args)
    subprocess.run(cmd, check=True)
    return out_obj
