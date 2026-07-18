"""Disk cache for Overpass responses (pure module, no bpy).

Avoid repeated Overpass queries across runs. Keys normally use ``key_hash`` of
the query text; values are raw response strings. The directory is created lazily
on the first write. ``MAPS3D_CACHE`` overrides ``~/.cache/maps-to-3d``.
"""
import hashlib
import os


def cache_dir():
    """Return the cache directory from MAPS3D_CACHE or the user cache."""
    env = os.environ.get("MAPS3D_CACHE")
    if env:
        return os.path.expanduser(env)
    return os.path.join(os.path.expanduser("~"), ".cache", "maps-to-3d")


def key_hash(text):
    """Return a stable SHA1 hex digest for the provided text."""
    if isinstance(text, str):
        text = text.encode("utf-8")
    return hashlib.sha1(text).hexdigest()


def _path_for(key):
    return os.path.join(cache_dir(), str(key) + ".txt")


def _ensure_dir():
    d = cache_dir()
    os.makedirs(d, exist_ok=True)
    return d


def get(key):
    """Return cached content for ``key``, or None when absent."""
    path = _path_for(key)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return fh.read()
    except OSError:
        return None


def put(key, text):
    """Store ``text`` under ``key`` and return the resulting path."""
    _ensure_dir()
    path = _path_for(key)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return path
