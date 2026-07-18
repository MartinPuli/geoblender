"""Configuration loader for maps-to-3d (pure module, no bpy).

Precedence is DEFAULTS < config file < environment variables. JSON is always
supported; YAML is optional through PyYAML. Missing or malformed files fall back
to defaults without aborting.
"""
import json
import os

# Base defaults. Optional paths are filled from the environment in load_config.
DEFAULTS = {
    "radius": 250,          # meters around the center
    "samples": 128,         # render samples
    "engine": "cycles",     # Blender engine
    "texture_dir": None,    # env MAPS3D_TEXTURES
    "hdri": None,           # env MAPS3D_HDRI
    "cache_dir": None,      # env MAPS3D_CACHE
}

# Environment override map: env -> (config key, caster).
ENV_OVERRIDES = {
    "MAPS3D_RADIUS": ("radius", int),
    "MAPS3D_SAMPLES": ("samples", int),
    "MAPS3D_ENGINE": ("engine", str),
    "MAPS3D_TEXTURES": ("texture_dir", str),
    "MAPS3D_HDRI": ("hdri", str),
    "MAPS3D_CACHE": ("cache_dir", str),
}


def _note(msg):
    """Emit an informational note when citylog is available."""
    try:
        from citylog import get_logger
        get_logger().info(msg)
    except Exception:
        pass


def _apply_env(cfg):
    """Apply environment overrides to cfg in place."""
    for env_key, (cfg_key, caster) in ENV_OVERRIDES.items():
        raw = os.environ.get(env_key)
        if raw is None or raw == "":
            continue
        try:
            cfg[cfg_key] = caster(raw)
        except (TypeError, ValueError):
            _note("invalid value in %s=%r; ignored" % (env_key, raw))
    return cfg


def _parse_yaml(text, path):
    """Parse YAML when PyYAML is installed; otherwise return None."""
    try:
        import yaml  # optional 'yaml' extra
    except ImportError:
        _note("PyYAML is not installed; ignoring %s (install the 'yaml' extra)" % path)
        return None
    try:
        return yaml.safe_load(text)
    except Exception as exc:  # yaml.YAMLError and compatible parser failures
        _note("invalid YAML in %s: %s" % (path, exc))
        return None


def _merge_file(cfg, path):
    """Merge a config file into cfg without aborting on errors."""
    if not os.path.isfile(path):
        _note("config not found: %s (using defaults)" % path)
        return cfg
    try:
        with open(path, "r", encoding="utf-8") as fh:
            text = fh.read()
    except OSError as exc:
        _note("could not read %s: %s" % (path, exc))
        return cfg

    ext = os.path.splitext(path)[1].lower()
    if ext in (".yaml", ".yml"):
        data = _parse_yaml(text, path)
    else:
        # Treat every non-YAML extension as JSON.
        try:
            data = json.loads(text)
        except ValueError as exc:
            _note("invalid JSON in %s: %s" % (path, exc))
            data = None

    if isinstance(data, dict):
        cfg.update(data)
    return cfg


def load_config(path=None):
    """
    Return a configuration dictionary.

    Precedence: DEFAULTS < file (when ``path`` is set) < environment.
    Missing or malformed files preserve defaults.
    """
    cfg = dict(DEFAULTS)
    _apply_env(cfg)            # fill optional paths and environment-backed defaults
    if path:
        _merge_file(cfg, path)  # file overrides defaults
    _apply_env(cfg)            # environment wins
    return cfg
