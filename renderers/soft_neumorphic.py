# -*- coding: utf-8 -*-
"""Soft neumorphic guide renderer.

Design goal:
- keep the information order and readability of classic_clean;
- translate the surface language into soft raised / recessed controls inspired by
  neumorphic mobile UI references;
- D1-D7 remain the largest information area;
- decoration yields to text.
"""
from functools import lru_cache
from pathlib import Path
import math
import re
import time

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

from .shared import SharedRendererTools
from .reward_items import RewardItemRenderer

STYLE_IDS = ("soft_neumorphic",)


def _rgb(value, fallback=(220, 224, 230)):
    s = str(value or "").strip()
    if len(s) == 7 and s.startswith("#"):
        try:
            return tuple(int(s[i:i+2], 16) for i in (1, 3, 5))
        except ValueError:
            pass
    return fallback


def _hex(rgb):
    return "#{:02X}{:02X}{:02X}".format(*[max(0, min(255, int(round(v)))) for v in rgb])


def _mix(a, b, t):
    ar = _rgb(a)
    br = _rgb(b)
    t = max(0.0, min(1.0, float(t)))
    return _hex(tuple(ar[i] + (br[i] - ar[i]) * t for i in range(3)))


def _rgba(value, alpha=255):
    return (*_rgb(value), max(0, min(255, int(alpha))))


@lru_cache(maxsize=128)
def _load_trimmed_rgba(path_text, mtime_ns):
    """Load/crop an icon once so tiny UI placements can be resampled smoothly."""
    src = Image.open(path_text).convert("RGBA")
    try:
        alpha = src.getchannel("A")
        bbox = alpha.getbbox()
        if bbox:
            src = src.crop(bbox)
    except Exception:
        pass
    return src


def _paste_icon_smooth(base, img_path, box, *, trim=True, soften=0.22, supersample=4):
    """Paste a small raster icon with anti-aliased, non-pixelated edges.

    The source is fitted on a supersampled canvas, lightly softened, then reduced
    with LANCZOS.  This is intentionally local to this renderer so shared engine
    artwork remains untouched.
    """
    try:
        p = Path(img_path)
        stat = p.stat()
        if trim:
            src = _load_trimmed_rgba(str(p), int(stat.st_mtime_ns)).copy()
        else:
            src = Image.open(p).convert("RGBA")
        x1, y1, x2, y2 = map(int, box)
        tw, th = max(1, x2 - x1), max(1, y2 - y1)
        ss = max(2, int(supersample))
        hi_w, hi_h = tw * ss, th * ss
        ratio = min(hi_w / max(1, src.width), hi_h / max(1, src.height))
        nw = max(1, int(round(src.width * ratio)))
        nh = max(1, int(round(src.height * ratio)))
        art = src.resize((nw, nh), Image.Resampling.LANCZOS)
        hi = Image.new("RGBA", (hi_w, hi_h), (0, 0, 0, 0))
        hi.alpha_composite(art, ((hi_w - nw) // 2, (hi_h - nh) // 2))
        if soften and soften > 0:
            # Only a fraction of a final pixel: enough to remove stair-step / pixel
            # harshness without making the game artwork look blurry.
            blurred = hi.filter(ImageFilter.GaussianBlur(float(soften) * ss))
            hi = Image.blend(hi, blurred, 0.24)
        final = hi.resize((tw, th), Image.Resampling.LANCZOS)
        if soften and soften > 0:
            edge_soft = final.filter(ImageFilter.GaussianBlur(min(0.34, float(soften))))
            final = Image.blend(final, edge_soft, 0.28)
        base.alpha_composite(final, (x1, y1))
        return True
    except Exception:
        return False



def _paste_icon_clean(base, img_path, box, *, trim=True):
    """LANCZOS-only icon placement. No blur, halo, glow, or extra shadow."""
    try:
        p = Path(img_path)
        stat = p.stat()
        src = _load_trimmed_rgba(str(p), int(stat.st_mtime_ns)).copy() if trim else Image.open(p).convert("RGBA")
        x1, y1, x2, y2 = map(int, box)
        tw, th = max(1, x2 - x1), max(1, y2 - y1)
        ratio = min(tw / max(1, src.width), th / max(1, src.height))
        nw = max(1, int(round(src.width * ratio)))
        nh = max(1, int(round(src.height * ratio)))
        try:
            art = src.resize((nw, nh), Image.Resampling.LANCZOS, reducing_gap=3.0)
        except TypeError:
            art = src.resize((nw, nh), Image.Resampling.LANCZOS)
        base.alpha_composite(art, (x1 + (tw - nw) // 2, y1 + (th - nh) // 2))
        return True
    except Exception:
        return False


def _aa_rounded_fill(base, box, radius, fill, scale=4):
    """Anti-alias only the panel face. Does not draw any shadow."""
    x1, y1, x2, y2 = map(int, box)
    w, h = max(2, x2 - x1), max(2, y2 - y1)
    s = max(2, int(scale))
    hi = Image.new("RGBA", (w * s, h * s), (0, 0, 0, 0))
    hd = ImageDraw.Draw(hi)
    hd.rounded_rectangle((0, 0, w * s - 1, h * s - 1),
                         radius=max(1, int(radius * s)),
                         fill=_rgba(fill, 255))
    face = hi.resize((w, h), Image.Resampling.LANCZOS)
    base.alpha_composite(face, (x1, y1))


def _aa_circle(base, box, fill, outline=None, outline_width=0, scale=6):
    """High quality anti-aliased circle used for small UI wells / knobs."""
    x1, y1, x2, y2 = map(int, box)
    w, h = max(2, x2 - x1), max(2, y2 - y1)
    s = max(2, int(scale))
    hi = Image.new("RGBA", (w * s, h * s), (0, 0, 0, 0))
    hd = ImageDraw.Draw(hi)
    ow = max(0, int(round(outline_width * s)))
    hd.ellipse((0, 0, w * s - 1, h * s - 1), fill=_rgba(fill, 255),
               outline=_rgba(outline, 255) if outline is not None and ow > 0 else None,
               width=ow if ow > 0 else 0)
    face = hi.resize((w, h), Image.Resampling.LANCZOS)
    base.alpha_composite(face, (x1, y1))


def _load_bg_logo(services, guide):
    cfg = guide.get("cfg") or {}
    p = services.resolve_path(cfg, "assets/BG_LOGO.png")
    if not p or not Path(p).exists():
        return None
    try:
        return Image.open(p).convert("RGBA")
    except Exception:
        return None


def _draw_day_watermark_logo(base, services, guide, box, colors):
    """Subtle watermark using source alpha only; no added shadow/glow."""
    src = _load_bg_logo(services, guide)
    if src is None:
        return
    x1, y1, x2, y2 = map(int, box)
    card_w, card_h = max(1, x2 - x1), max(1, y2 - y1)
    target_h = max(48, min(88, int(card_h * 0.47)))
    target_w = max(52, int(card_w * 0.115))
    src = src.copy()
    src.thumbnail((target_w, target_h), Image.Resampling.LANCZOS)
    if src.width <= 0 or src.height <= 0:
        return
    alpha = src.getchannel("A")
    amax = max(1, int(alpha.getextrema()[1] or 1))
    target_max = 14
    alpha = alpha.point(lambda a: max(0, min(255, int(round(a * target_max / amax)))))
    tint = _mix(colors["muted"], colors["surface"], 0.56)
    mark = Image.new("RGBA", src.size, (*_rgb(tint), 0))
    mark.putalpha(alpha)
    base.alpha_composite(mark, (x2 - 22 - mark.width, y2 - 10 - mark.height))


def _draw_reward_icon_smooth(base, reward_renderer, item, box, *, supersample=4):
    """Render reward artwork at high resolution, then reduce once for smooth edges."""
    x1, y1, x2, y2 = map(int, box)
    tw, th = max(1, x2 - x1), max(1, y2 - y1)
    ss = max(2, int(supersample))
    hi = Image.new("RGBA", (tw * ss, th * ss), (0, 0, 0, 0))
    try:
        resolved = reward_renderer.draw_icon(hi, item, (0, 0, tw * ss, th * ss))
        # A tiny post-downsample softening removes jagged rank/frame edges while
        # keeping the source art recognizable.
        final = hi.resize((tw, th), Image.Resampling.LANCZOS)
        soft = final.filter(ImageFilter.GaussianBlur(0.28))
        final = Image.blend(final, soft, 0.22)
        base.alpha_composite(final, (x1, y1))
        return resolved
    except Exception:
        return reward_renderer.resolve(item)


@lru_cache(maxsize=128)
def _blurred_round_mask(width, height, radius, blur):
    width = max(2, int(width))
    height = max(2, int(height))
    radius = max(1, int(radius))
    blur = max(1, int(blur))
    pad = blur * 3
    mask = Image.new("L", (width + pad * 2, height + pad * 2), 0)
    md = ImageDraw.Draw(mask)
    md.rounded_rectangle((pad, pad, pad + width - 1, pad + height - 1), radius=radius, fill=255)
    return mask.filter(ImageFilter.GaussianBlur(blur)), pad


def _paste_shadow(base, box, radius, color, offset=(0, 0), blur=10, alpha=90):
    x1, y1, x2, y2 = map(int, box)
    w = max(2, x2 - x1)
    h = max(2, y2 - y1)
    mask, pad = _blurred_round_mask(w, h, radius, blur)
    layer = Image.new("RGBA", mask.size, _rgba(color, alpha))
    px = x1 - pad + int(offset[0])
    py = y1 - pad + int(offset[1])
    base.paste(layer, (px, py), mask)


def _paste_inner_edge(base, box, radius, color, offset=(3, 3), blur=5, alpha=70):
    """Paint a soft inner edge without changing the global panel recipe.

    Positive offset creates a top/left inner shadow; negative offset creates
    a bottom/right inner highlight. The effect is clipped to the rounded box.
    """
    x1, y1, x2, y2 = map(int, box)
    w = max(2, x2 - x1)
    h = max(2, y2 - y1)
    mask = Image.new("L", (w, h), 0)
    md = ImageDraw.Draw(mask)
    md.rounded_rectangle((0, 0, w - 1, h - 1), radius=max(1, int(radius)), fill=255)
    shifted = Image.new("L", (w, h), 0)
    shifted.paste(mask, (int(offset[0]), int(offset[1])))
    edge = ImageChops.subtract(mask, shifted)
    edge = edge.filter(ImageFilter.GaussianBlur(max(1, int(blur))))
    edge = ImageChops.multiply(edge, mask)
    if alpha < 255:
        edge = edge.point(lambda p: int(p * max(0, min(255, alpha)) / 255))
    layer = Image.new("RGBA", (w, h), _rgba(color, 255))
    base.paste(layer, (x1, y1), edge)


def _soft_panel(base, box, radius, surface, shadow_dark, shadow_light,
                shadow=8, blur=10, dark_alpha=72, light_alpha=190,
                inset=False, accent_edge=None):
    """Draw a neumorphic surface. Inset mode is intentionally lighter-weight."""
    x1, y1, x2, y2 = map(int, box)
    d = ImageDraw.Draw(base)
    if not inset:
        _paste_shadow(base, box, radius, shadow_light, (-shadow, -shadow), blur, light_alpha)
        _paste_shadow(base, box, radius, shadow_dark, (shadow, shadow), blur, dark_alpha)
        d.rounded_rectangle((x1, y1, x2, y2), radius=radius, fill=surface)
        # No hard border: the paired shadows carry the shape, matching soft UI references.
    else:
        recessed = _mix(surface, shadow_dark, 0.035)
        d.rounded_rectangle((x1, y1, x2, y2), radius=radius, fill=recessed)
        # A restrained inset border avoids the hard, glossy outlines of skeuomorphic UI.
        d.rounded_rectangle((x1+1, y1+1, x2-1, y2-1), radius=max(1, radius-1), fill=None,
                            outline=_mix(recessed, shadow_dark, 0.12), width=2)
    if accent_edge:
        d.rounded_rectangle((x1, y1, x2, y2), radius=radius, fill=None, outline=accent_edge, width=2)


def _accent_pill(base, box, fill, shadow_dark, shadow_light, radius=18, shadow=4, blur=6):
    _soft_panel(base, box, radius, fill, shadow_dark, shadow_light,
                shadow=shadow, blur=blur, dark_alpha=68, light_alpha=150)


def _draw_molded_tier_node(base, x, y, colors, active=False):
    """Draw one anti-aliased soft milestone bead.

    The node is rendered at 4x and downsampled so it reads as a molded UI
    control instead of a low-resolution outlined circle.  It deliberately
    avoids a hard stroke; depth comes from the same light/dark pairing used
    throughout the neumorphic theme.
    """
    scale = 4
    size = 30
    pad = 8
    canvas_px = (size + pad * 2) * scale
    layer = Image.new("RGBA", (canvas_px, canvas_px), (0, 0, 0, 0))
    cx = cy = canvas_px // 2
    r = 9 * scale

    def ellipse_mask(dx=0, dy=0, radius=r):
        m = Image.new("L", (canvas_px, canvas_px), 0)
        md = ImageDraw.Draw(m)
        md.ellipse((cx-radius+dx, cy-radius+dy, cx+radius+dx, cy+radius+dy), fill=255)
        return m

    # Paired soft shadows create a small pearl-like control without any crisp ring.
    light_mask = ellipse_mask(-2 * scale, -2 * scale).filter(ImageFilter.GaussianBlur(2.1 * scale))
    dark_mask = ellipse_mask(2 * scale, 2 * scale).filter(ImageFilter.GaussianBlur(2.2 * scale))
    light_layer = Image.new("RGBA", layer.size, _rgba(colors["shadow_light"], 180))
    dark_layer = Image.new("RGBA", layer.size, _rgba(colors["shadow_dark"], 88))
    layer.alpha_composite(Image.composite(light_layer, Image.new("RGBA", layer.size), light_mask))
    layer.alpha_composite(Image.composite(dark_layer, Image.new("RGBA", layer.size), dark_mask))

    ld = ImageDraw.Draw(layer)
    ld.ellipse((cx-r, cy-r, cx+r, cy+r), fill=_rgba(colors["surface"], 255))

    # Accent is a rounded inset dot, larger once the Day1 progress has reached it.
    inner_r = (5.0 if active else 3.8) * scale
    inner_color = colors["primary"] if active else _mix(colors["primary"], colors["surface"], 0.18)
    ld.ellipse((cx-inner_r, cy-inner_r, cx+inner_r, cy+inner_r), fill=_rgba(inner_color, 255))
    # Tiny upper-left sheen keeps the node organic/soft rather than pixel-like.
    sheen_r = 1.6 * scale
    sx = cx - 1.8 * scale
    sy = cy - 2.0 * scale
    ld.ellipse((sx-sheen_r, sy-sheen_r, sx+sheen_r, sy+sheen_r),
               fill=(255, 255, 255, 115 if active else 86))

    layer = layer.resize((size + pad * 2, size + pad * 2), Image.Resampling.LANCZOS)
    px = int(round(x - layer.width / 2))
    py = int(round(y - layer.height / 2))
    base.alpha_composite(layer, (px, py))


@lru_cache(maxsize=128)
def _load_theme_font_cached(path_text, mtime_ns, size):
    try:
        return ImageFont.truetype(path_text, size=max(1, int(size)))
    except Exception:
        return None


def _resolve_theme_font_path(guide, services, raw):
    raw = str(raw or '').strip()
    if not raw:
        return None
    cfg = guide.get('cfg') or {}
    try:
        resolved = services.resolve_path(cfg, raw)
        if resolved and Path(resolved).is_file():
            return Path(resolved)
    except Exception:
        pass
    direct = Path(raw).expanduser()
    if direct.is_file():
        return direct
    cwd = Path.cwd() / raw
    return cwd if cwd.is_file() else None


def _install_theme_fonts(guide, services):
    """Temporarily route this renderer through font paths declared in theme.json.

    Supported renderer keys:
      font_path / font_regular_path: regular text
      font_bold_path: bold text (falls back to regular path)
    Paths may be project-relative or absolute. Empty values preserve engine defaults.
    """
    rcfg = _rcfg(guide)
    regular = _resolve_theme_font_path(
        guide, services, rcfg.get('font_regular_path') or rcfg.get('font_path')
    )
    bold = _resolve_theme_font_path(guide, services, rcfg.get('font_bold_path')) or regular
    if regular is None and bold is None:
        return None

    old_service_get_font = services._values.get('get_font') if hasattr(services, '_values') else None
    draw_functions = []
    for name in ('draw_left', 'draw_center', 'choose_shared_kpi_label_size'):
        try:
            fn = getattr(services, name)
        except Exception:
            continue
        if callable(fn) and hasattr(fn, '__globals__'):
            draw_functions.append(fn)
    old_globals = []
    for fn in draw_functions:
        g = fn.__globals__
        old_globals.append((g, g.get('get_font')))

    def themed_get_font(size, is_bold=False):
        path = bold if is_bold else regular
        if path is None:
            path = regular or bold
        if path is not None:
            try:
                mtime_ns = path.stat().st_mtime_ns
            except Exception:
                mtime_ns = 0
            f = _load_theme_font_cached(str(path), int(mtime_ns), int(size))
            if f is not None:
                return f
        if old_service_get_font is not None:
            return old_service_get_font(size, is_bold)
        return ImageFont.load_default()

    if hasattr(services, '_values'):
        services._values['get_font'] = themed_get_font
    for g, _old in old_globals:
        g['get_font'] = themed_get_font
    return old_service_get_font, old_globals


def _restore_theme_fonts(services, state):
    if not state:
        return
    old_service_get_font, old_globals = state
    if hasattr(services, '_values') and old_service_get_font is not None:
        services._values['get_font'] = old_service_get_font
    for g, old in old_globals:
        if old is None:
            g.pop('get_font', None)
        else:
            g['get_font'] = old


def _rcfg(guide):
    theme_cfg = guide.get("theme_config") or {}
    data = theme_cfg.get("renderer") if isinstance(theme_cfg.get("renderer"), dict) else {}
    return dict(data or {})


def _text_lines(text):
    return [x.strip() for x in str(text or "").replace("\r", "").split("\n") if x.strip()]


def _display_metric_label(label):
    s = str(label or "").strip()
    s = re.sub(r"^(期望|预计|预期)", "", s).strip()
    return s or str(label or "").strip()


def _format_score(value):
    try:
        f = float(value)
    except Exception:
        return ""
    return str(int(round(f)))


def _draw_title(services, base, draw, guide, colors, rcfg):
    W = int(services.W)
    surface = colors["surface"]
    title = services.clean(str(guide.get("title") or "活动攻略"))

    # Reference-inspired: a broad raised capsule, large typography, sparse chrome.
    box = (52, 36, W - 52, 142)
    _soft_panel(base, box, 34, surface, colors["shadow_dark"], colors["shadow_light"],
                shadow=8, blur=11, dark_alpha=72, light_alpha=205)
    # Small accent status dot / bar on the left keeps the palette present without
    # turning the entire page into a solid color block.
    _accent_pill(base, (74, 70, 92, 108), colors["primary"], colors["shadow_dark"], colors["shadow_light"], radius=9, shadow=2, blur=4)
    services.draw_left(
        draw, (112, 49, W - 76, 130), title, colors["text"],
        max_size=int(rcfg.get("title_font_size", 50) or 50), min_size=34,
        bold=True, max_lines=1, line_gap=0, valign="center"
    )


def _draw_kpis(services, base, draw, guide, colors, top):
    items = services.build_render_kpis((guide.get("kpis") or [])[:3], guide.get("cfg") or {})
    if not items:
        return top
    W = int(services.W)
    left, right = 48, W - 48
    gap = 14
    n = len(items)
    card_h = 112
    cell_w = (right - left - gap * (n - 1)) / max(1, n)
    for i, item in enumerate(items):
        x1 = int(round(left + i * (cell_w + gap)))
        x2 = int(round(x1 + cell_w))
        box = (x1, top, x2, top + card_h)
        _soft_panel(base, box, 26, colors["surface"], colors["shadow_dark"], colors["shadow_light"],
                    shadow=6, blur=9, dark_alpha=68, light_alpha=198)
        icon = item.get("icon")
        icon_box = (x1 + 14, top + 20, x1 + 76, top + 82)
        _soft_panel(base, icon_box, 31, colors["surface"], colors["shadow_dark"], colors["shadow_light"],
                    shadow=3, blur=5, dark_alpha=58, light_alpha=168)
        if icon and Path(icon).exists():
            _paste_icon_clean(base, Path(icon), (x1 + 24, top + 30, x1 + 66, top + 72), trim=True)
        else:
            services.draw_center(draw, icon_box, "•", colors["primary"], max_size=28, min_size=22, bold=True, max_lines=1)
        label = services.clean(str(item.get("label") or ""))
        value = services.clean(str(item.get("value") or ""))
        if item.get("budget_components") and len(item.get("budget_components") or []) == 1:
            value = services.clean(str(item["budget_components"][0].get("amount") or value))
        services.draw_left(draw, (x1 + 90, top + 15, x2 - 12, top + 50), label, colors["primary_dark"],
                           max_size=17, min_size=13, bold=True, max_lines=1, line_gap=0, valign="center")
        services.draw_left(draw, (x1 + 90, top + 47, x2 - 12, top + 96), value, colors["text"],
                           max_size=30, min_size=18, bold=True, max_lines=1, line_gap=0, valign="center")
    return top + card_h


def _draw_rewards(services, base, draw, guide, colors, top):
    W = int(services.W)
    tools = SharedRendererTools(services)
    leaves = tools.flat_reward_items(guide.get("reward_items") or [])[:4]
    panel = (48, top, W - 48, top + 188)
    _soft_panel(base, panel, 28, colors["surface"], colors["shadow_dark"], colors["shadow_light"],
                shadow=7, blur=10, dark_alpha=68, light_alpha=198)

    # Compact section label, like a molded control caption rather than a banner.
    label_box = (72, top + 17, 232, top + 55)
    _accent_pill(base, label_box, colors["primary_soft"], colors["shadow_dark"], colors["shadow_light"], radius=18, shadow=2, blur=4)
    services.draw_center(draw, label_box, "可兑换道具", colors["primary_dark"], max_size=18, min_size=15, bold=True, max_lines=1)

    if not leaves:
        text = tools.reward_summary(guide)
        services.draw_left(draw, (74, top + 69, W - 74, top + 166), text, colors["text"],
                           max_size=21, min_size=15, bold=False, max_lines=3, line_gap=3, valign="center")
        return top + 188

    gap = 12
    left, right = 72, W - 72
    cell_w = (right - left - gap * (len(leaves) - 1)) / len(leaves)
    reward_renderer = RewardItemRenderer(services, guide)
    for i, item in enumerate(leaves):
        x1 = int(round(left + i * (cell_w + gap)))
        x2 = int(round(x1 + cell_w))
        card = (x1, top + 68, x2, top + 166)
        _soft_panel(base, card, 20, colors["surface"], colors["shadow_dark"], colors["shadow_light"],
                    shadow=4, blur=6, dark_alpha=58, light_alpha=168)
        icon_size = min(62, int(cell_w * 0.31))
        ix1 = x1 + 12
        iy1 = top + 84
        ibox = (ix1, iy1, ix1 + icon_size, iy1 + icon_size)
        resolved = reward_renderer.draw_icon(base, item, ibox)
        if not (resolved.get("icon_path") and Path(resolved.get("icon_path")).exists()):
            services.draw_center(draw, ibox, "?", colors["muted"], max_size=20, min_size=15, bold=True, max_lines=1)
        name = services.clean(str(item.get("name") or "物品"))
        qty = services.clean(str(item.get("qty") or ""))
        label = name + ((" ×" + qty) if qty else "")
        services.draw_left(draw, (ix1 + icon_size + 10, top + 76, x2 - 10, top + 157), label, colors["text"],
                           max_size=15, min_size=12, bold=True, max_lines=3, line_gap=1, valign="center")
    return top + 188



def _progress_point_icon(services, guide):
    cfg = guide.get("cfg") or {}
    activity_icons = cfg.get("activity_icons") or {}
    if not isinstance(activity_icons, dict):
        return None
    raw = activity_icons.get("point") or activity_icons.get("tier_point") or activity_icons.get("progress_point")
    if not raw:
        return None
    p = services.resolve_path(cfg, raw)
    return Path(p) if p and Path(p).exists() else None


def _draw_tier_ruler(services, base, draw, guide, days, colors, top):
    """Global milestone strip with visible score labels and a recessed rail.

    The rail itself stays neutral/recessed while its filled portion uses the
    active variant accent. Progress is intentionally based on Day1 so this
    global strip communicates the starting-day milestone position rather than
    the final plan total.
    """
    contexts = [d.get("tier_progress") for d in days if isinstance(d.get("tier_progress"), dict)]
    if not contexts:
        return top
    ctx = contexts[0]
    thresholds = list(ctx.get("thresholds") or [])
    try:
        maximum = float(ctx.get("max") or 0)
    except Exception:
        maximum = 0.0
    if not thresholds or maximum <= 0:
        return top

    W = int(services.W)
    y1, y2 = top, top + 82
    box = (48, y1, W - 48, y2)
    # Keep the original card material / shadow recipe unchanged.
    _soft_panel(base, box, 24, colors["surface"], colors["shadow_dark"], colors["shadow_light"],
                shadow=5, blur=7, dark_alpha=60, light_alpha=174)

    # Leave a deliberate tail after tier 5 so the final node does not feel clipped.
    last_threshold = 0.0
    for item in thresholds:
        try:
            last_threshold = max(last_threshold, float(item.get("value") or 0))
        except Exception:
            pass
    visual_max = max(maximum, last_threshold * 1.075 if last_threshold > 0 else maximum)

    tx1, tx2 = 94, W - 90
    ty1, ty2 = y1 + 38, y1 + 55
    track = (tx1, ty1, tx2, ty2)

    # Activity point icon is part of the same recessed groove, not a separate button.
    progress_icon = _progress_point_icon(services, guide)
    icon_cx = 82
    icon_cy = int(round((ty1 + ty2) / 2))
    socket_r = 19
    socket_box = (icon_cx - socket_r, icon_cy - socket_r,
                  icon_cx + socket_r, icon_cy + socket_r)

    # Dedicated groove treatment for the score rail only. This does not alter
    # the shared raised-card/button material used elsewhere in the theme.
    recessed = _mix(colors["surface"], colors["shadow_dark"], 0.055)
    _aa_circle(base, socket_box, recessed, outline=_mix(recessed, colors["shadow_dark"], 0.22), outline_width=1.5, scale=8)
    _paste_inner_edge(base, socket_box, socket_r, colors["shadow_dark"], offset=(3, 3), blur=4, alpha=76)
    _paste_inner_edge(base, socket_box, socket_r, colors["shadow_light"], offset=(-2, -2), blur=3, alpha=112)
    draw.rounded_rectangle((icon_cx + 3, ty1, tx2, ty2), radius=9, fill=recessed)
    draw.rounded_rectangle(track, radius=9, fill=recessed)
    draw.rounded_rectangle((tx1 + 1, ty1 + 1, tx2 - 1, ty2 - 1), radius=8,
                           outline=_mix(recessed, colors["shadow_dark"], 0.24), width=2)
    draw.line((tx1 + 9, ty1 + 3, tx2 - 9, ty1 + 3),
              fill=_mix(recessed, colors["shadow_dark"], 0.30), width=2)
    draw.line((tx1 + 9, ty2 - 3, tx2 - 9, ty2 - 3),
              fill=_mix(recessed, colors["shadow_light"], 0.78), width=2)

    # Fill the groove using Day1's actual score. Keep a small inset so the
    # darker/lighter groove lips remain visible around the coloured progress.
    try:
        day1_score = float(ctx.get("score") or 0)
    except Exception:
        day1_score = 0.0
    if day1_score > 0:
        frac = max(0.0, min(1.0, day1_score / max(1.0, visual_max)))
        inner_x1 = tx1 + 4
        inner_x2 = tx2 - 4
        fill_x = int(round(inner_x1 + (inner_x2 - inner_x1) * frac))
        liquid = colors["primary"]
        socket_fill = (icon_cx - socket_r + 4, icon_cy - socket_r + 4,
                       icon_cx + socket_r - 4, icon_cy + socket_r - 4)
        _aa_circle(base, socket_fill, liquid, scale=8)
        # Bridge the socket liquid and the bar fill so they read as one continuous body.
        bridge_x1 = icon_cx + 2
        bridge_y1 = ty1 + 4
        bridge_y2 = ty2 - 4
        if fill_x > bridge_x1:
            fill_box = (bridge_x1, bridge_y1, fill_x, bridge_y2)
            draw.rounded_rectangle(fill_box, radius=5, fill=liquid)
            if fill_x - bridge_x1 > 12:
                draw.line((bridge_x1 + 8, ty1 + 5, fill_x - 5, ty1 + 5),
                          fill=_mix(liquid, "#FFFFFF", 0.40), width=1)
        # Same liquid highlight inside the socket for a soaked-in feel.
        draw.line((icon_cx - 8, icon_cy - 8, icon_cx + 8, icon_cy - 8),
                  fill=_mix(liquid, "#FFFFFF", 0.42), width=1)
    if progress_icon:
        _paste_icon_clean(base, progress_icon,
                          (icon_cx - 16, icon_cy - 16, icon_cx + 16, icon_cy + 16), trim=True)

    cy = (ty1 + ty2) / 2
    for item in thresholds:
        try:
            val = float(item.get("value") or 0)
        except Exception:
            continue
        if val < 0:
            continue
        x = tx1 + (tx2 - tx1) * min(1.0, val / max(1.0, visual_max))
        # Render at high resolution and downsample: smoother molded bead, no hard
        # ring and no pixel-style stair stepping.
        _draw_molded_tier_node(base, x, cy, colors, active=(val <= day1_score + 1e-6))

        label = services.clean(str(item.get("label") or "")).strip()
        score_text = _format_score(val)
        shown = (label + (" " + score_text if score_text else "")).strip()
        if shown:
            node_label_color = colors["primary_dark"] if val <= day1_score + 1e-6 else colors["muted"]
            services.draw_center(draw, (int(x - 66), y1 + 7, int(x + 66), y1 + 33), shown,
                                 node_label_color, max_size=13, min_size=10,
                                 bold=True, max_lines=1, line_gap=0)
    return y2


def _draw_metric_cell(services, base, draw, guide, item, box, colors):
    x1, y1, x2, y2 = map(int, box)
    # Use the original raised soft-button material so remaining/expected values
    # have clear physical depth without changing the theme's established texture.
    _soft_panel(base, box, 14, colors["surface"], colors["shadow_dark"], colors["shadow_light"],
                shadow=3, blur=5, dark_alpha=56, light_alpha=162)
    icon = services.config_day_icon(guide.get("cfg") or {}, item)
    has_icon = bool(icon and Path(icon).exists())
    icon_size = min(24, y2 - y1 - 12)
    tx = x1 + 10
    if has_icon:
        iy = int((y1 + y2 - icon_size) / 2)
        _paste_icon_clean(base, Path(icon), (tx, iy, tx + icon_size, iy + icon_size), trim=True)
        tx += icon_size + 8
    label = _display_metric_label(services.clean(str(item.get("label") or "")))
    value = services.clean(str(item.get("value") or ""))
    shown = (label + (" " + value if value else "")).strip()
    services.draw_left(draw, (tx, y1 + 3, x2 - 8, y2 - 3), shown, colors["text"],
                       max_size=14, min_size=12, bold=True, max_lines=1, line_gap=0, valign="center")


def _draw_day_card(services, base, draw, guide, info, box, colors, rcfg, shared_action_size, shared_metric_area_h):
    x1, y1, x2, y2 = map(int, box)
    special = bool(services.clean(str(info.get("special_label") or "")))
    surface = colors["surface"]
    # Preserve the exact card material from the user-selected baseline.
    _soft_panel(base, box, 25, surface, colors["shadow_dark"], colors["shadow_light"],
                shadow=6 if not special else 8, blur=9 if not special else 11,
                dark_alpha=66 if not special else 76, light_alpha=188,
                accent_edge=None)

    day = services.clean(str(info.get("day") or "DAY"))
    target = services.clean(str(info.get("target") or ""))
    tier = info.get("tier_progress") if isinstance(info.get("tier_progress"), dict) else None
    score = _format_score(tier.get("score")) if tier else ""
    title = day
    if target:
        title += "  |  目标 " + target
    if score:
        title += "  ·  " + score + "分"
    services.draw_left(draw, (x1 + 22, y1 + 12, x2 - 170, y1 + 55), title,
                       colors["primary_dark"],
                       max_size=23, min_size=18, bold=True, max_lines=1, line_gap=0, valign="center")

    if special:
        label = services.clean(str(info.get("special_label") or "重点"))
        badge = (x2 - 154, y1 + 12, x2 - 20, y1 + 51)
        _accent_pill(base, badge, colors["primary_dark"], colors["shadow_dark"], colors["shadow_light"], radius=16, shadow=2, blur=4)
        _aa_rounded_fill(base, badge, 16, colors["primary_dark"], scale=4)
        services.draw_center(draw, badge, label, colors["accent_text"], max_size=16, min_size=13, bold=True, max_lines=1)

    metrics = list(info.get("metric_items") or [])[:4]
    metric_w = 392 if metrics else 0
    action_x2 = x2 - (metric_w + 28 if metrics else 22)
    action_box = (x1 + 24, y1 + 57, action_x2, y2 - 16)

    action = services.clean(str(info.get("action") or "按计划执行"))
    services.draw_left(draw, action_box, action, colors["text"],
                       max_size=shared_action_size, min_size=shared_action_size,
                       bold=False, max_lines=6, line_gap=int(rcfg.get("day_action_line_gap", 4) or 4), valign="center")

    if metrics:
        mx1, mx2 = x2 - metric_w, x2 - 18
        body_y1, body_y2 = y1 + 61, y2 - 16
        available_h = max(1, body_y2 - body_y1)
        # One shared physical height is used for every day, so special-day cards
        # no longer stretch the remaining/expected controls.
        group_h = min(max(1, int(shared_metric_area_h)), available_h)
        my1 = int(round(body_y1 + (available_h - group_h) / 2))
        my2 = my1 + group_h
        cols = 2 if len(metrics) > 2 else 1
        rows = int(math.ceil(len(metrics) / cols))
        gap_x, gap_y = 8, 7
        cw = (mx2 - mx1 - gap_x * max(0, cols - 1)) / max(1, cols)
        rh = (my2 - my1 - gap_y * max(0, rows - 1)) / max(1, rows)
        for i, item in enumerate(metrics):
            rr, cc = divmod(i, cols)
            bx1 = int(round(mx1 + cc * (cw + gap_x)))
            by1 = int(round(my1 + rr * (rh + gap_y)))
            bx2 = int(round(bx1 + cw))
            by2 = int(round(by1 + rh))
            _draw_metric_cell(services, base, draw, guide, item, (bx1, by1, bx2, by2), colors)


def _day_weights(days):
    weights = []
    for info in days:
        lines = _text_lines(info.get("action"))
        n = max(1, len(lines))
        # Long days get actual height instead of smaller text. Special days get a bit more breathing room.
        weight = 1.0 + max(0, n - 2) * 0.28
        if info.get("special_label"):
            weight += 0.18
        weights.append(weight)
    return weights


def _draw_risk(services, base, draw, guide, colors, top, bottom):
    tools = SharedRendererTools(services)
    risk = tools.risk_items(guide)
    if not risk:
        return
    W = int(services.W)
    box = (48, top, W - 48, bottom)
    # Risk stays red in every accent variant; the original soft-card material
    # is retained, only the alert surface hue changes.
    risk_surface = _mix(colors["surface"], colors["warning_soft"], 0.78)
    _soft_panel(base, box, 25, risk_surface, colors["shadow_dark"], colors["shadow_light"],
                shadow=6, blur=9, dark_alpha=68, light_alpha=188)
    icon_box = (70, top + 18, 119, top + 67)
    _accent_pill(base, icon_box, colors["warning"], colors["shadow_dark"], colors["shadow_light"], radius=18, shadow=2, blur=4)
    font = services.get_font(28, True)
    bb = draw.textbbox((0, 0), "!", font=font)
    tw, th = bb[2] - bb[0], bb[3] - bb[1]
    cx = (icon_box[0] + icon_box[2]) / 2 + 0.5
    cy = (icon_box[1] + icon_box[3]) / 2 + 1.0
    draw.text((cx - tw / 2 - bb[0], cy - th / 2 - bb[1]), "!", font=font, fill="#FFFFFF")
    services.draw_left(draw, (132, top + 14, 282, top + 50), "风险提示", colors["warning"],
                       max_size=19, min_size=16, bold=True, max_lines=1, valign="center")
    text = "\n".join("• " + x for x in risk)
    risk_text = _mix(colors["warning"], "#551F1B", 0.34)
    services.draw_left(draw, (132, top + 48, W - 72, bottom - 14), text, risk_text,
                       max_size=17, min_size=14, bold=False, max_lines=5, line_gap=3, valign="center")


def _draw_footer(services, base, draw, guide, colors, footer_h):
    W, H = int(services.W), int(services.H)
    footer_box = (36, H - footer_h + 8, W - 36, H - 10)
    # Keep this area visually separate from the raised controls: the whole
    # group-contact strip is a dedicated recessed groove.
    _soft_panel(base, footer_box, 23, colors["surface"], colors["shadow_dark"], colors["shadow_light"], inset=True)
    fx1, fy1, fx2, fy2 = map(int, footer_box)
    footer_recessed = _mix(colors["surface"], colors["shadow_dark"], 0.045)
    draw.rounded_rectangle((fx1 + 3, fy1 + 3, fx2 - 3, fy2 - 3), radius=20,
                           fill=footer_recessed)
    # Stronger true inner shading only on this footer groove. These do not
    # touch the baseline card/button shadow recipe used elsewhere.
    inner_box = (fx1 + 3, fy1 + 3, fx2 - 3, fy2 - 3)
    _paste_inner_edge(base, inner_box, 20, colors["shadow_dark"], offset=(4, 4), blur=5, alpha=80)
    _paste_inner_edge(base, inner_box, 20, colors["shadow_light"], offset=(-3, -3), blur=4, alpha=125)

    text = services.clean(str(guide.get("watermark", "") or ""))
    cfg = guide.get("cfg") or {}
    raw_icon = cfg.get("watermark_group_icon")
    icon_path = services.resolve_path(cfg, raw_icon) if raw_icon else None

    icon_outer = 60
    avatar_inner = 52  # slightly stronger molded rim for a more obvious round knob feel
    gap = 12
    chosen = None
    max_text_w = W - 180
    for size in range(17, 13, -1):
        font = services.get_font(size, False)
        bb = draw.textbbox((0, 0), text or " ", font=font)
        tw = bb[2] - bb[0]
        if tw <= max_text_w:
            chosen = (font, bb, tw)
            break
    if chosen is None:
        font = services.get_font(14, False)
        bb = draw.textbbox((0, 0), text or " ", font=font)
        chosen = (font, bb, bb[2] - bb[0])
    font, bb, tw = chosen

    has_avatar = bool(icon_path and Path(icon_path).exists())
    total_w = tw + ((icon_outer + gap) if has_avatar else 0)
    start_x = int(round((W - total_w) / 2))
    cy = int(round((footer_box[1] + footer_box[3]) / 2))

    if has_avatar:
        ibox = (start_x, cy - icon_outer // 2, start_x + icon_outer, cy + icon_outer // 2)
        _soft_panel(base, ibox, icon_outer // 2, colors["surface"], colors["shadow_dark"], colors["shadow_light"],
                    shadow=5, blur=7, dark_alpha=60, light_alpha=176)
        try:
            src = Image.open(icon_path).convert("RGBA")
            side = min(src.width, src.height)
            sx = (src.width - side) // 2
            sy = (src.height - side) // 2
            # Build the avatar and circular mask at 4x and downsample once.
            # This removes the stair-stepped/pixelated circular edge that was
            # visible when the mask itself was drawn directly at ~40px.
            aa = 10
            work_size = avatar_inner * aa
            src = src.crop((sx, sy, sx + side, sy + side)).resize(
                (work_size, work_size), Image.Resampling.LANCZOS
            )
            mask_hi = Image.new("L", (work_size, work_size), 0)
            ImageDraw.Draw(mask_hi).ellipse((0, 0, work_size - 1, work_size - 1), fill=255)
            mask_hi = mask_hi.filter(ImageFilter.GaussianBlur(max(1, aa // 2)))
            mask = mask_hi.resize((avatar_inner, avatar_inner), Image.Resampling.LANCZOS)
            mask = mask.filter(ImageFilter.GaussianBlur(0.22))
            src = src.resize((avatar_inner, avatar_inner), Image.Resampling.LANCZOS)
            src.putalpha(mask)
            inset = (icon_outer - avatar_inner) // 2
            base.alpha_composite(src, (start_x + inset, cy - avatar_inner // 2))
        except Exception:
            services.draw_center(draw, ibox, "群", colors["primary_dark"], max_size=18, min_size=14, bold=True, max_lines=1)
        text_x = start_x + icon_outer + gap
    else:
        text_x = start_x

    th = bb[3] - bb[1]
    draw.text((text_x, cy - th / 2 - bb[1]), text, font=font, fill=colors["muted"])


def _render_impl(guide, out_path: Path, services):
    started = time.perf_counter()
    tools = SharedRendererTools(services)
    rcfg = _rcfg(guide)
    colors = tools.colors(guide, {
        "background": "#E7EBEF",
        "surface": "#E7EBEF",
        "text": "#26313A",
        "muted": "#66727C",
        "primary": "#5B8D72",
        "primary_dark": "#345E4B",
        "primary_soft": "#CFE0D6",
        "accent_text": "#FFFFFF",
        "shadow_dark": "#AEB8C2",
        "shadow_light": "#FFFFFF",
        "warning": "#C8524A",
        "warning_soft": "#F0D4D0",
    })

    # Six variants now behave like different indicator/control colours on the
    # same clean neutral device body.  Geometry, shadow offsets and blur values
    # are intentionally unchanged: this block changes colour only.
    source_primary = str(colors.get("primary") or guide.get("palette", {}).get("primary", "#5B8D72")).upper()
    accent_sets = {
        # original palette primary -> (clean accent, dark accent)
        "#5B8D72": ("#37966A", "#236647"),   # emerald green
        "#C39A35": ("#D39A18", "#8A6110"),   # warm amber / gold
        "#5D7FAE": ("#3E73D8", "#294F99"),   # clear cobalt blue
        "#8A6BAA": ("#8A59D1", "#5B3993"),   # blue-violet
        "#B76661": ("#D65353", "#963838"),   # coral red
        "#4D9094": ("#20A6AD", "#146E74"),   # crisp cyan-teal
    }
    primary, primary_dark = accent_sets.get(
        source_primary,
        (source_primary, _mix(source_primary, "#000000", 0.34)),
    )
    colors["primary"] = primary
    colors["primary_dark"] = primary_dark
    # Keep decorative pills visibly related to the variant, but never tint the
    # full cards.  A slightly stronger soft tint improves six-colour separation.
    colors["primary_soft"] = _mix(primary, "#FFFFFF", 0.70)

    # Preserve the approved tactile card/button material exactly. Only the page
    # field is cleaned slightly; surface/shadow values stay locked so the
    # upper-left highlight contour remains visible.
    colors["background"] = "#F1F3F6"
    colors["surface"] = "#E9EDF2"
    colors["text"] = "#25303A"
    colors["muted"] = "#66727D"
    colors["shadow_dark"] = "#AEB8C3"
    colors["shadow_light"] = "#FFFFFF"
    colors["warning"] = "#C94E49"
    colors["warning_soft"] = "#F2D6D3"

    W, H = int(services.W), int(services.H)
    bg = colors["background"]
    img = Image.new("RGBA", (W, H), _rgba(bg, 255))
    draw = ImageDraw.Draw(img)

    # Neutral-only depth gradient; keep it very subtle so the page stays clean
    # and the six accent colours do the distinguishing.
    top_tint = _mix(bg, "#FFFFFF", 0.08)
    bottom_tint = _mix(bg, "#DCE2E8", 0.04)
    grad = Image.new("RGBA", (1, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(grad)
    c1, c2 = _rgb(top_tint), _rgb(bottom_tint)
    for yy in range(H):
        t = yy / max(1, H - 1)
        c = tuple(int(round(c1[i] + (c2[i] - c1[i]) * t)) for i in range(3))
        gd.point((0, yy), fill=(*c, 255))
    grad = grad.resize((W, H))
    img.alpha_composite(grad)
    draw = ImageDraw.Draw(img)

    _draw_title(services, img, draw, guide, colors, rcfg)
    y = 166
    y = _draw_kpis(services, img, draw, guide, colors, y)
    y += 20
    y = _draw_rewards(services, img, draw, guide, colors, y)
    y += 18

    days = list(guide.get("days") or [])[:7]
    y = _draw_tier_ruler(services, img, draw, guide, days, colors, y)
    if days:
        y += 14

    # Reserve readable risk/footer first, then give the rest to D1-D7.
    footer_h = int(rcfg.get("footer_height", 72) or 72)
    risk_items = tools.risk_items(guide)
    risk_h = 148 if risk_items else 0
    bottom_padding = 24
    plan_bottom = H - footer_h - risk_h - bottom_padding - (14 if risk_h else 0)
    gap = 10
    available = max(700, plan_bottom - y - gap * max(0, len(days) - 1))
    weights = _day_weights(days)
    total_w = sum(weights) or 1
    heights = [available * w / total_w for w in weights]
    min_h = 156
    heights = [max(min_h, h) for h in heights]
    scale = available / max(1, sum(heights))
    heights = [h * scale for h in heights]

    shared_action_size = int(rcfg.get("day_action_font_size", 22) or 22)
    # Equal metric-control size across normal/special days, based on the
    # smallest actual day card.
    metric_candidates = [max(72, int(round(h)) - 61 - 16) for h in heights] if heights else [84]
    shared_metric_area_h = max(72, min(104, min(metric_candidates)))

    cursor = y
    for i, info in enumerate(days):
        h = heights[i]
        y1 = int(round(cursor))
        y2 = int(round(plan_bottom if i == len(days) - 1 else y1 + h))
        _draw_day_card(services, img, draw, guide, info, (48, y1, W - 48, y2), colors, rcfg,
                       shared_action_size, shared_metric_area_h)
        cursor = y2 + gap

    if risk_items:
        risk_top = H - footer_h - risk_h - 12
        _draw_risk(services, img, draw, guide, colors, risk_top, H - footer_h - 10)

    _draw_footer(services, img, draw, guide, colors, footer_h)

    tools.save(img, out_path, guide, started=started)



def render(guide, out_path: Path, services):
    font_state = _install_theme_fonts(guide, services)
    try:
        return _render_impl(guide, out_path, services)
    finally:
        _restore_theme_fonts(services, font_state)
