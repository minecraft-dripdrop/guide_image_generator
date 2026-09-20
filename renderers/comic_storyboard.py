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
import re
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


def _prepare_character_image(guide, s, colors, rcfg, mapped, idx, mirror=False, special=False):
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

        # Legacy compatibility: highlighted days used to switch from monochrome
        # to colour.  The current comic direction keeps characters coloured on
        # *every* day, so special/ordinary state is expressed by panel treatment
        # and the 重点回 marker instead of by desaturating the cast.
        if special and bool(_char_cfg(rcfg, "special_character_auto_color", None, True)):
            special_mode = str(
                _char_cfg(rcfg, "special_character_render_mode", None, "color")
                or "color"
            ).lower().strip()
            if mode not in ("color", "original", "vintage_color", "retro_color", "old_print_color"):
                mode = special_mode

    # V35.7x visual rule: all comic variants keep character art in colour on
    # ordinary as well as special days.  Vintage keeps a faded/paper-aged colour
    # treatment; shonen and detective preserve the source colours.  This is
    # renderer-local so no shared parser/data meaning is changed, and a future
    # theme can opt out explicitly if it truly needs monochrome characters.
    if bool(_char_cfg(rcfg, "character_all_days_color", None, True)):
        page_style = str(rcfg.get("page_style") or "shonen").lower().strip()
        mode = "vintage_color" if page_style == "vintage_print" else "color"

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
    im = _prepare_character_image(
        guide, s, colors, rcfg, mapped, idx, mirror=mirror,
        special=_special(info or {})
    )
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
    im = _prepare_character_image(
        guide, s, colors, rcfg, mapped, idx, mirror=mirror,
        special=_special(info or {})
    )
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
    if terminal:
        # D7 is deliberately a two-column comic composition: the character is
        # the visual anchor of the left column, not a small leftover decoration.
        # Keep the configured value as a floor, then allow the art to grow with
        # the actual left-column width (within a conservative cap).
        terminal_max_w = min(300, max(terminal_max_w, int(effective_w * .90)))
    target_w = int(min(effective_w * .94, (terminal_max_w if terminal else 150)) * scale)
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

    # Ordinary days anchor the character to the inner edge of the free-space
    # gutter. D7 is different: its left column is a deliberate illustration
    # panel, so anchoring to the command boundary makes the figure drift right
    # and leaves a conspicuous empty strip under the Day label.  Anchor D7 to
    # the OUTER/left panel edge and to the TOP of its free box instead.  This
    # makes the composition read naturally as "D7 -> character" on the left
    # and numbered commands on the right.
    if terminal and side == "left":
        # D7 is a deliberate two-column panel now: center the hero inside the
        # left illustration column instead of pinning it to either the outer
        # frame or the command gutter.  This uses the available space and makes
        # the whole D7 composition feel centered rather than left-empty/right-heavy.
        xx = int(x1 + max(0, (fw - target_w) / 2))
        yy = int(y1 + max(0, (fh - target_h) / 2))
        xx = max(px1 - overflow, min(xx, x2 - target_w))
        yy = max(y1, min(yy, y2 - target_h + bottom_overflow))
    else:
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


def _warning_callout(draw, s, box, text, ink, paper, max_size=19, min_size=11, bold=True, line_gap=5):
    """Warning body as one continuous rectangle + triangular tail.

    Rectangle and triangle share one stroke width.  The outline is drawn as a
    single perimeter with the rectangle's bottom edge deliberately split around
    the tail attachment, so there is no doubled/internal seam at the overlap.
    """
    x1, y1, x2, y2 = map(int, box)
    stroke = 4

    # Tail attachment points live on the rectangle's bottom edge.
    a = (x2 - 112, y2)
    tip = (x2 - 66, y2 + 32)
    b = (x2 - 30, y2)

    # Unified shadow silhouette.
    ox, oy = 4, 5
    draw.rectangle((x1+ox, y1+oy, x2+ox, y2+oy), fill=_rgba(ink, 34))
    draw.polygon(((a[0]+ox,a[1]+oy),(tip[0]+ox,tip[1]+oy),(b[0]+ox,b[1]+oy)), fill=_rgba(ink, 34))

    # Fill the joined rectangle + tail first.
    draw.rectangle((x1, y1, x2, y2), fill=paper)
    draw.polygon((a, tip, b), fill=paper)

    # Draw one continuous outer perimeter.  Crucially, there is NO bottom line
    # from a -> b; that shared segment is replaced by the two triangle edges.
    draw.line((x1, y1, x2, y1), fill=ink, width=stroke)
    draw.line((x1, y1, x1, y2), fill=ink, width=stroke)
    draw.line((x2, y1, x2, y2), fill=ink, width=stroke)
    draw.line((x1, y2, a[0], y2), fill=ink, width=stroke)
    draw.line((a, tip, b), fill=ink, width=stroke, joint="curve")
    draw.line((b[0], y2, x2, y2), fill=ink, width=stroke)

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


def _ellipsize_single_line(draw, s, text, font, max_width):
    """Return one readable line that never paints outside its allotted cell."""
    text = s.clean(str(text or ""))
    if not text:
        return ""
    try:
        if draw.textlength(text, font=font) <= max_width:
            return text
    except Exception:
        bb = draw.textbbox((0, 0), text, font=font)
        if bb[2] - bb[0] <= max_width:
            return text
    ellipsis = "…"
    lo, hi = 0, len(text)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        candidate = text[:mid].rstrip() + ellipsis
        try:
            fits = draw.textlength(candidate, font=font) <= max_width
        except Exception:
            bb = draw.textbbox((0, 0), candidate, font=font)
            fits = (bb[2] - bb[0]) <= max_width
        if fits:
            lo = mid
        else:
            hi = mid - 1
    return (text[:lo].rstrip() + ellipsis) if lo > 0 else ellipsis


def _compact_budget_kpi_text(label, value):
    """Avoid repeating the diamond resource name beside an already-visible icon."""
    label = str(label or "")
    value = str(value or "")
    budgetish = "预算" in label
    if budgetish and "钻石" in label:
        label = label.replace("钻石", "").strip(" ·|｜/-_") or "预算"
    if budgetish and "钻石" in value:
        value = value.replace("钻石", "").strip()
    return label, value


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
        label, value = _compact_budget_kpi_text(label, value)
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
    """Comic loot strip using the shared reward artwork layer.

    Reward information follows the same vertical hierarchy used by the main
    manga loot panel: artwork first, then quantity, then item name.  Keeping
    quantity on its own line makes the count scan much faster than appending it
    to the name.
    """
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
        qty_h = 20
        name_h = 28
        icon_size = int(min(cell_w-8, y2-y1-qty_h-name_h-8, frame_size_cfg))
        icon_size = max(24, icon_size)
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

        qty = s.clean(str(item.get("qty") or "1")) or "1"
        qty_y1 = min(y2-name_h-qty_h, iy1+icon_size+1)
        s.draw_center(draw, (cx1+2, qty_y1, cx2-2, qty_y1+qty_h), "×"+qty, colors["ink"],
                      max_size=max(12, name_size), min_size=max(9, name_min), bold=True, max_lines=1)
        s.draw_center(draw, (cx1+1, qty_y1+qty_h-1, cx2-1, y2), s.clean(str(item.get("name") or "物品")), colors["ink"],
                      max_size=name_size, min_size=name_min, bold=True, max_lines=2, line_gap=0)


def _reward_leaf_count_comic(node):
    if not isinstance(node, dict):
        return 0
    typ = node.get("type", "item")
    if typ == "item":
        return 1
    children = node.get("items") if typ == "bundle" else node.get("options")
    return sum(_reward_leaf_count_comic(x) for x in (children or []))


def _reward_tree_comic(guide, s):
    raw = guide.get("reward_items") or []
    if not raw:
        return None
    units = s.build_reward_display_units(raw)
    if not units:
        return None
    if len(units) == 1:
        return units[0]
    # Separate display units remain additive, matching the parser's historical
    # A 或 B + C -> (A 或 B) + C convention.
    return {"type": "bundle", "items": units, "_visual_root": True}


def _reward_measure_comic(node, item_w, plus_w, choice_gap, nested=False):
    if not isinstance(node, dict):
        return 0.0
    typ = node.get("type", "item")
    if typ == "item":
        return float(item_w)
    if typ == "bundle":
        children = list(node.get("items") or [])
        if not children:
            return float(item_w)
        width = 0.0
        for i, child in enumerate(children):
            compound = isinstance(child, dict) and child.get("type", "item") != "item"
            width += _reward_measure_comic(child, item_w, plus_w, choice_gap, nested=compound)
            if i:
                width += plus_w
        return width + (10 if nested else 0)
    if typ == "choice":
        options = list(node.get("options") or [])
        if not options:
            return float(item_w)
        # Alternatives share one ordinary white manga ticket.  Its width is
        # determined only by the reward content; the stamp overlays the outer
        # top-right corner and must never create an artificial blank tail.
        option_item_w = _choice_item_width_comic(options, item_w)
        option_gap = _choice_option_gap_comic(options, option_item_w, choice_gap)
        width = 0.0
        for i, option in enumerate(options):
            compound = isinstance(option, dict) and option.get("type", "item") != "item"
            local_item_w = item_w if compound else option_item_w
            width += _reward_measure_comic(option, local_item_w, plus_w, choice_gap, nested=compound)
            if i:
                width += option_gap
        # The shared white ticket needs a small real inset on both sides.  Earlier
        # versions measured only the option contents but then drew them inside
        # x1+7..x2-7, so a right-most choice could visually run past / flatten the
        # ticket's slanted right edge.  Make that inset part of the measured width.
        return width + 14
    return float(item_w)


def _reward_layout_sizes_comic(tree, available_w):
    leaves = max(1, _reward_leaf_count_comic(tree))
    target = 106 if leaves <= 3 else (86 if leaves == 4 else 70)
    min_w = 48
    for item_w in range(target, min_w - 1, -2):
        # No visible '+': items that belong to the same reward bundle sit
        # naturally close together.  Different alternatives still keep more
        # air *unless* the choice is simply A-or-B, where the shared ticket
        # itself already communicates that the two items belong together.
        plus_w = max(5, min(9, int(round(item_w * 0.075))))
        choice_gap = max(14, min(22, int(round(item_w * 0.17))))
        if _reward_measure_comic(tree, item_w, plus_w, choice_gap, nested=False) <= available_w:
            return item_w, plus_w, choice_gap
    return min_w, 5, 14


def _choice_item_width_comic(options, item_w):
    """Plain A-or-B choices can be more compact than stand-alone reward tickets."""
    options = list(options or [])
    simple_two = (
        len(options) == 2
        and all(isinstance(x, dict) and x.get("type", "item") == "item" for x in options)
    )
    if simple_two:
        return max(50, int(item_w) - 8)
    return int(item_w)


def _choice_option_gap_comic(options, item_w, choice_gap):
    """Use a tight gap for a plain A-or-B choice; keep compound choices readable."""
    options = list(options or [])
    simple_two = (
        len(options) == 2
        and all(isinstance(x, dict) and x.get("type", "item") == "item" for x in options)
    )
    if simple_two:
        return max(3, min(5, int(round(item_w * 0.05))))
    return choice_gap


def _draw_reward_operator_comic(base, draw, s, op, box, colors, rng=None):
    """Draw only the small hand-lettered '+' used inside additive bundles."""
    if op != "+":
        return
    x1, y1, x2, y2 = map(int, box)
    angle = -5 if ((x1 + y1) // 7) % 2 else 5
    layer = _rotated_text(base, "+", s, 22, colors.get("accent2", colors["paper"]),
                          angle=angle, bold=True, stroke=1, stroke_fill=colors["ink"], alpha=245)
    px = int((x1+x2-layer.width)/2)
    py = int((y1+y2-layer.height)/2)
    base.alpha_composite(layer, (px, py))


def _choice_stamp_text_comic(options):
    """Choice seal wording.  Two alternatives always read 二选一.

    Using 任选1个 made the seal semantically leak to the whole LOOT row: when
    two ordinary rewards sit beside the shared choice ticket, readers can easily
    parse it as “pick one of all four”.  二选一 states the scope more clearly,
    while the seal's physical attachment to the shared ticket identifies the pair.
    """
    options = list(options or [])
    if len(options) == 2:
        return "二选一"
    return f"{len(options)}选1"


def _draw_choice_stamp_comic(base, s, text, corner, colors, max_width=68):
    """Small high-contrast seal that sits *on* the ticket corner, not in it.

    The ticket keeps its natural content width.  Most of the seal hangs above
    and to the right of the parallelogram, leaving only a light corner overlap.
    """
    if not text:
        return
    red = colors.get("accent", "#C92D25")
    dark_red = "#7D1614"
    paper = colors.get("paper", "#FFFDF8")

    # Horizontal seal is easier to read while staying shallow enough to avoid
    # the reward icon row.  '任选1个' is intentionally compact.
    size = 15
    font = _font(s, size, True)
    probe = Image.new("RGBA", (8, 8), (0, 0, 0, 0))
    pd = ImageDraw.Draw(probe, "RGBA")
    bb = pd.textbbox((0, 0), text, font=font, stroke_width=0)
    tw, th = bb[2]-bb[0], bb[3]-bb[1]
    stamp_w = min(int(max_width), max(54, tw + 16))
    stamp_h = max(30, th + 12)
    pad = 7

    layer = Image.new("RGBA", (stamp_w+pad*2, stamp_h+pad*2), (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer, "RGBA")
    x1, y1, x2, y2 = pad, pad, pad+stamp_w, pad+stamp_h
    ld.rectangle((x1, y1, x2, y2), fill=_rgba(red, 252), outline=_rgba(dark_red, 255), width=3)
    ld.rectangle((x1+4, y1+4, x2-4, y2-4), outline=_rgba(paper, 215), width=1)
    bb = ld.textbbox((0, 0), text, font=font, stroke_width=0)
    tw, th = bb[2]-bb[0], bb[3]-bb[1]
    tx = pad + (stamp_w-tw)//2 - bb[0]
    ty = pad + (stamp_h-th)//2 - bb[1]
    ld.text((tx, ty), text, font=font, fill=_rgba(paper, 255))

    layer = layer.rotate(-8, resample=Image.BICUBIC, expand=True)
    cx, cy = map(int, corner)
    # Keep the seal visually attached to *this* white ticket.  It still hangs
    # mostly outside so it does not cover the right-most icon, but its lower
    # edge now overlaps the ticket border clearly instead of floating near the
    # whole LOOT panel and looking like it applies to every reward.
    # Keep most of the seal over/above the shared choice ticket rather than
    # hanging into the surrounding LOOT row.  This makes its scope read as
    # “these two options” while still only grazing the ticket border.
    px = int(cx - layer.width * 0.70)
    py = int(cy - layer.height * 0.72 + 7)
    base.alpha_composite(layer, (px, py))


def _draw_reward_item_ticket_comic(base, draw, guide, s, colors, rcfg, item, box, *, draw_ticket=True):
    """Draw one reward using icon -> quantity -> name, always on one vertical axis."""
    x1, y1, x2, y2 = map(int, box)
    if draw_ticket:
        draw.polygon(
            [(x1+2, y1+3), (x2-4, y1), (x2, y2-3), (x1+5, y2)],
            fill=colors["paper"], outline=colors["ink"]
        )
    cell_w = max(1, x2-x1)
    cell_h = max(1, y2-y1)
    frame_size_cfg = int(rcfg.get("reward_frame_size", 66) or 66)
    inset_plain = max(2, int(rcfg.get("reward_icon_plain_inset", 5) or 5))
    qty_h = 20 if cell_h >= 105 else 17
    name_h = min(34, max(24, int(cell_h*0.25)))
    top_pad = 4 if draw_ticket else 1
    icon_size = max(23, int(min(cell_w-8, cell_h-qty_h-name_h-top_pad-3, frame_size_cfg)))
    px1 = int(x1 + (cell_w-icon_size)/2)
    py1 = y1 + top_pad
    ibox = (px1, py1, px1+icon_size, py1+icon_size)
    reward_renderer = RewardItemRenderer(s, guide)
    resolved = reward_renderer.draw_icon(base, item, ibox, plain_inset=inset_plain)
    icon_path = resolved.get("icon_path")
    frame_path = resolved.get("frame_path")
    if not ((icon_path and Path(icon_path).exists()) or (frame_path and Path(frame_path).exists())):
        draw.rounded_rectangle(ibox, radius=6, outline=colors["accent"], width=2)
        s.draw_center(draw, ibox, "?", colors["accent"], max_size=18, min_size=11, bold=True, max_lines=1)

    qty = s.clean(str(item.get("qty") or "1")) or "1"
    qty_y1 = min(y2-name_h-qty_h, py1+icon_size+1)
    s.draw_center(
        draw, (x1+3, qty_y1, x2-3, qty_y1+qty_h), "×"+qty, colors["ink"],
        max_size=max(13, int(rcfg.get("reward_item_font_size", 15) or 15)),
        min_size=10, bold=True, max_lines=1, line_gap=0
    )
    s.draw_center(
        draw, (x1+3, qty_y1+qty_h-1, x2-3, y2-2), s.clean(str(item.get("name") or "物品")), colors["ink"],
        max_size=int(rcfg.get("reward_item_font_size", 15) or 15),
        min_size=max(9, int(rcfg.get("reward_item_min_font_size", 13) or 13)-2),
        bold=True, max_lines=2, line_gap=0
    )


def _draw_reward_expression_comic(base, draw, guide, s, colors, rcfg, node, box,
                                  item_w, plus_w, choice_gap, nested=False, inside_choice=False):
    x1, y1, x2, y2 = map(int, box)
    typ = (node or {}).get("type", "item") if isinstance(node, dict) else "item"
    if typ == "item":
        _draw_reward_item_ticket_comic(
            base, draw, guide, s, colors, rcfg, node or {}, box,
            draw_ticket=not inside_choice
        )
        return

    if typ == "choice":
        options = list(node.get("options") or [])
        if not options:
            return
        # One shared version of the existing white parallelogram.  There is no
        # internal header, divider, '或', or bracket: all reward icons keep one
        # top line, and the small corner stamp supplies the choice semantics.
        draw.polygon(
            [(x1+2, y1+3), (x2-4, y1), (x2, y2-3), (x1+5, y2)],
            fill=colors["paper"], outline=colors["ink"]
        )
        # Every alternative receives the same y-range.  The seal mostly hangs
        # outside the frame, so it does not consume any internal layout space.
        cy1, cy2 = y1+4, y2-4
        option_item_w = _choice_item_width_comic(options, item_w)
        widths = []
        for option in options:
            compound = isinstance(option, dict) and option.get("type", "item") != "item"
            local_item_w = item_w if compound else option_item_w
            widths.append(_reward_measure_comic(option, local_item_w, plus_w, choice_gap, nested=compound))
        option_gap = _choice_option_gap_comic(options, option_item_w, choice_gap)
        total = sum(widths) + option_gap * max(0, len(options)-1)
        # Content uses the full ticket width; no blank region is reserved for
        # the stamp.  This keeps the white parallelogram exactly as large as the
        # reward content requires.
        content_left = x1 + 7
        content_right = x2 - 7
        usable = max(1.0, content_right - content_left)
        cursor = content_left + max(0.0, (usable-total)/2.0)
        for i, (option, ow) in enumerate(zip(options, widths)):
            o1, o2 = int(round(cursor)), int(round(cursor+ow))
            compound = isinstance(option, dict) and option.get("type", "item") != "item"
            local_item_w = item_w if compound else option_item_w
            _draw_reward_expression_comic(
                base, draw, guide, s, colors, rcfg, option, (o1, cy1, o2, cy2),
                local_item_w, plus_w, choice_gap, nested=compound, inside_choice=True
            )
            cursor += ow
            if i < len(options)-1:
                cursor += option_gap

        _draw_choice_stamp_comic(
            base, s, _choice_stamp_text_comic(options), (x2-3, y1+2), colors,
            max_width=max(58, min(70, int((x2-x1)*0.28)))
        )
        return

    if typ == "bundle":
        children = list(node.get("items") or [])
    else:
        _draw_reward_item_ticket_comic(
            base, draw, guide, s, colors, rcfg, node or {}, box,
            draw_ticket=not inside_choice
        )
        return
    if not children:
        return

    pad = 5 if nested else 0
    widths = []
    for child in children:
        compound = isinstance(child, dict) and child.get("type", "item") != "item"
        widths.append(_reward_measure_comic(child, item_w, plus_w, choice_gap, nested=compound))
    # Root-level reward units should use the whole LOOT stage: keep each ticket
    # at its natural content width, then distribute the remaining horizontal
    # room *between* top-level units.  Nested bundles/choice internals stay
    # compact, so a two-item choice still reads as one tight group.
    root_spread = bool(node.get("_visual_root")) and not nested and len(children) > 1
    if root_spread:
        side_pad = 8
        content_w = sum(widths)
        available = max(1.0, (x2-x1) - side_pad*2)
        # Fill the LOOT row with whitespace, but never force a minimum gap that
        # pushes the final ticket past the right safety margin.  This was the
        # second cause of a clipped-looking right edge when a choice sat last.
        remaining = max(0.0, available - content_w)
        spread_gap = remaining / max(1, len(children)-1)
        total = content_w + spread_gap * max(0, len(children)-1)
        cursor = float(x1 + side_pad)
    else:
        spread_gap = float(plus_w)
        total = sum(widths) + spread_gap * max(0, len(children)-1)
        cursor = x1 + pad + max(0.0, (x2-x1-2*pad-total)/2.0)
    op_y1, op_y2 = y1 + 20, y2 - 30
    if op_y2 <= op_y1:
        op_y1, op_y2 = y1 + 5, y2 - 5

    for i, (child, cw) in enumerate(zip(children, widths)):
        c1, c2 = int(round(cursor)), int(round(cursor+cw))
        compound = isinstance(child, dict) and child.get("type", "item") != "item"
        _draw_reward_expression_comic(
            base, draw, guide, s, colors, rcfg, child, (c1, y1, c2, y2),
            item_w, plus_w, choice_gap, nested=compound, inside_choice=inside_choice
        )
        cursor += cw
        if i < len(children)-1:
            # No visible '+'.  Root-level units use editorial whitespace to fill
            # the LOOT frame; nested items remain close enough to read as a bundle.
            cursor += spread_gap

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
    # The large loot field uses the same dark/halftone language as STATUS.
    # Ordinary rewards keep individual white manga tickets; alternatives share
    # one ticket and receive only a small diagonal choice stamp at its top-right.
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

    tree = _reward_tree_comic(guide, s)
    if not tree:
        s.draw_center(draw, (rx1+12, ry1+10, rx2-12, ry2-10), tools.reward_summary(guide), colors["paper"],
                      max_size=int(rcfg.get("reward_item_font_size", 13) or 13), min_size=9,
                      bold=True, max_lines=3, line_gap=2)
        return
    inner = (rx1+8, ry1+8, rx2-8, ry2-8)
    available_w = inner[2] - inner[0]
    item_w, plus_w, choice_gap = _reward_layout_sizes_comic(tree, available_w)
    expr_w = _reward_measure_comic(tree, item_w, plus_w, choice_gap, nested=False)
    # A multi-unit root is given the whole stage so its renderer can distribute
    # natural-size tickets across the LOOT frame.  A single unit remains centered.
    if isinstance(tree, dict) and tree.get("_visual_root") and len(tree.get("items") or []) > 1:
        ex1, ex2 = inner[0], inner[2]
    else:
        ex1 = int(inner[0] + max(0, (available_w-expr_w)/2))
        ex2 = int(min(inner[2], ex1+expr_w))
    _draw_reward_expression_comic(
        base, draw, guide, s, colors, rcfg, tree,
        (ex1, inner[1], ex2, inner[3]), item_w, plus_w, choice_gap, nested=False
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
    # Keep a manga rhythm, but never manufacture a huge size mismatch when the
    # two days have similar content.  The old 35/65-ish tie split made equal
    # D3/D4 instructions look like a hero panel beside a squeezed footnote.
    # Near-ties now use only a subtle alternation; real content differences may
    # still earn extra width, but the smaller panel keeps a readable floor.
    tie_ratios = (0.53, 0.48, 0.52)
    pair_gaps = (18, 22, 19)
    offsets = ((10, 0), (0, 10), (8, 0))

    for row, (a, b) in enumerate(pairs):
        h = heights[row]
        gap = pair_gaps[row]
        wa, wb = weights[a], weights[b]
        rel = abs(wa - wb) / max(0.01, wa + wb)
        if rel < 0.10:
            ratio = tie_ratios[row]
        else:
            # Content-aware, not content-dominated: a denser day may become
            # larger, but never so large that its neighbour loses readable
            # speech-balloon width.  A 58-62% ceiling still gives comic rhythm.
            heavy_share = min(0.62, 0.56 + rel*0.34)
            ratio = heavy_share if wa > wb else 1.0 - heavy_share
        usable_w = inner_w - gap
        # D1-D6 need enough horizontal room for a real manga balloon + status
        # ribbon.  Use both the configured floor and ~39% of the row as the
        # minimum, so equal-content D3/D4 can never collapse into 2:1 widths.
        readable_floor = max(float(min_panel_width), usable_w * 0.39)
        min_ratio = min(0.47, readable_floor / max(1.0, usable_w))
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
    # Ordinary days are comic dialogue: even when their guide text contains
    # several numbered beats, keep them inside one speech balloon.  Only D7
    # uses the explicit ①②③-style command rhythm.  A previous generic
    # "3+ steps => strips" rule accidentally made D1/D3/etc. look like a task
    # table instead of manga dialogue.
    if terminal and len(steps) >= 2:
        _draw_command_strips(draw, s, box, steps, colors, rcfg, terminal=True)
        return
    _action_dialog_balloon(draw, s, box, action, colors["ink"], colors["balloon"],
                    max_size=int(rcfg.get("day_action_font_size", 19) or 19) + (1 if terminal else 0),
                    min_size=int(rcfg.get("day_action_min_font_size", 12) or 12),
                    tail="left" if idx%2==0 else "right", bold=True,
                    line_gap=int(rcfg.get("day_action_line_gap", 3) or 3))


def _clean_target_tier_comic(s, target):
    """Return only the tier wording used beside the Day title."""
    cleaned = s.clean(str(target or ""))
    cleaned = re.sub(r"^目标档位[：:\s]*", "", cleaned).strip()
    cleaned = re.sub(r"^目标[：:\s]*", "", cleaned).strip()
    return cleaned


def _draw_tier_ticket(draw, s, panel_box, target, colors, panel_fill, terminal=False, lead=False, page_style="shonen"):
    """Draw a top-right target-tier marker tailored to each comic variant.

    The information architecture stays stable (same corner, same tier text), while
    the prop language follows the selected variant:
      - shonen: A4 single-line chapter tab;
      - vintage_print: B2 double-line print placard;
      - detective_red: C5 evidence tag, deep-red stock with outlined white type and a white eyelet.
    """
    if not target:
        return None
    x1, y1, x2, y2 = map(int, panel_box)
    page_style = str(page_style or "shonen").lower().strip()
    max_size = 30 if terminal else (28 if lead else 26)
    min_size = 17

    # Fit the wording first.  The prop should hug its content rather than reserve
    # a UI-sized block, but keep a predictable minimum hit area at the corner.
    fsize = max_size
    font = _font(s, fsize, True)
    try:
        tb = draw.textbbox((0, 0), target, font=font)
        tw = tb[2] - tb[0]
    except Exception:
        tw = len(target) * fsize
    while fsize > min_size and tw > 104:
        fsize -= 1
        font = _font(s, fsize, True)
        try:
            tb = draw.textbbox((0, 0), target, font=font)
            tw = tb[2] - tb[0]
        except Exception:
            tw = len(target) * fsize

    top = y1 + 13
    rx = x2 - 14

    if page_style == "vintage_print":
        # B2 — double-line print placard: darker aged newsprint stock, tobacco-brown
        # press border and muted rust registration line.  The stronger sepia stock
        # separates it from the normal panel paper and reads more like an old刊 header.
        h = 43 if terminal else 40
        w = max(96, min(132, int(tw + 34)))
        left = rx - w
        paper = "#D8BF87"
        brown = "#5A3B22"
        rust = "#9A542F"
        outer = [(left+2, top+4), (rx-2, top), (rx, top+h-4), (left, top+h)]
        draw.polygon(outer, fill=paper, outline=brown)
        draw.line(outer + [outer[0]], fill=brown, width=3, joint="curve")
        inset = 6
        inner = [
            (left+inset+1, top+inset+2), (rx-inset-1, top+inset),
            (rx-inset, top+h-inset-3), (left+inset, top+h-inset)
        ]
        draw.line(inner + [inner[0]], fill=rust, width=2, joint="curve")
        # Tiny off-register line gives it a printed-magazine feel without clutter.
        draw.line((left+12, top+h+2, rx-10, top+h-2), fill=rust, width=2)
        s.draw_center(draw, (left+11, top+5, rx-10, top+h-4), target, brown,
                      max_size=fsize, min_size=min_size, bold=True, max_lines=1)
        return (left, top, rx, top+h+3)

    if page_style == "detective_red":
        # C5 — evidence tag, option 9 (outlined): deep-red stock + white lettering
        # with a thin black stroke, a brighter red accent edge and a clean white eyelet.
        # Red establishes the case-file identity; white carries the information; black
        # stroke keeps the tier wording crisp against both the dark tag and red accents.
        h = 45 if terminal else 42
        w = max(106, min(140, int(tw + 46)))
        left = rx - w
        deep_red = "#8C1816"
        bright_red = "#E23B35"
        white = "#FFFFFF"
        ink = "#111111"
        notch = 17
        tag = [
            (left, top+5), (rx-notch-7, top), (rx, top+notch),
            (rx-7, top+h-5), (left+4, top+h)
        ]
        draw.polygon(tag, fill=deep_red, outline=ink)
        draw.line(tag + [tag[0]], fill=ink, width=2, joint="curve")
        # A short vivid-red registration edge adds contrast without turning the tag
        # into another warning badge.
        draw.line((left+10, top+h-5, rx-notch-13, top+h-8), fill=bright_red, width=3)
        # White eyelet/hole remains the strongest evidence-tag cue.
        cx, cy = rx-notch+1, top+notch
        r = 7
        draw.ellipse((cx-r, cy-r, cx+r, cy+r), fill=white, outline=bright_red, width=2)
        tx_box = (left+10, top+5, rx-notch-13, top+h-5)
        font = _font(s, fsize, True)
        try:
            bb = draw.textbbox((0,0), target, font=font, stroke_width=2)
            ww, hh = bb[2]-bb[0], bb[3]-bb[1]
        except Exception:
            ww, hh = int(len(target)*fsize*.9), fsize
        tx = int((tx_box[0]+tx_box[2]-ww)/2)
        ty = int((tx_box[1]+tx_box[3]-hh)/2 - 1)
        draw.text((tx, ty), target, font=font, fill=white, stroke_width=2, stroke_fill=ink)
        return (left, top, rx, top+h)

    # A4 — single-line chapter tab for the black/white shonen variant.  The left
    # black index strip makes it feel like a manga chapter tab rather than a UI pill.
    h = 42 if terminal else 39
    w = max(94, min(130, int(tw + 38)))
    left = rx - w
    paper = colors.get("paper") or "#FFFDF8"
    ink = colors.get("ink") or "#111111"
    accent = colors.get("accent") or "#B33431"
    tab = [(left+2, top+4), (rx-3, top), (rx, top+h-4), (left, top+h)]
    draw.polygon(tab, fill=paper, outline=ink)
    draw.line(tab + [tab[0]], fill=ink, width=3, joint="curve")
    strip_w = 18
    strip = [(left+2, top+4), (left+strip_w+3, top+3),
             (left+strip_w+1, top+h-1), (left, top+h)]
    draw.polygon(strip, fill=ink)
    # Keep A4 strictly monochrome; the chapter-tab geometry itself provides the
    # manga identity, so no extra red registration slash is needed.
    s.draw_center(draw, (left+strip_w+12, top+4, rx-7, top+h-3), target, ink,
                  max_size=fsize, min_size=min_size, bold=True, max_lines=1)
    return (left, top, rx, top+h)


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
        if page_style == "detective_red":
            # Detective panels already use red for case marks, stamps and tier
            # accents.  A full fan of red speed lines makes the evidence-board
            # variant noisy, so special days use one controlled halftone field
            # instead.  The red emphasis stays local to the Day label/character
            # side and never throws arbitrary lines across actions or metrics.
            _pattern_mask(base, poly, lambda pd: _halftone(
                pd, (x1, y1, min(x2, x1 + max(150, int(pw * .34))), y2),
                colors["accent"], step=10, radius=1, alpha=38, offset=idx
            ))
        else:
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

    # With all characters now kept in colour, special days need a consistent
    # non-character cue.  A restrained accent keyline/corner treatment works in
    # every comic variant without creating another large badge or UI component.
    if special:
        inset = 8
        sx1, sy1, sx2, sy2 = x1 + inset, y1 + inset, x2 - inset, y2 - inset
        if sx2 > sx1 + 30 and sy2 > sy1 + 30:
            # Upper-left and lower-right editorial brackets are enough to signal
            # a highlighted panel while leaving speech balloons/KPIs unobstructed.
            seg = max(34, min(74, int(min(pw, ph) * 0.20)))
            sw = 4 if terminal else 3
            draw.line((sx1, sy1, min(sx2, sx1+seg), sy1), fill=colors["accent"], width=sw)
            draw.line((sx1, sy1, sx1, min(sy2, sy1+seg)), fill=colors["accent"], width=sw)
            draw.line((max(sx1, sx2-seg), sy2, sx2, sy2), fill=colors["accent"], width=sw)
            draw.line((sx2, max(sy1, sy2-seg), sx2, sy2), fill=colors["accent"], width=sw)

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

    # ---- 1. Editorial header first.  Keep Day on the left and the target tier
    # as a separate, stable top-right label.  This prevents a long integrated
    # "D7 · 第X档" heading from dictating the width of the whole D7 composition.
    label = _day_label(info, idx)
    target = _clean_target_tier_comic(s, info.get("target"))
    day_color = colors["accent"] if special else colors["ink"]
    if terminal:
        base_fsize = 80 if special else 74
    else:
        base_fsize = 70 if lead else (60 if pw > 500 else 50)
        if special:
            base_fsize += 4
    # Only a light manga tilt: D7 is essentially level, ordinary days alternate
    # by just a couple of degrees.
    title_angle = 0 if terminal else (-2 if idx % 2 == 0 else 2)

    max_title_w = max(94, int(pw * (0.42 if terminal else 0.46)))
    title_size = base_fsize
    while title_size > 28:
        probe = _rotated_text(base, label, s, title_size, day_color,
                              title_angle, True, 2, colors["paper"], 242)
        if probe.width <= max_title_w:
            break
        title_size -= 2
    title_layer = _rotated_text(base, label, s, title_size, day_color,
                                title_angle, True, 2, colors["paper"], 242)
    title_x = x1 + 8
    title_y = y1 + 14
    base.alpha_composite(title_layer, (title_x, title_y))

    # Target tier uses the chosen anime chapter-subtitle bar.  It is a compact
    # prop in the panel corner and does not reserve action height.
    target_ticket = _draw_tier_ticket(
        draw, s, box, target, colors, fill, terminal=terminal, lead=lead, page_style=page_style
    )

    effect_words = ["START!", "GO!", "CHECK!", "PUSH!", "SAVE!", "MOVE!", "FINAL!!"]
    # On a special day the emphasis burst replaces the decorative effect word,
    # so the two callouts do not stack on top of each other.
    if not special:
        _paste_rotated_text(base, (x1+18, y1+92), effect_words[min(idx, 6)], s,
                            17 if not terminal else 27, colors["muted"],
                            6 if idx%2==0 else -6, True, 1, colors["paper"], 145)

    if special and not terminal:
        # D1-D6 special marker belongs to the Day header, not to the vertical
        # content stack.  Place it immediately to the RIGHT of the date on the
        # same header line, while respecting the top-right tier subtitle bar.
        # This also gives the speech balloon back the vertical space that the
        # old under-Date burst consumed.
        burst_outer = 39
        burst_inner = 21
        ticket_left = target_ticket[0] if target_ticket else (x2 - 16)
        title_right = title_x + title_layer.width
        available = ticket_left - title_right - 12
        if available < burst_outer * 2:
            burst_outer = max(30, int(available / 2))
            burst_inner = max(16, int(burst_outer * 0.54))
        burst_cx = min(title_right + burst_outer + 8, ticket_left - burst_outer - 6)
        burst_cx = max(title_right + burst_outer + 2, burst_cx)
        burst_cy = title_y + max(28, min(title_layer.height - 10, title_layer.height // 2))
        pts = _burst_polygon(burst_cx, burst_cy, burst_outer, burst_inner, 12, rng, inner=(.54, .76))
        draw.polygon(pts, fill=colors["accent"], outline=colors["ink"])
        s.draw_center(draw,
                      (burst_cx-burst_outer, burst_cy-burst_inner,
                       burst_cx+burst_outer, burst_cy+burst_inner),
                      "重点回!", colors["paper"],
                      max_size=12, min_size=8,
                      bold=True, max_lines=1)

    # ---- 2. Action box layout, still without considering any character.
    action = s.clean(str(info.get("action") or "")) or "按计划执行"
    steps = _split_action_steps(action)
    chars = len(action.replace("\n", ""))
    metric_items = list(info.get("metric_items") or [])[:4]
    has_metrics = bool(metric_items)
    # Very narrow Day panels cannot keep four status values readable in one
    # line. Reserve a compact 2x2 status area instead of clipping/ellipsizing
    # the last cells.
    # Decide by the real per-cell width rather than a brittle panel-width cutoff.
    # Four values with icons need roughly 105 px per cell to keep full numbers.
    metric_cell_est = (pw - 36) / max(1, len(metric_items)) if metric_items else pw
    # Four-digit values such as 5887/9811 need more room than three-digit
    # values even in a panel that is otherwise wide enough.  Make the switch
    # threshold data-aware so rebalancing D3/D4 never revives the old "58…"
    # regression in neighbouring panels.
    longest_metric_chars = max(
        (len(s.clean(str(item.get("value") or "—"))) for item in metric_items),
        default=1
    )
    metric_cell_need = 105 + max(0, longest_metric_chars - 3) * 12
    metric_two_rows = bool(
        has_metrics and len(metric_items) > 2 and metric_cell_est < metric_cell_need
    )
    metric_h = 62 if metric_two_rows else 38

    # D1-D6 keep the generous header safety band that protects the integrated
    # Day/tier title. D7 keeps its large typography in the LEFT illustration column.
    if terminal:
        header_h = max(62, int(rcfg.get("terminal_action_top", 72) or 72))
    else:
        header_h = 104 if lead else (80 if pw < 335 else 96)

    # Day label and target are now independent.  Only the left Day label needs
    # to reserve vertical header space; the top-right tier never pushes actions down.
    title_visual_bottom = 14 + title_layer.height
    # Ordinary panels place actions below the real rotated title bounds.  D7 is
    # different: its title lives in the left illustration column, so pushing the
    # right-hand command stack below the whole title wastes vertical space.
    # Keep D7's configured top and solve collision horizontally with a wider
    # illustration gutter below.
    if terminal:
        header_h = max(62, int(rcfg.get("terminal_action_top", 72) or 72))
    else:
        header_h = max(header_h, title_visual_bottom + 10)
        # Do not let a very tall title consume the action body completely.
        header_h = min(header_h, max(88, int(ph * 0.42)))
    by1 = y1 + header_h
    by2 = y2 - ((metric_h + 12) if has_metrics else 18)
    # Ordinary speech balloons need visible breathing room above the
    # remaining/expected ribbon.  Four pixels read as if the balloon were
    # glued to the status row, especially in narrow D1-D6 panels.  Reserve a
    # deliberate comic gutter without changing the metric ribbon itself.
    if has_metrics and not terminal:
        action_metric_gap = max(14, int(rcfg.get("day_action_metric_gap", 16) or 16))
        by2 = y2 - metric_h - 8 - action_metric_gap

    if terminal:
        # D7 previously grew its left gutter from the width of "D7 · 第X档".
        # That pushed every command strip toward the right edge and made the
        # whole panel feel right-heavy.  With the tier detached, use a balanced
        # fixed proportion instead: enough illustration room, but commands begin
        # closer to the visual center of the panel.
        configured_gutter = int(rcfg.get("terminal_illustration_width", 270) or 270)
        # D7 reads as two centered comic columns: a substantial character panel
        # on the left and ①②③ commands on the right.  Keep balanced outer margins
        # instead of pushing the command stack to the extreme right.
        # Keep the command column visually centered instead of over-reserving
        # the left illustration side.  The previous 45% gutter plus a positive
        # command shift pushed ①②③ noticeably to the right.  Around 37% leaves
        # a large hero column while bringing the commands back toward center.
        desired_gutter = max(250, configured_gutter, int(pw * 0.37))
        max_gutter = max(240, pw - 330)  # preserve a readable command column
        terminal_gutter = min(desired_gutter, max_gutter)
        # Optional theme override remains available, but the neutral default is
        # now zero: D7 should not receive an automatic rightward shove.
        terminal_command_shift_x = int(rcfg.get("terminal_command_shift_x", 0) or 0)
        terminal_command_shift_x = max(-28, min(28, terminal_command_shift_x))
        bx1, bx2 = x1 + terminal_gutter + 8 + terminal_command_shift_x, x2 - 24
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

    # Defensive minimum height.  If a very short panel is cramped, recover as
    # much action height as possible but never move the action above the real
    # visual bottom of the Day/tier title.
    if by2-by1 < 88:
        title_safe_y = y1 + title_visual_bottom + 4
        by1 = max(title_safe_y, min(by1, by2-88))
    _draw_action_bubble_or_strips(
        draw, s, (bx1, by1, bx2, by2),
        action, colors, rcfg, idx, terminal=terminal
    )

    # ---- 3. Metrics follow the action box horizontally, preserving the same gutter.
    metric_box = None
    if has_metrics:
        mx1, mx2 = bx1, bx2
        # The command bubble can become narrow in compact panels.  Status data
        # is more important than preserving that same width, so expand the
        # ribbon to the whole panel whenever a cell would become cramped.
        per_cell = (mx2-mx1) / max(1, len(metric_items))
        if mx2-mx1 < 110 or per_cell < 88:
            mx1, mx2 = x1+18, x2-18
        # Remaining / expected now use compact manga slashes: icon + value in
        # individual parallelograms.  No oversized full-width black bar.
        metric_box = (mx1, y2-metric_h-8, mx2, y2-8)
        _draw_metric_values_comic(
            base, draw, guide, info, s, colors, metric_box
        )

    # ---- 4. Only now look at the whitespace and insert optional decoration.
    gap = int(rcfg.get("character_content_gap", 10) or 10)
    free_bottom = (metric_box[1]-gap) if metric_box else (y2-5)
    # D7 metrics live only under the RIGHT command column.  They should not
    # shorten the LEFT character column; doing so was the main reason the
    # character stayed tiny while a large blank area remained visible.
    if terminal and open_side == "left":
        free_bottom = y2 - 8
    free = None
    # Keep character art below the left-side Day hierarchy.  On special D7 the
    # 重点回 burst sits under D7, so reserve that burst instead of shrinking or
    # pushing the right-side operation stack.
    free_top = by1 + 2
    if terminal:
        # The special marker now sits to the RIGHT of D7, so the illustration
        # column can begin directly beneath the Day title and use the vertical
        # space symmetrically.
        free_top = max(y1 + 68, y1 + 14 + title_layer.height - 4)
    if open_side == "left":
        fx1 = x1+8
        fx2 = bx1-gap
        free = (fx1, free_top, fx2, free_bottom)
    else:
        fx1 = bx2+gap
        fx2 = x2-8
        free = (fx1, free_top, fx2, free_bottom)

    character_placement = _paste_character_in_free_space(
        base, guide, s, colors, rcfg, box, free, info, idx,
        side=open_side, terminal=terminal
    )

    # D7 special-day emphasis is deliberately drawn AFTER the character.  The
    # character can therefore sit directly under D7 without hiding the marker;
    # the marker reads as a small comic overlay attached to the Day header.
    if special and terminal:
        # Attach the special-day burst to the D7 header itself: immediately to
        # the right of D7, while leaving the top-right tier ticket independent.
        burst_outer = 46
        burst_inner = 24
        ticket_left = target_ticket[0] if target_ticket else (x2 - 120)
        preferred_cx = title_x + title_layer.width + burst_outer + 8
        burst_cx = min(preferred_cx, ticket_left - burst_outer - 10)
        burst_cx = max(x1 + 112, burst_cx)
        burst_cy = y1 + 48
        pts = _burst_polygon(burst_cx, burst_cy, burst_outer, burst_inner, 12, rng, inner=(.54, .76))
        draw.polygon(pts, fill=colors["accent"], outline=colors["ink"])
        s.draw_center(draw,
                      (burst_cx-burst_outer, burst_cy-burst_inner,
                       burst_cx+burst_outer, burst_cy+burst_inner),
                      "重点回!", colors["paper"],
                      max_size=14, min_size=9, bold=True, max_lines=1)
    return character_placement

def _draw_metric_values_comic(base, draw, guide, info, s, colors, box):
    """One connected manga status ribbon: four icon/value cells, shared edges."""
    items = list(info.get("metric_items") or [])[:4]
    if not items:
        return
    x1,y1,x2,y2=map(int,box)
    n=len(items)
    w=max(1,x2-x1); h=max(1,y2-y1)

    # Compact portrait-like panels use two connected mini-ribbons (2 x 2).
    # This preserves the complete values rather than showing e.g. "6…".
    if n > 2 and h >= 56:
        gap = 4
        row_h = max(24, int((h-gap)/2))
        for rr in range(2):
            row_items = items[rr*2:(rr+1)*2]
            if not row_items:
                continue
            ry1 = y1 + rr*(row_h+gap)
            ry2 = y2 if rr == 1 else min(y2, ry1+row_h)
            nested_info = dict(info or {})
            nested_info["metric_items"] = row_items
            _draw_metric_values_comic(base, draw, guide, nested_info, s, colors, (x1, ry1, x2, ry2))
        return

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

    # Pick one shared size for the whole ribbon.  Narrow panels no longer let
    # the final remaining/expected value fall outside its cell.
    nominal_cell = max(1.0, w / float(n))
    shared_icon_size = max(14, min(22, h-8, int(nominal_cell*0.24)))
    shared_font_size = 11
    for candidate in range(15, 10, -1):
        font = _font(s, candidate, True)
        all_fit = True
        for item in items:
            icon = s.config_day_icon(cfg, item)
            icon_cost = shared_icon_size + 5 if icon and Path(icon).exists() else 0
            max_text_w = max(8, nominal_cell - icon_cost - 16)
            value = s.clean(str(item.get("value") or "—"))
            try:
                tw = draw.textlength(value, font=font)
            except Exception:
                bb = draw.textbbox((0, 0), value, font=font)
                tw = bb[2]-bb[0]
            if tw > max_text_w:
                all_fit = False
                break
        if all_fit:
            shared_font_size = candidate
            break
    shared_font = _font(s, shared_font_size, True)

    for i,item in enumerate(items):
        t0=i/float(n); t1=(i+1)/float(n)
        tl=top_left+(top_right-top_left)*t0; tr=top_left+(top_right-top_left)*t1
        bl=bot_left+(bot_right-bot_left)*t0; br=bot_left+(bot_right-bot_left)*t1
        a=int(max(tl,bl)+5); b=int(min(tr,br)-5)
        if b<=a+12:
            a=int(min(tl,bl)+3); b=int(max(tr,br)-3)
        icon=s.config_day_icon(cfg,item)
        icon_size=shared_icon_size
        value=s.clean(str(item.get("value") or "—"))
        # Center icon+number as a compact pair inside each shared cell.
        max_value_w=max(8,(b-a) - (icon_size+5 if icon and Path(icon).exists() else 0))
        max_value_w=max(8,max_value_w-4)
        value=_ellipsize_single_line(draw,s,value,shared_font,max_value_w)
        vb=draw.textbbox((0,0),value,font=shared_font)
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
                    max_size=shared_font_size,min_size=shared_font_size,bold=True,max_lines=1,line_gap=0,valign="center")

def _draw_risk(base, draw, guide, s, tools, colors, rcfg, box, rng):
    x1, y1, x2, y2 = map(int, box); cx=(x1+x2)//2; cy=(y1+y2)//2
    page_style = str(rcfg.get("page_style") or "shonen").lower().strip()

    risks = tools.risk_items(guide)
    body = "\n".join("●  "+x for x in risks[:4]) if risks else "●  到达目标档位后停止\n●  不要为随机奖励过度追高"
    warning = str(rcfg.get("warning_text") or "WARNING!!")

    if page_style == "detective_red":
        # Detective decoration follows one restrained case-file language: solid
        # red paper/backing, short corner brackets and stamps.  Avoid explosion
        # rays / long free-floating red lines, which duplicate the evidence-board
        # accents and make the lower page look tangled.
        accent = colors.get("accent", "#B51F24")
        ink = colors["ink"]
        paper = colors["paper"]

        # One torn-paper backing shape gives the warning visual weight without
        # sending spikes across the page.
        pad_x = 92
        top = y1 + 58
        bottom = y2 - 24
        back = [
            (x1+pad_x+18, top+8),
            (x2-pad_x-22, top),
            (x2-pad_x, top+24),
            (x2-pad_x-14, bottom-4),
            (x1+pad_x+6, bottom),
            (x1+pad_x-8, bottom-22),
        ]
        draw.polygon([(x+5, y+6) for x,y in back], fill=_rgba(ink, 45))
        draw.polygon(back, fill=_rgba(accent, 238), outline=ink)

        balloon = (x1+155, y1+76, x2-105, y2-38)
        _warning_callout(draw, s, balloon, body, ink, paper,
                         max_size=int(rcfg.get("risk_font_size", 19) or 19),
                         min_size=15, bold=True, line_gap=5)

        # Compact warning stamp attached to the upper-left of the backing.
        stamp = (x1+76, y1+23, x1+250, y1+70)
        draw.polygon([
            (stamp[0]+4, stamp[1]+5), (stamp[2], stamp[1]),
            (stamp[2]-7, stamp[3]-4), (stamp[0], stamp[3])
        ], fill=paper, outline=ink)
        draw.rectangle((stamp[0]+5, stamp[1]+6, stamp[0]+13, stamp[3]-5), fill=accent)
        _paste_rotated_text(base, (stamp[0]+20, stamp[1]+5), warning, s,
                            int(rcfg.get("warning_font_size", 29) or 29),
                            accent, -2, True, 1, paper, 255)

        # Two small, repeatable case-file corner brackets are enough decoration.
        draw.line((x1+54, y1+96, x1+54, y1+126), fill=accent, width=3)
        draw.line((x1+54, y1+96, x1+83, y1+96), fill=accent, width=3)
        draw.line((x2-54, y2-92, x2-54, y2-62), fill=accent, width=3)
        draw.line((x2-83, y2-62, x2-54, y2-62), fill=accent, width=3)
        return

    # Other manga variants retain the energetic explosion treatment.
    outer = colors.get("explosion_outer", "#D95827")
    inner = colors.get("explosion_inner", "#F3C84B")
    hot = colors.get("explosion_hot", "#E9822D")
    pts = _burst_polygon(cx, cy, (x2-x1)//2, (y2-y1)//2, 22, rng, inner=(.50, .74))
    draw.polygon([(x+6, y+7) for x,y in pts], fill=_rgba(colors["ink"], 48))
    draw.polygon(pts, fill=outer, outline=colors["ink"])
    inner_pts = _burst_polygon(cx, cy+4, int((x2-x1)*.39), int((y2-y1)*.34), 18, rng, inner=(.61, .82))
    draw.polygon(inner_pts, fill=inner, outline=hot)
    _speedlines(draw, (x1+35, y1+24, x2-35, y2-24), (cx, cy), colors["ink"], rng, count=22, alpha=(18, 34))

    _warning_callout(draw, s, (x1+165, y1+78, x2-115, y2-38), body, colors["ink"], colors["paper"],
                     max_size=int(rcfg.get("risk_font_size", 19) or 19), min_size=15, bold=True, line_gap=5)

    # Draw WARNING last as an impact burst / sound-effect title, never a UI pill.
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
    3. The selected culprit keeps its full-colour artwork; the magnifier and
       red 真凶 stamp provide the reveal without destroying character readability.
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
    all_chars_color = bool(_char_cfg(rcfg, "character_all_days_color", None, True))
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

        # All-colour comic rendering applies to ordinary suspects only.  The
        # detective variant keeps its own unrevealed-identity language for the
        # selected culprit: an opaque black silhouette + white question mark.
        # This is a semantic detective cue, not the ordinary/special-day colour
        # treatment, so it must remain even when character_all_days_color=True.
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
                    base.paste(opaque_black, (x1, y1), hard_alpha)
                except Exception:
                    pass

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
        # D7's character now begins directly below the Day hierarchy.  A tag
        # floating above the sprite would collide with the 重点回 burst, so keep
        # the roster tag attached to the character's upper-right shoulder area.
        if day_idx >= 6:
            tx1 = max(4, x2 - tag_w - 4)
            tx2 = tx1 + tag_w
            ty1 = max(4, y1 + 4)
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
            if day_idx >= 6:
                # D7's 重点回 burst now sits beside the Day label. Keep the
                # detective reveal stamp attached to the character itself so the
                # two comic callouts never overlap.
                sx1 = max(4, x1 + 6)
                sy1 = max(4, y1 + 8)
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

            # The magnifier + attached 真凶 stamp already identify the reveal.
            # Do not add a long red connector: on a dense case-board page it
            # reads as one more stray evidence string and crosses character art.

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
        # Detective paper uses a disciplined red/black line language.  The
        # background may feel like an evidence board, but the lines must read as
        # texture rather than as arbitrary connections between unrelated content.
        # Panels are painted later and therefore naturally mask the pattern; the
        # red/black hatching remains visible mainly in page margins and gutters.
        edge = c["accent"]
        for yy in range(-H, H*2, 48):
            d.line((0, yy, W, yy+W), fill=_rgba(c["ink"], 16), width=1)
        for yy in range(-H+24, H*2, 144):
            d.line((0, yy, W, yy+W), fill=_rgba(edge, 44), width=2)
        # A very faint counter-direction black hatch keeps the paper from reading
        # as a set of parallel hazard stripes while staying quieter than the red.
        for yy in range(0, H+W, 104):
            d.line((0, yy, W, yy-W), fill=_rgba(c["ink"], 6), width=1)
        for yy in range(0, H, 22):
            for xx in range((yy//22)%2*11, W, 22):
                d.ellipse((xx, yy, xx+1, yy+1), fill=_rgba(c["ink"], 18))

        # Four short evidence rails anchor the line texture to the case-file
        # motif.  They stay in the margins and never cross readable content.
        margin_marks = [
            (16, 205, 16, 352, "left"),
            (W-18, 335, W-18, 500, "right"),
            (16, H-520, 16, H-372, "left"),
            (W-18, H-356, W-18, H-214, "right"),
        ]
        for x1m, y1m, x2m, y2m, side in margin_marks:
            d.line((x1m, y1m, x2m, y2m), fill=_rgba(edge, 172), width=2)
            for yy in (y1m, y2m):
                d.ellipse((x1m-4, yy-4, x1m+4, yy+4), fill=_rgba(edge, 220))
            tick = 18 if side == "left" else -18
            mid = (y1m + y2m)//2
            d.line((x1m, mid, x1m+tick, mid-10), fill=_rgba(c["ink"], 145), width=2)

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

