# -*- coding: utf-8 -*-
"""Comic storyboard renderer for guide-image-generator V35.x.

V35.64 makes guide content authoritative: Day typography/header bands and action
boxes are laid out first; character art is inserted only into the remaining
editorial whitespace and may break outward through the panel border. Stable
character randomisation is variant-aware, and page_style enables genuinely
different manga/comic-book mastheads rather than simple recolors.
"""
import math
import random
import time
from pathlib import Path
from PIL import Image, ImageDraw, ImageOps, ImageEnhance
from .shared import SharedRendererTools
from .reward_items import RewardItemRenderer

STYLE_IDS = ("comic_storyboard",)


def _font(s, size, bold=False):
    return s.get_font(max(7, int(size)), bool(bold))


def _rgba(hex_color, alpha=255):
    if isinstance(hex_color, tuple):
        if len(hex_color) == 4:
            return hex_color[:3] + (int(alpha),)
        return tuple(hex_color[:3]) + (int(alpha),)
    text = str(hex_color or "#000000").lstrip("#")
    try:
        if len(text) >= 6:
            return (int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16), int(alpha))
    except Exception:
        pass
    return (0, 0, 0, int(alpha))


def _special(info):
    for key in ("special_label", "special", "highlight"):
        v = info.get(key)
        if isinstance(v, bool) and v:
            return True
        if str(v or "").strip():
            return True
    return False




_LEGACY_CAPY_DEFAULTS = {
    0: "capy_01_scarf_wave",
    1: "capy_02_hoodie_walk",
    2: "capy_03_sport_run",
    3: "capy_04_cape_fly",
    4: "capy_10_sleepy_walk",
    5: "capy_12_crawl",
    6: "capy_11_football_cheer",
}

_SUPPORTED_CHARACTER_EXTS = (".png", ".webp", ".jpg", ".jpeg")


def _char_cfg(rcfg, key, legacy_key=None, default=None):
    """Read the generic character config while keeping V35.56 capybara aliases."""
    if isinstance(rcfg, dict):
        if key in rcfg:
            return rcfg.get(key)
        if legacy_key and legacy_key in rcfg:
            return rcfg.get(legacy_key)
    return default


def _resolve_user_path(guide, s, raw):
    """Resolve absolute or generator-relative paths without assuming one asset root."""
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    try:
        direct = Path(text).expanduser()
        if direct.is_absolute() and direct.exists():
            return direct
    except Exception:
        pass
    try:
        resolved = s.resolve_path(guide.get("cfg") or {}, text)
        if resolved and Path(resolved).exists():
            return Path(resolved)
    except Exception:
        pass
    # Last chance: a path relative to the current working directory.  This is
    # useful for portable folders launched directly from the generator root.
    try:
        direct = Path(text).expanduser()
        if direct.exists():
            return direct.resolve()
    except Exception:
        pass
    return None


def _character_asset_dir(guide, s, rcfg):
    raw = _char_cfg(
        rcfg, "character_asset_dir", "capybara_asset_dir",
        "assets/comic_storyboard/capybara/color"
    )
    return _resolve_user_path(guide, s, raw), str(raw or "")


def _character_day_map(rcfg):
    custom = _char_cfg(rcfg, "character_day_map", "capybara_day_map", {})
    return custom if isinstance(custom, dict) else {}


def _character_pool(guide, s, rcfg):
    """Return character images from the configured directory.

    V35.58 also accepts a *set root* such as ``assets/.../capybara``.  If that
    directory contains no images directly, ``color/`` is preferred and ``bw/``
    is used as a fallback.  This makes the folder layout from the sprite-pack
    work without forcing users to point at a specific child directory.
    """
    directory, raw = _character_asset_dir(guide, s, rcfg)
    if directory is None or not directory.is_dir():
        return []
    exts = _char_cfg(rcfg, "character_extensions", None, None)
    if isinstance(exts, (list, tuple)) and exts:
        allowed = tuple((str(x).lower() if str(x).startswith(".") else "."+str(x).lower()) for x in exts)
    else:
        allowed = _SUPPORTED_CHARACTER_EXTS

    mode = str(_char_cfg(rcfg, "character_render_mode", "capybara_render_mode", "manga_gray") or "manga_gray").lower()
    search_dirs = [directory]
    preferred = ("color", "bw") if mode not in ("original_bw", "bw_source") else ("bw", "color")
    for child in preferred:
        d = directory / child
        if d.is_dir():
            search_dirs.append(d)

    files = []
    used_dir = directory
    for d in search_dirs:
        candidate = sorted(
            (x for x in d.iterdir() if x.is_file() and x.suffix.lower() in allowed),
            key=lambda x: x.name.lower()
        )
        if candidate:
            files = candidate
            used_dir = d
            break

    cache = guide.setdefault("_comic_character_pool_cache", {}) if isinstance(guide, dict) else {}
    try:
        stamp = used_dir.stat().st_mtime_ns
    except Exception:
        stamp = 0
    key = (str(used_dir), stamp, tuple(x.name for x in files))
    if key in cache:
        return list(cache[key])
    cache.clear()
    cache[key] = files
    return list(files)


def _auto_character_path(guide, s, rcfg, idx):
    """Choose a character automatically, with optional stable randomisation.

    ``random_stable`` (the default) shuffles the pool from the guide title/sheet
    so D1-D7 get different images without changing every time the same guide is
    regenerated.  This is friendly to preview caching and visual comparisons.
    ``random_each_render`` deliberately changes the assignment on each render.
    ``cycle`` uses sorted folder order.
    """
    pool = _character_pool(guide, s, rcfg)
    if not pool:
        return None
    mode = str(_char_cfg(rcfg, "character_selection_mode", None, "random_stable") or "random_stable").lower().strip()
    if mode in ("cycle", "ordered", "sequence", "mapped"):
        return pool[idx % len(pool)]

    cache = guide.setdefault("_comic_character_assignment_cache", {}) if isinstance(guide, dict) else {}
    names = tuple(str(x) for x in pool)
    seed_cfg = str(_char_cfg(rcfg, "character_random_seed", None, "") or "").strip()
    if mode in ("random_each_render", "random_each", "random_live"):
        if isinstance(guide, dict):
            nonce = guide.setdefault("_comic_character_render_nonce", time.time_ns())
        else:
            nonce = time.time_ns()
        seed_text = f"{seed_cfg}|{nonce}"
    else:
        base = str((guide or {}).get("sheet") or (guide or {}).get("title") or "guide") if isinstance(guide, dict) else "guide"
        # V35.64: stable random remains stable inside one variant, but different
        # variants intentionally receive different character shuffles.
        variant_key = str(
            _char_cfg(rcfg, "character_variant_key", None, "")
            or _char_cfg(rcfg, "page_style", None, "")
            or "default"
        ).strip()
        seed_text = f"{seed_cfg}|{base}|variant={variant_key}|{'|'.join(names)}"
    key = (mode, seed_text, names)
    shuffled = cache.get(key)
    if shuffled is None:
        shuffled = list(pool)
        random.Random("comic-character:" + seed_text).shuffle(shuffled)
        cache.clear()
        cache[key] = list(shuffled)
    # A shuffled list naturally avoids repeats while the pool is large enough.
    return shuffled[idx % len(shuffled)]


def _mapped_character_value(info, idx, terminal=False, rcfg=None):
    """Pick the user's explicit Day mapping; otherwise use the folder order.

    Mapping values may be a filename/stem under character_asset_dir, a generator-
    relative path, or an absolute path. This intentionally makes the renderer
    character-agnostic: cats, people, slimes, mascots, etc. all work the same.
    """
    custom = _character_day_map(rcfg or {})
    mapped = str(custom.get(f"D{idx+1}") or custom.get(str(idx+1)) or "").strip()
    if mapped:
        return mapped
    return None


def _find_character_path(guide, s, rcfg, mapped, idx):
    directory, raw_dir = _character_asset_dir(guide, s, rcfg)

    # Explicit day mapping has highest priority. It may itself be a full path.
    if mapped:
        direct = _resolve_user_path(guide, s, mapped)
        if direct and direct.is_file():
            return direct
        if directory and directory.is_dir():
            m = Path(mapped)
            candidates = [directory / mapped]
            if not m.suffix:
                candidates.extend(directory / f"{mapped}{ext}" for ext in _SUPPORTED_CHARACTER_EXTS)
            for c in candidates:
                if c.exists() and c.is_file():
                    return c

    # Generic automatic mode: use the configured selection strategy.  By
    # default this is a stable random shuffle with no repeats when possible.
    auto = _auto_character_path(guide, s, rcfg, idx)
    if auto:
        return auto

    # Backward compatibility for the V35.56 capybara pack if an old theme.json
    # is being used and the generic directory is unavailable.
    legacy_name = _LEGACY_CAPY_DEFAULTS.get(idx, "capy_01_scarf_wave")
    fallback = _resolve_user_path(guide, s, f"assets/comic_storyboard/capybara/bw/{legacy_name}.png")
    return fallback if fallback and fallback.is_file() else None


def _prepare_character_image(guide, s, colors, rcfg, mapped, idx, mirror=False):
    """Load character art, style it in memory, and trim transparent outer canvas.

    V35.68 adds:
    - character_force_render_mode: a variant can override per-Day color rules.
    - vintage_color: preserve the original colors while simulating faded,
      warm, slightly posterized old-manga printing.
    """
    path = _find_character_path(guide, s, rcfg, mapped, idx)
    if not path:
        return None
    cache = guide.setdefault("_comic_character_cache", {}) if isinstance(guide, dict) else {}

    forced_mode = str(
        _char_cfg(rcfg, "character_force_render_mode", None, "") or ""
    ).lower().strip()

    global_mode = str(_char_cfg(
        rcfg, "character_render_mode", "capybara_render_mode", "manga_gray"
    ) or "manga_gray").lower().strip()

    mode = forced_mode or global_mode
    if not forced_mode:
        mode_map = _char_cfg(rcfg, "character_render_mode_map", None, {})
        if isinstance(mode_map, dict):
            day_mode = mode_map.get(f"D{idx+1}")
            if day_mode is None:
                day_mode = mode_map.get(str(idx+1))
            if day_mode not in (None, ""):
                mode = str(day_mode).lower().strip()

    contrast = float(
        _char_cfg(rcfg, "character_contrast", "capybara_contrast", 1.18)
        or 1.18
    )
    trim = bool(_char_cfg(rcfg, "character_trim_transparent", None, True))
    trim_pad = max(
        0, int(_char_cfg(rcfg, "character_trim_padding", None, 4) or 0)
    )

    vintage_sat = float(
        _char_cfg(rcfg, "character_vintage_saturation", None, 0.72) or 0.72
    )
    vintage_warm = float(
        _char_cfg(rcfg, "character_vintage_warm_mix", None, 0.10) or 0.10
    )
    vintage_brightness = float(
        _char_cfg(rcfg, "character_vintage_brightness", None, 0.96) or 0.96
    )
    vintage_bits = max(
        4, min(8, int(_char_cfg(rcfg, "character_vintage_bits", None, 6) or 6))
    )

    key = (
        str(path), mode, round(contrast, 3),
        round(vintage_sat, 3), round(vintage_warm, 3),
        round(vintage_brightness, 3), vintage_bits,
        str(colors.get("ink")), str(colors.get("paper")),
        bool(mirror), trim, trim_pad
    )
    if key in cache:
        return cache[key].copy()

    try:
        im = Image.open(path).convert("RGBA")
    except Exception:
        return None

    if trim:
        bbox = im.getchannel("A").getbbox()
        if bbox:
            l, t, r, b = bbox
            l = max(0, l-trim_pad)
            t = max(0, t-trim_pad)
            r = min(im.width, r+trim_pad)
            b = min(im.height, b+trim_pad)
            if r > l and b > t:
                im = im.crop((l, t, r, b))

    alpha = im.getchannel("A")

    if mode in ("vintage_color", "retro_color", "old_print_color"):
        # Keep the source hue relationships, but make them look like old
        # serialized-manga ink: lower chroma, warmer stock, denser midtones,
        # and reduced channel precision.
        rgb = im.convert("RGB")
        rgb = ImageEnhance.Color(rgb).enhance(max(0.25, min(1.25, vintage_sat)))
        rgb = ImageEnhance.Contrast(rgb).enhance(max(0.6, min(1.8, contrast)))
        rgb = ImageEnhance.Brightness(rgb).enhance(
            max(0.65, min(1.25, vintage_brightness))
        )
        warm_rgb = _rgba(
            _char_cfg(rcfg, "character_vintage_tint", None, "#D6A969"), 255
        )[:3]
        warm = Image.new("RGB", rgb.size, warm_rgb)
        rgb = Image.blend(rgb, warm, max(0.0, min(0.35, vintage_warm)))
        rgb = ImageOps.posterize(rgb, vintage_bits)
        im = rgb.convert("RGBA")
        im.putalpha(alpha)

    elif mode not in ("color", "original"):
        gray = ImageOps.grayscale(im.convert("RGB"))
        gray = ImageEnhance.Contrast(gray).enhance(
            max(.4, min(2.4, contrast))
        )
        if mode in ("manga_ink", "ink", "duotone"):
            gray = ImageOps.colorize(
                gray,
                black=colors.get("ink", "#171717"),
                white=colors.get("paper", "#FFFDF8")
            ).convert("RGBA")
            gray.putalpha(alpha)
            im = gray
        else:
            im = Image.merge("RGBA", (gray, gray, gray, alpha))

    if mirror:
        im = ImageOps.mirror(im)

    cache[key] = im.copy()
    return im

def _paste_character(base, guide, s, colors, rcfg, box, info, idx, terminal=False, lead=False):
    """Place any configured character artwork as part of the manga composition."""
    if not bool(_char_cfg(rcfg, "character_enabled", "capybara_enabled", True)):
        return None
    x1, y1, x2, y2 = map(int, box)
    pw, ph = x2-x1, y2-y1
    min_pw = int(_char_cfg(rcfg, "character_min_panel_width", None, 185) or 185)
    min_ph = int(_char_cfg(rcfg, "character_min_panel_height", None, 132) or 132)
    if pw < min_pw or ph < min_ph:
        return None

    mapped = _mapped_character_value(info, idx, terminal=terminal, rcfg=rcfg)
    side_map = _char_cfg(rcfg, "character_side_map", None, {})
    forced_side = ""
    if isinstance(side_map, dict):
        forced_side = str(side_map.get(f"D{idx+1}") or side_map.get(str(idx+1)) or "").lower().strip()
    side = forced_side if forced_side in ("left", "right") else ("left" if idx in (0, 2, 5, 6) else "right")
    mirror = side == "right" and bool(_char_cfg(rcfg, "character_auto_mirror", None, True))
    im = _prepare_character_image(guide, s, colors, rcfg, mapped, idx, mirror=mirror)
    if im is None:
        return None

    scale = float(_char_cfg(rcfg, "character_scale", "capybara_scale", 1.0) or 1.0)
    scale_map = _char_cfg(rcfg, "character_scale_map", None, {})
    if isinstance(scale_map, dict):
        try:
            scale *= float(scale_map.get(f"D{idx+1}") or scale_map.get(str(idx+1)) or 1.0)
        except Exception:
            pass
    frac = 0.79 if terminal else (0.72 if lead else 0.68)
    if idx in (2, 3):
        frac += .04
    target_h = int(min(ph*frac*scale, 265 if terminal else 215))
    target_h = max(88, target_h)
    ratio = im.width / max(1, im.height)
    target_w = int(target_h * ratio)
    width_fraction = 0.38 if terminal else (0.34 if pw < 390 else 0.36)
    target_w = min(target_w, int(pw*width_fraction))

    # Never let the artwork consume the text area in a narrow panel.  Instead
    # shrink the figure just enough to guarantee a useful instruction column.
    text_min = int(_char_cfg(rcfg, "character_text_min_width", None, 170) or 170)
    margin_cost = 42 if side == "right" else 34
    max_character_w = max(72, pw - text_min - margin_cost)
    target_w = min(target_w, max_character_w)
    target_w = max(72, target_w)
    target_h = int(target_w / max(.01, ratio))
    if target_h > ph*0.78:
        target_h = int(ph*0.78)
        target_w = int(target_h*ratio)
    im = im.resize((max(1,target_w), max(1,target_h)), Image.Resampling.LANCZOS)

    opacity = max(40, min(255, int(_char_cfg(rcfg, "character_opacity", "capybara_opacity", 245) or 245)))
    if opacity < 255:
        a = im.getchannel("A").point(lambda v: int(v*opacity/255))
        im.putalpha(a)
    break_frame = bool(_char_cfg(rcfg, "character_break_frame", "capybara_break_frame", True))
    overflow = int(12 if break_frame else 0)
    bottom = y2 + (8 if break_frame and idx in (1, 3, 6) else -7)
    py = int(bottom - target_h)
    if side == "left":
        px = x1 + (5 if not break_frame else -overflow)
        reserve_edge = min(x2-120, px + target_w + 12)
        reserve = ("left", reserve_edge)
    else:
        px = x2 - target_w - (5 if not break_frame else -overflow)
        reserve_edge = max(x1+120, px - 12)
        reserve = ("right", reserve_edge)
    # A subtle white keyline separates grayscale characters from screentone.
    outline = int(_char_cfg(rcfg, "character_outline_width", None, 2) or 0)
    if outline > 0:
        alpha = im.getchannel("A")
        try:
            from PIL import ImageFilter
            expanded = alpha.filter(ImageFilter.MaxFilter(outline*2+1))
            halo = Image.new("RGBA", im.size, _rgba(colors.get("paper", "#FFFDF8"), 220))
            halo.putalpha(expanded)
            base.alpha_composite(halo, (int(px), int(py)))
        except Exception:
            pass
    base.alpha_composite(im, (int(px), int(py)))
    return {"side": reserve[0], "edge": reserve[1], "box": (int(px), int(py), int(px+target_w), int(py+target_h))}


def _paste_character_in_free_space(
    base, guide, s, colors, rcfg, panel_box, free_box, info, idx,
    side="left", terminal=False
):
    """Place decoration only inside whitespace left by the content layout.

    ``free_box`` is calculated after Day label, target, action box and metric bar.
    The character may extend OUTWARD through the panel edge, but never inward
    into the action box.  If the remaining whitespace is too small, no character
    is drawn; readability wins.
    """
    if not bool(_char_cfg(rcfg, "character_enabled", "capybara_enabled", True)):
        return None
    if not free_box:
        return None

    px1, py1, px2, py2 = map(int, panel_box)
    x1, y1, x2, y2 = map(int, free_box)
    fw, fh = x2-x1, y2-y1
    min_visible = int(_char_cfg(rcfg, "character_free_min_width", None, 58) or 58)
    min_h = int(_char_cfg(rcfg, "character_free_min_height", None, 72) or 72)
    if fw < min_visible or fh < min_h:
        return None

    mapped = _mapped_character_value(info, idx, terminal=terminal, rcfg=rcfg)
    mirror = side == "right" and bool(_char_cfg(rcfg, "character_auto_mirror", None, True))
    im = _prepare_character_image(guide, s, colors, rcfg, mapped, idx, mirror=mirror)
    if im is None:
        return None

    scale = float(_char_cfg(rcfg, "character_scale", "capybara_scale", 1.0) or 1.0)
    scale_map = _char_cfg(rcfg, "character_scale_map", None, {})
    if isinstance(scale_map, dict):
        try:
            scale *= float(scale_map.get(f"D{idx+1}") or scale_map.get(str(idx+1)) or 1.0)
        except Exception:
            pass

    ratio = im.width / max(1, im.height)
    break_frame = bool(_char_cfg(rcfg, "character_break_frame", "capybara_break_frame", True))
    overflow = int(_char_cfg(rcfg, "character_break_side_overflow", None, 14) or 0) if break_frame else 0
    bottom_overflow = int(_char_cfg(rcfg, "character_break_bottom_overflow", None, 7) or 0) if break_frame else 0

    # Outward overflow increases visual width without stealing content pixels.
    effective_w = fw + max(0, overflow)
    terminal_max_w = int(rcfg.get("character_terminal_max_width", 224) or 224)
    target_w = int(min(effective_w * .93, (terminal_max_w if terminal else 150)) * scale)
    target_w = max(min_visible, target_w)
    target_h = int(target_w / max(.01, ratio))

    max_h = int((fh + bottom_overflow) * .96)
    if target_h > max_h:
        target_h = max_h
        target_w = int(target_h * ratio)

    if target_w < min_visible or target_h < min_h:
        return None

    im = im.resize((max(1, target_w), max(1, target_h)), Image.Resampling.LANCZOS)
    opacity = max(40, min(255, int(_char_cfg(rcfg, "character_opacity", "capybara_opacity", 245) or 245)))
    if opacity < 255:
        a = im.getchannel("A").point(lambda v: int(v*opacity/255))
        im.putalpha(a)

    # Anchor the inner edge to the free-space boundary; overflow only goes out.
    yy = int(y2 + bottom_overflow - target_h)
    if side == "left":
        xx = int(x2 - target_w)
        xx = min(xx, x1)
        # never cross inward past free_box right edge
        xx = max(px1 - overflow, x2 - target_w)
    else:
        xx = int(x1)
        xx = min(px2 - target_w + overflow, xx)

    page_style = str(rcfg.get("page_style") or "shonen").lower().strip()
    outline = max(
        0,
        int(_char_cfg(rcfg, "character_outline_width", None, 2) or 0)
    )
    # V35.70: detective suspects use raw ink edges.  The generic white manga
    # halo was especially visible around a black culprit silhouette.
    if page_style == "detective_red":
        outline = 0
    if outline > 0:
        try:
            from PIL import ImageFilter
            alpha = im.getchannel("A")
            expanded = alpha.filter(ImageFilter.MaxFilter(outline*2+1))
            halo = Image.new("RGBA", im.size, _rgba(colors.get("paper", "#FFFDF8"), 220))
            halo.putalpha(expanded)
            base.alpha_composite(halo, (xx, yy))
        except Exception:
            pass
    base.alpha_composite(im, (xx, yy))
    return {
        "side": side,
        "box": (xx, yy, xx+target_w, yy+target_h),
        "image": im.copy(),
        "day_index": int(idx),
    }


def _render_kpis(guide, s, max_items=4):
    raw = list(guide.get("kpis") or [])[:max_items]
    try:
        return s.build_render_kpis(raw, guide.get("cfg") or {})[:max_items]
    except Exception:
        out = []
        for p in raw:
            if isinstance(p, (tuple, list)) and len(p) >= 2:
                out.append({"label": s.clean(str(p[0])), "value": s.clean(str(p[1])), "icon": None})
        return out


def _jitter_line(draw, p1, p2, fill, width, rng, passes=2, jitter=1):
    for _ in range(max(1, passes)):
        draw.line(
            (p1[0] + rng.randint(-jitter, jitter), p1[1] + rng.randint(-jitter, jitter),
             p2[0] + rng.randint(-jitter, jitter), p2[1] + rng.randint(-jitter, jitter)),
            fill=fill, width=max(1, int(width))
        )


def _panel_poly(box, skew=0, flip=False):
    x1, y1, x2, y2 = map(int, box)
    s = int(skew)
    if flip:
        return [(x1+s, y1), (x2, y1+s//2), (x2-s, y2), (x1, y2-s//2)]
    return [(x1, y1+s//2), (x2-s, y1), (x2, y2-s//2), (x1+s, y2)]


def _ink_poly(draw, poly, ink, rng, width=5):
    for i in range(len(poly)):
        a = poly[i]; b = poly[(i+1) % len(poly)]
        _jitter_line(draw, a, b, ink, width, rng, passes=2, jitter=1)


def _pattern_mask(base, poly, draw_pattern):
    mask = Image.new("L", base.size, 0)
    md = ImageDraw.Draw(mask)
    md.polygon(poly, fill=255)
    layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer, "RGBA")
    draw_pattern(ld)
    clipped = Image.new("RGBA", base.size, (0, 0, 0, 0))
    clipped.paste(layer, (0, 0), mask)
    base.alpha_composite(clipped)


def _halftone(draw, box, color, step=12, radius=1, alpha=45, offset=0):
    x1, y1, x2, y2 = map(int, box)
    c = _rgba(color, alpha)
    for yy in range(y1+offset, y2, step):
        shift = step//2 if ((yy-y1)//step) % 2 else 0
        for xx in range(x1+shift, x2, step):
            draw.ellipse((xx-radius, yy-radius, xx+radius, yy+radius), fill=c)


def _speedlines(draw, box, focus, color, rng, count=30, alpha=(28, 58)):
    x1, y1, x2, y2 = map(int, box); fx, fy = focus
    for _ in range(count):
        side = rng.choice((0, 1, 2, 3))
        if side == 0: px, py = rng.randint(x1, x2), y1
        elif side == 1: px, py = x2, rng.randint(y1, y2)
        elif side == 2: px, py = rng.randint(x1, x2), y2
        else: px, py = x1, rng.randint(y1, y2)
        t = rng.uniform(.18, .42)
        qx = int(px + (fx-px)*t); qy = int(py + (fy-py)*t)
        draw.line((px, py, qx, qy), fill=_rgba(color, rng.randint(alpha[0], alpha[1])), width=rng.choice((1, 1, 2)))


def _burst_polygon(cx, cy, rx, ry, n, rng, inner=(.65, .82)):
    pts = []
    for i in range(n*2):
        a = math.pi*2*i/(n*2) - math.pi/2
        rr = 1.0 if i % 2 == 0 else rng.uniform(inner[0], inner[1])
        pts.append((int(cx + math.cos(a)*rx*rr), int(cy + math.sin(a)*ry*rr)))
    return pts


def _rotated_text(base, text, s, size, color, angle=-8, bold=True, stroke=0, stroke_fill=None, alpha=255):
    f = _font(s, size, bold)
    tmp = Image.new("RGBA", (700, 220), (0, 0, 0, 0))
    td = ImageDraw.Draw(tmp, "RGBA")
    bb = td.textbbox((0, 0), text, font=f, stroke_width=stroke)
    w = max(8, bb[2]-bb[0]+30); h = max(8, bb[3]-bb[1]+30)
    tmp = Image.new("RGBA", (w, h), (0, 0, 0, 0)); td = ImageDraw.Draw(tmp, "RGBA")
    td.text((15-bb[0], 15-bb[1]), text, font=f, fill=_rgba(color, alpha), stroke_width=stroke,
            stroke_fill=stroke_fill if stroke else None)
    return tmp.rotate(angle, resample=Image.BICUBIC, expand=True)


def _paste_rotated_text(base, xy, text, s, size, color, angle=-8, bold=True, stroke=0, stroke_fill=None, alpha=255):
    layer = _rotated_text(base, text, s, size, color, angle, bold, stroke, stroke_fill, alpha)
    base.alpha_composite(layer, (int(xy[0]), int(xy[1])))


def _caption(draw, s, box, text, ink, paper, accent=None, angle=False, max_size=14):
    x1, y1, x2, y2 = map(int, box)
    if angle:
        pts = [(x1, y1+4), (x2-10, y1), (x2, y2-5), (x1+8, y2)]
        draw.polygon(pts, fill=ink)
    else:
        draw.rectangle((x1, y1, x2, y2), fill=ink)
    if accent:
        draw.rectangle((x1, y1, x1+6, y2), fill=accent)
    s.draw_center(draw, (x1+9, y1+2, x2-6, y2-2), text, paper,
                  max_size=max_size, min_size=max(9, max_size-6), bold=True, max_lines=1, line_gap=0)


def _speech_balloon(draw, s, box, text, ink, paper, max_size=19, min_size=11, tail="left", bold=True, line_gap=3):
    x1, y1, x2, y2 = map(int, box)
    # Rounded comic balloon with a deliberately heavy ink outline.
    draw.rounded_rectangle((x1, y1, x2, y2), radius=28, fill=paper, outline=ink, width=4)
    if tail == "left":
        pts = [(x1+16, y2-42), (x1-24, y2-15), (x1+45, y2-24)]
    elif tail == "right":
        pts = [(x2-18, y2-42), (x2+23, y2-17), (x2-48, y2-24)]
    elif tail == "top":
        pts = [(x1+42, y1+8), (x1+70, y1-24), (x1+92, y1+10)]
    else:
        pts = [(x2-76, y2-8), (x2-48, y2+24), (x2-26, y2-8)]
    draw.polygon(pts, fill=paper, outline=ink)
    s.draw_left(draw, (x1+20, y1+15, x2-20, y2-16), text, ink,
                max_size=max_size, min_size=min_size, bold=bold,
                max_lines=10, line_gap=line_gap, valign="center")


def _action_dialog_balloon(draw, s, box, text, ink, paper, max_size=19, min_size=11, tail="left", bold=True, line_gap=3):
    """Daily-operation balloon drawn as one continuous manga speech shape.

    The tail deliberately overlaps the rounded body.  Its base has no stroke:
    the tail fill erases the body outline beneath it, then only the two exposed
    tail edges are inked.  This removes the little internal triangle/base line
    and keeps the tail stroke exactly as heavy as the balloon border.
    """
    x1, y1, x2, y2 = map(int, box)
    h=max(1,y2-y1); w=max(1,x2-x1)
    radius=max(18,min(h//2-2,58))
    stroke=4

    if tail == "left":
        # Both attachment points sit *inside* the balloon so the tail fill
        # covers the body's border where the two shapes overlap.
        a=(x1+27,y2-49); tip=(x1-31,y2-8); b=(x1+76,y2-27)
    elif tail == "right":
        a=(x2-27,y2-49); tip=(x2+31,y2-8); b=(x2-76,y2-27)
    elif tail == "top":
        a=(x1+48,y1+14); tip=(x1+82,y1-31); b=(x1+114,y1+14)
    else:
        a=(x2-98,y2-15); tip=(x2-60,y2+31); b=(x2-25,y2-15)
    pts=[a,tip,b]

    # Soft offset shadow / rough-print registration.  Give the tail the same
    # shadow so it reads as part of the same physical balloon.
    draw.rounded_rectangle((x1+4,y1+5,x2+4,y2+5),radius=radius,fill=_rgba(ink,36))
    shadow_pts=[(px+4,py+5) for px,py in pts]
    draw.polygon(shadow_pts,fill=_rgba(ink,36))

    # Body first, then an overlapping tail WITHOUT a base outline.  Drawing the
    # paper-filled tail after the body is what hides the internal overlap seam.
    draw.rounded_rectangle((x1,y1,x2,y2),radius=radius,fill=paper,outline=ink,width=stroke)
    draw.polygon(pts,fill=paper)
    draw.line([a,tip,b],fill=ink,width=stroke,joint="curve")

    side_pad=max(17,min(28,int(w*0.055)))
    s.draw_left(draw,(x1+side_pad,y1+13,x2-side_pad,y2-14),text,ink,
                max_size=max_size,min_size=min_size,bold=bold,max_lines=10,
                line_gap=line_gap,valign="center")


def _narration_box(draw, s, box, title, body, ink, paper, accent):
    x1, y1, x2, y2 = map(int, box)
    draw.rectangle((x1+5, y1+6, x2+5, y2+6), fill=_rgba(ink, 45))
    draw.rectangle((x1, y1, x2, y2), fill=paper, outline=ink, width=4)
    draw.rectangle((x1, y1, x2, min(y2, y1+34)), fill=ink)
    draw.rectangle((x1, y1, x1+7, y2), fill=accent)
    s.draw_left(draw, (x1+14, y1+3, x2-8, y1+32), title, paper,
                max_size=12, min_size=9, bold=True, max_lines=1, line_gap=0, valign="center")
    s.draw_left(draw, (x1+15, y1+42, x2-12, y2-10), body, ink,
                max_size=14, min_size=9, bold=True, max_lines=3, line_gap=2, valign="center")


def _draw_kpi_cut_in(base, draw, guide, s, colors, rcfg, box, rng):
    x1, y1, x2, y2 = map(int, box)
    poly = _panel_poly(box, 14, False)
    page_style = str(rcfg.get("page_style") or "shonen").lower().strip()
    outer_fill = colors["panel_dark"]
    if page_style == "vintage_print":
        outer_fill = str(rcfg.get("vintage_resource_panel") or "#8F3F34")
    elif page_style == "detective_red":
        outer_fill = colors["ink"]
    draw.polygon(poly, fill=outer_fill)
    _ink_poly(draw, poly, colors["ink"], rng, width=6)
    _pattern_mask(base, poly, lambda pd: _halftone(pd, (x1, y1, x2, y2), colors["paper"], step=14, radius=1, alpha=32))
    _caption(draw, s, (x1+18, y1+14, x1+292, y1+56), str(rcfg.get("budget_title") or "资源状态 / STATUS"), colors["ink"], colors["paper"], colors["accent"], True, max_size=int(rcfg.get("cutin_title_font_size", 16) or 16))
    side_word = "EVIDENCE!" if page_style == "detective_red" else "CHECK!"
    side_color = colors["accent"] if page_style == "detective_red" else colors["accent2"]
    _paste_rotated_text(
        base, (x2-156, y1+12), side_word, s, 22,
        side_color, -7, True, 2, colors["ink"], 235
    )
    items = _render_kpis(guide, s, int(rcfg.get("budget_max_items", 4) or 4))
    if not items:
        s.draw_center(draw, (x1+20, y1+70, x2-20, y2-16), "暂无资源预算", colors["paper"], max_size=18, min_size=12, bold=True, max_lines=1)
        return
    cols = 2; gap = 12
    ax1, ay1, ax2, ay2 = x1+22, y1+72, x2-22, y2-18
    cw = (ax2-ax1-gap)/2; rh = (ay2-ay1-gap)/2
    for i, item in enumerate(items[:4]):
        col, row = i%2, i//2
        a = int(ax1+col*(cw+gap)); b = int(ay1+row*(rh+gap)); c = int(a+cw); e = int(b+rh)
        # white info insert like a manga stats annotation, not a button
        draw.polygon([(a, b+4), (c-6, b), (c, e-4), (a+5, e)], fill=colors["paper"], outline=colors["ink"])
        icon = item.get("icon")
        isz = min(34, e-b-10)
        ib = (a+9, int(b+(e-b-isz)/2), a+9+isz, int(b+(e-b-isz)/2)+isz)
        if icon and Path(icon).exists():
            s.draw_image_contain(base, Path(icon), ib)
        else:
            draw.ellipse((ib[0]+6, ib[1]+6, ib[2]-6, ib[3]-6), outline=colors["accent"], width=2)
        label = s.clean(str(item.get("label") or "资源")); value = s.clean(str(item.get("value") or "—"))
        tx = ib[2]+7
        s.draw_left(draw, (tx, b+4, c-7, b+29), label, colors["ink_mid"],
                    max_size=int(rcfg.get("resource_label_font_size", 13) or 13),
                    min_size=int(rcfg.get("resource_label_min_font_size", 9) or 9),
                    bold=True, max_lines=1, line_gap=0, valign="center")
        s.draw_left(draw, (tx, b+27, c-7, e-3), value, colors["ink"],
                    max_size=int(rcfg.get("resource_value_font_size", 23) or 23),
                    min_size=int(rcfg.get("resource_value_min_font_size", 14) or 14),
                    bold=True, max_lines=1, line_gap=0, valign="center")



def _draw_reward_icons_comic(base, draw, guide, s, colors, rcfg, box):
    """Comic loot strip using the shared reward artwork layer."""
    tools = SharedRendererTools(s)
    leaves = tools.flat_reward_items(guide.get("reward_items") or [])[:int(rcfg.get("reward_max_items", 5) or 5)]
    x1, y1, x2, y2 = map(int, box)
    if not leaves:
        s.draw_center(draw, (x1+8, y1+4, x2-8, y2-4), tools.reward_summary(guide), colors["ink"],
                      max_size=int(rcfg.get("reward_item_font_size", 13) or 13),
                      min_size=9, bold=True, max_lines=3, line_gap=2)
        return

    gap = 8
    cell_w = (x2-x1-gap*max(0, len(leaves)-1))/max(1, len(leaves))
    frame_size_cfg = int(rcfg.get("reward_frame_size", 66) or 66)
    inset_plain = max(2, int(rcfg.get("reward_icon_plain_inset", 5) or 5))
    name_size = int(rcfg.get("reward_item_font_size", 13) or 13)
    name_min = int(rcfg.get("reward_item_min_font_size", 9) or 9)
    reward_renderer = RewardItemRenderer(s, guide)

    for i, item in enumerate(leaves):
        cx1 = int(round(x1 + i*(cell_w+gap)))
        cx2 = int(round(cx1 + cell_w))
        name_h = 34
        icon_size = int(min(cell_w-8, y2-y1-name_h-4, frame_size_cfg))
        icon_size = max(26, icon_size)
        ix1 = int(cx1 + (cell_w-icon_size)/2)
        iy1 = y1 + 2
        ibox = (ix1, iy1, ix1+icon_size, iy1+icon_size)

        resolved = reward_renderer.draw_icon(
            base, item, ibox,
            # Framed reward geometry is global; frameless comic variants may keep a custom plain inset.
            plain_inset=inset_plain,
        )
        icon_path = resolved.get("icon_path")
        frame_path = resolved.get("frame_path")
        has_frame = bool(frame_path and Path(frame_path).exists())
        if not (icon_path and Path(icon_path).exists()) and not has_frame:
            draw.rounded_rectangle(ibox, radius=7, outline=colors["accent"], width=2)
            s.draw_center(draw, ibox, "?", colors["accent"], max_size=19, min_size=12, bold=True, max_lines=1)

        qty = s.clean(str(item.get("qty") or ""))
        label = s.clean(str(item.get("name") or "物品")) + ((" ×" + qty) if qty else "")
        s.draw_center(draw, (cx1, min(y2-31, iy1+icon_size+1), cx2, y2), label, colors["ink"],
                      max_size=name_size, min_size=name_min, bold=True, max_lines=2, line_gap=0)


def _draw_reward_cut_in(base, draw, guide, s, tools, colors, rcfg, box, rng):
    x1, y1, x2, y2 = map(int, box)
    poly = _panel_poly(box, 16, True)
    page_style = str(rcfg.get("page_style") or "shonen").lower().strip()
    outer_fill = colors["panel_dark"]
    if page_style == "vintage_print":
        outer_fill = str(rcfg.get("vintage_reward_panel") or "#443328")
    elif page_style == "detective_red":
        outer_fill = colors["ink"]
    # Match the resource insert while allowing variants to use distinct printed plates.
    draw.polygon(poly, fill=outer_fill)
    _pattern_mask(base, poly, lambda pd: _halftone(pd, (x1, y1, x2, y2), colors["paper"], step=14, radius=1, alpha=32, offset=1))
    _ink_poly(draw, poly, colors["ink"], rng, width=6)
    _caption(draw, s, (x1+18, y1+14, x1+292, y1+56), str(rcfg.get("reward_title") or "战利品特写 / LOOT"), colors["ink"], colors["paper"], colors["accent2"], True, max_size=int(rcfg.get("cutin_title_font_size", 16) or 16))
    reward_word = "CLUE!!" if page_style == "detective_red" else "DROP!!"
    _paste_rotated_text(
        base, (x2-150, y1+5), reward_word, s, 27,
        colors["accent"], 8, True, 2, colors["paper"], 235
    )
    if page_style == "detective_red":
        _draw_magnifier(
            draw, (x2-58, y1+96), 26, colors,
            width=5, alpha=215, angle=46
        )
    # The large loot field now uses the same dark/halftone language as STATUS.
    # Individual items remain readable on small pale paper tickets.
    rx1, ry1, rx2, ry2 = x1+22, y1+70, x2-22, y2-18
    draw.rectangle((rx1+5, ry1+6, rx2+5, ry2+6), fill=_rgba(colors["ink"], 62))
    inner_fill = (
        outer_fill
        if page_style in ("vintage_print", "detective_red")
        else colors["panel_dark"]
    )
    draw.rectangle(
        (rx1, ry1, rx2, ry2),
        fill=inner_fill, outline=colors["ink"], width=4
    )
    _halftone(draw, (rx1+3, ry1+3, rx2-3, ry2-3), colors["paper"], step=15, radius=1, alpha=28, offset=2)

    # Draw each loot item on its own tiny manga data ticket; the big background
    # stays dark, matching the resource panel instead of turning white.
    cfg = guide.get("cfg") or {}
    leaves = tools.flat_reward_items(guide.get("reward_items") or [])[:int(rcfg.get("reward_max_items", 5) or 5)]
    if not leaves:
        s.draw_center(draw, (rx1+12, ry1+10, rx2-12, ry2-10), tools.reward_summary(guide), colors["paper"],
                      max_size=int(rcfg.get("reward_item_font_size", 13) or 13), min_size=9,
                      bold=True, max_lines=3, line_gap=2)
        return
    # Readability-first loot grid: up to three columns, two rows for 4-6
    # rewards.  This is less "poster-like" than a five-item strip, but keeps
    # real item names readable without 9px text.
    gap_x = 7
    gap_y = 6
    inner = (rx1+8, ry1+8, rx2-8, ry2-8)
    ix1, iy1, ix2, iy2 = inner
    n = len(leaves)
    cols = min(3, n)
    rows = int(math.ceil(n / float(cols)))
    cell_w = (ix2-ix1-gap_x*max(0, cols-1))/max(1, cols)
    cell_h = (iy2-iy1-gap_y*max(0, rows-1))/max(1, rows)
    frame_size_cfg = int(rcfg.get("reward_frame_size", 66) or 66)
    inset_plain = max(2, int(rcfg.get("reward_icon_plain_inset", 5) or 5))
    name_size = int(rcfg.get("reward_item_font_size", 15) or 15)
    name_min = int(rcfg.get("reward_item_min_font_size", 13) or 13)
    reward_renderer = RewardItemRenderer(s, guide)

    for i, item in enumerate(leaves):
        rr, cc = divmod(i, cols)
        a = int(round(ix1 + cc*(cell_w+gap_x)))
        b = int(round(iy1 + rr*(cell_h+gap_y)))
        c = int(round(a + cell_w))
        e = int(round(b + cell_h))
        draw.polygon(
            [(a+2, b+3), (c-4, b), (c, e-3), (a+5, e)],
            fill=colors["paper"], outline=colors["ink"]
        )

        name_h = min(38, max(30, int(cell_h*0.38)))
        icon_size = int(min(cell_w-10, cell_h-name_h-5, frame_size_cfg))
        icon_size = max(28, icon_size)
        px1 = int(a+(cell_w-icon_size)/2)
        py1 = b+3
        ibox = (px1, py1, px1+icon_size, py1+icon_size)
        resolved = reward_renderer.draw_icon(
            base, item, ibox,
            # Framed reward geometry is global; frameless comic variants may keep a custom plain inset.
            plain_inset=inset_plain,
        )
        icon_path = resolved.get("icon_path")
        frame_path = resolved.get("frame_path")
        has_frame = bool(frame_path and Path(frame_path).exists())
        if not (icon_path and Path(icon_path).exists()) and not has_frame:
            draw.rounded_rectangle(ibox, radius=7, outline=colors["accent"], width=2)
            s.draw_center(draw, ibox, "?", colors["accent"], max_size=19, min_size=12, bold=True, max_lines=1)

        qty = s.clean(str(item.get("qty") or ""))
        label = s.clean(str(item.get("name") or "物品")) + ((" ×"+qty) if qty else "")
        s.draw_center(
            draw, (a+4, max(b+icon_size+4, e-name_h), c-4, e-2),
            label, colors["ink"],
            max_size=name_size, min_size=name_min,
            bold=True, max_lines=2, line_gap=1
        )


def _day_label(info, idx):
    day = str(info.get("day") or f"DAY {idx+1}")
    if any(ch.isdigit() for ch in day):
        return day.replace("Day", "D").replace("DAY", "D")
    return f"D{idx+1}"


def _split_action_steps(text):
    """Split guide action text into comic command beats without dropping content.

    Circled list numerals (①②③...) and ordinary list prefixes are treated as
    source formatting only. The renderer supplies its own clean 1..N badges.
    """
    import re
    raw = str(text or "").replace("\r", "\n").strip()
    if not raw:
        return []
    circled = "①②③④⑤⑥⑦⑧⑨⑩"
    # Turn circled numerals into explicit separators, even when the source text
    # puts all steps on one line with no spaces.
    for i, ch in enumerate(circled, 1):
        raw = raw.replace(ch, f"\n{i}. ")
    lines = [x.strip() for x in raw.split("\n") if x.strip()]
    out = []
    for line in lines:
        # Split 1. / 1、 / 1) / 1） / 1: sequences that appear mid-line.
        parts = re.split(r"(?=(?<!\d)[1-9][\.、\)）:]\s*)", line)
        parts = [x.strip() for x in parts if x.strip()]
        for part in (parts or [line]):
            cleaned = re.sub(r"^[1-9][\.、\)）:]\s*", "", part).strip()
            cleaned = re.sub(r"^[①②③④⑤⑥⑦⑧⑨⑩]\s*", "", cleaned).strip()
            if cleaned:
                out.append(cleaned)
    return out


def _action_weight(info):
    """Approximate how much panel area a day's instructions deserve."""
    text = str((info or {}).get("action") or "").strip()
    steps = _split_action_steps(text)
    chars = len(text.replace("\n", ""))
    # Weight long prose and many explicit steps, while keeping the range tame.
    w = 1.0 + min(2.5, chars / 72.0) + min(1.5, max(0, len(steps)-1) * 0.28)
    if _special(info or {}):
        w += 0.18
    return max(1.0, w)


def _dynamic_day_slots(days, top=485, d7_top=1510, left=44, right=1036, min_panel_width=315):
    """Strongly content-aware D1-D6 manga mosaic.

    The previous version still converged toward six similarly sized boxes.  This
    layout deliberately exaggerates panel hierarchy: within every D1/D2,
    D3/D4, D5/D6 pair the text-heavier day receives a visibly larger share,
    while near-ties fall back to alternating 35/65-ish manga splits.  Row height
    is also driven by the heaviest day in that row, so dense instructions gain
    both width *and* height rather than merely shrinking their font.
    """
    first = list(days[:6])
    while len(first) < 6:
        first.append({})
    weights = [_action_weight(x) for x in first]
    pairs = [(0, 1), (2, 3), (4, 5)]

    # Row heights respond strongly to content density.  A power curve gives the
    # heaviest row a clearly larger footprint while preserving a useful minimum.
    loads = [max(weights[a], weights[b]) + 0.18*(weights[a] + weights[b]) for a, b in pairs]
    row_gap = 20
    total_h = max(760, d7_top - top - row_gap*2)
    min_h = 220.0
    spare = max(0.0, total_h - min_h*3)
    shaped = [max(0.01, x)**1.55 for x in loads]
    shaped_sum = sum(shaped) or 1.0
    heights = [min_h + spare*(x/shaped_sum) for x in shaped]
    scale = total_h / max(1.0, sum(heights))
    heights = [h*scale for h in heights]

    slots = [None]*6
    y = float(top)
    inner_w = right - left
    # Near-equal pairs still get a bold asymmetric comic rhythm instead of 50/50.
    tie_ratios = (0.35, 0.66, 0.40)
    pair_gaps = (18, 24, 19)
    offsets = ((14, 0), (0, 16), (12, 0))

    for row, (a, b) in enumerate(pairs):
        h = heights[row]
        gap = pair_gaps[row]
        wa, wb = weights[a], weights[b]
        rel = abs(wa - wb) / max(0.01, wa + wb)
        if rel < 0.085:
            ratio = tie_ratios[row]
        else:
            # Strong hierarchy: the text-heavier day gets roughly 60-72% width.
            heavy_share = min(0.72, 0.59 + rel*0.62)
            ratio = heavy_share if wa > wb else 1.0 - heavy_share
        usable_w = inner_w - gap
        # Keep the composition clearly irregular without creating sliver panels
        # that cannot hold both character art and readable guide text.
        min_ratio = max(0.30, min(0.46, float(min_panel_width) / max(1.0, usable_w)))
        ratio = max(min_ratio, min(1.0-min_ratio, ratio))
        lw = int(round(usable_w * ratio))
        oy_l, oy_r = offsets[row]
        y1 = int(round(y)); y2 = int(round(y + h))

        lbox = (left, y1 + oy_l, left + lw, y2)
        rbox = (left + lw + gap, y1 + oy_r, right, y2 - (5 if row == 1 else 0))
        lwidth = lbox[2] - lbox[0]
        rwidth = rbox[2] - rbox[0]
        slots[a] = (lbox, "tone" if row != 1 else "speed", lwidth > 540 or weights[a] > 2.45)
        slots[b] = (rbox, "speed" if row != 2 else "tone", rwidth > 540 or weights[b] > 2.45)
        y += h + row_gap
    return slots

def _draw_command_strips(draw, s, box, steps, colors, rcfg, terminal=False):
    """Numbered manga command strips for multi-step days, especially D7.

    V35.66: terminal rows use a protected minimum rhythm and badges are drawn
    from square bounding boxes, so 1/2/3/4/5 can never become oval simply
    because a row is short.
    """
    x1, y1, x2, y2 = map(int, box)
    n = max(1, len(steps))

    if terminal:
        gap = max(4, int(rcfg.get("terminal_command_gap", 6) or 6))
        min_row = max(34, int(rcfg.get("terminal_command_min_row_height", 40) or 40))
    else:
        gap = 6
        min_row = 28

    available_h = max(1, y2-y1)
    # Prefer the configured minimum row height. If a custom theme makes the D7
    # panel unusually short, reduce gaps first; only then allow rows to shrink.
    needed = n*min_row + (n-1)*gap
    if terminal and needed > available_h and n > 1:
        gap = max(2, int((available_h - n*min_row) / (n-1)))
    usable = max(n*22, available_h-gap*(n-1))
    rh = usable / n

    max_font = int(rcfg.get("day_action_font_size", 19) or 19) + (1 if terminal else 0)
    min_font = int(rcfg.get("day_action_min_font_size", 12) or 12)

    for i, step in enumerate(steps):
        yy1 = int(round(y1 + i*(rh+gap)))
        yy2 = int(round(y1 + (i+1)*rh + i*gap))
        yy2 = min(y2, yy2)
        row_h = max(1, yy2-yy1)

        if terminal and i == n-1:
            fill = colors["ink"]; txt = colors["paper"]; edge = colors["accent"]
        else:
            fill = colors["paper"] if i % 2 == 0 else colors["panel_fill_alt"]
            txt = colors["ink"]; edge = colors["accent"] if i == 0 else colors["ink"]

        poly = [(x1+5, yy1), (x2-8, yy1+2), (x2, yy2-4), (x1, yy2)]
        draw.polygon(poly, fill=fill, outline=colors["ink"])
        draw.rectangle((x1, yy1, x1+7, yy2), fill=edge)

        # Always a true circle: diameter is derived from row height, then a square
        # box is centered vertically.  No stretched ellipse.
        preferred_badge = int(rcfg.get("terminal_badge_size", 30) or 30) if terminal else 28
        badge_d = max(20, min(preferred_badge, row_h-8))
        badge_x1 = x1 + 13
        badge_y1 = yy1 + max(2, (row_h-badge_d)//2)
        badge = (badge_x1, badge_y1, badge_x1+badge_d, badge_y1+badge_d)

        badge_fill = colors["ink"] if fill != colors["ink"] else colors["accent"]
        draw.ellipse(badge, fill=badge_fill, outline=colors["ink"], width=2)
        s.draw_center(
            draw, badge, str(i+1), colors["paper"],
            max_size=min(12, max(9, badge_d//2)),
            min_size=8, bold=True, max_lines=1
        )

        cleaned = step
        import re
        cleaned = re.sub(
            r"^(?:[1-9][\.、\)）:]|[①②③④⑤⑥⑦⑧⑨⑩])\s*",
            "", cleaned
        ).strip()

        text_x1 = badge[2] + 9
        s.draw_left(
            draw, (text_x1, yy1+4, x2-12, yy2-4),
            cleaned, txt,
            max_size=max_font, min_size=min_font, bold=True,
            max_lines=2 if terminal else 2,
            line_gap=int(rcfg.get("day_action_line_gap", 3) or 3),
            valign="center"
        )

def _draw_action_bubble_or_strips(draw, s, box, action, colors, rcfg, idx, terminal=False):
    steps = _split_action_steps(action)
    # Multi-step instructions work better as manga command beats than a giant white bubble.
    if len(steps) >= 3 or (terminal and len(steps) >= 2):
        _draw_command_strips(draw, s, box, steps, colors, rcfg, terminal=terminal)
        return
    _action_dialog_balloon(draw, s, box, action, colors["ink"], colors["balloon"],
                    max_size=int(rcfg.get("day_action_font_size", 19) or 19) + (1 if terminal else 0),
                    min_size=int(rcfg.get("day_action_min_font_size", 12) or 12),
                    tail="left" if idx%2==0 else "right", bold=True,
                    line_gap=int(rcfg.get("day_action_line_gap", 3) or 3))


def _draw_day_panel(base, draw, guide, info, idx, s, colors, rcfg, box, rng, mode="speed", terminal=False, lead=False):
    x1, y1, x2, y2 = map(int, box)
    special = _special(info)
    pw, ph = x2-x1, y2-y1
    skew = 18 if lead else (12 if terminal else 14)
    poly = _panel_poly(box, skew, flip=bool(idx % 2))
    page_style = str(rcfg.get("page_style") or "shonen").lower().strip()
    if page_style == "vintage_print":
        palette = rcfg.get("vintage_day_palette") or [
            "#E1D09C", "#E5C87F", "#E2C16F",
            "#DFBC6A", "#57624B", "#53634E", "#765B6B"
        ]
        if isinstance(palette, (list, tuple)) and palette:
            fill = str(palette[min(idx, len(palette)-1)])
        else:
            fill = colors["day_scene"]
        if special:
            fill = str(rcfg.get("vintage_special_fill") or "#765B6B")
    else:
        fill = colors["day_fill_special"] if special else colors["day_scene"]
    draw.polygon(poly, fill=fill)

    if special:
        _pattern_mask(base, poly, lambda pd: _speedlines(
            pd, (x1, y1, x2, y2),
            (int(x1+(x2-x1)*.62), int(y1+(y2-y1)*.48)),
            colors["accent"], rng, count=50, alpha=(22, 52)
        ))
        _halftone(draw, (x1+8, y1+8, min(x2, x1+150), y2-8),
                  colors["accent"], step=9, radius=1, alpha=42)
    elif mode == "tone":
        _pattern_mask(base, poly, lambda pd: _halftone(
            pd, (x1, y1, x2, y2), colors["tone"],
            step=10, radius=1, alpha=55, offset=idx
        ))
    else:
        _pattern_mask(base, poly, lambda pd: _speedlines(
            pd, (x1, y1, x2, y2),
            (int(x1+(x2-x1)*.72), int(y1+(y2-y1)*.52)),
            colors["tone"], rng,
            count=36 if lead else 26, alpha=(24, 56)
        ))
    _ink_poly(draw, poly, colors["ink"], rng, width=7 if terminal else (6 if lead else 5))

    if page_style == "detective_red":
        # Evidence number in each Day panel.
        ex = x2 - 58
        ey = y2 - 58
        draw.ellipse(
            (ex-19, ey-19, ex+19, ey+19),
            fill=colors["paper"], outline=colors["accent"], width=4
        )
        s.draw_center(
            draw, (ex-16, ey-15, ex+16, ey+15),
            f"E{idx+1}", colors["accent"],
            max_size=11, min_size=8, bold=True, max_lines=1
        )
        draw.line(
            (x1+10, y2-12, x1+54, y2-12),
            fill=colors["accent"], width=4
        )
        draw.line(
            (x1+10, y2-12, x1+10, y2-46),
            fill=colors["accent"], width=4
        )

    # ---- 1. Editorial header first: Day typography and target NEVER move for a character.
    label = _day_label(info, idx)
    day_color = colors["accent"] if special else colors["ink"]
    fsize = 84 if terminal else (70 if lead else (60 if pw > 500 else 50))
    _paste_rotated_text(base, (x1+8, y1+14), label, s, fsize, day_color,
                        -8 if idx%2==0 else 6, True, 2, colors["paper"], 242)

    effect_words = ["START!", "GO!", "CHECK!", "PUSH!", "SAVE!", "MOVE!", "FINAL!!"]
    _paste_rotated_text(base, (x1+18, y1+92), effect_words[min(idx, 6)], s,
                        17 if not terminal else 27, colors["muted"],
                        8 if idx%2==0 else -8, True, 1, colors["paper"], 145)

    target = s.clean(str(info.get("target") or ""))
    if target:
        reserve = 150 if special else 18
        cap_w = min(320 if not terminal else 390, max(150, pw-150-reserve//2))
        tx2 = x2-reserve
        tx1 = max(x1+112, tx2-cap_w)
        _caption(draw, s, (tx1, y1+14, tx2, y1+50),
                 "本格目标  " + target,
                 colors["ink"], colors["paper"],
                 colors["accent"] if special else None,
                 True, max_size=13 if not terminal else 14)

    if special:
        pts = _burst_polygon(x2-69, y1+36, 61, 30, 12, rng, inner=(.54, .76))
        draw.polygon(pts, fill=colors["accent"], outline=colors["ink"])
        s.draw_center(draw, (x2-129, y1+13, x2-12, y1+59), "重点回!",
                      colors["paper"], max_size=15, min_size=10,
                      bold=True, max_lines=1)

    # ---- 2. Action box layout, still without considering any character.
    action = s.clean(str(info.get("action") or "")) or "按计划执行"
    steps = _split_action_steps(action)
    chars = len(action.replace("\n", ""))
    has_metrics = bool(info.get("metric_items"))

    # D1-D6 keep the generous header safety band that fixed Day-title collisions.
    # D7 is different: its large D7/FINAL typography lives in the LEFT illustration
    # column, so the RIGHT command list can start just below the target caption.
    if terminal:
        header_h = max(62, int(rcfg.get("terminal_action_top", 72) or 72))
    else:
        header_h = 104 if lead else 96
    by1 = y1 + header_h
    by2 = y2 - (52 if has_metrics else 18)

    if terminal:
        # V35.65: D7 returns to the preferred "illustration column + command list"
        # composition. The left column is deliberately wide enough for a real
        # character splash, while all numbered steps and metrics stay on the right.
        terminal_gutter = int(rcfg.get("terminal_illustration_width", 270) or 270)
        terminal_gutter = max(235, min(int(pw * 0.34), terminal_gutter))
        bx1, bx2 = x1 + terminal_gutter, x2 - 20
        open_side = "left"
    else:
        usable_x1, usable_x2 = x1+18, x2-18
        usable_w = usable_x2-usable_x1

        # Short instructions deliberately leave a manga illustration gutter.
        # Dense instructions expand first; character art is allowed only if
        # something is genuinely left after this calculation.
        complexity = min(1.0, max(0.0, (chars-22)/58.0 + max(0, len(steps)-2)*0.16))
        frac = 0.66 + 0.24*complexity
        if pw < 370:
            frac = max(frac, 0.75)
        if lead:
            frac = max(frac, 0.72)
        if len(steps) >= 3:
            frac = max(frac, 0.84)
        frac = min(0.94, frac)

        bw = int(usable_w * frac)
        bw = max(min(usable_w, 190), min(usable_w, bw))

        # Fixed editorial alternation, not character-driven placement.
        open_side = "left" if idx in (0, 2, 5) else "right"
        if open_side == "left":
            bx2 = usable_x2
            bx1 = bx2-bw
        else:
            bx1 = usable_x1
            bx2 = bx1+bw

    # Defensive minimum height. If a very short panel cannot hold both header and
    # action region, shrink only the header reserve slightly—never overlap Day text.
    if by2-by1 < 88:
        by1 = min(by1, y1+84)
    _draw_action_bubble_or_strips(
        draw, s, (bx1, by1, bx2, by2),
        action, colors, rcfg, idx, terminal=terminal
    )

    # ---- 3. Metrics follow the action box horizontally, preserving the same gutter.
    metric_box = None
    if has_metrics:
        tools = SharedRendererTools(s)
        mx1, mx2 = bx1, bx2
        if mx2-mx1 < 110:
            mx1, mx2 = x1+18, x2-18
        # Remaining / expected now use compact manga slashes: icon + value in
        # individual parallelograms.  No oversized full-width black bar.
        metric_box = (mx1, y2-46, mx2, y2-8)
        _draw_metric_values_comic(
            base, draw, guide, info, s, colors, metric_box
        )

    # ---- 4. Only now look at the whitespace and insert optional decoration.
    gap = int(rcfg.get("character_content_gap", 10) or 10)
    free = None
    if open_side == "left":
        fx1 = x1+8
        fx2 = bx1-gap
        free = (fx1, by1+2, fx2, y2-5)
    else:
        fx1 = bx2+gap
        fx2 = x2-8
        free = (fx1, by1+2, fx2, y2-5)

    character_placement = _paste_character_in_free_space(
        base, guide, s, colors, rcfg, box, free, info, idx,
        side=open_side, terminal=terminal
    )
    return character_placement

def _draw_metric_values_comic(base, draw, guide, info, s, colors, box):
    """One connected manga status ribbon: four icon/value cells, shared edges."""
    items = list(info.get("metric_items") or [])[:4]
    if not items:
        return
    x1,y1,x2,y2=map(int,box)
    n=len(items)
    w=max(1,x2-x1); h=max(1,y2-y1)
    skew=max(10,min(18,int(w*0.035)))

    # One continuous parallelogram band.  Internal diagonal rules create four
    # connected cells instead of four floating black chips.
    outer=[(x1+skew,y1),(x2,y1),(x2-skew,y2),(x1,y2)]
    draw.polygon([(x+3,y+3) for x,y in outer],fill=_rgba(colors["ink"],38))
    draw.polygon(outer,fill=colors["ink"],outline=colors.get("accent",colors["ink"]))

    top_left=x1+skew; top_right=x2
    bot_left=x1; bot_right=x2-skew
    cfg=guide.get("cfg") or {}
    for k in range(1,n):
        t=k/float(n)
        xt=int(round(top_left+(top_right-top_left)*t))
        xb=int(round(bot_left+(bot_right-bot_left)*t))
        draw.line((xt,y1+2,xb,y2-2),fill=_rgba(colors.get("accent",colors["paper"]),210),width=2)

    for i,item in enumerate(items):
        t0=i/float(n); t1=(i+1)/float(n)
        tl=top_left+(top_right-top_left)*t0; tr=top_left+(top_right-top_left)*t1
        bl=bot_left+(bot_right-bot_left)*t0; br=bot_left+(bot_right-bot_left)*t1
        a=int(max(tl,bl)+5); b=int(min(tr,br)-5)
        if b<=a+12:
            a=int(min(tl,bl)+3); b=int(max(tr,br)-3)
        icon=s.config_day_icon(cfg,item)
        icon_size=max(16,min(22,h-8))
        value=s.clean(str(item.get("value") or "—"))
        # Center icon+number as a compact pair inside each shared cell.
        value_font=_font(s,15,True)
        vb=draw.textbbox((0,0),value,font=value_font)
        vw=max(1,vb[2]-vb[0])
        pair_w=vw + (icon_size+5 if icon and Path(icon).exists() else 0)
        px=max(a, int((a+b-pair_w)/2))
        if icon and Path(icon).exists():
            iy=int(y1+(h-icon_size)/2)
            s.draw_image_contain(base,Path(icon),(px,iy,px+icon_size,iy+icon_size))
            tx=px+icon_size+5
        else:
            tx=px
        s.draw_left(draw,(tx,y1+1,b,y2-1),value,colors["paper"],
                    max_size=15,min_size=11,bold=True,max_lines=1,line_gap=0,valign="center")

def _draw_risk(base, draw, guide, s, tools, colors, rcfg, box, rng):
    x1, y1, x2, y2 = map(int, box); cx=(x1+x2)//2; cy=(y1+y2)//2
    # A real comic explosion palette: dark orange outer blast + yellow inner flash.
    outer = colors.get("explosion_outer", "#D95827")
    inner = colors.get("explosion_inner", "#F3C84B")
    hot = colors.get("explosion_hot", "#E9822D")
    pts = _burst_polygon(cx, cy, (x2-x1)//2, (y2-y1)//2, 22, rng, inner=(.50, .74))
    draw.polygon([(x+6, y+7) for x,y in pts], fill=_rgba(colors["ink"], 48))
    draw.polygon(pts, fill=outer, outline=colors["ink"])
    inner_pts = _burst_polygon(cx, cy+4, int((x2-x1)*.39), int((y2-y1)*.34), 18, rng, inner=(.61, .82))
    draw.polygon(inner_pts, fill=inner, outline=hot)
    _speedlines(draw, (x1+35, y1+24, x2-35, y2-24), (cx, cy), colors["ink"], rng, count=22, alpha=(18, 34))

    risks = tools.risk_items(guide)
    body = "\n".join("●  "+x for x in risks[:4]) if risks else "●  到达目标档位后停止\n●  不要为随机奖励过度追高"
    _speech_balloon(draw, s, (x1+165, y1+78, x2-115, y2-38), body, colors["ink"], colors["paper"],
                    max_size=int(rcfg.get("risk_font_size", 19) or 19), min_size=15, tail="bottom", bold=True, line_gap=5)

    # Draw WARNING last as an impact burst / sound-effect title, never a UI pill.
    warning = str(rcfg.get("warning_text") or "WARNING!!")
    wcx, wcy = x1+178, y1+47
    wburst = _burst_polygon(wcx, wcy, 142, 48, 15, rng, inner=(.42, .68))
    draw.polygon([(x+4, y+5) for x,y in wburst], fill=_rgba(colors["ink"], 62))
    draw.polygon(wburst, fill=hot, outline=colors["ink"])
    inner_burst = _burst_polygon(wcx, wcy, 116, 37, 13, rng, inner=(.60, .78))
    draw.polygon(inner_burst, fill=inner, outline=outer)
    # A tiny offset duplicate mimics rough comic printing.
    _paste_rotated_text(base, (x1+72, y1+17), warning, s,
                        int(rcfg.get("warning_font_size", 29) or 29), colors["ink"], -4,
                        True, 2, colors["paper"], 255)



def _draw_magnifier(draw, center, radius, colors, width=7, alpha=255, angle=38):
    """Programmatic detective magnifying-glass motif."""
    cx, cy = map(int, center)
    r = int(radius)
    ink = _rgba(colors["ink"], alpha)
    accent = _rgba(colors.get("accent", colors["ink"]), alpha)
    draw.ellipse((cx-r, cy-r, cx+r, cy+r), outline=ink, width=max(2, int(width)))
    draw.arc(
        (cx-r+8, cy-r+8, cx+r-8, cy+r-8),
        205, 330, fill=accent, width=max(2, int(width//2))
    )
    a = math.radians(angle)
    hx1 = cx + math.cos(a)*r*0.78
    hy1 = cy + math.sin(a)*r*0.78
    hx2 = cx + math.cos(a)*r*1.85
    hy2 = cy + math.sin(a)*r*1.85
    draw.line((hx1, hy1, hx2, hy2), fill=ink, width=max(4, int(width*1.25)))
    cap = max(3, int(width//2))
    draw.ellipse((hx2-cap, hy2-cap, hx2+cap, hy2+cap), fill=ink)


def _draw_culprit_magnifier(draw, box, colors, width=10, angle=42):
    """Oversized culprit lens with an unmistakable thick handle.

    The old version used a near-full-character circle with a thin handle that
    often started outside the visible panel, so it still read as a red ring.
    This version slightly reduces and offsets the lens, then keeps a chunky
    double-stroked handle close to the silhouette.
    """
    x1, y1, x2, y2 = map(int, box)
    bw=max(1,x2-x1); bh=max(1,y2-y1)
    cx=int((x1+x2)/2 - bw*0.045)
    cy=int((y1+y2)/2 - bh*0.045)
    r=max(30, int(min(max(bw,bh)*0.48, min(bw,bh)*0.72)))
    accent=colors.get("accent", "#B51F24")
    dark=colors.get("ink", accent)
    paper=colors.get("paper", "#FFFFFF")
    w=max(7,int(width))

    # Double lens rim: strong dark-red outer edge + brighter inner edge.
    draw.ellipse((cx-r,cy-r,cx+r,cy+r), outline=dark, width=w+4)
    draw.ellipse((cx-r+5,cy-r+5,cx+r-5,cy+r-5), outline=accent, width=max(4,w))

    a=math.radians(angle)
    # Start the handle inside the rim so the joint is visible, and stop before it
    # can disappear far outside the panel.
    hx1=cx+math.cos(a)*r*0.76
    hy1=cy+math.sin(a)*r*0.76
    handle_len=max(42,int(r*0.92))
    hx2=hx1+math.cos(a)*handle_len
    hy2=hy1+math.sin(a)*handle_len
    # Thick outer grip + inner accent makes it read as a real magnifier handle.
    draw.line((hx1,hy1,hx2,hy2), fill=dark, width=w+10)
    draw.line((hx1,hy1,hx2,hy2), fill=accent, width=w+4)
    joint=max(7,(w+8)//2)
    draw.ellipse((hx1-joint,hy1-joint,hx1+joint,hy1+joint), fill=accent, outline=dark, width=3)
    cap=max(8,(w+10)//2)
    draw.ellipse((hx2-cap,hy2-cap,hx2+cap,hy2+cap), fill=accent, outline=dark, width=3)

    # Small white lens glints reinforce the object as glass rather than a circle.
    glint_w=max(3,w//3)
    draw.arc((cx-r+13,cy-r+13,cx+r-13,cy+r-13), 205, 252, fill=paper, width=glint_w)
    draw.arc((cx-r+19,cy-r+19,cx+r-19,cy+r-19), 258, 282, fill=paper, width=max(2,glint_w-1))


def _draw_old_paper_distress(draw, W, H, colors, rng):
    """Old serialized-manga paper: stains, edge foxing and hairline cracks."""
    stain = colors.get("paper_stain", "#A97F3F")
    crack = colors.get("paper_crack", colors.get("ink_mid", "#4A3E30"))

    for _ in range(30):
        side = rng.choice(("l", "r", "t", "b", "any"))
        if side == "l":
            x, y = rng.randint(-18, 55), rng.randint(0, H)
        elif side == "r":
            x, y = rng.randint(W-55, W+18), rng.randint(0, H)
        elif side == "t":
            x, y = rng.randint(0, W), rng.randint(-18, 65)
        elif side == "b":
            x, y = rng.randint(0, W), rng.randint(H-65, H+18)
        else:
            x, y = rng.randint(0, W), rng.randint(0, H)
        rx = rng.randint(10, 44)
        ry = rng.randint(5, 24)
        draw.ellipse(
            (x-rx, y-ry, x+rx, y+ry),
            fill=_rgba(stain, rng.randint(7, 18))
        )

    for _ in range(19):
        x = rng.randint(0, W)
        y = rng.randint(0, H)
        pts = [(x, y)]
        direction = rng.choice((-1, 1))
        for _seg in range(rng.randint(2, 5)):
            x += direction*rng.randint(15, 42)
            y += rng.randint(-14, 14)
            pts.append((x, y))
        draw.line(pts, fill=_rgba(crack, rng.randint(12, 25)), width=1)


def _draw_detective_suspect_overlay(
    base, draw, guide, s, colors, rcfg, placements
):
    """Turn the actually rendered character set into a detective suspect roster.

    V35.69 rules:
    1. Suspect A/B/C/... follows *visible-character order*, not Day number.
       If D1 has no character and D2 is the first visible one, D2 is 嫌疑人A.
    2. The culprit is stably randomised from the same visible roster, so it may
       occur on any Day that actually contains a rendered character.
    3. The selected culprit artwork is replaced in-place by a pure black
       silhouette before the red hand-drawn circle / 真凶 stamp is added.
    """
    if not placements:
        return

    # Page order only; missing Day characters are naturally skipped.
    visible = [
        idx for idx in sorted(int(k) for k in placements.keys())
        if placements.get(idx) and placements.get(idx).get("box")
    ]
    if not visible:
        return

    # Optional override remains useful for debugging, but the default is random
    # among actual visible characters.
    forced = rcfg.get("detective_culprit_day")
    culprit_day = None
    if forced not in (None, ""):
        try:
            candidate = int(str(forced).upper().replace("D", "")) - 1
            if candidate in visible:
                culprit_day = candidate
        except Exception:
            culprit_day = None

    if culprit_day is None:
        seed = "|".join([
            str(_char_cfg(rcfg, "character_random_seed", None, "") or ""),
            str((guide or {}).get("sheet") or ""),
            str((guide or {}).get("title") or ""),
            str(
                _char_cfg(
                    rcfg, "character_variant_key", None, "detective_red"
                ) or "detective_red"
            ),
            "visible_suspect_culprit_v2",
            ",".join(str(x) for x in visible),
        ])
        culprit_day = random.Random(seed).choice(visible)

    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    suspect_prefix = str(
        rcfg.get("detective_suspect_text") or "嫌疑人"
    )
    culprit_text = str(
        rcfg.get("detective_culprit_text") or "真凶"
    )
    silhouette_color = _rgba(
        rcfg.get("detective_culprit_silhouette_color") or "#050505",
        255
    )

    # rank is based on actual visible character count, not Day index.
    for rank, day_idx in enumerate(visible):
        placement = placements.get(day_idx) or {}
        box = placement.get("box")
        if not box:
            continue

        x1, y1, x2, y2 = map(int, box)
        cx = (x1+x2)//2
        is_culprit = day_idx == culprit_day

        suspect_id = (
            alphabet[rank]
            if rank < len(alphabet)
            else str(rank + 1)
        )
        label = f"{suspect_prefix}{suspect_id}"

        # True culprit reveal: replace the character with a 100% opaque,
        # binary black silhouette.  Do NOT reuse semi-transparent sprite alpha
        # as the source alpha and mask at the same time (that would let clothing
        # details show through).
        if is_culprit:
            rendered_im = placement.get("image")
            if rendered_im is not None:
                try:
                    from PIL import ImageFilter

                    source_alpha = rendered_im.getchannel("A")
                    threshold = max(
                        1,
                        min(
                            254,
                            int(
                                rcfg.get(
                                    "detective_culprit_alpha_threshold", 12
                                ) or 12
                            )
                        )
                    )
                    hard_alpha = source_alpha.point(
                        lambda v: 255 if v >= threshold else 0
                    )

                    # Slightly expand the silhouette to cover any anti-aliased
                    # remnants of the original character edge.
                    expand = max(
                        0,
                        min(
                            4,
                            int(
                                rcfg.get(
                                    "detective_culprit_silhouette_expand", 1
                                ) or 0
                            )
                        )
                    )
                    if expand > 0:
                        hard_alpha = hard_alpha.filter(
                            ImageFilter.MaxFilter(expand * 2 + 1)
                        )

                    # Opaque RGB/RGBA source + binary mask => one alpha operation.
                    # Interior pixels become absolute black, never translucent.
                    opaque_black = Image.new(
                        "RGBA",
                        rendered_im.size,
                        (
                            silhouette_color[0],
                            silhouette_color[1],
                            silhouette_color[2],
                            255,
                        ),
                    )
                    # paste() safely clips characters that break outside the panel.
                    base.paste(opaque_black, (x1, y1), hard_alpha)
                except Exception:
                    pass

            # Put the white question mark at the visual centre of the culprit
            # silhouette, not above the head.  It now reads as an identity mask.
            qw=max(46,int((x2-x1)*0.62)); qh=max(54,int((y2-y1)*0.54))
            qbox=(cx-qw//2, (y1+y2)//2-qh//2, cx+qw//2, (y1+y2)//2+qh//2)
            s.draw_center(
                draw,qbox,"?",colors["paper"],
                max_size=max(34,min(68,int((y2-y1)*0.38))),
                min_size=26,bold=True,max_lines=1
            )

        # Compact suspect tag based on the actual roster.
        tag_w = max(62, min(94, x2-x1+14))
        tag_h = 22
        tx1 = max(4, cx-tag_w//2)
        tx2 = tx1+tag_w
        ty1 = max(4, y1-24)
        ty2 = ty1+tag_h

        if is_culprit:
            # Use an unmistakable magnifying glass rather than a near-full red
            # circle.  The lens is slightly smaller/offset and the handle is much
            # thicker, shorter and kept close to the character.
            _draw_culprit_magnifier(
                draw, (x1, y1, x2, y2), colors,
                width=max(8,int(rcfg.get("detective_culprit_magnifier_width",10) or 10)),
                angle=int(rcfg.get("detective_culprit_magnifier_angle",42) or 42)
            )

            # Red 真凶 stamp.
            stamp_w = max(
                58,
                int(rcfg.get("detective_culprit_stamp_width", 62) or 62)
            )
            stamp_h = 30
            sx1 = max(4, min(x2-stamp_w, cx-stamp_w//2))
            sy1 = max(4, y1-59)
            draw.rectangle(
                (sx1, sy1, sx1+stamp_w, sy1+stamp_h),
                fill=colors["paper"],
                outline=colors["accent"],
                width=4
            )
            s.draw_center(
                draw,
                (sx1+3, sy1+2, sx1+stamp_w-3, sy1+stamp_h-2),
                culprit_text,
                colors["accent"],
                max_size=14, min_size=10,
                bold=True, max_lines=1
            )

            # Editorial evidence line pointing directly at the silhouette.
            draw.line(
                (sx1+stamp_w, sy1+stamp_h//2, x1+8, y1+8),
                fill=colors["accent"], width=3
            )

        # Even the culprit retains its suspect roster identity (e.g. 嫌疑人C),
        # while the separate red 真凶 mark reveals the solution.
        tag_fill = colors["accent"] if is_culprit else colors["ink"]
        draw.rectangle(
            (tx1, ty1, tx2, ty2),
            fill=tag_fill,
            outline=colors["paper"],
            width=2
        )
        s.draw_center(
            draw,
            (tx1+2, ty1+1, tx2-2, ty2-1),
            label,
            colors["paper"],
            max_size=10, min_size=8,
            bold=True, max_lines=1
        )


def _group_text(guide):
    cfg = guide.get("cfg") or {}
    return str(guide.get("watermark") or cfg.get("watermark") or "欢迎加入冒险者日记萌新交流群")


def _draw_footer(base, draw, guide, s, colors, rcfg, box):
    """Compact manga editorial footer: 次回预告 + group info."""
    x1, y1, x2, y2 = map(int, box)
    h = max(48, y2-y1)

    draw.rounded_rectangle(
        (x1, y1, x2, y2),
        radius=18, fill=colors["balloon"], outline=colors["ink"], width=3
    )

    # Small manga speech-tail notch.
    tail_x = x1 + 120
    draw.polygon(
        [(tail_x, y2-2), (tail_x+20, y2+10), (tail_x+34, y2-2)],
        fill=colors["balloon"], outline=colors["ink"]
    )

    tag_w = max(82, int(rcfg.get("footer_preview_tag_width", 92) or 92))
    draw.rectangle(
        (x1+10, y1+10, x1+10+tag_w, y2-10),
        fill=colors["ink"]
    )
    s.draw_center(
        draw, (x1+14, y1+12, x1+6+tag_w, y2-12),
        str(rcfg.get("footer_preview_text") or "次回预告"),
        colors["paper"],
        max_size=13, min_size=10, bold=True, max_lines=1
    )

    text = _group_text(guide)
    cfg = guide.get("cfg") or {}
    raw_icon = rcfg.get("group_avatar") or cfg.get("watermark_group_icon")
    icon_path = s.resolve_path(cfg, raw_icon) if raw_icon else None

    try:
        icon_size = max(
            24, int(rcfg.get("footer_group_icon_size", 32) or 32)
        )
    except Exception:
        icon_size = 32
    icon_size = min(icon_size, max(24, h-22))
    has_icon = bool(icon_path and Path(icon_path).exists())
    gap = 10 if has_icon else 0

    content_x1 = x1 + 10 + tag_w + 18
    content_x2 = x2 - 18
    max_text_w = max(
        120,
        content_x2-content_x1-(icon_size+gap if has_icon else 0)
    )

    # Group information is real guide content, not a tiny manga folio note.
    # Give it two lines at a protected minimum instead of silently shrinking
    # to 11px when the QQ sentence is long.
    sx = content_x1
    cy = (y1+y2)//2
    if has_icon:
        iy = int(cy-icon_size/2)
        draw.rectangle(
            (int(sx)-2, iy-2, int(sx)+icon_size+2, iy+icon_size+2),
            fill=colors["paper"], outline=colors["ink"], width=2
        )
        s.draw_image_contain(
            base, Path(icon_path),
            (int(sx), iy, int(sx)+icon_size, iy+icon_size)
        )
        sx += icon_size + gap

    s.draw_left(
        draw, (int(sx), y1+8, content_x2, y2-8),
        text, colors["ink"],
        max_size=int(rcfg.get("footer_font_size", 18) or 18),
        min_size=int(rcfg.get("footer_min_font_size", 15) or 15),
        bold=True, max_lines=2, line_gap=2, valign="center"
    )

def render(guide, out_path: Path, services):
    started = time.perf_counter(); W, H = services.W, services.H
    tools = SharedRendererTools(services)
    c = tools.colors(guide, {
        "background":"#E8E6E0", "paper":"#FFFDF8", "ink":"#171717", "ink_mid":"#343434", "muted":"#74716B",
        "accent":"#B33431", "accent2":"#E7B83D", "panel_fill":"#F6F2E7", "panel_fill_alt":"#F3F3EF", "cell_fill":"#FFFBF1",
        "rule":"#99958D", "tone":"#66635D", "day_scene":"#EDEBE5", "day_fill_special":"#F6E7E3", "panel_dark":"#3A3936",
        "risk_fill":"#FFF5D9", "balloon":"#FFFDF8"
    })
    rcfg = (guide.get("theme_config") or {}).get("renderer") or {}
    selection_mode = str(_char_cfg(rcfg, "character_selection_mode", None, "random_stable") or "random_stable").lower().strip()
    if selection_mode in ("random_each_render", "random_each", "random_live") and isinstance(guide, dict):
        guide["_comic_character_render_nonce"] = time.time_ns()
        guide.pop("_comic_character_assignment_cache", None)
    rng = random.Random("comic3:" + str(guide.get("sheet") or guide.get("title") or "guide"))
    img = Image.new("RGBA", (W, H), c["background"]); d = ImageDraw.Draw(img, "RGBA")

    page_style = str(rcfg.get("page_style") or "shonen").lower().strip()

    # Page texture changes structurally by variant.
    if page_style == "vintage_print":
        # Warm aged manga stock matching the supplied reference.
        for y in range(0, H, 14):
            d.line((0, y, W, y), fill=_rgba(c["tone"], 7), width=1)
        for _ in range(360):
            x = rng.randint(0, W-1)
            y = rng.randint(0, H-1)
            rr = rng.choice((1, 1, 1, 1, 2))
            d.ellipse(
                (x-rr, y-rr, x+rr, y+rr),
                fill=_rgba(c["ink"], rng.randint(5, 15))
            )
        _draw_old_paper_distress(
            d, W, H,
            {
                **c,
                "paper_stain": str(rcfg.get("vintage_stain") or "#A87934"),
                "paper_crack": str(rcfg.get("vintage_crack") or "#64452D"),
            },
            rng
        )

    elif page_style == "detective_red":
        # High-contrast crime manga: black hatch + red evidence-string traces.
        for yy in range(-H, H*2, 28):
            d.line((0, yy, W, yy+W), fill=_rgba(c["ink"], 8), width=1)
        for yy in range(0, H, 18):
            for xx in range((yy//18)%2*9, W, 18):
                d.ellipse(
                    (xx, yy, xx+1, yy+1),
                    fill=_rgba(c["ink"], 26)
                )
        for _ in range(10):
            xa = rng.choice((rng.randint(0, 130), rng.randint(W-130, W)))
            ya = rng.randint(190, H-160)
            xb = rng.choice((rng.randint(0, 180), rng.randint(W-180, W)))
            yb = rng.randint(190, H-160)
            d.line(
                (xa, ya, xb, yb),
                fill=_rgba(c["accent"], 25), width=2
            )
            d.ellipse(
                (xa-4, ya-4, xa+4, ya+4),
                fill=_rgba(c["accent"], 70)
            )

    else:
        for y in range(0, H, 22):
            for x in range((y//22)%2*11, W, 22):
                d.ellipse(
                    (x, y, x+1, y+1),
                    fill=_rgba(c["tone"], 23)
                )
        for _ in range(18):
            x = rng.randint(0, W-1)
            y = rng.randint(0, H-1)
            ln = rng.randint(14, 52)
            d.line(
                (x, y, min(W-1, x+ln), y+rng.choice((-1,0,1))),
                fill=_rgba(c["tone"], 14), width=1
            )

    title = guide.get("title") or "活动攻略"

    if page_style == "vintage_print":
        # Reference-like old manga masthead on aged stock.
        d.rectangle((0, 0, W, 16), fill=c["ink"])
        d.polygon([(0, 20), (315, 20), (272, 188), (0, 188)], fill=c["ink"])
        d.text(
            (36, 34), "STRATEGY",
            font=_font(services, 14, True), fill=c["accent2"]
        )
        d.text(
            (36, 60), "MANGA",
            font=_font(services, 31, True), fill=c["paper"]
        )
        d.text(
            (38, 111), "第 01 话",
            font=_font(services, 16, True), fill=c["paper"]
        )
        d.text(
            (38, 143), "复古连载版",
            font=_font(services, 11, True), fill=_rgba(c["paper"], 190)
        )
        services.draw_left(
            d, (300, 42, W-72, 140), title, c["ink"],
            max_size=int(rcfg.get("title_font_size", 41) or 41),
            min_size=27, bold=True, max_lines=2,
            line_gap=0, valign="center"
        )
        d.line((300, 153, W-62, 153), fill=c["ink"], width=6)
        d.line((300, 164, W-218, 164), fill=c["accent"], width=3)
        _paste_rotated_text(
            img, (W-196, 36), "攻略!!", services, 34,
            c["accent"], 7, True, 2, c["paper"], 245
        )
        d.text(
            (W-228, 176), "OLD PRINT / SERIAL 01",
            font=_font(services, 9, True), fill=c["muted"]
        )

    elif page_style == "detective_red":
        # Black / red / white detective case-board masthead.
        d.rectangle((0, 0, W, 18), fill=c["ink"])
        d.rectangle(
            (24, 28, W-24, 176),
            fill=c["paper"], outline=c["ink"], width=6
        )
        d.polygon(
            [(24, 28), (286, 28), (248, 176), (24, 176)],
            fill=c["ink"]
        )
        d.rectangle((44, 45, 194, 76), fill=c["accent"])
        d.text(
            (55, 51), "CASE FILE 01",
            font=_font(services, 14, True), fill=c["paper"]
        )
        d.text(
            (44, 94), "攻略事件簿",
            font=_font(services, 24, True), fill=c["paper"]
        )
        services.draw_left(
            d, (294, 40, W-190, 132), title, c["ink"],
            max_size=34, min_size=23, bold=True,
            max_lines=2, line_gap=0, valign="center"
        )
        d.line((294, 145, W-62, 145), fill=c["ink"], width=6)
        d.line((294, 158, W-250, 158), fill=c["accent"], width=5)
        _draw_magnifier(
            d, (W-118, 82), 42, c,
            width=8, alpha=255, angle=40
        )
        d.rectangle((W-244, 132, W-102, 166), fill=c["accent"])
        services.draw_center(
            d, (W-238, 135, W-108, 162),
            "CONFIDENTIAL", c["paper"],
            max_size=11, min_size=8, bold=True, max_lines=1
        )
        for px, py in ((318, 164), (W-284, 165)):
            d.ellipse(
                (px-6, py-6, px+6, py+6),
                fill=c["accent"], outline=c["ink"], width=2
            )
        d.line((324, 164, W-290, 165), fill=c["accent"], width=2)

    else:
        # Original Japanese shonen-style manga masthead.
        d.rectangle((0, 0, W, 16), fill=c["ink"])
        d.polygon([(0, 20), (315, 20), (272, 188), (0, 188)], fill=c["ink"])
        d.text((36, 35), "STRATEGY", font=_font(services, 15, True), fill=c["accent2"])
        d.text((36, 62), "MANGA", font=_font(services, 31, True), fill=c["paper"])
        d.text((38, 112), "第 01 话", font=_font(services, 17, True), fill=c["paper"])
        d.text((38, 144), "攻略特别篇", font=_font(services, 12, True), fill=_rgba(c["paper"], 190))
        services.draw_left(d, (300, 42, W-72, 140), title, c["ink"],
                           max_size=int(rcfg.get("title_font_size", 41) or 41),
                           min_size=27, bold=True, max_lines=2, line_gap=0,
                           valign="center")
        d.line((300, 153, W-62, 153), fill=c["ink"], width=6)
        d.line((300, 164, W-218, 164), fill=c["accent"], width=3)
        _paste_rotated_text(img, (W-196, 36), "攻略!!", services, 34,
                            c["accent"], 7, True, 2, c["paper"], 245)
        d.text((W-226, 176), "SPECIAL ISSUE / PAGE 01",
               font=_font(services, 9, True), fill=c["muted"])

    # Top editorial cut-ins: still informative, but visually subordinate to the manga page.
    _draw_kpi_cut_in(img, d, guide, services, c, rcfg, (44, 206, 512, 455), rng)
    _draw_reward_cut_in(img, d, guide, services, tools, c, rcfg, (548, 206, 1036, 455), rng)

    # D1-D6 panel area is now content-aware: short instructions stay compact,
    # long instructions get more width/height. Pairing and offsets preserve an
    # intentionally irregular manga rhythm instead of becoming a neat grid.
    days = list(guide.get("days") or [])[:7]
    dynamic = _dynamic_day_slots(
        days, top=485, d7_top=1510, left=44, right=1036,
        min_panel_width=int(rcfg.get("day_panel_min_width", 315) or 315)
    )
    slots = list(dynamic) + [((72, 1520, 1008, 1858), "impact", True)]
    character_placements = {}
    for i, info in enumerate(days):
        box, mode, lead = slots[i]
        placement = _draw_day_panel(
            img, d, guide, info, i, services, c, rcfg, box, rng, mode,
            terminal=(i == len(days)-1 and i >= 6), lead=lead
        )
        if placement:
            character_placements[i] = placement

    if page_style == "detective_red":
        _draw_detective_suspect_overlay(
            img, d, guide, services, c, rcfg, character_placements
        )

    for i in range(len(days), 7):
        x1,y1,x2,y2 = slots[i][0]
        poly = _panel_poly(slots[i][0], 14, bool(i%2)); d.polygon(poly, fill=_rgba(c["paper"], 75)); _ink_poly(d, poly, _rgba(c["rule"], 120), rng, 2)
        services.draw_center(d, (x1, y1, x2, y2), "TO BE CONTINUED", _rgba(c["muted"], 125), max_size=13, min_size=10, bold=True, max_lines=1)

    # Crisis panel: a full manga beat, not a footer alert card.
    _draw_risk(img, d, guide, services, tools, c, rcfg, (58, 1872, 1022, 2218), rng)
    _draw_footer(img, d, guide, services, c, rcfg, (66, 2232, 1014, 2318))

    # Crop marks / folio complete the printed-page language.
    for (x,y,sx,sy) in [(24,24,1,1),(W-24,24,-1,1),(24,H-24,1,-1),(W-24,H-24,-1,-1)]:
        d.line((x,y,x+sx*30,y), fill=c["ink"], width=2); d.line((x,y,x,y+sy*30), fill=c["ink"], width=2)
    d.text((W-122, H-36), "01 / 01", font=_font(services, 9, True), fill=c["muted"])

    tools.save(img, out_path, guide, started)

