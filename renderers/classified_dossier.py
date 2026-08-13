# -*- coding: utf-8 -*-
"""Classified dossier / investigation file renderer.

Design goals:
- black / charcoal paper dossier with red warning accents
- stacked, slightly rotated file cards rather than clean UI panels
- dynamic-height D1..Dn cards so long steps never need to be crushed into tiny text
- reward / KPI / day metrics keep original game icons for recognition
- all aging / grain is deterministic for stable re-renders
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
import hashlib
import os
import math
import random
import re
import time

from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageChops

from .shared import SharedRendererTools
from .reward_items import RewardItemRenderer

STYLE_IDS = ("classified_dossier",)


def _renderer_cfg(guide):
    theme_cfg = guide.get("theme_config") or {}
    rc = theme_cfg.get("renderer") if isinstance(theme_cfg.get("renderer"), dict) else {}
    cfg = dict(rc or {})
    project_cfg = guide.get("cfg") or {}
    if isinstance(project_cfg.get("classified_dossier"), dict):
        cfg.update(project_cfg.get("classified_dossier") or {})
    return cfg


def _seed(guide, salt=""):
    raw = "{}|{}|{}|{}".format(
        guide.get("title") or "",
        guide.get("sheet") or "",
        guide.get("variant_id") or "",
        salt,
    )
    return int(hashlib.sha256(raw.encode("utf-8", "ignore")).hexdigest()[:16], 16)


def _rng(guide, salt=""):
    return random.Random(_seed(guide, salt))


def _resolve_path(guide, services, raw):
    if not raw:
        return None
    cfg = guide.get("cfg") or {}
    try:
        p = services.resolve_path(cfg, raw)
        if p and Path(p).is_file():
            return Path(p)
    except Exception:
        pass
    p = Path(str(raw))
    if p.is_file():
        return p
    p2 = Path.cwd() / str(raw)
    return p2 if p2.is_file() else None


@lru_cache(maxsize=96)
def _font_cached(path_text, mtime_ns, size):
    try:
        if path_text and Path(path_text).exists():
            return ImageFont.truetype(path_text, max(1, int(size)))
    except Exception:
        pass
    return None


@lru_cache(maxsize=1)
def _system_font_inventory():
    """Build a small installed-font filename index without bundling any font files."""
    roots = []
    windir = os.environ.get("WINDIR")
    if windir:
        roots.append(Path(windir) / "Fonts")
    localapp = os.environ.get("LOCALAPPDATA")
    if localapp:
        roots.append(Path(localapp) / "Microsoft" / "Windows" / "Fonts")
    roots.extend([
        Path("C:/Windows/Fonts"),
        Path("/System/Library/Fonts"),
        Path("/Library/Fonts"),
        Path.home() / "Library" / "Fonts",
        Path("/usr/share/fonts"),
        Path("/usr/local/share/fonts"),
        Path.home() / ".local" / "share" / "fonts",
        Path.home() / ".fonts",
    ])
    inventory = {}
    seen = set()
    for root in roots:
        try:
            root = root.expanduser()
            key = str(root.resolve()) if root.exists() else str(root)
        except Exception:
            key = str(root)
        if key in seen or not root.exists():
            continue
        seen.add(key)
        try:
            for fp in root.rglob("*"):
                if fp.is_file() and fp.suffix.lower() in {".ttf", ".ttc", ".otf"}:
                    inventory.setdefault(fp.name.lower(), fp)
        except Exception:
            continue
    return inventory


def _auto_font_path(role):
    role = str(role or "body").lower()
    if role in {"title", "stamp"}:
        names = [
            "SourceHanSansSC-Heavy.otf", "SourceHanSansCN-Heavy.otf",
            "SourceHanSansSC-Bold.otf", "SourceHanSansCN-Bold.otf",
            "NotoSansCJKsc-Bold.otf", "NotoSansCJK-Bold.ttc",
            "msyhbd.ttc", "PingFang.ttc", "simhei.ttf", "wqy-zenhei.ttc",
        ]
    else:
        names = [
            "SourceHanSansSC-Regular.otf", "SourceHanSansCN-Regular.otf",
            "NotoSansCJKsc-Regular.otf", "NotoSansCJK-Regular.ttc",
            "msyh.ttc", "PingFang.ttc", "simhei.ttf", "wqy-zenhei.ttc",
        ]
    inv = _system_font_inventory()
    for name in names:
        fp = inv.get(name.lower())
        if fp and fp.exists():
            return fp
    return None


class _Fonts:
    def __init__(self, guide, services, rcfg):
        self.s = services
        self.guide = guide
        self.title_path = _resolve_path(guide, services, rcfg.get("title_font_path") or rcfg.get("font_path")) or _auto_font_path("title")
        self.body_path = _resolve_path(guide, services, rcfg.get("body_font_path") or rcfg.get("font_path")) or _auto_font_path("body")
        self.stamp_path = _resolve_path(guide, services, rcfg.get("stamp_font_path") or rcfg.get("body_font_path") or rcfg.get("font_path")) or _auto_font_path("stamp")
        try:
            self.scale = max(0.70, float(rcfg.get("font_scale", 1.0) or 1.0))
        except Exception:
            self.scale = 1.0

    def _get(self, path, size, bold=False):
        size = max(1, int(round(size * self.scale)))
        if path:
            try:
                mt = path.stat().st_mtime_ns
            except Exception:
                mt = 0
            f = _font_cached(str(path), mt, size)
            if f is not None:
                return f
        return self.s.get_font(size, bold)

    def title(self, size, bold=True):
        return self._get(self.title_path, size, bold)

    def body(self, size, bold=False):
        return self._get(self.body_path, size, bold)

    def stamp(self, size, bold=True):
        return self._get(self.stamp_path, size, bold)


def _text_w(draw, text, font):
    try:
        return float(draw.textlength(str(text or ""), font=font))
    except Exception:
        b = draw.textbbox((0, 0), str(text or " "), font=font)
        return float(max(0, b[2] - b[0]))


def _line_h(draw, font):
    b = draw.textbbox((0, 0), "国Ag", font=font)
    return max(1, b[3] - b[1])


def _wrap_paragraph(draw, text, font, max_width):
    text = str(text or "")
    if not text:
        return [""]
    out = []
    line = ""
    for ch in text:
        if ch == "\n":
            out.append(line)
            line = ""
            continue
        test = line + ch
        if line and _text_w(draw, test, font) > max_width:
            out.append(line)
            line = ch
        else:
            line = test
    if line or not out:
        out.append(line)
    return out


def _wrap_steps(draw, action, font, max_width):
    text = str(action or "").replace("\r", "").strip()
    parts = [p.strip() for p in text.split("\n") if p.strip()]
    if not parts:
        parts = ["—"]
    out = []
    for idx, part in enumerate(parts):
        lines = _wrap_paragraph(draw, part, font, max_width)
        out.extend(lines)
        if idx < len(parts) - 1:
            out.append("__STEP_GAP__")
    return out


def _draw_wrapped(draw, xy, lines, font, fill, line_gap=6, gap_after_step=4):
    x, y = xy
    h = _line_h(draw, font)
    for line in lines:
        if line == "__STEP_GAP__":
            y += gap_after_step
            continue
        draw.text((x, y), line, font=font, fill=fill)
        y += h + line_gap
    return y


def _fit_title_font(draw, fonts, text, max_w, start=54, min_size=30):
    for size in range(int(start), int(min_size) - 1, -1):
        f = fonts.title(size, True)
        if _text_w(draw, text, f) <= max_w:
            return f
    return fonts.title(min_size, True)


def _compose_bilingual(cn, en):
    cn = str(cn or "").strip()
    en = str(en or "").strip()
    if cn and en:
        return f"{cn} / {en}"
    return cn or en


def _day_title_bilingual(info, services, rcfg):
    """Theme-local bilingual day title.

    ``第3档`` -> ``D3｜目标 第3档 / TARGET TIER 3``.
    Other targets -> ``D3｜目标 / TARGET：目标内容``.
    """
    clean = services.clean
    day = clean(str(info.get("day") or "DAY"))
    target = clean(str(info.get("target") or ""))
    if not target:
        return day
    cn = clean(str(rcfg.get("target_label_cn") or "目标"))
    en = clean(str(rcfg.get("target_label_en") or "TARGET"))
    tier_en = clean(str(rcfg.get("target_tier_en") or "TIER"))
    m = re.fullmatch(r"第\s*([^档]+?)\s*档", target)
    if m:
        left = (cn + " " + target).strip() if cn else target
        if en:
            token = clean(m.group(1))
            right = (en + (" " + tier_en if tier_en else "") + (" " + token if token else "")).strip()
            return day + "｜" + left + " / " + right
        return day + "｜" + left
    label = _compose_bilingual(cn, en)
    return day + ("｜" + label + "：" + target if label else "｜" + target)


def _hex_rgb(value, fallback=(60, 60, 60)):
    text = str(value or "").strip().lstrip("#")
    if len(text) == 6:
        try:
            return tuple(int(text[i:i+2], 16) for i in (0, 2, 4))
        except Exception:
            pass
    return fallback


def _mix_color(a, b, t=0.18):
    ca = _hex_rgb(a)
    cb = _hex_rgb(b, ca)
    t = max(0.0, min(1.0, float(t)))
    c = tuple(round(ca[i] * (1-t) + cb[i] * t) for i in range(3))
    return "#%02X%02X%02X" % c


_QUALITY_FALLBACK = {
    "white": "#CBD6E2",
    "green": "#65C86B",
    "blue": "#5DA8FF",
    "purple": "#B16CFF",
    "orange": "#F2A43A",
    "red": "#E35A55",
    "pink": "#FF78B6",
    "chaoyue": "#FFD45E",
    "jueshi": "#F4F0E7",
}


def _fit_header_title(draw, fonts, text, max_w, start=52, min_size=30, max_lines=2):
    for size in range(int(start), int(min_size)-1, -1):
        f = fonts.title(size, True)
        lines = _wrap_paragraph(draw, text, f, max_w)
        if len(lines) <= max_lines:
            return f, lines
    f = fonts.title(min_size, True)
    lines = _wrap_paragraph(draw, text, f, max_w)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        if lines:
            last = lines[-1]
            while last and _text_w(draw, last + "…", f) > max_w:
                last = last[:-1]
            lines[-1] = (last + "…") if last else "…"
    return f, lines


def _grain_overlay(size, rng, alpha=20, coarse=False):
    w, h = size
    # low-cost deterministic paper grain using sparse dots + blurred cloudy patches
    layer = Image.new("RGBA", size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    dot_count = max(400, int((w * h) / (5500 if coarse else 8000)))
    for _ in range(dot_count):
        x = rng.randrange(0, w)
        y = rng.randrange(0, h)
        v = rng.choice([(255,255,255,alpha//2), (0,0,0,alpha)])
        r = 1 if rng.random() < 0.92 else rng.randint(2, 4)
        d.ellipse((x-r, y-r, x+r, y+r), fill=v)
    for _ in range(max(12, int(h / 220))):
        x = rng.randrange(-40, w)
        y = rng.randrange(0, h)
        length = rng.randint(50, 260)
        col = (235, 226, 205, rng.randint(8, 20))
        d.line((x, y, min(w+20, x+length), y+rng.randint(-2,2)), fill=col, width=1)
    return layer


def _rough_line(draw, pts, fill, width, rng, jitter=2, passes=1):
    pts = list(pts)
    for _ in range(max(1, passes)):
        jpts = []
        for x, y in pts:
            jpts.append((int(x + rng.randint(-jitter, jitter)), int(y + rng.randint(-jitter, jitter))))
        draw.line(jpts, fill=fill, width=max(1, int(width)))


def _corner_marks(draw, box, color, width=3, inset=18, arm=34):
    x1,y1,x2,y2 = map(int, box)
    pts = [
        ((x1+inset+arm,y1+inset),(x1+inset,y1+inset),(x1+inset,y1+inset+arm)),
        ((x2-inset-arm,y1+inset),(x2-inset,y1+inset),(x2-inset,y1+inset+arm)),
        ((x1+inset,y2-inset-arm),(x1+inset,y2-inset),(x1+inset+arm,y2-inset)),
        ((x2-inset-arm,y2-inset),(x2-inset,y2-inset),(x2-inset,y2-inset-arm)),
    ]
    for p in pts:
        draw.line(p, fill=color, width=width, joint="curve")


def _texture_card(card, rng, strength=1.0):
    if strength <= 0:
        return card
    card.alpha_composite(_grain_overlay(card.size, rng, alpha=int(18*strength), coarse=True))
    d = ImageDraw.Draw(card)
    for _ in range(max(4, int(card.height / 150))):
        if rng.random() < 0.65:
            y = rng.randint(10, max(11, card.height-10))
            x = rng.randint(5, max(6, card.width-100))
            l = rng.randint(30, 150)
            d.line((x,y,min(card.width-5,x+l),y+rng.randint(-1,1)), fill=(230,220,198,rng.randint(10,24)), width=1)
    return card


def _paste_rotated(base, card, center_x, top_y, angle, shadow=True, shadow_alpha=125):
    pad = 12
    if shadow:
        alpha = card.getchannel("A")
        shadow_im = Image.new("RGBA", card.size, (0,0,0,0))
        shadow_im.putalpha(alpha.point(lambda p: int(p * shadow_alpha / 255)))
        sh = shadow_im.rotate(angle, resample=Image.BICUBIC, expand=True)
        sx = int(center_x - sh.width/2 + 10)
        sy = int(top_y + 12)
        base.alpha_composite(sh, (sx, sy))
    rot = card.rotate(angle, resample=Image.BICUBIC, expand=True)
    x = int(center_x - rot.width/2)
    y = int(top_y)
    base.alpha_composite(rot, (x,y))
    return y + rot.height + pad


def _draw_card_shell(size, colors, title, file_no, fonts, rng, special=False):
    w,h = size
    card = Image.new("RGBA", size, colors["card"])
    d = ImageDraw.Draw(card)
    border = colors["border"]
    red = colors["red"]
    ink = colors["ink"]
    # outer edge + inner dossier frame
    d.rectangle((1,1,w-2,h-2), outline=colors["shadow_edge"], width=4)
    d.rectangle((10,10,w-11,h-11), outline=border, width=2)
    d.rectangle((20,20,w-21,h-21), outline=border, width=2)
    _corner_marks(d, (20,20,w-21,h-21), border, width=3, inset=0, arm=26)
    header_h = 66
    d.rectangle((22,22,w-23,22+header_h), fill=colors["red_dark"] if special else red)
    # slightly uneven red header edge
    _rough_line(d, [(22,22+header_h),(w-23,22+header_h)], colors["red_deep"], 3, rng, 2, 1)
    fnum = fonts.body(16, True)
    d.text((36, 33), str(file_no), font=fnum, fill=colors["header_ink"])
    title_max_w=w-230
    priority_box=None
    if special:
        sfont = fonts.stamp(16, True)
        label = "PRIORITY / 重点"
        sw = _text_w(d, label, sfont)
        bx2 = w-42
        bx1 = int(bx2-sw-34)
        priority_box=(bx1,bx2,sfont,label)
        title_max_w=max(120,bx1-150)
    ftitle = _fit_title_font(d, fonts, title, max_w=title_max_w, start=31, min_size=20)
    d.text((132, 27), title, font=ftitle, fill=colors["header_ink"])
    if priority_box:
        bx1,bx2,sfont,label=priority_box
        d.rectangle((bx1,31,bx2,70), outline=colors["header_ink"], width=2)
        d.text((bx1+16,39), label, font=sfont, fill=colors["header_ink"])
    return _texture_card(card, rng, 1.0)


def _draw_stamp(text, fonts, color, rng, diameter=190):
    layer = Image.new("RGBA", (diameter+80, diameter+80), (0,0,0,0))
    d = ImageDraw.Draw(layer)
    c = layer.width//2
    r = diameter//2
    # slightly imperfect double ring
    for pass_i in range(2):
        offx = rng.randint(-3,3); offy = rng.randint(-3,3)
        d.ellipse((c-r+offx,c-r+offy,c+r+offx,c+r+offy), outline=color, width=5 if pass_i==0 else 2)
    # diagonal rectangular stamp band
    band = Image.new("RGBA", (diameter+30, 88), (0,0,0,0))
    bd = ImageDraw.Draw(band)
    bd.rectangle((3,3,band.width-4,band.height-4), outline=color, width=5)
    f = fonts.stamp(28, True)
    lines = [x for x in str(text or "内部攻略\n禁止外传").split("\n") if x]
    if len(lines) == 1:
        lines = [lines[0]]
    total_h = len(lines) * 32
    yy = (band.height-total_h)//2
    for line in lines[:2]:
        tw = _text_w(bd, line, f)
        bd.text(((band.width-tw)/2, yy), line, font=f, fill=color)
        yy += 32
    band = band.rotate(-8 + rng.uniform(-2,2), resample=Image.BICUBIC, expand=True)
    layer.alpha_composite(band, (int(c-band.width/2), int(c-band.height/2)))
    # distress the stamp with transparent pinholes
    mask = layer.getchannel("A")
    md = ImageDraw.Draw(mask)
    for _ in range(150):
        x = rng.randrange(0, layer.width); y=rng.randrange(0,layer.height)
        rr = rng.choice([1,1,1,2,3])
        md.ellipse((x-rr,y-rr,x+rr,y+rr), fill=rng.randint(0,80))
    layer.putalpha(mask)
    return layer


def _draw_author(base, guide, services, fonts, colors, rcfg, x, y, max_w=600):
    cfg = guide.get("cfg") or {}
    author = cfg.get("author") if isinstance(cfg.get("author"), dict) else {}
    name = services.clean(str(rcfg.get("author_text") if "author_text" in rcfg else author.get("text") or "")) or "攻略作者"
    prefix = services.clean(str(rcfg.get("author_prefix") if "author_prefix" in rcfg else author.get("prefix") or "攻略制作"))
    sep = str(rcfg.get("author_separator") or " / ")
    show_avatar = bool(rcfg.get("show_author_avatar", False))
    avatar_raw = rcfg.get("author_avatar") or author.get("qq_avatar") or author.get("avatar") or author.get("icon")
    avatar = _resolve_path(guide, services, avatar_raw) if show_avatar else None
    d = ImageDraw.Draw(base)
    f = fonts.body(int(rcfg.get("author_font_size", 20) or 20), True)
    label = (prefix + sep + name) if prefix else name
    d.text((x, y+6), label, font=f, fill=colors["muted"])
    tw = _text_w(d, label, f)
    if avatar:
        size = int(rcfg.get("author_avatar_size", 46) or 46)
        try:
            src = Image.open(avatar).convert("RGBA")
            src.thumbnail((size,size), Image.LANCZOS)
            photo = Image.new("RGBA", (size+8,size+8), colors["paper"])
            px=(photo.width-src.width)//2; py=(photo.height-src.height)//2
            photo.alpha_composite(src,(px,py))
            pd=ImageDraw.Draw(photo); pd.rectangle((0,0,photo.width-1,photo.height-1), outline=colors["muted"], width=2)
            base.alpha_composite(photo,(int(x+tw+14), y-2))
        except Exception:
            pass


def _draw_budget_card(guide, services, fonts, colors, width, rng):
    rcfg = _renderer_cfg(guide)
    try:
        max_items = max(1, int(rcfg.get("budget_max_items", 6) or 6))
    except Exception:
        max_items = 6
    try:
        kpis = services.build_render_kpis((guide.get("kpis") or [])[:max_items], guide.get("cfg") or {})
    except Exception:
        kpis = []
        for pair in (guide.get("kpis") or [])[:max_items]:
            if isinstance(pair, (list, tuple)) and len(pair) >= 2:
                kpis.append({"label": services.clean(str(pair[0])), "value": services.clean(str(pair[1]))})
            elif isinstance(pair, dict):
                kpis.append(pair)
    items = list(kpis or [])[:max_items]
    n = len(items)
    if n <= 3:
        cols = max(1, n)
    elif n == 4:
        cols = 2
    else:
        cols = 3
    rows = max(1, math.ceil(max(1, n) / cols))
    content_top = 104
    gap = 12
    cell_h = int(rcfg.get("budget_cell_height", 94) or 94)
    h = content_top + rows * cell_h + max(0, rows-1) * gap + 28
    title = _compose_bilingual(rcfg.get("budget_title_cn", "资源预算"), rcfg.get("budget_title_en", "RESOURCE BUDGET"))
    card = _draw_card_shell((width,h), colors, title, str(rcfg.get("budget_file_no") or "FILE-01"), fonts, rng)
    d = ImageDraw.Draw(card)
    if not items:
        return card
    cw=(width-68-gap*(cols-1))/max(1,cols)
    for i,item in enumerate(items):
        row=i//cols; col=i%cols
        x1=int(34+col*(cw+gap)); x2=int(x1+cw)
        y1=int(content_top+row*(cell_h+gap)); y2=y1+cell_h
        d.rectangle((x1,y1,x2,y2), fill=colors["panel"], outline=colors["line"], width=1)
        icon=item.get("icon")
        icon_size=min(54, max(40, cell_h-34))
        tx=x1+14
        if icon and Path(str(icon)).exists():
            iy=y1+(cell_h-icon_size)//2
            services.draw_image_contain(card, Path(icon), (x1+14, iy, x1+14+icon_size, iy+icon_size))
            tx=x1+14+icon_size+12
        label=services.clean(str(item.get("label") or ""))
        val=services.clean(str(item.get("value") or ""))
        lf=fonts.body(15,True); vf=fonts.body(22,True)
        d.text((tx,y1+13),label,font=lf,fill=colors["muted"])
        lines=_wrap_paragraph(d,val,vf,max(40,x2-tx-12))[:2]
        yy=y1+36
        for line in lines:
            d.text((tx,yy),line,font=vf,fill=colors["ink"]); yy += _line_h(d,vf)+2
    return card



def _reward_leaves(guide, services):
    tools = SharedRendererTools(services)
    return tools.flat_reward_items(guide.get("reward_items") or [])


def _draw_reward_card(guide, services, fonts, colors, width, rng):
    rcfg=_renderer_cfg(guide)
    try:
        max_items=max(1,int(rcfg.get("reward_max_items",6) or 6))
    except Exception:
        max_items=6
    leaves=_reward_leaves(guide,services)[:max_items]
    rows=max(1,math.ceil(len(leaves)/3))
    row_stride=112
    cell_h=98
    h=132+rows*row_stride
    title=_compose_bilingual(rcfg.get("reward_title_cn","可兑换奖励"),rcfg.get("reward_title_en","REWARD INVENTORY"))
    card=_draw_card_shell((width,h),colors,title,str(rcfg.get("reward_file_no") or "FILE-02"),fonts,rng)
    d=ImageDraw.Draw(card)
    if not leaves:
        f=fonts.body(22,False)
        text=SharedRendererTools(services).reward_summary(guide)
        _draw_wrapped(d,(46,112),_wrap_paragraph(d,text,f,width-92),f,colors["ink"],6)
        return card
    cfg=guide.get("cfg") or {}
    cols=min(3,max(1,len(leaves)))
    gap=12; cw=(width-84-gap*(cols-1))/cols
    show_quality=bool(rcfg.get("reward_quality_background",True))
    reward_renderer=RewardItemRenderer(services,guide)
    for i,item in enumerate(leaves):
        row=i//cols; col=i%cols
        x1=int(34+col*(cw+gap)); y1=104+row*row_stride; x2=int(x1+cw); y2=y1+cell_h
        d.rectangle((x1,y1,x2,y2), fill=colors["panel"], outline=colors["line"], width=1)
        resolved=reward_renderer.resolve(item)
        icon_path=resolved.get("icon_path")
        q=resolved.get("quality") or ""
        frame_path=resolved.get("frame_path") if show_quality else None
        has_real_frame=bool(frame_path and Path(frame_path).exists())
        ib=(x1+14,y1+12,x1+80,y1+78)
        if show_quality and q and not has_real_frame:
            qc=_QUALITY_FALLBACK.get(q, colors["line"])
            fill=_mix_color(colors["panel"],qc,0.20)
            d.rounded_rectangle(ib, radius=10, fill=fill, outline=qc, width=2)
        resolved=reward_renderer.draw_icon(
            card,item,ib,
            draw_quality_frame=bool(show_quality),
            assume_quality_frame=bool(show_quality and q),
            # Framed reward geometry is global; frameless dossier variants may keep a custom plain inset.
            plain_inset=int(rcfg.get("reward_item_plain_inner_inset",8) or 8),
            trim_transparent=bool(rcfg.get("reward_icon_trim_transparent",True)),
        )
        icon_path=resolved.get("icon_path")
        if not (icon_path and Path(icon_path).exists()) and show_quality and q:
            ph=fonts.body(15,True)
            mark="品质"
            tw=_text_w(d,mark,ph)
            d.text(((ib[0]+ib[2]-tw)/2,ib[1]+24),mark,font=ph,fill=_QUALITY_FALLBACK.get(q,colors["muted"]))
        nf=fonts.body(18,True); qf=fonts.body(21,True)
        name=services.clean(str(item.get("name") or "物品"))
        qty=services.clean(str(item.get("qty") or ""))
        name_lines=_wrap_paragraph(d,name,nf,max(30,x2-(x1+94)-12))[:2]
        yy=y1+13
        for line in name_lines:
            d.text((x1+94,yy),line,font=nf,fill=colors["ink"]); yy += _line_h(d,nf)+1
        if qty:
            d.text((x1+94,y2-34),"× "+qty,font=qf,fill=colors["red"])
    return card



def _draw_prep_card(guide, services, fonts, colors, width, rng):
    """Compact combined resource + reward card to save vertical space."""
    rcfg=_renderer_cfg(guide)
    tools=SharedRendererTools(services)
    try:
        max_budget=max(1,int(rcfg.get("budget_max_items",6) or 6))
    except Exception:
        max_budget=6
    try:
        kpis=services.build_render_kpis((guide.get("kpis") or [])[:max_budget], guide.get("cfg") or {})
    except Exception:
        kpis=[]
        for pair in (guide.get("kpis") or [])[:max_budget]:
            if isinstance(pair,(list,tuple)) and len(pair)>=2:
                kpis.append({"label":services.clean(str(pair[0])),"value":services.clean(str(pair[1]))})
            elif isinstance(pair,dict):
                kpis.append(pair)
    budget_items=list(kpis or [])[:max_budget]

    try:
        max_rewards=max(1,int(rcfg.get("reward_max_items",6) or 6))
    except Exception:
        max_rewards=6
    leaves=_reward_leaves(guide,services)[:max_rewards]

    outer_pad=34
    col_gap=18
    inner_w=(width-outer_pad*2-col_gap)//2
    sub_title_h=30
    cell_gap=8
    budget_cols=2 if len(budget_items)>1 else 1
    reward_cols=2 if len(leaves)>1 else 1
    budget_rows=max(1, math.ceil(max(1,len(budget_items))/budget_cols))
    reward_rows=max(1, math.ceil(max(1,len(leaves))/reward_cols))
    budget_cell_h=max(68,int(rcfg.get("prep_budget_cell_height",72) or 72))
    reward_cell_h=max(74,int(rcfg.get("prep_reward_cell_height",78) or 78))
    content_h=max(
        sub_title_h + budget_rows*budget_cell_h + max(0,budget_rows-1)*cell_gap,
        sub_title_h + reward_rows*reward_cell_h + max(0,reward_rows-1)*cell_gap,
    )
    h=108+content_h+30
    title=_compose_bilingual(rcfg.get("prep_title_cn","行动准备"),rcfg.get("prep_title_en","OPERATION PREP"))
    card=_draw_card_shell((width,h),colors,title,str(rcfg.get("prep_file_no") or "FILE-00"),fonts,rng)
    d=ImageDraw.Draw(card)
    left_x=outer_pad
    right_x=outer_pad+inner_w+col_gap
    top=104
    sf=fonts.body(16,True)
    budget_title=_compose_bilingual(rcfg.get("budget_title_cn","资源预算"),rcfg.get("budget_title_en","RESOURCE BUDGET"))
    reward_title=_compose_bilingual(rcfg.get("reward_title_cn","可兑换奖励"),rcfg.get("reward_title_en","REWARD INVENTORY"))
    d.text((left_x,top),budget_title,font=sf,fill=colors["red"])
    d.text((right_x,top),reward_title,font=sf,fill=colors["red"])
    d.line((left_x+inner_w+col_gap//2,top,right_x-col_gap//2,top+content_h),fill=colors["line"],width=1)

    # budget: compact 2-column cells
    if budget_items:
        bw=(inner_w-cell_gap*(budget_cols-1))/budget_cols
        for i,item in enumerate(budget_items):
            row=i//budget_cols; col=i%budget_cols
            x1=int(left_x+col*(bw+cell_gap)); y1=int(top+sub_title_h+row*(budget_cell_h+cell_gap)); x2=int(x1+bw); y2=y1+budget_cell_h
            d.rectangle((x1,y1,x2,y2),fill=colors["panel"],outline=colors["line"],width=1)
            icon=item.get("icon")
            icon_size=min(38,max(28,budget_cell_h-28))
            tx=x1+10
            if icon and Path(str(icon)).exists():
                iy=y1+(budget_cell_h-icon_size)//2
                services.draw_image_contain(card,Path(icon),(x1+9,iy,x1+9+icon_size,iy+icon_size))
                tx=x1+9+icon_size+8
            label=services.clean(str(item.get("label") or "")); val=services.clean(str(item.get("value") or ""))
            lf=fonts.body(15,True); vf=fonts.body(20,True)
            label_lines=_wrap_paragraph(d,label,lf,max(30,x2-tx-8))[:1]
            d.text((tx,y1+9),label_lines[0] if label_lines else "",font=lf,fill=colors["muted"])
            vlines=_wrap_paragraph(d,val,vf,max(30,x2-tx-8))[:1]
            d.text((tx,y1+32),vlines[0] if vlines else "",font=vf,fill=colors["ink"])

    # rewards: compact 2-column inventory cells
    if leaves:
        cfg=guide.get("cfg") or {}
        show_quality=bool(rcfg.get("reward_quality_background",True))
        reward_renderer=RewardItemRenderer(services,guide)
        rw=(inner_w-cell_gap*(reward_cols-1))/reward_cols
        for i,item in enumerate(leaves):
            row=i//reward_cols; col=i%reward_cols
            x1=int(right_x+col*(rw+cell_gap)); y1=int(top+sub_title_h+row*(reward_cell_h+cell_gap)); x2=int(x1+rw); y2=y1+reward_cell_h
            d.rectangle((x1,y1,x2,y2),fill=colors["panel"],outline=colors["line"],width=1)
            resolved=reward_renderer.resolve(item)
            icon_path=resolved.get("icon_path")
            q=resolved.get("quality") or ""
            frame_path=resolved.get("frame_path") if show_quality else None
            has_real_frame=bool(frame_path and Path(frame_path).exists())
            # Keep reward icons visually prominent even in the compact preparation card.
            # V35.29 restores them close to the original standalone reward-card scale.
            try:
                reward_icon_size=max(52,min(int(rcfg.get("prep_reward_icon_size",66) or 66), reward_cell_h-10))
            except Exception:
                reward_icon_size=min(66,reward_cell_h-10)
            icon_left=x1+7
            icon_top=y1+(reward_cell_h-reward_icon_size)//2
            ib=(icon_left,icon_top,icon_left+reward_icon_size,icon_top+reward_icon_size)
            text_x=ib[2]+9
            if show_quality and q and not has_real_frame:
                qc=_QUALITY_FALLBACK.get(q,colors["line"]); fill=_mix_color(colors["panel"],qc,0.20)
                d.rounded_rectangle(ib,radius=8,fill=fill,outline=qc,width=2)
            reward_renderer.draw_icon(
                card,item,ib,
                draw_quality_frame=bool(show_quality),
                assume_quality_frame=bool(show_quality and q),
                # Framed reward geometry is global; frameless dossier variants may keep a custom plain inset.
                plain_inset=int(rcfg.get("reward_item_plain_inner_inset",8) or 8),
                trim_transparent=bool(rcfg.get("reward_icon_trim_transparent",True)),
            )
            nf=fonts.body(16,True); qf=fonts.body(19,True)
            name=services.clean(str(item.get("name") or "物品")); qty=services.clean(str(item.get("qty") or ""))
            name_lines=_wrap_paragraph(d,name,nf,max(30,x2-text_x-7))[:2]
            yy=y1+8
            for line in name_lines:
                d.text((text_x,yy),line,font=nf,fill=colors["ink"]); yy+=_line_h(d,nf)
            if qty:
                d.text((text_x,y2-26),"× "+qty,font=qf,fill=colors["red"])
    else:
        f=fonts.body(16,False)
        text=tools.reward_summary(guide)
        _draw_wrapped(d,(right_x,top+sub_title_h+8),_wrap_paragraph(d,text,f,inner_w),f,colors["ink"],4)
    return card

def _metric_icon_path(guide, services, item):
    try:
        p=services.config_day_icon(guide.get("cfg") or {}, item)
        return Path(p) if p and Path(p).exists() else None
    except Exception:
        return None


def _day_card_height(guide, services, fonts, info, width):
    rcfg=_renderer_cfg(guide)
    tmp=Image.new("RGBA",(width,400),(0,0,0,0)); d=ImageDraw.Draw(tmp)
    body_font=fonts.body(max(12,int(rcfg.get("day_action_font_size",26) or 26)),False)
    left_w=width-330-70
    lines=_wrap_steps(d, info.get("action") or "", body_font, left_w)
    line_count=sum(1 for x in lines if x != "__STEP_GAP__")
    gaps=sum(1 for x in lines if x == "__STEP_GAP__")
    line_gap=max(0,int(rcfg.get("day_action_line_gap",7) or 7))
    step_gap=max(0,int(rcfg.get("day_action_step_gap",7) or 7))
    text_h=line_count*(_line_h(d,body_font)+line_gap)+gaps*step_gap
    # STATUS panel needs room for its title plus every metric row. Keep this
    # independent from action text so the final expected value can never be clipped.
    metric_count=len(info.get("metric_items") or [])
    metric_h=max(148, 42 + metric_count*38 + 12)
    special_extra=34 if services.clean(str(info.get("special_label") or "")) else 0
    body_h=max(text_h+34,metric_h+20,154)
    return 102+body_h+special_extra


def _draw_day_card(guide, services, fonts, colors, width, info, index, rng):
    rcfg=_renderer_cfg(guide)
    special_label=services.clean(str(info.get("special_label") or ""))
    special=bool(special_label)
    h=_day_card_height(guide,services,fonts,info,width)
    title=_day_title_bilingual(info,services,rcfg)
    card=_draw_card_shell((width,h),colors,title,f"LOG-{index+1:02d}",fonts,rng,special=special)
    d=ImageDraw.Draw(card)
    left_x1=44; left_x2=width-382; panel_x1=width-356; panel_x2=width-40
    special_extra=34 if special else 0
    y1=106+special_extra; y2=h-28
    if special:
        # 档案式优先级强调：标签条 + 左侧红色优先级轨道，替代手绘圆圈。
        tag_prefix=services.clean(str(rcfg.get("special_tag_prefix") or "重点节点"))
        tag=(tag_prefix+"："+special_label) if tag_prefix else special_label
        tf=fonts.body(15,True)
        tag_y=104
        tag_w=min(left_x2-left_x1,max(180,int(_text_w(d,tag,tf)+30)))
        d.rectangle((left_x1,tag_y,left_x1+tag_w,tag_y+25),fill=colors["red_dark"])
        d.text((left_x1+12,tag_y+4),tag,font=tf,fill=colors["paper"])
        d.rectangle((left_x1-10,y1-3,left_x1-4,y2),fill=colors["red"])
        d.rectangle((left_x1,y1-4,left_x2,y2),fill=_mix_color(colors["card"],colors["red"],0.08),outline=colors["red_deep"],width=1)
    # action block
    body_font=fonts.body(max(12,int(rcfg.get("day_action_font_size",26) or 26)),False)
    lines=_wrap_steps(d,info.get("action") or "",body_font,left_x2-left_x1-6)
    action_line_gap=max(0,int(rcfg.get("day_action_line_gap",7) or 7))
    action_step_gap=max(0,int(rcfg.get("day_action_step_gap",7) or 7))
    _draw_wrapped(d,(left_x1+(8 if special else 0),y1+4),lines,body_font,colors["ink"],line_gap=action_line_gap,gap_after_step=action_step_gap)
    # right resource-status record
    d.rectangle((panel_x1,y1-4,panel_x2,y2), fill=colors["panel"], outline=colors["line"], width=1)
    pf=fonts.body(15,True)
    status_title=_compose_bilingual(rcfg.get("status_title_cn","剩余和期望"),rcfg.get("status_title_en","STATUS"))
    d.text((panel_x1+14,y1+8),status_title,font=pf,fill=colors["red"] if special else colors["muted"])
    yy=y1+36
    metric_items=list(info.get("metric_items") or [])
    for m in metric_items:
        icon=_metric_icon_path(guide,services,m)
        row_h=38
        tx=panel_x1+16
        if icon:
            services.draw_image_contain(card,icon,(panel_x1+14,yy+3,panel_x1+44,yy+33))
            tx=panel_x1+54
        label=services.clean(str(m.get("label") or ""))
        value=services.clean(str(m.get("value") or ""))
        lf=fonts.body(14,False); vf=fonts.body(18,True)
        d.text((tx,yy),label,font=lf,fill=colors["muted"])
        vw=_text_w(d,value,vf)
        d.text((panel_x2-12-vw,yy+12),value,font=vf,fill=colors["ink"])
        yy+=row_h
    return card



def _draw_days_log_card(guide, services, fonts, colors, width, days, rng):
    """Render all day actions inside one dossier sheet to avoid repeated card chrome."""
    rcfg=_renderer_cfg(guide)
    days=list(days or [])
    if not days:
        days=[{"day":"DAY","target":"","action":"—","metric_items":[],"special_label":""}]
    tmp=Image.new("RGBA",(width,1200),(0,0,0,0)); td=ImageDraw.Draw(tmp)
    body_font=fonts.body(max(12,int(rcfg.get("day_action_font_size",26) or 26)),False)
    line_gap=max(0,int(rcfg.get("day_action_line_gap",7) or 7))
    step_gap=max(0,int(rcfg.get("day_action_step_gap",7) or 7))
    panel_w=max(300,int(rcfg.get("log_status_panel_width",320) or 320))
    left_x1=44; panel_x2=width-42; panel_x1=panel_x2-panel_w; left_x2=panel_x1-18
    text_w=max(180,left_x2-left_x1-8)
    row_specs=[]
    for info in days:
        lines=_wrap_steps(td,info.get("action") or "",body_font,text_w)
        lc=sum(1 for x in lines if x!="__STEP_GAP__"); gaps=sum(1 for x in lines if x=="__STEP_GAP__")
        text_h=lc*(_line_h(td,body_font)+line_gap)+gaps*step_gap
        metrics=list(info.get("metric_items") or [])
        metric_h=max(68,34+len(metrics)*34)
        body_h=max(text_h+16,metric_h+8,82)
        title_h=42
        row_h=title_h+body_h+12
        row_specs.append((info,lines,metrics,title_h,body_h,row_h))
    total_rows=sum(x[5] for x in row_specs)
    h=106+total_rows+20
    title=_compose_bilingual(rcfg.get("log_title_cn","每日行动日志"),rcfg.get("log_title_en","OPERATION LOG"))
    card=_draw_card_shell((width,h),colors,title,str(rcfg.get("log_file_no") or "LOG-ALL"),fonts,rng)
    d=ImageDraw.Draw(card)
    y=101
    for idx,(info,lines,metrics,title_h,body_h,row_h) in enumerate(row_specs):
        special_label=services.clean(str(info.get("special_label") or "")); special=bool(special_label)
        # compact per-day title rail rather than a full file-card header
        rail_fill=_mix_color(colors["panel"],colors["red"],0.20 if special else 0.08)
        d.rectangle((38,y,width-38,y+title_h),fill=rail_fill,outline=colors["red_deep"] if special else colors["line"],width=1)
        day=services.clean(str(info.get("day") or f"D{idx+1}"))
        df=fonts.title(22,True)
        d.text((50,y+8),day,font=df,fill=colors["red"] if special else colors["ink"])
        target_title=_day_title_bilingual(info,services,rcfg)
        # Remove duplicated day token from the target portion, since day is its own badge here.
        if "｜" in target_title:
            target_title=target_title.split("｜",1)[1]
        tf=fonts.body(17,True)
        target_max=panel_x1-140
        target_lines=_wrap_paragraph(d,target_title,tf,max(100,target_max))[:1]
        d.text((112,y+10),target_lines[0] if target_lines else "",font=tf,fill=colors["ink"])
        if special:
            prefix=services.clean(str(rcfg.get("special_tag_prefix") or "重点节点"))
            label=(prefix+"："+special_label) if prefix else special_label
            sf=fonts.body(13,True)
            sw=min(panel_w-24,max(110,int(_text_w(d,label,sf)+20)))
            sx=panel_x2-sw
            d.rectangle((sx,y+8,panel_x2,y+34),fill=colors["red_dark"])
            d.text((sx+10,y+13),label,font=sf,fill=colors["paper"])
        body_y=y+title_h+6
        # action area
        if special:
            d.rectangle((left_x1-8,body_y,left_x1-3,body_y+body_h-6),fill=colors["red"])
        _draw_wrapped(d,(left_x1,body_y+3),lines,body_font,colors["ink"],line_gap=line_gap,gap_after_step=step_gap)
        # status panel; same information, less repeated chrome
        d.rectangle((panel_x1,body_y,panel_x2,body_y+body_h-6),fill=colors["panel"],outline=colors["line"],width=1)
        pf=fonts.body(15,True)
        status_title=_compose_bilingual(rcfg.get("status_title_cn","剩余和期望"),rcfg.get("status_title_en","STATUS"))
        d.text((panel_x1+11,body_y+7),status_title,font=pf,fill=colors["red"] if special else colors["muted"])
        yy=body_y+34
        for m in metrics:
            icon=_metric_icon_path(guide,services,m); tx=panel_x1+12
            if icon:
                services.draw_image_contain(card,icon,(panel_x1+10,yy+2,panel_x1+38,yy+30)); tx=panel_x1+46
            label=services.clean(str(m.get("label") or "")); value=services.clean(str(m.get("value") or ""))
            lf=fonts.body(14,False); vf=fonts.body(18,True)
            d.text((tx,yy),label,font=lf,fill=colors["muted"])
            vw=_text_w(d,value,vf); d.text((panel_x2-10-vw,yy+10),value,font=vf,fill=colors["ink"])
            yy+=34
        y+=row_h
        if idx<len(row_specs)-1:
            _rough_line(d,[(42,y-4),(width-42,y-4)],colors["line"],1,rng,1,1)
    return card

def _draw_risk_card(guide, services, fonts, colors, width, rng):
    risks=SharedRendererTools(services).risk_items(guide)
    if not risks:
        risks=["按计划执行，避免额外消耗。"]
    rcfg=_renderer_cfg(guide)
    f=fonts.body(max(14,int(rcfg.get("risk_font_size",21) or 21)),False)
    tmp=Image.new("RGBA",(width,1000),(0,0,0,0)); d=ImageDraw.Draw(tmp)

    # 风险提示始终单列：一个风险占一整行，不再两条并排。
    items=risks[:5]
    x1=46
    x2=width-46
    text_x=x1+48
    text_w=max(120,x2-text_x-16)
    measured=[]
    for r in items:
        lines=_wrap_paragraph(d,r,f,text_w)
        rh=max(56,len(lines)*(_line_h(d,f)+5)+18)
        measured.append((r,lines,rh))

    row_gap=8
    h=106+sum(x[2] for x in measured)+max(0,len(measured)-1)*row_gap+22
    risk_title=_compose_bilingual(rcfg.get("risk_title_cn","风险提示"),rcfg.get("risk_title_en","RISK NOTICE"))
    card=_draw_card_shell((width,h),colors,risk_title,str(rcfg.get("risk_file_no") or "FILE-WARN"),fonts,rng,special=True)
    d=ImageDraw.Draw(card)

    y=102
    for idx,(r,lines,rh) in enumerate(measured):
        d.rectangle((x1,y,x2,y+rh),fill=_mix_color(colors["card"],colors["red"],0.05),outline=colors["line"],width=1)
        bang=fonts.title(29,True)
        d.text((x1+14,y+7),"!",font=bang,fill=colors["red"])
        _draw_wrapped(d,(text_x,y+10),lines,f,colors["ink"],5)
        y+=rh
        if idx<len(measured)-1:
            y+=row_gap
    return card


def _draw_barcode(draw, x, y, w, h, color, bg, rng, label="FILE"):
    draw.rectangle((x,y,x+w,y+h), fill=bg)
    cur=x+10
    while cur<x+w-12:
        bw=rng.choice([1,2,2,3,4])
        gap=rng.choice([1,2,3])
        top=y+8+rng.choice([0,0,1,2])
        draw.rectangle((cur,top,cur+bw,y+h-20),fill=color)
        cur += bw+gap
    f = ImageFont.load_default()
    draw.text((x+10,y+h-16),label,font=f,fill=color)


def _draw_fingerprint(draw, box, color, rng):
    x1,y1,x2,y2=map(int,box)
    cx=(x1+x2)//2; cy=(y1+y2)//2
    maxrx=(x2-x1)//2-6; maxry=(y2-y1)//2-6
    for i in range(11):
        rx=maxrx-i*5; ry=maxry-i*4
        if rx<=3 or ry<=3: break
        start=192+rng.randint(-8,8); end=520+rng.randint(-10,8)
        draw.arc((cx-rx,cy-ry,cx+rx,cy+ry),start=start,end=end,fill=color,width=2)
    # break a few ridges with paper-colored scratches
    for _ in range(8):
        yy=rng.randint(y1+8,y2-8)
        draw.line((rng.randint(x1+8,cx),yy,rng.randint(cx,x2-5),yy+rng.randint(-2,2)),fill=(0,0,0,0),width=2)


def _draw_header(base, guide, services, fonts, colors, rcfg, rng):
    d=ImageDraw.Draw(base)
    W=base.width
    # layered folder / envelope shapes behind the title
    d.polygon([(26,218),(W-55,230),(W-28,392),(45,376)],fill=colors["folder_back"])
    d.polygon([(48,240),(W-92,251),(W-45,382),(66,369)],fill=colors["folder_mid"])
    # stamp first, so title layout can reserve a safe zone for it
    stamp=_draw_stamp(rcfg.get("stamp_text") or "内部攻略\n禁止外传",fonts,colors["red"],_rng(guide,"stamp"),diameter=int(rcfg.get("stamp_diameter",170) or 170))
    stamp_x=W-stamp.width-int(rcfg.get("stamp_right",38) or 38)
    stamp_y=int(rcfg.get("stamp_top",50) or 50)
    base.alpha_composite(stamp,(stamp_x,stamp_y))
    # title: no longer repeats sheet by default; long titles wrap to at most two lines.
    prefix=str(rcfg.get("title_prefix") or "机密档案")
    title=services.clean(str(guide.get("title") or guide.get("sheet") or "活动攻略"))
    full=f"{prefix}：{title}" if prefix else title
    title_x=int(rcfg.get("header_title_x",62) or 62)
    title_y=int(rcfg.get("header_title_y",58) or 58)
    safe_right=max(300, W-stamp_x+18)
    title_max_w=max(260,W-title_x-safe_right)
    f, title_lines=_fit_header_title(d,fonts,full,title_max_w,start=int(rcfg.get("header_title_size",52) or 52),min_size=int(rcfg.get("header_title_min_size",30) or 30),max_lines=2)
    line_h=_line_h(d,f)+3
    yy=title_y
    for line in title_lines:
        d.text((title_x,yy),line,font=f,fill=colors["paper"])
        yy+=line_h
    # customizable subtitle. Sheet subtitle is opt-in to avoid duplicate-looking titles.
    if bool(rcfg.get("header_use_sheet_subtitle",False)):
        subtitle=services.clean(str(guide.get("sheet") or ""))
    else:
        subtitle=services.clean(str(rcfg.get("header_subtitle") or "行动记录 / OPERATION LOG"))
    subtitle_y=max(int(rcfg.get("header_subtitle_y",154) or 154), yy+6)
    if subtitle:
        sf=fonts.title(int(rcfg.get("header_subtitle_size",24) or 24),True)
        d.text((66,subtitle_y),"| "+subtitle,font=sf,fill=colors["paper"])
    author_y=max(int(rcfg.get("header_author_y",194) or 194), subtitle_y+38)
    _draw_author(base,guide,services,fonts,colors,rcfg,67,author_y,max_w=620)
    # file id vertical on left folder
    vf=fonts.body(22,True)
    file_id=str(rcfg.get("file_id") or "FILE-0726")
    label=Image.new("RGBA",(190,42),(0,0,0,0)); ld=ImageDraw.Draw(label)
    ld.text((0,5),file_id,font=vf,fill=colors["paper"])
    label=label.rotate(90,expand=True,resample=Image.BICUBIC)
    base.alpha_composite(label,(36,270))


def _draw_footer(base, guide, services, fonts, colors, rcfg, y, rng):
    d=ImageDraw.Draw(base)
    W,H=base.size
    # compact dossier bottom data strip
    tape_h=48
    d.rectangle((46,y,W-46,H-tape_h-2),fill=colors["folder_mid"],outline=colors["line"],width=2)
    cfg=guide.get("cfg") or {}
    group_icon=_resolve_path(guide,services,rcfg.get("footer_group_icon") or cfg.get("watermark_group_icon"))
    show_icon=bool(rcfg.get("footer_show_group_icon",True))
    icon_outer=max(40,int(rcfg.get("footer_group_icon_size",62) or 62))
    icon_x=72+int(rcfg.get("footer_icon_x_offset",0) or 0)
    icon_y=y+18+int(rcfg.get("footer_icon_y_offset",0) or 0)
    x=icon_x
    if group_icon and show_icon:
        try:
            src=Image.open(group_icon).convert("RGBA")
            inner=max(20,icon_outer-12)
            src.thumbnail((inner,inner),Image.LANCZOS)
            photo=Image.new("RGBA",(icon_outer,icon_outer),colors["paper"])
            photo.alpha_composite(src,((icon_outer-src.width)//2,(icon_outer-src.height)//2))
            pd=ImageDraw.Draw(photo); pd.rectangle((0,0,icon_outer-1,icon_outer-1),outline=colors["muted"],width=2)
            base.alpha_composite(photo,(icon_x,icon_y)); x=icon_x+icon_outer+int(rcfg.get("footer_text_gap",18) or 18)
        except Exception:
            pass
    else:
        x=72
    text_size=max(12,int(rcfg.get("footer_text_size",24) or 24))
    wf=fonts.body(text_size,True)
    watermark=services.clean(str(rcfg.get("footer_text") if "footer_text" in rcfg else guide.get("watermark") or ""))
    # Welcome text owns the top row; barcode/fingerprint move to a lower row so larger type never collides.
    configured_w=max(120,int(rcfg.get("footer_text_max_width",520) or 520))
    max_text_w=min(configured_w,max(140,W-x-48))
    lines=_wrap_paragraph(d,watermark,wf,max_text_w)
    # If it still needs >2 lines, gently reduce only the footer font until it fits.
    min_footer_size=max(14,int(rcfg.get("footer_text_min_size",18) or 18))
    while text_size>min_footer_size and (len(lines)>2 or (len(lines)==2 and _text_w(d,lines[-1],wf)<max_text_w*0.18)):
        text_size-=1
        wf=fonts.body(text_size,True)
        lines=_wrap_paragraph(d,watermark,wf,max_text_w)
    lines=lines[:2]
    lh=_line_h(d,wf)
    block_h=max(1,len(lines))*(lh+4)-4
    if group_icon and show_icon and bool(rcfg.get("footer_text_center_to_avatar",True)):
        text_y=icon_y+(icon_outer-block_h)//2
    else:
        text_y=y+28
    x+=int(rcfg.get("footer_text_x_offset",0) or 0)
    text_y+=int(rcfg.get("footer_text_y_offset",0) or 0)
    _draw_wrapped(d,(x,text_y),lines,wf,colors["paper"],4)
    # barcode + fingerprint on a separate lower row
    lower_y=max(icon_y+icon_outer+10, y+90)
    _draw_barcode(d,W-300,lower_y,112,50,colors["paper"],colors["card"],rng,label=str(rcfg.get("barcode_text") or "CLASSIFIED"))
    fp_box=(W-168,lower_y-5,W-82,lower_y+55)
    d.rectangle(fp_box,fill=colors["paper"])
    fpd=ImageDraw.Draw(base)
    _draw_fingerprint(fpd,(W-158,lower_y+1,W-92,lower_y+50),colors["card"],rng)
    # classic yellow/black warning tape at the very bottom
    tape_y=H-tape_h
    warning_yellow="#F2C230"
    warning_black="#171612"
    d.rectangle((0,tape_y,W,H),fill=warning_yellow)
    stripe_w=54
    for xx in range(-60,W+60,stripe_w):
        d.polygon([(xx,tape_y),(xx+22,tape_y),(xx-8,H),(xx-30,H)],fill=warning_black)


def _build_background(size, colors, rng):
    W,H=size
    img=Image.new("RGBA",size,colors["background"])
    d=ImageDraw.Draw(img)
    # outer vignette / paper board
    d.rectangle((18,18,W-19,H-19),outline=colors["edge"],width=3)
    # old creases from corners
    crease=(211,202,184,70)
    d.line((0,120,120,0),fill=crease,width=2)
    d.line((8,132,129,7),fill=(220,210,192,36),width=1)
    d.line((W-2,220,W-120,92),fill=(220,210,192,34),width=2)
    # subtle red ruled lines under dossier content
    for yy in range(360,H-170,74):
        d.line((110,yy,W-82,yy),fill=colors["rule"],width=1)
    img.alpha_composite(_grain_overlay(size,rng,alpha=24,coarse=False))
    # edge darkening
    vign=Image.new("L",size,0)
    vd=ImageDraw.Draw(vign)
    vd.rectangle((0,0,W,H),fill=180)
    for i in range(60):
        a=int(180*(1-i/60))
        vd.rectangle((i,i,W-1-i,H-1-i),outline=max(0,a),width=1)
    dark=Image.new("RGBA",size,(0,0,0,0)); dark.putalpha(vign)
    img.alpha_composite(dark)
    return img


def render(guide, out_path: Path, services):
    started=time.perf_counter()
    tools=SharedRendererTools(services)
    rcfg=_renderer_cfg(guide)
    colors=tools.colors(guide,{
        "background":"#11110F","card":"#211F1B","panel":"#1A1916","folder_back":"#171612","folder_mid":"#1D1B17",
        "red":"#C63B33","red_dark":"#A72D28","red_deep":"#6F1917","paper":"#EFE6CF","ink":"#F3EBD9","muted":"#BFB6A5",
        "line":"#514C43","border":"#080808","shadow_edge":"#050505","edge":"#3A362F","rule":"#4A211E","header_ink":"#11110F",
    })
    fonts=_Fonts(guide,services,rcfg)
    W=int(rcfg.get("canvas_width",services.W) or services.W)
    card_w=min(W-118,int(rcfg.get("card_width",930) or 930))
    rotations=[]
    rr=_rng(guide,"angles")
    # budget + rewards + each day + risk
    compact_layout=bool(rcfg.get("compact_layout",True))
    continuous_log=bool(rcfg.get("continuous_day_log",True))
    day_card_count=1 if continuous_log else len(guide.get("days") or [])
    card_count=(1 if compact_layout else 2)+day_card_count+1
    max_rot=float(rcfg.get("card_rotation",0.65) or 0.65)
    for i in range(card_count):
        sign=-1 if i%2==0 else 1
        rotations.append(sign*rr.uniform(0.15,max_rot))

    # prebuild content cards so page height follows actual content. In compact
    # mode, budget + rewards share one preparation dossier to avoid duplicate shell/header height.
    cards=[]
    compact_layout=bool(rcfg.get("compact_layout",True))
    if compact_layout:
        cards.append(_draw_prep_card(guide,services,fonts,colors,card_w,_rng(guide,"prep")))
    else:
        cards.append(_draw_budget_card(guide,services,fonts,colors,card_w,_rng(guide,"budget")))
        cards.append(_draw_reward_card(guide,services,fonts,colors,card_w,_rng(guide,"rewards")))
    continuous_log=bool(rcfg.get("continuous_day_log",True))
    if continuous_log:
        cards.append(_draw_days_log_card(guide,services,fonts,colors,card_w,guide.get("days") or [],_rng(guide,"day-log")))
    else:
        for i,info in enumerate(guide.get("days") or []):
            cards.append(_draw_day_card(guide,services,fonts,colors,card_w,info,i,_rng(guide,f"day-{i}")))
    cards.append(_draw_risk_card(guide,services,fonts,colors,card_w,_rng(guide,"risk")))

    header_h=330 if compact_layout else 390
    gap=int(rcfg.get("card_gap",10) or 10)
    content_est=sum(c.height+gap+24 for c in cards)
    footer_h=max(190,int(rcfg.get("footer_height",200) or 200))
    H=header_h+content_est+footer_h+54
    H=max(H,services.H)
    base=_build_background((W,H),colors,_rng(guide,"paper"))
    _draw_header(base,guide,services,fonts,colors,rcfg,_rng(guide,"header"))

    y=300 if compact_layout else 350
    cx=W//2+20
    for i,card in enumerate(cards):
        y=_paste_rotated(base,card,cx,y,rotations[i],shadow=True,shadow_alpha=135)
        y+=gap
    footer_y=y+2
    # crop page to content instead of leaving arbitrary blank space
    final_h=max(services.H,int(footer_y+footer_h))
    if final_h != H:
        base=base.crop((0,0,W,final_h))
    _draw_footer(base,guide,services,fonts,colors,rcfg,footer_y,_rng(guide,"footer"))
    tools.save(base,out_path,guide,started)
