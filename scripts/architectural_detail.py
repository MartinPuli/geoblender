"""Semantic facade grammars for varied, symmetric, readable buildings.

This module is intentionally Blender-free.  It converts normalized building
semantics and footprint metrics into a deterministic architectural profile;
``blocks_build`` turns that profile into editable facade/interior geometry.
Names never select a profile, and every inferred choice is reproducible.
"""

import math
import zlib


DEFAULT_CONFIG = {
    "enabled": "auto",
    "profile_variation": True,
    "symmetry": True,
    "visible_interiors": True,
    "editable_interior_layouts": True,
    "interior_radius": 115.0,
    "interior_depth": 0.16,
    "max_interior_bays_per_building": 180,
    "max_interior_floors": 8,
    "max_partition_modules_per_building": 220,
    "floor_slab_thickness": 0.12,
    "partition_thickness": 0.09,
    "corridor_width": 2.2,
    "lit_ratio": 0.38,
    "mullions": True,
    "balconies": True,
    "max_balconies_per_building": 36,
}


PROFILE_DEFAULTS = {
    "house": {
        "bay": 3.5, "width": 0.58, "height": 0.56, "symmetry": "paired",
        "mullions": 1, "interior_palette": "domestic", "balcony_every": 0,
    },
    "residential": {
        "bay": 3.25, "width": 0.62, "height": 0.60, "symmetry": "paired",
        "mullions": 1, "interior_palette": "domestic", "balcony_every": 2,
    },
    "commercial": {
        "bay": 3.45, "width": 0.80, "height": 0.74, "symmetry": "grid",
        "mullions": 2, "interior_palette": "office", "balcony_every": 0,
    },
    "curtain_wall": {
        "bay": 2.55, "width": 0.90, "height": 0.84, "symmetry": "grid",
        "mullions": 2, "interior_palette": "office", "balcony_every": 0,
    },
    "hotel": {
        "bay": 3.0, "width": 0.64, "height": 0.62, "symmetry": "bilateral",
        "mullions": 1, "interior_palette": "hospitality", "balcony_every": 2,
    },
    "healthcare": {
        "bay": 3.05, "width": 0.72, "height": 0.62, "symmetry": "bilateral",
        "mullions": 2, "interior_palette": "clinical", "balcony_every": 0,
    },
    "education": {
        "bay": 3.8, "width": 0.70, "height": 0.70, "symmetry": "bilateral",
        "mullions": 2, "interior_palette": "classroom", "balcony_every": 0,
    },
    "civic": {
        "bay": 4.35, "width": 0.54, "height": 0.68, "symmetry": "bilateral",
        "mullions": 1, "interior_palette": "civic", "balcony_every": 0,
    },
    "industrial": {
        "bay": 6.2, "width": 0.68, "height": 0.42, "symmetry": "clerestory",
        "mullions": 3, "interior_palette": "industrial", "balcony_every": 0,
    },
    "mixed": {
        "bay": 3.65, "width": 0.66, "height": 0.62, "symmetry": "paired",
        "mullions": 1, "interior_palette": "neutral", "balcony_every": 0,
    },
}


INTERIOR_PALETTES = {
    "domestic": ([0.95, 0.63, 0.34], [0.10, 0.12, 0.16]),
    "office": ([0.70, 0.82, 0.95], [0.07, 0.11, 0.16]),
    "hospitality": ([0.96, 0.69, 0.40], [0.12, 0.10, 0.12]),
    "clinical": ([0.82, 0.92, 0.92], [0.08, 0.13, 0.15]),
    "classroom": ([0.92, 0.81, 0.52], [0.11, 0.13, 0.15]),
    "civic": ([0.88, 0.74, 0.49], [0.11, 0.10, 0.10]),
    "industrial": ([0.68, 0.78, 0.75], [0.08, 0.10, 0.11]),
    "neutral": ([0.86, 0.72, 0.50], [0.09, 0.11, 0.14]),
}


def _tokens(building):
    return " ".join(str(building.get(key, "")) for key in (
        "type", "building_use", "building_material", "building_part",
    )).lower()


def classify_profile(building):
    """Classify an architectural grammar from normalized semantics only."""
    tokens = _tokens(building)
    if any(value in tokens for value in ("hospital", "clinic", "healthcare")):
        return "healthcare"
    if any(value in tokens for value in ("school", "university", "college", "kindergarten")):
        return "education"
    if any(value in tokens for value in ("industrial", "warehouse", "hangar", "factory")):
        return "industrial"
    if "hotel" in tokens:
        return "hotel"
    if any(value in tokens for value in ("office", "commercial", "retail", "supermarket")):
        return "curtain_wall" if "glass" in tokens else "commercial"
    if any(value in tokens for value in ("apartments", "residential", "dormitory")):
        return "residential"
    if any(value in tokens for value in ("house", "detached", "terrace", "bungalow")):
        return "house"
    if any(value in tokens for value in ("church", "cathedral", "civic", "public", "government")):
        return "civic"
    if "glass" in tokens:
        return "curtain_wall"
    return "mixed"


def footprint_metrics(points):
    ring = list(points or [])
    if len(ring) > 2 and ring[0] == ring[-1]:
        ring = ring[:-1]
    if len(ring) < 3:
        return {"area": 0.0, "perimeter": 0.0, "aspect": 1.0, "vertices": len(ring)}
    area = abs(sum(
        ring[i][0] * ring[(i + 1) % len(ring)][1]
        - ring[(i + 1) % len(ring)][0] * ring[i][1]
        for i in range(len(ring)))) * 0.5
    lengths = [math.hypot(ring[(i + 1) % len(ring)][0] - ring[i][0],
                          ring[(i + 1) % len(ring)][1] - ring[i][1])
               for i in range(len(ring))]
    longest = max(lengths) if lengths else 1.0
    positive = [value for value in lengths if value > 0.2]
    shortest = min(positive) if positive else longest
    return {
        "area": area,
        "perimeter": sum(lengths),
        "aspect": max(1.0, longest / max(0.2, shortest)),
        "vertices": len(ring),
    }


def stable_seed(building):
    metrics = footprint_metrics(building.get("footprint"))
    identity = building.get("osm_id") or building.get("id") or "semantic"
    signature = "%s|%s|%.1f|%.1f|%d" % (
        identity, classify_profile(building), metrics["area"],
        metrics["perimeter"], metrics["vertices"])
    return zlib.crc32(signature.encode("utf-8")) & 0xFFFFFFFF


def facade_parameters(building, style, height=None, base=0.0, surface=None):
    """Resolve a deterministic yet varied facade/interior specification."""
    cfg = style.get("facade") or {}
    arch = style.get("architectural_detail") or DEFAULT_CONFIG
    profile = classify_profile(building)
    defaults = PROFILE_DEFAULTS[profile]
    seed = stable_seed(building)
    variant = seed % 5 if arch.get("profile_variation", True) else 2
    factors = (0.90, 0.96, 1.0, 1.07, 1.14)
    floor_h = max(2.2, float(cfg.get("floor_height", 3.2)))
    levels = building.get("levels")
    if levels not in (None, 0) and height is not None:
        observed = (float(height) - float(base)) / max(1, int(levels))
        if 2.2 <= observed <= 5.5:
            floor_h = observed
    if profile == "healthcare":
        floor_h = max(floor_h, 3.45)
    elif profile in ("commercial", "curtain_wall"):
        floor_h = max(floor_h, 3.25)
    bay = float(defaults["bay"]) * factors[variant]
    width = float(defaults["width"]) + (variant - 2) * 0.018
    window_h = float(defaults["height"]) + ((seed // 7) % 3 - 1) * 0.018
    lit, dark = INTERIOR_PALETTES[defaults["interior_palette"]]
    surface = surface or {"roughness": 0.8, "metallic": 0.0}
    return {
        "profile": profile,
        "variant": int(variant),
        "seed": int(seed),
        "floor_height": round(floor_h, 3),
        "bay": round(max(2.0, bay), 3),
        "window_width_ratio": round(max(0.28, min(0.93, width)), 3),
        "window_height_ratio": round(max(0.28, min(0.90, window_h)), 3),
        "symmetry": defaults["symmetry"] if arch.get("symmetry", True) else "grid",
        "mullion_divisions": int(defaults["mullions"]),
        "interior_palette": defaults["interior_palette"],
        "interior_lit_color": lit,
        "interior_dark_color": dark,
        "balcony_every": int(defaults["balcony_every"]),
        "wall_roughness": float(surface.get("roughness", 0.8)),
        "wall_metallic": float(surface.get("metallic", 0.0)),
        "window_roughness": 0.16 if profile == "curtain_wall" else 0.22,
    }


def detect(scene, style=None):
    cfg = (style or {}).get("architectural_detail") or DEFAULT_CONFIG
    if cfg.get("enabled") is False:
        return False
    return any(len(item.get("footprint", [])) >= 3
               and str(item.get("structure_mode", "solid")) != "roof_only"
               for item in scene.get("buildings", []))


def interior_layout_spec(building, style, height, base=0.0):
    """Resolve an editable inferred floor/corridor layout for a source shell."""
    cfg = style.get("architectural_detail") or DEFAULT_CONFIG
    profile = classify_profile(building)
    facade = facade_parameters(building, style, height=height, base=base)
    floor_h = max(2.2, float(facade["floor_height"]))
    total_floors = max(1, int((float(height) - float(base)) / floor_h))
    floors = min(total_floors, max(1, int(cfg.get("max_interior_floors", 8))))
    if profile == "industrial":
        layout = "open_plan"
    elif profile in ("healthcare", "hotel", "education"):
        layout = "double_loaded_corridor"
    elif profile in ("commercial", "curtain_wall", "civic"):
        layout = "core_and_open_plan"
    else:
        layout = "central_core_rooms"
    return {
        "enabled": bool(cfg.get("editable_interior_layouts", True)),
        "profile": profile, "layout": layout,
        "total_floors": total_floors, "modeled_floors": floors,
        "floor_height": floor_h,
        "corridor_width": max(1.4, float(cfg.get("corridor_width", 2.2))),
        "slab_thickness": max(0.06, float(cfg.get("floor_slab_thickness", 0.12))),
        "partition_thickness": max(0.05, float(cfg.get("partition_thickness", 0.09))),
        "max_partitions": max(0, int(cfg.get("max_partition_modules_per_building", 220))),
        "provenance": "procedural_inference",
    }
