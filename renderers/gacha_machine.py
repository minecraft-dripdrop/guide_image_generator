# -*- coding: utf-8 -*-
"""Gacha-machine strategy renderer.

Mobile-first 9:16 layout based on the approved readability sketch:
small decorative capsule chamber -> large D1-D7 operation console -> compact
resource control -> warning plate -> physical capsule pickup / reward hatch.
The capsule chamber sells the theme; the operation console owns the page.
"""
from __future__ import annotations

import random
from pathlib import Path
from PIL import Image, ImageDraw, ImageOps, ImageFilter

from .shared import SharedRendererTools
from .reward_items import RewardItemRenderer
from ._media_theme_common import (
    mobile_canvas, rcfg, clean, target_text, target_level_number, special_text,
    day_metric_text,
)

STYLE_IDS = ("gacha_machine",)


def _capsule(draw, cx, cy, r, top, bottom, outline="#FFFFFF", seam=None):
    """Simple two-tone capsule used as the theme's repeating visual language."""
    seam = seam or outline
    draw.ellipse((cx-r, cy-r, cx+r, cy+r), fill=bottom, outline=outline, width=max(2, r//14))
    draw.pieslice((cx-r, cy-r, cx+r, cy+r), 180, 360, fill=top)
    draw.line((cx-r+2, cy, cx+r-2, cy), fill=seam, width=max(2, r//16))
    # small glossy highlight
    hr = max(4, r//7)
    draw.ellipse((cx-r//2, cy-r//2, cx-r//2+hr, cy-r//2+hr), fill="#FFFFFF")


def _shade_hex(color, factor=0.78):
    """Return a darker/lighter hex variant for plastic capsule halves."""
    c = str(color or "#888888").lstrip("#")
    if len(c) != 6:
        return "#777777"
    try:
        vals = [int(c[i:i+2], 16) for i in (0,2,4)]
    except Exception:
        return "#777777"
    vals = [max(0,min(255,int(round(v*factor)))) for v in vals]
    return "#{:02X}{:02X}{:02X}".format(*vals)


def _mix_hex(a, b, t=0.5):
    """Blend two #RRGGBB colors."""
    def _rgb(c):
        c = str(c or "#888888").lstrip("#")
        if len(c) != 6:
            return (136,136,136)
        try:
            return tuple(int(c[i:i+2],16) for i in (0,2,4))
        except Exception:
            return (136,136,136)
    ar,ag,ab=_rgb(a); br,bg,bb=_rgb(b)
    t=max(0.0,min(1.0,float(t)))
    rr=int(round(ar*(1-t)+br*t)); gg=int(round(ag*(1-t)+bg*t)); bb2=int(round(ab*(1-t)+bb*t))
    return "#{:02X}{:02X}{:02X}".format(rr,gg,bb2)


def _screw(draw, cx, cy, r=6, fill="#C7CDD1", outline="#5B6369"):
    """Small metal fastener used to make the cabinet feel physically assembled."""
    draw.ellipse((cx-r, cy-r, cx+r, cy+r), fill=fill, outline=outline, width=2)
    draw.line((cx-r//2, cy, cx+r//2, cy), fill=outline, width=1)


def _beveled_panel(draw, box, fill, light="#F46A60", dark="#7D2925", radius=24, width=5):
    """Paint a shallow plastic/metal bevel without changing the layout semantics."""
    x1,y1,x2,y2 = map(int, box)
    draw.rounded_rectangle((x1,y1,x2,y2), radius=radius, fill=fill, outline=dark, width=width)
    # top/left highlight + bottom/right shadow suggest molded cabinet thickness
    draw.line((x1+radius,y1+7,x2-radius,y1+7), fill=light, width=3)
    draw.line((x1+7,y1+radius,x1+7,y2-radius), fill=light, width=3)
    draw.line((x1+radius,y2-8,x2-radius,y2-8), fill=dark, width=4)
    draw.line((x2-8,y1+radius,x2-8,y2-radius), fill=dark, width=4)


def _compact_diamond_kpi(label, value):
    """Theme-local display cleanup: diamond icon already says '钻石', so omit the word."""
    label = str(label or "")
    value = str(value or "")
    if "预算" in label and "钻石" in label:
        label = label.replace("钻石", "").strip(" ·|｜/-_") or "预算"
    if "预算" in label and "钻石" in value:
        value = value.replace("钻石", "").strip()
    return label, value


def _draw_gacha_kpis(base, draw, guide, services, tools, box, colors):
    """Gacha-local KPI cells: canonical icons, compact diamond wording, LCD-like readout."""
    items = tools.kpis(guide)
    if not items:
        return
    x1,y1,x2,y2 = map(int, box)
    gap = 8
    count = len(items)
    cell_w = (x2-x1-gap*max(0,count-1))/max(1,count)
    for i,item in enumerate(items):
        a = int(round(x1+i*(cell_w+gap)))
        b = int(round(a+cell_w))
        # recessed LCD cell
        draw.rounded_rectangle((a,y1,b,y2), radius=9, fill="#11171B", outline="#364149", width=2)
        draw.line((a+6,y1+5,b-6,y1+5), fill="#273137", width=2)
        icon = item.get("icon")
        has_icon = bool(icon and Path(icon).exists())
        label,value = _compact_diamond_kpi(services.clean(str(item.get("label") or "")), services.clean(str(item.get("value") or "")))
        icon_size = min(36, y2-y1-16, max(24,int(cell_w//4)))
        tx = a+10
        if has_icon:
            iy = int(y1+(y2-y1-icon_size)/2)
            services.draw_image_contain(base, Path(icon), (a+9,iy,a+9+icon_size,iy+icon_size))
            tx = a+17+icon_size
        services.draw_left(draw,(tx,y1+7,b-7,y1+31),label,"#AAB5BC",
                           max_size=13,min_size=10,bold=True,max_lines=1,valign="center")
        services.draw_left(draw,(tx,y1+29,b-7,y2-5),value,colors["screen_text"],
                           max_size=21,min_size=15,bold=True,max_lines=1,valign="center")


def _draw_coin_mechanism(draw, services, box, colors):
    """Compact coin slot + turn knob assembly, deliberately outside KPI text cells."""
    x1,y1,x2,y2 = map(int, box)
    # metal faceplate
    draw.rounded_rectangle((x1,y1,x2,y2), radius=16, fill="#E3E6E7", outline="#6D767C", width=3)
    draw.rounded_rectangle((x1+7,y1+7,x2-7,y2-7), radius=11, fill="#BFC6CA", outline="#F8FAFA", width=2)
    # coin slot
    slot_cx=(x1+x2)//2
    draw.rounded_rectangle((slot_cx-22,y1+14,slot_cx+22,y1+27), radius=5, fill="#343B3F", outline="#777F84", width=1)
    services.draw_center(draw,(x1+8,y1+29,x2-8,y1+46),"COIN", "#4A5257", max_size=8,min_size=7,bold=True,max_lines=1)
    # physical turn knob
    cy=y1+73
    draw.ellipse((slot_cx-31,cy-31,slot_cx+31,cy+31), fill="#D6DBDE", outline="#646D73", width=3)
    draw.ellipse((slot_cx-18,cy-18,slot_cx+18,cy+18), fill="#8E979D", outline="#4E565B", width=2)
    draw.line((slot_cx,cy-17,slot_cx,cy-29), fill=colors["machine"], width=5)
    # arrow hints at real vending action
    draw.arc((slot_cx-42,cy-42,slot_cx+42,cy+42), 15, 120, fill="#626B70", width=3)
    services.draw_center(draw,(x1+8,y2-24,x2-8,y2-5),"TURN", "#4A5257", max_size=8,min_size=7,bold=True,max_lines=1)


def _cover_crop(source, size, focus_y=0.44):
    """Center-cover an image into size, with a slight vertical focus bias."""
    tw, th = map(int, size)
    if tw <= 0 or th <= 0:
        return source.copy()
    sw, sh = source.size
    scale = max(tw / max(1, sw), th / max(1, sh))
    rw, rh = max(1, int(round(sw * scale))), max(1, int(round(sh * scale)))
    layer = source.resize((rw, rh), Image.Resampling.LANCZOS)
    left = max(0, (rw - tw) // 2)
    max_top = max(0, rh - th)
    # focus_y is the desired source focus position inside the output window.
    focus_px = int(round(rh * max(0.0, min(1.0, focus_y))))
    top = max(0, min(max_top, focus_px - th // 2))
    return layer.crop((left, top, left + tw, top + th))


def _draw_glass_chamber(base, draw, guide, services, box, colors):
    """Compact glass chamber using theme-configured artwork when available.

    The renderer never hardcodes a concrete artwork filename. The active theme /
    variant declares ``assets.capsule_chamber``; this function only consumes that
    setting and keeps a deterministic Python fallback when it is absent or invalid.
    """
    x1,y1,x2,y2 = map(int, box)
    # thick cabinet rim / inner glass bezel
    draw.rounded_rectangle((x1-8,y1-8,x2+8,y2+8), radius=34, fill="#B9342E", outline="#6C2522", width=4)
    draw.rounded_rectangle((x1,y1,x2,y2), radius=30, fill=colors["glass"], outline="#39454D", width=5)

    # Keep only a very thin physical gasket around supplied artwork.  A large
    # light-colored inset makes the chamber look like an image pasted into a
    # picture frame rather than content living behind the machine glass.
    inner = (x1+7, y1+7, x2-7, y2-7)
    ix1,iy1,ix2,iy2 = inner
    artwork_path = None
    artwork_crop = None
    artwork_focus_y = 0.43
    try:
        theme_cfg = guide.get("theme_config") if isinstance(guide.get("theme_config"), dict) else {}
        asset_cfg = theme_cfg.get("assets") if isinstance(theme_cfg.get("assets"), dict) else {}
        artwork_cfg = asset_cfg.get("capsule_chamber")
        # Backward-compatible: old themes may still provide a plain string.
        if isinstance(artwork_cfg, dict):
            artwork_value = str(artwork_cfg.get("path") or "").strip()
            crop_value = artwork_cfg.get("crop")
            if isinstance(crop_value, (list, tuple)) and len(crop_value) == 4:
                try:
                    artwork_crop = tuple(float(v) for v in crop_value)
                except Exception:
                    artwork_crop = None
            try:
                artwork_focus_y = float(artwork_cfg.get("focus_y", artwork_focus_y))
            except Exception:
                artwork_focus_y = 0.43
        else:
            artwork_value = str(artwork_cfg or "").strip()
        if artwork_value:
            artwork_path = services.resolve_path(guide.get("cfg") or {}, artwork_value)
    except Exception:
        artwork_path = None

    used_artwork = False
    if artwork_path and Path(artwork_path).is_file():
        try:
            source = Image.open(artwork_path).convert("RGBA")
            sw, sh = source.size
            # Asset-specific framing belongs to the theme config.  Crop directly
            # into the artwork's glass-content region so its own silver/red bezel
            # never becomes a second frame inside our machine.
            if artwork_crop is not None:
                l,t,r,b = artwork_crop
                l=max(0.0,min(1.0,l)); t=max(0.0,min(1.0,t))
                r=max(l+0.001,min(1.0,r)); b=max(t+0.001,min(1.0,b))
                crop=(int(round(sw*l)),int(round(sh*t)),int(round(sw*r)),int(round(sh*b)))
                source=source.crop(crop)
            layer = _cover_crop(source, (ix2-ix1, iy2-iy1), focus_y=artwork_focus_y)

            # Rounded mask clips the supplied artwork to our deterministic glass window.
            mask = Image.new("L", layer.size, 0)
            md = ImageDraw.Draw(mask)
            md.rounded_rectangle((0,0,layer.width-1,layer.height-1), radius=25, fill=255)
            layer.putalpha(mask)
            base.alpha_composite(layer, (ix1, iy1))
            used_artwork = True
        except Exception:
            used_artwork = False

    if not used_artwork:
        # Safe fallback for projects where the optional artwork has not been copied.
        draw.rounded_rectangle(inner, radius=22, fill="#E8F4F8", outline="#A9BBC6", width=2)
        rng = random.Random(70917)
        palette = ["#F04F45","#2D9BD1","#F1B933","#74B945","#9956A6","#F58D2F","#F6F3EA","#3AA99D","#F17CA3"]
        cap_top = y1 + 58
        cap_bottom = y2 - 30
        for _ in range(28):
            r = rng.randint(21, 31)
            cx = rng.randint(x1+46, x2-46)
            cy = rng.randint(cap_top, cap_bottom)
            top = rng.choice(palette)
            bottom = _shade_hex(top, 0.80)
            draw.ellipse((cx-r+4,cy-r+6,cx+r+4,cy+r+6), fill="#A9B6BC")
            _capsule(draw,cx,cy,r,top,bottom,"#FFFFFF","#D9E4E8")

    # A thin gasket is enough for supplied artwork.  AI chamber artwork already
    # contains its own glass reflections, so do not paint another set of strong
    # white streaks over it.  The fallback still needs synthetic reflections.
    draw.rounded_rectangle(inner, radius=25, outline="#66747D", width=2)
    if not used_artwork:
        draw.line((x1+28,y1+34,x1+46,y2-30), fill="#FFFFFF", width=8)
        draw.line((x1+58,y1+40,x1+65,y2-46), fill="#F9FDFF", width=3)
        draw.line((x2-48,y1+40,x2-38,y2-40), fill="#FFFFFF", width=4)
    draw.line((x1+24,y2-22,x2-24,y2-22), fill="#A9B8BF", width=4)
    for sx,sy in ((x1+22,y1+22),(x2-22,y1+22),(x1+22,y2-22),(x2-22,y2-22)):
        _screw(draw,sx,sy,5)


def _theme_asset_value(guide, key):
    """Return one theme asset config value without hard-coding filenames."""
    try:
        theme_cfg = guide.get("theme_config") if isinstance(guide.get("theme_config"), dict) else {}
        assets = theme_cfg.get("assets") if isinstance(theme_cfg.get("assets"), dict) else {}
        return assets.get(key)
    except Exception:
        return None


def _draw_refined_capsule(draw, cx, cy, r, color):
    """More dimensional fallback day capsule: molded plastic, seam, shadow, speculars."""
    dark = _shade_hex(color, 0.72)
    mid = _shade_hex(color, 0.88)
    # Ground shadow is drawn by the shared capsule placement helper.
    # lower shell + top shell
    draw.ellipse((cx-r, cy-r, cx+r, cy+r), fill=dark, outline="#F9FBFC", width=3)
    draw.pieslice((cx-r+1, cy-r+1, cx+r-1, cy+r-1), 180, 360, fill=color)
    # lower-side inner glow to make the plastic shell feel rounded
    draw.arc((cx-r+5, cy-r+8, cx+r-5, cy+r-3), 18, 155, fill=mid, width=max(2, r//10))
    # molded seam and rim
    draw.line((cx-r+4, cy, cx+r-4, cy), fill="#F7FAFB", width=3)
    draw.line((cx-r+7, cy+4, cx+r-7, cy+4), fill=_shade_hex(color,0.58), width=2)
    # specular highlights
    hr=max(5,r//5)
    draw.ellipse((cx-r//2, cy-r//2, cx-r//2+hr, cy-r//2+hr), fill="#FFFFFF")
    draw.arc((cx-r+7, cy-r+7, cx+r-7, cy+r-7), 205, 292, fill="#FFFFFF", width=2)


def _hex_rgb(value, fallback="#888888"):
    """Parse a CSS-style #RRGGBB color into an RGB tuple."""
    text = str(value or fallback).strip().lstrip("#")
    if len(text) != 6:
        text = str(fallback).strip().lstrip("#")
    try:
        return tuple(int(text[i:i+2], 16) for i in (0,2,4))
    except Exception:
        return (136,136,136)


def _mix_rgb(a, b, amount):
    amount=max(0.0,min(1.0,float(amount)))
    return tuple(int(round(x+(y-x)*amount)) for x,y in zip(a,b))


def _tinted_capsule_layer(source, color):
    """Build a colored version from source luminance while preserving alpha.

    This is shared by both recolor modes.  Bright source pixels remain highlights,
    dark source pixels remain molded/shadow details, and only the hue family changes.
    """
    src=source.convert("RGBA")
    alpha=src.getchannel("A")
    gray=ImageOps.grayscale(src)
    base_rgb=_hex_rgb(color)
    dark_rgb=_mix_rgb(base_rgb,(8,10,12),0.58)
    light_rgb=_mix_rgb(base_rgb,(255,255,255),0.80)
    tinted=ImageOps.colorize(
        gray,
        black=dark_rgb,
        mid=base_rgb,
        white=light_rgb,
        blackpoint=12,
        midpoint=148,
        whitepoint=248,
    ).convert("RGBA")
    tinted.putalpha(alpha)
    return tinted


def _recolor_neutral_capsule(source, color):
    """Tint an entire neutral gray/white AI master (legacy/full recolor mode)."""
    return _tinted_capsule_layer(source,color)


def _recolor_colored_half_capsule(source, color, saturation_threshold=34, softness=30):
    """Replace only the *colored* plastic half and keep white/neutral plastic intact.

    Recommended master artwork: one saturated red (or any saturated hue) half plus
    one white half on transparent background.  The selection is based on HSV
    saturation instead of a geometric straight-line mask, so an AI-drawn curved or
    tilted seam is preserved exactly.  White plastic, gray seam hardware and white
    specular highlights stay untouched.
    """
    src=source.convert("RGBA")
    tinted=_tinted_capsule_layer(src,color)
    sat=src.convert("HSV").getchannel("S")
    threshold=max(0,min(240,int(saturation_threshold)))
    soft=max(1,min(120,int(softness)))
    hi=min(255,threshold+soft)
    if hi<=threshold:
        hi=min(255,threshold+1)
    # Feather the chroma selection so antialiased colored edges do not develop halos.
    def _sel(v):
        if v<=threshold:
            return 0
        if v>=hi:
            return 255
        return int(round((v-threshold)*255/max(1,hi-threshold)))
    mask=sat.point(_sel)
    return Image.composite(tinted,src,mask)


def _day_capsule_asset_entry(cfg, day_index):
    """Resolve the per-day capsule asset entry declared by Theme JSON.

    ``assets.day_capsule.items`` is intentionally ordered by day so concrete
    filenames, per-file scale and visual-centering offsets stay out of the
    renderer.  A plain string entry is accepted as shorthand for ``{"path": ...}``.
    """
    if not isinstance(cfg, dict):
        return {}
    items=cfg.get("items")
    if not isinstance(items,(list,tuple)) or not items:
        return {}
    try:
        entry=items[int(day_index) % len(items)]
    except Exception:
        entry=items[0]
    if isinstance(entry,dict):
        return entry
    text=str(entry or "").strip()
    return {"path":text} if text else {}


def _day_capsule_color(cfg, asset_entry, day_index, fallback_color):
    """Resolve vector/recolor fallback color without hard-coding a day palette."""
    if isinstance(asset_entry,dict):
        value=(asset_entry.get("fallback_color") or asset_entry.get("base") or
               asset_entry.get("color"))
        text=str(value or "").strip()
        if text:
            return text
    if not isinstance(cfg, dict):
        return fallback_color
    colors=cfg.get("colors")
    if not isinstance(colors,(list,tuple)) or not colors:
        return fallback_color
    try:
        entry=colors[int(day_index) % len(colors)]
    except Exception:
        entry=colors[0]
    # Backward-compatible: allow {"base":"#..."} as well as a plain hex string.
    if isinstance(entry,dict):
        entry=entry.get("base") or entry.get("color")
    text=str(entry or "").strip()
    return text if text else fallback_color


def _day_capsule_accent_color(guide, day_index, fallback_color):
    """Resolve the visual accent for one day's capsule from Theme JSON.

    ``accent_color`` / ``border_color`` are preferred for UI accents.  If they are
    absent we reuse the configured fallback/recolor color, keeping concrete day
    palettes out of the renderer.
    """
    cfg = _theme_asset_value(guide, "day_capsule")
    asset_entry = _day_capsule_asset_entry(cfg, day_index)
    if isinstance(asset_entry, dict):
        value = asset_entry.get("accent_color") or asset_entry.get("border_color")
        text = str(value or "").strip()
        if text:
            return text
    return _day_capsule_color(cfg, asset_entry, day_index, fallback_color)


def _draw_true_center_text(draw, services, box, text, color, size, bold=True, y_offset=0):
    """Center by the actual glyph bbox instead of the font line box.

    The shared ``draw_center`` intentionally uses line-height metrics; for a tiny
    tier badge that can make Arabic numerals look optically low.  This local helper
    compensates for the glyph bbox while leaving shared rendering untouched.
    """
    x1, y1, x2, y2 = map(float, box)
    font = services.get_font(int(size), bool(bold))
    s = str(text or "")
    bb = draw.textbbox((0, 0), s, font=font)
    tw = bb[2] - bb[0]
    th = bb[3] - bb[1]
    tx = x1 + ((x2 - x1) - tw) / 2.0 - bb[0]
    ty = y1 + ((y2 - y1) - th) / 2.0 - bb[1] + float(y_offset)
    draw.text((tx, ty), s, font=font, fill=color)


def _trim_transparent_artwork(source, threshold=8, safety=0.025):
    """Crop transparent padding from AI icon artwork so the capsule fills its rail.

    AI exports often keep 8–15% transparent safe margins.  Keeping those margins
    *again* inside a renderer contain box makes the icon look much smaller than
    the vector fallback.  We crop only alpha-empty space and retain a tiny safety
    margin, so highlights/shadows are not clipped.
    """
    src=source.convert("RGBA")
    alpha=src.getchannel("A")
    # Treat near-transparent antialias pixels as empty for a stable bbox.
    mask=alpha.point(lambda v: 255 if v > int(threshold) else 0)
    bbox=mask.getbbox()
    if not bbox:
        return src
    x1,y1,x2,y2=bbox
    pad=max(1,int(round(max(x2-x1,y2-y1)*float(safety))))
    x1=max(0,x1-pad); y1=max(0,y1-pad); x2=min(src.width,x2+pad); y2=min(src.height,y2+pad)
    return src.crop((x1,y1,x2,y2))


def _draw_capsule_ground_shadow(base, box, shadow_cfg=None):
    """Draw only a soft contact shadow peeking out below the capsule.

    The shadow layer is intentionally taller than the destination icon box.  This
    lets the lower blurred edge remain visible *outside* the capsule artwork after
    the capsule is composited on top, instead of being completely hidden or
    turning into a large black backing disc.
    """
    x1, y1, x2, y2 = map(int, box)
    w=max(1,x2-x1); h=max(1,y2-y1)
    cfg=shadow_cfg if isinstance(shadow_cfg,dict) else {}
    try: width_ratio=max(0.28,min(0.82,float(cfg.get("width_ratio",0.52))))
    except Exception: width_ratio=0.52
    try: height_ratio=max(0.04,min(0.16,float(cfg.get("height_ratio",0.075))))
    except Exception: height_ratio=0.075
    try: center_y_ratio=max(0.90,min(1.08,float(cfg.get("center_y_ratio",0.985))))
    except Exception: center_y_ratio=0.985
    try: blur_ratio=max(0.008,min(0.08,float(cfg.get("blur_ratio",0.028))))
    except Exception: blur_ratio=0.028
    try: opacity=max(25,min(235,int(cfg.get("opacity",112))))
    except Exception: opacity=112
    try: spill_ratio=max(0.04,min(0.20,float(cfg.get("spill_ratio",0.11))))
    except Exception: spill_ratio=0.11

    spill=max(5,int(round(h*spill_ratio)))
    layer_h=h+spill*2
    layer=Image.new("RGBA",(w,layer_h),(0,0,0,0))
    ld=ImageDraw.Draw(layer,"RGBA")
    sw=max(3,int(round(w*width_ratio)))
    sh=max(3,int(round(h*height_ratio)))
    cx=w//2
    # cy is allowed to sit at / just below the original icon box bottom.
    cy=int(round(h*center_y_ratio))
    ld.ellipse((cx-sw//2,cy-sh//2,cx+sw//2,cy+sh//2),fill=(0,0,0,opacity))
    blur=max(1,int(round(min(w,h)*blur_ratio)))
    layer=layer.filter(ImageFilter.GaussianBlur(blur))
    base.alpha_composite(layer,(x1,y1))

def _draw_configured_day_capsule(base, draw, guide, services, box, fallback_color, day_index=0):
    """Draw one theme-configured per-day capsule asset, else a vector fallback.

    Preferred Theme JSON shape::

      "day_capsule": {
        "padding": 0.0,
        "trim_alpha": true,
        "items": [
          {
            "path": "assets/<capsule-file>.png",
            "scale": 1.0,
            "offset_x": 0.04,
            "offset_y": 0.0,
            "fallback_color": "#F04F45"
          }
        ]
      }

    ``offset_x`` / ``offset_y`` are fractions of the destination capsule box, so
    artwork-specific visual centering remains editable in Theme JSON and scales
    naturally between normal-day and D7 icon sizes.  Legacy single-master recolor
    settings remain supported for older theme configs.
    """
    x1,y1,x2,y2 = map(int, box)
    cfg = _theme_asset_value(guide, "day_capsule")
    asset_entry = _day_capsule_asset_entry(cfg, day_index)

    def _pick(key, default=None):
        if isinstance(asset_entry,dict) and key in asset_entry:
            return asset_entry.get(key)
        if isinstance(cfg,dict) and key in cfg:
            return cfg.get(key)
        return default

    path_value = str(_pick("path", "") or "").strip()
    recolor = bool(_pick("recolor", False))
    recolor_mode = str(_pick("recolor_mode", "neutral_full") or "neutral_full").strip().lower()
    trim_alpha = bool(_pick("trim_alpha", True))
    try:
        saturation_threshold = int(_pick("saturation_threshold", 34))
    except Exception:
        saturation_threshold = 34
    try:
        recolor_softness = int(_pick("recolor_softness", 30))
    except Exception:
        recolor_softness = 30
    try:
        pad = max(0.0, min(0.22, float(_pick("padding", 0.04))))
    except Exception:
        pad = 0.04
    try:
        asset_scale = max(0.55, min(1.35, float(_pick("scale", 1.0))))
    except Exception:
        asset_scale = 1.0
    try:
        offset_x = max(-0.45, min(0.45, float(_pick("offset_x", 0.0))))
    except Exception:
        offset_x = 0.0
    try:
        offset_y = max(-0.45, min(0.45, float(_pick("offset_y", 0.0))))
    except Exception:
        offset_y = 0.0

    target_color=_day_capsule_color(cfg,asset_entry,day_index,fallback_color)
    shadow_cfg = cfg.get("shadow") if isinstance(cfg,dict) else None
    p = None
    if path_value:
        try:
            p = services.resolve_path(guide.get("cfg") or {}, path_value)
        except Exception:
            p = None
    if p and Path(p).is_file():
        try:
            source=Image.open(p).convert("RGBA")
            if trim_alpha:
                source=_trim_transparent_artwork(source)
            # Optional transparent safety canvas for artwork whose decorative tabs /
            # ribbons touch the original PNG edge. This is theme-configured per item.
            try:
                safe_margin=max(0.0,min(0.18,float(_pick("safe_margin",0.0))))
            except Exception:
                safe_margin=0.0
            if safe_margin > 0:
                pad_px=max(1,int(round(max(source.size)*safe_margin)))
                padded=Image.new("RGBA",(source.width+pad_px*2,source.height+pad_px*2),(0,0,0,0))
                padded.alpha_composite(source,(pad_px,pad_px))
                source=padded
            if recolor:
                if recolor_mode in {"colored_half","colored_only","selective_color","selective"}:
                    source=_recolor_colored_half_capsule(
                        source,target_color,
                        saturation_threshold=saturation_threshold,
                        softness=recolor_softness,
                    )
                else:
                    source=_recolor_neutral_capsule(source,target_color)
            inset_x = int(round((x2-x1)*pad)); inset_y=int(round((y2-y1)*pad))
            tx1,ty1,tx2,ty2=x1+inset_x,y1+inset_y,x2-inset_x,y2-inset_y
            tw=max(1,tx2-tx1); th=max(1,ty2-ty1)
            sw,sh=source.size
            fit=min(tw/max(1,sw),th/max(1,sh))
            scale=fit*asset_scale
            rw=max(1,int(round(sw*scale))); rh=max(1,int(round(sh*scale)))
            layer=source.resize((rw,rh),Image.Resampling.LANCZOS)

            # Composite through a slot-sized layer so scale/offset tuning can never
            # leak artwork into the action text column.  Positive X/Y moves right/down.
            slot=Image.new("RGBA",(tw,th),(0,0,0,0))
            px=int(round((tw-rw)/2 + offset_x*tw))
            py=int(round((th-rh)/2 + offset_y*th))
            # PIL alpha_composite requires a non-negative destination. Crop the
            # source when tuning moves/scales it past a slot edge, preserving the
            # requested visual offset instead of silently falling back to vectors.
            sx1=max(0,-px); sy1=max(0,-py)
            dx=max(0,px); dy=max(0,py)
            cw=min(rw-sx1,tw-dx); ch=min(rh-sy1,th-dy)
            if cw > 0 and ch > 0:
                clipped=layer.crop((sx1,sy1,sx1+cw,sy1+ch))
                # Contact shadow follows the *actual visible artwork bounds*, not
                # the larger icon slot.  It therefore peeks out only below the
                # capsule even when an asset has unusual transparent margins.
                _draw_capsule_ground_shadow(
                    base, (tx1+dx,ty1+dy,tx1+dx+cw,ty1+dy+ch), shadow_cfg
                )
                slot.alpha_composite(clipped,(dx,dy))
            base.alpha_composite(slot,(tx1,ty1))
            return True
        except Exception:
            pass
    cx=(x1+x2)//2; cy=(y1+y2)//2; r=max(10,min(x2-x1,y2-y1)//2-3)
    _draw_capsule_ground_shadow(base,(cx-r,cy-r,cx+r,cy+r),shadow_cfg)
    _draw_refined_capsule(draw,cx,cy,r,target_color)
    return False


def _metric_groups(services, info):
    """Compact repeated 剩余/期望 prefixes while preserving all source values."""
    groups={"remaining":[],"expected":[],"other":[]}
    for item in list(info.get("metric_items") or [])[:4]:
        label=clean(services,item.get("label"),"")
        value=clean(services,item.get("value"),"")
        if not (label or value):
            continue
        if "剩余" in label:
            short=label.replace("剩余","").strip() or "资源"
            groups["remaining"].append((short+(" "+value if value else "")).strip())
        elif "期望" in label:
            short=label.replace("期望","").strip() or "资源"
            groups["expected"].append((short+(" "+value if value else "")).strip())
        else:
            groups["other"].append((label+(" "+value if value else "")).strip())
    return groups


def _draw_day_metrics_emphasis(base, draw, guide, services, info, box, colors):
    """Icon-first day metrics: actual configured item icon + large number only.

    On a phone, repeated labels such as ``剩余制作券`` / ``期望普通卷轴``
    become unreadable before the numbers do.  The activity JSON already maps all
    four semantic slots to stable icons, so this component intentionally removes
    the repeated words and lets icon + number carry the status.
    """
    x1,y1,x2,y2=map(int,box)
    items=list(info.get("metric_items") or [])[:4]
    if not items:
        return
    cfg=guide.get("cfg") or {}
    gap=6
    n=len(items)
    cw=(x2-x1-gap*max(0,n-1))/max(1,n)
    h=max(1,y2-y1)
    icon_size=max(18,min(25,h-5))
    for i,item in enumerate(items):
        a=int(round(x1+i*(cw+gap))); b=int(round(a+cw))
        role=str(item.get("role") or "")
        if role == "expected":
            fill="#2B2819"; border="#75642D"; fg=colors["screen_text"]
        else:
            fill="#16252C"; border="#2B5261"; fg="#D9F3FF"
        draw.rounded_rectangle((a,y1,b,y2),radius=6,fill=fill,outline=border,width=1)
        icon=None
        try:
            icon=services.config_day_icon(cfg,item)
        except Exception:
            icon=None
        tx=a+7
        if icon and Path(icon).exists():
            iy=int(round(y1+(h-icon_size)/2))
            services.draw_image_contain(base,Path(icon),(a+6,iy,a+6+icon_size,iy+icon_size))
            tx=a+11+icon_size
        else:
            # Geometry-only fallback avoids missing-font squares while keeping role color.
            cy=(y1+y2)//2; rr=max(5,icon_size//3)
            draw.ellipse((a+8,cy-rr,a+8+2*rr,cy+rr),fill=fg,outline=border,width=1)
            tx=a+15+2*rr
        value=clean(services,item.get("value"),"—")
        services.draw_center(draw,(tx,y1+1,b-4,y2-1),value,fg,
                             max_size=16,min_size=12,bold=True,max_lines=1)


def _draw_warning_icon(draw, cx, cy, size, color):
    """Vector warning symbol avoids missing Unicode glyph / tofu-square issues."""
    h=int(size); w=int(round(size*1.08))
    pts=[(cx,cy-h//2),(cx-w//2,cy+h//2),(cx+w//2,cy+h//2)]
    draw.polygon(pts,fill=None,outline=color)
    # Pillow polygon outline has no width control on older versions: reinforce with lines.
    draw.line((pts[0],pts[1],pts[2],pts[0]),fill=color,width=2,joint="curve")
    draw.line((cx,cy-h//5,cx,cy+h//7),fill=color,width=3)
    draw.ellipse((cx-2,cy+h//3-2,cx+2,cy+h//3+2),fill=color)


def _draw_gacha_footer(base, draw, guide, services, y1, h, colors):
    """Centered footer as one unit; group avatar receives a visible framed treatment."""
    w=base.width; y2=min(base.height,int(y1+h))
    draw.rectangle((0,y1,w,y2),fill=colors["background"])
    draw.line((0,y1,w,y1),fill="#C9BEB2",width=2)
    text=clean(services,guide.get("watermark"),"")
    cfg=guide.get("cfg") or {}
    icon_path=None
    raw_icon=cfg.get("watermark_group_icon")
    if raw_icon:
        try:
            p=services.resolve_path(cfg,raw_icon)
            if p and Path(p).is_file(): icon_path=Path(p)
        except Exception:
            icon_path=None
    # Fit the complete avatar+text block and then center the block, not only the text box.
    size=min(46,max(34,y2-y1-16)) if icon_path else 0
    gap=12 if icon_path and text else 0
    chosen=17
    font=services.get_font(chosen,False)
    max_text_w=w-84-size-gap
    while chosen>14:
        bb=draw.textbbox((0,0),text or " ",font=font)
        if bb[2]-bb[0] <= max_text_w: break
        chosen-=1; font=services.get_font(chosen,False)
    bb=draw.textbbox((0,0),text or " ",font=font)
    tw=max(0,bb[2]-bb[0]); th=max(1,bb[3]-bb[1])
    total=size+gap+tw
    sx=int(round((w-total)/2))
    if icon_path:
        iy=int(round(y1+(y2-y1-size)/2))
        # Deliberately square group-avatar frame; QQ group avatars are square assets.
        draw.rectangle((sx-5,iy-5,sx+size+5,iy+size+5),fill="#FFF9EF",outline=colors["machine_dark"],width=3)
        draw.rectangle((sx-2,iy-2,sx+size+2,iy+size+2),outline=colors["machine"],width=2)
        services.draw_image_contain(base,icon_path,(sx,iy,sx+size,iy+size))
    if text:
        tx=sx+size+gap
        ty=int(round(y1+(y2-y1-th)/2-bb[1]))
        draw.text((tx,ty),text,font=font,fill=colors["muted"])

def _draw_day_card(base, draw, guide, services, tools, cfg, colors, info, idx, box, d7=False):
    x1,y1,x2,y2 = map(int, box)
    special = bool(special_text(services,info))
    # Special days stay on the normal card fill; their capsule color alone marks the border.
    fill = "#3B292A" if d7 else "#30373C"
    capsule_accent = _day_capsule_accent_color(guide, idx, colors["accent"])
    border = capsule_accent if (d7 or special) else "#69747B"
    if d7:
        border_width = int(cfg.get("d7_border_width", 4) or 4)
    elif special:
        border_width = int(cfg.get("special_border_width", 3) or 3)
    else:
        border_width = int(cfg.get("day_border_width", 2) or 2)
    draw.rounded_rectangle((x1,y1,x2,y2), radius=14, fill=fill, outline=border, width=border_width)

    day = clean(services,info.get("day"),f"D{idx+1}")
    target = target_text(services,info)
    marker = special_text(services,info)

    # Capsule icon lives in a dedicated left rail and is vertically centred.
    # The day text stays in the header; the capsule itself is purely visual.
    badge_size = int(cfg.get("day_capsule_size",86) or 86) if not d7 else int(cfg.get("day_capsule_d7_size",100) or 100)
    badge_r = max(30,badge_size//2)
    badge_cx = x1 + (60 if not d7 else 72)
    content_bottom = y2 - 43
    badge_cy = int(round((y1 + 8 + content_bottom) / 2))
    _draw_configured_day_capsule(base, draw, guide, services,
                                 (badge_cx-badge_r,badge_cy-badge_r,badge_cx+badge_r,badge_cy+badge_r),
                                 colors["primary"], day_index=idx)

    # Day header and authentic target tier.
    header_x = x1 + (130 if not d7 else 184)
    header_text = (day + "｜FINAL 最终出蛋") if d7 else day
    services.draw_left(draw,(header_x,y1+10,x2-108,y1+42),header_text,colors["light"],
                       max_size=19,min_size=14,bold=True,max_lines=1,valign="center")
    # Compact target tier: keep the badge small, but make all three glyphs readable.
    tier_w = int(cfg.get("tier_badge_width", 74) or 74)
    tier_h = int(cfg.get("tier_badge_height", 32) or 32)
    tier_right = int(cfg.get("tier_badge_right", 12) or 12)
    tier_top = int(cfg.get("tier_badge_top", 9) or 9)
    tier_box=(x2-tier_right-tier_w,y1+tier_top,x2-tier_right,y1+tier_top+tier_h)
    draw.rounded_rectangle(tier_box, radius=max(7,tier_h//4), fill=colors["accent"], outline="#FFF4C5", width=2)
    level=target_level_number(services,info)
    if str(level).isdigit():
        num_size = int(cfg.get("tier_number_font_size", 27) or 27)
        affix_size = int(cfg.get("tier_affix_font_size", 12) or 12)
        num_y = int(cfg.get("tier_number_y_offset", -1) or 0)
        affix_y = int(cfg.get("tier_affix_y_offset", -1) or 0)
        f_aff=services.get_font(affix_size,True)
        f_num=services.get_font(num_size,True)
        parts=[("第",f_aff,affix_y),(str(level),f_num,num_y),("档",f_aff,affix_y)]
        gap=max(1,int(cfg.get("tier_text_gap",1) or 1))
        widths=[]
        for text,font,_ in parts:
            bb=draw.textbbox((0,0),text,font=font)
            widths.append(bb[2]-bb[0])
        total=sum(widths)+gap*2
        cursor=tier_box[0]+(tier_w-total)/2.0
        for (text,font,yoff),pw in zip(parts,widths):
            bb=draw.textbbox((0,0),text,font=font)
            th=bb[3]-bb[1]
            ty=tier_box[1]+(tier_h-th)/2.0-bb[1]+yoff
            draw.text((cursor-bb[0],ty),text,font=font,fill=colors["machine_dark"])
            cursor += pw + gap
    else:
        _draw_true_center_text(draw, services,
                               (tier_box[0]+4,tier_box[1],tier_box[2]-4,tier_box[3]),
                               target, colors["machine_dark"], 13, True, -1)

    # No special-day label: the per-day capsule-colored border is the only marker.
    action_top = y1 + 48

    action = clean(services,info.get("action"),"按计划执行")
    metric = day_metric_text(services,info,max_items=4)

    if d7:
        # Full-width final day: capsule/identity on left,正文 on right.
        divider_x = x1 + 176
        draw.line((divider_x,y1+48,divider_x,y2-45),fill="#685E58",width=2)
        services.draw_left(draw,(divider_x+18,y1+47,x2-18,y2-49),action,colors["light"],
                           max_size=int(cfg.get("day_action_font_size",24) or 24),
                           min_size=int(cfg.get("day_action_min_font_size",17) or 17),
                           bold=True,max_lines=5,line_gap=2,valign="center")
    else:
        # Mobile readability first: the majority of each card is text.
        services.draw_left(draw,(header_x,action_top,x2-14,y2-47),action,"#E1E6E9",
                           max_size=int(cfg.get("day_action_font_size",24) or 24),
                           min_size=int(cfg.get("day_action_min_font_size",17) or 17),
                           bold=True,max_lines=4,line_gap=1,valign="center")

    # Remaining / expected metrics are decision-critical: give them distinct high-contrast pills.
    draw.line((x1+12,y2-42,x2-12,y2-42),fill="#59646B",width=1)
    _draw_day_metrics_emphasis(base,draw,guide,services,info,(x1+12,y2-38,x2-12,y2-7),colors)


def _reward_tree_gacha(guide, services):
    raw=guide.get("reward_items") or []
    if not raw:
        return None
    try:
        units=services.build_reward_display_units(raw)
    except Exception:
        units=[]
    if not units:
        return None
    if len(units)==1:
        return units[0]
    return {"type":"bundle","items":units,"_visual_root":True}


def _reward_leaf_count_gacha(node):
    if not isinstance(node,dict):
        return 0
    typ=node.get("type","item")
    if typ=="item":
        return 1
    children=node.get("items") if typ=="bundle" else node.get("options")
    return sum(_reward_leaf_count_gacha(x) for x in (children or []))


def _reward_unit_weight_gacha(node):
    if not isinstance(node,dict):
        return 1.0
    typ=node.get("type","item")
    if typ=="choice":
        n=max(2,len(node.get("options") or []))
        return 1.62 if n==2 else min(2.35,1.0+0.46*n)
    if typ=="bundle":
        leaves=max(1,_reward_leaf_count_gacha(node))
        return min(2.15,0.86+0.54*leaves)
    return 1.0


def _reward_display_cfg_gacha(guide):
    theme=guide.get("theme_config") if isinstance(guide.get("theme_config"),dict) else {}
    cfg=theme.get("reward_display") if isinstance(theme.get("reward_display"),dict) else {}
    return cfg


def _reward_palette_gacha(guide, colors):
    cfg=_reward_display_cfg_gacha(guide)
    raw=cfg.get("palette")
    if isinstance(raw,(list,tuple)) and raw:
        vals=[str(v) for v in raw if str(v).strip()]
        if vals:
            return vals
    return ["#E95A68","#F2B632","#5A84C9","#58B98A","#A45BE5","#F29A32","#EA6692"]

def _reward_quality_palette_gacha(guide, services, node_or_item):
    rr=RewardItemRenderer(services,guide)
    item=node_or_item
    if isinstance(node_or_item,dict) and node_or_item.get("type")!="item":
        leaf=_reward_leaf_items_gacha(node_or_item,1)
        item=leaf[0] if leaf else None
    resolved=rr.resolve(item or {}) if isinstance(item,dict) else {}
    q=str(resolved.get("quality") or "").strip().lower()
    if q=="chaoyue":
        return ("#66D0FF","#A65BFF", "#78DAFF")
    if q=="red":
        return ("#FF645E","#D9364E", "#FF666B")
    if q=="purple":
        return ("#A86DFF","#CF54F2", "#D783FF")
    if q=="pink":
        return ("#FF7AB8","#F44A86", "#FF8ABD")
    return ("#66D0FF","#A65BFF", "#78DAFF")


def _reward_accent_gacha(guide, colors, index, choice=False):
    cfg=_reward_display_cfg_gacha(guide)
    if choice:
        return str(cfg.get("choice_accent") or colors["accent"])
    pal=_reward_palette_gacha(guide,colors)
    return pal[index % len(pal)]


def _reward_leaf_items_gacha(node, limit=2):
    out=[]
    queue=[node]
    while queue and len(out)<limit:
        cur=queue.pop(0)
        if not isinstance(cur,dict):
            continue
        typ=cur.get("type","item")
        if typ=="item":
            out.append(cur)
        else:
            queue[0:0]=list(cur.get("items") or cur.get("options") or [])
    return out


def _draw_reward_icon_big_gacha(base, draw, guide, services, colors, item, box, *, name_box=None, qty_box=None, glow=None):
    """Large reward artwork with optional floating glow and separate caption boxes."""
    x1,y1,x2,y2=map(int,box)
    rr=RewardItemRenderer(services,guide)
    if glow:
        # Soft backlight is intentionally subtle; the actual reward icon remains the hero.
        layer=Image.new("RGBA",base.size,(0,0,0,0))
        ld=ImageDraw.Draw(layer,"RGBA")
        gx=(x1+x2)//2; gy=(y1+y2)//2
        rw=max(10,int((x2-x1)*0.47)); rh=max(7,int((y2-y1)*0.38))
        rgb=_hex_rgb(glow)
        ld.ellipse((gx-rw,gy-rh,gx+rw,gy+rh),fill=(rgb[0],rgb[1],rgb[2],58))
        layer=layer.filter(ImageFilter.GaussianBlur(max(3,int((y2-y1)*0.10))))
        base.alpha_composite(layer)
    resolved=rr.draw_icon(base,item,(x1,y1,x2,y2))
    icon_path=resolved.get("icon_path")
    frame_path=resolved.get("frame_path")
    if not ((icon_path and Path(icon_path).exists()) or (frame_path and Path(frame_path).exists())):
        draw.rounded_rectangle((x1,y1,x2,y2),radius=8,outline=colors["accent"],width=2)
        services.draw_center(draw,(x1,y1,x2,y2),"?",colors["accent"],max_size=24,min_size=16,bold=True,max_lines=1)
    qty=clean(services,item.get("qty"),"")
    name=clean(services,item.get("name"),"物品")
    if qty_box and qty:
        services.draw_center(draw,qty_box,"×"+qty,colors["screen_text"],max_size=12,min_size=9,bold=True,max_lines=1)
    if name_box:
        services.draw_center(draw,name_box,name,colors["light"],max_size=10,min_size=8,bold=True,max_lines=2,line_gap=0)


def _reward_units_gacha(guide, services, max_items=6):
    tree=_reward_tree_gacha(guide,services)
    if not tree:
        return []
    if isinstance(tree,dict) and tree.get("type")=="bundle" and tree.get("_visual_root"):
        units=list(tree.get("items") or [])
    else:
        units=[tree]
    return units[:max_items] if max_items else units


def _layout_reward_units_gacha(units, box):
    """Allocate top-level reward units across the entire tray, never a centered cluster."""
    x1,y1,x2,y2=map(int,box)
    if not units:
        return []
    side_pad=2
    gap=12 if len(units)<=4 else 8
    weights=[_reward_unit_weight_gacha(u) for u in units]
    total=max(0.1,sum(weights))
    usable=max(1,(x2-x1)-2*side_pad-gap*max(0,len(units)-1))
    out=[]; cursor=float(x1+side_pad)
    for i,(unit,weight) in enumerate(zip(units,weights)):
        b=x2-side_pad if i==len(units)-1 else int(round(cursor+usable*(weight/total)))
        a=int(round(cursor))
        out.append((unit,(a,y1,b,y2),i))
        cursor=float(b+gap)
    return out


# ---------------------------------------------------------------------------
# Reward style A: capsule pedestals / floating prizes
# ---------------------------------------------------------------------------
def _draw_reward_qty_text_gacha(services, draw, box, text, color):
    services.draw_center(draw,box,text,color,max_size=20,min_size=12,bold=True,max_lines=1)


def _draw_reward_name_bar_gacha(draw, services, box, name, outline):
    x1,y1,x2,y2=map(int,box)
    draw.rounded_rectangle((x1,y1,x2,y2),radius=14,fill="#1E2830",outline=_shade_hex(outline,1.05),width=2)
    services.draw_center(draw,(x1+6,y1,x2-6,y2),name,"#FFFDF8",max_size=11,min_size=7,bold=True,max_lines=1)


def _draw_reward_role_pill_gacha(base, draw, services, box, title, c1, c2):
    x1,y1,x2,y2=map(int,box)
    tmp=Image.new("RGBA",base.size,(0,0,0,0))
    td=ImageDraw.Draw(tmp)
    w=max(1,x2-x1); h=max(1,y2-y1)
    for xx in range(w):
        t=0 if w<=1 else xx/float(w-1)
        rgb=_mix_hex(c1,c2,t)
        td.line((x1+xx,y1,x1+xx,y2),fill=rgb,width=1)
    mask=Image.new("L",(w,h),0)
    md=ImageDraw.Draw(mask)
    md.rounded_rectangle((0,0,w-1,h-1),radius=h//2,fill=255)
    crop=tmp.crop((x1,y1,x2,y2))
    crop.putalpha(mask)
    base.alpha_composite(crop,(x1,y1))
    draw.rounded_rectangle((x1,y1,x2,y2),radius=h//2,outline=_shade_hex(c1,1.15),width=2)
    services.draw_center(draw,(x1+3,y1,x2-3,y2),title,"#FFFDF8",max_size=13,min_size=9,bold=True,max_lines=1)


def _draw_reward_item_shadow_gacha(draw, box):
    # v16: intentionally no icon shadow for a cleaner reward zone.
    return

def _draw_reward_a_tray_gacha(base, draw, box, c1, c2):
    # v16: trays removed; keep helper as a no-op for compatibility.
    return

def _draw_reward_pedestal_single_gacha(base, draw, guide, services, colors, item, box, accent):
    x1,y1,x2,y2=map(int,box)
    c1,c2,_qty_color=_reward_quality_palette_gacha(guide,services,item)
    cx=(x1+x2)//2
    # quality card shell
    draw.rounded_rectangle((x1+10,y1+8,x2-10,y2-6),radius=18,fill="#171F26",outline=_mix_hex(c1,c2,0.4),width=2)
    icon=(cx-46,y1+22,cx+46,y1+116)
    _draw_reward_icon_big_gacha(base,draw,guide,services,colors,item,icon,glow=None)
    qty=clean(services,item.get("qty"),"")
    if qty:
        services.draw_center(draw,(cx-34,y1+122,cx+34,y1+146),"×"+qty,"#FFFFFF",max_size=17,min_size=11,bold=True,max_lines=1)
    _draw_reward_name_bar_gacha(draw,services,(cx-74,y1+150,cx+74,y1+178),clean(services,item.get("name"),"物品"),c1)

def _draw_reward_pedestal_choice_gacha(base, draw, guide, services, colors, node, box, accent):
    x1,y1,x2,y2=map(int,box)
    opts=list(node.get("options") or [])[:2]
    if not opts:
        return
    c1,c2,_qty_color=_reward_quality_palette_gacha(guide,services,opts[0])
    # one shared card for A/B
    draw.rounded_rectangle((x1+10,y1+8,x2-10,y2-6),radius=18,fill="#171F26",outline=_mix_hex(c1,c2,0.4),width=2)
    left=x1+int((x2-x1)*0.27)
    right=x1+int((x2-x1)*0.73)
    centers=[left,right]
    for i,opt in enumerate(opts):
        leaf=_reward_leaf_items_gacha(opt,1)
        if not leaf:
            continue
        item=leaf[0]
        cx=centers[i]
        icon=(cx-44,y1+26,cx+44,y1+110)
        _draw_reward_icon_big_gacha(base,draw,guide,services,colors,item,icon,glow=None)
        qty=clean(services,item.get("qty"),"")
        if qty:
            services.draw_center(draw,(cx-34,y1+118,cx+34,y1+142),"×"+qty,"#FFFFFF",max_size=17,min_size=11,bold=True,max_lines=1)
        _draw_reward_name_bar_gacha(draw,services,(cx-78,y1+150,cx+78,y1+178),clean(services,item.get("name"),"物品"),c1)
    cx=(x1+x2)//2; cy=y1+76
    draw.line((cx,y1+42,cx,y2-20),fill="#44515B",width=1)
    draw.ellipse((cx-24,cy-24,cx+24,cy+24),fill="#27313A",outline="#F0CA5B",width=3)
    draw.ellipse((cx-16,cy-16,cx+16,cy+16),fill="#151B21",outline="#FFF3B4",width=1)
    services.draw_center(draw,(cx-24,cy-24,cx+24,cy+24),"或",colors["screen_text"],max_size=18,min_size=10,bold=True,max_lines=1)

def _draw_reward_style_pedestal_gacha(base, draw, guide, services, tools, box, colors, units):
    layouts=_layout_reward_units_gacha(units,box)
    for unit,ubox,index in layouts:
        typ=unit.get("type","item") if isinstance(unit,dict) else "item"
        accent=_reward_accent_gacha(guide,colors,index,choice=(typ=="choice"))
        if typ=="choice":
            _draw_reward_pedestal_choice_gacha(base,draw,guide,services,colors,unit,ubox,accent)
        else:
            leaves=_reward_leaf_items_gacha(unit,1)
            if leaves:
                _draw_reward_pedestal_single_gacha(base,draw,guide,services,colors,dict(leaves[0]),ubox,accent)

# ---------------------------------------------------------------------------
# Reward style B: illuminated vending/prize windows
# ---------------------------------------------------------------------------
def _draw_prize_window_shell_gacha(draw, box, accent, choice=False):
    x1,y1,x2,y2=map(int,box); w=x2-x1
    # machine bezel
    draw.rounded_rectangle((x1+1,y1+1,x2-1,y2-1),radius=12,fill="#0D1215",outline="#7A868D",width=2)
    draw.rounded_rectangle((x1+5,y1+5,x2-5,y2-7),radius=9,fill="#172026",outline=_shade_hex(accent,0.78),width=3)
    draw.rounded_rectangle((x1+9,y1+9,x2-9,y2-26),radius=7,fill="#090D10",outline=accent,width=1)
    # marquee indicator lights
    for lx in (x1+15,x2-15):
        draw.ellipse((lx-3,y1+11,lx+3,y1+17),fill="#F8E69A",outline="#493B17",width=1)
    # bottom LCD strip
    draw.rounded_rectangle((x1+8,y2-25,x2-8,y2-7),radius=5,fill="#121A1F",outline="#34434B",width=1)
    if choice:
        mid=(x1+x2)//2
        draw.line((mid,y1+26,mid,y2-29),fill="#556169",width=2)
    return (x1+10,y1+21,x2-10,y2-29)


def _draw_reward_style_window_gacha(base, draw, guide, services, tools, box, colors, units):
    layouts=_layout_reward_units_gacha(units,box)
    for unit,ubox,index in layouts:
        typ=unit.get("type","item") if isinstance(unit,dict) else "item"
        choice=(typ=="choice")
        accent=_reward_accent_gacha(guide,colors,index,choice=choice)
        x1,y1,x2,y2=ubox
        inner=_draw_prize_window_shell_gacha(draw,ubox,accent,choice=choice)
        if choice:
            opts=list(unit.get("options") or [])[:2]
            label="二选一" if len(opts)==2 else f"{len(opts)}选1"
            label_w=min(76,max(60,(x2-x1)//3))
            draw.rounded_rectangle(((x1+x2)//2-label_w//2,y1+5,(x1+x2)//2+label_w//2,y1+22),radius=7,fill=accent,outline="#FFF2B0",width=1)
            services.draw_center(draw,((x1+x2)//2-label_w//2+3,y1+5,(x1+x2)//2+label_w//2-3,y1+22),label,"#182026",max_size=11,min_size=9,bold=True,max_lines=1)
            ix1,iy1,ix2,iy2=inner; mid=(ix1+ix2)//2
            for i,opt in enumerate(opts):
                leaf=_reward_leaf_items_gacha(opt,1)
                if not leaf: continue
                a=ix1 if i==0 else mid+4; b=mid-4 if i==0 else ix2
                size=max(48,min(68,b-a-8,iy2-iy1))
                cx=(a+b)//2; yy=iy1+max(0,(iy2-iy1-size)//2)
                _draw_reward_icon_big_gacha(base,draw,guide,services,colors,leaf[0],(cx-size//2,yy,cx+size//2,yy+size),glow=accent)
            services.draw_center(draw,(mid-13,(iy1+iy2)//2-12,mid+13,(iy1+iy2)//2+12),"或",colors["screen_text"],max_size=10,min_size=8,bold=True,max_lines=1)
            names=[]
            for opt in opts:
                leaf=_reward_leaf_items_gacha(opt,1)
                if leaf: names.append(clean(services,leaf[0].get("name"),"物品"))
            services.draw_center(draw,(x1+9,y2-24,x2-9,y2-8)," / ".join(names),colors["light"],max_size=8,min_size=7,bold=True,max_lines=1)
        else:
            leaf=_reward_leaf_items_gacha(unit,1)
            if not leaf: continue
            item=leaf[0]; ix1,iy1,ix2,iy2=inner
            size=max(52,min(74,ix2-ix1,iy2-iy1+5))
            cx=(ix1+ix2)//2; yy=iy1+max(0,(iy2-iy1-size)//2)
            _draw_reward_icon_big_gacha(base,draw,guide,services,colors,item,(cx-size//2,yy,cx+size//2,yy+size),glow=accent)
            qty=clean(services,item.get("qty"),"")
            cap=("×"+qty+"  " if qty else "")+clean(services,item.get("name"),"物品")
            services.draw_center(draw,(x1+9,y2-24,x2-9,y2-8),cap,colors["light"],max_size=9,min_size=7,bold=True,max_lines=1)


# ---------------------------------------------------------------------------
# Reward style C: acrylic gacha domes / mini prize chambers
# ---------------------------------------------------------------------------
def _draw_acrylic_dome_gacha(base, box, accent, choice=False):
    x1,y1,x2,y2=map(int,box); w=x2-x1; h=y2-y1
    overlay=Image.new("RGBA",base.size,(0,0,0,0)); od=ImageDraw.Draw(overlay,"RGBA")
    base_y=y2-30
    # transparent dome body
    dome=(x1+4,y1+5,x2-4,base_y+17)
    rgb=_hex_rgb(accent)
    od.rounded_rectangle(dome,radius=min(22,max(12,w//6)),fill=(125,155,170,30),outline=(205,230,240,160),width=2)
    # colored glass tint near the lower edge
    od.rounded_rectangle((x1+7,base_y-6,x2-7,base_y+12),radius=9,fill=(rgb[0],rgb[1],rgb[2],60))
    # glass gleam
    od.arc((x1+10,y1+9,x2-10,base_y+10),190,286,fill=(255,255,255,170),width=2)
    overlay=overlay.filter(ImageFilter.GaussianBlur(0.25))
    base.alpha_composite(overlay)
    d=ImageDraw.Draw(base)
    # machine base + indicator
    d.ellipse((x1+9,base_y+20,x2-7,y2),fill="#06090B")
    d.rounded_rectangle((x1+3,base_y+5,x2-3,y2-5),radius=10,fill="#273137",outline="#86939B",width=2)
    d.rounded_rectangle((x1+8,base_y+7,x2-8,base_y+18),radius=6,fill=_shade_hex(accent,0.62),outline=accent,width=1)
    if choice:
        mid=(x1+x2)//2
        d.ellipse((mid-5,base_y+9,mid+5,base_y+19),fill="#F2C75A",outline="#5C4518",width=1)
    return (x1+9,y1+15,x2-9,base_y+2), base_y


def _draw_reward_style_dome_gacha(base, draw, guide, services, tools, box, colors, units):
    for unit,ubox,index in _layout_reward_units_gacha(units,box):
        typ=unit.get("type","item") if isinstance(unit,dict) else "item"
        choice=(typ=="choice")
        accent=_reward_accent_gacha(guide,colors,index,choice=choice)
        x1,y1,x2,y2=ubox
        inner,base_y=_draw_acrylic_dome_gacha(base,ubox,accent,choice=choice)
        if choice:
            opts=list(unit.get("options") or [])[:2]
            label="二选一" if len(opts)==2 else f"{len(opts)}选1"
            lw=min(74,max(58,(x2-x1)//3))
            draw.rounded_rectangle(((x1+x2)//2-lw//2,y1+1,(x1+x2)//2+lw//2,y1+19),radius=8,fill="#273137",outline=accent,width=2)
            services.draw_center(draw,((x1+x2)//2-lw//2+3,y1+1,(x1+x2)//2+lw//2-3,y1+19),label,colors["screen_text"],max_size=11,min_size=9,bold=True,max_lines=1)
            ix1,iy1,ix2,iy2=inner; mid=(ix1+ix2)//2
            for i,opt in enumerate(opts):
                leaf=_reward_leaf_items_gacha(opt,1)
                if not leaf: continue
                a=ix1 if i==0 else mid+5; b=mid-5 if i==0 else ix2
                size=max(48,min(66,b-a-4,iy2-iy1+7))
                cx=(a+b)//2; yy=iy1+max(0,(iy2-iy1-size)//2)
                _draw_reward_icon_big_gacha(base,draw,guide,services,colors,leaf[0],(cx-size//2,yy,cx+size//2,yy+size),glow=accent)
            services.draw_center(draw,(mid-12,(iy1+iy2)//2-11,mid+12,(iy1+iy2)//2+11),"或",colors["light"],max_size=10,min_size=8,bold=True,max_lines=1)
            services.draw_center(draw,(x1+5,base_y+7,x2-5,y2-5),"二选一奖励",colors["light"],max_size=9,min_size=7,bold=True,max_lines=1)
        else:
            leaf=_reward_leaf_items_gacha(unit,1)
            if not leaf: continue
            item=leaf[0]; ix1,iy1,ix2,iy2=inner
            size=max(54,min(76,ix2-ix1,iy2-iy1+9))
            cx=(ix1+ix2)//2; yy=iy1+max(0,(iy2-iy1-size)//2)
            _draw_reward_icon_big_gacha(base,draw,guide,services,colors,item,(cx-size//2,yy,cx+size//2,yy+size),glow=accent)
            qty=clean(services,item.get("qty"),"")
            cap=("×"+qty+"  " if qty else "")+clean(services,item.get("name"),"物品")
            services.draw_center(draw,(x1+5,base_y+7,x2-5,y2-5),cap,colors["light"],max_size=9,min_size=7,bold=True,max_lines=1)


# ---------------------------------------------------------------------------
# Reward style D: illuminated prize rings / jackpot selector
# ---------------------------------------------------------------------------
def _draw_ring_reward_single_gacha(base, draw, guide, services, colors, item, box, accent):
    x1,y1,x2,y2=map(int,box); w=x2-x1; h=y2-y1
    strip_h=23
    ring_size=max(58,min(82,w-10,h-strip_h-2))
    cx=(x1+x2)//2; cy=y1+max(ring_size//2+2,(h-strip_h)//2)
    # compact floor shadow and double illuminated ring
    draw.ellipse((cx-ring_size//2+7,cy+ring_size//2-8,cx+ring_size//2-7,cy+ring_size//2+4),fill="#070A0C")
    draw.ellipse((cx-ring_size//2,cy-ring_size//2,cx+ring_size//2,cy+ring_size//2),fill="#11181C",outline=_shade_hex(accent,0.58),width=4)
    draw.ellipse((cx-ring_size//2+5,cy-ring_size//2+5,cx+ring_size//2-5,cy+ring_size//2-5),outline=accent,width=3)
    # three tiny marquee lamps sell the arcade/gacha feel
    for angx in (-1,0,1):
        lx=cx+angx*15
        draw.ellipse((lx-2,y1+3,lx+2,y1+7),fill="#FFF1A8",outline=_shade_hex(accent,0.55),width=1)
    icon_size=max(46,ring_size-18)
    _draw_reward_icon_big_gacha(base,draw,guide,services,colors,item,(cx-icon_size//2,cy-icon_size//2,cx+icon_size//2,cy+icon_size//2),glow=accent)
    draw.rounded_rectangle((x1+3,y2-strip_h,x2-3,y2-3),radius=7,fill="#151D22",outline=_shade_hex(accent,0.72),width=2)
    qty=clean(services,item.get("qty"),"")
    cap=("×"+qty+"  " if qty else "")+clean(services,item.get("name"),"物品")
    services.draw_center(draw,(x1+6,y2-strip_h+1,x2-6,y2-4),cap,colors["light"],max_size=9,min_size=7,bold=True,max_lines=1)


def _draw_ring_reward_choice_gacha(base, draw, guide, services, colors, node, box, accent):
    x1,y1,x2,y2=map(int,box); w=x2-x1; h=y2-y1
    opts=list(node.get("options") or [])[:2]
    label="二选一" if len(opts)==2 else f"{len(opts)}选1"
    draw.rounded_rectangle((x1+2,y1+1,x2-2,y2-3),radius=12,fill="#11171B",outline=_shade_hex(accent,0.62),width=2)
    lw=min(78,max(62,w//3))
    draw.rounded_rectangle(((x1+x2)//2-lw//2,y1+2,(x1+x2)//2+lw//2,y1+20),radius=8,fill=accent,outline="#FFF2B0",width=1)
    services.draw_center(draw,((x1+x2)//2-lw//2+3,y1+2,(x1+x2)//2+lw//2-3,y1+20),label,"#172026",max_size=11,min_size=9,bold=True,max_lines=1)
    strip_h=22; inner_y1=y1+20; inner_y2=y2-strip_h-2
    mid=(x1+x2)//2
    for i,opt in enumerate(opts):
        leaf=_reward_leaf_items_gacha(opt,1)
        if not leaf: continue
        a=x1+5 if i==0 else mid+6; b=mid-6 if i==0 else x2-5
        ring_size=max(50,min(66,b-a-4,inner_y2-inner_y1))
        cx=(a+b)//2; cy=inner_y1+(inner_y2-inner_y1)//2+2
        draw.ellipse((cx-ring_size//2,cy-ring_size//2,cx+ring_size//2,cy+ring_size//2),fill="#0B1013",outline=_shade_hex(accent,0.65),width=3)
        draw.ellipse((cx-ring_size//2+4,cy-ring_size//2+4,cx+ring_size//2-4,cy+ring_size//2-4),outline=accent,width=2)
        icon_size=max(42,ring_size-14)
        _draw_reward_icon_big_gacha(base,draw,guide,services,colors,leaf[0],(cx-icon_size//2,cy-icon_size//2,cx+icon_size//2,cy+icon_size//2),glow=accent)
    cy=(inner_y1+inner_y2)//2
    draw.ellipse((mid-12,cy-12,mid+12,cy+12),fill="#2A3237",outline=accent,width=2)
    services.draw_center(draw,(mid-12,cy-12,mid+12,cy+12),"或",colors["screen_text"],max_size=10,min_size=8,bold=True,max_lines=1)
    names=[]
    for opt in opts:
        leaf=_reward_leaf_items_gacha(opt,1)
        if leaf: names.append(clean(services,leaf[0].get("name"),"物品"))
    draw.rounded_rectangle((x1+6,y2-strip_h,x2-6,y2-4),radius=6,fill="#151D22",outline=_shade_hex(accent,0.75),width=1)
    services.draw_center(draw,(x1+8,y2-strip_h+1,x2-8,y2-5)," / ".join(names),colors["light"],max_size=8,min_size=7,bold=True,max_lines=1)


def _draw_reward_style_ring_gacha(base, draw, guide, services, tools, box, colors, units):
    for unit,ubox,index in _layout_reward_units_gacha(units,box):
        typ=unit.get("type","item") if isinstance(unit,dict) else "item"
        accent=_reward_accent_gacha(guide,colors,index,choice=(typ=="choice"))
        if typ=="choice":
            _draw_ring_reward_choice_gacha(base,draw,guide,services,colors,unit,ubox,accent)
        else:
            leaf=_reward_leaf_items_gacha(unit,1)
            if leaf:
                _draw_ring_reward_single_gacha(base,draw,guide,services,colors,leaf[0],ubox,accent)


def _draw_large_reward_tray(base, draw, guide, services, tools, box, colors, max_items=6):
    """Theme-selectable gacha reward presentation; semantic A-or-B stays intact."""
    units=_reward_units_gacha(guide,services,max_items=max_items)
    if not units:
        services.draw_center(draw,box,tools.reward_summary(guide),colors["light"],max_size=15,min_size=11,bold=True,max_lines=2)
        return
    cfg=_reward_display_cfg_gacha(guide)
    style=str(cfg.get("style") or "capsule_pedestal").strip().lower()
    if style in {"prize_window","window","vending_window"}:
        _draw_reward_style_window_gacha(base,draw,guide,services,tools,box,colors,units)
    elif style in {"acrylic_dome","dome","prize_dome"}:
        _draw_reward_style_dome_gacha(base,draw,guide,services,tools,box,colors,units)
    elif style in {"light_ring","ring","jackpot_ring"}:
        _draw_reward_style_ring_gacha(base,draw,guide,services,tools,box,colors,units)
    else:
        _draw_reward_style_pedestal_gacha(base,draw,guide,services,tools,box,colors,units)

def render(guide, out_path, services):
    tools = SharedRendererTools(services)
    cfg = rcfg(guide)
    colors = tools.colors(guide, {
        "background":"#EFE8DE", "machine":"#D94840", "machine_dark":"#5C2724",
        "glass":"#EAF1F4", "slot":"#DCE5E9", "slot_border":"#5F6C75",
        "screen":"#171D21", "screen_text":"#F6E5A1", "ink":"#273038",
        "muted":"#65717A", "accent":"#F0CF69", "risk":"#F4D66F",
        "light":"#FFFDF7", "primary":"#D94840", "dark":"#20272C", "chip":"#E6DBCF",
    })
    W,H,img = mobile_canvas(services, colors["background"])
    d = ImageDraw.Draw(img)

    # Title stays outside the machine, like a product poster / arcade cabinet label.
    services.draw_center(d,(38,22,W-38,70),clean(services,guide.get("title"),"活动攻略"),colors["ink"],
                         max_size=38,min_size=28,bold=True,max_lines=1)
    services.draw_center(d,(38,72,W-38,108),"扭蛋机攻略 · GACHA 7-DAY MACHINE",colors["muted"],
                         max_size=15,min_size=12,bold=False,max_lines=1)

    # Machine body. Footer remains outside it.
    machine = (68,118,W-68,H-86)
    _beveled_panel(d,machine,colors["machine"],light="#F36B61",dark=colors["machine_dark"],radius=38,width=7)
    # cabinet fasteners make the outer shell read as a physical machine
    for sx,sy in ((90,142),(W-90,142),(90,H-112),(W-90,H-112)):
        _screw(d,sx,sy,7)

    # 1) Compact transparent chamber: ~17% of page height.
    _draw_glass_chamber(img,d,guide,services,(108,150,W-108,408),colors)

    # 2) Main operation console: largest block on page (~41%).
    op_box = (108,432,W-108,1280)
    d.rounded_rectangle((op_box[0]-8,op_box[1]-8,op_box[2]+8,op_box[3]+8),radius=28,fill="#22282C",outline="#111619",width=5)
    d.rounded_rectangle(op_box,radius=22,fill=colors["screen"],outline="#59636A",width=3)
    for sx,sy in ((op_box[0]+16,op_box[1]+16),(op_box[2]-16,op_box[1]+16),(op_box[0]+16,op_box[3]-16),(op_box[2]-16,op_box[3]-16)):
        _screw(d,sx,sy,5,fill="#AEB6BB",outline="#4D565C")
    services.draw_left(d,(132,448,W-360,488),"7-DAY OPERATION CONSOLE",colors["light"],
                       max_size=20,min_size=16,bold=True,max_lines=1,valign="center")
    services.draw_left(d,(W-340,450,W-132,486),"每日操作主区域", "#BFC8CD",
                       max_size=12,min_size=9,bold=False,max_lines=1,valign="center")

    days = list(guide.get("days") or [])[:7]
    gap_x = 16
    gap_y = 14
    left = 128
    right = W-128
    body_top = 500
    card_w = (right-left-gap_x)//2
    card_h = 160

    for i,info in enumerate(days[:6]):
        row,col = divmod(i,2)
        x1 = left + col*(card_w+gap_x)
        y1 = body_top + row*(card_h+gap_y)
        _draw_day_card(img,d,guide,services,tools,cfg,colors,info,i,(x1,y1,x1+card_w,y1+card_h),d7=False)

    # D7 full-width and taller, but still the same console / capsule language.
    if len(days) >= 7:
        d7_y = body_top + 3*(card_h+gap_y)
        _draw_day_card(img,d,guide,services,tools,cfg,colors,days[6],6,(left,d7_y,right,1258),d7=True)

    # 3) Compact resource control panel.  Real KPI values are retained.
    kpi_box = (108,1282,W-108,1404)
    d.rounded_rectangle(kpi_box,radius=18,fill="#1D2226",outline="#454E54",width=3)
    services.draw_left(d,(132,1292,W-280,1318),"RESOURCE CONTROL", "#AAB5BC",
                       max_size=11,min_size=9,bold=True,max_lines=1,valign="center")
    # Reuse the project's canonical KPI icon mapping so budget / expected values
    # carry the same resource icons as other themes.
    _draw_gacha_kpis(img,d,guide,services,tools,(132,1320,W-300,1392),colors)
    # A real coin/turn mechanism sells the machine far better than another data card.
    _draw_coin_mechanism(d,services,(W-275,1294,W-132,1400),colors)

    # 4) Safety / reminder plate.  Each reminder owns one row.
    risk_box = (108,1424,W-108,1538)
    d.rounded_rectangle(risk_box,radius=14,fill=colors["risk"],outline="#735B21",width=2)
    risks = tools.risk_items(guide) or ["D3 / D7 为重点日，按每日操作执行。"]
    inner_top, inner_bottom = 1432, 1530
    line_h = max(18, (inner_bottom-inner_top)//max(1,len(risks)))
    for i,risk in enumerate(risks):
        ry1 = inner_top + i*line_h
        ry2 = inner_top + (i+1)*line_h
        icon_cx=133
        icon_cy=(ry1+ry2)//2
        _draw_warning_icon(d,icon_cx,icon_cy,min(20,max(14,line_h-10)),colors["machine_dark"])
        services.draw_left(
            d,(153,ry1,W-132,ry2),clean(services,risk),colors["machine_dark"],
            max_size=int(cfg.get("risk_font_size",18) or 18),
            min_size=int(cfg.get("risk_min_font_size",13) or 13),
            bold=True,max_lines=1,line_gap=0,valign="center",
        )

    # 5) Physical pickup hatch + real rewards.  Recessed tunnel, bezel and half-dropped capsule.
    hatch = (108,1552,W-108,1836)
    d.rounded_rectangle((hatch[0]-6,hatch[1]-6,hatch[2]+6,hatch[3]+6),radius=28,fill="#2C3338",outline="#0E1214",width=5)
    d.rounded_rectangle(hatch,radius=23,fill="#11171B",outline="#78858D",width=3)
    services.draw_center(d,(136,1564,W-136,1598),"CAPSULE PICKUP / 扭蛋舱口",colors["light"],
                         max_size=18,min_size=15,bold=True,max_lines=1)
    # recessed throat with deep shadow, top lip and side bolts
    opening = (246,1601,W-246,1668)
    d.rounded_rectangle((opening[0]-9,opening[1]-8,opening[2]+9,opening[3]+8),radius=31,fill="#4A5359",outline="#909AA0",width=2)
    d.rounded_rectangle(opening,radius=27,fill="#030607",outline="#252D31",width=3)
    d.arc((opening[0]+12,opening[1]+9,opening[2]-12,opening[3]+42),180,360,fill="#68757D",width=5)
    d.line((opening[0]+18,opening[1]+9,opening[2]-18,opening[1]+9),fill="#B6C0C6",width=3)
    _screw(d,opening[0]-17,(opening[1]+opening[3])//2,5)
    _screw(d,opening[2]+17,(opening[1]+opening[3])//2,5)
    # D7 physically drops from the throat using the SAME theme-configured
    # per-day asset as the Day7 card. No concrete capsule filename is hard-coded here.
    _draw_configured_day_capsule(
        img,d,guide,services,(W//2-43,1613,W//2+43,1699),
        colors["primary"],day_index=6,
    )

    # Reward tray: use a taller, theme-owned layout so the real item artwork can
    # be visibly larger than the generic shared-card default.
    tray = (136,1696,W-136,1826)
    d.rounded_rectangle(tray,radius=14,fill="#222A2F",outline="#536169",width=2)
    _draw_large_reward_tray(img,d,guide,services,tools,(150,1701,W-150,1820),colors,
                            max_items=int(cfg.get("reward_max_items",4) or 4))

    _draw_gacha_footer(img,d,guide,services,H-70,70,colors)
    tools.save(img,out_path,guide)
