#!/usr/bin/env python3
"""
fetch_3dtiles.py — download a real regional mesh from Google Photorealistic 3D
Tiles and build a manifest for importing it into Blender around a local origin.

Usage:
  GOOGLE_MAPS_API_KEY=... python3 scripts/fetch_3dtiles.py LAT LON RADIUS_M OUT_DIR \
      [--detail 25] [--max-tiles 80]

Output in OUT_DIR/:
  tiles/*.glb           downloaded meshes
  manifest.json         { center:{lat,lon}, ecef_origin, enu[3x3],
                          tiles:[ { file, transform(16 col-major ECEF) } ] }

Requires the Map Tiles API to be enabled for the key. Preserve Google's required
attribution from each tile's copyright metadata.
"""
import json
import math
import os
import sys

try:
    import requests
except ImportError:
    sys.exit("Missing 'requests': python3 -m pip install requests")

BASE = "https://tile.googleapis.com"
ROOT = "/v1/3dtiles/root.json"

A = 6378137.0
F = 1.0 / 298.257223563
E2 = F * (2 - F)


def latlon_to_ecef(lat, lon, h=0.0):
    la, lo = math.radians(lat), math.radians(lon)
    n = A / math.sqrt(1 - E2 * math.sin(la) ** 2)
    x = (n + h) * math.cos(la) * math.cos(lo)
    y = (n + h) * math.cos(la) * math.sin(lo)
    z = (n * (1 - E2) + h) * math.sin(la)
    return (x, y, z)


def enu_basis(lat, lon):
    la, lo = math.radians(lat), math.radians(lon)
    sl, cl, so, co = math.sin(la), math.cos(la), math.sin(lo), math.cos(lo)
    east = (-so, co, 0.0)
    north = (-sl * co, -sl * so, cl)
    up = (cl * co, cl * so, sl)
    return [east, north, up]


def mat_ident():
    return [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]


def mat_mul(a, b):
    # 4x4 column-major (glTF/3D Tiles convention)
    r = [0.0] * 16
    for c in range(4):
        for row in range(4):
            s = 0.0
            for k in range(4):
                s += a[k * 4 + row] * b[c * 4 + k]
            r[c * 4 + row] = s
    return r


def mat_apply(m, p):
    x, y, z = p
    return (m[0] * x + m[4] * y + m[8] * z + m[12],
            m[1] * x + m[5] * y + m[9] * z + m[13],
            m[2] * x + m[6] * y + m[10] * z + m[14])


def box_center_world(box, T):
    return mat_apply(T, (box[0], box[1], box[2]))


def box_radius(box):
    # Upper-bound extent from the sum of the three semiaxis norms.
    def n(a, b, c):
        return math.sqrt(a * a + b * b + c * c)
    return n(box[3], box[4], box[5]) + n(box[6], box[7], box[8]) + n(box[9], box[10], box[11])


class Fetcher:
    def __init__(self, key, target_ecef, radius, detail, max_tiles, out_dir):
        self.key = key
        self.target = target_ecef
        self.radius = radius
        self.detail = detail
        self.max_tiles = max_tiles
        self.tiles_dir = os.path.join(out_dir, "tiles")
        os.makedirs(self.tiles_dir, exist_ok=True)
        self.collected = []      # {file, transform}
        self.session = None

    def _url(self, uri):
        u = BASE + uri
        sep = "&" if "?" in u else "?"
        u = u + sep + "key=" + self.key
        if self.session and "session=" not in u:
            u = u + "&session=" + self.session
        return u

    def _get_json(self, uri):
        r = requests.get(self._url(uri), timeout=40)
        r.raise_for_status()
        if "session=" in r.url:
            self.session = r.url.split("session=")[1].split("&")[0]
        return r.json()

    def _near(self, box, T=None):
        # Correct OBB containment: the box is a center plus three ECEF semiaxes.
        # The target is near when each projection is within its axis plus radius.
        cx, cy, cz = box[0], box[1], box[2]
        dx = self.target[0] - cx
        dy = self.target[1] - cy
        dz = self.target[2] - cz
        for i in (3, 6, 9):
            a0, a1, a2 = box[i], box[i + 1], box[i + 2]
            L2 = a0 * a0 + a1 * a1 + a2 * a2
            if L2 < 1e-6:
                continue
            proj = (dx * a0 + dy * a1 + dz * a2) / L2   # in semiaxis units
            margin = self.radius / math.sqrt(L2)
            if abs(proj) > 1.0 + margin:
                return False
        return True

    def visit(self, tile, parent_T, depth=0):
        if len(self.collected) >= self.max_tiles:
            return
        T = parent_T
        tr = tile.get("transform")
        if tr:
            T = mat_mul(parent_T, tr)
        bv = tile.get("boundingVolume", {})
        box = bv.get("box")
        if box and not self._near(box, T):
            if os.environ.get("TILEDEBUG"):
                c = box_center_world(box, T)
                print(f"  {'  '*depth}PRUNE depth={depth} dist={int(math.dist(c,self.target))} ge={tile.get('geometricError',0):.0f}")
            return
        ge = tile.get("geometricError", 0.0)
        if os.environ.get("TILEDEBUG") and depth <= 12:
            _u = (tile.get("content") or {}).get("uri", "")
            _k = "glb" if ".glb" in _u else (".json" if ".json" in _u else "-")
            print(f"  {'  '*depth}visit depth={depth} ge={ge:.0f} kind={_k} nchild={len(tile.get('children') or [])}")
        content = tile.get("content") or {}
        uri = content.get("uri", "")
        children = tile.get("children") or []

        # 1) Fetch a nested .json tileset, possibly with a session, and continue.
        if uri and ".json" in uri:
            try:
                sub = self._get_json(uri)
                if isinstance(sub, dict) and sub.get("root"):
                    self.visit(sub["root"], T, depth + 1)
            except Exception as e:
                if os.environ.get("TILEDEBUG"):
                    print(f"  {'  '*depth}SUBFAIL {str(e)[:60]}")
            return
        # 2) Download a GLB at target detail and stop to avoid overlapping LODs.
        if uri and ".glb" in uri and ge <= self.detail:
            self._download_glb(uri, T)
            return
        # 3) Descend through children nearest the target for more detail.
        if children:
            def key(ch):
                b = ch.get("boundingVolume", {}).get("box")
                Tc = mat_mul(T, ch["transform"]) if ch.get("transform") else T
                return math.dist(box_center_world(b, Tc), self.target) if b else 1e18
            for ch in sorted(children, key=key):
                if len(self.collected) >= self.max_tiles:
                    break
                self.visit(ch, T, depth + 1)
        # 4) Download a coarse leaf without children as a fallback.
        elif uri and ".glb" in uri:
            self._download_glb(uri, T)

    def _download_glb(self, uri, T):
        try:
            r = requests.get(self._url(uri), timeout=60)
            if r.status_code != 200 or r.content[:4] != b"glTF":
                return
            name = "tile_%03d.glb" % len(self.collected)
            with open(os.path.join(self.tiles_dir, name), "wb") as f:
                f.write(r.content)
            self.collected.append({"file": "tiles/" + name, "transform": T})
            if len(self.collected) % 10 == 0:
                print(f"   {len(self.collected)} tiles...")
        except Exception as e:
            print(f"   (GLB download failed: {e})")


def main():
    if len(sys.argv) < 5:
        sys.exit("Usage: fetch_3dtiles.py LAT LON RADIUS_M OUT_DIR [--detail 25] [--max-tiles 80]")
    lat, lon, radius = float(sys.argv[1]), float(sys.argv[2]), float(sys.argv[3])
    out_dir = sys.argv[4]
    detail = 25.0
    max_tiles = 80
    if "--detail" in sys.argv:
        detail = float(sys.argv[sys.argv.index("--detail") + 1])
    if "--max-tiles" in sys.argv:
        max_tiles = int(sys.argv[sys.argv.index("--max-tiles") + 1])
    key = os.environ.get("GOOGLE_MAPS_API_KEY")
    if not key:
        sys.exit("Missing GOOGLE_MAPS_API_KEY")

    os.makedirs(out_dir, exist_ok=True)
    target = latlon_to_ecef(lat, lon)
    print(f"Downloading Google 3D Tiles: {lat},{lon} r={radius}m detail<={detail} max={max_tiles}")
    fx = Fetcher(key, target, radius, detail, max_tiles, out_dir)
    root = fx._get_json(ROOT)
    fx.visit(root.get("root", {}), mat_ident())

    manifest = {
        "center": {"lat": lat, "lon": lon},
        "ecef_origin": list(target),
        "enu": enu_basis(lat, lon),
        "tiles": fx.collected,
    }
    with open(os.path.join(out_dir, "manifest.json"), "w") as f:
        json.dump(manifest, f)
    print(f"OK: {len(fx.collected)} tiles -> {out_dir}/tiles + manifest.json")


if __name__ == "__main__":
    main()
