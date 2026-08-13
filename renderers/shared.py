# -*- coding: utf-8 -*-
"""Shared, layout-neutral components used by every non-classic renderer."""
from pathlib import Path
import re
import time

from .reward_items import RewardItemRenderer


def renderer_colors(guide, defaults=None):
    defaults = dict(defaults or {})
    theme_cfg = guide.get("theme_config") or {}
    colors = theme_cfg.get("colors") if isinstance(theme_cfg.get("colors"), dict) else {}
    result = dict(defaults)
    result.update(colors)
    p = guide.get("palette") or {}
    result.setdefault("primary", p.get("primary", "#4E8C63"))
    result.setdefault("dark", p.get("dark", "#2F5D40"))
    result.setdefault("light", p.get("light", "#EAF3EC"))
    result.setdefault("chip", p.get("chip", "#DCEBDF"))
    result.setdefault("text", result.get("dark", "#26384A"))
    result.setdefault("background", "#F3F6FA")
    return result


class SharedRendererTools:
    def __init__(self, services):
        self.s = services

    def colors(self, guide, defaults=None):
        return renderer_colors(guide, defaults)

    def risk_items(self, guide):
        clean = self.s.clean
        risk = guide.get("risk") or []
        if isinstance(risk, str):
            risk = [clean(x) for x in risk.replace("\r", "").split("\n") if clean(x)]
        return [clean(str(x)) for x in risk if clean(str(x))]

    def kpis(self, guide):
        clean = self.s.clean
        try:
            return self.s.build_render_kpis((guide.get("kpis") or [])[:3], guide.get("cfg") or {})
        except Exception:
            rows = []
            for pair in (guide.get("kpis") or [])[:3]:
                if isinstance(pair, (list, tuple)) and len(pair) >= 2:
                    rows.append({"label": clean(str(pair[0])), "value": clean(str(pair[1]))})
            return rows

    def author(self, guide):
        clean = self.s.clean
        cfg = guide.get("cfg") or {}
        author = cfg.get("author") if isinstance(cfg.get("author"), dict) else {}
        prefix = clean(str(author.get("prefix") or "攻略制作"))
        name = clean(str(author.get("text") or ""))
        return (prefix + " · " + name).strip(" ·") if name else prefix

    def save(self, img, out_path, guide, started=None):
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        cfg = guide.get("cfg") or {}
        perf_cfg = cfg.get("performance") if isinstance(cfg.get("performance"), dict) else {}
        optimize = bool(perf_cfg.get("png_optimize", False))
        level = max(0, min(9, int(perf_cfg.get("png_compress_level", 1) or 1)))
        img.convert("RGB").save(out_path, "PNG", optimize=optimize, compress_level=level)
        if started is not None and bool(perf_cfg.get("print_timing", False)):
            print("[耗时] {}：{:.2f} 秒".format(out_path.name, time.perf_counter() - started))

    @staticmethod
    def rule(draw, xy, fill, width=2):
        draw.line(tuple(map(int, xy)), fill=fill, width=max(1, int(width)))

    def text(self, draw, box, text, color, size=22, bold=False, align="left", max_lines=6, valign="top"):
        clean = self.s.clean
        if align == "center":
            self.s.draw_center(draw, box, clean(str(text)), color, max_size=size, min_size=max(10, size-8), bold=bold, max_lines=max_lines, line_gap=4)
        else:
            self.s.draw_left(draw, box, clean(str(text)), color, max_size=size, min_size=max(10, size-8), bold=bold, max_lines=max_lines, line_gap=4, valign=valign)

    def footer_plain(self, draw, guide, fg, line=None, bg=None, height=54):
        W, H = self.s.W, self.s.H
        y1 = H - height
        if bg:
            draw.rectangle((0, y1, W, H), fill=bg)
        if line:
            draw.line((0, y1, W, y1), fill=line, width=2)
        # Readability-first footer: a small area is fine, tiny text is not.
        self.s.draw_center(
            draw, (36, y1+4, W-36, H-4), guide.get("watermark", ""), fg,
            max_size=19, min_size=15, bold=False, max_lines=2, line_gap=2
        )

    def day_title(self, info):
        clean = self.s.clean
        title = clean(str(info.get("day") or "DAY"))
        target = clean(str(info.get("target") or ""))
        return title + ("｜目标 " + target if target else "")

    def metric_text(self, info):
        clean = self.s.clean
        parts = []
        for item in info.get("metric_items") or []:
            label = clean(str(item.get("label") or ""))
            value = clean(str(item.get("value") or ""))
            if label or value:
                parts.append((label + " " + value).strip())
        return "   ".join(parts)

    def draw_simple_kpis(self, draw, guide, box, fg, accent, fill=None, border=None, compact=False):
        clean = self.s.clean
        items = self.kpis(guide)
        if not items:
            return
        x1,y1,x2,y2 = map(int, box)
        count = len(items)
        gap = 12
        cw = (x2-x1-gap*(count-1))/max(1,count)
        for i,item in enumerate(items):
            a = int(round(x1+i*(cw+gap))); b = int(round(a+cw))
            if fill:
                draw.rectangle((a,y1,b,y2), fill=fill, outline=border or accent, width=2)
            label = clean(str(item.get("label") or ""))
            value = clean(str(item.get("value") or ""))
            self.s.draw_left(
                draw,(a+10,y1+8,b-10,y1+(35 if compact else 45)),label,accent,
                max_size=(17 if compact else 20),min_size=(14 if compact else 15),
                bold=True,max_lines=1,line_gap=0,valign="center"
            )
            self.s.draw_left(
                draw,(a+10,y1+(32 if compact else 44),b-10,y2-6),value,fg,
                max_size=(25 if compact else 32),min_size=(17 if compact else 18),
                bold=True,max_lines=2,line_gap=2,valign="center"
            )

    def reward_summary(self, guide):
        text = self.s.clean(str(guide.get("reward") or ""))
        if text:
            text = re.sub(r"^[^：:]*[：:]\s*", "", text)
        return text or "—"

    @staticmethod
    def flat_reward_items(nodes):
        out = []
        def walk(node):
            if not isinstance(node, dict):
                return
            typ = node.get("type", "item")
            if typ == "item":
                out.append(node)
            elif typ == "bundle":
                for child in node.get("items") or []:
                    walk(child)
            elif typ == "choice":
                for child in node.get("options") or []:
                    walk(child)
        for node in nodes or []:
            walk(node)
        return out

    def draw_reward_icons(self, base, draw, guide, box, fg, accent, bg=None, border=None, max_items=6, show_names=True, text_fallback=True, pixel=False):
        s = self.s
        clean = s.clean
        cfg = guide.get("cfg") or {}
        leaves = self.flat_reward_items(guide.get("reward_items") or [])[:max_items]
        x1, y1, x2, y2 = map(int, box)
        if bg:
            draw.rectangle((x1, y1, x2, y2), fill=bg, outline=border or accent, width=1 if pixel else 2)
        if not leaves:
            if text_fallback:
                s.draw_left(draw, (x1+6, y1+4, x2-6, y2-4), self.reward_summary(guide), fg, max_size=16, min_size=10, bold=False, max_lines=4, line_gap=2, valign="center")
            return
        gap = 6 if pixel else 10
        cell_w = (x2 - x1 - gap * max(0, len(leaves)-1)) / max(1, len(leaves))
        reward_renderer = RewardItemRenderer(s, guide)
        for i, item in enumerate(leaves):
            cx1 = int(round(x1 + i * (cell_w + gap)))
            cx2 = int(round(cx1 + cell_w))
            name_h = 40 if show_names else 0
            icon_area_h = max(20, (y2-y1) - name_h - 4)
            icon_size = int(min(cell_w - 8, icon_area_h - 4, 66 if not pixel else 54))
            icon_size = max(18, icon_size)
            ix1 = int(cx1 + (cell_w-icon_size)/2)
            iy1 = y1 + 2
            ibox = (ix1, iy1, ix1+icon_size, iy1+icon_size)
            resolved = reward_renderer.draw_icon(base, item, ibox)
            icon_path = resolved.get("icon_path")
            if not (icon_path and Path(icon_path).exists()):
                if pixel:
                    draw.rectangle(ibox, outline=accent, width=1)
                else:
                    s.rounded(draw, ibox, 6, None, outline=accent, width=1)
                s.draw_center(draw, ibox, "?", accent, max_size=18, min_size=12, bold=True, max_lines=1)
            if show_names:
                qty = clean(str(item.get("qty") or ""))
                label = clean(str(item.get("name") or "物品")) + ((" ×" + qty) if qty else "")
                s.draw_center(
                    draw, (cx1+2, min(y2-38, iy1+icon_size+1), cx2-2, y2), label, fg,
                    max_size=14, min_size=12, bold=True, max_lines=2, line_gap=1
                )

    def draw_kpis_with_icons(self, base, draw, guide, box, fg, accent, fill=None, border=None, compact=False, vertical=False, pixel=False):
        s = self.s
        clean = s.clean
        items = self.kpis(guide)
        if not items:
            return
        x1, y1, x2, y2 = map(int, box)
        gap = 8 if compact else 12
        if vertical:
            cell_h = (y2-y1-gap*max(0,len(items)-1))/max(1,len(items))
            boxes = [(x1, int(y1+i*(cell_h+gap)), x2, int(y1+i*(cell_h+gap)+cell_h)) for i in range(len(items))]
        else:
            cell_w = (x2-x1-gap*max(0,len(items)-1))/max(1,len(items))
            boxes = [(int(x1+i*(cell_w+gap)), y1, int(x1+i*(cell_w+gap)+cell_w), y2) for i in range(len(items))]
        for item, (a,b,cx,dy) in zip(items, boxes):
            if fill:
                draw.rectangle((a,b,cx,dy), fill=fill, outline=border or accent, width=1 if pixel else 2)
            icon = item.get("icon")
            has_icon = bool(icon and Path(icon).exists())
            label = clean(str(item.get("label") or ""))
            value = clean(str(item.get("value") or ""))
            if vertical:
                icon_size = min(30 if compact else 38, dy-b-8)
                tx = a+8
                if has_icon:
                    iy = int(b+(dy-b-icon_size)/2)
                    s.draw_image_contain(base, Path(icon), (a+8, iy, a+8+icon_size, iy+icon_size))
                    tx = a+16+icon_size
                s.draw_left(draw,(tx,b+3,cx-8,b+(dy-b)*0.48),label,accent,max_size=14 if compact else 17,min_size=12,bold=True,max_lines=1,line_gap=0,valign="center")
                s.draw_left(draw,(tx,b+(dy-b)*0.42,cx-8,dy-3),value,fg,max_size=20 if compact else 25,min_size=15,bold=True,max_lines=1,line_gap=0,valign="center")
            else:
                icon_size = min(34 if compact else 44, dy-b-12, max(20,(cx-a)//4))
                text_left = a+8
                if has_icon:
                    iy = int(b+(dy-b-icon_size)/2)
                    s.draw_image_contain(base, Path(icon), (a+8, iy, a+8+icon_size, iy+icon_size))
                    text_left = a+16+icon_size
                s.draw_left(draw,(text_left,b+4,cx-6,b+(30 if compact else 38)),label,accent,max_size=15 if compact else 18,min_size=12,bold=True,max_lines=1,line_gap=0,valign="center")
                s.draw_left(draw,(text_left,b+(27 if compact else 36),cx-6,dy-4),value,fg,max_size=23 if compact else 29,min_size=16,bold=True,max_lines=2,line_gap=1,valign="center")

    def draw_metric_icons(self, base, draw, guide, info, box, fg, accent, bg=None, border=None, max_items=4, pixel=False):
        """Readable, fixed-spec day status component.

        Same kind of "remaining / expected" information should never become a
        mix of large and tiny text. All cells in one call use the same icon
        target size and the same 14px text target (13px minimum).
        """
        s = self.s
        clean = s.clean
        cfg = guide.get("cfg") or {}
        items = list(info.get("metric_items") or [])[:max_items]
        x1, y1, x2, y2 = map(int, box)
        if not items:
            return
        if bg:
            draw.rectangle((x1, y1, x2, y2), fill=bg, outline=border or accent, width=1)

        n = len(items)
        h = max(1, y2-y1)
        w = max(1, x2-x1)

        # Wide bars keep one row. Narrow manga/map cards use a 2-column grid
        # when the theme has reserved enough vertical room.
        one_row_cw = w / max(1, n)
        if n > 2 and one_row_cw < 185 and h >= 48:
            cols = 2
        else:
            cols = n
        rows = (n + cols - 1) // cols
        gap_x = 6
        gap_y = 4
        cw = (w - gap_x * max(0, cols-1)) / max(1, cols)
        rh = (h - gap_y * max(0, rows-1)) / max(1, rows)

        icon_size = max(16, min(25, int(rh - 6)))
        font_max = 14
        font_min = 13

        for i, item in enumerate(items):
            rr, cc = divmod(i, cols)
            a = int(round(x1 + cc * (cw + gap_x)))
            b = int(round(a + cw))
            yy1 = int(round(y1 + rr * (rh + gap_y)))
            yy2 = int(round(yy1 + rh))

            icon = s.config_day_icon(cfg, item)
            has_icon = bool(icon and Path(icon).exists())
            tx = a + 5
            if has_icon:
                iy = int(yy1 + (yy2-yy1-icon_size)/2)
                s.draw_image_contain(base, Path(icon), (a+5, iy, a+5+icon_size, iy+icon_size))
                tx = a + 10 + icon_size

            label = clean(str(item.get("label") or ""))
            value = clean(str(item.get("value") or ""))
            shown = (label + ("  " + value if value else "")).strip()

            s.draw_left(
                draw, (tx, yy1+1, b-4, yy2-1), shown, fg,
                max_size=font_max, min_size=font_min, bold=True,
                max_lines=1, line_gap=0, valign="center"
            )

