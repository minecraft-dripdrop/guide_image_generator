# -*- coding: utf-8 -*-
"""Private helpers for the mobile-first media themes.

These helpers are intentionally private to the new renderer family and do not
change any existing theme behavior.  All five renderers use a native 9:16
canvas while consuming the same public guide data and renderer services.
"""
from __future__ import annotations

from pathlib import Path
import re
from PIL import Image, ImageDraw

from .shared import SharedRendererTools


def mobile_canvas(services, background):
    """Return a native 9:16 RGBA canvas using engine width."""
    w = int(services.W)
    h = int(round(w * 16 / 9))
    return w, h, Image.new("RGBA", (w, h), background)


def rcfg(guide):
    data = (guide.get("theme_config") or {}).get("renderer")
    return dict(data) if isinstance(data, dict) else {}


def clean(services, value, fallback=""):
    text = services.clean(str(value or ""))
    return text or fallback


def target_text(services, info):
    raw = clean(services, info.get("target"), "")
    if not raw:
        return "目标未填"
    return raw


def special_text(services, info):
    return clean(services, info.get("special_label"), "")


def target_level_number(services, info):
    """Return just the numeric target tier when possible (e.g. 第3档 -> 3)."""
    raw = target_text(services, info)
    m = re.search(r"(\d+)", raw)
    return m.group(1) if m else raw


def day_metric_text(services, info, max_items=4):
    parts = []
    for item in list(info.get("metric_items") or [])[:max_items]:
        label = clean(services, item.get("label"), "")
        value = clean(services, item.get("value"), "")
        if label or value:
            parts.append((label + (" " + value if value else "")).strip())
    return "  ·  ".join(parts)


def draw_day_metrics(base, draw, guide, info, box, services, fg, accent, bg=None, border=None):
    """Use the shared fixed-spec day metric component when data exists."""
    if not list(info.get("metric_items") or []):
        return
    tools = SharedRendererTools(services)
    tools.draw_metric_icons(base, draw, guide, info, box, fg=fg, accent=accent, bg=bg, border=border, max_items=4)


def draw_footer(base, draw, guide, services, y1, h, fg, bg=None, line=None):
    """9:16-aware footer; unlike SharedRendererTools.footer_plain it does not use services.H."""
    w = base.width
    y2 = min(base.height, int(y1 + h))
    if bg:
        draw.rectangle((0, y1, w, y2), fill=bg)
    if line:
        draw.line((0, y1, w, y1), fill=line, width=2)

    cfg = guide.get("cfg") or {}
    raw_icon = cfg.get("watermark_group_icon")
    icon_path = None
    if raw_icon:
        try:
            p = services.resolve_path(cfg, raw_icon)
            if p and Path(p).is_file():
                icon_path = Path(p)
        except Exception:
            icon_path = None

    text = clean(services, guide.get("watermark"), "")
    left = 42
    if icon_path:
        size = min(42, max(30, y2-y1-12))
        iy = y1 + (y2-y1-size)//2
        services.draw_image_contain(base, icon_path, (42, iy, 42+size, iy+size))
        left = 42 + size + 12

    services.draw_left(
        draw, (left, y1+5, w-42, y2-5), text, fg,
        max_size=18, min_size=15, bold=False, max_lines=2,
        line_gap=2, valign="center",
    )


def draw_title(draw, guide, services, box, fg, accent=None, kicker=None, title_size=38):
    x1,y1,x2,y2 = map(int, box)
    title = clean(services, guide.get("title"), "活动攻略")
    subtitle = clean(services, guide.get("subtitle"), "")
    if kicker:
        services.draw_left(draw, (x1,y1,x2,y1+30), kicker, accent or fg,
                           max_size=16,min_size=13,bold=True,max_lines=1,valign="center")
        ty = y1+32
    else:
        ty = y1
    services.draw_left(draw, (x1,ty,x2,y2-(34 if subtitle else 0)), title, fg,
                       max_size=title_size,min_size=28,bold=True,max_lines=2,line_gap=2,valign="center")
    if subtitle:
        services.draw_left(draw, (x1,y2-35,x2,y2), subtitle, accent or fg,
                           max_size=16,min_size=14,bold=False,max_lines=1,valign="center")


def draw_risk_block(draw, guide, services, tools, box, fg, accent, fill, border=None, prefix="提醒"):
    x1,y1,x2,y2 = map(int, box)
    draw.rounded_rectangle((x1,y1,x2,y2), radius=14, fill=fill, outline=border or accent, width=2)
    items = tools.risk_items(guide)
    text = "  ·  ".join(items) if items else "暂无额外提醒，按每日操作执行。"
    services.draw_left(draw, (x1+22,y1+10,x2-18,y2-10), f"{prefix}：{text}", fg,
                       max_size=18,min_size=15,bold=True,max_lines=3,line_gap=3,valign="center")


def draw_kpi_cells(base, draw, guide, services, tools, box, fg, accent, fill, border, compact=True):
    tools.draw_kpis_with_icons(base, draw, guide, box, fg=fg, accent=accent, fill=fill, border=border, compact=compact)


def reward_block(base, draw, guide, services, tools, box, fg, accent, fill, border, title="奖励", max_items=4):
    x1,y1,x2,y2 = map(int, box)
    draw.rounded_rectangle((x1,y1,x2,y2), radius=14, fill=fill, outline=border or accent, width=2)
    services.draw_left(draw, (x1+18,y1+8,x2-18,y1+38), title, accent,
                       max_size=19,min_size=16,bold=True,max_lines=1,valign="center")
    tools.draw_reward_icons(base, draw, guide, (x1+16,y1+42,x2-16,y2-8), fg=fg, accent=accent,
                            bg=None, border=None, max_items=max_items, show_names=True, text_fallback=True)
