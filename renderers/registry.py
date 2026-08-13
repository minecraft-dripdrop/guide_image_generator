# -*- coding: utf-8 -*-
"""Automatic renderer discovery.

Adding ``renderers/foo.py`` with ``STYLE_IDS`` and ``render`` is enough; the
main generator does not need a new import or mapping entry.
"""
import importlib
import pkgutil
from pathlib import Path

_RESERVED = {"registry", "services", "shared"}
_CACHE = None


def _discover():
    registry = {}
    package = __package__ or "renderers"
    folder = Path(__file__).resolve().parent
    for item in pkgutil.iter_modules([str(folder)]):
        name = item.name
        if name.startswith("_") or name in _RESERVED:
            continue
        module = importlib.import_module(package + "." + name)
        style_ids = tuple(getattr(module, "STYLE_IDS", ()) or ())
        render = getattr(module, "render", None)
        if not style_ids or not callable(render):
            continue
        for style_id in style_ids:
            style_id = str(style_id).strip()
            if not style_id:
                continue
            if style_id in registry:
                raise RuntimeError("重复 renderer.style：{}".format(style_id))
            registry[style_id] = render
    return registry


def renderer_registry():
    global _CACHE
    if _CACHE is None:
        _CACHE = _discover()
    return dict(_CACHE)


def get_renderer(style):
    return renderer_registry().get(str(style or "").strip())


def available_styles():
    return tuple(sorted(renderer_registry()))
