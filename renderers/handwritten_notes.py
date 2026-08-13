# -*- coding: utf-8 -*-
"""Renderer module for ``handwritten_notes``.

V35.38 notebook identity refinement:
- budget -> rewards -> D1~D7 -> tips
- generic renderer-local font_path (no font-name-specific config)
- notebook timeline instead of card rows
- cream journal now uses graphite/pencil writing with restrained red accents; review markup uses a single 阅 stamp
- rough pencil lines, scribbled circles, highlighter strokes, taped sticky notes
"""
from functools import lru_cache
from pathlib import Path
import hashlib
import random
import re
import time
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageChops, ImageOps
from .shared import SharedRendererTools
from .reward_items import RewardItemRenderer

STYLE_IDS = ("handwritten_notes",)


def _renderer_cfg(guide):
    theme_cfg = guide.get("theme_config") or {}
    rc = theme_cfg.get("renderer") if isinstance(theme_cfg.get("renderer"), dict) else {}
    cfg = dict(rc or {})
    project_cfg = guide.get("cfg") or {}
    if isinstance(project_cfg.get("handwritten_notes"), dict):
        cfg.update(project_cfg.get("handwritten_notes"))
    return cfg


def _clean(services, value):
    return services.clean(str(value or ""))


def _resolve_font_path(guide, services, rcfg):
    """Resolve the notebook font, with an optional per-variant override.

    ``font_override_path`` is intentionally generic: a variant may point at any
    font file the user owns.  If that override is empty or missing on disk, the
    base theme's ``font_path`` is used automatically instead of falling back to
    an unrelated system font.
    """
    cfg = guide.get("cfg") or {}

    def _try(raw):
        raw = raw or ""
        if not raw:
            return None
        resolved = services.resolve_path(cfg, raw)
        if resolved and Path(resolved).is_file():
            return Path(resolved)
        direct = Path(str(raw))
        if direct.is_file():
            return direct
        cwd_p = Path.cwd() / str(raw)
        return cwd_p if cwd_p.is_file() else None

    override = _try(rcfg.get("font_override_path"))
    if override is not None:
        return override
    return _try(rcfg.get("font_path"))


@lru_cache(maxsize=96)
def _load_font_cached(path_text, mtime_ns, size):
    if path_text and Path(path_text).exists():
        try:
            return ImageFont.truetype(path_text, size=max(1, int(size)))
        except Exception:
            pass
    return None


class _NotebookFonts:
    """Renderer-local handwriting font helper.

    ``weight`` uses small duplicate glyph offsets rather than Pillow's outline
    stroke. This makes thin handwriting fonts darker without closing up the
    counters and gaps between adjacent Chinese characters. ``tracking`` adds
    explicit inter-character spacing to compensate for naturally narrow fonts.
    """
    def __init__(self, services, font_path=None, weight=0, tracking=0, scale=1.0):
        self.s = services
        self.path = str(font_path) if font_path else ""
        try:
            self.weight = max(0, min(3, int(weight or 0)))
        except Exception:
            self.weight = 0
        try:
            self.tracking = max(0.0, min(4.0, float(tracking or 0)))
        except Exception:
            self.tracking = 0.0
        try:
            self.scale = max(0.70, min(1.50, float(scale or 1.0)))
        except Exception:
            self.scale = 1.0
        try:
            self.mtime_ns = Path(self.path).stat().st_mtime_ns if self.path else 0
        except Exception:
            self.mtime_ns = 0

    def font(self, size, bold=False):
        actual_size = max(1, int(round(float(size) * self.scale)))
        f = _load_font_cached(self.path, self.mtime_ns, actual_size) if self.path else None
        return f or self.s.get_font(actual_size, bold)

    def _char_advance(self, draw, ch, font):
        try:
            return float(draw.textlength(ch or " ", font=font))
        except Exception:
            bb = draw.textbbox((0, 0), ch or " ", font=font)
            return float(max(1, bb[2] - bb[0]))

    def width(self, draw, text, font):
        text = str(text or " ")
        if not text:
            return 0.0
        total = sum(self._char_advance(draw, ch, font) for ch in text)
        total += self.tracking * max(0, len(text) - 1)
        # duplicate-offset fake weight extends the visual edge a little
        return total + (0.75 if self.weight >= 1 else 0.0)

    def wrap(self, draw, text, font, max_width):
        result = []
        for para in str(text or "").replace("\r", "").split("\n"):
            if not para:
                result.append("")
                continue
            line = ""
            for ch in para:
                test = line + ch
                if line and self.width(draw, test, font) > max_width:
                    result.append(line)
                    line = ch
                else:
                    line = test
            if line:
                result.append(line)
        return result or [""]

    def fit(self, draw, text, box, max_size, min_size, bold=False, max_lines=5, line_gap=3):
        x1, y1, x2, y2 = map(int, box)
        for size in range(int(max_size), int(min_size) - 1, -1):
            f = self.font(size, bold)
            lines = self.wrap(draw, text, f, x2 - x1)
            if len(lines) > max_lines:
                continue
            heights = []
            total = 0
            for line in lines:
                bb = draw.textbbox((0, 0), line or " ", font=f)
                h = max(1, bb[3] - bb[1])
                heights.append(h)
                total += h
            total += line_gap * max(0, len(lines) - 1)
            if total <= y2 - y1:
                return f, lines, heights, total
        f = self.font(min_size, bold)
        lines = self.wrap(draw, text, f, x2 - x1)[:max_lines]
        heights = []
        total = 0
        for line in lines:
            bb = draw.textbbox((0, 0), line or " ", font=f)
            h = max(1, bb[3] - bb[1])
            heights.append(h)
            total += h
        total += line_gap * max(0, len(lines) - 1)
        return f, lines, heights, total

    def _weight_offsets(self, bold=False):
        # Bold headings get one extra subtle pass when using a custom thin font.
        w = self.weight + (1 if bold and self.path else 0)
        w = min(3, w)
        if w <= 0:
            return [(0.0, 0.0)]
        if w == 1:
            return [(0.0, 0.0), (0.65, 0.0)]
        if w == 2:
            return [(0.0, 0.0), (0.65, 0.0), (0.0, 0.65)]
        return [(0.0, 0.0), (0.70, 0.0), (0.0, 0.70), (0.70, 0.70)]

    def _draw_line(self, draw, xy, text, font, fill, bold=False):
        x, y = float(xy[0]), float(xy[1])
        offsets = self._weight_offsets(bold)
        for idx, ch in enumerate(str(text or "")):
            for dx, dy in offsets:
                draw.text((x + dx, y + dy), ch, font=font, fill=fill)
            x += self._char_advance(draw, ch, font)
            if idx < len(str(text or "")) - 1:
                x += self.tracking

    def left(self, draw, box, text, color, max_size=20, min_size=11, bold=False, max_lines=5, line_gap=3, valign="top"):
        x1, y1, x2, y2 = map(int, box)
        f, lines, hs, total = self.fit(draw, text, box, max_size, min_size, bold, max_lines, line_gap)
        y = y1 if valign == "top" else y1 + max(0, (y2 - y1 - total) / 2)
        for line, h in zip(lines, hs):
            self._draw_line(draw, (x1, y), line, f, color, bold=bold)
            y += h + line_gap

    def center(self, draw, box, text, color, max_size=20, min_size=11, bold=False, max_lines=3, line_gap=3):
        x1, y1, x2, y2 = map(int, box)
        f, lines, hs, total = self.fit(draw, text, box, max_size, min_size, bold, max_lines, line_gap)
        y = y1 + max(0, (y2 - y1 - total) / 2)
        for line, h in zip(lines, hs):
            w = self.width(draw, line, f)
            self._draw_line(draw, ((x1 + x2 - w) / 2, y), line, f, color, bold=bold)
            y += h + line_gap




def _fit_rgba(src, size):
    tw, th = map(int, size)
    tw, th = max(1, tw), max(1, th)
    src = src.convert("RGBA")
    if src.width <= 0 or src.height <= 0:
        return Image.new("RGBA", (tw, th), (0, 0, 0, 0))
    scale = min(tw / src.width, th / src.height)
    nw = max(1, int(round(src.width * scale)))
    nh = max(1, int(round(src.height * scale)))
    return src.resize((nw, nh), Image.LANCZOS)


def _clamp_strength(value, default=0.55):
    try:
        return max(0.0, min(1.0, float(value)))
    except Exception:
        return default


def _icon_style(rcfg):
    """Notebook icon mode.

    V35.10 intentionally keeps only two visual choices:
      - original: untouched game icon
      - sticker: original icon with a white cut-out border and soft paper shadow

    Old sketch/crayon values are treated as ``original`` so old configs do not
    crash or silently keep an unwanted filter effect.
    """
    style = str(rcfg.get("icon_style") or "original").strip().lower()
    aliases = {
        "none": "original", "off": "original", "normal": "original",
        "原图": "original", "原始": "original",
        "贴纸": "sticker", "sticker_white": "sticker", "white_sticker": "sticker",
    }
    style = aliases.get(style, style)
    return style if style in ("original", "sticker") else "original"


def _sticker_icon_image(src, outline_ratio=0.08, shadow=True, shadow_alpha=58):
    """Create a white die-cut sticker around the *final composed artwork*.

    Important: callers should compose the final visible item artwork first
    (including rank badges), then pass that complete RGBA artwork here.
    The outline therefore follows
    S/SS/SSS badges too instead of outlining only the base item icon.
    The border thickness is proportional to the final artwork size.
    """
    rgba = src.convert("RGBA")
    # White cut-out border scales with the final artwork size rather than
    # using a fixed pixel width.  Large stickers therefore get a wider border
    # while tiny metric icons keep a fine, unobtrusive edge.
    try:
        ratio = max(0.0, float(outline_ratio))
    except Exception:
        ratio = 0.08
    ow = int(round(min(rgba.width, rgba.height) * ratio))
    if ratio > 0 and ow < 1:
        ow = 1

    shadow_dx, shadow_dy = (2, 3) if shadow else (0, 0)
    blur = 1.25 if shadow else 0.0
    pad = ow + max(abs(shadow_dx), abs(shadow_dy)) + 4
    canvas_size = (rgba.width + pad * 2, rgba.height + pad * 2)

    alpha = Image.new("L", canvas_size, 0)
    alpha.paste(rgba.getchannel("A"), (pad, pad))

    if ow > 0:
        # MaxFilter needs an odd kernel.  No style-level upper clamp is applied;
        # the white border grows from whatever final artwork size the user chose.
        kernel = max(3, ow * 2 + 1)
        if kernel % 2 == 0:
            kernel += 1
        outline_mask = alpha.filter(ImageFilter.MaxFilter(kernel))
    else:
        outline_mask = alpha

    result = Image.new("RGBA", canvas_size, (0, 0, 0, 0))
    if shadow:
        shadow_mask = outline_mask.filter(ImageFilter.GaussianBlur(radius=blur))
        sh = Image.new("RGBA", canvas_size, (78, 72, 65, 0))
        try:
            alpha_scale = max(0, min(255, int(shadow_alpha))) / 255.0
        except Exception:
            alpha_scale = 58 / 255.0
        sh.putalpha(shadow_mask.point(lambda v: int(v * alpha_scale)))
        shifted = Image.new("RGBA", canvas_size, (0, 0, 0, 0))
        shifted.alpha_composite(sh, (shadow_dx, shadow_dy))
        result = Image.alpha_composite(result, shifted)

    white = Image.new("RGBA", canvas_size, (255, 255, 252, 0))
    white.putalpha(outline_mask)
    result = Image.alpha_composite(result, white)

    art = Image.new("RGBA", canvas_size, (0, 0, 0, 0))
    art.alpha_composite(rgba, (pad, pad))
    return Image.alpha_composite(result, art)


def _crop_rgba_to_content(src, margin=2):
    rgba = src.convert("RGBA")
    bbox = rgba.getchannel("A").getbbox()
    if not bbox:
        return rgba
    x1, y1, x2, y2 = bbox
    x1 = max(0, x1 - margin); y1 = max(0, y1 - margin)
    x2 = min(rgba.width, x2 + margin); y2 = min(rgba.height, y2 + margin)
    return rgba.crop((x1, y1, x2, y2))


def _compose_reward_art(guide, services, item, meta, canvas_size=160):
    """Build notebook reward art through the shared reward-item renderer.

    The standard quality frame is intentionally omitted for handwritten notes.
    S / SS / SSS remains part of the composed transparent artwork, then the
    notebook renderer adds its white sticker outline around the whole result.
    """
    reward_renderer = RewardItemRenderer(services, guide)
    return reward_renderer.compose_art(
        item,
        canvas_size=canvas_size,
        include_quality_frame=False,
        trim_transparent=False,
        margin_ratio=0.08,
    )


def _draw_notebook_art(base, src, box, rcfg, rng=None):
    """Draw an RGBA artwork in notebook style.

    ``sticker_art_scale`` is intentionally not capped at 1.0.  Scale is applied
    to the artwork first; the white border is added afterwards.  Values such as
    1.2, 1.5 or 2.0 therefore truly enlarge the sticker instead of merely
    shrinking the border inside a fixed icon box.
    """
    if src is None:
        return False
    src = src.convert("RGBA")
    x1, y1, x2, y2 = map(int, box)
    tw, th = max(1, x2 - x1), max(1, y2 - y1)
    style = _icon_style(rcfg)

    if style == "sticker":
        try:
            scale = float(rcfg.get("sticker_art_scale", 1.0))
        except Exception:
            scale = 1.0
        # No upper style limit.  Only reject non-positive values.
        if scale <= 0:
            scale = 1.0
        art_w = max(1, int(round(tw * scale)))
        art_h = max(1, int(round(th * scale)))
        fitted = _fit_rgba(src, (art_w, art_h))

        try:
            outline_ratio = float(rcfg.get("sticker_outline_ratio", 0.08))
        except Exception:
            outline_ratio = 0.08
        outline_ratio = max(0.0, outline_ratio)
        shadow = bool(rcfg.get("sticker_shadow", True))
        try:
            shadow_alpha = int(rcfg.get("sticker_shadow_alpha", 58))
        except Exception:
            shadow_alpha = 58
        fitted = _sticker_icon_image(
            fitted,
            outline_ratio=outline_ratio,
            shadow=shadow,
            shadow_alpha=shadow_alpha,
        )

        if rng is not None:
            try:
                angle = float(rcfg.get("sticker_rotation", 1.2))
            except Exception:
                angle = 1.2
            angle = max(0.0, min(8.0, angle))
            if angle > 0:
                fitted = fitted.rotate(rng.uniform(-angle, angle), resample=Image.BICUBIC, expand=True)
        # Deliberately do NOT fit back into the original box.  The user's scale
        # may make the sticker larger than its nominal layout slot.
    else:
        fitted = _fit_rgba(src, (tw, th))

    px = int(round((x1 + x2 - fitted.width) / 2))
    py = int(round((y1 + y2 - fitted.height) / 2))
    base.alpha_composite(fitted, (px, py))
    return True


def _draw_notebook_icon(base, icon_path, box, rcfg, rng=None):
    if not icon_path:
        return False
    try:
        p = Path(icon_path)
        if not p.is_file():
            return False
        src = Image.open(p).convert("RGBA")
    except Exception:
        return False
    return _draw_notebook_art(base, src, box, rcfg, rng)



def _avatar_rgba(path, round_mask=True):
    """Load/crop an avatar to a compact RGBA artwork.

    QQ/group avatars are rendered as notebook stickers independently from the
    item icon style, so users may keep item icons original while still giving
    avatars a white cut-out border.
    """
    if not path:
        return None
    try:
        p = Path(path)
        if not p.is_file():
            return None
        src = Image.open(p).convert("RGBA")
    except Exception:
        return None
    side = min(src.width, src.height)
    if side <= 0:
        return None
    left = (src.width - side) // 2
    top = (src.height - side) // 2
    src = src.crop((left, top, left + side, top + side))
    if round_mask:
        mask = Image.new("L", (side, side), 0)
        md = ImageDraw.Draw(mask)
        md.ellipse((1, 1, side - 2, side - 2), fill=255)
        src.putalpha(mask)
    return _crop_rgba_to_content(src, margin=1)


def _draw_avatar_sticker(base, avatar_path, box, outline_ratio=0.10, shadow=True,
                         shadow_alpha=48, art_scale=1.0, round_mask=True):
    art = _avatar_rgba(avatar_path, round_mask=round_mask)
    if art is None:
        return False
    x1, y1, x2, y2 = map(int, box)
    tw, th = max(1, x2 - x1), max(1, y2 - y1)
    try:
        scale = float(art_scale)
    except Exception:
        scale = 1.0
    if scale <= 0:
        scale = 1.0
    fitted = _fit_rgba(art, (max(1, int(tw * scale)), max(1, int(th * scale))))
    fitted = _sticker_icon_image(
        fitted,
        outline_ratio=max(0.0, float(outline_ratio or 0)),
        shadow=bool(shadow),
        shadow_alpha=shadow_alpha,
    )
    px = int(round((x1 + x2 - fitted.width) / 2))
    py = int(round((y1 + y2 - fitted.height) / 2))
    base.alpha_composite(fitted, (px, py))
    return True


def _resolve_avatar_path(guide, services, raw):
    if not raw:
        return None
    cfg = guide.get("cfg") or {}
    p = services.resolve_path(cfg, raw)
    if p and Path(p).is_file():
        return Path(p)
    p2 = Path(str(raw))
    return p2 if p2.is_file() else None


def _draw_author_signature(img, draw, guide, services, rtools, hf, colors, rcfg, x, y, x2):
    """Draw '玩家手记 / 作者' followed by the QQ avatar sticker."""
    cfg = guide.get("cfg") or {}
    author_cfg = cfg.get("author") if isinstance(cfg.get("author"), dict) else {}
    text = "玩家手记 / " + rtools.author(guide)
    try:
        avatar_size = max(16, int(rcfg.get("author_avatar_size", 27)))
    except Exception:
        avatar_size = 27
    show_avatar = bool(rcfg.get("show_author_avatar", True))
    avatar_raw = rcfg.get("author_avatar") or author_cfg.get("qq_avatar") or author_cfg.get("avatar")
    avatar_path = _resolve_avatar_path(guide, services, avatar_raw) if show_avatar else None
    try:
        ratio = max(0.0, float(rcfg.get("author_avatar_outline_ratio", rcfg.get("avatar_outline_ratio", 0.10))))
    except Exception:
        ratio = 0.10
    try:
        art_scale = float(rcfg.get("author_avatar_scale", 1.0))
    except Exception:
        art_scale = 1.0

    # Fit the text while reserving room for the avatar at the end.
    reserve = (avatar_size + 13) if avatar_path else 0
    max_text_w = max(80, x2 - x - reserve)
    chosen_font = None
    chosen_size = 16
    for sz in range(16, 10, -1):
        f = hf.font(sz, False)
        if hf.width(draw, text, f) <= max_text_w:
            chosen_font = f
            chosen_size = sz
            break
    chosen_font = chosen_font or hf.font(11, False)
    text_w = hf.width(draw, text, chosen_font)
    bb = draw.textbbox((0, 0), text or " ", font=chosen_font)
    text_h = max(1, bb[3] - bb[1])
    ty = y + max(0, (avatar_size - text_h) / 2) - 1
    hf._draw_line(draw, (x, ty), text, chosen_font, colors["dark"], bold=False)
    if avatar_path:
        ax1 = int(x + text_w + 8)
        ay1 = int(y)
        _draw_avatar_sticker(
            img, avatar_path,
            (ax1, ay1, ax1 + avatar_size, ay1 + avatar_size),
            outline_ratio=ratio,
            shadow=bool(rcfg.get("avatar_sticker_shadow", True)),
            shadow_alpha=int(rcfg.get("avatar_sticker_shadow_alpha", 44)),
            art_scale=art_scale,
            round_mask=True,
        )
    return int(x + text_w + reserve)


def _draw_footer_with_group_avatar(img, draw, guide, services, hf, colors, rcfg, box):
    """Center the group avatar sticker + watermark as one footer signature."""
    x1, y1, x2, y2 = map(int, box)
    cfg = guide.get("cfg") or {}
    text = _clean(services, guide.get("watermark") or cfg.get("watermark"))
    if not text:
        return
    show_icon = bool(rcfg.get("show_group_avatar", True))
    group_raw = rcfg.get("group_avatar") or cfg.get("watermark_group_icon")
    group_path = _resolve_avatar_path(guide, services, group_raw) if show_icon else None
    try:
        icon_size = max(14, int(rcfg.get("group_avatar_size", 25)))
    except Exception:
        icon_size = 25
    try:
        ratio = max(0.0, float(rcfg.get("group_avatar_outline_ratio", rcfg.get("avatar_outline_ratio", 0.10))))
    except Exception:
        ratio = 0.10
    try:
        art_scale = float(rcfg.get("group_avatar_scale", 1.0))
    except Exception:
        art_scale = 1.0

    # Fit footer text and center icon+text as one unit.
    gap = 9 if group_path else 0
    chosen_font = None
    for sz in range(16, 9, -1):
        f = hf.font(sz, False)
        tw = hf.width(draw, text, f)
        if tw + (icon_size + gap if group_path else 0) <= (x2 - x1):
            chosen_font = f
            break
    chosen_font = chosen_font or hf.font(10, False)
    tw = hf.width(draw, text, chosen_font)
    total = tw + (icon_size + gap if group_path else 0)
    sx = x1 + max(0, (x2 - x1 - total) / 2)
    if group_path:
        iy = int(y1 + max(0, (y2 - y1 - icon_size) / 2))
        _draw_avatar_sticker(
            img, group_path,
            (int(sx), iy, int(sx) + icon_size, iy + icon_size),
            outline_ratio=ratio,
            shadow=bool(rcfg.get("avatar_sticker_shadow", True)),
            shadow_alpha=int(rcfg.get("avatar_sticker_shadow_alpha", 44)),
            art_scale=art_scale,
            round_mask=True,
        )
        sx += icon_size + gap
    bb = draw.textbbox((0, 0), text or " ", font=chosen_font)
    th = max(1, bb[3] - bb[1])
    ty = y1 + max(0, (y2 - y1 - th) / 2) - 1
    hf._draw_line(draw, (sx, ty), text, chosen_font, colors["dark"], bold=False)


def _scribble_focus_loop(draw, box, color, rng, width=3, passes=2):
    """A deliberately imperfect red-pen loop for special days.

    Unlike a UI ellipse, this is sampled as a slightly uneven hand-drawn loop,
    with different wobble on each pass and a tiny open gap near the lower-right.
    """
    import math
    x1, y1, x2, y2 = map(int, box)
    cx, cy = (x1 + x2) / 2.0, (y1 + y2) / 2.0
    rx, ry = max(8.0, (x2 - x1) / 2.0), max(8.0, (y2 - y1) / 2.0)
    for p in range(max(1, passes)):
        pts = []
        # leave a small human-looking gap rather than closing a perfect ellipse
        start_deg = 18 + rng.randint(-5, 5)
        end_deg = 350 + rng.randint(-5, 3)
        steps = 54
        for i in range(steps + 1):
            t = math.radians(start_deg + (end_deg - start_deg) * i / steps)
            wobble_x = rng.uniform(-2.8, 2.8) + (1.2 if p else 0)
            wobble_y = rng.uniform(-2.4, 2.4) - (0.8 if p else 0)
            # slow wobble makes the loop feel hand-guided rather than noisy
            sx = math.sin(t * 3.0 + p) * 1.8
            sy = math.cos(t * 2.0 + p) * 1.5
            pts.append((int(cx + rx * math.cos(t) + wobble_x + sx),
                        int(cy + ry * math.sin(t) + wobble_y + sy)))
        draw.line(pts, fill=color, width=width, joint="curve")

def _note_mode(rcfg):
    """Return the visual language for the handwriting variant.

    red_journal: warm cream sketchbook written primarily in graphite/pencil, with red reserved for action marks and emphasis.
    review_markup: clean ruled paper with black source notes and a separate red
                   reviewer/teacher annotation layer.
    classic: legacy notebook behavior used by old configs and retro print.
    """
    value = str(rcfg.get("note_mode") or "classic").strip().lower()
    aliases = {
        "red": "red_journal", "cream_red": "red_journal", "米白红笔": "red_journal",
        "review": "review_markup", "black_red": "review_markup", "黑笔红批": "review_markup",
    }
    value = aliases.get(value, value)
    return value if value in ("red_journal", "review_markup", "classic") else "classic"


def _print_effect(rcfg):
    value = str(rcfg.get("print_effect") or "").strip().lower()
    aliases = {
        "retro": "retro_print",
        "old_print": "retro_print",
        "vintage_print": "retro_print",
        "旧印刷": "retro_print",
        "复古印刷": "retro_print",
    }
    return aliases.get(value, value)


def _draw_retro_paper_wear(img, colors, rcfg, rng):
    """Add subtle age, edge darkening and imperfect fold creases behind content."""
    if _print_effect(rcfg) != "retro_print":
        return
    W, H = img.size
    try:
        aging = max(0.0, min(1.5, float(rcfg.get("retro_edge_aging", 0.55))))
    except Exception:
        aging = 0.55
    if aging <= 0:
        return

    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    paper_box = (42, 28, W - 42, H - 62)
    x1, y1, x2, y2 = paper_box
    # Uneven warm edge oxidation: several translucent strokes rather than one
    # digital-perfect vignette.
    edge_rgb = (126, 91, 48)
    layers = max(4, int(10 * aging))
    for i in range(layers):
        inset = i * 3 + rng.randint(0, 2)
        alpha = int((5 + (layers - i) * 1.6) * min(1.0, aging))
        od.rectangle((x1 + inset, y1 + inset, x2 - inset, y2 - inset), outline=(*edge_rgb, alpha), width=1)

    # A few extremely faint handling stains, deterministic for this guide.
    stain_count = max(2, int(4 * min(1.0, aging)))
    for _ in range(stain_count):
        sw = rng.randint(90, 210)
        sh = rng.randint(40, 115)
        sx = rng.randint(x1 + 20, max(x1 + 21, x2 - sw - 20))
        sy = rng.randint(y1 + 25, max(y1 + 26, y2 - sh - 25))
        alpha = rng.randint(5, 11)
        od.ellipse((sx, sy, sx + sw, sy + sh), fill=(137, 101, 58, alpha))

    if bool(rcfg.get("retro_fold_creases", True)):
        # Top-right dog-ear / fold memory: light line paired with a darker one.
        c_alpha = int(34 * min(1.0, aging))
        hi_alpha = int(42 * min(1.0, aging))
        p1 = (x2 - 138, y1 + 5)
        p2 = (x2 - 5, y1 + 124)
        od.line((p1, p2), fill=(116, 88, 56, c_alpha), width=2)
        od.line(((p1[0] - 3, p1[1] + 2), (p2[0] - 3, p2[1] + 2)), fill=(255, 247, 222, hi_alpha), width=1)
        # Bottom-left soft fold, shorter and less obvious.
        q1 = (x1 + 5, y2 - 115)
        q2 = (x1 + 112, y2 - 5)
        od.line((q1, q2), fill=(116, 88, 56, max(8, c_alpha - 8)), width=1)
        od.line(((q1[0] + 3, q1[1] - 2), (q2[0] + 3, q2[1] - 2)), fill=(255, 247, 222, max(8, hi_alpha - 10)), width=1)

    img.alpha_composite(overlay)


def _shift_l_channel(ch, dx, dy):
    """Shift one L channel without the wraparound produced by ImageChops.offset."""
    w, h = ch.size
    out = Image.new("L", (w, h), 0)
    src_x1 = max(0, -dx); src_y1 = max(0, -dy)
    src_x2 = min(w, w - dx) if dx >= 0 else w
    src_y2 = min(h, h - dy) if dy >= 0 else h
    if src_x2 <= src_x1 or src_y2 <= src_y1:
        return out
    crop = ch.crop((src_x1, src_y1, src_x2, src_y2))
    out.paste(crop, (max(0, dx), max(0, dy)))
    return out


def _apply_retro_print_effect(img, colors, rcfg, rng):
    """Turn the clean notebook render into a restrained low-fi old print.

    The effect is intentionally subtle: it should read as an aged printed handout,
    not as a destructive Instagram filter.  It adds low-resolution softness,
    slight CMY/RGB registration error and halftone dots while preserving layout.
    """
    if _print_effect(rcfg) != "retro_print":
        return img
    base = img.convert("RGBA")
    W, H = base.size

    # Small type loses a little crispness as if reproduced by an older press or
    # photocopier.  Downsample/upscale and blend back instead of blurring hard.
    try:
        softness = max(0.0, min(1.0, float(rcfg.get("retro_softness", 0.48))))
    except Exception:
        softness = 0.48
    if softness > 0:
        factor = 1.0 - 0.055 * softness
        lw, lh = max(32, int(W * factor)), max(32, int(H * factor))
        low = base.resize((lw, lh), Image.Resampling.BILINEAR).resize((W, H), Image.Resampling.BILINEAR)
        base = Image.blend(base, low, 0.34 * softness)

    # Ink registration drift. One-pixel channel separation is enough at this
    # canvas size; blend strength controls visibility so text remains legible.
    try:
        mis = max(0.0, min(1.5, float(rcfg.get("retro_ink_misregister", 0.65))))
    except Exception:
        mis = 0.65
    if mis > 0:
        px = max(1, int(round(mis)))
        r, g, b, a = base.split()
        rr = _shift_l_channel(r, px, 0)
        bb = _shift_l_channel(b, -px, 1 if px > 0 else 0)
        shifted = Image.merge("RGBA", (rr, g, bb, a))
        base = Image.blend(base, shifted, min(0.22, 0.12 + 0.07 * min(1.0, mis)))

    # Halftone dots are clipped by estimated ink density, so the paper itself
    # stays paper-like while darker printed areas acquire tiny screen dots.
    try:
        half = max(0.0, min(1.0, float(rcfg.get("retro_halftone_strength", 0.26))))
    except Exception:
        half = 0.26
    if half > 0:
        gray = ImageOps.grayscale(base.convert("RGB"))
        density = ImageOps.invert(gray).point(lambda v: 0 if v < 36 else min(255, int((v - 36) * 1.65)))
        spacing = max(5, int(rcfg.get("retro_halftone_spacing", 7) or 7))
        tile = Image.new("L", (spacing, spacing), 0)
        td = ImageDraw.Draw(tile)
        dot = max(1, int(round(1 + half * 1.4)))
        cx = spacing // 2; cy = spacing // 2
        td.ellipse((cx - dot, cy - dot, cx + dot, cy + dot), fill=255)
        pattern = Image.new("L", (W, H), 0)
        for yy in range(0, H, spacing):
            for xx in range(0, W, spacing):
                pattern.paste(tile, (xx, yy))
        mask = ImageChops.multiply(pattern, density)
        mask = mask.point(lambda v: int(v * (0.12 + 0.24 * half)))
        ink = Image.new("RGBA", (W, H), (76, 62, 48, 0))
        ink.putalpha(mask)
        base = Image.alpha_composite(base, ink)

    return base


def _seed_rng(guide, salt=""):
    src = f"{guide.get('title','')}|{salt}"
    seed = int(hashlib.md5(src.encode("utf-8")).hexdigest()[:8], 16)
    return random.Random(seed)


def _rough_line(draw, points, color, width=2, rng=None, jitter=2, passes=1):
    rng = rng or random.Random(1)
    pts = [(int(x), int(y)) for x, y in points]
    if len(pts) < 2:
        return
    for _ in range(max(1, passes)):
        out = []
        for idx, (x, y) in enumerate(pts):
            if idx in (0, len(pts) - 1):
                out.append((x + rng.randint(-1, 1), y + rng.randint(-1, 1)))
            else:
                out.append((x + rng.randint(-jitter, jitter), y + rng.randint(-jitter, jitter)))
        draw.line(out, fill=color, width=width, joint="curve")


def _rough_underline(draw, x1, y, x2, color, rng, width=2):
    mid1 = x1 + int((x2 - x1) * 0.34)
    mid2 = x1 + int((x2 - x1) * 0.71)
    _rough_line(draw, [(x1, y), (mid1, y + rng.randint(-2, 2)), (mid2, y + rng.randint(-2, 2)), (x2, y + rng.randint(-1, 2))], color, width, rng, 2, 2)


def _scribble_circle(draw, box, color, rng, width=2, passes=2):
    x1, y1, x2, y2 = map(int, box)
    for _ in range(passes):
        dx1, dy1 = rng.randint(-2, 2), rng.randint(-2, 2)
        dx2, dy2 = rng.randint(-2, 2), rng.randint(-2, 2)
        draw.ellipse((x1 + dx1, y1 + dy1, x2 + dx2, y2 + dy2), outline=color, width=width)


def _highlighter(draw, box, fill, rng):
    x1, y1, x2, y2 = map(int, box)
    pts = [
        (x1 + rng.randint(-4, 3), y1 + rng.randint(0, 4)),
        (x2 + rng.randint(-3, 5), y1 + rng.randint(-2, 3)),
        (x2 + rng.randint(-5, 3), y2 + rng.randint(-2, 4)),
        (x1 + rng.randint(-3, 5), y2 + rng.randint(-3, 3)),
    ]
    draw.polygon(pts, fill=fill)

def _special_day_icon_kind(label):
    """Return the tiny notebook doodle used beside a known special-day label."""
    text = str(label or "").strip()
    if "氪金" in text or "充值" in text:
        return "coins"
    if "收尾" in text:
        return "flag"
    return ""


def _draw_handdrawn_coin(draw, cx, cy, w, h, colors, rng):
    """One low hand-drawn coin with a stronger sketch outline and clear overlap."""
    outline = colors.get("coin_outline", "#68431B")
    inner_outline = colors.get("coin_inner_outline", "#8B5B25")
    fill = colors.get("coin_fill", "#DDB65A")
    shade = colors.get("coin_shadow", "#B98738")
    shine = colors.get("coin_highlight", "#F3D98E")
    x1, x2 = cx - w / 2, cx + w / 2
    y1, y2 = cy - h / 2, cy + h / 2

    # Visible lower rim so overlapping coins still read as stacked at small size.
    draw.rounded_rectangle(
        (int(x1 + 1), int(y1 + 3), int(x2 - 1), int(y2 + 5)),
        radius=max(2, int(h / 2)),
        fill=shade,
    )
    draw.ellipse((int(x1), int(y1), int(x2), int(y2)), fill=fill)

    # Two imperfect passes create a stronger notebook silhouette without turning
    # the icon into a clean UI vector.
    _scribble_circle(
        draw, (int(x1), int(y1), int(x2), int(y2)),
        outline, rng, width=max(2, int(round(h * 0.18))), passes=2,
    )
    _scribble_circle(
        draw, (int(x1 + 2), int(y1 + 1), int(x2 - 2), int(y2 - 1)),
        inner_outline, rng, width=1, passes=1,
    )
    _rough_line(
        draw,
        [
            (cx - w * 0.42, cy + h * 0.12),
            (cx, cy + h * 0.31),
            (cx + w * 0.42, cy + h * 0.12),
        ],
        outline,
        max(1, int(round(h * 0.14))),
        rng,
        1,
        1,
    )
    _rough_line(
        draw,
        [
            (cx - w * 0.25, cy - h * 0.10),
            (cx, cy - h * 0.27),
            (cx + w * 0.24, cy - h * 0.09),
        ],
        shine,
        1,
        rng,
        1,
        1,
    )


def _draw_handdrawn_coin_stack(draw, box, colors, rng):
    """Natural low coin pile (approved C composition) with a stronger outline."""
    x1, y1, x2, y2 = map(int, box)
    w = max(20, x2 - x1)
    h = max(18, y2 - y1)
    cx = (x1 + x2) / 2
    cy = (y1 + y2) / 2 + 1
    # The approved C pile is wider than the nominal icon box because the
    # outer coins and sparkle extend far beyond the centre.  Scale against the
    # *true* visual bounds so the doodle never intrudes into the label text.
    scale = min(w / 108.0, h / 40.0)
    scale = max(0.38, min(1.18, scale))

    # Draw rear/lower coins first, then overlap toward the top.  The pile stays
    # wide and low rather than reading as three artificial vertical towers.
    pile = [
        (-31,  7, 42, 13),
        ( 28,  8, 42, 13),
        ( -8,  3, 46, 14),
        ( 12, -7, 44, 14),
        (-19,-14, 44, 14),
        (  6,-22, 46, 14),
    ]
    for dx, dy, coin_w, coin_h in pile:
        _draw_handdrawn_coin(
            draw,
            cx + dx * scale,
            cy + dy * scale,
            coin_w * scale,
            coin_h * scale,
            colors,
            rng,
        )

    accent = colors.get("primary", "#B64B43")
    sx, sy = cx + 49 * scale, cy - 19 * scale
    r = 4.3 * scale
    pts = [
        (sx, sy-r), (sx+r*.22, sy-r*.22), (sx+r, sy), (sx+r*.22, sy+r*.22),
        (sx, sy+r), (sx-r*.22, sy+r*.22), (sx-r, sy), (sx-r*.22, sy-r*.22),
    ]
    draw.polygon([(int(a), int(b)) for a, b in pts], fill=accent)


def _draw_handdrawn_finish_flag(draw, box, colors, rng):
    """Small finish flag doodle, kept intentionally simpler than a UI icon."""
    x1, y1, x2, y2 = map(int, box)
    w, h = max(18, x2 - x1), max(18, y2 - y1)
    cx = (x1 + x2) / 2
    cy = (y1 + y2) / 2
    scale = min(w / 39.0, h / 42.0)
    scale = max(0.55, min(1.15, scale))
    ink = colors.get("dark", colors.get("text", "#4B4A45"))
    accent = colors.get("primary", "#B64B43")
    paper = colors.get("paper", "#FFF7E8")
    pole_x = cx - 8 * scale
    _rough_line(
        draw,
        [(pole_x, cy + 17 * scale), (pole_x + 1.5 * scale, cy - 17 * scale)],
        ink,
        max(1, int(round(1.8 * scale))),
        rng,
        1,
        2,
    )
    flag = [
        (pole_x + 1 * scale, cy - 17 * scale),
        (cx + 18 * scale, cy - 13 * scale),
        (cx + 11 * scale, cy - 2 * scale),
        (pole_x + 1 * scale, cy - 6 * scale),
    ]
    draw.polygon([(int(a), int(b)) for a, b in flag], fill=paper)
    _rough_line(draw, flag + [flag[0]], ink, max(1, int(round(1.5 * scale))), rng, 1, 1)
    # Tiny check mark makes the meaning "finish/complete" immediate.
    _rough_line(
        draw,
        [
            (cx - 1 * scale, cy - 10 * scale),
            (cx + 4 * scale, cy - 6 * scale),
            (cx + 11 * scale, cy - 12 * scale),
        ],
        accent,
        max(1, int(round(1.8 * scale))),
        rng,
        1,
        2,
    )


def _draw_special_day_label(draw, hf, special_text, special_label, box, colors, rng):
    """Draw the existing special label and, when known, a small doodle to its right."""
    x1, y1, x2, y2 = map(int, box)
    kind = _special_day_icon_kind(special_label)
    if not kind:
        hf.left(
            draw, box, special_text, colors["primary"],
            max_size=12, min_size=8, bold=True, max_lines=1, valign="center",
        )
        return

    icon_w = 58 if kind == "coins" else 34
    gap = 12 if kind == "coins" else 8
    # Reserve icon space first so long labels shrink rather than collide with it.
    text_box = (x1, y1, max(x1 + 40, x2 - icon_w - gap), y2)
    font, lines, heights, total = hf.fit(
        draw, special_text, text_box,
        max_size=12, min_size=8, bold=True, max_lines=1, line_gap=0,
    )
    line = lines[0] if lines else special_text
    text_y = y1 + max(0, (y2 - y1 - total) / 2)
    hf._draw_line(draw, (x1, text_y), line, font, colors["primary"], bold=True)
    text_w = hf.width(draw, line, font)
    # Always start the icon after the rendered glyphs plus a fixed safe gap.
    # The text box already reserves this width, so no fallback is allowed to
    # pull the doodle back over the label when space becomes tight.
    icon_x1 = int(x1 + text_w + gap)
    icon_x1 = min(icon_x1, x2 - icon_w)

    # Align the doodle to the *visible glyph center*, not merely the label box.
    # This keeps ★氪金日 / ★收尾日 and their icon on the same visual baseline
    # even when the handwriting font has a non-zero bbox top bearing.
    ink_bb = draw.textbbox((0, 0), line or " ", font=font)
    visual_center_y = text_y + (ink_bb[1] + ink_bb[3]) / 2
    if kind == "coins":
        icon_h = min(31, max(25, y2 - y1 + 2))
        iy1 = int(round(visual_center_y - icon_h / 2))
        _draw_handdrawn_coin_stack(
            draw, (icon_x1, iy1, icon_x1 + icon_w, iy1 + icon_h), colors, rng
        )
    else:
        icon_h = min(31, max(25, y2 - y1 + 2))
        iy1 = int(round(visual_center_y - icon_h / 2))
        _draw_handdrawn_finish_flag(
            draw, (icon_x1, iy1, icon_x1 + icon_w, iy1 + icon_h), colors, rng
        )


def _torn_note(draw, box, fill, outline, rng, width=2):
    x1, y1, x2, y2 = map(int, box)
    top = [(x1 + 4, y1 + rng.randint(0, 3)), (x1 + (x2-x1)//3, y1 + rng.randint(-3, 3)), (x1 + 2*(x2-x1)//3, y1 + rng.randint(-3, 3)), (x2 - 3, y1 + rng.randint(0, 4))]
    right = [(x2 + rng.randint(-2,2), y1 + (y2-y1)//3), (x2 + rng.randint(-3,2), y1 + 2*(y2-y1)//3)]
    bottom = [(x2 - 4, y2 + rng.randint(-2,2)), (x1 + 2*(x2-x1)//3, y2 + rng.randint(-3,3)), (x1 + (x2-x1)//3, y2 + rng.randint(-3,3)), (x1 + 3, y2 + rng.randint(-2,2))]
    left = [(x1 + rng.randint(-2,2), y1 + 2*(y2-y1)//3), (x1 + rng.randint(-2,3), y1 + (y2-y1)//3)]
    pts = top + right + bottom + left
    draw.polygon(pts, fill=fill)
    _rough_line(draw, pts + [pts[0]], outline, width, rng, 2, 2)
    return pts


def _tape(draw, x, y, w, fill, rng, slant=0):
    pts = [
        (x + rng.randint(-2,2), y + slant),
        (x + w + rng.randint(-2,2), y - slant),
        (x + w - 3 + rng.randint(-2,2), y + 15 - slant),
        (x + 3 + rng.randint(-2,2), y + 15 + slant),
    ]
    draw.polygon(pts, fill=fill)


def _get_kpis(guide, services, limit=4):
    cfg = guide.get("cfg") or {}
    try:
        return services.build_render_kpis((guide.get("kpis") or [])[:limit], cfg)
    except Exception:
        rows = []
        for pair in (guide.get("kpis") or [])[:limit]:
            if isinstance(pair, (list, tuple)) and len(pair) >= 2:
                rows.append({"label": _clean(services, pair[0]), "value": _clean(services, pair[1])})
        return rows


def _draw_section_heading(draw, hf, text, x, y, colors, rng, rcfg, max_w=520):
    mode = _note_mode(rcfg)
    primary = colors.get("primary", "#D74E43")
    dark = colors.get("dark", colors.get("text", "#27313B"))
    text = str(text or "")
    if mode == "red_journal":
        # Cream-journal headings behave like hand-lettered tabs: graphite title on a pale
        # marker swipe, with restrained red underline/arrow accents.
        span = min(max_w - 14, max(150, len(text) * 29 + 26))
        _highlighter(draw, (x - 7, y + 2, x + span, y + 34), colors.get("section_highlighter", "#F7D3CA"), rng)
        hf.left(draw, (x, y, x + max_w, y + 36), text, dark, max_size=24, min_size=15, bold=True, max_lines=1, valign="center")
        line_end = x + min(max_w - 28, span + 18)
        _rough_underline(draw, x + 1, y + 35, line_end, primary, rng, width=2)
        _rough_underline(draw, x + 18, y + 39, max(x + 45, line_end - 25), primary, rng, width=1)
        draw.polygon([(line_end + 2, y + 32), (line_end + 13, y + 36), (line_end + 3, y + 41)], fill=primary)
        return
    if mode == "review_markup":
        # The source document stays black; red is reserved for the reviewer.
        hf.left(draw, (x, y, x + max_w - 64, y + 36), text, dark, max_size=24, min_size=15, bold=True, max_lines=1, valign="center")
        length = min(max_w - 82, max(120, len(text) * 25))
        _rough_underline(draw, x + 2, y + 34, x + length, dark, rng, width=1)
        # Reviewer mark stays visual-only: a red hand-drawn check, no repeated "批" label.
        mark_x = min(x + max_w - 42, x + length + 18)
        my = y + 16
        _rough_line(draw, [(mark_x, my), (mark_x + 7, my + 8), (mark_x + 22, my - 8)], primary, 2, rng, 1, 2)
        return
    hf.left(draw, (x, y, x + max_w, y + 36), text, primary, max_size=24, min_size=15, bold=True, max_lines=1, valign="center")
    length = min(max_w - 20, max(120, len(text) * 27))
    _rough_underline(draw, x + 2, y + 34, x + length, primary, rng, width=2)


def _draw_budget(img, draw, guide, services, hf, colors, box, rng, rcfg):
    x1, y1, x2, y2 = map(int, box)
    mode = _note_mode(rcfg)
    items = _get_kpis(guide, services, 4)
    if not items:
        return
    count = len(items)
    cell_w = (x2 - x1) / count
    for i, it in enumerate(items):
        a = int(x1 + i * cell_w)
        b = int(x1 + (i + 1) * cell_w)
        label = _clean(services, it.get("label"))
        value = _clean(services, it.get("value"))
        icon = it.get("icon")
        dx = rng.randint(-5, 5)
        hf.center(draw, (a + 6 + dx, y1, b - 6 + dx, y1 + 26), label, colors["dark"], max_size=16, min_size=10, bold=True, max_lines=1)
        size = min(46, max(32, int(cell_w * 0.24)))
        ix = int((a + b - size) / 2 + dx)
        iy = y1 + 31 + rng.randint(0, 5)
        if icon and Path(icon).exists():
            _draw_notebook_icon(img, Path(icon), (ix, iy, ix + size, iy + size), rcfg, rng)
        else:
            _scribble_circle(draw, (ix, iy, ix + size, iy + size), colors["dark"], rng, width=1, passes=1)
            hf.center(draw, (ix, iy, ix + size, iy + size), "?", colors["dark"], max_size=16, min_size=10, bold=True, max_lines=1)
        value_y = iy + size + 4
        value_color = colors["text"]
        hf.center(draw, (a + 4 + dx, value_y, b - 4 + dx, y2 - 4), value, value_color, max_size=25, min_size=16, bold=True, max_lines=1)
        if mode == "review_markup":
            # reviewer circles the budget number, source label/icon stay black.
            _scribble_focus_loop(draw, (a + 20 + dx, value_y - 2, b - 20 + dx, y2 - 1), colors["primary"], rng, width=1, passes=1)
        else:
            _rough_underline(draw, a + 25 + dx, y2 - 5 + rng.randint(-1,1), b - 25 + dx, colors.get("line_dark", "#8BA7B8"), rng, width=1)


def _reward_leaf_count(node):
    """Count visible item leaves in a parsed reward-expression node."""
    if not isinstance(node, dict):
        return 0
    typ = node.get("type", "item")
    if typ == "item":
        return 1
    if typ == "bundle":
        return sum(_reward_leaf_count(x) for x in (node.get("items") or []))
    if typ == "choice":
        return sum(_reward_leaf_count(x) for x in (node.get("options") or []))
    return 0


def _reward_expression_tree(guide, services):
    """Build the handwritten theme's visual reward expression.

    The engine parser already preserves parenthetical bundles.  Its
    ``build_reward_display_units`` helper additionally merges linear ``A 或 B``
    nodes into a choice while keeping the historical rule that remaining
    top-level units are additive.  Turning multiple display units into one
    top-level bundle therefore gives us a stable visual grammar:

      item              -> item sticker
      bundle            -> +
      choice            -> 或
      nested expression -> hand-drawn grouping loop

    No parser behavior is reimplemented here, so handwritten notes stay in
    sync with the classic renderer and future engine parser fixes.
    """
    raw = guide.get("reward_items") or []
    if not raw:
        return None
    units = services.build_reward_display_units(raw)
    if not units:
        return None
    if len(units) == 1:
        return units[0]
    return {"type": "bundle", "items": units, "_visual_root": True}


def _reward_group_extra(node, nested=False):
    """Width overhead independent of item-cell width."""
    if not isinstance(node, dict):
        return 0
    typ = node.get("type", "item")
    if typ == "item":
        return 0
    children = (node.get("items") or []) if typ == "bundle" else (node.get("options") or [])
    # Nested compound expressions receive a lasso/grouping loop.  Reserve a
    # little breathing room so the line never crosses stickers or labels.
    pad = 18 if nested else 0
    return pad + sum(_reward_group_extra(ch, nested=(isinstance(ch, dict) and ch.get("type", "item") != "item")) for ch in children)


def _reward_measure(node, item_w, plus_w, or_w, nested=False):
    if not isinstance(node, dict):
        return 0.0
    typ = node.get("type", "item")
    if typ == "item":
        return float(item_w)
    if typ == "bundle":
        children = list(node.get("items") or [])
        op_w = plus_w
    elif typ == "choice":
        children = list(node.get("options") or [])
        op_w = or_w
    else:
        return float(item_w)
    if not children:
        return float(item_w)
    inner = 0.0
    for i, child in enumerate(children):
        child_compound = isinstance(child, dict) and child.get("type", "item") != "item"
        inner += _reward_measure(child, item_w, plus_w, or_w, nested=child_compound)
        if i:
            inner += op_w
    return inner + (18 if nested else 0)


def _reward_layout_sizes(tree, available_w):
    """Pick one shared item width so every reward leaf stays visually equal."""
    leaves = max(1, _reward_leaf_count(tree))
    # Keep the visual language readable instead of shrinking one branch only.
    # Five- or six-item expressions simply use uniformly smaller stickers.
    target = 146 if leaves <= 4 else (122 if leaves == 5 else 102)
    min_w = 68
    for item_w in range(target, min_w - 1, -2):
        plus_w = max(29, min(42, int(round(item_w * 0.27))))
        or_w = max(48, min(66, int(round(item_w * 0.43))))
        if _reward_measure(tree, item_w, plus_w, or_w, nested=False) <= available_w:
            return item_w, plus_w, or_w
    item_w = min_w
    return item_w, 28, 46


def _draw_reward_group_loop(draw, box, color, rng, width=2):
    """Loose pencil lasso used as a visual parenthesis around a compound group."""
    import math
    x1, y1, x2, y2 = map(int, box)
    if x2 - x1 < 20 or y2 - y1 < 20:
        return
    cx, cy = (x1 + x2) / 2.0, (y1 + y2) / 2.0
    rx = max(10.0, (x2 - x1) / 2.0)
    ry = max(10.0, (y2 - y1) / 2.0)
    for p in range(2):
        pts = []
        # Almost closed rather than geometrically perfect: it reads like a
        # player circled a group with a pencil, not like a UI container.
        start = -7 + rng.randint(-3, 3)
        end = 354 + rng.randint(-2, 4)
        for i in range(68):
            t = math.radians(start + (end - start) * i / 67.0)
            wobble = math.sin(t * 3.0 + p * 0.9) * 1.4
            jx = rng.uniform(-1.6, 1.6)
            jy = rng.uniform(-1.3, 1.3)
            pts.append((
                int(cx + (rx + wobble) * math.cos(t) + jx + p * 0.4),
                int(cy + (ry + wobble * 0.6) * math.sin(t) + jy - p * 0.3),
            ))
        draw.line(pts, fill=color, width=max(1, width - (1 if p else 0)), joint="curve")


def _draw_reward_operator(draw, hf, op, box, colors, rng):
    x1, y1, x2, y2 = map(int, box)
    cy = (y1 + y2) // 2
    if op == "或":
        # Choice is the important semantic fork.  Give it a small hand-marker
        # swatch and side strokes so it can never be mistaken for ordinary text.
        hx1 = x1 + 5
        hx2 = x2 - 5
        hy1 = cy - 18
        hy2 = cy + 18
        _highlighter(draw, (hx1, hy1, hx2, hy2), colors.get("section_highlighter", "#EFD9C9"), rng)
        _rough_line(draw, [(x1 + 1, cy), (hx1 - 2, cy + rng.randint(-1, 1))], colors["primary"], 2, rng, 1, 1)
        _rough_line(draw, [(hx2 + 2, cy + rng.randint(-1, 1)), (x2 - 1, cy)], colors["primary"], 2, rng, 1, 1)
        hf.center(draw, (hx1, hy1 - 1, hx2, hy2 + 1), "或", colors["primary"], max_size=21, min_size=16, bold=True, max_lines=1)
    else:
        # Plus is intentionally simpler/weaker than the choice marker.
        hf.center(draw, (x1, cy - 20, x2, cy + 20), "+", colors.get("dark", colors["text"]), max_size=24, min_size=18, bold=True, max_lines=1)


def _draw_reward_item_node(img, draw, guide, services, hf, colors, node, box, rng, rcfg):
    x1, y1, x2, y2 = map(int, box)
    cfg = guide.get("cfg") or {}
    catalog = services.build_item_catalog(cfg)
    meta = services.find_item_meta(node.get("name", ""), catalog) or {}
    icon_path = services.resolve_path(cfg, meta.get("icon") or node.get("icon"))

    cell_w = max(1, x2 - x1)
    cell_h = max(1, y2 - y1)
    # Preserve room for two lines of item name.  Sticker size scales uniformly
    # with the shared item-cell width picked for the whole expression.
    size = max(34, min(58, int(round(cell_w * 0.43)), cell_h - 48))
    ix = int((x1 + x2 - size) / 2 + rng.randint(-2, 2))
    iy = y1 + 7 + rng.randint(-1, 2)
    if icon_path and Path(icon_path).exists():
        reward_art = _compose_reward_art(guide, services, node, meta)
        if reward_art is not None:
            _draw_notebook_art(img, reward_art, (ix, iy, ix + size, iy + size), rcfg, rng)
        else:
            _draw_notebook_icon(img, Path(icon_path), (ix, iy, ix + size, iy + size), rcfg, rng)
    else:
        _scribble_circle(draw, (ix, iy, ix + size, iy + size), colors["dark"], rng, width=1, passes=1)
        hf.center(draw, (ix, iy, ix + size, iy + size), "?", colors["dark"], max_size=15, min_size=10, bold=True, max_lines=1)

    qty = _clean(services, node.get("qty"))
    label = _clean(services, node.get("name")) + ((" ×" + qty) if qty else "")
    label_top = min(y2 - 35, iy + size + 4)
    hf.center(
        draw, (x1 + 1, label_top, x2 - 1, y2 - 3), label, colors["text"],
        max_size=13 if cell_w >= 92 else 12,
        min_size=8, bold=True, max_lines=2, line_gap=1,
    )


def _draw_reward_expression_node(img, draw, guide, services, hf, colors, node, box, rng, rcfg,
                                 item_w, plus_w, or_w, nested=False):
    """Recursively render one item/bundle/choice expression."""
    x1, y1, x2, y2 = map(int, box)
    typ = (node or {}).get("type", "item") if isinstance(node, dict) else "item"
    if typ == "item":
        _draw_reward_item_node(img, draw, guide, services, hf, colors, node or {}, box, rng, rcfg)
        return

    if typ == "bundle":
        children = list(node.get("items") or [])
        op = "+"
        op_w = plus_w
    elif typ == "choice":
        children = list(node.get("options") or [])
        op = "或"
        op_w = or_w
    else:
        _draw_reward_item_node(img, draw, guide, services, hf, colors, node or {}, box, rng, rcfg)
        return

    if not children:
        return

    pad_x = 9 if nested else 0
    inner_x1, inner_x2 = x1 + pad_x, x2 - pad_x
    child_widths = []
    for child in children:
        comp = isinstance(child, dict) and child.get("type", "item") != "item"
        child_widths.append(_reward_measure(child, item_w, plus_w, or_w, nested=comp))
    total_children = sum(child_widths) + op_w * max(0, len(children) - 1)
    cursor = inner_x1 + max(0.0, (inner_x2 - inner_x1 - total_children) / 2.0)

    # Operators sit around the sticker center rather than the text baseline.
    op_y1 = y1 + 8
    op_y2 = min(y2 - 34, y1 + 76)
    if op_y2 <= op_y1:
        op_y2 = y2 - 4

    for i, (child, cw) in enumerate(zip(children, child_widths)):
        c1 = int(round(cursor))
        c2 = int(round(cursor + cw))
        child_compound = isinstance(child, dict) and child.get("type", "item") != "item"
        _draw_reward_expression_node(
            img, draw, guide, services, hf, colors, child, (c1, y1, c2, y2), rng, rcfg,
            item_w, plus_w, or_w, nested=child_compound,
        )
        cursor += cw
        if i < len(children) - 1:
            o1 = int(round(cursor))
            o2 = int(round(cursor + op_w))
            _draw_reward_operator(draw, hf, op, (o1, op_y1, o2, op_y2), colors, rng)
            cursor += op_w

    if nested:
        # The group loop acts as the handwritten equivalent of parentheses.
        loop_color = colors.get("dark", colors["text"])
        _draw_reward_group_loop(draw, (x1 + 2, y1 + 2, x2 - 2, y2 - 2), loop_color, rng, width=2)


def _draw_rewards(img, draw, guide, services, rtools, hf, colors, box, rng, rcfg):
    x1, y1, x2, y2 = map(int, box)
    mode = _note_mode(rcfg)
    if mode == "review_markup":
        _torn_note(draw, box, colors.get("paper", "#FFFEFA"), colors.get("dark", "#30363A"), rng, width=1)
        # red proofing corners distinguish the review sheet from a sticky note
        _rough_line(draw, [(x1 + 3, y1 + 28), (x1 + 3, y1 + 3), (x1 + 30, y1 + 3)], colors["primary"], 2, rng, 1, 2)
        _rough_line(draw, [(x2 - 30, y2 - 3), (x2 - 3, y2 - 3), (x2 - 3, y2 - 28)], colors["primary"], 2, rng, 1, 2)
    else:
        _torn_note(draw, box, colors.get("reward_note", "#FFF1A8"), "#C5A84A", rng, width=2)
        _tape(draw, x1 + 40, y1 - 8, 70, colors.get("tape", "#EAD9B4"), rng, slant=2)
        _tape(draw, x2 - 118, y1 - 5, 62, colors.get("tape", "#EAD9B4"), rng, slant=-1)

    tree = _reward_expression_tree(guide, services)
    if not tree:
        hf.left(draw, (x1 + 22, y1 + 18, x2 - 22, y2 - 14), rtools.reward_summary(guide), colors["text"], max_size=18, min_size=11, max_lines=4, valign="center")
        return

    inner = (x1 + 16, y1 + 10, x2 - 16, y2 - 8)
    available_w = inner[2] - inner[0]
    item_w, plus_w, or_w = _reward_layout_sizes(tree, available_w)
    expression_w = _reward_measure(tree, item_w, plus_w, or_w, nested=False)
    ex1 = int(inner[0] + max(0, (available_w - expression_w) / 2))
    ex2 = int(min(inner[2], ex1 + expression_w))
    _draw_reward_expression_node(
        img, draw, guide, services, hf, colors, tree,
        (ex1, inner[1], ex2, inner[3]), rng, rcfg,
        item_w, plus_w, or_w, nested=False,
    )

def _step_lines(action):
    text = str(action or "").replace("\r", "").strip()
    if not text:
        return []
    parts = [x.strip() for x in text.split("\n") if x.strip()]
    if len(parts) <= 1 and ("；" in text or ";" in text):
        parts = [x.strip() for x in re.split(r"[；;]", text) if x.strip()]
    clean_parts = []
    lead_re = re.compile(r"^\s*(?:[①②③④⑤⑥⑦⑧⑨⑩]|\(?\d{1,2}\)?[\.、\)）:]?)\s*")
    for p in parts[:5]:
        clean_parts.append(lead_re.sub("", p).strip() or p)
    return clean_parts


def _draw_steps(draw, hf, action, box, colors, rng, rcfg):
    x1, y1, x2, y2 = map(int, box)
    steps = _step_lines(action)
    mode = _note_mode(rcfg)
    if not steps:
        hf.left(draw, box, "今天没有额外操作", colors["text"], max_size=16, min_size=11, max_lines=2, valign="center")
        return

    available = max(1, y2 - y1)
    row_h = max(30, int(available / len(steps)))
    for i, text in enumerate(steps):
        sy1 = y1 + i * row_h
        sy2 = y2 if i == len(steps) - 1 else min(y2, sy1 + row_h)
        if mode == "review_markup":
            # Black source checklist + a separate red grading/check layer.
            box_s = 19
            cy = int(sy1 + max(3, (sy2 - sy1 - box_s) / 2))
            bx = x1 + 2
            _rough_line(draw, [(bx, cy), (bx + box_s, cy), (bx + box_s, cy + box_s), (bx, cy + box_s), (bx, cy)], colors.get("dark", colors["text"]), 1, rng, 1, 1)
            # reviewer check sits slightly outside the black checkbox
            _rough_line(draw, [(bx + 3, cy + 9), (bx + 8, cy + 15), (bx + 20, cy + 1)], colors["primary"], 2, rng, 1, 2)
            hf.left(draw, (x1 + 34, sy1 + 1, x2 - 28, sy2 - 1), text, colors["text"], max_size=17, min_size=13, max_lines=2, line_gap=2, valign="center")
            # occasional short red editorial underline, never on every line
            if i % 2 == 0:
                ux1 = x1 + 38 + rng.randint(4, 16)
                ux2 = min(x2 - 34, ux1 + rng.randint(90, 170))
                _rough_underline(draw, ux1, sy2 - 4, ux2, colors["primary"], rng, width=1)
        elif mode == "red_journal":
            # Graphite is the writing layer; red is reserved for quick action arrows
            # rather than being used for every sentence.
            ay = int((sy1 + sy2) / 2)
            _rough_line(draw, [(x1 + 1, ay), (x1 + 21, ay + rng.randint(-2, 2))], colors["primary"], 2, rng, 2, 2)
            draw.polygon([(x1 + 18, ay - 6), (x1 + 29, ay), (x1 + 18, ay + 6)], fill=colors["primary"])
            hf.left(draw, (x1 + 38, sy1 + 1, x2, sy2 - 1), text, colors["text"], max_size=17, min_size=13, max_lines=2, line_gap=2, valign="center")
        else:
            circle_size = 25
            cy = int(sy1 + max(2, (sy2 - sy1 - circle_size) / 2))
            circle = (x1, cy, x1 + circle_size, cy + circle_size)
            _scribble_circle(draw, circle, colors["primary"], rng, width=2, passes=2)
            hf.center(draw, circle, str(i + 1), colors["primary"], max_size=13, min_size=10, bold=True, max_lines=1)
            hf.left(draw, (x1 + 35, sy1 + 1, x2, sy2 - 1), text, colors["text"], max_size=17, min_size=13, max_lines=2, line_gap=2, valign="center")


def _allocate_day_heights(days, available_height, gap=5):
    """Allocate more vertical space to days with more written steps.

    Three-step days remain compact; four/five-step days automatically grow.
    If every day is unusually long, all rows scale down proportionally but
    preserve a practical minimum.
    """
    n = len(days)
    if n <= 0:
        return []
    usable = max(1, int(available_height - gap * max(0, n - 1)))
    desired = []
    minimum = []
    for info in days:
        step_count = max(1, len(_step_lines(info.get("action") or "")))
        # Header/sticky need ~60 px; each written step gets ~29 px.
        h = 92 + step_count * 29
        if step_count >= 5:
            h += 10
        desired.append(max(148, h))
        minimum.append(142 if step_count <= 3 else (158 if step_count == 4 else 176))

    total = sum(desired)
    if total <= usable:
        extra = usable - total
        # Give leftover room to longer days first, then distribute the rest.
        weights = [max(1, len(_step_lines(info.get("action") or ""))) for info in days]
        wsum = sum(weights) or n
        add = [int(extra * w / wsum) for w in weights]
        rem = extra - sum(add)
        for i in range(rem):
            add[i % n] += 1
        return [desired[i] + add[i] for i in range(n)]

    # Need to shrink. First consume the flexible amount above each minimum.
    heights = list(desired)
    overflow = total - usable
    caps = [max(0, heights[i] - minimum[i]) for i in range(n)]
    cap_total = sum(caps)
    if cap_total > 0:
        shrink = [min(caps[i], int(overflow * caps[i] / cap_total)) for i in range(n)]
        rem = overflow - sum(shrink)
        idx = 0
        while rem > 0 and idx < n * 20:
            i = idx % n
            if shrink[i] < caps[i]:
                shrink[i] += 1
                rem -= 1
            idx += 1
        heights = [heights[i] - shrink[i] for i in range(n)]
        overflow = max(0, sum(heights) - usable)

    if overflow > 0:
        # Last resort: scale all rows, still keeping the five-step day larger.
        scale = usable / max(1, sum(heights))
        heights = [max(126, int(h * scale)) for h in heights]
        diff = usable - sum(heights)
        i = 0
        while diff != 0 and i < n * 40:
            k = i % n
            if diff > 0:
                heights[k] += 1
                diff -= 1
            elif heights[k] > 126:
                heights[k] -= 1
                diff += 1
            i += 1
    return heights


def _draw_metric_sticky(img, draw, guide, info, services, hf, colors, box, fill, rng, rcfg):
    x1, y1, x2, y2 = map(int, box)
    mode = _note_mode(rcfg)
    if mode == "review_markup":
        # A clipped review slip: white sheet, black source border, red review tab.
        _torn_note(draw, box, colors.get("paper", "#FFFEFA"), colors.get("dark", "#30363A"), rng, width=1)
        _highlighter(draw, (x1 + 6, y1 + 5, x2 - 6, y1 + 30), colors.get("review_highlighter", "#FFD7D2"), rng)
        hf.left(draw, (x1 + 11, y1 + 6, x2 - 8, y1 + 31), "剩余和期望", colors["dark"], max_size=13, min_size=9, bold=True, max_lines=1, valign="center")
        # red paper-clip line on top edge
        _rough_line(draw, [(x2 - 40, y1 - 3), (x2 - 19, y1 + 4), (x2 - 31, y1 + 15)], colors["primary"], 2, rng, 1, 1)
        top = y1 + 34
    else:
        _torn_note(draw, box, fill, "#C1AF69", rng, width=1)
        _tape(draw, x1 + (x2-x1)//2 - 28, y1 - 6, 58, colors.get("tape", "#EAD9B4"), rng, slant=rng.choice([-2,-1,1,2]))
        label = "补给速记" if mode == "red_journal" else "剩余和期望"
        hf.left(draw, (x1 + 12, y1 + 8, x2 - 8, y1 + 31), label, colors["dark"], max_size=14, min_size=10, bold=True, max_lines=1, valign="center")
        top = y1 + 34
    items = list(info.get("metric_items") or [])[:4]
    if not items:
        hf.center(draw, (x1 + 10, top, x2 - 10, y2 - 8), "—", colors["text"], max_size=18, min_size=12, max_lines=1)
        return
    cfg = guide.get("cfg") or {}
    row_h = max(23, int((y2 - top - 7) / len(items)))
    for i, item in enumerate(items):
        ry1 = top + i * row_h
        ry2 = min(y2 - 4, ry1 + row_h)
        icon = services.config_day_icon(cfg, item)
        size = min(21, max(15, row_h - 4))
        ix = x1 + 10
        iy = int(ry1 + (row_h - size) / 2)
        if icon and Path(icon).exists():
            _draw_notebook_icon(img, Path(icon), (ix, iy, ix + size, iy + size), rcfg, rng)
        label = _clean(services, item.get("label"))
        value = _clean(services, item.get("value"))
        hf.left(draw, (ix + size + 6, ry1, x2 - 7, ry2), (label + "  " + value).strip(), colors["text"], max_size=12, min_size=8, bold=True, max_lines=1, valign="center")


def _draw_day(img, draw, guide, info, index, services, hf, colors, box, sticky_fill, rng, rcfg):
    x1, y1, x2, y2 = map(int, box)
    mode = _note_mode(rcfg)
    # no enclosing card: keep the paper texture visible
    marker_x = x1 + 7 + rng.randint(-2, 3)
    marker_y = y1 + 10 + rng.randint(-2, 3)
    marker_box = (marker_x, marker_y, marker_x + 48, marker_y + 45)
    if mode == "red_journal":
        # Filled red action marker + cream label, unlike the review稿's black source marker.
        draw.ellipse(marker_box, fill=colors.get("marker_fill", "#B74438"))
        _scribble_circle(draw, marker_box, colors["primary"], rng, width=2, passes=2)
        hf.center(draw, marker_box, f"D{index + 1}", colors.get("paper", "#FFF8ED"), max_size=16, min_size=11, bold=True, max_lines=1)
    elif mode == "review_markup":
        _scribble_circle(draw, marker_box, colors.get("dark", colors["text"]), rng, width=2, passes=1)
        hf.center(draw, marker_box, f"D{index + 1}", colors.get("dark", colors["text"]), max_size=16, min_size=11, bold=True, max_lines=1)
        # separate red reviewer tick outside the black day marker
        _rough_line(draw, [(marker_box[2] - 3, marker_box[1] + 4), (marker_box[2] + 5, marker_box[1] + 11), (marker_box[2] + 16, marker_box[1] - 5)], colors["primary"], 2, rng, 1, 2)
    else:
        _scribble_circle(draw, marker_box, colors["primary"], rng, width=2, passes=2)
        hf.center(draw, marker_box, f"D{index + 1}", colors["primary"], max_size=16, min_size=11, bold=True, max_lines=1)

    content_x = x1 + 70 + rng.randint(-2, 5)
    sticky_w = 220
    sticky_x2 = x2 - rng.randint(0, 8)
    sticky_x1 = sticky_x2 - sticky_w
    text_x2 = sticky_x1 - 22

    target = _clean(services, info.get("target"))
    special = _clean(services, info.get("special_label"))
    target_text = ("目标：" + target) if target else "今日计划"
    highlight_w = min(text_x2 - content_x, max(180, len(target_text) * 28 + 32))
    marker_fill = colors.get("special_highlighter", "#FFD0D8") if special else colors.get("day_highlighter", "#D9EEF8")
    if mode == "review_markup":
        # review稿 keeps source headings un-highlighted; the red layer annotates it.
        hf.left(draw, (content_x, y1 + 7, text_x2, y1 + 42), target_text, colors["dark"], max_size=20, min_size=13, bold=True, max_lines=1, valign="center")
        _rough_underline(draw, content_x, y1 + 39, min(text_x2 - 8, content_x + highlight_w), colors.get("dark", colors["text"]), rng, width=1)
    else:
        _highlighter(draw, (content_x - 4, y1 + 9, content_x + highlight_w, y1 + 40), marker_fill, rng)
        hf.left(draw, (content_x, y1 + 7, text_x2, y1 + 42), target_text, colors["dark"], max_size=20, min_size=13, bold=True, max_lines=1, valign="center")
    if special:
        special_text = ("重点｜" + special) if mode == "review_markup" else ("★" + special)
        _draw_special_day_label(
            draw, hf, special_text, special,
            (content_x + highlight_w + 6, y1 + 10, text_x2, y1 + 38),
            colors, rng,
        )

    _draw_steps(draw, hf, info.get("action") or "", (content_x, y1 + 48, text_x2, y2 - 15), colors, rng, rcfg)

    sticky_y1 = y1 + 17 + rng.randint(-4, 7)
    sticky_y2 = min(y2 - 9, sticky_y1 + max(108, (y2 - y1) - 32))
    _draw_metric_sticky(img, draw, guide, info, services, hf, colors, (sticky_x1, sticky_y1, sticky_x2, sticky_y2), sticky_fill, rng, rcfg)

    # Special days get a rough red-pen focus loop around the entire day's note.
    # It is intentionally uneven/open rather than a clean geometric ellipse.
    if special and bool(rcfg.get("circle_special_days", True)):
        circle_color = rcfg.get("special_day_circle_color") or colors.get("primary", "#D74E43")
        try:
            circle_width = max(1, int(rcfg.get("special_day_circle_width", 3)))
        except Exception:
            circle_width = 3
        step_circle_x1 = max(x1 + 54, content_x - 16)
        step_circle_x2 = min(text_x2 + 10, sticky_x1 - 10)
        step_circle_y1 = y1 + 43
        step_circle_y2 = y2 - 13
        if mode == "review_markup":
            # A review bracket is much more like margin correction than a UI circle.
            bx = step_circle_x2 - 2
            _rough_line(draw, [(bx, step_circle_y1), (bx + 12, step_circle_y1 + 7), (bx + 7, step_circle_y2 - 8), (bx - 2, step_circle_y2)], circle_color, circle_width, rng, 2, 2)
            hf.left(draw, (bx + 16, step_circle_y1, sticky_x1 - 4, min(step_circle_y2, step_circle_y1 + 34)), "重点", circle_color, max_size=12, min_size=9, bold=True, max_lines=1, valign="center")
        elif step_circle_x2 > step_circle_x1 + 40 and step_circle_y2 > step_circle_y1 + 30:
            _scribble_focus_loop(
                draw,
                (step_circle_x1, step_circle_y1, step_circle_x2, step_circle_y2),
                circle_color,
                rng,
                width=circle_width,
                passes=2,
            )

    # a loose pencil separator, deliberately not full width
    sep_y = y2 - 5 + rng.randint(-1, 2)
    _rough_line(draw, [(content_x - 18, sep_y), (content_x + 210, sep_y + rng.randint(-2,2)), (x2 - 28, sep_y + rng.randint(-2,2))], colors.get("separator", "#C6D2D8"), 1, rng, 2, 1)
    return marker_box


def _connect_day_markers(draw, marker_boxes, color, rng):
    for i in range(len(marker_boxes) - 1):
        a = marker_boxes[i]
        b = marker_boxes[i + 1]
        x1 = (a[0] + a[2]) // 2
        y1 = a[3] + 5
        x2 = (b[0] + b[2]) // 2
        y2 = b[1] - 5
        mid = (y1 + y2) // 2
        pts = [(x1, y1), (x1 + rng.randint(-7,7), mid - 5), (x2 + rng.randint(-6,6), mid + 6), (x2, y2 - 6)]
        _rough_line(draw, pts, color, 2, rng, 3, 1)
        draw.polygon([(x2 - 5, y2 - 12), (x2 + 6, y2 - 10), (x2, y2)], fill=color)


def render(guide, out_path: Path, services):
    W, H = services.W, services.H
    rtools = SharedRendererTools(services)
    started = time.perf_counter()
    rcfg = _renderer_cfg(guide)
    colors = rtools.colors(guide, {
        "background": "#F3EBDD",
        "text": "#27313B",
        "primary": "#D74E43",
        "dark": "#315B72",
        "light": "#FFE98E",
        "paper": "#FFFDF8",
        "line": "#C7DDE8",
        "line_dark": "#93AAB6",
        "margin": "#E2A0A0",
        "separator": "#CBD4D8",
        "title_highlighter": "#FFD9C8",
        "day_highlighter": "#D9EEF8",
        "special_highlighter": "#FFD0D8",
        "reward_note": "#FFF0A7",
        "tape": "#E8D7B1",
    })
    font_path = _resolve_font_path(guide, services, rcfg)
    font_weight = rcfg.get("font_weight", rcfg.get("font_stroke_width", 0))
    font_tracking = rcfg.get("font_tracking", 1 if int(font_weight or 0) > 0 else 0)
    font_scale = rcfg.get("font_scale", 1.0)
    hf = _NotebookFonts(services, font_path, font_weight, font_tracking, font_scale)
    rng = _seed_rng(guide, "handwritten-notebook-v354")

    img = Image.new("RGBA", (W, H), colors["background"])
    d = ImageDraw.Draw(img)
    paper = colors.get("paper", "#FFFDF8")
    d.rectangle((42, 28, W - 42, H - 62), fill=paper, outline="#D7CFC0", width=1)

    retro_print = _print_effect(rcfg) == "retro_print"
    note_mode = _note_mode(rcfg)
    try:
        retro_jitter = max(1, min(8, int(rcfg.get("retro_line_jitter", 3))))
    except Exception:
        retro_jitter = 3

    # Paper language is variant-specific. The two modern handwriting variants
    # deliberately no longer share the same blue-line notebook shell.
    if note_mode == "red_journal":
        # Warm dot-grid sketchbook: casual planning, fewer school-notebook cues.
        dot = colors.get("line", "#D9C8B6")
        for yy in range(96, H - 90, 38):
            for xx in range(72, W - 70, 38):
                r = 1 if (xx // 38 + yy // 38) % 3 else 2
                d.ellipse((xx-r, yy-r, xx+r, yy+r), fill=dot)
        # loose red frame/margin strokes rather than punched holes
        _rough_line(d, [(112, 62), (109 + rng.randint(-2,2), H - 92)], colors.get("margin", colors["primary"]), 2, rng, 2, 2)
        _rough_line(d, [(W - 96, 66), (W - 91, H - 112)], colors.get("line_dark", "#C9B8A8"), 1, rng, 2, 1)
        # scraps of masking tape make the page feel like a field notebook spread
        _tape(d, 58, 38, 78, colors.get("tape", "#E6D4AF"), rng, slant=2)
        _tape(d, W - 154, 45, 74, colors.get("tape", "#E6D4AF"), rng, slant=-2)
    else:
        # Clean campus/review notebook and legacy retro print use ruled paper.
        for yy in range(90, H - 82, 52):
            if retro_print:
                pts = [
                    (61, yy + rng.randint(-1, 1)),
                    (int(W * 0.34), yy + rng.randint(-retro_jitter, retro_jitter)),
                    (int(W * 0.67), yy + rng.randint(-retro_jitter, retro_jitter)),
                    (W - 61, yy + rng.randint(-1, 1)),
                ]
                _rough_line(d, pts, colors.get("line", "#C7DDE8"), 1, rng, retro_jitter, 1)
            else:
                _rough_line(d, [(61, yy), (W - 61, yy + rng.randint(-1,1))], colors.get("line", "#C7DDE8"), 1, rng, 1, 1)
        if retro_print:
            _rough_line(d, [(129, 52), (128 + rng.randint(-2,2), H//2), (128, H - 88)], colors.get("margin", "#E2A0A0"), 2, rng, retro_jitter, 2)
        else:
            _rough_line(d, [(129, 52), (128, H - 88)], colors.get("margin", "#E2A0A0"), 2, rng, 1, 2)
        for yy in range(96, H - 100, 158):
            d.ellipse((62, yy - 8, 78, yy + 8), fill="#DDD7CB", outline="#AAA49A")
            d.ellipse((64, yy - 6, 76, yy + 6), fill=colors["background"])
    _draw_retro_paper_wear(img, colors, rcfg, _seed_rng(guide, "retro-paper-wear"))
    d = ImageDraw.Draw(img)

    # Header identity differs strongly between the graphite field journal and review稿.
    if note_mode == "red_journal":
        _highlighter(d, (150, 63, W - 112, 140), colors.get("title_highlighter", "#F3C3B8"), rng)
        hf.left(d, (163, 61, W - 124, 143), guide.get("title") or "活动攻略", colors["dark"], max_size=42, min_size=25, bold=True, max_lines=2, line_gap=1, valign="center")
        # little field-note label and arrow add an informal planner feel
        hf.left(d, (W - 252, 141, W - 105, 174), "★ 今日作战稿", colors["primary"], max_size=13, min_size=9, bold=True, max_lines=1, valign="center")
    elif note_mode == "review_markup":
        hf.left(d, (163, 63, W - 245, 143), guide.get("title") or "活动攻略", colors["text"], max_size=40, min_size=24, bold=True, max_lines=2, line_gap=1, valign="center")
        _rough_underline(d, 163, 140, W - 250, colors.get("dark", colors["text"]), rng, width=2)
        # A single traditional reviewer stamp: only the character "阅".
        sx1, sy1, sx2, sy2 = W - 204, 66, W - 126, 144
        for inset in (0, 5):
            _rough_line(d, [(sx1 + inset, sy1 + inset), (sx2 - inset, sy1 + inset),
                            (sx2 - inset, sy2 - inset), (sx1 + inset, sy2 - inset),
                            (sx1 + inset, sy1 + inset)], colors["primary"], 2 if inset == 0 else 1, rng, 1, 2)
        hf.center(d, (sx1 + 8, sy1 + 5, sx2 - 8, sy2 - 5), "阅", colors["primary"], max_size=31, min_size=21, bold=True, max_lines=1)
    else:
        _highlighter(d, (156, 65, W - 110, 139), colors.get("title_highlighter", "#FFD9C8"), rng)
        hf.left(d, (163, 63, W - 124, 143), guide.get("title") or "活动攻略", colors["text"], max_size=42, min_size=25, bold=True, max_lines=2, line_gap=1, valign="center")
    author_end_x = _draw_author_signature(img, d, guide, services, rtools, hf, colors, rcfg, 164, 150, W - 110)
    _rough_underline(d, 164, 181, min(W - 160, max(164 + 220, author_end_x)), colors["dark"], rng, width=1)

    # 1. budget, free-floating items on the page (no cards)
    _draw_section_heading(d, hf, rcfg.get("budget_title") or "① 先算预算", 158, 201, colors, rng, rcfg)
    _draw_budget(img, d, guide, services, hf, colors, (160, 241, W - 88, 350), rng, rcfg)

    # small handwritten arrow into reward note
    _rough_line(d, [(144, 345), (150, 371), (143, 390)], colors["primary"], 2, rng, 3, 1)
    d.polygon([(137, 383), (149, 391), (141, 397)], fill=colors["primary"])

    # 2. rewards as one taped note
    _draw_section_heading(d, hf, rcfg.get("reward_title") or "② 想换这些", 158, 365, colors, rng, rcfg)
    _draw_rewards(img, d, guide, services, rtools, hf, colors, (164, 407, W - 90, 548), rng, rcfg)

    # 3. daily notebook timeline
    _draw_section_heading(d, hf, rcfg.get("days_title") or "③ 每天照着做", 158, 570, colors, rng, rcfg)
    days = list(guide.get("days") or [])
    day_top = 613
    tips_top = H - 320
    day_bottom = tips_top - 30
    day_gap = 5
    day_heights = _allocate_day_heights(days, day_bottom - day_top, day_gap)
    sticky_palette = ["#FFF2A7", "#DFF0FA", "#E7F2CA", "#FFE0DA", "#E9E0F7", "#FFECCA", "#DDF1E4"]
    marker_boxes = []
    cursor_y = day_top
    for i, info in enumerate(days):
        row_h = day_heights[i] if i < len(day_heights) else 150
        y1 = cursor_y
        y2 = min(day_bottom, y1 + row_h)
        day_rng = _seed_rng(guide, f"day-{i}")
        marker = _draw_day(img, d, guide, info, i, services, hf, colors, (151, y1, W - 86, y2), sticky_palette[i % len(sticky_palette)], day_rng, rcfg)
        marker_boxes.append(marker)
        cursor_y = y2 + day_gap
    _connect_day_markers(d, marker_boxes, colors.get("dark", colors["text"]) if note_mode == "review_markup" else colors["primary"], _seed_rng(guide, "day-arrows"))

    # 4. final warning: every warning gets its own oversized red exclamation.
    tip_rng = _seed_rng(guide, "tips")
    _draw_section_heading(d, hf, rcfg.get("tip_title") or "④ 最后提醒", 158, tips_top, colors, tip_rng, rcfg)
    risks = rtools.risk_items(guide)
    tips = risks[:5] if risks else ["到档就停", "留资源给后面", "别手滑多点一次"]
    body_y = tips_top + 46
    body_bottom = H - 92
    available_tip_h = max(80, body_bottom - body_y)
    tip_row_h = max(36, int(available_tip_h / max(1, len(tips))))
    for i, text in enumerate(tips):
        ry1 = body_y + i * tip_row_h
        ry2 = body_bottom if i == len(tips) - 1 else min(body_bottom, ry1 + tip_row_h)
        if note_mode == "review_markup":
            # Source warning remains black, reviewer adds margin correction marks.
            mark = "×" if i % 3 == 1 else "!"
            hf.center(d, (166, ry1 + 1, 214, ry2 - 1), mark, colors["primary"], max_size=31, min_size=23, bold=True, max_lines=1)
            hf.left(d, (226, ry1 + 1, W - 165, ry2 - 2), text, colors["text"], max_size=18, min_size=13, bold=True, max_lines=2, line_gap=2, valign="center")
            hf.left(d, (W - 158, ry1 + 1, W - 108, ry2 - 2), "注意", colors["primary"], max_size=12, min_size=9, bold=True, max_lines=1, valign="center")
            _rough_line(d, [(W - 164, ry1 + 5), (W - 164, ry2 - 7)], colors["primary"], 2, tip_rng, 1, 2)
        else:
            bang_box = (166 + (i % 2) * 3, ry1 + 1, 220 + (i % 2) * 3, ry2 - 1)
            hf.center(d, bang_box, "!", colors["primary"], max_size=34, min_size=25, bold=True, max_lines=1)
            _rough_underline(d, bang_box[0] + 12, ry2 - 5, bang_box[2] - 11, colors["primary"], tip_rng, width=2)
            tip_text_color = colors["text"] if note_mode == "red_journal" else colors["primary"]
            hf.left(d, (232, ry1 + 1, W - 112, ry2 - 2), text, tip_text_color, max_size=19, min_size=14, bold=True, max_lines=2, line_gap=2, valign="center")

    # footer: QQ group avatar sticker + watermark sentence as one centered line
    _rough_line(d, [(64, H - 78), (W - 64, H - 79)], colors.get("line_dark", "#93AAB6"), 1, rng, 1, 1)
    _draw_footer_with_group_avatar(img, d, guide, services, hf, colors, rcfg, (88, H - 70, W - 88, H - 22))

    img = _apply_retro_print_effect(img, colors, rcfg, _seed_rng(guide, "retro-print-post"))
    rtools.save(img, out_path, guide, started)
