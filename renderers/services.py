# -*- coding: utf-8 -*-
"""Renderer dependency boundary.

Renderers deliberately do not import ``guide_image_generator``. The main engine
exports a small, explicit set of stable drawing/data helpers through this object,
which avoids circular imports and keeps each renderer independently replaceable.
"""

EXPORTED_RENDERER_API = (
    "W", "H",
    "apply_tint",
    "build_render_kpis",
    "build_reward_display_units",
    "choose_shared_kpi_label_size",
    "clean",
    "config_day_icon",
    "draw_action_content",
    "draw_center",
    "draw_day_metric_bubbles",
    "draw_decorative_title",
    "draw_image_contain",
    "draw_item_rank_badge",
    "draw_item_fragment_badge",
    "draw_kpi_card",
    "draw_left",
    "draw_module_frame",
    "draw_special_day_badge",
    "draw_warning_icon",
    "find_item_meta",
    "get_font",
    "build_item_catalog",
    "recommended_special_badge_width",
    "resolve_path",
    "reward_icon_content_box",
    "rounded",
    "text_width",
)


class RendererServices:
    """Facade exposing only engine helpers that renderers are allowed to use."""

    def __init__(self, values):
        self._values = dict(values)

    @classmethod
    def from_engine_namespace(cls, namespace):
        missing = [name for name in EXPORTED_RENDERER_API if name not in namespace]
        if missing:
            raise RuntimeError("Renderer API 缺少依赖：" + ", ".join(missing))
        return cls({name: namespace[name] for name in EXPORTED_RENDERER_API})

    def __getattr__(self, name):
        try:
            return self._values[name]
        except KeyError:
            raise AttributeError(name)
