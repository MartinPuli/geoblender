"""Concise shared logger for maps-to-3d (pure module, no bpy)."""
import logging
import os

_FORMAT = "%(levelname)s %(name)s: %(message)s"


def _level_from_env():
    """Read a name or numeric log level from MAPS3D_LOGLEVEL."""
    raw = os.environ.get("MAPS3D_LOGLEVEL", "INFO").strip()
    if not raw:
        return logging.INFO
    if raw.isdigit():
        return int(raw)
    return getattr(logging, raw.upper(), logging.INFO)


def get_logger(name="maps3d"):
    """
    Return logger ``name`` and configure it exactly once.

    Re-read the level on every call for tests, but never duplicate handlers.
    """
    logger = logging.getLogger(name)
    logger.setLevel(_level_from_env())
    if not getattr(logger, "_maps3d_configured", False):
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter(_FORMAT))
        logger.addHandler(handler)
        logger.propagate = False
        logger._maps3d_configured = True
    return logger
