"""Optional registry for external landmark packs (pure module, no bpy).

The core contains no city names or literal coordinates. Normal landmarks come
from OSM tags; this API exists only for explicit private or optional packs.
"""
import math

# Deliberately empty: never add concrete locations to the core.
LANDMARKS = []


def haversine_m(lat1, lon1, lat2, lon2):
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(a)))


def landmarks_for_center(lat, lon, landmarks=None):
    """Filter an explicit pack by geofence; return empty without a pack."""
    out = []
    for lm in (LANDMARKS if landmarks is None else landmarks):
        if haversine_m(lat, lon, lm["lat"], lm["lon"]) <= lm["radius_m"]:
            out.append(lm)
    return out


def name_matches(lm, osm_name):
    """Return whether an OSM name matches, or no name constraint exists."""
    wanted = [w.lower() for w in lm.get("match_names", [])]
    if not wanted:
        return True
    return bool(osm_name) and osm_name.strip().lower() in wanted
