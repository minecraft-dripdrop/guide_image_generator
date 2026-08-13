# -*- coding: utf-8 -*-
"""Arcade pinball strategy renderer.

The entire page is treated as the front panel / playfield of a real arcade
pinball machine.  Decorative rails, balls, bumpers and flippers create the
machine identity, while all guide text remains horizontal and readable.
"""
from __future__ import annotations

import hashlib
import math
import random
import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageOps

from .shared import SharedRendererTools
from .reward_items import RewardItemRenderer

STYLE_IDS = ("arcade_pinball",)


def _rcfg(guide):
    tc = guide.get("theme_config") or {}
    r = tc.get("renderer") if isinstance(tc.get("renderer"), dict) else {}
    cfg = dict(r or {})
    pcfg = guide.get("cfg") or {}
    if isinstance(pcfg.get("arcade_pinball"), dict):
        cfg.update(pcfg.get("arcade_pinball") or {})
    return cfg


def _rng(guide, salt=""):
    raw = "{}|{}|{}|{}".format(
        guide.get("sheet") or "",
        guide.get("title") or "",
        guide.get("variant_id") or "",
        salt,
    )
    seed = int(hashlib.sha256(raw.encode("utf-8", "ignore")).hexdigest()[:16], 16)
    return random.Random(seed)


def _rgb(v, default=(255, 255, 255)):
    if isinstance(v, tuple):
        return v[:3]
    s = str(v or "").lstrip("#")
    try:
        if len(s) >= 6:
            return tuple(int(s[i:i+2], 16) for i in (0, 2, 4))
    except Exception:
        pass
    return default


def _rgba(v, a=255, default=(255, 255, 255)):
    r, g, b = _rgb(v, default)
    return (r, g, b, max(0, min(255, int(a))))


def _mix(a, b, t):
    ca = _rgb(a); cb = _rgb(b)
    t = max(0.0, min(1.0, float(t)))
    return tuple(int(round(ca[i] * (1 - t) + cb[i] * t)) for i in range(3))


def _glow_rounded(base, box, radius, fill, glow, glow_radius=12, glow_alpha=125, outline=None, width=2):
    x1, y1, x2, y2 = map(int, box)
    pad = int(glow_radius * 2 + 8)
    layer = Image.new("RGBA", (x2-x1+pad*2, y2-y1+pad*2), (0,0,0,0))
    ld = ImageDraw.Draw(layer)
    local = (pad, pad, pad + (x2-x1), pad + (y2-y1))
    ld.rounded_rectangle(local, radius=radius, outline=_rgba(glow, glow_alpha), width=max(3, int(width)+2))
    blur = layer.filter(ImageFilter.GaussianBlur(glow_radius))
    base.alpha_composite(blur, (x1-pad, y1-pad))
    d = ImageDraw.Draw(base)
    d.rounded_rectangle((x1,y1,x2,y2), radius=radius, fill=fill, outline=outline or glow, width=width)


def _bolt(draw, xy, r, colors):
    x,y = xy
    draw.ellipse((x-r,y-r,x+r,y+r), fill=colors["bolt_dark"], outline=colors["rail_hi"], width=1)
    draw.ellipse((x-r+2,y-r+2,x+r-2,y+r-2), fill=colors["bolt"], outline=colors["bolt_dark"], width=1)
    draw.line((x-r//2,y,x+r//2,y), fill=colors["bolt_dark"], width=1)


def _bulb(base, xy, r, color, hot=None, style="classic"):
    x,y = map(int,xy); r=max(3,int(r))
    glow = Image.new("RGBA", (r*6,r*6), (0,0,0,0))
    gd = ImageDraw.Draw(glow)
    c = _rgb(color)
    gd.ellipse((r, r, r*5, r*5), fill=(c[0],c[1],c[2],80 if style!="ticket" else 45))
    glow = glow.filter(ImageFilter.GaussianBlur(r))
    base.alpha_composite(glow,(x-r*3,y-r*3))
    d=ImageDraw.Draw(base)
    d.ellipse((x-r,y-r,x+r,y+r), fill=color, outline=hot or "#FFF6C8", width=2)
    hr=max(2,r//3)
    d.ellipse((x-r//2,y-r//2,x-r//2+hr,y-r//2+hr), fill=hot or "#FFFFFF")


def _ball(base, xy, r, color, edge, hi="#FFFFFF"):
    x,y=map(int,xy); r=max(5,int(r))
    layer=Image.new("RGBA",(r*4,r*4),(0,0,0,0)); ld=ImageDraw.Draw(layer)
    ld.ellipse((r//2,r//2,r*7//2,r*7//2), fill=_rgba(edge,80))
    layer=layer.filter(ImageFilter.GaussianBlur(max(2,r//2)))
    base.alpha_composite(layer,(x-r*2,y-r*2))
    d=ImageDraw.Draw(base)
    d.ellipse((x-r,y-r,x+r,y+r), fill=color, outline=edge, width=max(2,r//5))
    d.ellipse((x-r//2,y-r//2,x+r//6,y+r//6), fill=_rgba(hi,190))
    d.arc((x-r+3,y-r+3,x+r-3,y+r-3), 205, 330, fill=_rgba(edge,180), width=max(1,r//7))


def _bumper(base, xy, r, colors, style="classic"):
    x,y=map(int,xy); r=int(r)
    _bulb(base,(x,y),r+4,colors["bumper_glow"],colors["lamp_hot"],style)
    d=ImageDraw.Draw(base)
    d.ellipse((x-r,y-r,x+r,y+r), fill=colors["bumper"], outline=colors["rail_hi"], width=3)
    d.ellipse((x-r+8,y-r+8,x+r-8,y+r-8), fill=colors["playfield"], outline=colors["accent2"], width=3)
    d.ellipse((x-7,y-7,x+7,y+7), fill=colors["lamp_hot"])


def _rail(draw, pts, colors, width=12):
    pts=[(int(x),int(y)) for x,y in pts]
    draw.line(pts, fill=colors["rail_shadow"], width=width+5, joint="curve")
    draw.line(pts, fill=colors["rail"], width=width, joint="curve")
    draw.line([(x-1,y-2) for x,y in pts], fill=colors["rail_hi"], width=max(2,width//4), joint="curve")


def _flipper(draw, p1, p2, body, outline, hi):
    x1,y1=p1; x2,y2=p2
    width=28
    draw.line((x1,y1,x2,y2), fill=outline, width=width+8)
    draw.line((x1,y1,x2,y2), fill=body, width=width)
    draw.line((x1,y1-3,x2,y2-3), fill=hi, width=5)
    for x,y in (p1,p2):
        draw.ellipse((x-18,y-18,x+18,y+18),fill=outline)
        draw.ellipse((x-12,y-12,x+12,y+12),fill=body,outline=hi,width=2)


def _bevel_panel(draw, box, fill, edge, hi, shadow, radius=18, width=4):
    x1,y1,x2,y2=map(int,box)
    draw.rounded_rectangle((x1+5,y1+7,x2+5,y2+7), radius=radius, fill=shadow)
    draw.rounded_rectangle((x1,y1,x2,y2), radius=radius, fill=fill, outline=edge, width=width)
    draw.line((x1+radius,y1+5,x2-radius,y1+5), fill=hi, width=2)


def _ticket_stub(draw, xy, colors, angle=0):
    # Small 2D sticker; no rotation is used so text/layout stays crisp.
    x,y=map(int,xy)
    draw.rounded_rectangle((x,y,x+86,y+34), radius=6, fill=colors["ticket"], outline=colors["ticket_edge"], width=2)
    draw.line((x+58,y+3,x+58,y+31),fill=colors["ticket_edge"],width=1)
    for yy in range(y+7,y+29,6):
        draw.ellipse((x+55,yy,x+61,yy+4),fill=colors["cabinet_dark"])


def _gear(draw, xy, r, colors, teeth=14, fill=None, edge=None, hub=None):
    """Programmatic brass/iron gear used only by the steampunk variant."""
    cx, cy = map(int, xy)
    r = max(14, int(r))
    teeth = max(8, int(teeth))
    fill = fill or colors["edge"]
    edge = edge or colors["edge_dark"]
    hub = hub or colors["bolt"]
    pts = []
    for i in range(teeth * 4):
        ang = -math.pi / 2 + i * (math.pi * 2 / (teeth * 4))
        phase = i % 4
        rr = r if phase in (0, 1) else r * 0.80
        pts.append((cx + math.cos(ang) * rr, cy + math.sin(ang) * rr))
    draw.polygon(pts, fill=fill, outline=edge)
    draw.ellipse((cx-r*0.58,cy-r*0.58,cx+r*0.58,cy+r*0.58),fill=colors["cabinet_dark"],outline=edge,width=3)
    for i in range(6):
        ang=i*math.pi/3
        x1=cx+math.cos(ang)*r*0.17; y1=cy+math.sin(ang)*r*0.17
        x2=cx+math.cos(ang)*r*0.50; y2=cy+math.sin(ang)*r*0.50
        draw.line((x1,y1,x2,y2),fill=fill,width=max(4,r//8))
    draw.ellipse((cx-r*0.18,cy-r*0.18,cx+r*0.18,cy+r*0.18),fill=hub,outline=edge,width=2)


def _pressure_gauge(base, xy, r, colors):
    """Small mechanical pressure gauge for the steampunk score bridge."""
    d=ImageDraw.Draw(base)
    cx,cy=map(int,xy); r=max(18,int(r))
    d.ellipse((cx-r-4,cy-r-4,cx+r+4,cy+r+4),fill=colors["cabinet_shadow"],outline=colors["edge_dark"],width=3)
    d.ellipse((cx-r,cy-r,cx+r,cy+r),fill="#D8C49A",outline=colors["edge"],width=4)
    for i in range(9):
        a=math.radians(210+i*15)
        x1=cx+math.cos(a)*r*0.66; y1=cy+math.sin(a)*r*0.66
        x2=cx+math.cos(a)*r*0.88; y2=cy+math.sin(a)*r*0.88
        d.line((x1,y1,x2,y2),fill=colors["edge_dark"],width=2)
    a=math.radians(305)
    d.line((cx,cy,cx+math.cos(a)*r*0.62,cy+math.sin(a)*r*0.62),fill="#7E281C",width=3)
    d.ellipse((cx-5,cy-5,cx+5,cy+5),fill=colors["bolt_dark"],outline=colors["edge"],width=1)


def _draw_steampunk_decor(base, colors):
    """Gears/pipes live on the cabinet margins so they never steal Day text space."""
    d = ImageDraw.Draw(base, "RGBA")
    # Copper pipes around the outer shell.
    pipe = colors.get("pipe", colors["rail"])
    pipe_hi = colors.get("pipe_hi", colors["rail_hi"])
    for pts in [
        [(66,320),(66,520),(92,548)],
        [(1014,326),(1014,548),(988,576)],
        [(72,1760),(72,1990),(116,2030)],
        [(1008,1740),(1008,1988),(968,2028)],
    ]:
        d.line(pts, fill=colors["rail_shadow"], width=13, joint="curve")
        d.line(pts, fill=pipe, width=9, joint="curve")
        d.line([(x-1,y-2) for x,y in pts], fill=pipe_hi, width=2, joint="curve")
    # Deliberately clipped/edge gears: strongly steampunk, but outside reading columns.
    for args in [
        ((70,360),58,16), ((1006,460),50,14), ((74,1870),64,16), ((1007,1870),60,15),
        ((92,618),34,12), ((987,650),32,12),
    ]:
        _gear(d, args[0], args[1], colors, teeth=args[2])
    # Extra rivets reinforce a constructed brass machine rather than a recolour.
    for y in range(360,1980,150):
        _bolt(d,(66,y),5,colors); _bolt(d,(1014,y),5,colors)


def _draw_background(base, guide, colors, style, rng):
    d=ImageDraw.Draw(base,"RGBA")
    W,H=base.size
    d.rectangle((0,0,W,H),fill=colors["background"])
    # Room/cabinet glow.
    for i in range(10):
        inset=i*8
        a=max(8,58-i*5)
        d.rounded_rectangle((inset,inset,W-inset-1,H-inset-1),radius=30,outline=_rgba(colors["accent"],a),width=5)

    if style=="neon":
        for _ in range(80):
            x=rng.randrange(18,W-18); y=rng.randrange(20,H-30); r=rng.choice([1,1,1,2])
            c=rng.choice([colors["accent"],colors["accent2"],colors["lamp"]])
            d.ellipse((x-r,y-r,x+r,y+r),fill=_rgba(c,rng.randint(35,120)))
        # faint scan lines
        for y in range(0,H,12):
            d.line((0,y,W,y),fill=(255,255,255,8),width=1)
    elif style=="steampunk":
        # Warm soot / brass patina.  Kept mostly on the cabinet background.
        for _ in range(230):
            x=rng.randrange(10,W-10); y=rng.randrange(18,H-18)
            if rng.random() < 0.72:
                d.point((x,y), fill=(244,188,86,rng.randint(10,42)))
            else:
                l=rng.randint(8,34)
                d.line((x,y,min(W-6,x+l),y+rng.randint(-2,2)), fill=(87,48,24,rng.randint(18,48)), width=1)
    elif style=="ticket":
        band=[colors["accent"],colors["accent2"],colors["lamp"]]
        for i,x in enumerate(range(20,W,72)):
            d.rectangle((x,0,min(W,x+18),H),fill=_rgba(band[i%3],16))
    else:
        # worn arcade speckles / scratches, sparse enough for clean text.
        for _ in range(180):
            x=rng.randrange(12,W-12); y=rng.randrange(20,H-20)
            if rng.random()<0.78:
                d.point((x,y),fill=(255,220,160,rng.randint(10,40)))
            else:
                l=rng.randint(5,25)
                d.line((x,y,min(W-5,x+l),y+rng.randint(-2,2)),fill=(255,215,150,rng.randint(12,34)),width=1)


def _draw_cabinet_shell(base, colors, style):
    d=ImageDraw.Draw(base)
    W,H=base.size
    # Main cabinet, thick front-facing construction, not perspective warped.
    d.rounded_rectangle((22,20,W-22,H-18), radius=38, fill=colors["cabinet_shadow"], outline=colors["edge_dark"], width=6)
    d.rounded_rectangle((35,32,W-35,H-32), radius=32, fill=colors["cabinet"], outline=colors["edge"], width=6)
    d.rounded_rectangle((52,48,W-52,H-48), radius=25, fill=colors["cabinet_dark"], outline=colors["rail_hi"], width=2)
    for xy in [(48,48),(W-48,48),(48,H-48),(W-48,H-48),(72,275),(W-72,275)]:
        _bolt(d,xy,9,colors)
    if style == "steampunk":
        for xy in [(72,150),(W-72,150),(72,2160),(W-72,2160),(250,56),(W-250,56)]:
            _bolt(d,xy,6,colors)


def _draw_marquee(base, guide, services, colors, rcfg, style):
    d=ImageDraw.Draw(base)
    W=base.width
    # V35.78: the classic red cabinet uses a shorter marquee so the resource
    # and reward wings can become taller. Neon/steampunk keep their established
    # silhouette because their top treatment is part of the variant identity.
    compact = style == "classic"
    box=(96,58,W-96,248 if compact else 282)
    if style=="neon":
        _glow_rounded(base,box,24,colors["marquee"],colors["accent"],16,150,colors["accent2"],4)
    else:
        _bevel_panel(d,box,colors["marquee"],colors["edge"],colors["rail_hi"],colors["cabinet_shadow"],24,5)
    if bool(rcfg.get("marquee_bulbs",True)):
        xs=list(range(128,W-127,56))
        bottom_bulb_y = 228 if compact else 262
        for x in xs:
            _bulb(base,(x,77),6,colors["lamp"],colors["lamp_hot"],style)
            _bulb(base,(x,bottom_bulb_y),6,colors["lamp"],colors["lamp_hot"],style)

    badge=(380,34,700,88 if compact else 92)
    _glow_rounded(base,badge,16,colors["badge"],colors["accent2"],8,80,colors["rail_hi"],3)
    services.draw_center(d,badge,rcfg.get("top_badge_text","EXTRA BALL"),colors["badge_text"],max_size=24,min_size=15,bold=True,max_lines=1,line_gap=0)

    title=services.clean(str(guide.get("title") or "弹珠活动攻略"))
    title_box=(128,90,W-128,164) if compact else (128,98,W-128,198)
    services.draw_center(d,title_box,title,colors["title"],max_size=int(rcfg.get("title_font_size",48) or 48),min_size=28,bold=True,max_lines=2,line_gap=1)
    subtitle=services.clean(str(guide.get("subtitle") or ""))
    if not subtitle:
        subtitle=rcfg.get("subtitle_fallback","资源预算｜重点奖励｜七日执行｜风险提示")
    sub_box=(148,167,W-148,213) if compact else (148,202,W-148,250)
    services.draw_center(d,sub_box,subtitle,colors["subtitle"],max_size=18,min_size=11,bold=True,max_lines=1,line_gap=0)
    if style == "steampunk":
        _gear(d,(126,170),34,colors,teeth=12)
        _gear(d,(W-126,170),34,colors,teeth=12)


def _side_panel_shell(draw, box, colors, title, services, accent=None):
    x1,y1,x2,y2=map(int,box)
    accent=accent or colors["accent"]
    # side-wing octagonal panel
    cut=18
    poly=[(x1+cut,y1),(x2-cut,y1),(x2,y1+cut),(x2,y2-cut),(x2-cut,y2),(x1+cut,y2),(x1,y2-cut),(x1,y1+cut)]
    shadow=[(x+5,y+7) for x,y in poly]
    draw.polygon(shadow,fill=colors["cabinet_shadow"])
    draw.polygon(poly,fill=colors["panel"],outline=colors["edge"])
    draw.line((x1+18,y1+4,x2-18,y1+4),fill=colors["rail_hi"],width=2)
    draw.rectangle((x1+12,y1+12,x2-12,y1+62),fill=colors["panel_header"],outline=accent,width=2)
    services.draw_center(draw,(x1+20,y1+17,x2-20,y1+57),title,colors["panel_title"],max_size=23,min_size=15,bold=True,max_lines=1,line_gap=0)
    for xy in [(x1+14,y1+14),(x2-14,y1+14),(x1+14,y2-14),(x2-14,y2-14)]:
        _bolt(draw,xy,6,colors)


def _draw_kpi_panel(base, guide, services, tools, colors, box):
    d=ImageDraw.Draw(base)
    _side_panel_shell(d,box,colors,"资源 / BALL STOCK",services)
    items=tools.kpis(guide)
    x1,y1,x2,y2=map(int,box)
    if not items:
        services.draw_center(d,(x1+20,y1+78,x2-20,y2-20),"暂无资源预算",colors["muted"],max_size=16,min_size=11,bold=False,max_lines=2,line_gap=3)
        return
    top=y1+74; bottom=y2-18; gap=7
    rh=(bottom-top-gap*max(0,len(items)-1))/max(1,len(items))
    for i,item in enumerate(items):
        yy1=int(top+i*(rh+gap)); yy2=int(yy1+rh)
        d.rounded_rectangle((x1+16,yy1,x2-16,yy2),radius=11,fill=colors["screen"],outline=colors["screen_edge"],width=2)
        label=services.clean(str(item.get("label") or "资源"))
        value=services.clean(str(item.get("value") or "—"))
        icon=item.get("icon")
        tx=x1+28
        if icon and Path(icon).exists():
            sz=min(32,yy2-yy1-10)
            services.draw_image_contain(base,Path(icon),(tx,yy1+5,tx+sz,yy1+5+sz))
            tx+=sz+7
        services.draw_left(
            d,(tx,yy1+5,x2-96,yy2-5),label,colors["muted"],
            max_size=int(_rcfg(guide).get("resource_name_font_size",16) or 16),
            min_size=int(_rcfg(guide).get("resource_name_min_font_size",14) or 14),
            bold=True,max_lines=1,line_gap=0,valign="center"
        )
        services.draw_left(
            d,(x2-108,yy1+4,x2-28,yy2-4),value,colors["score"],
            max_size=int(_rcfg(guide).get("resource_value_font_size",22) or 22),
            min_size=int(_rcfg(guide).get("resource_value_min_font_size",16) or 16),
            bold=True,max_lines=1,line_gap=0,valign="center"
        )


def _ellipsize_single_line(draw, services, text, font, max_width):
    """Keep a label on one line at a fixed font size, using … instead of shrinking."""
    s = services.clean(str(text or ""))
    if not s:
        return ""
    if services.text_width(draw, s, font) <= max_width:
        return s
    ell = "…"
    if services.text_width(draw, ell, font) > max_width:
        return ""
    lo, hi = 0, len(s)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        candidate = s[:mid].rstrip() + ell
        if services.text_width(draw, candidate, font) <= max_width:
            lo = mid
        else:
            hi = mid - 1
    return s[:lo].rstrip() + ell


def _draw_single_line_fitted(draw, services, box, text, color, max_size, min_size, bold=True, align="left"):
    """Single-line text: fit by font size, then ellipsize only at min size."""
    x1, y1, x2, y2 = map(int, box)
    s = services.clean(str(text or ""))
    if not s:
        return
    chosen = None
    for size in range(int(max_size), int(min_size) - 1, -1):
        font = services.get_font(size, bold)
        if services.text_width(draw, s, font) <= (x2 - x1):
            chosen = font
            break
    if chosen is None:
        chosen = services.get_font(int(min_size), bold)
        s = _ellipsize_single_line(draw, services, s, chosen, x2 - x1)

    bb = draw.textbbox((0, 0), s or " ", font=chosen)
    th = max(1, bb[3] - bb[1])
    ty = y1 + max(0, (y2 - y1 - th) / 2) - bb[1]
    if align == "right":
        tx = x2 - services.text_width(draw, s, chosen)
    elif align == "center":
        tx = x1 + ((x2 - x1) - services.text_width(draw, s, chosen)) / 2
    else:
        tx = x1
    draw.text((tx, ty), s, font=chosen, fill=color)


def _draw_single_line_complete(draw, services, box, text, color, max_size, min_size, bold=True, align="left"):
    """Draw the complete label on one line without ellipsis.

    It first uses normal font fitting.  If an unusually long item still cannot
    fit at the configured minimum size, the text is *slightly condensed
    horizontally* instead of being truncated.  This preserves the full item
    name and keeps its visual height readable.
    """
    x1, y1, x2, y2 = map(int, box)
    s = services.clean(str(text or ""))
    if not s:
        return
    max_w = max(1, x2 - x1)
    chosen = None
    for size in range(int(max_size), int(min_size) - 1, -1):
        font = services.get_font(size, bold)
        if services.text_width(draw, s, font) <= max_w:
            chosen = font
            break
    if chosen is not None:
        bb = draw.textbbox((0, 0), s, font=chosen)
        th = max(1, bb[3] - bb[1])
        ty = y1 + max(0, (y2 - y1 - th) / 2) - bb[1]
        tw = services.text_width(draw, s, chosen)
        if align == "right":
            tx = x2 - tw
        elif align == "center":
            tx = x1 + (max_w - tw) / 2
        else:
            tx = x1
        draw.text((tx, ty), s, font=chosen, fill=color)
        return

    # No truncation: render at minimum readable height, then condense only in X.
    font = services.get_font(int(min_size), bold)
    bb = draw.textbbox((0, 0), s, font=font)
    raw_w = max(1, bb[2] - bb[0])
    raw_h = max(1, bb[3] - bb[1])
    pad = 3
    layer = Image.new("RGBA", (raw_w + pad * 2, raw_h + pad * 2), (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    ld.text((pad - bb[0], pad - bb[1]), s, font=font, fill=color)
    target_w = max(1, min(layer.width, max_w))
    if target_w != layer.width:
        layer = layer.resize((target_w, layer.height), Image.Resampling.LANCZOS)
    if align == "right":
        tx = x2 - layer.width
    elif align == "center":
        tx = x1 + (max_w - layer.width) / 2
    else:
        tx = x1
    ty = y1 + max(0, (y2 - y1 - layer.height) / 2)
    # The base image is the same RGBA canvas behind this draw object.
    try:
        draw._image.alpha_composite(layer, (int(tx), int(ty)))
    except Exception:
        # Pillow's ImageDraw internals vary.  A conservative fallback keeps the
        # full name at minimum font size even if it slightly crowds the box.
        draw.text((x1, y1 + max(0, (y2-y1-raw_h)/2) - bb[1]), s, font=font, fill=color)

def _draw_reward_panel(base, guide, services, tools, colors, box):
    """Four readable reward rows: shared artwork + full one-line name + right qty."""
    d = ImageDraw.Draw(base)
    _side_panel_shell(d, box, colors, "奖励 / JACKPOT", services, colors["accent2"])
    x1, y1, x2, y2 = map(int, box)
    leaves = tools.flat_reward_items(guide.get("reward_items") or [])[:4]
    rows = []
    reward_renderer = RewardItemRenderer(services, guide)

    for item in leaves:
        qty = services.clean(str(item.get("qty") or ""))
        rows.append({
            "item": item,
            "label": services.clean(str(item.get("name") or "奖励")),
            "value": (("×" + qty) if qty else ""),
        })

    if not rows:
        summary = tools.reward_summary(guide)
        parts = [services.clean(x) for x in re.split(r"[\n；;、|]+", summary) if services.clean(x)]
        if not parts:
            parts = ["暂无奖励信息"]
        for part in parts[:4]:
            rows.append({"item": {"name": part}, "label": part, "value": ""})

    top = y1 + 74
    bottom = y2 - 16
    gap = 5
    rh = (bottom - top - gap * max(0, len(rows) - 1)) / max(1, len(rows))
    rcfg = _rcfg(guide)
    icon_size_cfg = int(rcfg.get("reward_row_icon_size", 34) or 34)
    name_max = int(rcfg.get("reward_name_font_size", 18) or 17)
    name_min = int(rcfg.get("reward_name_min_font_size", 15) or 14)
    qty_max = int(rcfg.get("reward_qty_font_size", 19) or 19)
    qty_min = int(rcfg.get("reward_qty_min_font_size", 16) or 16)

    for i, row in enumerate(rows):
        yy1 = int(top + i * (rh + gap))
        yy2 = int(yy1 + rh)
        row_x1, row_x2 = x1 + 11, x2 - 11
        d.rounded_rectangle(
            (row_x1, yy1, row_x2, yy2),
            radius=11,
            fill=colors["screen"],
            outline=colors["accent2"],
            width=2,
        )

        icon_slot = min(icon_size_cfg, max(24, yy2 - yy1 - 7))
        ix = row_x1 + 8
        iy = int(yy1 + (yy2 - yy1 - icon_slot) / 2)
        ibox = (ix, iy, ix + icon_slot, iy + icon_slot)
        resolved = reward_renderer.draw_icon(
            base, row["item"], ibox,
            # Framed reward geometry is global; only overall icon_slot varies by theme.
            plain_inset=max(3, int(icon_slot * 0.10)),
        )
        icon_path = resolved.get("icon_path")
        if not (icon_path and Path(icon_path).exists()):
            d.rounded_rectangle(ibox, radius=6, outline=colors["accent2"], width=1)
            services.draw_center(d, ibox, "?", colors["accent2"], max_size=17, min_size=12, bold=True, max_lines=1)

        # Quantity width is based on the actual number, not a wasteful fixed box.
        value = row.get("value") or ""
        qty_font = services.get_font(qty_max, True)
        qty_w = services.text_width(d, value, qty_font) if value else 0
        qty_w = max(42 if value else 0, min(66, int(qty_w + 5)))
        qty_box = (row_x2 - 7 - qty_w, yy1 + 3, row_x2 - 7, yy2 - 3)
        name_box = (ibox[2] + 6, yy1 + 3, qty_box[0] - 5, yy2 - 3)

        # Full item name is more important than decorative whitespace: never ellipsize.
        _draw_single_line_complete(
            d, services, name_box, row["label"], colors["text"],
            max_size=name_max, min_size=name_min, bold=True, align="left",
        )
        if value:
            _draw_single_line_fitted(
                d, services, qty_box, value, colors["score"],
                max_size=qty_max, min_size=qty_min, bold=True, align="right",
            )


def _draw_score_center(base, guide, services, colors, rcfg, style):
    d=ImageDraw.Draw(base)
    box=(348,310,732,432)
    if style=="neon":
        _glow_rounded(base,box,20,colors["screen"],colors["accent2"],10,120,colors["accent"],3)
    else:
        _bevel_panel(d,box,colors["screen"],colors["screen_edge"],colors["rail_hi"],colors["cabinet_shadow"],16,3)
    services.draw_center(d,(360,320,720,356),rcfg.get("center_label","BALL DROP"),colors["accent2"],max_size=18,min_size=12,bold=True,max_lines=1,line_gap=0)
    core=services.clean(str(guide.get("core") or ""))
    status=core if core else rcfg.get("center_status","READY · HOLD · JACKPOT")
    services.draw_center(d,(360,360,720,418),status,colors["score"],max_size=22,min_size=11,bold=True,max_lines=2,line_gap=1)

    # Physical score bridge.  The steampunk variant swaps the middle lamp for
    # a pressure gauge so it reads as a real brass mechanism, not a recolour.
    lamp_y = 518
    if style == "steampunk":
        _bulb(base,(438,lamp_y),12,colors["accent"],colors["lamp_hot"],style)
        _pressure_gauge(base,(540,lamp_y),34,colors)
        _bulb(base,(642,lamp_y),12,colors["final"],colors["lamp_hot"],style)
        services.draw_center(d,(392,lamp_y+24,484,lamp_y+45),"BALL",colors["muted"],max_size=9,min_size=7,bold=True,max_lines=1,line_gap=0)
        services.draw_center(d,(596,lamp_y+24,688,lamp_y+45),"JACKPOT",colors["muted"],max_size=9,min_size=7,bold=True,max_lines=1,line_gap=0)
    else:
        labels = [(430, colors["accent"], "BALL"), (540, colors["accent2"], "SAVE"), (650, colors["final"], "JACKPOT")]
        for x, c, label in labels:
            _bulb(base, (x, lamp_y), 16, c, colors["lamp_hot"], style)
            services.draw_center(d, (x-44, lamp_y+24, x+44, lamp_y+47), label, colors["muted"], max_size=9, min_size=7, bold=True, max_lines=1, line_gap=0)



def _split_action_steps(text, services):
    """Split numbered/semicolon operations into logical lines.

    The pinball theme is a phone-first quick guide: one operation should stay on
    one horizontal line whenever width allows.  We therefore preserve explicit
    numbering and only use semicolons as a fallback splitter.
    """
    s = services.clean(str(text or ""))
    if not s:
        return ["按计划执行"]
    s = s.replace("\r", "\n")
    raw_lines = [services.clean(x) for x in s.split("\n") if services.clean(x)]
    if len(raw_lines) > 1:
        return raw_lines[:5]

    s = raw_lines[0] if raw_lines else s
    # 1. / 1、 / 1) / 1） / ① / （1） / (1)
    marker = re.compile(r'(?=(?:[①②③④⑤⑥⑦⑧⑨⑩]|[（(]?\d{1,2}[）)]|\d{1,2}[\.、]))')
    starts = [m.start() for m in marker.finditer(s)]
    if len(starts) >= 2:
        parts = []
        for i, st in enumerate(starts):
            ed = starts[i+1] if i+1 < len(starts) else len(s)
            part = services.clean(s[st:ed].strip(" ；;｜|"))
            if part:
                parts.append(part)
        if parts:
            return parts[:5]

    # A common spreadsheet style is "操作A；操作B；操作C" with no numbering.
    # Treat these as independent operations so each gets its own wide row.
    semi = [services.clean(x) for x in re.split(r"[；;]+", s) if services.clean(x)]
    if 1 < len(semi) <= 5:
        return semi
    return [s]


def _draw_day_metrics(base, guide, services, colors, rcfg, info, box, style):
    """Fixed-spec remaining/expected strip.

    V35.74: every Day and every metric uses the same cell height, icon box,
    icon size and text size. Long text is ellipsized; it is never silently
    shrunk differently from the other metrics.
    """
    items = list(info.get("metric_items") or [])[:4]
    if not items:
        return

    d = ImageDraw.Draw(base)
    x1, y1, x2, y2 = map(int, box)
    gap = int(rcfg.get("day_metric_gap", 7) or 7)
    count = len(items)
    cw = (x2 - x1 - gap * max(0, count - 1)) / max(1, count)
    cfg = guide.get("cfg") or {}

    icon_size = int(rcfg.get("day_metric_icon_size", 24) or 24)
    font_size = int(rcfg.get("day_metric_font_size", 16) or 16)
    font = services.get_font(font_size, True)
    icon_gap = int(rcfg.get("day_metric_icon_gap", 7) or 7)
    pad_x = int(rcfg.get("day_metric_pad_x", 10) or 10)

    for i, item in enumerate(items):
        a = int(round(x1 + i * (cw + gap)))
        b = int(round(a + cw))
        d.rounded_rectangle(
            (a, y1, b, y2),
            radius=8,
            fill=colors["metric_bg"],
            outline=colors["screen_edge"],
            width=1,
        )

        icon_box = min(icon_size, max(14, y2 - y1 - 8))
        ix = a + pad_x
        iy = int(y1 + (y2 - y1 - icon_box) / 2)
        icon = None
        try:
            icon = services.config_day_icon(cfg, item)
        except Exception:
            icon = None
        if icon and Path(icon).exists():
            services.draw_image_contain(
                base, Path(icon),
                (ix, iy, ix + icon_box, iy + icon_box)
            )

        label = services.clean(str(item.get("label") or ""))
        value = services.clean(str(item.get("value") or ""))
        shown = (label + ("  " + value if value else "")).strip()

        tx = ix + icon_box + icon_gap
        max_w = max(8, b - pad_x - tx)
        shown = _ellipsize_single_line(d, services, shown, font, max_w)
        bb = d.textbbox((0, 0), shown or " ", font=font)
        th = max(1, bb[3] - bb[1])
        ty = y1 + max(0, (y2 - y1 - th) / 2) - bb[1]
        d.text((tx, ty), shown, font=font, fill=colors["metric"])


def _day_slots(n):
    # V35.73: single-column wide mission inserts.  Width is more valuable than
    # decorative two-column density because each numbered operation should stay
    # on one readable line whenever possible.
    slots=[
        (154,632,926,792,"wide"),
        (154,802,926,962,"wide"),
        (154,972,926,1132,"wide"),
        (154,1142,926,1302,"wide"),
        (154,1312,926,1472,"wide"),
        (154,1482,926,1642,"wide"),
        (154,1652,926,1862,"final"),
    ]
    return slots[:max(0,min(7,n))]


def _draw_day_card(base, guide, services, tools, colors, rcfg, info, box, idx, role, style):
    d=ImageDraw.Draw(base)
    x1,y1,x2,y2=map(int,box)
    special=services.clean(str(info.get("special_label") or ""))
    is_final=role=="final"
    accent=colors["final"] if (special or is_final) else colors["accent2" if idx%2 else "accent"]
    if style=="neon":
        _glow_rounded(base,(x1,y1,x2,y2),16,colors["mission"],accent,7,70,accent,2)
    else:
        d.rounded_rectangle((x1+4,y1+5,x2+4,y2+5),radius=16,fill=colors["cabinet_shadow"])
        d.rounded_rectangle((x1,y1,x2,y2),radius=16,fill=colors["mission"],outline=accent,width=3)

    # Header: Day on the left, target on the right.  This removes a whole target
    # row and gives the actual operation text more room.
    header_y2 = y1 + 40
    d.rectangle((x1+10,y1+7,x2-10,header_y2),fill=colors["mission_header"],outline=accent,width=1)
    day=services.clean(str(info.get("day") or f"D{idx+1}"))
    label=day
    if special:
        label += " · " + special
    elif is_final:
        label += " · FINAL BALL"
    services.draw_left(d,(x1+22,y1+9,x1+340,header_y2-2),label,colors["mission_title"],
                       max_size=22 if not is_final else 25,min_size=15,bold=True,max_lines=1,line_gap=0,valign="center")
    target=services.clean(str(info.get("target") or ""))
    if target:
        services.draw_left(d,(x1+350,y1+9,x2-22,header_y2-2),"目标："+target,colors["muted"],
                           max_size=17 if not is_final else 18,min_size=12,bold=True,max_lines=1,line_gap=0,valign="center")

    metrics = list(info.get("metric_items") or [])[:4]
    metric_h = 34 if metrics else 0
    metric_y2 = y2 - 8
    metric_y1 = metric_y2 - metric_h
    action_y1 = header_y2 + 3
    action_y2 = (metric_y1 - 4) if metrics else (y2 - 9)

    action=services.clean(str(info.get("action") or "按计划执行"))
    lines=_split_action_steps(action, services)
    line_gap=3
    available=max(24, action_y2-action_y1)
    line_h=(available-line_gap*max(0,len(lines)-1))/max(1,len(lines))
    max_font=int(rcfg.get("day_action_font_size",23) or 23)+(2 if is_final else 0)
    min_font=int(rcfg.get("day_action_min_font_size",16) or 16)
    # One logical operation per row, max_lines=1.  A very long single operation
    # may shrink to min_font, but it will not silently become tiny multi-line text.
    for j,line in enumerate(lines):
        yy1=int(round(action_y1+j*(line_h+line_gap)))
        yy2=int(round(yy1+line_h))
        services.draw_left(d,(x1+22,yy1,x2-22,yy2),line,colors["text"],
                           max_size=max_font,min_size=min_font,bold=True,
                           max_lines=1,line_gap=0,valign="center")

    if metrics:
        _draw_day_metrics(base, guide, services, colors, rcfg, info,
                          (x1+20, metric_y1, x2-20, metric_y2), style)

    for xx in (x1+12,x2-12):
        if style == "steampunk":
            _bolt(d,(xx,y1+25),4,colors)
        else:
            _bulb(base,(xx,y1+25),4,accent,colors["lamp_hot"],style)


def _draw_playfield(base, guide, services, tools, colors, rcfg, style, rng):
    d=ImageDraw.Draw(base,"RGBA")
    outer=(96,590,984,2048)
    d.rounded_rectangle((100,596,988,2054),radius=36,fill=colors["cabinet_shadow"])
    d.rounded_rectangle(outer,radius=34,fill=colors["playfield"],outline=colors["edge"],width=5)
    d.rounded_rectangle((112,606,968,2032),radius=28,outline=colors["rail_hi"],width=2)

    # Real machine identity is pushed into the narrow side lanes so the wide
    # central reading column remains untouched.
    _rail(d,[(126,632),(126,1924),(214,1992),(330,1998)],colors,10)
    _rail(d,[(954,632),(954,1924),(866,1992),(750,1998)],colors,10)
    _rail(d,[(928,632),(944,760),(944,906)],colors,7)
    services.draw_center(d,(892,606,960,638),"LAUNCH",colors["accent2"],max_size=10,min_size=7,bold=True,max_lines=1,line_gap=0)

    # Bumpers live in side margins between card rows, never on top of text.
    for x,y,r in [(126,875,17),(954,1045,17),(126,1385,17),(954,1555,17)]:
        _bumper(base,(x,y),r,colors,style)

    days=list(guide.get("days") or [])[:7]
    for idx,(info,slot) in enumerate(zip(days,_day_slots(len(days)))):
        x1,y1,x2,y2,role=slot
        _draw_day_card(base,guide,services,tools,colors,rcfg,info,(x1,y1,x2,y2),idx,role,style)

    # Balls stay in the lanes / between mechanics.
    ball_colors=[colors["ball1"],colors["ball2"],colors["ball3"]]
    positions=[(125,730,11),(954,790,12),(126,1215,11),(954,1430,12),(126,1718,11),(954,1800,11)]
    jitter=int(rcfg.get("ball_jitter",8) or 8)
    for i,(x,y,r) in enumerate(positions):
        x+=rng.randint(-jitter,jitter); y+=rng.randint(-jitter,jitter)
        _ball(base,(x,y),r,ball_colors[i%len(ball_colors)],colors["ball_edge"])

    # Physical flippers and drain remain beneath the seven Day cards.
    _flipper(d,(350,1942),(505,1896),colors["flipper"],colors["edge_dark"],colors["rail_hi"])
    _flipper(d,(730,1942),(575,1896),colors["flipper"],colors["edge_dark"],colors["rail_hi"])
    d.ellipse((510,1930,570,1990),fill=colors["drain"],outline=colors["edge_dark"],width=4)
    services.draw_center(d,(503,1989,577,2017),"OUT",colors["muted"],max_size=10,min_size=7,bold=True,max_lines=1,line_gap=0)
    for x,c in [(430,colors["lamp"]),(540,colors["accent2"]),(650,colors["final"])]:
        _bulb(base,(x,2010),7,c,colors["lamp_hot"],style)


def _draw_risk_apron(base, guide, services, tools, colors, rcfg, style):
    d=ImageDraw.Draw(base)
    box=(104,2062,976,2248)
    if style=="neon":
        _glow_rounded(base,box,22,colors["apron"],colors["accent"],8,75,colors["accent2"],3)
    else:
        _bevel_panel(d,box,colors["apron"],colors["edge"],colors["rail_hi"],colors["cabinet_shadow"],20,4)
    tb=(382,2045,698,2100)
    d.polygon([(395,2045),(685,2045),(698,2059),(698,2086),(685,2100),(395,2100),(382,2086),(382,2059)],fill=colors["panel_header"],outline=colors["final"])
    services.draw_center(d,tb,rcfg.get("risk_title","WARNING / 提示"),colors["panel_title"],max_size=19,min_size=13,bold=True,max_lines=1,line_gap=0)
    risks=tools.risk_items(guide) or ["暂无额外风险提示"]
    top=2108; bottom=2237; gap=6
    rows=min(3,len(risks))
    rh=(bottom-top-gap*(rows-1))/max(1,rows)
    for i,text in enumerate(risks[:3]):
        y1=int(top+i*(rh+gap)); y2=int(y1+rh)
        accent=colors["final"] if i==0 else colors["accent2" if i%2 else "accent"]
        d.rounded_rectangle((148,y1,932,y2),radius=10,fill=colors["warning_bg"],outline=accent,width=2)
        _bulb(base,(166,(y1+y2)//2),5,accent,colors["lamp_hot"],style)
        services.draw_left(d,(184,y1+3,916,y2-3),"• "+text,colors["warning_text"],max_size=int(rcfg.get("risk_font_size",19) or 19),min_size=int(rcfg.get("risk_min_font_size",15) or 15),bold=True,max_lines=2,line_gap=2,valign="center")


def _draw_footer(base, guide, services, colors, style):
    """Footer with square QQ group avatar + large one-line group info."""
    d = ImageDraw.Draw(base)
    rcfg = _rcfg(guide)
    cfg = guide.get("cfg") or {}
    y1 = 2259
    box = (104, y1, 976, 2327)
    d.rounded_rectangle(box, radius=15, fill=colors["footer"], outline=colors["edge"], width=2)

    text = services.clean(str(guide.get("watermark") or cfg.get("watermark") or "攻略图生成器"))
    raw_icon = rcfg.get("group_avatar") or cfg.get("watermark_group_icon")
    icon_path = services.resolve_path(cfg, raw_icon) if raw_icon else None

    avatar_size = int(rcfg.get("footer_group_avatar_size", 44) or 44)
    avatar_size = max(28, min(52, avatar_size))
    avatar_gap = int(rcfg.get("footer_group_avatar_gap", 11) or 11)
    inner_x1, inner_x2 = 126, 954
    inner_y1, inner_y2 = y1 + 7, 2320
    available_w = inner_x2 - inner_x1

    max_font = int(rcfg.get("footer_font_size", 20) or 20)
    min_font = int(rcfg.get("footer_min_font_size", 16) or 16)
    icon_reserve = avatar_size + avatar_gap if icon_path else 0

    chosen = None
    shown = text
    for sz in range(max_font, min_font - 1, -1):
        f = services.get_font(sz, True)
        if services.text_width(d, text, f) + icon_reserve <= available_w:
            chosen = f
            break
    if chosen is None:
        chosen = services.get_font(min_font, True)
        shown = _ellipsize_single_line(
            d, services, text, chosen, max(8, available_w - icon_reserve)
        )

    text_w = services.text_width(d, shown, chosen)
    total_w = text_w + icon_reserve
    sx = inner_x1 + max(0, (available_w - total_w) / 2)

    if icon_path and Path(icon_path).exists():
        try:
            src = Image.open(icon_path).convert("RGBA")
            art = ImageOps.fit(
                src,
                (avatar_size - 4, avatar_size - 4),
                method=Image.Resampling.LANCZOS,
                centering=(0.5, 0.5),
            )
            frame = Image.new("RGBA", (avatar_size, avatar_size), colors["screen"])
            frame.alpha_composite(art, (2, 2))
            fd = ImageDraw.Draw(frame)
            fd.rectangle(
                (0, 0, avatar_size - 1, avatar_size - 1),
                outline=colors["rail_hi"],
                width=int(rcfg.get("footer_group_avatar_border_width", 2) or 2),
            )
            iy = int(inner_y1 + (inner_y2 - inner_y1 - avatar_size) / 2)
            base.alpha_composite(frame, (int(sx), iy))
            sx += avatar_size + avatar_gap
        except Exception:
            pass

    bb = d.textbbox((0, 0), shown or " ", font=chosen)
    th = max(1, bb[3] - bb[1])
    ty = inner_y1 + max(0, (inner_y2 - inner_y1 - th) / 2) - bb[1]
    d.text((sx, ty), shown, font=chosen, fill=colors["footer_text"])


def render(guide, out_path: Path, services):
    tools=SharedRendererTools(services)
    rcfg=_rcfg(guide)
    style=str(rcfg.get("page_style") or "classic").lower().strip()
    colors=tools.colors(guide,{
        "background":"#070812","cabinet_shadow":"#020207","cabinet":"#851E24","cabinet_dark":"#18121B",
        "edge":"#D7883E","edge_dark":"#270A0D","rail":"#C6CAD1","rail_hi":"#F7E7B0","rail_shadow":"#34343D",
        "bolt":"#AF7E4C","bolt_dark":"#3A2415","marquee":"#8D171B","badge":"#3C163B","badge_text":"#FFD86D",
        "title":"#FFF0A6","subtitle":"#FFE9CE","accent":"#FF4B35","accent2":"#3FE7FF","final":"#FFD246",
        "lamp":"#FF9B2F","lamp_hot":"#FFF8C7","panel":"#281525","panel_header":"#8B1C23","panel_title":"#FFF1B8",
        "screen":"#120E1B","screen_edge":"#614C69","score":"#FFE17C","text":"#FFF1C9","muted":"#C5B3B6",
        "playfield":"#241539","mission":"#25152E","mission_header":"#3A1733","mission_title":"#FFF2BF",
        "metric_bg":"#130D1A","metric":"#FFE7A2","bumper":"#E54B3D","bumper_glow":"#FF603F",
        "ball1":"#F4443D","ball2":"#3EC7FF","ball3":"#FFD34E","ball_edge":"#34121C","flipper":"#EF593F","drain":"#09070D",
        "apron":"#251521","warning_bg":"#130E19","warning_text":"#FFF0CE","footer":"#171019","footer_text":"#D8C5C2",
        "ticket":"#F1C968","ticket_edge":"#77451D",
        "primary":"#FF4B35","dark":"#070812","light":"#FFF0A6","chip":"#281525",
    })
    # Convert colours to RGB strings/tuples are both fine for PIL.
    img=Image.new("RGBA",(int(services.W),int(services.H)),colors["background"])
    rng=_rng(guide,"page")
    _draw_background(img,guide,colors,style,rng)
    _draw_cabinet_shell(img,colors,style)
    _draw_marquee(img,guide,services,colors,rcfg,style)
    if style == "steampunk":
        _draw_steampunk_decor(img,colors)

    # Classic red cabinet: reclaimed marquee height is given directly to the
    # resource/reward rows. Other variants retain their established proportions.
    side_top = 258 if style == "classic" else 302
    _draw_kpi_panel(img,guide,services,tools,colors,(42,side_top,342,574))
    _draw_reward_panel(img,guide,services,tools,colors,(738,side_top,1038,574))
    _draw_score_center(img,guide,services,colors,rcfg,style)


    _draw_playfield(img,guide,services,tools,colors,rcfg,style,rng)
    _draw_risk_apron(img,guide,services,tools,colors,rcfg,style)
    _draw_footer(img,guide,services,colors,style)
    tools.save(img,out_path,guide)
