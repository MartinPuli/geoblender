"""Choose a roof type per building (pure module, no bpy).

Honor OSM ``roof:shape`` first. Without a tag, derive deterministic variety from
height, profile bias, and position seed. Geometry lives in blender_build.py.
"""
import math

# Buildings below this threshold prefer pitched roofs; taller ones prefer flat roofs.
ROOF_SMALL_MAX_H = 11.0

ROOF_KINDS = ("flat", "parapet", "hipped", "gabled", "pyramidal", "dome", "skillion")

# OSM roof:shape values supported by the procedural builder.
_OSM_ROOF = {
    "flat": "flat",
    "gabled": "gabled",
    "gambrel": "gabled",
    "saltbox": "gabled",
    "quadruple_saltbox": "gabled",
    "hipped": "hipped",
    "half-hipped": "hipped",
    "mansard": "hipped",
    "pyramidal": "pyramidal",
    "dome": "dome",
    "onion": "dome",
    "round": "dome",
    "skillion": "skillion",
    "mono_pitch": "skillion",
    "lean_to": "skillion",
}


def _hash01(seed):
    """Return deterministic noise in [0, 1) from a seed."""
    n = math.sin(seed * 127.1 + 311.7) * 43758.5453
    return n - math.floor(n)


_LOW_BIAS = {"hipped", "gabled", "pyramidal", "skillion"}
_HIGH_BIAS = {"flat", "parapet", "skillion"}


def choose_roof_kind(roof_shape, height_m, seed=0.0, small_max=None, bias=None):
    """Return one ROOF_KINDS value.

    OSM tags have highest priority. Otherwise apply a compatible profile bias
    most of the time, then use the seed for deterministic neighborhood variety.
    """
    small_max = ROOF_SMALL_MAX_H if small_max is None else small_max
    if roof_shape:
        rs = str(roof_shape).strip().lower()
        if rs in _OSM_ROOF:
            return _OSM_ROOF[rs]
    h = _hash01(seed)
    if height_m <= small_max:
        if bias in _LOW_BIAS and h < 0.6:
            return bias
        if h < 0.45:
            return "hipped"
        if h < 0.78:
            return "gabled"
        if h < 0.90:
            return "pyramidal"
        return "skillion"
    if bias in _HIGH_BIAS and h < 0.6:
        return bias
    return "parapet" if h < 0.55 else "flat"
