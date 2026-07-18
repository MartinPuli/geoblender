"""Tag/statistics-driven architectural profiles (pure module, no bpy).

Infer scene defaults from actual OSM building statistics instead of global city
rules. Profiles fill missing height, roof, and material hints without naming a
specific location.
"""

PROFILES = (
    "modern_towers",
    "historic_center",
    "industrial",
    "informal_dense",
    "residential_lowrise",
    "mixed",
)

# Profile defaults for missing data. roof_bias applies only without roof:shape.
PROFILE_DEFAULTS = {
    "modern_towers":       {"default_height": 24.0, "roof_bias": "flat",     "wall_hint": "glass"},
    "historic_center":     {"default_height": 9.0,  "roof_bias": "gabled",   "wall_hint": "masonry"},
    "industrial":          {"default_height": 8.0,  "roof_bias": "skillion", "wall_hint": "concrete"},
    "informal_dense":      {"default_height": 4.5,  "roof_bias": "flat",     "wall_hint": "brick"},
    "residential_lowrise": {"default_height": 7.0,  "roof_bias": "hipped",   "wall_hint": "masonry"},
    "mixed":               {"default_height": 9.0,  "roof_bias": None,       "wall_hint": None},
}

_PITCHED = {"gabled", "hipped", "half-hipped", "gambrel", "mansard", "pyramidal", "saltbox"}
_INDUSTRIAL = {"industrial", "warehouse", "factory", "hangar", "manufacture"}


def _stats(buildings):
    n = len(buildings)
    heights = sorted(float(b.get("height", 0.0) or 0.0) for b in buildings)
    med = heights[n // 2] if n else 0.0
    tall = sum(1 for h in heights if h >= 28.0) / n if n else 0.0
    low = sum(1 for h in heights if h <= 8.0) / n if n else 0.0
    roofs = [str(b.get("roof_shape") or "").lower() for b in buildings]
    pitched = sum(1 for r in roofs if r in _PITCHED) / n if n else 0.0
    types = [str(b.get("type") or "").lower() for b in buildings]
    industrial = sum(1 for t in types if t in _INDUSTRIAL) / n if n else 0.0
    return {"n": n, "median_h": med, "tall_frac": tall, "low_frac": low,
            "pitched_frac": pitched, "industrial_frac": industrial}


def classify_profile(buildings):
    """Classify one PROFILES value from the height/roof/type distribution."""
    s = _stats(buildings)
    if s["n"] == 0:
        return "mixed"
    # Many towers imply a modern district even when low podiums lower the median.
    if s["tall_frac"] >= 0.20 or (s["tall_frac"] >= 0.12 and s["median_h"] >= 20.0):
        return "modern_towers"
    if s["pitched_frac"] >= 0.35 and s["median_h"] <= 14.0:
        return "historic_center"
    if s["industrial_frac"] >= 0.25:
        return "industrial"
    if s["low_frac"] >= 0.70 and s["pitched_frac"] < 0.10:
        return "informal_dense"
    if s["low_frac"] >= 0.50:
        return "residential_lowrise"
    return "mixed"


def profile_defaults(profile):
    """Return a copy of profile defaults."""
    return dict(PROFILE_DEFAULTS.get(profile, PROFILE_DEFAULTS["mixed"]))


def classify(buildings):
    """Return ``(profile, defaults)`` for scene.json."""
    p = classify_profile(buildings)
    return p, profile_defaults(p)
