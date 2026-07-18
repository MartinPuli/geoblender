"""
Tests for configuration, logging, and disk cache. They require neither Blender
nor Overpass and use temporary pytest state instead of the user's environment.

Run: python3 -m pytest tests/ -q
"""
import json
import logging
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import cityconfig  # noqa: E402
import citylog     # noqa: E402
import citycache   # noqa: E402

_ENV_KEYS = (
    "MAPS3D_TEXTURES", "MAPS3D_HDRI", "MAPS3D_CACHE",
    "MAPS3D_RADIUS", "MAPS3D_SAMPLES", "MAPS3D_ENGINE",
)


def _clear_env(monkeypatch):
    for k in _ENV_KEYS:
        monkeypatch.delenv(k, raising=False)


# --- cityconfig: defaults + overrides ---
def test_config_defaults(monkeypatch):
    _clear_env(monkeypatch)
    cfg = cityconfig.load_config()
    assert cfg["radius"] == 250
    assert cfg["samples"] == 128
    assert cfg["engine"] == "cycles"
    assert cfg["texture_dir"] is None
    assert cfg["hdri"] is None
    assert cfg["cache_dir"] is None


def test_config_missing_file_is_safe(monkeypatch, tmp_path):
    _clear_env(monkeypatch)
    cfg = cityconfig.load_config(str(tmp_path / "nonexistent.json"))
    assert cfg["radius"] == 250  # preserve defaults


def test_config_json_override(monkeypatch, tmp_path):
    _clear_env(monkeypatch)
    p = tmp_path / "cfg.json"
    p.write_text(json.dumps({"radius": 500, "engine": "eevee"}))
    cfg = cityconfig.load_config(str(p))
    assert cfg["radius"] == 500     # file overrides the default
    assert cfg["engine"] == "eevee"
    assert cfg["samples"] == 128    # lo no especificado se conserva


def test_config_env_overrides_file(monkeypatch, tmp_path):
    _clear_env(monkeypatch)
    p = tmp_path / "cfg.json"
    p.write_text(json.dumps({"radius": 500}))
    monkeypatch.setenv("MAPS3D_RADIUS", "999")
    cfg = cityconfig.load_config(str(p))
    assert cfg["radius"] == 999     # environment takes precedence


# --- citylog: type, level, and idempotence ---
def test_logger_is_logging_logger_default_level(monkeypatch):
    monkeypatch.delenv("MAPS3D_LOGLEVEL", raising=False)
    log = citylog.get_logger("maps3d_test_default")
    assert isinstance(log, logging.Logger)
    assert log.level == logging.INFO


def test_logger_level_from_env(monkeypatch):
    monkeypatch.setenv("MAPS3D_LOGLEVEL", "DEBUG")
    log = citylog.get_logger("maps3d_test_debug")
    assert isinstance(log, logging.Logger)
    assert log.level == logging.DEBUG


def test_logger_idempotent_no_duplicate_handlers():
    a = citylog.get_logger("maps3d_test_idem")
    before = len(a.handlers)
    b = citylog.get_logger("maps3d_test_idem")
    assert a is b               # same logger
    assert len(b.handlers) == before  # no duplica handlers


# --- citycache: round trip in a temporary directory ---
def test_cache_dir_honors_env(monkeypatch, tmp_path):
    target = str(tmp_path / "mycache")
    monkeypatch.setenv("MAPS3D_CACHE", target)
    assert citycache.cache_dir() == target


def test_cache_put_then_get_roundtrip(monkeypatch, tmp_path):
    monkeypatch.setenv("MAPS3D_CACHE", str(tmp_path / "cache"))
    key = citycache.key_hash("overpass:[out:json];node(1);out;")
    assert citycache.get(key) is None          # not created yet
    path = citycache.put(key, "RESPONSE-BODY")  # lazily creates the directory
    assert os.path.isfile(path)
    assert citycache.get(key) == "RESPONSE-BODY"


def test_key_hash_is_sha1_hex():
    h = citycache.key_hash("hola")
    assert len(h) == 40
    assert all(c in "0123456789abcdef" for c in h)
    assert citycache.key_hash("hola") == citycache.key_hash("hola")  # estable
