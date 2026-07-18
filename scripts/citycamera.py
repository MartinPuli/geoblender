"""Collision-safe street camera placement (pure module, no bpy).

If the requested camera point falls inside a building footprint, move it to the
nearest sampled road point outside every building. Testable without Blender or
Overpass.
"""
import math


def point_in_poly(poly, px, py):
    inside = False
    n = len(poly)
    j = n - 1
    for i in range(n):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if ((yi > py) != (yj > py)) and \
           (px < (xj - xi) * (py - yi) / ((yj - yi) or 1e-9) + xi):
            inside = not inside
        j = i
    return inside


def inside_any_building(buildings, x, y):
    for b in buildings:
        fp = b.get("footprint")
        if fp and len(fp) >= 3 and point_in_poly(fp, x, y):
            return True
    return False


def _road_points(roads, step=6.0):
    pts = []
    for r in roads:
        if float(r.get("z", 0) or 0) > 1.0:
            continue  # ignore elevated bridges
        path = r.get("path", [])
        for i in range(len(path) - 1):
            x1, y1 = path[i]
            x2, y2 = path[i + 1]
            dx, dy = x2 - x1, y2 - y1
            L = math.hypot(dx, dy)
            if L < 1e-6:
                continue
            n = max(1, int(L / step))
            for k in range(n + 1):
                t = k / n
                pts.append((x1 + dx * t, y1 + dy * t))
    return pts


def safe_street_point(scene, x=0.0, y=0.0):
    """Return a road point outside all buildings and whether it moved."""
    buildings = scene.get("buildings", [])
    roads = scene.get("roads", [])
    if not inside_any_building(buildings, x, y):
        return (x, y), False
    best, bestd = None, 1e30
    for (px, py) in _road_points(roads):
        if inside_any_building(buildings, px, py):
            continue
        d = (px - x) ** 2 + (py - y) ** 2
        if d < bestd:
            bestd, best = d, (px, py)
    return (best or (x, y)), (best is not None)
