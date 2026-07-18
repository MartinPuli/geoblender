"""
Pure OSM2World adapter tests that require neither Java nor the .jar.

They verify that missing dependencies report unavailable and trigger the default
procedural-engine fallback.

Run: python3 -m pytest tests/test_adapter.py -q
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import pytest  # noqa: E402

import osm2world_adapter as o2w  # noqa: E402


def test_unavailable_without_jar(monkeypatch):
    # Without OSM2WORLD_JAR or jar=, it is unavailable even if Java is on PATH.
    monkeypatch.delenv("OSM2WORLD_JAR", raising=False)
    assert o2w.osm2world_available() is False
    assert o2w.osm2world_available(jar=None) is False


def test_unavailable_with_missing_jar_file(monkeypatch, tmp_path):
    # A nonexistent .jar does not count as available.
    monkeypatch.delenv("OSM2WORLD_JAR", raising=False)
    ghost = str(tmp_path / "no_existe.jar")
    assert o2w.osm2world_available(jar=ghost) is False


def test_run_raises_when_unavailable(monkeypatch):
    # Missing Java or .jar must trigger the documented fallback signal.
    monkeypatch.delenv("OSM2WORLD_JAR", raising=False)
    with pytest.raises(o2w.OSM2WorldUnavailable):
        o2w.run_osm2world("zona.osm", "zona.obj", jar=None)


def test_unavailable_when_no_java(monkeypatch, tmp_path):
    # A valid .jar without discoverable Java is still unavailable.
    real_jar = tmp_path / "OSM2World.jar"
    real_jar.write_text("dummy")
    monkeypatch.setenv("OSM2WORLD_JAR", str(real_jar))
    monkeypatch.delenv("JAVA_BIN", raising=False)
    monkeypatch.setattr(o2w.shutil, "which", lambda _name: None)
    assert o2w.osm2world_available() is False
    with pytest.raises(o2w.OSM2WorldUnavailable):
        o2w.run_osm2world("zona.osm", "zona.obj")


def test_unavailable_class_is_runtimeerror():
    assert issubclass(o2w.OSM2WorldUnavailable, RuntimeError)
