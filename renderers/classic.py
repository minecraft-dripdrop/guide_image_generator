# -*- coding: utf-8 -*-
"""Classic clean/card renderer. Kept as the engine fallback renderer."""
import math
import re
import time
from pathlib import Path
from PIL import Image, ImageDraw, ImageOps, ImageFont, ImageFilter, ImageChops
from .shared import SharedRendererTools
from .reward_items import RewardItemRenderer

STYLE_IDS = ("classic_clean", "classic_cards")




# ---------------------------------------------------------------------------
# Classic-only helpers
#
# These used to be split across classic_header.py / classic_footer.py /
# classic_rewards.py.  They intentionally live here now so the entire classic
# theme is maintained as one renderer module.
# ---------------------------------------------------------------------------

def _classic_base_background(size, theme_cfg):
    colors = theme_cfg.get("colors") if isinstance(theme_cfg.get("colors"), dict) else {}
    return Image.new("RGBA", size, colors.get("background", "#F3F6FA"))


def _header_hex_rgb(value, fallback=(47, 93, 64)):
    if isinstance(value, (tuple, list)) and len(value) >= 3:
        try:
            return (int(value[0]), int(value[1]), int(value[2]))
        except Exception:
            return fallback
    text = str(value or "").strip()
    if len(text) == 7 and text.startswith("#"):
        try:
            return tuple(int(text[i:i + 2], 16) for i in (1, 3, 5))
        except ValueError:
            pass
    return fallback


def _relative_luminance(rgb):
    def channel(value):
        value = max(0.0, min(255.0, float(value))) / 255.0
        return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4

    r, g, b = (channel(v) for v in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast_ratio(a, b):
    la = _relative_luminance(a)
    lb = _relative_luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def _auto_text_color(background_color, primary):
    """Choose the most readable classic title color for the actual ribbon color."""
    bg = _header_hex_rgb(background_color, _header_hex_rgb(primary))
    candidates = (
        "#FFFBE8",       # classic warm white
        "#FFFFFF",
        "#17212B",
        "#243342",
    )
    return max(candidates, key=lambda color: _contrast_ratio(_header_hex_rgb(color), bg))


def _fit_font(draw, text, max_width, get_font, start=22, minimum=15, bold=False):
    for size in range(start, minimum - 1, -1):
        font = get_font(size, bold)
        bb = draw.textbbox((0, 0), text, font=font)
        if bb[2] - bb[0] <= max_width:
            return font, bb
    font = get_font(minimum, bold)
    return font, draw.textbbox((0, 0), text, font=font)


def _rgb_mix(a, b, t):
    ar, ag, ab = _header_hex_rgb(a)
    br, bg, bb = _header_hex_rgb(b)
    t = max(0.0, min(1.0, float(t)))
    return (
        round(ar + (br - ar) * t),
        round(ag + (bg - ag) * t),
        round(ab + (bb - ab) * t),
    )


def _horizontal_gradient(size, colors):
    width, height = map(int, size)
    width = max(1, width)
    height = max(1, height)
    palette = [c for c in colors if c] or ['#4E8C63']
    if len(palette) == 1:
        palette = [palette[0], palette[0]]
    stops = [i / max(1, len(palette) - 1) for i in range(len(palette))]
    layer = Image.new('RGBA', (width, height), (0, 0, 0, 0))
    px = layer.load()
    for x in range(width):
        pos = 0.0 if width == 1 else x / (width - 1)
        idx = 0
        while idx < len(stops) - 2 and pos > stops[idx + 1]:
            idx += 1
        left_stop = stops[idx]
        right_stop = stops[min(len(stops) - 1, idx + 1)]
        local_t = 0.0 if right_stop <= left_stop else (pos - left_stop) / (right_stop - left_stop)
        color = _rgb_mix(palette[idx], palette[min(len(palette) - 1, idx + 1)], local_t)
        for y in range(height):
            px[x, y] = (*color, 255)
    return layer


def _rounded_panel_layer(size, colors, radius=18, border_width=4, fill=(255, 255, 255, 244), inner_outline=(255, 255, 255, 145), shadow_alpha=34):
    width, height = map(int, size)
    width = max(1, width)
    height = max(1, height)
    scale = 3
    w, h = width * scale, height * scale
    sr = max(1, int(round(radius * scale)))
    bw = max(1, int(round(border_width * scale)))
    layer = Image.new('RGBA', (w, h), (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    if shadow_alpha:
        ld.rounded_rectangle((scale * 2, scale * 5, w - scale * 2, h - scale), radius=sr, fill=(0, 0, 0, shadow_alpha))
    ring = _horizontal_gradient((w, h), colors)
    ring_mask = Image.new('L', (w, h), 0)
    md = ImageDraw.Draw(ring_mask)
    md.rounded_rectangle((0, 0, w - 1, h - 1), radius=sr, fill=255)
    inset = bw
    md.rounded_rectangle((inset, inset, w - 1 - inset, h - 1 - inset), radius=max(1, sr - inset), fill=0)
    ring.putalpha(ring_mask)
    layer.alpha_composite(ring)
    inset_fill = bw + scale
    ld.rounded_rectangle(
        (inset_fill, inset_fill, w - 1 - inset_fill, h - 1 - inset_fill),
        radius=max(1, sr - inset_fill),
        fill=fill,
    )
    if inner_outline:
        ld.rounded_rectangle(
            (inset_fill + scale, inset_fill + scale, w - 1 - inset_fill - scale, h - 1 - inset_fill - scale),
            radius=max(1, sr - inset_fill - scale),
            outline=inner_outline,
            width=max(1, scale),
        )
    return layer.resize((width, height), Image.Resampling.LANCZOS)


def _paste_gradient_panel(base, box, colors, radius=18, border_width=4, fill=(255, 255, 255, 244), inner_outline=(255, 255, 255, 145), shadow_alpha=34):
    x1, y1, x2, y2 = map(int, box)
    if x2 <= x1 or y2 <= y1:
        return
    layer = _rounded_panel_layer((x2 - x1, y2 - y1), colors, radius=radius, border_width=border_width, fill=fill, inner_outline=inner_outline, shadow_alpha=shadow_alpha)
    base.alpha_composite(layer, (x1, y1))


def _styled_circle_avatar(path, size, outer_color, accent_color, fallback_text='Q'):
    size = max(1, int(size))
    if path and Path(path).exists():
        try:
            src = Image.open(path).convert('RGBA')
            side = min(src.width, src.height)
            left = (src.width - side) // 2
            top = (src.height - side) // 2
            src = src.crop((left, top, left + side, top + side)).resize((size, size), Image.Resampling.LANCZOS)
        except Exception:
            src = None
    else:
        src = None
    if src is None:
        src = Image.new('RGBA', (size, size), _header_hex_rgb(outer_color) + (255,))
        fd = ImageDraw.Draw(src)
        font = ImageFont.load_default()
        bb = fd.textbbox((0, 0), fallback_text, font=font)
        fd.text(((size - (bb[2] - bb[0])) / 2 - bb[0], (size - (bb[3] - bb[1])) / 2 - bb[1]), fallback_text, fill=(255, 255, 255, 245), font=font)
    mask = Image.new('L', (size, size), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, size - 1, size - 1), fill=255)
    src.putalpha(mask)

    outer = _header_hex_rgb(outer_color)
    accent = _header_hex_rgb(accent_color)
    pad = max(5, int(round(size * 0.12)))
    canvas = Image.new('RGBA', (size + pad * 2, size + pad * 2), (0, 0, 0, 0))
    d = ImageDraw.Draw(canvas)
    d.ellipse((pad - 1, pad + 3, pad + size + 1, pad + size + 5), fill=(0, 0, 0, 28))
    d.ellipse((0, 0, canvas.width - 2, canvas.height - 2), fill=(255, 255, 255, 228), outline=(255, 255, 255, 244), width=2)
    d.ellipse((3, 3, canvas.width - 5, canvas.height - 5), outline=outer + (245,), width=4)
    d.ellipse((7, 7, canvas.width - 9, canvas.height - 9), outline=accent + (210,), width=2)
    d.ellipse((canvas.width - 15, 9, canvas.width - 10, 14), fill=accent + (150,))
    d.ellipse((9, canvas.height - 15, 13, canvas.height - 11), fill=outer + (120,))
    canvas.alpha_composite(src, (pad, pad))
    return canvas


def _draw_header_divider(base, draw, y, primary, dark):
    """Classic V4-style separator without the former center capsule."""
    y = int(y)
    left, right = 38, base.width - 38
    dark_rgb = _header_hex_rgb(dark)
    primary_rgb = _header_hex_rgb(primary)
    pale = _rgb_mix(primary_rgb, (255, 255, 255), 0.58)

    # Restore the lighter V4 three-line rhythm.  The small center capsule/gem is
    # intentionally omitted, so the separator reads as a clean full-width rule.
    draw.line((left, y - 5, right, y - 5), fill=primary_rgb + (72,), width=1)
    draw.line((left, y, right, y), fill=dark_rgb + (172,), width=3)
    draw.line((left, y + 4, right, y + 4), fill=pale + (170,), width=2)


def _classic_title_box(base_width, cfg):
    """Classic main-title geometry.

    Old activity JSON files still carry the former 150px split-header height.
    The restored classic capsule keeps that visual weight without wasting the
    whole 280px legacy header area.
    """
    header_cfg = cfg.get("header") if isinstance(cfg, dict) and isinstance(cfg.get("header"), dict) else {}
    title_cfg = header_cfg.get("title") if isinstance(header_cfg.get("title"), dict) else {}
    try:
        raw_top = int(title_cfg.get("top", 18) or 18)
    except Exception:
        raw_top = 18
    # Legacy files commonly say top=30.  Pull the capsule up a little so title +
    # author read as one compact header stack.
    top = max(14, min(22, raw_top - 10 if raw_top >= 28 else raw_top))
    try:
        raw_h = int(title_cfg.get("height", 112) or 112)
    except Exception:
        raw_h = 112
    # 150px is the old split-header slot, not the desired capsule body height.
    height = 112 if raw_h >= 130 else max(100, min(116, raw_h))
    margin = max(32, min(46, int(round(base_width * 0.03))))
    return (margin, top, base_width - margin, top + height)


def get_header_height(cfg):
    """Height reserved by the classic title tray and its lower separator."""
    title_box = _classic_title_box(1080, cfg)
    return int(title_box[3] + 34)


def _directional_edge_mask(width, height, top_extent=0.55, left_extent=0.48, top_strength=1.0, left_strength=0.82):
    """Directional edge falloff used by the classic recessed title well."""
    width = max(1, int(width))
    height = max(1, int(height))
    masks = []

    top_span = max(1, int(round(height * max(0.0, min(1.0, float(top_extent))))))
    vals = []
    for yy in range(height):
        if yy < top_span:
            t = 1.0 - yy / max(1, top_span - 1)
            vals.append(max(0, min(255, int(255 * min(1.0, t * t * float(top_strength))))))
        else:
            vals.append(0)
    strip = Image.new("L", (1, height))
    strip.putdata(vals)
    masks.append(strip.resize((width, height), Image.Resampling.NEAREST))

    left_span = max(1, int(round(width * max(0.0, min(1.0, float(left_extent))))))
    vals = []
    for xx in range(width):
        if xx < left_span:
            t = 1.0 - xx / max(1, left_span - 1)
            vals.append(max(0, min(255, int(255 * min(1.0, t * t * float(left_strength))))))
        else:
            vals.append(0)
    strip = Image.new("L", (width, 1))
    strip.putdata(vals)
    masks.append(strip.resize((width, height), Image.Resampling.NEAREST))

    return ImageChops.lighter(masks[0], masks[1])


def _draw_header_facet_diamond(draw, cx, cy, rx, ry, primary):
    outer = [(cx, cy - ry), (cx + rx, cy), (cx, cy + ry), (cx - rx, cy)]
    outer = [(int(round(x)), int(round(y))) for x, y in outer]
    draw.polygon(outer, fill=_header_hex_rgb(primary) + (255,))
    draw.line(outer + [outer[0]], fill=_header_hex_rgb(_apply_local_tint(primary, -0.34)) + (240,), width=max(1, int(round(rx * 0.14))), joint="curve")
    draw.polygon(
        [(int(cx), int(cy - ry)), (int(cx + rx), int(cy)), (int(cx), int(cy))],
        fill=(255, 248, 198, 220),
    )
    draw.polygon(
        [(int(cx), int(cy)), (int(cx + rx), int(cy)), (int(cx), int(cy + ry))],
        fill=_header_hex_rgb(_apply_local_tint(primary, -0.12)) + (235,),
    )


def _draw_four_point_sparkle(draw, cx, cy, radius, fill):
    radius = max(2.0, float(radius))
    inner = radius * 0.22
    pts = [
        (cx, cy - radius), (cx + inner, cy - inner),
        (cx + radius, cy), (cx + inner, cy + inner),
        (cx, cy + radius), (cx - inner, cy + inner),
        (cx - radius, cy), (cx - inner, cy - inner),
    ]
    draw.polygon([(int(round(x)), int(round(y))) for x, y in pts], fill=fill)


def _apply_local_tint(color, tint):
    rgb = _header_hex_rgb(color)
    out = []
    for channel in rgb:
        if tint < 0:
            value = round(channel * (1 + tint))
        else:
            value = round(channel + (255 - channel) * tint)
        out.append(max(0, min(255, value)))
    return "#{:02X}{:02X}{:02X}".format(*out)


def _draw_classic_main_title_layer(services, size, fill_color, primary):
    """Reproduce the older classic recessed tray title language.

    Based on the user's earlier standalone ribbon implementation: deep tray,
    fixed double rim, vertical well gradient, directional top-left inner shadow,
    faceted side gems and restrained sparkles.  The former decorative line below
    the title text is intentionally omitted.
    """
    width, height = map(int, size)
    ss = 4
    sw, sh = max(1, width * ss), max(1, height * ss)
    layer = Image.new("RGBA", (sw, sh), (0, 0, 0, 0))

    # Use a colour slightly darker than the theme primary.  The caller's
    # fill_color is already adaptive, but the old tray looked best when the
    # recess stayed visibly darker than the patterned page background.
    tray_primary = services.apply_tint(primary, -0.17)

    body_y1 = int(sh * 0.15)
    body_y2 = int(sh * 0.86)
    body_h = body_y2 - body_y1
    body_x1 = int(sw * 0.040)
    body_x2 = int(sw * 0.960)
    radius = body_h // 2
    cy = (body_y1 + body_y2) // 2

    # Very light external shadow: enough to separate the tray from the page,
    # but the depth is mainly created by the bevel and inner shadow.
    outer_shadow_rgb = _header_hex_rgb(services.apply_tint(tray_primary, -0.58))
    shadow = Image.new("RGBA", layer.size, (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow)
    sd.rounded_rectangle(
        (body_x1 + ss, body_y1 + 2 * ss, body_x2 + ss, body_y2 + 3 * ss),
        radius=radius,
        fill=(*outer_shadow_rgb, 34),
    )
    shadow = shadow.filter(ImageFilter.GaussianBlur(max(1, int(1.55 * ss))))
    layer.alpha_composite(shadow)
    d = ImageDraw.Draw(layer)

    # Short tapered end caps from the older ribbon.
    point_len = int(body_h * 0.20)
    point_half = int(body_h * 0.18)
    for side in (-1, 1):
        anchor = body_x1 if side < 0 else body_x2
        d.polygon(
            [
                (anchor - side * int(point_len * 0.45), cy - point_half),
                (anchor - side * point_len, cy),
                (anchor - side * int(point_len * 0.45), cy + point_half),
                (anchor + side * int(point_len * 0.12), cy),
            ],
            fill=_header_hex_rgb(services.apply_tint(tray_primary, -0.04)) + (255,),
        )

    tray_base_rgb = _header_hex_rgb(services.apply_tint(tray_primary, -0.18))
    tray_fill_rgb = tuple(int(round(tray_base_rgb[i] * 0.86 + 36 * 0.14)) for i in range(3))
    d.rounded_rectangle((body_x1, body_y1, body_x2, body_y2), radius=radius, fill=(*tray_fill_rgb, 255))

    panel_inset = max(8, int(6.1 * ss))
    panel_x1 = body_x1 + panel_inset
    panel_y1 = body_y1 + panel_inset
    panel_x2 = body_x2 - panel_inset
    panel_y2 = body_y2 - panel_inset
    panel_radius = max(4, radius - panel_inset)

    # Recessed center well.  The top catches a little light, the lower half is
    # darker, exactly like the older implementation supplied by the user.
    gradient = Image.new("RGBA", layer.size, (0, 0, 0, 0))
    gd = ImageDraw.Draw(gradient)
    top_rgb = _header_hex_rgb(services.apply_tint(tray_primary, 0.08))
    mid_rgb = _header_hex_rgb(services.apply_tint(tray_primary, -0.01))
    bottom_rgb = _header_hex_rgb(services.apply_tint(tray_primary, -0.12))
    for yy in range(panel_y1, panel_y2 + 1):
        u = (yy - panel_y1) / max(1, panel_y2 - panel_y1)
        if u < 0.45:
            uu = u / 0.45
            rgb = _rgb_mix(top_rgb, mid_rgb, uu)
        else:
            uu = (u - 0.45) / 0.55
            rgb = _rgb_mix(mid_rgb, bottom_rgb, uu)
        gd.line((panel_x1, yy, panel_x2, yy), fill=rgb + (255,), width=1)
    mask = Image.new("L", layer.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((panel_x1, panel_y1, panel_x2, panel_y2), radius=panel_radius, fill=255)
    gradient.putalpha(mask)
    layer.alpha_composite(gradient)
    d = ImageDraw.Draw(layer)

    # Outer tray rim: deep hard edge plus one restrained warm highlight.
    tray_outline_rgb = tuple(max(0, min(255, int(round(c * 0.72)))) for c in tray_fill_rgb)
    tray_highlight_rgb = tuple(max(0, min(255, int(round(c * 0.52 + 255 * 0.48)))) for c in tray_fill_rgb)
    d.rounded_rectangle((body_x1, body_y1, body_x2, body_y2), radius=radius, outline=tray_outline_rgb + (248,), width=max(2, int(1.55 * ss)))
    outer_highlight_inset = max(2, int(1.8 * ss))
    d.rounded_rectangle(
        (body_x1 + outer_highlight_inset, body_y1 + outer_highlight_inset, body_x2 - outer_highlight_inset, body_y2 - outer_highlight_inset),
        radius=max(4, radius - outer_highlight_inset),
        outline=tray_highlight_rgb + (188,),
        width=max(1, int(0.82 * ss)),
    )

    # Top-left inner shadow from the old code.  This is what gives the well its
    # characteristic "pressed into a tray" feel instead of a flat rounded card.
    inset_pad = max(1, int(1.3 * ss))
    inner_box = (panel_x1 + inset_pad, panel_y1 + inset_pad, panel_x2 - inset_pad, panel_y2 - inset_pad)
    inner_radius = max(4, panel_radius - inset_pad)
    rim_shadow_rgb = _header_hex_rgb(services.apply_tint(tray_primary, -0.74))
    fill_shadow = Image.new("RGBA", layer.size, (*rim_shadow_rgb, 0))
    fsd = ImageDraw.Draw(fill_shadow)
    fsd.rounded_rectangle(inner_box, radius=inner_radius, fill=(*rim_shadow_rgb, 255))
    local_mask = _directional_edge_mask(
        max(1, inner_box[2] - inner_box[0] + 1),
        max(1, inner_box[3] - inner_box[1] + 1),
        top_extent=0.55,
        left_extent=0.48,
        top_strength=1.0,
        left_strength=0.82,
    )
    local_mask = local_mask.point(lambda a: max(0, min(255, int(a * 128 / 255))))
    local_mask = local_mask.filter(ImageFilter.GaussianBlur(max(1, int(1.2 * ss * 0.65))))
    rim_mask = Image.new("L", layer.size, 0)
    rim_mask.paste(local_mask, (inner_box[0], inner_box[1]))
    clipped = ImageChops.multiply(fill_shadow.getchannel("A"), rim_mask)
    fill_shadow.putalpha(clipped)
    layer.alpha_composite(fill_shadow)
    d = ImageDraw.Draw(layer)

    # Light lip along the well edge.
    rim_highlight_inset = max(1, int(1.5 * ss))
    d.rounded_rectangle(
        (panel_x1 + rim_highlight_inset, panel_y1 + rim_highlight_inset, panel_x2 - rim_highlight_inset, panel_y2 - rim_highlight_inset),
        radius=max(4, panel_radius - rim_highlight_inset),
        outline=(255, 249, 230, 210),
        width=max(1, int(0.78 * ss)),
    )

    # Large faceted gems, short inner rails and small outside sparkles.  These
    # retain the old light/dark facet relationship the user preferred.
    for side in (-1, 1):
        inner_x = body_x1 + body_h * 0.48 if side < 0 else body_x2 - body_h * 0.48
        outer_x = body_x1 - body_h * 0.47 if side < 0 else body_x2 + body_h * 0.47
        gem_color = services.apply_tint(tray_primary, 0.48)
        _draw_header_facet_diamond(d, inner_x, cy, body_h * 0.115, body_h * 0.115, gem_color)
        _draw_four_point_sparkle(
            d, outer_x, cy, body_h * 0.095,
            _header_hex_rgb(services.apply_tint(tray_primary, 0.66)) + (225,),
        )
        if side < 0:
            line = (inner_x + body_h * 0.20, cy, inner_x + body_h * 0.55, cy)
        else:
            line = (inner_x - body_h * 0.55, cy, inner_x - body_h * 0.20, cy)
        d.line(tuple(int(round(v)) for v in line), fill=(255, 255, 255, 120), width=max(1, int(0.75 * ss)))

        sparkle_x = inner_x + side * body_h * 0.28
        _draw_four_point_sparkle(d, sparkle_x, cy - body_h * 0.27, body_h * 0.038, (255, 244, 177, 210))
        _draw_four_point_sparkle(d, sparkle_x + side * body_h * 0.10, cy + body_h * 0.27, body_h * 0.028, (255, 255, 255, 175))

    # IMPORTANT: the old function also had a decorative divider under the title
    # text.  The user explicitly asked to remove it, so nothing is drawn there.
    return layer.resize((width, height), Image.Resampling.LANCZOS)


def draw_split_header(services, base, draw, guide, cfg, primary):
    """Draw the restored classic main-title capsule.

    The function keeps its historical name only for compatibility with preview
    callers; the visual is a single wide centered capsule, matching the classic
    reference rather than the compact section-title style.
    """
    theme_cfg = guide.get("theme_config") if isinstance(guide.get("theme_config"), dict) else {}
    art_cfg = theme_cfg.get("classic_art") if isinstance(theme_cfg.get("classic_art"), dict) else {}
    title_art = art_cfg.get("header_title") if isinstance(art_cfg.get("header_title"), dict) else {}
    header_cfg = cfg.get("header") if isinstance(cfg.get("header"), dict) else {}
    title_cfg = header_cfg.get("title") if isinstance(header_cfg.get("title"), dict) else {}

    title = services.clean(str(guide.get("title") or "活动攻略"))
    subtitle = services.clean(str(guide.get("subtitle") or ""))
    # Keep an existing separator but normalize it to the classic thin divider.
    if subtitle:
        shown_title = f"{title} | {subtitle}"
    else:
        shown_title = title.replace("｜", " | ")

    try:
        tint = float(title_art.get("primary_tint", theme_cfg.get("title_primary_tint", -0.42)) or -0.42)
    except Exception:
        tint = -0.42
    tint = min(tint, -0.12)
    fill_color = services.apply_tint(primary, tint)

    auto_color = title_art.get("auto_color", True) is not False
    configured_color = title_art.get("text_color") or title_cfg.get("text_color")
    if auto_color or str(configured_color or "").lower() in {"auto", "adaptive", "auto_contrast", "auto_readable"}:
        text_color = _auto_text_color(fill_color, primary)
    else:
        text_color = str(configured_color or "#FFFBE8")

    box = _classic_title_box(base.width, cfg)
    x1, y1, x2, y2 = box
    layer = _draw_classic_main_title_layer(services, (x2 - x1, y2 - y1), fill_color, primary)
    base.alpha_composite(layer, (x1, y1))

    try:
        configured_max = int(title_cfg.get("font_size", 56) or 56)
    except Exception:
        configured_max = 56
    try:
        configured_min = int(title_cfg.get("min_font_size", 40) or 40)
    except Exception:
        configured_min = 40

    # Keep the current font family/weight, but deliberately leave breathing room
    # around the ink.  The legacy 56px setting was appropriate for the much taller
    # split header; inside the restored recessed tray it visually touches the rims.
    max_size = max(44, min(50, configured_max))
    min_size = max(32, min(max_size, configured_min))

    tray_body_top = y1 + int(round((y2 - y1) * 0.15))
    tray_body_bottom = y1 + int(round((y2 - y1) * 0.86))
    tray_body_h = max(1, tray_body_bottom - tray_body_top)
    side_pad = max(126, int((x2 - x1) * 0.125))
    max_text_width = max(80, (x2 - x1) - side_pad * 2)
    max_ink_height = max(28, tray_body_h - 22)

    font = None
    bb = None
    for size in range(max_size, min_size - 1, -1):
        candidate = services.get_font(size, True)
        candidate_bb = draw.textbbox((0, 0), shown_title, font=candidate)
        ink_w = candidate_bb[2] - candidate_bb[0]
        ink_h = candidate_bb[3] - candidate_bb[1]
        if ink_w <= max_text_width and ink_h <= max_ink_height:
            font, bb = candidate, candidate_bb
            break
    if font is None:
        font = services.get_font(min_size, True)
        bb = draw.textbbox((0, 0), shown_title, font=font)

    # Center by the real glyph ink bounds, not the font em box.  A tiny downward
    # optical correction keeps CJK titles visually centered in the recessed well.
    visual_cx = (x1 + x2) / 2
    visual_cy = (tray_body_top + tray_body_bottom) / 2
    tx = visual_cx - (bb[0] + bb[2]) / 2
    ty = visual_cy - (bb[1] + bb[3]) / 2 + 1
    shadow = services.apply_tint(fill_color, -0.55)
    draw.text((tx + 1, ty + 2), shown_title, font=font, fill=shadow)
    draw.text((tx, ty), shown_title, font=font, fill=text_color)
    return get_header_height(cfg)


def _footer_hex_rgb(value, fallback=(78, 140, 99)):
    text = str(value or "").strip()
    if len(text) == 7 and text.startswith("#"):
        try:
            return tuple(int(text[i:i + 2], 16) for i in (1, 3, 5))
        except ValueError:
            pass
    return fallback


def footer_config(cfg):
    section = cfg.get("group_footer") if isinstance(cfg, dict) else {}
    return section if isinstance(section, dict) else {}


def _circle_avatar(path, size, fallback_color):
    accent = _header_hex_rgb(fallback_color)
    outer = _rgb_mix(accent, (255, 255, 255), 0.35)
    return _styled_circle_avatar(path, size, outer, accent, fallback_text='群')


def _gradient(width, height, left, center, right):
    width, height = max(1, int(width)), max(1, int(height))
    layer = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    left = _footer_hex_rgb(left)
    center = _footer_hex_rgb(center)
    right = _footer_hex_rgb(right)
    split = max(1, int(width * 0.48))
    for x in range(width):
        if x <= split:
            t = x / max(1, split)
            a, b = left, center
        else:
            t = (x - split) / max(1, width - 1 - split)
            a, b = center, right
        color = tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))
        d.line((x, 0, x, height), fill=(*color, 255), width=1)
    return layer


def _paste_decoration(base, path, box, mirror=False, opacity=255):
    if path is None or not Path(path).exists():
        return False
    x1, y1, x2, y2 = map(int, box)
    if x2 <= x1 or y2 <= y1:
        return False
    try:
        im = Image.open(path).convert("RGBA")
        if mirror:
            im = ImageOps.mirror(im)
        scale = min((x2 - x1) / max(1, im.width), (y2 - y1) / max(1, im.height))
        nw = max(1, int(im.width * scale))
        nh = max(1, int(im.height * scale))
        im = im.resize((nw, nh), Image.Resampling.LANCZOS)
        if opacity < 255:
            im.putalpha(im.getchannel("A").point(lambda a: int(a * opacity / 255)))
        px = x1 if not mirror else x2 - nw
        py = y2 - nh
        base.alpha_composite(im, (px, py))
        return True
    except Exception:
        return False


def draw_group_footer(services, base, draw, box, text, primary, icon_path=None, cfg=None, palette=None):
    """Draw group avatar + message as one horizontally centered footer group."""
    x1, y1, x2, y2 = map(int, box)
    w, h = max(1, x2 - x1), max(1, y2 - y1)
    fcfg = footer_config(cfg or {})
    palette = palette or {}

    layer = _gradient(
        w,
        h,
        palette.get("footer_left", services.apply_tint(primary, 0.86)),
        palette.get("footer_center", services.apply_tint(primary, 0.94)),
        palette.get("footer_right", services.apply_tint(primary, 0.84)),
    )
    ld = ImageDraw.Draw(layer)
    ld.line((0, 1, w, 1), fill=(255, 255, 255, 190), width=1)
    base.alpha_composite(layer, (x1, y1))

    left_raw = fcfg.get("left_decoration") or fcfg.get("left_decor")
    right_raw = fcfg.get("right_decoration") or fcfg.get("right_decor")
    left_path = services.resolve_path(cfg or {}, left_raw) if left_raw else None
    right_path = services.resolve_path(cfg or {}, right_raw) if right_raw else None
    decor_h = max(10, min(h, int(fcfg.get("decoration_height", h) or h)))
    decor_w = int(fcfg.get("decoration_width", max(100, int(w * 0.14))) or max(100, int(w * 0.14)))
    opacity = max(0, min(255, int(fcfg.get("decoration_opacity", 255) or 255)))
    if left_path:
        _paste_decoration(base, left_path, (x1, y2 - decor_h, x1 + decor_w, y2), opacity=opacity)
    if right_path:
        _paste_decoration(base, right_path, (x2 - decor_w, y2 - decor_h, x2, y2), opacity=opacity)
    elif left_path and bool(fcfg.get("mirror_left_to_right", True)):
        _paste_decoration(base, left_path, (x2 - decor_w, y2 - decor_h, x2, y2), mirror=True, opacity=opacity)

    icon_size = max(28, min(h - 6, int(fcfg.get("icon_size", min(h - 8, 44)) or min(h - 8, 44))))
    gap = int(fcfg.get("content_gap", 12) or 12)
    m = re.search(r"(\d{6,})\s*$", str(text))
    number = m.group(1) if m else ""
    prefix = services.clean(str(text)[:m.start()]) if m else services.clean(str(text))

    reserved = max(decor_w if (left_path or right_path) else 30, 30)
    max_content_w = max(220, w - 2 * reserved)
    chosen = None
    for size in range(20, 11, -1):
        pf = services.get_font(size, False)
        nf = services.get_font(size + 2, True)
        pbb = draw.textbbox((0, 0), prefix, font=pf)
        nbb = draw.textbbox((0, 0), number, font=nf)
        number_gap = 13 if number else 0
        text_w = (pbb[2] - pbb[0]) + number_gap + (nbb[2] - nbb[0])
        total_w = icon_size + gap + text_w
        if total_w <= max_content_w:
            chosen = (pf, nf, pbb, nbb, number_gap, total_w)
            break
    if chosen is None:
        pf = services.get_font(12, False)
        nf = services.get_font(14, True)
        pbb = draw.textbbox((0, 0), prefix, font=pf)
        nbb = draw.textbbox((0, 0), number, font=nf)
        number_gap = 10 if number else 0
        total_w = icon_size + gap + (pbb[2] - pbb[0]) + number_gap + (nbb[2] - nbb[0])
        chosen = (pf, nf, pbb, nbb, number_gap, total_w)

    pf, nf, pbb, nbb, number_gap, total_w = chosen
    start_x = x1 + (w - total_w) / 2
    icon_y = y1 + (h - icon_size) / 2
    avatar = _circle_avatar(icon_path, icon_size, primary)
    base.alpha_composite(avatar, (int(start_x), int(icon_y)))

    text_x = start_x + icon_size + gap
    cy = (y1 + y2) / 2
    ph = pbb[3] - pbb[1]
    draw.text(
        (text_x, cy - ph / 2 - pbb[1]), prefix, font=pf,
        fill=palette.get("footer_text", services.apply_tint(primary, -0.45)),
    )
    if number:
        nx = text_x + (pbb[2] - pbb[0]) + number_gap
        nh = nbb[3] - nbb[1]
        draw.text(
            (nx, cy - nh / 2 - nbb[1]), number, font=nf,
            fill=palette.get("footer_number", services.apply_tint(primary, -0.58)),
        )


QUALITY_ORDER = {
    "white": 1, "green": 2, "blue": 3, "purple": 4, "orange": 5,
    "red": 6, "pink": 7, "chaoyue": 8, "jueshi": 9,
}
QUALITY_COLORS = {
    "white": "#B8C0C8",
    "green": "#59A86C",
    "blue": "#5A7FDB",
    "purple": "#9B63D3",
    "orange": "#E28B3D",
    "red": "#D95B5B",
    "pink": "#D96A9A",
    "chaoyue": "#9A62FF",
    "jueshi": "#67D9C7",
}


def node_weight(node):
    if not isinstance(node, dict):
        return 1
    typ = node.get("type", "item")
    if typ == "item":
        return 1
    if typ == "bundle":
        return max(1, sum(node_weight(x) for x in (node.get("items") or [])))
    if typ == "choice":
        return max(2, sum(node_weight(x) for x in (node.get("options") or [])))
    return 1


def pack_units(units, max_slots=4):
    rows = []
    current = []
    used = 0
    for unit in units or []:
        weight = max(1, node_weight(unit))
        if current and used + weight > max_slots:
            rows.append(current)
            current = []
            used = 0
        current.append(unit)
        used += weight
    if current:
        rows.append(current)
    return rows


class ClassicRewardRenderer:
    def __init__(self, services, guide):
        self.s = services
        self.guide = guide
        self.cfg = guide.get("cfg") or {}
        self.palette = guide.get("palette") or {}
        self.items = RewardItemRenderer(services, guide)

    def quality(self, node):
        if not isinstance(node, dict):
            return ""
        typ = node.get("type", "item")
        if typ == "item":
            return self.items.resolve(node).get("quality") or ""
        children = node.get("options") if typ == "choice" else node.get("items")
        best = ""
        for child in children or []:
            q = self.quality(child)
            if QUALITY_ORDER.get(q, 0) > QUALITY_ORDER.get(best, 0):
                best = q
        return best

    def _quality_color(self, q):
        return QUALITY_COLORS.get(str(q or "").lower(), self.palette.get("primary", "#4E8C63"))

    def _quality_stops(self, q):
        q = str(q or "").lower()
        if q == "chaoyue":
            return ["#77D3FF", "#6485FF", "#D56BFF"]
        if q == "jueshi":
            return ["#98F27C", "#62CD87", "#67D9C7"]
        base = self._quality_color(q)
        return [self.s.apply_tint(base, 0.20), base, self.s.apply_tint(base, -0.08)]

    def _node_palette(self, nodes):
        if isinstance(nodes, dict):
            nodes = [nodes]
        nodes = [n for n in (nodes or []) if isinstance(n, dict)]
        if not nodes:
            return self._quality_stops("")
        if len(nodes) == 1:
            return self._quality_stops(self.quality(nodes[0]))
        colors = []
        for index, node in enumerate(nodes):
            stops = self._quality_stops(self.quality(node))
            if index == 0:
                colors.extend([stops[0], stops[-1]])
            else:
                colors.extend([stops[0], stops[-1]])
        return colors

    def _item_text_color(self, q):
        base = self._quality_color(q)
        if q == "white":
            return self.s.apply_tint(base, -0.42)
        return self.s.apply_tint(base, -0.14)

    def _card_fill(self):
        return self.palette.get("reward_card", self.palette.get("card", "#FFFFFF"))

    def _draw_shell(self, base, box, colors, radius=16, border_width=2, fill=None):
        _paste_gradient_panel(
            base,
            box,
            colors,
            radius=radius,
            border_width=border_width,
            fill=fill or (255, 255, 255, 245),
            inner_outline=(255, 255, 255, 110),
            shadow_alpha=18,
        )

    def _draw_item_content(self, base, draw, box, item, compact=False):
        x1, y1, x2, y2 = map(int, box)
        resolved = self.items.resolve(item)
        q = resolved.get("quality") or "white"
        box_w = max(1, x2 - x1)
        box_h = max(1, y2 - y1)
        side_cap = 92 if compact else 98
        icon_side = min(box_w - 20, max(72, int(box_h * (0.52 if compact else 0.58))), side_cap)
        icon_side = max(58, icon_side)
        icon_x1 = int(x1 + (box_w - icon_side) / 2)
        icon_y1 = int(y1 + (6 if compact else 8))
        icon_box = (icon_x1, icon_y1, icon_x1 + icon_side, icon_y1 + icon_side)
        # Restore the project's original quality-frame artwork (including its gradient/background),
        # rather than replacing it with a code-drawn outline.
        self.items.draw_icon(base, item, icon_box, draw_quality_frame=True, assume_quality_frame=True)

        if not resolved.get("icon_path"):
            inner = (icon_x1 + 18, icon_y1 + 16, icon_x1 + icon_side - 18, icon_y1 + icon_side - 18)
            self.s.rounded(draw, inner, 10, self.palette.get("light", "#EEF3F7"))
            self.s.draw_center(draw, inner, "物品图", self.palette.get("dark", "#34495E"), max_size=13, min_size=10, bold=True, max_lines=1)

        qty = self.s.clean(str(item.get("qty") or ""))
        name = self.s.clean(str(item.get("name") or "物品"))
        label = name + ((" ×" + qty) if qty else "")
        text_top = icon_y1 + icon_side + (5 if compact else 6)
        self.s.draw_center(
            draw,
            (x1 + 5, text_top, x2 - 5, y2 - 4),
            label,
            self._item_text_color(q),
            max_size=14 if compact else 15,
            min_size=10,
            bold=True,
            max_lines=2,
            line_gap=1,
        )
        return resolved

    def draw_item(self, base, draw, box, item):
        resolved = self.items.resolve(item)
        self._draw_shell(base, box, self._quality_stops(resolved.get("quality") or "white"), radius=17, border_width=2, fill=(255, 255, 255, 246))
        self._draw_item_content(base, draw, box, item, compact=False)

    def _draw_connector(self, draw, box, text):
        self.s.draw_center(
            draw,
            box,
            text,
            self.palette.get("secondary_text", self.palette.get("dark", "#4E5966")),
            max_size=19,
            min_size=14,
            bold=True,
            max_lines=1,
        )

    def _draw_inline_bundle(self, base, draw, box, bundle):
        x1, y1, x2, y2 = map(int, box)
        items = [x for x in (bundle.get("items") or []) if isinstance(x, dict)]
        if not items:
            return
        gap = 18
        usable = max(1, x2 - x1 - gap * max(0, len(items) - 1))
        unit_w = usable / max(1, len(items))
        cursor = x1
        slots = []
        for child in items:
            b = (int(round(cursor)), y1, int(round(cursor + unit_w)), y2)
            slots.append(b)
            self._draw_item_content(base, draw, b, child, compact=True)
            cursor = b[2] + gap
        for i in range(1, len(slots)):
            cx = (slots[i - 1][2] + slots[i][0]) // 2
            self._draw_connector(draw, (cx - 10, y1 + 4, cx + 10, y2 - 4), "+")

    def draw_bundle(self, base, draw, box, bundle):
        items = [x for x in (bundle.get("items") or []) if isinstance(x, dict)]
        self._draw_shell(base, box, self._node_palette(items), radius=17, border_width=2, fill=(255, 255, 255, 246))
        self._draw_inline_bundle(base, draw, (int(box[0]) + 6, int(box[1]) + 3, int(box[2]) - 6, int(box[3]) - 3), bundle)

    def draw_choice(self, base, draw, box, choice):
        x1, y1, x2, y2 = map(int, box)
        options = [x for x in (choice.get("options") or []) if isinstance(x, dict)]
        if not options:
            return
        self._draw_shell(base, box, self._node_palette(options), radius=17, border_width=2, fill=(255, 255, 255, 246))
        pad = 10
        gap = 28
        weights = []
        for node in options:
            typ = node.get("type", "item")
            if typ == "bundle":
                weights.append(max(1.3, min(2.0, len(node.get("items") or []))))
            else:
                weights.append(1.0)
        usable = max(1, x2 - x1 - pad * 2 - gap * max(0, len(options) - 1))
        total = max(1.0, sum(weights))
        cursor = x1 + pad
        boxes = []
        for node, weight in zip(options, weights):
            width = usable * weight / total
            b = (int(round(cursor)), y1 + 4, int(round(cursor + width)), y2 - 4)
            boxes.append(b)
            typ = node.get("type", "item")
            if typ == "bundle":
                self._draw_inline_bundle(base, draw, b, node)
            else:
                self._draw_item_content(base, draw, b, node, compact=True)
            cursor = b[2] + gap
        for i in range(1, len(boxes)):
            cx = (boxes[i - 1][2] + boxes[i][0]) // 2
            self._draw_connector(draw, (cx - 16, y1 + 8, cx + 16, y2 - 8), "或")

    def draw_node(self, base, draw, box, node):
        typ = (node or {}).get("type", "item")
        if typ == "choice":
            self.draw_choice(base, draw, box, node)
        elif typ == "bundle":
            self.draw_bundle(base, draw, box, node)
        else:
            self.draw_item(base, draw, box, node)


def render(guide, out_path: Path, services):
    W, H = services.W, services.H
    apply_tint = services.apply_tint
    build_render_kpis = services.build_render_kpis
    build_reward_display_units = services.build_reward_display_units
    choose_shared_kpi_label_size = services.choose_shared_kpi_label_size
    clean = services.clean
    draw_action_content = services.draw_action_content
    draw_center = services.draw_center
    draw_day_metric_bubbles = services.draw_day_metric_bubbles
    draw_decorative_title = services.draw_decorative_title
    draw_kpi_card = services.draw_kpi_card
    draw_left = services.draw_left
    draw_module_frame = services.draw_module_frame
    draw_special_day_badge = services.draw_special_day_badge
    draw_warning_icon = services.draw_warning_icon
    get_font = services.get_font
    recommended_special_badge_width = services.recommended_special_badge_width
    resolve_path = services.resolve_path
    rounded = services.rounded
    text_width = services.text_width
    render_started = time.perf_counter()
    rtools = SharedRendererTools(services)
    p = guide["palette"]
    primary, dark, light = p["primary"], p["dark"], p["light"]
    theme_cfg = guide.get("theme_config") or {}
    theme_colors = theme_cfg.get("colors") if isinstance(theme_cfg.get("colors"), dict) else {}
    text_color = theme_colors.get("text", "#26384A")
    cfg = dict(guide.get("cfg") or {})
    img = _classic_base_background((W, H), theme_cfg)

    # Classic-only artwork layer. The source pattern is treated as tone information
    # rather than a fixed blue bitmap: every palette variant recolors it from the
    # current primary/dark colours, so green/gold/blue/purple/red/cyan all keep the
    # same motif geometry while changing hue automatically.
    classic_art = theme_cfg.get("classic_art") if isinstance(theme_cfg.get("classic_art"), dict) else {}

    def _asset_path(raw):
        text = str(raw or "").strip()
        if not text:
            return None
        # Classic assets live beside guide_image_generator.py in project assets/.
        resolved = resolve_path(cfg, text)
        if resolved and resolved.exists():
            return resolved
        script_root = Path(str(cfg.get("_script_dir") or ""))
        if script_root:
            candidate = (script_root / text).resolve()
            if candidate.exists():
                return candidate
        return None

    def _rgb(hex_color, fallback=(80, 120, 100)):
        text = str(hex_color or "").strip()
        if len(text) == 7 and text.startswith("#"):
            try:
                return tuple(int(text[i:i+2], 16) for i in (1, 3, 5))
            except ValueError:
                pass
        return fallback

    def _mix_hex(a, b, t):
        t = max(0.0, min(1.0, float(t)))
        ar, ag, ab = _rgb(a)
        br, bg, bb = _rgb(b)
        vals = (
            round(ar + (br-ar)*t),
            round(ag + (bg-ag)*t),
            round(ab + (bb-ab)*t),
        )
        return "#{:02X}{:02X}{:02X}".format(*vals)

    pattern_cfg = classic_art.get("variant_background") if isinstance(classic_art.get("variant_background"), dict) else {}
    if pattern_cfg.get("enabled", True) is not False:
        pattern_path = _asset_path(pattern_cfg.get("path"))
        if not pattern_path:
            pattern_path = _asset_path("assets/bb_capymon_bg.png")
        if pattern_path and pattern_path.is_file():
            try:
                source = Image.open(pattern_path).convert("RGBA")
                # Ignore the source hue/alpha and keep only its luminance map. This
                # makes the supplied blue artwork a reusable palette-aware texture.
                gray = ImageOps.grayscale(source.convert("RGB"))
                gray = ImageOps.autocontrast(gray, cutoff=1)
                base_tint = float(pattern_cfg.get("base_tint", 0.08) or 0.08)
                dark_mix = float(pattern_cfg.get("motif_dark_mix", 0.64) or 0.64)
                high = apply_tint(primary, base_tint)
                low = _mix_hex(primary, dark, dark_mix)
                tile = ImageOps.colorize(gray, black=low, white=high).convert("RGBA")
                tile.putalpha(255)

                tile_width_ratio = max(0.45, min(2.5, float(pattern_cfg.get("tile_width_ratio", 1.0) or 1.0)))
                target_w = max(1, int(round(W * tile_width_ratio)))
                target_h = max(1, int(round(tile.height * (target_w / max(1, tile.width)))))
                tile = tile.resize((target_w, target_h), Image.Resampling.LANCZOS)

                pattern_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
                y0 = -int(float(pattern_cfg.get("offset_y_ratio", 0.0) or 0.0) * target_h)
                row = 0
                while y0 < H:
                    # Alternating half-tile offset avoids obvious vertical columns
                    # if a future pattern asset is not perfectly seamless.
                    x0 = -target_w // 2 if (row % 2 and bool(pattern_cfg.get("stagger", False))) else 0
                    while x0 < W:
                        pattern_layer.alpha_composite(tile, (x0, y0))
                        x0 += target_w
                    y0 += target_h
                    row += 1

                opacity = max(0.0, min(1.0, float(pattern_cfg.get("opacity", 1.0) or 1.0)))
                if opacity > 0:
                    if opacity < 0.999:
                        alpha = pattern_layer.getchannel("A").point(lambda a: int(round(a * opacity)))
                        pattern_layer.putalpha(alpha)
                    img.alpha_composite(pattern_layer)
            except Exception:
                # Artwork is decorative only; a bad optional asset must never stop
                # guide generation. The normal classic background remains intact.
                pass

    d = ImageDraw.Draw(img)
    panel_fill = theme_colors.get("panel", "#FBFEFC")
    panel_secondary = theme_colors.get("panel_secondary", theme_colors.get("card_secondary", "#F8FCFA"))
    card_fill = theme_colors.get("card", "#FFFFFF")
    card_highlight = theme_colors.get("card_highlight", apply_tint(primary, 0.88))
    card_border = theme_colors.get("card_border", p.get("chip", light))
    title_text_color = theme_colors.get("title_text", "#FFFFFF")
    risk_cfg = theme_cfg.get("risk") if isinstance(theme_cfg.get("risk"), dict) else {}
    risk_primary = risk_cfg.get("primary", "#D96A54")
    risk_panel = risk_cfg.get("panel", "#FFF9F7")
    risk_bubble = risk_cfg.get("bubble", "#FCEDE9")
    risk_border = risk_cfg.get("border", "#EDB9B0")
    risk_text = risk_cfg.get("text", "#A33B33")
    # Classic owns its complete title/author stack.  Keep the activity-level
    # typography hints (notably the original 56px title size), while the classic
    # geometry helper translates obsolete 280/150px split-header dimensions into
    # the restored wide capsule layout.
    header_cfg = dict(cfg.get("header") or {}) if isinstance(cfg.get("header"), dict) else {}
    title_cfg = dict(header_cfg.get("title") or {}) if isinstance(header_cfg.get("title"), dict) else {}
    header_cfg["title"] = title_cfg
    cfg["header"] = header_cfg
    footer_cfg = footer_config(cfg)
    watermark_group_icon_size = int(footer_cfg.get("icon_size", cfg.get("watermark_group_icon_size", 44)) or 44)
    watermark_h = int(footer_cfg.get("height", max(58, watermark_group_icon_size + 12)) or max(58, watermark_group_icon_size + 12))
    watermark_h = max(62, min(76, watermark_h))

    # 顶部标题区只保留标题横条；背景由主题自身控制，不再读取活动 Banner/背景图。
    header_h = draw_split_header(services, img, d, guide, cfg, primary)
    # No QQ avatar / author capsule in the classic header for now.
    _draw_header_divider(img, d, header_h - 12, primary, dark)

    y = header_h + 6

    # Restore the previous classic capsule artwork (the engine's
    # draw_decorative_title style) while forcing all three section headings to use
    # the same measured capsule width.  A tiny proxy only overrides the helper's
    # first text measurement; all later font-fit/drawing calls use the real draw
    # object, so the visual style remains the established classic style.
    section_title_h = 68
    section_title_bounds = (72, W-72)
    section_title_reference = "执行计划｜目标档位必看"
    reference_font = get_font(30, True)
    reference_bb = d.textbbox((0, 0), section_title_reference, font=reference_font)

    class _FixedFirstMeasureDraw:
        def __init__(self, real_draw, fixed_bbox):
            self._real = real_draw
            self._fixed_bbox = fixed_bbox
            self._first_textbbox = True
        def textbbox(self, *args, **kwargs):
            if self._first_textbbox:
                self._first_textbbox = False
                return self._fixed_bbox
            return self._real.textbbox(*args, **kwargs)
        def __getattr__(self, name):
            return getattr(self._real, name)

    def _section_title_box(section_top):
        return (
            section_title_bounds[0], int(section_top-4),
            section_title_bounds[1], int(section_top-4+section_title_h)
        )

    def _draw_fixed_section_title(section_top, text, fill_color):
        box = _section_title_box(section_top)
        proxy = _FixedFirstMeasureDraw(d, reference_bb)
        draw_decorative_title(img, proxy, box, text, fill_color, cfg)
        return box

    # KPI 卡片：支持多预算资源自动拆分为多张卡（如钻石预算、翡翠预算）。
    render_kpis = build_render_kpis(guide["kpis"][:3], cfg)
    if render_kpis:
        left, right = 48, W-48
        gap_x = 12
        gap_y = 10
        # V35.79：经典简洁顶部 KPI 改为单行紧凑卡。多资源预算最多会
        # 展开到 4 张 KPI，直接四栏排开，避免 2×2 占掉一整块 Day 高度。
        area_h = 94
        count = len(render_kpis)

        if count <= 4:
            cols = count
            rows = 1
        else:
            cols = 3
            rows = math.ceil(count / 3)

        card_w = (right-left-gap_x*(cols-1))/max(1, cols)

        shared_label_size = None
        if count and rows == 1:
            sample_card_w = card_w
            sample_circle = min(72, max(50, area_h-18), max(50, int(sample_card_w*0.24)))
            label_max_w = int(sample_card_w - (11 + sample_circle + 10 + 9))
            shared_label_size = choose_shared_kpi_label_size(
                d, [it["label"] for it in render_kpis], label_max_w,
                max_size=21, min_size=12
            )

        for i, item in enumerate(render_kpis):
            row = i // cols
            col = i % cols
            # 如果最后一行只有 1 张，自动居中并占满整行。
            if rows > 1 and row == rows - 1 and (count % cols == 1) and i == count - 1:
                x1 = left
                x2 = right
            else:
                x1 = round(left + col*(card_w+gap_x))
                x2 = round(x1 + card_w)
            y1 = round(y + row*(area_h+10))
            draw_kpi_card(
                img, d, (x1, y1, x2, y1 + area_h),
                item["label"], item["value"], p, item.get("icon"),
                budget_components=item.get("budget_components") or [],
                label_size=shared_label_size
            )
        y += rows*area_h + (rows-1)*gap_y + 8

    # 可兑换道具：经典主题自己负责视觉层。每个叶子物品都有独立品质外框，
    # choice / bundle 只负责表达“或 / +”关系，因此 A 或 (B + C) 不会被画成 A/B/C 三选一。
    reward_items = guide.get("reward_items") or []
    if reward_items:
        section_top = y
        units = build_reward_display_units(reward_items)
        reward_renderer = ClassicRewardRenderer(services, guide)
        unit_rows = pack_units(units, max_slots=4)
        gap_x = 14
        gap_y = 9
        item_h = 122
        rows = max(1, len(unit_rows))
        panel_top = section_top + 14
        content_y = section_top + 58
        panel_bottom = content_y + rows * item_h + max(0, rows - 1) * gap_y + 12
        draw_module_frame(img, d, (34, panel_top, W - 34, panel_bottom), primary, fill=panel_fill, radius=22, ornate=True)
        _draw_fixed_section_title(section_top, "可兑换道具", primary)

        current_y = content_y
        for row_units in unit_rows:
            total_slots = sum(max(1, node_weight(unit)) for unit in row_units)
            usable_w = W - 112
            unit_gap_total = gap_x * max(0, len(row_units) - 1)
            slot_w = (usable_w - unit_gap_total) / max(1, total_slots)
            row_total_w = slot_w * total_slots + unit_gap_total
            cursor_x = (W - row_total_w) / 2
            for unit in row_units:
                weight = max(1, node_weight(unit))
                unit_w = slot_w * weight
                x1 = int(round(cursor_x))
                x2 = int(round(x1 + unit_w))
                y1 = int(current_y)
                y2 = int(y1 + item_h)
                reward_renderer.draw_node(img, d, (x1, y1, x2, y2), unit)
                cursor_x = x2 + gap_x
            current_y += item_h + gap_y
        y = panel_bottom + 10

    plan_section_top=y
    title_box = _section_title_box(plan_section_top)
    _draw_fixed_section_title(plan_section_top, "执行计划｜目标档位必看", primary)
    y = plan_section_top + 58

    risk_items = guide.get("risk") or []
    if isinstance(risk_items, str):
        risk_items = [clean(x) for x in risk_items.replace("\r", "").split("\n") if clean(x)]

    # 风险区高度随条目数变化：标题胶囊覆盖在外层面板顶边，每条风险一张警告卡。
    if risk_items:
        # Give the risk module back a little vertical breathing room.  The extra
        # height is intentionally taken from the flexible Day area (special days
        # still remain taller than normal days), rather than shrinking the footer
        # or section-title capsules again.
        risk_title_h = 60
        risk_bubble_gap = 8
        if len(risk_items) <= 3:
            risk_bubble_h = 66
        elif len(risk_items) <= 4:
            risk_bubble_h = 60
        else:
            risk_bubble_h = 54
        risk_h = 14 + risk_title_h + len(risk_items)*risk_bubble_h + max(0,len(risk_items)-1)*risk_bubble_gap + 12
    else:
        risk_h = 28

    bottom_margin = watermark_h + 16
    plan_bottom = H - risk_h - bottom_margin

    days = list(guide.get("days") or [])[:7]
    n = len(days)
    row_gap = 7

    # Tier progress configuration is resolved before Day heights so a single
    # shared tier legend can reserve a small lane once instead of repeating
    # threshold labels below all seven progress bars.
    renderer_cfg = theme_cfg.get("renderer") if isinstance(theme_cfg.get("renderer"), dict) else {}
    tier_progress_enabled = bool(renderer_cfg.get("day_tier_progress_enabled", False))
    has_tier_progress_data = tier_progress_enabled and any(
        isinstance(info.get("tier_progress"), dict) and info.get("tier_progress", {}).get("max")
        for info in days
    )
    # The global ruler and the per-Day progress bar are independent.  This lets
    # the classic theme explain the tier thresholds once, while each Day header
    # stays lightweight and only shows the day's planned score as text.
    tier_progress_daily_bar = bool(renderer_cfg.get("day_tier_progress_daily_bar", True))
    has_tier_progress = has_tier_progress_data and tier_progress_daily_bar
    tier_progress_title_score = bool(renderer_cfg.get("day_tier_progress_title_score", False))
    tier_progress_global_legend = bool(renderer_cfg.get("day_tier_progress_global_legend", False))
    tier_progress_global_legend_style = clean(str(renderer_cfg.get(
        "day_tier_progress_legend_style", "boxed"
    ) or "boxed")).lower()
    tier_progress_legend_h = max(0, int(renderer_cfg.get("day_tier_progress_legend_height", 22) or 22)) if (has_tier_progress_data and tier_progress_global_legend) else 0
    # The classic shared scale is a threshold lookup, not a live progress bar.
    # For the milestone-ruler presentation reserve enough vertical room for
    # readable labels above a thin rail instead of forcing text inside the bar.
    if tier_progress_legend_h and tier_progress_global_legend_style in {
        "tier_blocks_right_cap", "milestone_ruler", "milestone_ticks"
    }:
        milestone_h = max(60, min(96, int(renderer_cfg.get(
            "day_tier_progress_milestone_height", 64
        ) or 64)))
        tier_progress_legend_h = max(tier_progress_legend_h, milestone_h)
    if tier_progress_legend_h:
        y += tier_progress_legend_h

    plan_h = max(1, plan_bottom - y)

    # V35.81 readability-first classic layout:
    # Saved vertical space is no longer divided evenly.  Normal days keep a
    # comfortable baseline, while special days (typically the multi-step D7)
    # receive most of the remaining height.  This is the actual "space handoff"
    # the compact header/reward/risk sections were intended to create.
    if n:
        available_rows_h = max(1.0, plan_h - row_gap * max(0, n-1))
        base_h = min(118.0, max(98.0, available_rows_h / n * 0.70))
        if base_h * n > available_rows_h:
            base_h = available_rows_h / n
        remaining_h = max(0.0, available_rows_h - base_h*n)
        priorities = []
        import re as _re
        for info in days:
            special = bool(clean(str(info.get("special_label") or "")))
            raw_action = clean(str(info.get("action") or ""))
            step_count = max(1, len([
                x for x in _re.split(r"[；;]+|\r?\n", raw_action) if clean(x)
            ]))
            # Special rows get a strong priority; additional numbered operations
            # add a smaller content-density bonus.
            priority = (2.65 if special else 1.0) + 0.16*max(0, step_count-2)
            priorities.append(priority)
        priority_sum = sum(priorities) or float(n)
        row_heights = [base_h + remaining_h*(w/priority_sum) for w in priorities]
    else:
        row_heights = [plan_h]

    draw_module_frame(
        img, d, (28, plan_section_top+20, W-28, plan_bottom+10),
        primary, fill=panel_secondary, radius=24, ornate=True
    )
    _draw_fixed_section_title(plan_section_top, "执行计划｜目标档位必看", primary)

    # Prepare shared tier-scale data here; the styled global ruler is drawn
    # later, after the activity-specific point icon loader is available.
    _global_tier_legend = None
    if tier_progress_legend_h:
        legend_progress = next((
            info.get("tier_progress") for info in days
            if isinstance(info.get("tier_progress"), dict) and info.get("tier_progress", {}).get("max")
        ), None)
        if isinstance(legend_progress, dict):
            legend_items = []
            for item in legend_progress.get("thresholds") or []:
                try:
                    tier = int(item.get("tier", len(legend_items) + 1) or (len(legend_items) + 1))
                    value = float(item.get("value", 0) or 0)
                except Exception:
                    continue
                if value > 0:
                    legend_items.append((tier, value))
            try:
                maximum = float(legend_progress.get("max", 0) or 0)
            except Exception:
                maximum = 0
            if maximum > 0 and not any(abs(v - maximum) < 1e-8 for _, v in legend_items):
                legend_items.append((len(legend_items) + 1, maximum))
            legend_items = sorted(legend_items, key=lambda pair: (pair[1], pair[0]))
            if legend_items and maximum > 0:
                _global_tier_legend = {"items": legend_items, "maximum": maximum}

    def _readable_action_text(raw):
        raw = clean(str(raw or ""))
        if not raw:
            return "按计划执行"
        # Preserve explicit line breaks; otherwise turn semicolon-separated
        # numbered operations into separate readable lines.
        chunks = [
            clean(x) for x in __import__("re").split(r"[；;]+|\r?\n", raw)
            if clean(x)
        ]
        return "\n".join(chunks) if len(chunks) > 1 else raw

    # 所有 Day 共用一套正文字号。字号由 7 天里最拥挤的那一天决定，
    # 避免 Day1 很大、Day7 因多条序号突然变小。KPI 压缩后释放的高度
    # 优先用于保住这一套统一字号。
    day_head_h = (
        max(43, min(58, int(renderer_cfg.get("day_tier_progress_header_height", 57) or 57)))
        if has_tier_progress else 43
    )
    # Tier progress is deliberately a compact status element next to the target
    # text, not a full-width header decoration.  These defaults preserve ample
    # room on the right for the special-day pennant.
    tier_progress_layout = clean(str(renderer_cfg.get("day_tier_progress_layout", "compact") or "compact")).lower()
    tier_progress_width = max(250, int(renderer_cfg.get("day_tier_progress_width", 355) or 355))
    tier_progress_min_width = max(210, int(renderer_cfg.get("day_tier_progress_min_width", 270) or 270))
    tier_progress_title_gap = max(8, int(renderer_cfg.get("day_tier_progress_title_gap", 18) or 18))
    tier_progress_badge_gap = max(12, int(renderer_cfg.get("day_tier_progress_badge_gap", 28) or 28))
    tier_progress_right_margin = max(10, int(renderer_cfg.get("day_tier_progress_right_margin", 22) or 22))
    tier_progress_reserve_badge_space = bool(renderer_cfg.get("day_tier_progress_reserve_badge_space", True))
    tier_progress_vertical_offset = int(renderer_cfg.get("day_tier_progress_vertical_offset", 0) or 0)
    tier_progress_track_h = max(8, min(18, int(renderer_cfg.get("day_tier_progress_track_height", 14) or 14)))
    tier_progress_icon_size = max(16, min(36, int(renderer_cfg.get("day_tier_progress_icon_size", 23) or 23)))
    tier_progress_supersample = max(1, min(6, int(renderer_cfg.get("day_tier_progress_supersample", 4) or 4)))
    tier_progress_track_radius = max(0, min(6, int(renderer_cfg.get("day_tier_progress_track_radius", 2) or 2)))
    tier_progress_score_font_size = max(8, min(14, int(renderer_cfg.get("day_tier_progress_score_font_size", 10) or 10)))
    tier_progress_marker_size = max(1, min(5, int(renderer_cfg.get("day_tier_progress_marker_size", 2) or 2)))
    tier_progress_label_font_size = max(7, min(12, int(renderer_cfg.get("day_tier_progress_label_font_size", 10) or 10)))
    tier_progress_label_gap = max(1, min(8, int(renderer_cfg.get("day_tier_progress_label_gap", 3) or 3)))
    tier_progress_label_x_offset = max(0, min(16, int(renderer_cfg.get("day_tier_progress_label_x_offset", 5) or 5)))
    tier_progress_label_position = clean(str(renderer_cfg.get("day_tier_progress_label_position", "below_right") or "below_right")).lower()
    tier_progress_label_vertical_offset = max(-4, min(4, int(renderer_cfg.get("day_tier_progress_label_vertical_offset", 0) or 0)))
    tier_progress_score_vertical_offset = max(-4, min(4, int(renderer_cfg.get("day_tier_progress_score_vertical_offset", 1) or 1)))
    tier_progress_show_max_label = bool(renderer_cfg.get("day_tier_progress_show_max_label", True))
    tier_progress_max_label_right_padding = max(2, min(16, int(renderer_cfg.get("day_tier_progress_max_label_right_padding", 5) or 5)))
    # The track now derives from the theme's light Day header color instead of
    # a dark primary/dark blend. This is what keeps ordinary pale-blue days
    # visually pale-blue instead of inserting a navy slab into every row.
    tier_progress_track_primary_mix = max(0.0, min(1.0, float(renderer_cfg.get("day_tier_progress_track_primary_mix", 0.10) or 0.10)))
    tier_progress_fill_primary_mix = max(0.0, min(1.0, float(renderer_cfg.get("day_tier_progress_fill_primary_mix", 0.46) or 0.46)))
    tier_progress_track_inner_pad = max(0, min(3, int(renderer_cfg.get("day_tier_progress_track_inner_pad", 1) or 1)))
    tier_progress_track_outline = bool(renderer_cfg.get("day_tier_progress_track_outline", True))
    tier_progress_track_outline_width = max(1, min(2, int(renderer_cfg.get("day_tier_progress_track_outline_width", 1) or 1)))
    tier_progress_track_outline_dark_mix = max(0.0, min(1.0, float(renderer_cfg.get("day_tier_progress_track_outline_dark_mix", 0.48) or 0.48)))
    tier_progress_legend_font_size = max(9, min(15, int(renderer_cfg.get("day_tier_progress_legend_font_size", 12) or 12)))
    action_font_max = max(16, int(renderer_cfg.get("day_action_font_size", 24) or 24))
    action_font_min = max(13, min(action_font_max, int(renderer_cfg.get("day_action_min_font_size", 16) or 16)))
    action_line_gap = 3
    action_max_lines = 7

    def _wrap_action_for_size(text, size, max_width):
        font = get_font(size, False)
        out = []
        for para in str(text or "").replace("\r", "").split("\n"):
            if not para:
                out.append("")
                continue
            line = ""
            for ch in para:
                test = line + ch
                if line and text_width(d, test, font) > max_width:
                    out.append(line)
                    line = ch
                else:
                    line = test
            if line:
                out.append(line)
        return font, (out or [""])

    def _action_size_fits(info, size, row_height):
        has_metrics = bool(info.get("metric_items"))
        metric_w = 420 if has_metrics else 0
        max_width = (W-48-metric_w-18 if has_metrics else W-48-22) - (48+22)
        max_height = max(24, int(row_height) - day_head_h - 16)
        font, lines = _wrap_action_for_size(_readable_action_text(info.get("action")), size, max_width)
        if len(lines) > action_max_lines:
            return False
        heights = []
        for line in lines:
            bb = d.textbbox((0, 0), line or " ", font=font)
            heights.append(bb[3]-bb[1])
        total_h = sum(heights) + action_line_gap*max(0, len(lines)-1)
        return total_h <= max_height

    shared_action_size = action_font_min
    if days:
        for candidate in range(action_font_max, action_font_min-1, -1):
            if all(
                _action_size_fits(info, candidate, row_heights[i])
                for i, info in enumerate(days)
            ):
                shared_action_size = candidate
                break

    # Remaining/expected cards must keep the same physical size on every day.
    # Special-day rows may be taller, but their status cards no longer stretch
    # with the row.  Use the shortest Day body as the shared status-area height.
    _metric_body_candidates = [
        max(72, int(round(h)) - day_head_h - 17) for h in row_heights
    ] if row_heights else [96]
    shared_metric_area_h = max(78, min(108, min(_metric_body_candidates)))

    def _draw_metrics_right(info, box):
        """Two-row right-side status area with a shared size across all days."""
        items = list(info.get("metric_items") or [])[:4]
        if not items:
            return
        x1, y1, x2, y2 = map(int, box)
        # Use one shared status-block height for all seven days, but center that
        # block vertically inside each Day body.  A taller special day therefore
        # gets equal whitespace above/below the KPI block instead of leaving it
        # stuck to the top edge.
        available_h = max(1, y2-y1)
        group_h = min(shared_metric_area_h, available_h)
        gy1 = int(round(y1 + (available_h-group_h)/2))
        gy2 = gy1 + int(group_h)
        y1, y2 = gy1, gy2
        n = len(items)
        cols = 1 if n <= 2 else 2
        rows = 2 if n >= 2 else 1
        gap_x, gap_y = 6, 5
        cw = (x2-x1-gap_x*max(0,cols-1))/max(1,cols)
        rh = (y2-y1-gap_y*max(0,rows-1))/max(1,rows)
        metric_bg = theme_colors.get("metric_bg", apply_tint(primary, 0.94))
        metric_border = theme_colors.get("metric_border", card_border)
        metric_fg = theme_colors.get("metric_text", text_color)
        for i,item in enumerate(items):
            rr,cc=divmod(i,cols)
            a=int(round(x1+cc*(cw+gap_x))); b=int(round(a+cw))
            yy1=int(round(y1+rr*(rh+gap_y))); yy2=int(round(yy1+rh))
            rounded(d,(a,yy1,b,yy2),9,metric_bg,outline=metric_border,width=1)
            icon = services.config_day_icon(cfg, item)
            icon_size=min(24,max(18,int(yy2-yy1-8)))
            tx=a+8
            if icon and Path(icon).exists():
                iy=int(yy1+(yy2-yy1-icon_size)/2)
                services.draw_image_contain(img,Path(icon),(tx,iy,tx+icon_size,iy+icon_size))
                tx += icon_size+6
            label=clean(str(item.get("label") or ""))
            value=clean(str(item.get("value") or ""))

            # 保持旧版“图标 + 标签 + 数值”单行样式，只做轻量放大。
            # 同时适当加宽右侧状态区，避免长标签把 18946 / 1092 等数值挤掉。
            shown=(label+(" "+value if value else "")).strip()
            draw_left(
                d,(tx,yy1+2,b-5,yy2-2),shown,metric_fg,
                max_size=15,min_size=14,bold=True,max_lines=1,line_gap=0,valign="center"
            )

    watermark_cfg = classic_art.get("paper_watermark") if isinstance(classic_art.get("paper_watermark"), dict) else {}
    _paper_watermark_source = None
    if watermark_cfg.get("enabled", True) is not False:
        watermark_path = _asset_path(watermark_cfg.get("path"))
        if not watermark_path:
            watermark_path = _asset_path("assets/BG_LOGO.png")
        if watermark_path and watermark_path.is_file():
            try:
                _paper_watermark_source = Image.open(watermark_path).convert("RGBA")
            except Exception:
                _paper_watermark_source = None

    def _draw_paper_watermark(card_box, head_h):
        # Watermark sits in the paper/body portion only, never in the coloured
        # day header. Its source PNG is already soft; we multiply that alpha again
        # so the mark reads as paper printing rather than foreground artwork.
        if _paper_watermark_source is None:
            return
        x1, y1, x2, y2 = map(int, card_box)
        body_h = max(1, y2 - (y1 + head_h))
        card_w = max(1, x2 - x1)
        height_ratio = max(0.20, min(1.20, float(watermark_cfg.get("height_ratio", 0.72) or 0.72)))
        max_width_ratio = max(0.05, min(0.50, float(watermark_cfg.get("max_width_ratio", 0.16) or 0.16)))
        target_h = max(18, int(round(body_h * height_ratio)))
        target_w_limit = max(18, int(round(card_w * max_width_ratio)))
        src = _paper_watermark_source.copy()
        src.thumbnail((target_w_limit, target_h), Image.Resampling.LANCZOS)
        if src.width <= 0 or src.height <= 0:
            return

        color = watermark_cfg.get("color") or dark
        cr, cg, cb = _rgb(color, _rgb(dark))
        alpha = src.getchannel("A")
        opacity = max(0.0, min(1.0, float(watermark_cfg.get("opacity", 0.08) or 0.08)))

        # 用户提供的 Logo PNG 本身已经是低透明度素材（最大 alpha 远小于 255）。
        # 旧逻辑再乘一次 opacity 会把它压到几乎不可见。现在默认把素材自身
        # 的 alpha 曲线归一化，再由 opacity 直接表示“最终最大可见透明度”。
        if bool(watermark_cfg.get("normalize_source_alpha", True)):
            alpha_max = max(1, int(alpha.getextrema()[1] or 1))
            target_max = int(round(255 * opacity))
            scale = target_max / alpha_max
            alpha = alpha.point(lambda a: max(0, min(255, int(round(a * scale)))))
        else:
            alpha = alpha.point(lambda a: int(round(a * opacity)))

        tinted = Image.new("RGBA", src.size, (cr, cg, cb, 0))
        tinted.putalpha(alpha)

        right_margin = max(4, int(watermark_cfg.get("right_margin", 14) or 14))
        bottom_margin = max(2, int(watermark_cfg.get("bottom_margin", 5) or 5))
        px = max(x1 + 4, x2 - right_margin - tinted.width)
        py = max(y1 + head_h + 2, y2 - bottom_margin - tinted.height)
        img.alpha_composite(tinted, (px, py))

    tier_progress_art_cfg = (
        classic_art.get("tier_progress")
        if isinstance(classic_art.get("tier_progress"), dict)
        else {}
    )

    def _load_tier_point_icon():
        """Load the activity-specific point icon.

        Primary source is the activity JSON, e.g.::

            "activity_icons": {
                "point": "assets/point/fishing_festival.png"
            }

        This keeps the icon activity-owned instead of theme-owned.  A theme-level
        ``point_icon`` is accepted only as a backwards-compatible fallback for
        older projects.  We intentionally DO NOT auto-pick the first image in
        assets/point, because that folder can contain point icons for many events.
        """
        candidates = []

        activity_icons = cfg.get("activity_icons") or {}
        if isinstance(activity_icons, dict):
            activity_point = _asset_path(
                activity_icons.get("point")
                or activity_icons.get("tier_point")
                or activity_icons.get("progress_point")
            )
            if activity_point and activity_point.is_file():
                candidates.append(activity_point)

        # Backwards compatibility only. New activity configs should use
        # activity_icons.point so different activities never share an icon by
        # accident.
        configured = _asset_path(tier_progress_art_cfg.get("point_icon"))
        if configured and configured.is_file() and configured not in candidates:
            candidates.append(configured)

        for candidate in candidates:
            try:
                src = Image.open(candidate).convert("RGBA")
                # Trim transparent padding so the icon itself can read clearly
                # at phone-preview size even when the source canvas is square.
                alpha_bbox = src.getchannel("A").getbbox()
                if alpha_bbox:
                    src = src.crop(alpha_bbox)
                return src
            except Exception:
                continue
        return None

    _tier_point_source = _load_tier_point_icon()

    def _paste_tier_point_icon(cx, cy, size):
        if _tier_point_source is None:
            return False
        size = max(12, int(size))
        src = _tier_point_source.copy()
        src.thumbnail((size, size), Image.Resampling.LANCZOS)
        if src.width <= 0 or src.height <= 0:
            return False
        px = int(round(cx - src.width / 2))
        py = int(round(cy - src.height / 2))
        img.alpha_composite(src, (px, py))
        return True

    def _draw_global_tier_ruler():
        """Draw the shared tier-threshold ruler above the Day cards.

        The ruler is explanatory rather than a live progress meter.  Tier labels
        sit above exact proportional threshold nodes, joined by short dashed
        stems.  The rail extends slightly beyond the first and last thresholds so
        the highest tier reads as a milestone on a scale, not the physical end of
        a completion bar.
        """
        if not (_global_tier_legend and tier_progress_legend_h):
            return

        items = list(_global_tier_legend.get("items") or [])
        maximum = float(_global_tier_legend.get("maximum", 0) or 0)
        if not items or maximum <= 0:
            return

        legend_y1 = plan_section_top + 52
        legend_y2 = legend_y1 + tier_progress_legend_h
        # Day cards are drawn from x=48 to x=W-48.  Matching that span makes
        # the shared scale feel structurally attached to the card stack below.
        left = int(renderer_cfg.get("day_tier_progress_ruler_left", 48) or 48)
        right = W - int(renderer_cfg.get("day_tier_progress_ruler_right", 48) or 48)
        if right - left < 220:
            return

        icon_size = max(16, min(36, int(renderer_cfg.get(
            "day_tier_progress_legend_icon_size", tier_progress_icon_size
        ) or tier_progress_icon_size)))
        legend_style = clean(str(renderer_cfg.get(
            "day_tier_progress_legend_style", "boxed"
        ) or "boxed")).lower()

        if legend_style in {"tier_blocks_right_cap", "milestone_ruler", "milestone_ticks"}:
            # Readable milestone ruler for the classic theme.
            #
            # Why this is deliberately *not* a segmented progress bar:
            # - the values are thresholds, not completion states;
            # - each label belongs to one exact score position;
            # - labels stay above the rail so the first short 0-210 range no
            #   longer dictates a tiny font for the entire component.
            milestone_label_size = max(13, min(18, int(renderer_cfg.get(
                "day_tier_progress_milestone_font_size", 15
            ) or 15)))
            milestone_rail_h = max(6, min(12, int(renderer_cfg.get(
                "day_tier_progress_milestone_rail_height", 8
            ) or 8)))
            milestone_node_size = max(14, min(24, int(renderer_cfg.get(
                "day_tier_progress_milestone_node_size", 18
            ) or 18)))
            milestone_inner_size = max(5, min(milestone_node_size - 6, int(renderer_cfg.get(
                "day_tier_progress_milestone_inner_size", 8
            ) or 8)))
            milestone_stem_gap = max(2, min(10, int(renderer_cfg.get(
                "day_tier_progress_milestone_stem_gap", 3
            ) or 3)))
            milestone_stem_len = max(6, min(16, int(renderer_cfg.get(
                "day_tier_progress_milestone_stem_length", 10
            ) or 10)))

            # The point icon acts as the visual origin of the ruler.  Start the
            # rail at the icon centre and paste the icon afterwards, so the line
            # appears to grow naturally from behind the icon with no visible gap.
            if _tier_point_source is not None:
                icon_size = max(22, min(32, icon_size))
                icon_cx = left + icon_size / 2
                track_x1 = icon_cx
            else:
                icon_size = 0
                icon_cx = left
                track_x1 = left + 2

            node_r = milestone_node_size / 2
            track_x2 = right - 2
            if track_x2 - track_x1 < 220:
                track_x1 = left + 2
                icon_size = 0

            # Thresholds use a proportional inner span, while the rail itself
            # extends beyond the first/last marker.  Percentage-based padding
            # scales cleanly with different output widths and avoids a hard
            # "3980 = physical end of bar" impression.
            track_span = max(1.0, track_x2 - track_x1)
            marker_head_pad = max(node_r + 4, min(30.0, track_span * 0.03))
            marker_tail_pad = max(node_r + 12, min(64.0, track_span * 0.065))
            marker_x1 = track_x1 + marker_head_pad
            marker_x2 = track_x2 - marker_tail_pad
            if marker_x2 <= marker_x1:
                marker_x1 = track_x1 + max(node_r + 2, 10)
                marker_x2 = track_x2 - max(node_r + 2, 10)
            marker_w = max(1.0, marker_x2 - marker_x1)

            ss = tier_progress_supersample
            local_w = max(1, right - left)
            local_h = max(1, legend_y2 - legend_y1)
            layer = Image.new("RGBA", (local_w * ss, local_h * ss), (0, 0, 0, 0))
            ld = ImageDraw.Draw(layer)

            def lx(x):
                return int(round((x - left) * ss))

            def ly(y):
                return int(round((y - legend_y1) * ss))

            label_font = get_font(milestone_label_size * ss, True)
            # Rail sits in the lower third of the reserved lane.  This leaves a
            # calm label row above it while keeping the whole module compact.
            rail_cy = legend_y2 - max(14, int(round(milestone_node_size * 0.82)))
            rail_y1 = rail_cy - milestone_rail_h / 2
            rail_y2 = rail_cy + milestone_rail_h / 2

            label_ink_rgb = _header_hex_rgb(renderer_cfg.get(
                "day_tier_progress_legend_label_ink_color", "#17212B"
            ), (23, 33, 43))
            # Slightly deepen the rail so it stays readable in full-page
            # mobile previews without regressing into a heavy progress bar.
            rail_fill = _rgb_mix(card_fill, primary, 0.36)
            rail_outline = _rgb_mix(light, primary, 0.52)
            node_outline = _rgb_mix(primary, dark, 0.46)
            node_fill = _rgb_mix(card_fill, primary, 0.04)
            node_inner = _rgb_mix(primary, dark, 0.10)
            stem_rgb = _rgb_mix(primary, dark, 0.34)
            text_rgb = _rgb_mix(label_ink_rgb, dark, 0.14)

            # Thin rounded threshold rail with a subtle upper highlight.  It is
            # intentionally uniform: darker spans would imply completed progress.
            rx1, rx2 = lx(track_x1), lx(track_x2)
            ry1, ry2 = ly(rail_y1), ly(rail_y2)
            rr = max(1, int(round(milestone_rail_h * ss / 2)))
            ld.rounded_rectangle(
                (rx1, ry1, rx2, ry2),
                radius=rr,
                fill=(*rail_fill, 235),
                outline=(*rail_outline, 210),
                width=max(1, ss),
            )
            hi_y = min(ry2 - ss, ry1 + max(1, ss))
            ld.line(
                (rx1 + rr, hi_y, rx2 - rr, hi_y),
                fill=(255, 255, 255, 88),
                width=max(1, ss),
            )

            label_top = legend_y1 + 2
            min_text_x = lx(track_x1) - 4 * ss
            # Keep a dedicated safe margin at the right edge so the last label
            # never gets clipped even after adding the trailing rail tail.
            text_safe_right = max(track_x1 + 120, right - 10)
            max_text_x = lx(text_safe_right)
            previous_right = None

            for tier, value in items:
                ratio = max(0.0, min(1.0, float(value) / maximum))
                marker_x = marker_x1 + marker_w * ratio
                marker_x_s = lx(marker_x)

                label = f"{int(tier)}档 {int(round(value))}"
                bb = ld.textbbox((0, 0), label, font=label_font)
                tw = bb[2] - bb[0]
                desired_x = marker_x_s - tw / 2
                text_x = max(min_text_x, min(max_text_x - tw, desired_x))

                # The first three thresholds are close together.  Preserve a
                # small breathing gap if a future activity uses wider labels.
                if previous_right is not None and text_x < previous_right + 8 * ss:
                    text_x = min(max_text_x - tw, previous_right + 8 * ss)
                previous_right = text_x + tw

                text_y = ly(label_top) - bb[1]
                preferred_text_y = ly(rail_cy - node_r - milestone_stem_gap - milestone_stem_len) - bb[3]
                if preferred_text_y > text_y:
                    text_y = preferred_text_y
                ld.text(
                    (int(round(text_x)), int(round(text_y))),
                    label,
                    font=label_font,
                    fill=(*text_rgb, 255),
                )

                # Short dashed stem visually binds the label to the exact score
                # point without making the component look like a chart grid.
                stem_x = marker_x_s
                stem_top = int(round(text_y + bb[3] + milestone_stem_gap * ss))
                stem_bottom = ly(rail_cy - node_r - 3)
                dash = max(2 * ss, 1)
                gap = max(2 * ss, 1)
                yy = stem_top
                while yy < stem_bottom:
                    y_end = min(stem_bottom, yy + dash)
                    ld.line(
                        (stem_x, yy, stem_x, y_end),
                        fill=(*stem_rgb, 135),
                        width=max(1, ss),
                    )
                    yy = y_end + gap

                # Milestone marker: light outer disc + strong theme ring + dot.
                outer_r = node_r * ss
                inner_r = milestone_inner_size * ss / 2
                cy_s = ly(rail_cy)
                shadow_off = max(1, ss)
                ld.ellipse(
                    (
                        marker_x_s - outer_r,
                        cy_s - outer_r + shadow_off,
                        marker_x_s + outer_r,
                        cy_s + outer_r + shadow_off,
                    ),
                    fill=(0, 0, 0, 28),
                )
                ld.ellipse(
                    (
                        marker_x_s - outer_r,
                        cy_s - outer_r,
                        marker_x_s + outer_r,
                        cy_s + outer_r,
                    ),
                    fill=(*node_fill, 255),
                    outline=(*node_outline, 255),
                    width=max(2 * ss, ss),
                )
                ld.ellipse(
                    (
                        marker_x_s - inner_r,
                        cy_s - inner_r,
                        marker_x_s + inner_r,
                        cy_s + inner_r,
                    ),
                    fill=(*node_inner, 255),
                )

            layer = layer.resize((local_w, local_h), Image.Resampling.LANCZOS)
            img.alpha_composite(layer, (left, legend_y1))
            if icon_size:
                _paste_tier_point_icon(icon_cx, rail_cy, icon_size)
            return

        track_h = max(9, min(24, int(renderer_cfg.get(
            "day_tier_progress_legend_track_height", tier_progress_track_h
        ) or tier_progress_track_h)))
        label_size = max(7, min(14, int(renderer_cfg.get(
            "day_tier_progress_legend_font_size", tier_progress_label_font_size
        ) or tier_progress_label_font_size)))
        label_x_offset = max(1, min(14, int(renderer_cfg.get(
            "day_tier_progress_legend_label_x_offset", 5
        ) or 5)))
        max_right_padding = max(2, min(18, int(renderer_cfg.get(
            "day_tier_progress_legend_max_label_right_padding", 5
        ) or 5)))
        tick_h = max(3, min(track_h - 2, int(renderer_cfg.get(
            "day_tier_progress_legend_tick_height", 7
        ) or 7)))
        tick_w = max(1, min(3, int(renderer_cfg.get(
            "day_tier_progress_legend_tick_width", 1
        ) or 1)))
        track_mix = max(0.0, min(1.0, float(renderer_cfg.get(
            "day_tier_progress_legend_track_primary_mix", 0.08
        ) or 0.08)))
        surface_mix = max(0.0, min(0.30, float(renderer_cfg.get(
            "day_tier_progress_legend_surface_primary_mix", 0.045
        ) or 0.045)))
        fill_mode = clean(str(renderer_cfg.get(
            "day_tier_progress_legend_fill_mode", "surface"
        ) or "surface")).lower()
        outline_mix = max(0.0, min(1.0, float(renderer_cfg.get(
            "day_tier_progress_legend_outline_dark_mix", 0.52
        ) or 0.52)))
        tick_mix = max(0.0, min(1.0, float(renderer_cfg.get(
            "day_tier_progress_legend_tick_dark_mix", 0.72
        ) or 0.72)))
        label_dark_mix = max(0.0, min(1.0, float(renderer_cfg.get(
            "day_tier_progress_legend_label_dark_mix", 0.88
        ) or 0.88)))
        tick_color_mode = clean(str(renderer_cfg.get(
            "day_tier_progress_legend_tick_color_mode", "theme"
        ) or "theme")).lower()
        label_color_mode = clean(str(renderer_cfg.get(
            "day_tier_progress_legend_label_color_mode", "auto"
        ) or "auto")).lower()
        threshold_label_mode = clean(str(renderer_cfg.get(
            "day_tier_progress_legend_threshold_label_mode", "score_only"
        ) or "score_only")).lower()
        tick_ink_rgb = _header_hex_rgb(renderer_cfg.get(
            "day_tier_progress_legend_tick_ink_color", "#17212B"
        ), (23, 33, 43))
        label_ink_rgb = _header_hex_rgb(renderer_cfg.get(
            "day_tier_progress_legend_label_ink_color", "#17212B"
        ), (23, 33, 43))
        contrast_luminance_threshold = max(0.0, min(1.0, float(renderer_cfg.get(
            "day_tier_progress_legend_contrast_luminance_threshold", 0.29
        ) or 0.29)))
        light_label_rgb = _header_hex_rgb(renderer_cfg.get(
            "day_tier_progress_legend_light_label_color", "#FFFFFF"
        ), (255, 255, 255))
        gold_label_rgb = _header_hex_rgb(renderer_cfg.get(
            "day_tier_progress_legend_gold_label_color", "#4E3A12"
        ), (78, 58, 18))
        primary_rgb_for_legend = _header_hex_rgb(primary)
        is_gold_palette = (
            primary_rgb_for_legend[0] >= 150
            and primary_rgb_for_legend[1] >= 110
            and primary_rgb_for_legend[2] <= 100
        )
        light_tick_rgb = _header_hex_rgb(renderer_cfg.get(
            "day_tier_progress_legend_light_tick_color", "#FFFFFF"
        ), (255, 255, 255))
        light_text_alpha = max(180, min(255, int(renderer_cfg.get(
            "day_tier_progress_legend_light_text_alpha", 255
        ) or 255)))
        light_label_from_tier = max(1, min(5, int(renderer_cfg.get(
            "day_tier_progress_legend_light_label_from_tier", 3
        ) or 3)))
        light_label_stroke_width = max(0, min(2, int(renderer_cfg.get(
            "day_tier_progress_legend_light_label_stroke_width", 1
        ) or 0)))
        light_label_stroke_alpha = max(0, min(255, int(renderer_cfg.get(
            "day_tier_progress_legend_light_label_stroke_alpha", 150
        ) or 150)))
        tick_ink_theme_mix = max(0.0, min(0.35, float(renderer_cfg.get(
            "day_tier_progress_legend_tick_ink_theme_mix", 0.0
        ) or 0.0)))
        rail_mix = max(0.0, min(1.0, float(renderer_cfg.get(
            "day_tier_progress_legend_rail_primary_mix", 0.62
        ) or 0.62)))
        rail_alpha = max(0, min(255, int(renderer_cfg.get(
            "day_tier_progress_legend_rail_alpha", 150
        ) or 150)))
        highlight_alpha = max(0, min(255, int(renderer_cfg.get(
            "day_tier_progress_legend_highlight_alpha", 105
        ) or 105)))
        segment_mix_a = max(0.0, min(0.50, float(renderer_cfg.get(
            "day_tier_progress_legend_segment_mix_a", 0.08
        ) or 0.08)))
        segment_mix_b = max(0.0, min(0.50, float(renderer_cfg.get(
            "day_tier_progress_legend_segment_mix_b", 0.20
        ) or 0.20)))
        gradient_inner_y_pad = max(1, min(5, int(renderer_cfg.get(
            "day_tier_progress_legend_gradient_inner_y_pad", 2
        ) or 2)))
        gradient_end_inset = max(1, min(12, int(renderer_cfg.get(
            "day_tier_progress_legend_gradient_end_inset", 5
        ) or 5)))
        raw_gradient_mixes = renderer_cfg.get(
            "day_tier_progress_legend_gradient_stop_mixes",
            [0.10, 0.24, 0.38, 0.52, 0.66, 0.78],
        )
        if not isinstance(raw_gradient_mixes, (list, tuple)):
            raw_gradient_mixes = [0.10, 0.24, 0.38, 0.52, 0.66, 0.78]
        gradient_mixes = []
        for value in raw_gradient_mixes[:6]:
            try:
                gradient_mixes.append(max(0.0, min(1.0, float(value))))
            except (TypeError, ValueError):
                pass
        while len(gradient_mixes) < 6:
            gradient_mixes.append([0.10, 0.24, 0.38, 0.52, 0.66, 0.78][len(gradient_mixes)])
        raw_gradient_darkening = renderer_cfg.get(
            "day_tier_progress_legend_gradient_darkening",
            [0.0, 0.0, 0.0, 0.0, 0.02, 0.08],
        )
        if not isinstance(raw_gradient_darkening, (list, tuple)):
            raw_gradient_darkening = [0.0, 0.0, 0.0, 0.0, 0.02, 0.08]
        gradient_darkening = []
        for value in raw_gradient_darkening[:6]:
            try:
                gradient_darkening.append(max(0.0, min(0.5, float(value))))
            except (TypeError, ValueError):
                pass
        while len(gradient_darkening) < 6:
            gradient_darkening.append([0.0, 0.0, 0.0, 0.0, 0.02, 0.08][len(gradient_darkening)])

        # Flat tier-band palette used by the right-capped scale.  Each tier is a
        # distinct solid color (no gradient), ordered from light to dark.
        raw_band_mixes = renderer_cfg.get(
            "day_tier_progress_legend_band_primary_mixes",
            [0.14, 0.30, 0.46, 0.62, 0.78],
        )
        if not isinstance(raw_band_mixes, (list, tuple)):
            raw_band_mixes = [0.14, 0.30, 0.46, 0.62, 0.78]
        band_mixes = []
        for value in raw_band_mixes[:5]:
            try:
                band_mixes.append(max(0.0, min(1.0, float(value))))
            except (TypeError, ValueError):
                pass
        while len(band_mixes) < 5:
            band_mixes.append([0.14, 0.30, 0.46, 0.62, 0.78][len(band_mixes)])

        raw_band_darkening = renderer_cfg.get(
            "day_tier_progress_legend_band_darkening",
            [0.0, 0.0, 0.0, 0.02, 0.08],
        )
        if not isinstance(raw_band_darkening, (list, tuple)):
            raw_band_darkening = [0.0, 0.0, 0.0, 0.02, 0.08]
        band_darkening = []
        for value in raw_band_darkening[:5]:
            try:
                band_darkening.append(max(0.0, min(0.5, float(value))))
            except (TypeError, ValueError):
                pass
        while len(band_darkening) < 5:
            band_darkening.append([0.0, 0.0, 0.0, 0.02, 0.08][len(band_darkening)])


        icon_cx = left + icon_size / 2 if _tier_point_source is not None else left
        # Count the point icon as part of the ruler's overall card-width span.
        # The track begins just under/after the icon, while its right edge aligns
        # exactly with the Day cards below.
        track_x1 = left + (icon_size * 3 // 5 if _tier_point_source is not None else 0)
        track_x2 = right
        if track_x2 - track_x1 < 180:
            track_x1 = left
            icon_size = 0

        content_h = max(track_h, icon_size)
        track_y = int(round(legend_y1 + max(0, (legend_y2 - legend_y1 - content_h) / 2)))

        ss = tier_progress_supersample
        local_w = max(1, right - left)
        local_h = max(1, legend_y2 - legend_y1)
        layer = Image.new("RGBA", (local_w * ss, local_h * ss), (0, 0, 0, 0))
        ld = ImageDraw.Draw(layer)

        def lx(x):
            return int(round((x - left) * ss))

        def ly(y):
            return int(round((y - legend_y1) * ss))

        # This ruler is a lookup tool, not decorative chrome: the user should be
        # able to read a Day score such as 635 and immediately compare it with
        # the 630 threshold.  Use the theme's existing chip/light surface for
        # enough separation from the white panel, then reserve the darker theme
        # tones for the border, ticks and numerals.
        chip_fill = theme_colors.get("chip", light)
        if fill_mode == "chip":
            # Keep the familiar chip surface, but allow a controlled amount of
            # theme primary color so the global ruler is easy to find at a glance.
            track_fill = _rgb_mix(chip_fill, primary, track_mix)
        elif fill_mode == "light":
            track_fill = _rgb_mix(light, primary, track_mix)
        else:
            track_fill = _rgb_mix(card_fill, primary, surface_mix)
        track_outline = _rgb_mix(primary, dark, outline_mix)
        rail_rgb = _rgb_mix(primary, dark, rail_mix)
        tick_rgb = _rgb_mix(primary, dark, tick_mix)
        label_rgb = _rgb_mix(primary, dark, label_dark_mix)
        # P5D can use a neutral high-contrast ink for small ruler details.
        # This keeps 210/630/1060/2520/3980 readable across all six color
        # variants without forcing the last bands to become excessively dark.
        tick_ink_rgb = _rgb_mix(tick_ink_rgb, dark, tick_ink_theme_mix)
        radius = max(1, tier_progress_track_radius) * ss

        tx1, ty1 = lx(track_x1), ly(track_y)
        tx2, ty2 = lx(track_x2), ly(track_y + track_h)
        rail_y = int(round((ty1 + ty2) / 2))
        rail_inset = max(radius, 3 * ss)
        flat_band_colors = None
        if legend_style == "tier_blocks_right_cap":
            # A ruler with a straight left edge and a true semicircular right
            # cap.  The five tier ranges are full-height, flat-color blocks;
            # there is deliberately no gradient and no inner rail.
            cap_r = max(1, int(round((ty2 - ty1) / 2)))
            shape_mask = Image.new("L", layer.size, 0)
            md = ImageDraw.Draw(shape_mask)
            cap_cx = tx2 - cap_r
            md.rectangle((tx1, ty1, cap_cx, ty2), fill=255)
            md.ellipse((tx2 - 2 * cap_r, ty1, tx2, ty2), fill=255)

            flat_band_colors = []
            for idx in range(5):
                color = _rgb_mix(light, primary, band_mixes[idx])
                if band_darkening[idx] > 0:
                    color = _rgb_mix(color, dark, band_darkening[idx])
                flat_band_colors.append(color)

            bands = Image.new("RGBA", layer.size, (0, 0, 0, 0))
            bd = ImageDraw.Draw(bands)
            bounds = [0.0] + [max(0.0, min(maximum, float(v))) for _, v in items[:5]]
            while len(bounds) < 6:
                bounds.append(maximum)
            for idx in range(5):
                a = bounds[idx] / maximum if maximum > 0 else 0.0
                b = bounds[idx + 1] / maximum if maximum > 0 else 1.0
                xa = tx1 + int(round((tx2 - tx1) * a))
                xb = tx1 + int(round((tx2 - tx1) * b))
                # Add one pixel of overlap before masking to avoid anti-aliased
                # seams between adjacent solid-color bands.
                bd.rectangle((xa, ty1, min(tx2, xb + ss), ty2), fill=(*flat_band_colors[idx], 255))
            bands.putalpha(ImageChops.multiply(bands.getchannel("A"), shape_mask))
            layer.alpha_composite(bands)

            ow = max(1, tier_progress_track_outline_width * ss)
            outline = (*track_outline, 255)
            # Straight left/top/bottom edges, semicircle only on the far right.
            ld.line((tx1, ty1, cap_cx, ty1), fill=outline, width=ow)
            ld.line((tx1, ty2, cap_cx, ty2), fill=outline, width=ow)
            ld.line((tx1, ty1, tx1, ty2), fill=outline, width=ow)
            arc_box = (tx2 - 2 * cap_r, ty1, tx2, ty2)
            ld.arc(arc_box, start=-90, end=90, fill=outline, width=ow)

        elif legend_style == "gradient_capsule":
            # Outer silhouette is a true capsule/ellipse.  The interior color
            # field is deliberately rectangular: no rounded segment ends and no
            # center rail, just a continuous tier-to-tier gradient.
            capsule_radius = max(1, int(round(track_h * ss / 2)))
            ld.rounded_rectangle(
                (tx1, ty1, tx2, ty2),
                radius=capsule_radius,
                fill=track_fill,
                outline=track_outline,
                width=max(1, tier_progress_track_outline_width * ss),
            )

            gx1 = tx1 + gradient_end_inset * ss
            gx2 = tx2 - gradient_end_inset * ss
            gy1 = ty1 + gradient_inner_y_pad * ss
            gy2 = ty2 - gradient_inner_y_pad * ss
            if gx2 > gx1 and gy2 > gy1:
                # Anchor the color transition at the real tier thresholds so the
                # visual scale remains faithful to 210/630/1060/2520/3980.
                threshold_values = [
                    max(0.0, min(maximum, float(value)))
                    for _, value in items
                ]
                stop_values = [0.0] + threshold_values
                # Ensure exactly six color anchors: start + five tier endpoints.
                stop_values = stop_values[:6]
                while len(stop_values) < 6:
                    stop_values.append(maximum)
                stop_positions = [
                    0.0 if maximum <= 0 else max(0.0, min(1.0, value / maximum))
                    for value in stop_values
                ]
                stop_colors = []
                for idx in range(6):
                    color = _rgb_mix(light, primary, gradient_mixes[idx])
                    if gradient_darkening[idx] > 0:
                        color = _rgb_mix(color, dark, gradient_darkening[idx])
                    stop_colors.append(color)

                gw = max(1, gx2 - gx1 + 1)
                gh = max(1, gy2 - gy1 + 1)
                grad = Image.new("RGBA", (gw, gh), (0, 0, 0, 0))
                gp = grad.load()
                for px in range(gw):
                    pos = 0.0 if gw <= 1 else px / (gw - 1)
                    seg = 0
                    while seg < len(stop_positions) - 2 and pos > stop_positions[seg + 1]:
                        seg += 1
                    p0 = stop_positions[seg]
                    p1 = stop_positions[min(seg + 1, len(stop_positions) - 1)]
                    t = 0.0 if p1 <= p0 else (pos - p0) / (p1 - p0)
                    rgb = _rgb_mix(stop_colors[seg], stop_colors[min(seg + 1, len(stop_colors) - 1)], t)
                    for py in range(gh):
                        gp[px, py] = (*rgb, 255)
                layer.alpha_composite(grad, (gx1, gy1))

            # Redraw the capsule outline on top of the rectangular gradient.
            ld.rounded_rectangle(
                (tx1, ty1, tx2, ty2),
                radius=capsule_radius,
                fill=None,
                outline=track_outline,
                width=max(1, tier_progress_track_outline_width * ss),
            )
        elif legend_style == "line":
            # Pure ruler: no filled capsule, only a strong axis plus ticks.
            ld.line(
                (tx1 + rail_inset, rail_y, tx2 - rail_inset, rail_y),
                fill=(*rail_rgb, max(210, rail_alpha)),
                width=max(2 * ss, tier_progress_track_outline_width * ss),
            )
        else:
            ld.rounded_rectangle(
                (tx1, ty1, tx2, ty2),
                radius=radius,
                fill=track_fill,
                outline=track_outline,
                width=max(1, tier_progress_track_outline_width * ss),
            )
            if legend_style == "segmented":
                # Alternate very subtle theme tints between threshold ranges so
                # the user can perceive each tier band without a heavy dark bar.
                vals = [0.0] + [max(0.0, min(maximum, float(v))) for _, v in items]
                vals = sorted(set(vals))
                for seg_i in range(len(vals)-1):
                    a, b = vals[seg_i], vals[seg_i+1]
                    xa = lx(track_x1 + (track_x2-track_x1)*(a/maximum))
                    xb = lx(track_x1 + (track_x2-track_x1)*(b/maximum))
                    mix = segment_mix_a if seg_i % 2 == 0 else segment_mix_b
                    seg_rgb = _rgb_mix(track_fill, primary, mix)
                    # Stay inside the outer border; square segment edges are
                    # intentional because ticks mark the exact boundaries.
                    ld.rectangle((xa, ty1 + ss, xb, ty2 - ss), fill=seg_rgb)
                # redraw outline over segment fills
                ld.rounded_rectangle(
                    (tx1, ty1, tx2, ty2),
                    radius=radius,
                    fill=None,
                    outline=track_outline,
                    width=max(1, tier_progress_track_outline_width * ss),
                )
            if rail_alpha and legend_style != "gradient_capsule":
                ld.line(
                    (tx1 + rail_inset, rail_y, tx2 - rail_inset, rail_y),
                    fill=(*rail_rgb, rail_alpha),
                    width=max(1, ss),
                )
            if highlight_alpha and legend_style != "gradient_capsule":
                hi_rgb = _rgb_mix(track_fill, card_fill, 0.62)
                hi_y = min(ty2 - ss, ty1 + max(ss, 2 * ss))
                ld.line(
                    (tx1 + rail_inset, hi_y, tx2 - rail_inset, hi_y),
                    fill=(*hi_rgb, highlight_alpha),
                    width=max(1, ss),
                )

        inner_pad = 0 if legend_style == "tier_blocks_right_cap" else max(1, tier_progress_track_inner_pad)
        ix1 = track_x1 + inner_pad
        ix2 = track_x2 - inner_pad
        inner_w = max(1, ix2 - ix1)
        label_font = get_font(label_size * ss, True)
        center_y = track_y + track_h / 2

        for idx, (tier, value) in enumerate(items):
            ratio = max(0.0, min(1.0, value / maximum))
            mx = ix1 + inner_w * ratio
            is_last = idx == len(items) - 1 or abs(value - maximum) < 1e-8

            score_label = str(int(round(value)))
            if threshold_label_mode in {"tier_score", "tier_score_inline", "threshold"}:
                label = f"{int(tier)}档 {score_label}"
            else:
                label = score_label
            bb = ld.textbbox((0, 0), label, font=label_font)
            tw = bb[2] - bb[0]
            th = bb[3] - bb[1]

            if is_last:
                # The right edge itself acts as the final tick; keep 3980 cleanly
                # inset rather than drawing a redundant line on top of the border.
                text_x = lx(ix2 - max_right_padding) - tw - bb[0]
            else:
                x = lx(mx)
                if legend_style == "tier_blocks_right_cap":
                    # Full-height separators make the five flat-color tiers read
                    # as actual blocks rather than a continuous fill.
                    sep_inset = max(ss, tier_progress_track_outline_width * ss)
                    if tick_color_mode == "adaptive" and flat_band_colors:
                        left_band = flat_band_colors[min(4, max(0, idx))]
                        right_band = flat_band_colors[min(4, max(0, idx + 1))]
                        separator_bg = _rgb_mix(left_band, right_band, 0.5)
                        separator_rgb = (
                            light_tick_rgb
                            if _relative_luminance(separator_bg) <= contrast_luminance_threshold
                            else tick_ink_rgb
                        )
                    else:
                        separator_rgb = tick_ink_rgb if tick_color_mode == "ink" else track_outline
                    ld.line(
                        (x, ty1 + sep_inset, x, ty2 - sep_inset),
                        fill=(*separator_rgb, 238),
                        width=max(1, tick_w * ss),
                    )
                else:
                    tick_top = center_y - tick_h / 2
                    tick_bottom = center_y + tick_h / 2
                    ld.line(
                        (x, ly(tick_top), x, ly(tick_bottom)),
                        fill=(*tick_rgb, 235),
                        width=max(1, tick_w * ss),
                    )
                text_x = lx(mx + label_x_offset) - bb[0]
                text_x = min(lx(ix2 - max_right_padding) - tw - bb[0], text_x)

            if legend_style == "line":
                text_y = rail_y + 3 * ss - bb[1]
            else:
                text_y = (ty1 + ty2 - th) / 2 - bb[1]

            text_rgb = label_rgb
            text_alpha = 252
            if legend_style == "tier_blocks_right_cap" and flat_band_colors:
                # Threshold labels are anchored to their exact tick.  Use dark
                # ink on light bands, but reverse to white once the band is
                # visually dark enough; this is intentionally an aesthetic
                # threshold rather than a pure maximum-contrast calculation.
                band_index = min(4, idx + (0 if is_last else 1))
                band_bg = flat_band_colors[band_index]
                if label_color_mode == "ink":
                    text_rgb = label_ink_rgb
                elif label_color_mode in {"tier_cutoff", "tier", "from_tier"}:
                    if int(tier) >= light_label_from_tier:
                        # Do not outline all light labels just to rescue gold.
                        # Gold is handled as its own palette case with dark-brown
                        # text, while darker palettes use clean white text.
                        text_rgb = gold_label_rgb if is_gold_palette else light_label_rgb
                        text_alpha = light_text_alpha
                    else:
                        text_rgb = label_ink_rgb
                elif _relative_luminance(band_bg) <= contrast_luminance_threshold:
                    text_rgb = light_label_rgb
                    text_alpha = light_text_alpha
                else:
                    text_rgb = label_ink_rgb
            if text_rgb == light_label_rgb and light_label_stroke_width > 0:
                ld.text(
                    (text_x, text_y),
                    label,
                    font=label_font,
                    fill=(*text_rgb, text_alpha),
                    stroke_width=light_label_stroke_width * ss,
                    stroke_fill=(*label_ink_rgb, light_label_stroke_alpha),
                )
            else:
                ld.text((text_x, text_y), label, font=label_font, fill=(*text_rgb, text_alpha))

        layer = layer.resize((local_w, local_h), Image.Resampling.LANCZOS)
        img.alpha_composite(layer, (left, legend_y1))

        if icon_size:
            _paste_tier_point_icon(icon_cx, track_y + track_h / 2, icon_size)

    _draw_global_tier_ruler()

    def _format_tier_progress_number(value, decimals=None):
        try:
            number = float(value)
        except Exception:
            return clean(str(value or ""))
        if decimals is not None:
            decimals = max(0, int(decimals))
            if decimals == 0:
                # Points shown in the progress component are intentionally whole
                # numbers.  Only the displayed text drops the decimal portion;
                # the bar ratio itself still uses the full-precision score.
                return str(int(number))
            return (f"{number:.{decimals}f}").rstrip("0").rstrip(".")
        if abs(number - round(number)) < 1e-8:
            return str(int(round(number)))
        return ("{:.2f}".format(number)).rstrip("0").rstrip(".")

    def _draw_tier_progress(info, box, head_fill, head_text, highlight=False):
        """Draw one continuous, polished tier progress track.

        Design goals:
        - keep one single bar across all tiers;
        - use a low-radius rectangular trough instead of a capsule;
        - use a strictly rectangular filled segment;
        - show tier milestones as tiny marks with compact per-bar score labels;
        - omit the final/max milestone because the total is already in the score;
        - omit the current-position cursor line; the fill edge is sufficient;
        - supersample the whole component before compositing to remove the
          pixel-stepped look of tiny text, borders and milestone markers.
        """
        progress = info.get("tier_progress") if isinstance(info.get("tier_progress"), dict) else None
        if not progress:
            return
        try:
            current = max(0.0, float(progress.get("score", 0) or 0))
            maximum = float(progress.get("max", 0) or 0)
        except Exception:
            return
        if maximum <= 0:
            return

        threshold_items = []
        for item in progress.get("thresholds") or []:
            try:
                value = float(item.get("value", 0) or 0)
                tier = int(item.get("tier", len(threshold_items) + 1) or (len(threshold_items) + 1))
            except Exception:
                continue
            # The max/final tier is the endpoint of the whole bar and is already
            # represented by the ``current / maximum`` score, so do not add a
            # redundant marker at 100%.
            if 0 < value < maximum - 1e-8:
                threshold_items.append({"tier": tier, "value": value})
        threshold_items.sort(key=lambda item: (item["value"], item["tier"]))

        bx1, by1, bx2, by2 = map(int, box)
        if bx2 - bx1 < 180 or by2 - by1 < 42:
            return

        track_h = tier_progress_track_h
        label_font_probe = get_font(tier_progress_label_font_size, True)
        label_probe_bb = d.textbbox((0, 0), "2520", font=label_font_probe)
        label_h = max(7, label_probe_bb[3] - label_probe_bb[1]) if threshold_items else 0
        # Labels may live either beneath the track (legacy) or inside it.
        # Inside labels consume no extra vertical lane, so the whole progress
        # component stays vertically centered in the Day header.
        label_lane_h = (tier_progress_label_gap + label_h) if (threshold_items and tier_progress_label_position != "inside_right") else 0
        block_h = max(track_h + label_lane_h, tier_progress_icon_size if _tier_point_source is not None else track_h)
        track_y = int(round(by1 + max(0, (by2 - by1 - block_h) / 2) + tier_progress_vertical_offset))
        icon_size = tier_progress_icon_size if _tier_point_source is not None else 0
        icon_cx = bx1 + icon_size // 2 if icon_size else bx1
        track_x1 = bx1 + (icon_size * 3 // 5 if icon_size else 0)
        track_x2 = bx2
        if track_x2 - track_x1 < 140:
            track_x1 = bx1
            icon_size = 0

        # Draw the tiny component at higher resolution, then downsample with
        # LANCZOS.  This is the main anti-aliasing pass that removes the rough
        # one-pixel stair-stepping visible in the previous version.
        ss = tier_progress_supersample
        local_w = max(1, bx2 - bx1)
        local_h = max(1, by2 - by1)
        layer = Image.new("RGBA", (local_w * ss, local_h * ss), (0, 0, 0, 0))
        ld = ImageDraw.Draw(layer)

        def sx(x):
            return int(round((x - bx1) * ss))

        def sy(y):
            return int(round((y - by1) * ss))

        # Use ONE neutral/light progress palette for both normal and special
        # days.  The ordinary Day header is light, so the track must live in
        # that same light family; special-day emphasis remains the header +
        # yellow pennant, not a second darker progress-bar style.
        progress_light = theme_colors.get("day_header", light)
        trough = _rgb_mix(progress_light, primary, tier_progress_track_primary_mix)
        trough_outline = _rgb_mix(primary, dark, tier_progress_track_outline_dark_mix)
        trough_inner = _rgb_mix(trough, "#FFFFFF", 0.28)
        fill_color = _rgb_mix(progress_light, primary, tier_progress_fill_primary_mix)
        fill_top = _rgb_mix(fill_color, "#FFFFFF", 0.16)
        radius = tier_progress_track_radius * ss

        tx1, ty1, tx2, ty2 = sx(track_x1), sy(track_y), sx(track_x2), sy(track_y + track_h)
        ld.rounded_rectangle(
            (tx1, ty1, tx2, ty2),
            radius=radius,
            fill=trough,
            outline=trough_outline if tier_progress_track_outline else None,
            width=max(1, tier_progress_track_outline_width * ss),
        )

        # Subtle inset highlight/shadow gives the small bar a machined UI edge
        # without turning it into a glossy capsule.
        inset = max(1, ss)
        ld.line((tx1 + radius, ty1 + inset, tx2 - radius, ty1 + inset), fill=(*trough_inner, 110), width=max(1, ss // 2))
        shadow_color = _rgb_mix(trough, primary, 0.18)
        ld.line((tx1 + radius, ty2 - inset, tx2 - radius, ty2 - inset), fill=(*shadow_color, 95), width=max(1, ss // 2))

        inner_pad = tier_progress_track_inner_pad
        ix1 = track_x1 + inner_pad
        iy1 = track_y + inner_pad
        ix2 = track_x2 - inner_pad
        iy2 = track_y + track_h - inner_pad
        inner_w = max(1, ix2 - ix1)
        ratio = max(0.0, min(1.0, current / maximum))
        fill_x2 = int(round(ix1 + inner_w * ratio))

        if fill_x2 > ix1:
            # Deliberately square/rectangular fill: no ellipse/capsule at either
            # end.  The outer trough still has a restrained 4px corner radius.
            fx2 = max(ix1 + 1, min(ix2, fill_x2))
            ld.rectangle((sx(ix1), sy(iy1), sx(fx2), sy(iy2)), fill=fill_color)
            gloss_h = max(1, int(round((iy2 - iy1) * 0.36)))
            if gloss_h > 0:
                ld.rectangle((sx(ix1), sy(iy1), sx(fx2), sy(iy1 + gloss_h)), fill=(*fill_top, 220))

        marker_size = tier_progress_marker_size
        label_font = get_font(tier_progress_label_font_size * ss, True)
        # On special-day headers the lane behind milestone labels is the
        # saturated primary color.  Reuse the high-contrast header text color
        # there instead of the normal muted label color; otherwise the small
        # 210/630/1060/2520 values visually sink into the dark header.
        if tier_progress_label_position == "inside_right":
            # Inside labels always sit on the same light progress trough, even
            # on special days.  Use the same dark, theme-aware ink for every
            # Day so Day4~Day6 do not turn into low-contrast white-on-light
            # text merely because their surrounding header is highlighted.
            marker_fill = _rgb_mix(primary, dark, 0.16)
            label_rgb = _rgb_mix(dark, primary, 0.12)
            label_alpha = 235
        elif highlight:
            marker_fill = _rgb_mix(head_text, "#FFFFFF", 0.08)
            label_rgb = _rgb_mix(head_text, "#FFFFFF", 0.06)
            label_alpha = 255
        else:
            marker_fill = _rgb_mix(primary, "#FFFFFF", 0.18)
            label_rgb = _rgb_mix(dark, progress_light, 0.30)
            label_alpha = 230
        for item in threshold_items:
            value = item["value"]
            pos_ratio = max(0.0, min(1.0, value / maximum))
            mx = ix1 + inner_w * pos_ratio

            # Small diamonds mark each threshold.  The numeric threshold is
            # printed directly under its own marker, so the user can read the
            # scale locally without a separate shared legend.
            ms = marker_size
            my = track_y + track_h / 2
            diamond = [
                (sx(mx), sy(my - ms)),
                (sx(mx + ms), sy(my)),
                (sx(mx), sy(my + ms)),
                (sx(mx - ms), sy(my)),
            ]
            ld.polygon(diamond, fill=(*marker_fill, 210))

            label = _format_tier_progress_number(value, 0)
            lbb = ld.textbbox((0, 0), label, font=label_font)
            ltw = lbb[2] - lbb[0]
            # Put the threshold value slightly to the RIGHT of its diamond.
            # This keeps the node itself visually readable instead of having the
            # label centered directly beneath it.  The endpoint/max label is
            # handled separately below and remains right-aligned.
            label_x = sx(mx + tier_progress_label_x_offset) - lbb[0]
            min_x = sx(track_x1)
            max_x = sx(track_x2) - ltw
            label_x = max(min_x, min(max_x, label_x))
            if tier_progress_label_position == "inside_right":
                label_h_px = lbb[3] - lbb[1]
                label_y = (
                    (ty1 + ty2 - label_h_px) / 2
                    - lbb[1]
                    + tier_progress_label_vertical_offset * ss
                )
            else:
                label_y = sy(track_y + track_h + tier_progress_label_gap) - lbb[1]
            ld.text((label_x, label_y), label, font=label_font, fill=(*label_rgb, label_alpha))

        # Show the final/max score once at the far-right endpoint, without a
        # fifth marker.  Unlike the intermediate labels it does NOT receive the
        # rightward node offset, so 3980 remains visually anchored to the end.
        if tier_progress_show_max_label:
            max_label = _format_tier_progress_number(maximum, 0)
            mbb = ld.textbbox((0, 0), max_label, font=label_font)
            mtw = mbb[2] - mbb[0]
            # Keep the final 3980 visibly INSIDE the trough instead of hugging
            # the clipped outer edge.  Use the inner track boundary plus a
            # configurable right padding, and keep it marker-free.
            max_label_x = sx(ix2 - tier_progress_max_label_right_padding) - mtw - mbb[0]
            if tier_progress_label_position == "inside_right":
                max_label_h_px = mbb[3] - mbb[1]
                max_label_y = (
                    (ty1 + ty2 - max_label_h_px) / 2
                    - mbb[1]
                    + tier_progress_label_vertical_offset * ss
                )
            else:
                max_label_y = sy(track_y + track_h + tier_progress_label_gap) - mbb[1]
            ld.text((max_label_x, max_label_y), max_label, font=label_font, fill=(*label_rgb, label_alpha))

        score_text = "{} / {}".format(
            _format_tier_progress_number(current, 0),
            _format_tier_progress_number(maximum, 0),
        )
        score_font = get_font(tier_progress_score_font_size * ss, True)
        bb = ld.textbbox((0, 0), score_text, font=score_font)
        tw = bb[2] - bb[0]
        th = bb[3] - bb[1]
        sx_text = (tx1 + tx2 - tw) / 2 - bb[0]
        sy_text = (ty1 + ty2 - th) / 2 - bb[1] + tier_progress_score_vertical_offset * ss
        # No cursor line and no text shadow.  Dark theme text is quieter and
        # sharper on the new light trough than the previous high-contrast white
        # text treatment.
        # The current score sits inside the light track.  Give special days a
        # slightly deeper ink color and full opacity so the number remains
        # crisp even though the surrounding Day header itself is dark.
        score_rgb = _rgb_mix(dark, "#000000", 0.18) if highlight else _rgb_mix(dark, primary, 0.18)
        ld.text((sx_text, sy_text), score_text, font=score_font, fill=(*score_rgb, 255 if highlight else 245))

        layer = layer.resize((local_w, local_h), Image.Resampling.LANCZOS)
        img.alpha_composite(layer, (bx1, by1))

        if icon_size:
            _paste_tier_point_icon(icon_cx, track_y + track_h / 2, icon_size)

    # In stretch mode every Day uses the same right-side badge reserve.
    # This keeps all progress bars visually centered/aligned even on ordinary
    # days where the special-day pennant itself is absent.
    _tier_progress_badge_reserve_w = 0
    if tier_progress_reserve_badge_space:
        _badge_font = get_font(17, True)
        for _day_info in days:
            _badge_label = clean(str(_day_info.get("special_label") or ""))
            if not _badge_label:
                continue
            _tier_progress_badge_reserve_w = max(
                _tier_progress_badge_reserve_w,
                recommended_special_badge_width(
                    cfg, _badge_label, text_width(d, _badge_label, _badge_font), height=56
                ),
            )

    def day_card(info, x1, y1, x2, y2, highlight=False):
        head_h = day_head_h
        has_metrics = bool(info.get("metric_items"))
        body_fill = card_highlight if highlight else card_fill
        head_fill = primary if highlight else theme_colors.get("day_header", light)
        head_text = title_text_color if highlight else theme_colors.get("day_header_text", dark)
        outline = primary if highlight else card_border

        rounded(d, (x1, y1, x2, y2), 17, body_fill)
        d.rounded_rectangle((x1, y1, x2, y1+head_h), radius=17, fill=head_fill)
        d.rectangle((x1, y1+head_h//2, x2, y1+head_h), fill=head_fill)
        d.line((x1+2, y1+head_h, x2-2, y1+head_h), fill=outline, width=2)
        d.rounded_rectangle(
            (x1, y1, x2, y2), radius=17, fill=None,
            outline=outline, width=3 if highlight else 2
        )
        _draw_paper_watermark((x1, y1, x2, y2), head_h)

        day = clean(str(info.get("day") or "DAY"))
        target = clean(str(info.get("target") or ""))
        title = day + (("｜目标 " + target) if target else "")
        title_progress = info.get("tier_progress") if has_tier_progress_data else None
        if tier_progress_title_score and isinstance(title_progress, dict):
            try:
                title_score = float(title_progress.get("score", title_progress.get("current", 0)) or 0)
            except Exception:
                title_score = 0
            if title_score > 0:
                title += "({}分)".format(_format_tier_progress_number(title_score, 0))
        badge_w = 0
        if highlight:
            # 特殊日使用与参考图一致的黄色“矩形 + 倒三角”挂牌，
            # 不再用普通圆角胶囊，让收尾日/特殊节点一眼可见。
            badge_text = clean(str(info.get("special_label") or "")) or "重点"
            bf = get_font(17, True)
            badge_w = recommended_special_badge_width(
                cfg, badge_text, text_width(d, badge_text, bf), height=56
            )
            bx2 = x2 - 14
            bx1 = bx2 - badge_w
            draw_special_day_badge(
                img, d, (bx1, y1-6, bx2, y1+50),
                badge_text, primary, cfg
            )

        tier_progress = info.get("tier_progress") if has_tier_progress else None
        progress_left = None
        progress_right = None
        title_left = x1 + 20
        title_limit = x2 - 22 - badge_w
        if isinstance(tier_progress, dict):
            title_probe_font = get_font(24, True)
            title_probe_w = int(round(text_width(d, title, title_probe_font)))
            progress_left = int(round(title_left + title_probe_w + tier_progress_title_gap))

            # Stretch mode: use the entire middle lane between the target title
            # and the special-day badge zone.  Left/right gaps remain explicit
            # parameters, while the bar itself automatically grows with the card.
            reserve_badge_w = max(badge_w, _tier_progress_badge_reserve_w)
            safe_right = x2 - tier_progress_right_margin
            if reserve_badge_w:
                safe_right -= reserve_badge_w + tier_progress_badge_gap

            if tier_progress_layout in {"stretch", "stretch_between_title_badge", "fill_available"}:
                progress_right = safe_right
            else:
                progress_right = min(progress_left + tier_progress_width, safe_right)

            if progress_right - progress_left < tier_progress_min_width:
                # If the title is unusually long, allow the left edge to move
                # slightly back while still preserving the badge safety zone.
                progress_left = max(title_left + 170, progress_right - tier_progress_min_width)
            if progress_right - progress_left < 180:
                progress_left = None
                progress_right = None

        title_right = (progress_left - tier_progress_title_gap) if progress_left else title_limit
        draw_left(
            d, (title_left, y1+2, title_right, y1+head_h-2),
            title, head_text, max_size=24, min_size=18,
            bold=True, max_lines=1, line_gap=0, valign="center"
        )
        if progress_left is not None and progress_right is not None:
            _draw_tier_progress(
                info,
                (progress_left, y1+2, progress_right, y1+head_h-2),
                head_fill, head_text, highlight=highlight
            )

        # Remaining/expected status lives at the right in two rows. This gives
        # the action text the full card height instead of sacrificing a bottom strip.
        metric_w = 420 if has_metrics else 0
        action_right = (x2-metric_w-18) if has_metrics else (x2-22)
        action_text = _readable_action_text(info.get("action"))
        draw_left(
            d, (x1+22, y1+head_h+7, action_right, y2-9),
            action_text, text_color,
            max_size=shared_action_size, min_size=shared_action_size,
            bold=False, max_lines=action_max_lines, line_gap=action_line_gap,
            valign="center"
        )

        if has_metrics:
            _draw_metrics_right(
                info,
                (x2-metric_w+2, y1+head_h+8, x2-12, y2-9)
            )

    current_y = y
    special_indices = {
        i for i, item in enumerate(days)
        if clean(str(item.get("special_label", "")))
    }
    for i, info in enumerate(days):
        y1 = int(round(current_y))
        y2 = int(round(y1 + row_heights[i]))
        # Never draw past the plan area on the final row.
        if i == n-1:
            y2 = int(plan_bottom)
        day_card(
            info, 48, y1, W-48, y2,
            highlight=(i in special_indices)
        )
        current_y = y2 + row_gap

    if risk_items:
        ry = H - watermark_h - risk_h
        panel_top = ry + 12
        panel_bottom = H - watermark_h - 6
        draw_module_frame(img,d,(34,panel_top,W-34,panel_bottom),risk_primary,fill=risk_panel,radius=22,ornate=True)

        title_box = _draw_fixed_section_title(ry, "风险提示", risk_primary)

        bubble_gap = 6
        content_top = ry + 58
        content_bottom = panel_bottom - 8
        bubble_h = (content_bottom-content_top-bubble_gap*(len(risk_items)-1))/max(1,len(risk_items))
        for i, risk_item_text in enumerate(risk_items):
            by1=int(round(content_top+i*(bubble_h+bubble_gap)))
            by2=int(round(by1+bubble_h))
            rounded(d,(62,by1,W-62,by2),14,risk_bubble,outline=risk_border,width=2)
            icon_size=min(31,max(24,int((by2-by1)*0.55)))
            ix1=78; iy1=int((by1+by2-icon_size)/2)
            draw_warning_icon(img,d,(ix1,iy1,ix1+icon_size,iy1+icon_size))
            draw_left(
                d,(ix1+icon_size+18,by1+5,W-82,by2-5),risk_item_text,risk_text,
                max_size=20,min_size=15,bold=False,max_lines=3,line_gap=3
            )

    # Classic-only footer: group avatar + group text as one centered block.
    group_text = clean(str(guide.get("watermark", "") or ""))
    wm_left = resolve_path(cfg, cfg.get("watermark_group_icon"))
    fy1 = H-watermark_h
    footer_bg = theme_colors.get("footer_bg", apply_tint(primary, 0.91))
    d.rectangle((0, fy1, W, H), fill=footer_bg)
    d.line((0, fy1+1, W, fy1+1), fill=apply_tint(primary, 0.35), width=2)
    draw_group_footer(
        services, img, d, (0, fy1, W, H), group_text, primary,
        icon_path=wm_left, cfg=cfg, palette=theme_colors
    )

    perf_cfg = cfg.get("performance") if isinstance(cfg.get("performance"), dict) else {}
    png_optimize = bool(perf_cfg.get("png_optimize", False))
    png_compress_level = max(0, min(9, int(perf_cfg.get("png_compress_level", 1) or 1)))
    rgb = img.convert("RGB")
    rgb.save(
        out_path,
        "PNG",
        optimize=png_optimize,
        compress_level=png_compress_level,
    )
    if bool(perf_cfg.get("print_timing", False)):
        elapsed = time.perf_counter() - render_started
        print("[耗时] {}：{:.2f} 秒".format(out_path.name, elapsed))
