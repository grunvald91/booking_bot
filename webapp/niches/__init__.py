"""Niche landing pages — YAML config loader.

Reads `_shared.yaml` and per-niche `<slug>.yaml` files in this directory,
deep-merges shared defaults under per-niche values, and exposes `get_niche(slug)`
for the aiohttp handler.
"""

from __future__ import annotations

import os
import threading
from typing import Any

import yaml

_NICHES_DIR = os.path.dirname(__file__)
_SHARED_NAME = "_shared.yaml"
_lock = threading.Lock()
_cache: dict[str, dict[str, Any]] = {}
_shared_cache: dict[str, Any] | None = None
_RELOAD_ON_EACH_REQUEST = os.environ.get("NICHES_RELOAD", "0") == "1"


def _load_yaml(path: str) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ValueError(f"YAML root must be a mapping: {path}")
    return data


def _deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge `overlay` into `base`. Overlay wins on conflicts."""
    result = dict(base)
    for key, value in overlay.items():
        if (
            key in result
            and isinstance(result[key], dict)
            and isinstance(value, dict)
        ):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _load_shared() -> dict[str, Any]:
    global _shared_cache
    if _shared_cache is None or _RELOAD_ON_EACH_REQUEST:
        _shared_cache = _load_yaml(os.path.join(_NICHES_DIR, _SHARED_NAME))
    return _shared_cache


def list_niches() -> list[str]:
    """Return the list of available niche slugs (filenames without extension)."""
    return sorted(
        os.path.splitext(name)[0]
        for name in os.listdir(_NICHES_DIR)
        if name.endswith(".yaml") and not name.startswith("_")
    )


def get_niche(slug: str) -> dict[str, Any] | None:
    """Return merged niche data, or None if the slug is unknown."""
    if not slug or slug != slug.lower() or not slug.replace("-", "").isalnum():
        return None

    with _lock:
        if not _RELOAD_ON_EACH_REQUEST and slug in _cache:
            return _cache[slug]

        path = os.path.join(_NICHES_DIR, f"{slug}.yaml")
        if not os.path.isfile(path):
            return None

        shared = _load_shared()
        niche = _load_yaml(path)
        merged = _deep_merge(shared, niche)
        merged["slug"] = slug

        if not _RELOAD_ON_EACH_REQUEST:
            _cache[slug] = merged
        return merged
