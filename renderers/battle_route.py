# -*- coding: utf-8 -*-
"""Tactical battle-route / campaign-map renderer.

Original visual language inspired by field maps and campaign planning boards:
- procedural parchment map, contour lines, routes and compass marks
- D1..Dn nodes connected by a red operation route
- alternating pinned mission notes for each day
- independent resource / reward intelligence panels
- one-risk-per-row threat assessment and commander footer

No external background image is required.
"""
from __future__ import annotations

from pathlib import Path
import hashlib
import math
import random
import re
import time

from PIL import Image, ImageDraw, ImageFilter

from .shared import SharedRendererTools
from .reward_items import RewardItemRenderer

STYLE_IDS = ("battle_route",)


def _rcfg(guide):
    tc = guide.get("theme_config") or {}
    base = tc.get("renderer") if isinstance(tc.get("renderer"), dict) else {}
    cfg = dict(base or {})
    project = guide.get("cfg") or {}
    if isinstance(project.get("battle_route"), dict):
        cfg.update(project.get("battle_route") or {})
    return cfg


def _seed(guide, salt=""):
    raw = "{}|{}|{}|{}".format(
        guide.get("title") or "", guide.get("sheet") or "",
        guide.get("variant_id") or "", salt,
    )
    return int(hashlib.sha256(raw.encode("utf-8", "ignore")).hexdigest()[:16], 16)


def _rng(guide, salt=""):
    return random.Random(_seed(guide, salt))


def _mix(a, b, t):
    def rgb(c):
        c = str(c).lstrip("#")
        if len(c) == 3:
            c = "".join(ch*2 for ch in c)
        try:
            return tuple(int(c[i:i+2], 16) for i in (0,2,4))
        except Exception:
            return (128,128,128)
    x, y = rgb(a), rgb(b)
    q = max(0.0, min(1.0, float(t)))
    z = tuple(int(round(x[i]*(1-q)+y[i]*q)) for i in range(3))
    return "#{:02X}{:02X}{:02X}".format(*z)


def _rgba(color, alpha=255):
    """Return an RGBA tuple from #RGB/#RRGGBB/#RRGGBBAA; useful for faint map layers."""
    raw=str(color or "#000000").lstrip("#")
    if len(raw)==3:
        raw="".join(ch*2 for ch in raw)
    try:
        r,g,b=(int(raw[i:i+2],16) for i in (0,2,4))
        if len(raw)>=8:
            src_a=int(raw[6:8],16)
            alpha=int(src_a*max(0,min(255,int(alpha)))/255)
        return (r,g,b,max(0,min(255,int(alpha))))
    except Exception:
        return (0,0,0,max(0,min(255,int(alpha))))


def _font(s, size, bold=False):
    return s.get_font(max(8, int(size)), bool(bold))


def _text_w(draw, text, font):
    try:
        return draw.textlength(str(text or ""), font=font)
    except Exception:
        b = draw.textbbox((0,0), str(text or " "), font=font)
        return max(0, b[2]-b[0])


def _wrap(draw, text, font, max_w, max_lines=None):
    text = str(text or "").replace("\r", "").strip()
    paragraphs = [p.strip() for p in text.split("\n") if p.strip()] or ["—"]
    lines = []
    for p in paragraphs:
        line = ""
        for ch in p:
            trial = line + ch
            if line and _text_w(draw, trial, font) > max_w:
                lines.append(line)
                line = ch
            else:
                line = trial
        if line:
            lines.append(line)
        if max_lines and len(lines) >= max_lines:
            break
    if max_lines and len(lines) > max_lines:
        lines = lines[:max_lines]
    return lines or ["—"]


def _draw_multiline(draw, x, y, lines, font, fill, gap=4, bullet=False, bullet_fill=None):
    bb = draw.textbbox((0,0), "国Ag", font=font)
    lh = max(1, bb[3]-bb[1])
    for line in lines:
        if bullet:
            draw.ellipse((x, y+lh*0.45-2, x+4, y+lh*0.45+2), fill=bullet_fill or fill)
            draw.text((x+12, y), line, font=font, fill=fill)
        else:
            draw.text((x, y), line, font=font, fill=fill)
        y += lh + gap
    return y


def _paper_noise(size, rng, alpha=22):
    """Low-frequency paper grain.

    Earlier versions used a fairly dense random field.  It looked fine, but the high
    entropy also made every 1080x2340 PNG unnecessarily large.  A coarser grain plus
    a slightly stronger blur keeps the aged-paper impression while compressing much
    better and leaving the actual route/details easier to read.
    """
    w,h = size
    small = Image.new("L", (max(2,w//15), max(2,h//15)), 0)
    px = small.load()
    for yy in range(small.height):
        for xx in range(small.width):
            px[xx,yy] = rng.randint(82,178)
    small = small.resize((w,h), Image.Resampling.BILINEAR).filter(ImageFilter.GaussianBlur(2.1))
    tint = Image.new("RGBA", (w,h), (105,65,28,0))
    tint.putalpha(small.point(lambda v: int(v*alpha/255)))
    return tint

def _torn_edge(draw, w, h, colors, rng):
    edge = colors["edge"]
    dark = colors["edge_dark"]
    pts_top=[]; pts_bottom=[]
    x=8
    while x < w-8:
        pts_top.append((x, rng.randint(9,21))); x += rng.randint(24,54)
    pts_top += [(w-8,16)]
    x=8
    while x < w-8:
        pts_bottom.append((x, h-rng.randint(9,23))); x += rng.randint(24,54)
    pts_bottom += [(w-8,h-15)]
    draw.line(pts_top, fill=edge, width=3)
    draw.line(pts_bottom, fill=edge, width=3)
    draw.rectangle((13,15,w-14,h-16), outline=dark, width=2)


def _draw_map_texture(base, colors, rng, rcfg=None):
    """Build a lighter aged military-map surface without noisy visual filler."""
    rcfg=rcfg or {}
    d = ImageDraw.Draw(base, "RGBA")
    W,H = base.size
    base.alpha_composite(_paper_noise((W,H), rng, int(rcfg.get("texture_noise_alpha",22) or 22)))

    # Uneven paper tone / water stains.  Keep only a few large, soft marks; tiny random
    # marks add file size faster than they add atmosphere.
    stain = Image.new("RGBA", (W,H), (0,0,0,0))
    sd = ImageDraw.Draw(stain, "RGBA")
    for _ in range(int(rcfg.get("texture_stain_count",9) or 9)):
        cx=rng.randint(-80,W+80); cy=rng.randint(120,H-80)
        rx=rng.randint(65,230); ry=rng.randint(35,135)
        col=rng.choice([(91,55,27,13),(128,82,38,10),(231,214,170,10)])
        sd.ellipse((cx-rx,cy-ry,cx+rx,cy+ry),fill=col)
    stain=stain.filter(ImageFilter.GaussianBlur(22))
    base.alpha_composite(stain)

    # Faded military grid.  A wider grid reads more like a map and compresses better.
    grid_step=max(48,int(rcfg.get("texture_grid_step",64) or 64))
    minor=colors["map_grid"]
    for x in range(48, W-30, grid_step):
        d.line((x,190,x,H-150), fill=minor, width=1)
    for y in range(210, H-145, grid_step):
        d.line((28,y,W-28,y), fill=minor, width=1)
    major=colors.get("map_grid_major", colors["map_grid"])
    for x in range(48, W-30, grid_step*4):
        d.line((x,190,x,H-150), fill=major, width=1)
    for y in range(210, H-145, grid_step*4):
        d.line((28,y,W-28,y), fill=major, width=1)

    # Abstract old roads / borders: fewer random lines, preserving the geographic cue.
    for idx in range(int(rcfg.get("texture_road_count",5) or 5)):
        x = rng.randint(20, W-20); y = rng.randint(210, H-220)
        pts=[]
        for k in range(rng.randint(6,9)):
            x += rng.randint(-90,90); y += rng.randint(45,105)
            pts.append((max(18,min(W-18,x)), max(195,min(H-165,y))))
        if len(pts)>1:
            d.line(pts, fill=colors["map_line"], width=1)

    # Topographic fragments.  About half the old density is enough once semantic
    # terrain (river, road, ridge, woods) is present.
    for _ in range(int(rcfg.get("texture_contour_count",28) or 28)):
        cx=rng.randint(20,W-20); cy=rng.randint(210,H-160)
        rx=rng.randint(40,160); ry=rng.randint(18,72)
        loops=rng.choice([1,1,1,2])
        for j in range(loops):
            box=(cx-rx-j*8,cy-ry-j*4,cx+rx+j*8,cy+ry+j*4)
            start=rng.randint(0,100); end=start+rng.randint(105,240)
            d.arc(box,start=start,end=end,fill=colors["contour"],width=1)

    # Paper folds: keep because they add large-scale texture without visual noise.
    fold=colors.get("fold", "#6F4D2D20")
    hi=colors.get("fold_highlight", "#FFF4D51B")
    for fx in [int(W*0.34), int(W*0.69)]:
        d.line((fx,22,fx+rng.randint(-12,12),H-32),fill=fold,width=3)
        d.line((fx+3,22,fx+3+rng.randint(-9,9),H-32),fill=hi,width=1)
    for fy in [int(H*0.40), int(H*0.72)]:
        d.line((24,fy,W-24,fy+rng.randint(-8,8)),fill=fold,width=2)
        d.line((24,fy+3,W-24,fy+3+rng.randint(-6,6)),fill=hi,width=1)

    # Sparse military marks only.  These should reward close inspection, not become noise.
    for i in range(int(rcfg.get("texture_mark_count",10) or 10)):
        x=rng.randint(45,W-120); y=rng.randint(240,H-190)
        if i%3==0:
            d.polygon([(x,y+8),(x+8,y),(x+16,y+8),(x+8,y+16)],outline=colors["faint_mark"])
        elif i%3==1:
            d.rectangle((x,y,x+rng.randint(22,44),y+rng.randint(8,14)), outline=colors["faint_mark"], width=1)
        else:
            d.ellipse((x,y,x+12,y+12),outline=colors["faint_mark"],width=1)

    # Edge wear and darker vignette.
    for inset,alpha in [(0,30),(6,21),(13,14),(21,8)]:
        col=(71,42,22,alpha)
        d.rectangle((inset,inset,W-1-inset,H-1-inset),outline=col,width=6)
    _torn_edge(d,W,H,colors,rng)

def _draw_terrain_features(base, colors, rng, route_start=324, route_end=1792):
    """Add readable, low-contrast terrain semantics beneath the operation route.

    The intent is not to simulate a precise real-world map.  These shapes simply give the
    campaign path believable terrain to travel through: a river, old road, ridge, woods,
    boundary and bridge.  All features remain faint so Day nodes and text stay dominant.
    """
    d=ImageDraw.Draw(base,"RGBA")
    W,H=base.size
    top=max(235,int(route_start-70)); bottom=min(H-185,int(route_end+130))

    # A meandering river with two worn banks.  Keep it mostly left/centre so the intel
    # dossiers at upper right stay visually separate.
    river=[]
    steps=15
    span=max(1,bottom-top)
    for i in range(steps):
        t=i/(steps-1)
        y=top+t*span
        x=125 + 245*t + 75*math.sin(t*math.pi*2.35+0.45) + rng.uniform(-15,15)
        river.append((x,y))
    river_col=_rgba(colors.get("terrain_blue",colors.get("route_blue","#4E6C74")),52)
    river_bank=_rgba(colors.get("terrain_bank",colors.get("map_line","#6E5136")),58)
    d.line(river,fill=river_col,width=11)
    d.line([(x-6,y) for x,y in river],fill=river_bank,width=1)
    d.line([(x+7,y) for x,y in river],fill=river_bank,width=1)

    # Old supply road: a broad faded track with a broken centre line.
    road=[(74,top+110),(205,top+245),(175,top+420),(300,top+605),(265,top+790),(420,min(bottom,top+1030)),(520,bottom-40)]
    road_col=_rgba(colors.get("terrain_road",colors.get("map_line","#72583D")),42)
    road_edge=_rgba(colors.get("terrain_boundary",colors.get("edge","#6A482B")),52)
    d.line(road,fill=road_col,width=10)
    d.line(road,fill=road_edge,width=1)
    for a,b in zip(road,road[1:]):
        _rough_dash(d,a,b,_rgba(colors.get("terrain_road_center",colors.get("paper_light","#D5C39A")),50),1,rng,dash=11,gap=13)

    # Forest clusters.  Tiny triangular tree symbols read as map texture at a distance.
    forest_col=_rgba(colors.get("terrain_green",colors.get("olive_rule","#747A54")),54)
    clusters=[(790,820,120,78),(785,1325,145,92),(175,1540,115,76)]
    for cx,cy,rx,ry in clusters:
        for _ in range(14):
            x=cx+rng.randint(-rx,rx); y=cy+rng.randint(-ry,ry)
            if x<35 or x>W-35 or y<top or y>bottom: continue
            s=rng.randint(5,9)
            d.polygon([(x,y-s),(x-s,y+s),(x+s,y+s)],outline=forest_col)
            if rng.random()<0.45:
                d.line((x,y+s,x,y+s+4),fill=forest_col,width=1)

    # Ridge / escarpment hatching, kept away from the upper-right dossiers.
    ridge_col=_rgba(colors.get("terrain_ridge",colors.get("contour","#6D5131")),64)
    ridge=[]
    for i in range(12):
        t=i/11
        x=650+270*t
        y=1010+170*math.sin(t*math.pi)+rng.randint(-8,8)
        ridge.append((x,y))
    d.line(ridge,fill=ridge_col,width=2)
    for i,(x,y) in enumerate(ridge[1:-1],1):
        if i%2:
            d.line((x,y,x+14,y+18),fill=ridge_col,width=1)
            d.line((x+7,y+4,x+20,y+21),fill=ridge_col,width=1)

    # Old sector boundary and a small objective zone.
    boundary=[(650,1515),(740,1470),(885,1510),(945,1620),(900,1730),(770,1760),(670,1680),(650,1515)]
    for a,b in zip(boundary,boundary[1:]):
        _rough_dash(d,a,b,_rgba(colors.get("terrain_boundary",colors.get("annotation_rule","#65513A")),62),2,rng,dash=13,gap=9)
    tf=None  # font is intentionally omitted here; labels are drawn in the annotation pass.

    # Bridge marker crossing the river at a deterministic mid-map location.
    target_y=min(bottom-90,max(top+420,1140))
    nearest=min(river,key=lambda p:abs(p[1]-target_y))
    bx,by=nearest
    d.line((bx-23,by-10,bx+25,by+10),fill=_rgba(colors.get("terrain_ink",colors.get("ink_mid","#523A2C")),78),width=3)
    d.line((bx-19,by-18,bx+29,by+2),fill=_rgba(colors.get("terrain_ink",colors.get("ink_mid","#523A2C")),62),width=1)


def _rotated_map_text(base, xy, text, font, fill, angle=0):
    """Small rotated pencil note used as an atmospheric annotation."""
    text=str(text or "")
    if not text:
        return
    probe=Image.new("RGBA",(500,90),(0,0,0,0)); pd=ImageDraw.Draw(probe,"RGBA")
    b=pd.textbbox((0,0),text,font=font)
    w=max(4,b[2]-b[0]+12); h=max(4,b[3]-b[1]+12)
    layer=Image.new("RGBA",(w,h),(0,0,0,0)); ld=ImageDraw.Draw(layer,"RGBA")
    ld.text((6-b[0],5-b[1]),text,font=font,fill=fill)
    if angle:
        layer=layer.rotate(angle,expand=True,resample=Image.Resampling.BICUBIC)
    base.alpha_composite(layer,(int(xy[0]),int(xy[1])))


def _draw_field_annotations(base, days, points, s, colors, rcfg, rng):
    """Sparse human pencil/grease-pencil marks that make the map feel actively planned."""
    if not points:
        return
    d=ImageDraw.Draw(base,"RGBA")
    faint=_rgba(colors.get("hand_note",colors.get("ink_mid","#523A2C")),98)
    blue=_rgba(colors.get("route_blue",colors.get("compass_blue","#4C6B73")),92)
    red=_rgba(colors.get("pencil_red",colors.get("route_red","#843C34")),110)
    font=_font(s,12,False); small=_font(s,10,True)

    # Route-start pencil note.
    p0=points[0]
    _rotated_map_text(base,(68,max(205,p0[1]-88)),"出发点 / START",small,blue,-4)
    d.line((168,p0[1]-64,p0[0]-40,p0[1]-16),fill=blue,width=2)
    d.polygon([(p0[0]-40,p0[1]-16),(p0[0]-49,p0[1]-15),(p0[0]-43,p0[1]-7)],fill=blue)

    # Mid-route annotations intentionally live in edge space, not over Day text.
    candidates=[
        ("补给检查", 790, max(770,points[min(2,len(points)-1)][1]+70), -5, blue),
        ("绕行", 78, max(1110,points[min(4,len(points)-1)][1]-55), 7, faint),
        ("保持间距", 750, max(1440,points[min(5,len(points)-1)][1]-35), -3, faint),
    ]
    for label,x,y,ang,col in candidates:
        if y<base.height-365:
            _rotated_map_text(base,(x,y),label,font,col,ang)
            d.line((x+8,y+22,x+58,y+7),fill=col,width=1)

    # Special days get a red reviewer-style emphasis around the point, while normal days stay blue-grey.
    for i,(info,p) in enumerate(zip(days,points)):
        special=bool(s.clean(str(info.get("special_label") or "")))
        if not special:
            continue
        cx,cy=p; rr=int(rcfg.get("node_radius",31) or 31)+18
        d.arc((cx-rr,cy-rr,cx+rr,cy+rr),12,332,fill=red,width=2)
        lab=s.clean(str(info.get("special_label") or "重点"))
        _rotated_map_text(base,(cx+rr+8,cy-rr-8),"重点 / "+lab,small,red,-5 if i%2==0 else 4)

    # End-of-route direction cue.
    pe=points[-1]
    ex=min(base.width-230,pe[0]+95); ey=min(base.height-390,pe[1]+62)
    _rotated_map_text(base,(ex,ey),"撤离 / END",small,red,4)
    d.line((pe[0]+32,pe[1]+24,ex+15,ey+4),fill=red,width=2)


def _draw_tape(base, box, color, angle=0):
    x1,y1,x2,y2 = map(int,box)
    w=max(1,x2-x1); h=max(1,y2-y1)
    tape=Image.new("RGBA",(w,h),(0,0,0,0)); td=ImageDraw.Draw(tape,"RGBA")
    td.rectangle((0,0,w,h), fill=color)
    for x in range(-20,w+20,14):
        td.line((x,0,x+8,h), fill=(255,255,255,24), width=1)
    if angle:
        tape=tape.rotate(angle,expand=True,resample=Image.Resampling.BICUBIC)
    base.alpha_composite(tape,(x1-(tape.width-w)//2,y1-(tape.height-h)//2))


def _rough_line(draw, a, b, fill, width, rng, passes=3, jitter=1.5):
    """Slightly imperfect multi-pass line, like grease pencil on paper."""
    ax,ay=a; bx,by=b
    for k in range(max(1,passes)):
        jx1=rng.uniform(-jitter,jitter); jy1=rng.uniform(-jitter,jitter)
        jx2=rng.uniform(-jitter,jitter); jy2=rng.uniform(-jitter,jitter)
        draw.line((ax+jx1,ay+jy1,bx+jx2,by+jy2),fill=fill,width=max(1,width-(k//2)))


def _rough_dash(draw, a, b, fill, width, rng, dash=18, gap=11):
    dx=b[0]-a[0]; dy=b[1]-a[1]; dist=max(1.0,math.hypot(dx,dy))
    t=0.0
    while t<dist:
        t2=min(dist,t+dash+rng.uniform(-2,2))
        p1=(a[0]+dx*t/dist,a[1]+dy*t/dist)
        p2=(a[0]+dx*t2/dist,a[1]+dy*t2/dist)
        _rough_line(draw,p1,p2,fill,width,rng,passes=2,jitter=0.8)
        t += dash+gap+rng.uniform(-2,2)


def _paper_card_polygon(x1,y1,x2,y2,rng,tear=5):
    """Small irregularities on card edges; intentionally subtle for readability."""
    return [
        (x1+rng.randint(0,tear),y1+rng.randint(0,tear)),
        (x1+(x2-x1)*0.35,y1+rng.randint(0,tear)),
        (x1+(x2-x1)*0.68,y1+rng.randint(0,tear)),
        (x2-rng.randint(0,tear),y1+rng.randint(0,tear)),
        (x2-rng.randint(0,tear),y2-rng.randint(0,tear)),
        (x1+(x2-x1)*0.62,y2-rng.randint(0,tear)),
        (x1+(x2-x1)*0.28,y2-rng.randint(0,tear)),
        (x1+rng.randint(0,tear),y2-rng.randint(0,tear)),
    ]


def _draw_flag(draw, x, y, colors, scale=1.0):
    pole=int(42*scale); fw=int(34*scale); fh=int(20*scale)
    draw.line((x,y,x,y-pole),fill=colors["node_border"],width=max(2,int(3*scale)))
    draw.polygon([(x+2,y-pole+2),(x+fw,y-pole+7),(x+2,y-pole+fh)],fill=colors["route_red"],outline=colors["node_border"])


def _draw_map_annotations(base, s, colors, rcfg, rng, route_start, route_end):
    d=ImageDraw.Draw(base,"RGBA")
    W,H=base.size
    f=_font(s,11,True)
    labels=[("SECTOR A-3",80,255), ("GRID 07-14",185,route_start+130), ("RV-02",W-208,route_start+510),
            ("OBJ BRAVO",95,route_start+790), ("CHECKPOINT",W-250,route_end-120)]
    for text,x,y in labels:
        if y < H-180:
            d.text((x,y),text,font=f,fill=colors["annotation"])
            d.line((x,y+18,x+60,y+18),fill=colors["annotation_rule"],width=1)
    # tiny direction arrows and objective flags
    for i in range(3):
        x=rng.randint(70,W-90); y=rng.randint(route_start+80,max(route_start+120,route_end+60))
        if y>=H-180: continue
        col=colors["annotation_rule"]
        d.line((x,y,x+22,y-10),fill=col,width=2)
        d.polygon([(x+22,y-10),(x+14,y-9),(x+19,y-3)],fill=col)
    _draw_flag(d,W-115,min(H-210,route_end+95),colors,0.75)



def _trim_rgba(src):
    """Trim transparent padding so the actual game art can fill its intended box."""
    try:
        if src.mode != "RGBA":
            src=src.convert("RGBA")
        alpha=src.getchannel("A")
        bbox=alpha.getbbox()
        if bbox:
            src=src.crop(bbox)
    except Exception:
        pass
    return src


def _paste_trimmed_icon(base, path, box, pad=2):
    """Contain a transparency-trimmed icon inside box without changing the quality frame."""
    try:
        src=Image.open(path).convert("RGBA")
        src=_trim_rgba(src)
        x1,y1,x2,y2=map(int,box)
        pad=max(0,int(pad))
        mw=max(1,x2-x1-pad*2); mh=max(1,y2-y1-pad*2)
        src.thumbnail((mw,mh),Image.Resampling.LANCZOS)
        px=x1+pad+(mw-src.width)//2
        py=y1+pad+(mh-src.height)//2
        base.alpha_composite(src,(px,py))
        return True
    except Exception:
        return False


def _distressed_print_text(base, xy, text, font, fill, ghost, rng):
    """Subtle old-print registration/ink wear; readable, never decorative enough to hurt text."""
    x,y=map(int,xy)
    layer=Image.new("RGBA",base.size,(0,0,0,0))
    ld=ImageDraw.Draw(layer,"RGBA")
    ld.text((x+1,y+1),text,font=font,fill=ghost)
    ld.text((x,y),text,font=font,fill=fill)
    # very light dry-ink specks only across the title's bounding box
    try:
        b=ld.textbbox((x,y),text,font=font)
        for _ in range(max(6,int((b[2]-b[0])/50))):
            xx=rng.randint(b[0],max(b[0],b[2]-2)); yy=rng.randint(b[1],max(b[1],b[3]-1))
            ld.rectangle((xx,yy,xx+rng.randint(1,3),yy+1),fill=(205,181,132,55))
    except Exception:
        pass
    base.alpha_composite(layer)


def _fit_action_lines(draw, s, text, max_w, max_h, preferred, minimum=12, bold=True, preferred_gap=3):
    """Fit all action lines without dropping numbered steps.

    Daily execution copy is the primary information layer of this theme, so it
    prefers a bold face and only shrinks when the complete text cannot fit.
    """
    text=s.clean(str(text or "—"))
    preferred=max(minimum,int(preferred))
    preferred_gap=max(1,int(preferred_gap))
    for size in range(preferred,minimum-1,-1):
        f=_font(s,size,bold)
        lines=_wrap(draw,text,f,max_w,None)
        bb=draw.textbbox((0,0),"国Ag",font=f); lh=max(1,bb[3]-bb[1])
        gap=preferred_gap if size>=15 else max(1,preferred_gap-1)
        need=len(lines)*(lh+gap)-gap
        if need<=max_h:
            return f,lines,gap
    f=_font(s,minimum,bold)
    lines=_wrap(draw,text,f,max_w,None)
    return f,lines,1


def _footer_group_text(guide, rcfg, s):
    raw=rcfg.get("footer_group_text")
    if not raw:
        raw=guide.get("watermark") or ""
    text=s.clean(str(raw or ""))
    if not text:
        return "欢迎加入冒险者日记萌新交流群"
    if "欢迎加入" not in text:
        return "欢迎加入"+text
    return text




def _draw_variant_overlay(base, colors, rcfg, rng):
    """Variant-specific cartographic marks.

    These are deliberately low-contrast and semantic rather than decorative noise:
    the night-recon sheet gains bearing/crosshair overlays, while the desert sheet
    gains dune contours and convoy-track references.  The core route/info layout is
    unchanged, so all variants continue to share the same renderer logic.
    """
    style=str(rcfg.get("map_variant_style") or "parchment").strip().lower()
    if style not in {"night_recon","blueprint_command"}:
        return
    d=ImageDraw.Draw(base,"RGBA")
    W,H=base.size
    if style=="night_recon":
        col=_rgba(colors.get("variant_overlay", colors.get("terrain_green","#74806A")),58)
        faint=_rgba(colors.get("variant_overlay_faint", colors.get("map_grid_major","#74806A")),34)
        # Survey crosshairs and bearing rings suggest an acetate night-recon overlay.
        for cx,cy,r in [(255,560,105),(535,1110,135),(760,1520,94)]:
            d.ellipse((cx-r,cy-r,cx+r,cy+r),outline=faint,width=1)
            d.line((cx-r-18,cy,cx+r+18,cy),fill=faint,width=1)
            d.line((cx,cy-r-18,cx,cy+r+18),fill=faint,width=1)
            for ang in (45,135):
                a=math.radians(ang)
                dx=math.cos(a)*(r+10); dy=math.sin(a)*(r+10)
                d.line((cx-dx,cy-dy,cx+dx,cy+dy),fill=_rgba(col,28),width=1)
        # Coordinate/bearing ticks along the map edge.
        for y in range(360,1810,160):
            d.line((33,y,51,y),fill=col,width=2)
        # Avoid font dependency above; small squares provide the same survey-register cue.
        for y in range(360,1810,160):
            d.rectangle((56,y-3,61,y+2),fill=col)
        # Low-light diagonal plotting marks.
        for x,y in [(165,840),(870,980),(650,1710)]:
            d.line((x-18,y+18,x+18,y-18),fill=col,width=2)
            d.ellipse((x-5,y-5,x+5,y+5),outline=col,width=1)
    else:
        line=_rgba(colors.get("variant_overlay", colors.get("terrain_blue","#A8D7E8")),82)
        faint=_rgba(colors.get("variant_overlay_faint", colors.get("map_grid_major","#A8D7E8")),44)
        # Blueprint drafting overlay: registration crosses, scale bars, datum rings and
        # measured construction lines.  These are geometric on purpose so this variant
        # reads like a command-room cyanotype rather than another aged paper map.
        for cx,cy in [(160,420),(905,760),(180,1380),(845,1695)]:
            d.line((cx-20,cy,cx+20,cy),fill=line,width=1)
            d.line((cx,cy-20,cx,cy+20),fill=line,width=1)
            d.ellipse((cx-7,cy-7,cx+7,cy+7),outline=faint,width=1)
        for x1,y1,x2,y2 in [(95,610,350,610),(680,1010,955,1010),(120,1570,430,1570)]:
            d.line((x1,y1,x2,y2),fill=faint,width=1)
            for x in range(x1,x2+1,25):
                tick=8 if ((x-x1)//25)%5==0 else 4
                d.line((x,y1-tick,x,y1+tick),fill=line,width=1)
        for cx,cy,r in [(520,780,116),(690,1435,90)]:
            d.ellipse((cx-r,cy-r,cx+r,cy+r),outline=faint,width=1)
            d.ellipse((cx-r//2,cy-r//2,cx+r//2,cy+r//2),outline=_rgba(line,42),width=1)
            d.line((cx-r-14,cy,cx+r+14,cy),fill=_rgba(line,36),width=1)
            d.line((cx,cy-r-14,cx,cy+r+14),fill=_rgba(line,36),width=1)
        # Technical callout brackets and revision marks.
        for x,y,w in [(78,930,118),(832,1225,130),(92,1760,150)]:
            d.line((x,y,x+w,y),fill=line,width=1)
            d.line((x,y,x,y+15),fill=line,width=1)
            d.line((x+w,y,x+w,y+15),fill=line,width=1)
            d.rectangle((x+w+7,y-5,x+w+15,y+3),outline=faint,width=1)

def _draw_title(base, guide, s, colors, rcfg):
    d=ImageDraw.Draw(base,"RGBA")
    W=base.width
    title=s.clean(str(guide.get("title") or guide.get("sheet") or "活动攻略"))
    prefix=s.clean(str(rcfg.get("title_prefix") or "战术作战路线"))
    full=(prefix+" · "+title) if prefix else title
    rng=_rng(guide,"title-v2")
    style=str(rcfg.get("map_variant_style") or "parchment").strip().lower()

    # Printed directly on the map instead of sitting inside a modern UI plate.
    top=38
    d.line((72,top+3,W-72,top+3),fill=colors["title_rule"],width=1)
    small=_font(s,12,True)
    file_no=s.clean(str(rcfg.get("file_id") or "FIELD-OPS-07"))
    kicker=str(rcfg.get("map_kicker") or "FIELD OPERATION MAP")
    copy_label=str(rcfg.get("copy_label") or "TACTICAL COPY")
    d.text((76,top+10),kicker+"  /  "+file_no,font=small,fill=colors["muted"])
    d.text((W-248,top+10),copy_label,font=small,fill=colors["annotation"])

    size=int(rcfg.get("title_font_size",40) or 40)
    tf=_font(s,size,True)
    while size>28 and _text_w(d,full,tf)>W-150:
        size-=2; tf=_font(s,size,True)
    _distressed_print_text(base,(76,top+35),full,tf,colors["ink_dark"],colors["title_ghost"],rng)
    d.line((72,top+93,W-72,top+93),fill=colors["title_rule"],width=2)
    d.line((72,top+98,W-310,top+98),fill=colors["title_rule_faint"],width=1)

    # Archive mark.  Blueprint mode uses a drafting title block instead of tape/stamp
    # so it cannot be mistaken for the parchment family.
    sx=W-190; sy=top+104
    stamp_text=str(rcfg.get("stamp_text") or "MAP COPY")
    if style=="blueprint_command":
        tech=_rgba(colors.get("variant_overlay",colors["stamp_faint"]),130)
        d.rectangle((sx-18,sy-3,sx+122,sy+38),outline=tech,width=1)
        d.line((sx+58,sy-3,sx+58,sy+38),fill=_rgba(tech,80),width=1)
        d.text((sx-11,sy+3),"DRAWING",font=_font(s,8,True),fill=_rgba(tech,95))
        d.text((sx-11,sy+16),stamp_text,font=_font(s,11,True),fill=tech)
        d.text((sx+65,sy+4),"REV",font=_font(s,8,True),fill=_rgba(tech,95))
        d.text((sx+81,sy+16),"A",font=_font(s,13,True),fill=tech)
        d.ellipse((W-77,18,W-45,50),outline=_rgba(tech,90),width=1)
        d.line((W-61,11,W-61,57),fill=_rgba(tech,65),width=1)
        d.line((W-84,34,W-38,34),fill=_rgba(tech,65),width=1)
    else:
        d.rectangle((sx,sy,sx+116,sy+34),outline=colors["stamp_faint"],width=2)
        d.text((sx+13,sy+7),stamp_text,font=_font(s,13,True),fill=colors["stamp_faint"])
        _draw_tape(base,(W-122,10,W-33,41),(201,188,151,120),angle=-17)

def _panel(draw, box, colors, title, title_fill=None, style="parchment"):
    x1,y1,x2,y2=map(int,box)
    # Small archive sheet pinned to the map. Blueprint mode becomes a clipped-corner
    # technical dossier instead of physical torn paper.
    style=str(style or "parchment").strip().lower()
    rng=random.Random((x1*31+y1*17+x2*13+y2*7) & 0xFFFFFFFF)
    if style=="blueprint_command":
        cut=8
        poly=[(x1+cut,y1),(x2-cut,y1),(x2,y1+cut),(x2,y2-cut),(x2-cut,y2),(x1+cut,y2),(x1,y2-cut),(x1,y1+cut)]
    else:
        poly=_paper_card_polygon(x1,y1,x2,y2,rng,tear=5)
    shadow=[(x+7,y+9) for x,y in poly]
    edge=[(x,y+4) for x,y in poly]
    draw.polygon(shadow,fill=colors["shadow"])
    draw.polygon(edge,fill=colors["card_edge"],outline=colors["panel_border"])
    draw.polygon(poly,fill=colors["panel_paper"],outline=colors["panel_border"])

    # Faint archive grid under the content; deliberately low contrast.
    for xx in range(x1+18,x2-10,30):
        draw.line((xx,y1+42,xx,y2-10),fill=colors.get("panel_grid","#745A3B18"),width=1)
    for yy in range(y1+49,y2-9,26):
        draw.line((x1+12,yy,x2-12,yy),fill=colors.get("panel_grid","#745A3B18"),width=1)

    # Header is a faded field-label strip, not a full-width UI title bar.
    th=36
    fill=title_fill or colors["panel_head"]
    hx1=x1+12; hx2=x2-38
    head=[(hx1+2,y1+7),(hx2-4,y1+5),(hx2,y1+9),(hx2-2,y1+th),(hx1,y1+th+1),(hx1-2,y1+11)]
    draw.polygon(head,fill=fill,outline=colors["panel_border"])
    draw.line((hx1+8,y1+th+4,hx2-5,y1+th+3),fill=colors["paper_highlight"],width=1)

    if style=="blueprint_command":
        tech=_rgba(colors.get("variant_overlay",colors["panel_border"]),120)
        # Drafting registration ticks and document index box.
        for x,y in [(x1+9,y1+9),(x2-9,y1+9),(x1+9,y2-9),(x2-9,y2-9)]:
            draw.line((x-5,y,x+5,y),fill=tech,width=1); draw.line((x,y-5,x,y+5),fill=tech,width=1)
        draw.rectangle((x2-55,y1+8,x2-13,y1+27),outline=_rgba(tech,80),width=1)
    else:
        # Folded corner + paperclip/rivet cues make it feel attached to the map.
        draw.polygon([(x2-33,y1+2),(x2-5,y1+6),(x2-5,y1+31)],fill=colors.get("panel_fold",colors["card_edge"]),outline=colors["panel_border"])
        draw.arc((x1+5,y1+2,x1+28,y1+29),190,505,fill=colors.get("clip",colors["edge_dark"]),width=2)
        draw.ellipse((x2-26,y1+15,x2-20,y1+21),fill=colors["rivet"],outline=colors["edge_dark"])

        # A few short abrasion marks; never cross the main text region heavily.
        for _ in range(5):
            wx=rng.randint(x1+24,max(x1+25,x2-50)); wy=rng.choice([rng.randint(y1+3,y1+34),rng.randint(max(y1+45,y2-25),y2-8)])
            draw.line((wx,wy,wx+rng.randint(5,16),wy+rng.choice([-1,0,1])),fill=colors.get("panel_wear","#60452B22"),width=1)
    return (x1+14,y1+48,x2-14,y2-12)


def _render_kpis(guide, s, max_items=6):
    raw=list(guide.get("kpis") or [])[:max_items]
    try:
        return s.build_render_kpis(raw, guide.get("cfg") or {})
    except Exception:
        out=[]
        for pair in raw:
            if isinstance(pair,(list,tuple)) and len(pair)>=2:
                out.append({"label":s.clean(str(pair[0])),"value":s.clean(str(pair[1]))})
        return out



def _draw_resource_label(draw, box, text, s, fill, max_size=11, min_size=6):
    """Draw a resource label without silently dropping trailing characters.

    Shared ``draw_left(..., max_lines=1)`` first wraps text and then keeps only the
    first wrapped line.  In the narrow two-column INTEL ledger that made longer
    labels look as if only the first few Chinese characters existed.  Here we first
    fit the *whole* label onto one line; only when that is impossible at the minimum
    size do we use two compact lines, still preserving the complete text.
    """
    x1,y1,x2,y2=map(int,box)
    text=s.clean(str(text or "资源"))
    if not text:
        text="资源"
    usable=max(1,x2-x1)
    for size in range(int(max_size),int(min_size)-1,-1):
        f=_font(s,size,True)
        if _text_w(draw,text,f) <= usable:
            bb=draw.textbbox((0,0),text,font=f)
            th=max(1,bb[3]-bb[1])
            yy=y1+max(0,(y2-y1-th)/2)
            # Pillow's default text origin includes the font's top bearing.
            # Subtract bbox top so the visible glyphs stay inside the requested box.
            draw.text((x1,yy-bb[1]),text,font=f,fill=fill)
            return

    # Extremely long custom labels: wrap into two lines at the minimum size, but do
    # not truncate.  Split near the visual midpoint so both lines remain balanced.
    f=_font(s,min_size,True)
    chars=list(text)
    best=None
    for cut in range(1,len(chars)):
        a="".join(chars[:cut]); b="".join(chars[cut:])
        wa=_text_w(draw,a,f); wb=_text_w(draw,b,f)
        if wa<=usable and wb<=usable:
            score=max(wa,wb)+abs(wa-wb)*0.15
            if best is None or score<best[0]:
                best=(score,a,b)
    if best:
        lines=[best[1],best[2]]
        bbs=[draw.textbbox((0,0),ln,font=f) for ln in lines]
        hs=[max(1,bb[3]-bb[1]) for bb in bbs]
        gap=0
        total=sum(hs)+gap
        yy=y1+max(0,(y2-y1-total)/2)
        for ln,hh,bb in zip(lines,hs,bbs):
            draw.text((x1,yy-bb[1]),ln,font=f,fill=fill)
            yy+=hh+gap
        return

    # Last-resort safety for pathological labels: preserve the entire string by
    # horizontally compressing only this tiny ledger label instead of clipping it.
    bb=draw.textbbox((0,0),text,font=f)
    tw=max(1,bb[2]-bb[0]); th=max(1,bb[3]-bb[1])
    layer=Image.new("RGBA",(tw+4,th+4),(0,0,0,0))
    ld=ImageDraw.Draw(layer)
    ld.text((2,2-bb[1]),text,font=f,fill=fill)
    target_w=max(1,usable)
    if layer.width>target_w:
        layer=layer.resize((target_w,layer.height),Image.Resampling.LANCZOS)
    yy=int(y1+max(0,(y2-y1-layer.height)/2))
    if hasattr(draw,"_image"):
        draw._image.paste(layer,(x1,yy),layer)
    else:
        draw.text((x1,yy),text,font=f,fill=fill)


def _draw_kpi_panel(base, guide, s, tools, colors, rcfg, box):
    """Resource intelligence as an old quartermaster ledger, not a 2x2 app grid."""
    d=ImageDraw.Draw(base,"RGBA")
    title=str(rcfg.get("budget_title") or "资源情报 / RESOURCE INTEL")
    inner=_panel(d,box,colors,title,title_fill=colors["panel_head"],style=rcfg.get("map_variant_style","parchment"))
    d.text((box[0]+25,box[1]+10),title,font=_font(s,16,True),fill=colors["panel_head_text"])
    items=_render_kpis(guide,s,int(rcfg.get("budget_max_items",6) or 6))
    if not items:
        s.draw_center(d,inner,"暂无资源预算",colors["muted"],max_size=15,min_size=12,bold=False,max_lines=1)
        return

    x1,y1,x2,y2=map(int,inner)
    n=len(items); cols=1 if n<=2 else 2; rows=int(math.ceil(n/float(cols)))
    gap_x=8; gap_y=7
    cw=(x2-x1-gap_x*(cols-1))/cols
    rh=(y2-y1-gap_y*(rows-1))/rows
    cfg=guide.get("cfg") or {}
    catalog=s.build_item_catalog(cfg)

    def resolve_icon(item,label):
        raw=item.get("icon")
        path=s.resolve_path(cfg,raw) if raw else None
        if path and Path(path).exists():
            return path
        key=label.replace("预算","").replace("资源","").replace("期望","").strip()
        for br in cfg.get("budget_resources") or []:
            aliases=[str(br.get("name") or "")]+[str(x) for x in (br.get("aliases") or [])]
            if any(a and (a in label or a in key or key in a) for a in aliases):
                p=s.resolve_path(cfg,br.get("icon")) if br.get("icon") else None
                if p and Path(p).exists():
                    return p
        meta=s.find_item_meta(key,catalog) or {}
        p=s.resolve_path(cfg,meta.get("icon")) if meta.get("icon") else None
        return p if p and Path(p).exists() else None

    for i,item in enumerate(items):
        col=i%cols; row=i//cols
        a=int(x1+col*(cw+gap_x)); b=int(y1+row*(rh+gap_y)); c=int(a+cw); e=int(b+rh)
        # Ledger entry: warm paper fill, thin ruled lines, no heavy button border.
        d.rectangle((a,b,c,e),fill=colors.get("intel_cell",colors["panel_cell"]))
        d.line((a+3,b+1,c-3,b+1),fill=colors.get("intel_rule",colors["panel_cell_border"]),width=1)
        d.line((a+3,e-2,c-3,e-2),fill=colors.get("intel_rule",colors["panel_cell_border"]),width=1)
        d.line((a+3,b+5,a+3,e-6),fill=colors["olive_rule"],width=2)
        # Tiny archival index makes the four entries read like a requisition form.
        d.text((c-28,b+4),"{:02d}".format(i+1),font=_font(s,8,True),fill=_rgba(colors["muted"],130))

        label=s.clean(str(item.get("label") or "资源")); value=s.clean(str(item.get("value") or "—"))
        label_size=int(rcfg.get("resource_label_font_size",17 if cols==2 else 18) or (17 if cols==2 else 18))

        # Quartermaster-entry layout: the INTEL note is intentionally the same
        # size as the SUPPLY note, so use that recovered cell area for a genuinely
        # larger icon and type rather than leaving the content tiny in a big card.
        # [ icon ]  resource label
        # [      ]  quantity
        # The old layout placed the label across the full cell and then painted the
        # icon on top of it.  In a short two-row panel that physically covered the
        # first Chinese characters (e.g. 钻石预算 -> only the tail stayed visible).
        slot=46 if cols==2 else 52
        sx=a+10
        sy=int(b+max(5,(rh-slot)/2))
        sy=min(sy,e-slot-5)
        d.rectangle((sx,sy,sx+slot,sy+slot),fill=colors.get("icon_slot",colors["panel_paper"]),outline=colors.get("intel_rule",colors["panel_cell_border"]),width=1)
        icon_path=resolve_icon(item,label)
        if icon_path:
            _paste_trimmed_icon(base,icon_path,(sx+3,sy+3,sx+slot-3,sy+slot-3),pad=0)
        else:
            d.ellipse((sx+9,sy+9,sx+slot-9,sy+slot-9),outline=colors["olive_rule"],width=2)

        vx=sx+slot+7
        right=c-7
        # Resource name gets its own top line to the right of the icon.
        # It can shrink slightly for long custom names, but is never hidden behind art.
        label_top=b+7
        label_bottom=min(e-34,b+30)
        _draw_resource_label(
            d,(vx,label_top,right,label_bottom),label,s,colors["ink_mid"],
            max_size=label_size,
            min_size=int(rcfg.get("resource_label_min_font_size",14) or 14),
        )
        # Quantity sits directly below the resource name.  Do NOT vertically
        # center it inside the whole remaining half-cell: that made the visible
        # glyphs drift too close to the bottom rule on short ledger rows.
        # Instead fit the value to width, then place its visible glyph top at a
        # predictable Y coordinate immediately under the label.
        value_max=int(rcfg.get("resource_value_font_size",27 if cols==2 else 29) or (27 if cols==2 else 29))
        value_min=int(rcfg.get("resource_value_min_font_size",20) or 20)
        value_font=None
        value_bbox=None
        for value_size in range(value_max,value_min-1,-1):
            vf=_font(s,value_size,True)
            vb=d.textbbox((0,0),value,font=vf)
            if (vb[2]-vb[0]) <= max(1,right-vx):
                value_font=vf
                value_bbox=vb
                break
        if value_font is None:
            value_font=_font(s,value_min,True)
            value_bbox=d.textbbox((0,0),value,font=value_font)

        value_offset=int(rcfg.get("resource_value_y_offset",0) or 0)
        value_visible_top=max(label_bottom+1,b+31)+value_offset
        value_visible_h=max(1,value_bbox[3]-value_bbox[1])
        # Keep the number clear of the bottom ledger rule even when users tune
        # the offset in theme.json.
        value_visible_top=min(value_visible_top,e-5-value_visible_h)
        d.text((vx,value_visible_top-value_bbox[1]),value,font=value_font,fill=colors["ink_dark"])

def _reward_leaves(nodes):
    out=[]
    def walk(node):
        if not isinstance(node,dict): return
        typ=node.get("type","item")
        if typ=="item": out.append(node)
        elif typ=="bundle":
            for child in node.get("items") or []: walk(child)
        elif typ=="choice":
            for child in node.get("options") or []: walk(child)
    for node in nodes or []: walk(node)
    return out



def _draw_reward_panel(base, guide, s, tools, colors, rcfg, box):
    d=ImageDraw.Draw(base,"RGBA")
    title=str(rcfg.get("reward_title") or "补给清单 / SUPPLY LIST")
    inner=_panel(d,box,colors,title,title_fill=colors["reward_head"],style=rcfg.get("map_variant_style","parchment"))
    d.text((box[0]+25,box[1]+10),title,font=_font(s,16,True),fill=colors["panel_head_text"])
    leaves=_reward_leaves(guide.get("reward_items") or [])[:int(rcfg.get("reward_max_items",6) or 6)]
    if not leaves:
        s.draw_left(d,inner,tools.reward_summary(guide),colors["ink_dark"],max_size=14,min_size=10,bold=False,max_lines=5,line_gap=3,valign="center")
        return
    x1,y1,x2,y2=map(int,inner)
    n=len(leaves); cols=2 if n>1 else 1; rows=int(math.ceil(n/float(cols)))
    gap_x=6; gap_y=4; cw=(x2-x1-gap_x*(cols-1))/cols; rh=(y2-y1-gap_y*(rows-1))/rows
    reward_renderer=RewardItemRenderer(s,guide)
    frame_cfg=int(rcfg.get("reward_frame_size",42) or 42)
    for i,item in enumerate(leaves):
        col=i%cols; row=i//cols
        a=int(x1+col*(cw+gap_x)); b=int(y1+row*(rh+gap_y)); c=int(a+cw); e=int(b+rh)
        d.rectangle((a,b,c,e),fill=colors["panel_cell"],outline=colors["panel_cell_border"],width=1)
        d.line((a+5,e-4,c-5,e-4),fill=colors.get("panel_wear",colors["panel_cell_border"]),width=1)
        frame_size=max(30,min(frame_cfg,int(rh-8),int(cw*0.35)))
        ix=a+7; iy=int(b+(rh-frame_size)/2); ib=(ix,iy,ix+frame_size,iy+frame_size)
        resolved=reward_renderer.draw_icon(
            base,item,ib,
            # Framed reward geometry is global; this plain inset is only for genuinely frameless items.
            plain_inset=3,
            trim_transparent=True,
        )
        icon_path=resolved.get("icon_path")
        if not (icon_path and Path(icon_path).exists()):
            d.rectangle(ib,fill=colors["panel_cell"],outline=colors["panel_cell_border"],width=1)
            s.draw_center(d,ib,"?",colors["ink_mid"],max_size=17,min_size=11,bold=True,max_lines=1,line_gap=0)
        name=s.clean(str(item.get("name") or "物品")); qty=s.clean(str(item.get("qty") or ""))
        tx=ix+frame_size+7
        s.draw_left(
            d,(tx,b+4,c-5,b+int(rh*0.64)),name,colors["ink_dark"],
            max_size=15,min_size=12,bold=True,max_lines=2,line_gap=1,valign="center"
        )
        if qty:
            s.draw_left(
                d,(tx,b+int(rh*0.63),c-5,e-2),"×"+qty,colors["muted"],
                max_size=15,min_size=13,bold=True,max_lines=1,line_gap=0,valign="center"
            )


def _route_points(W, start_y, step, n, rng):
    # The route deliberately wanders through the map instead of behaving like a vertical flowchart.
    # Node positions still leave safe reading zones for the attached Day notes and upper-right dossiers.
    xs=[350,470,330,535,385,565,455]
    pts=[]
    for i in range(n):
        x=xs[i%len(xs)] + rng.randint(-24,24)
        y=start_y+i*step + rng.randint(-8,8)
        pts.append((x,y))
    return pts

def _draw_route(base, points, colors, rng):
    d=ImageDraw.Draw(base,"RGBA")
    if not points:
        return

    def bent(a,b,index,amount=82):
        """Two intermediate bends make each leg look hand-planned around terrain."""
        dx=b[0]-a[0]; dy=b[1]-a[1]; dist=max(1.0,math.hypot(dx,dy))
        px=-dy/dist; py=dx/dist
        sign=-1 if index%2 else 1
        o1=sign*(amount+rng.uniform(-22,22))
        o2=-sign*(amount*0.45+rng.uniform(-18,18))
        p1=(a[0]+dx*0.34+px*o1, a[1]+dy*0.34+py*o1)
        p2=(a[0]+dx*0.69+px*o2, a[1]+dy*0.69+py*o2)
        clamp=lambda p:(max(150,min(base.width-150,p[0])),p[1])
        return [a,clamp(p1),clamp(p2),b]

    # Muted reconnaissance / fallback paths are deliberately incomplete and not parallel copies.
    for shift,col,phase in [(-155,colors["route_blue"],0),(175,colors["route_decoy"],1)]:
        alt=[]
        for i,(x,y) in enumerate(points):
            alt.append((max(55,min(base.width-55,x+shift+int(48*math.sin(i*1.08+phase)))), y+rng.randint(-24,24)))
        for idx,(a,b) in enumerate(zip(alt,alt[1:])):
            poly=bent(a,b,idx+phase,58)
            for p,q in zip(poly,poly[1:]):
                _rough_dash(d,p,q,col,3,rng,dash=17,gap=13)

    # Main red grease-pencil route: non-vector bends, slight double tracing and occasional dry ink.
    for idx,(a,b) in enumerate(zip(points,points[1:])):
        poly=bent(a,b,idx,76)
        for p,q in zip(poly,poly[1:]):
            _rough_line(d,p,q,colors["route_shadow"],11,rng,passes=2,jitter=2.3)
            _rough_line(d,p,q,colors["route_red"],6,rng,passes=3,jitter=1.7)
        # Arrow sits on the longest middle leg and follows its actual heading.
        seg=max(zip(poly,poly[1:]),key=lambda ab:math.hypot(ab[1][0]-ab[0][0],ab[1][1]-ab[0][1]))
        p,q=seg
        ax=p[0]+(q[0]-p[0])*0.64; ay=p[1]+(q[1]-p[1])*0.64
        ang=math.atan2(q[1]-p[1],q[0]-p[0]); size=15
        p0=(ax+math.cos(ang)*size,ay+math.sin(ang)*size)
        p1=(ax+math.cos(ang+2.55)*size,ay+math.sin(ang+2.55)*size)
        p2=(ax+math.cos(ang-2.55)*size,ay+math.sin(ang-2.55)*size)
        d.polygon((p0,p1,p2),fill=colors["route_red"])

    # A few tiny route check ticks add analogue planning character without cluttering text.
    for i,p in enumerate(points[1:-1],1):
        if i%2:
            x,y=p
            col=_rgba(colors.get("pencil_red",colors["route_red"]),92)
            d.line((x-10,y-43,x+2,y-31),fill=col,width=2)
            d.line((x+2,y-31,x+19,y-52),fill=col,width=2)

def _metric_line(info, s):
    parts=[]
    for item in info.get("metric_items") or []:
        lab=s.clean(str(item.get("label") or "")); val=s.clean(str(item.get("value") or ""))
        if lab or val: parts.append((lab+" "+val).strip())
    return " · ".join(parts)



def _draw_day_card(base, guide, info, index, node, s, colors, rcfg, side):
    W=base.width
    style=str(rcfg.get("map_variant_style") or "parchment").strip().lower()
    special=bool(s.clean(str(info.get("special_label") or "")))
    terminal=(index == int(rcfg.get("route_day_count_hint",7) or 7)-1)
    base_w=int(rcfg.get("day_card_width",330) or 330)
    # Normal days read as field-note strips; special/terminal days have slightly more visual weight.
    if special:
        card_w=int(rcfg.get("special_day_card_width",base_w+16) or (base_w+16))
    elif terminal:
        card_w=int(rcfg.get("terminal_day_card_width",base_w+12) or (base_w+12))
    else:
        card_w=int(rcfg.get("normal_day_card_width",base_w-4) or (base_w-4))
    base_h=int(rcfg.get("day_card_height",154) or 154)
    gap=39
    action=s.clean(str(info.get("action") or "—"))

    # Determine all wrapped lines first. Card may grow so numbered steps such as 1-5 are never dropped.
    probe=Image.new("RGBA",(card_w+40,300),(0,0,0,0)); pd=ImageDraw.Draw(probe)
    preferred=int(rcfg.get("day_action_font_size",19) or 19)
    action_bold=bool(rcfg.get("day_action_bold",True))
    action_line_gap=int(rcfg.get("day_action_line_gap",3) or 3)
    prelim_font=_font(s,preferred,action_bold)
    prelim=_wrap(pd,action,prelim_font,card_w-54,None)
    extra=max(0,len(prelim)-3)*19
    type_extra=(10 if special else 0)+(12 if terminal else 0)
    card_h=min(int(rcfg.get("day_card_max_height",214) or 214),base_h+extra+type_extra)

    if side=="left":
        x2=node[0]-gap; x1=x2-card_w
    else:
        x1=node[0]+gap; x2=x1+card_w
    x1=max(34,min(W-card_w-34,x1)); x2=x1+card_w
    # V35.80: the final Day note sits beside the red route terminal.  Give D7 a
    # small rightward bias so the paper no longer masks the red path underneath.
    if terminal:
        shift_x = int(rcfg.get("terminal_note_shift_right", 46) or 0)
        if shift_x:
            x1=max(34,min(W-card_w-34,x1+shift_x)); x2=x1+card_w
    y1=node[1]-card_h//2; y2=y1+card_h

    # V35.78: a long D7 note can grow close to the fixed threat panel. Move the
    # terminal note upward according to both its wrapped-line pressure and its
    # actual lower edge, instead of letting the risk panel cover the paper.
    note_shift_up = 0
    if terminal:
        safe_bottom = int(rcfg.get("terminal_note_safe_bottom", 1862) or 1862)
        line_pressure = max(0, len(prelim)-3) * int(rcfg.get("terminal_note_shift_per_extra_line", 16) or 16)
        edge_pressure = max(0, y2-safe_bottom)
        note_shift_up = min(
            int(rcfg.get("terminal_note_max_shift_up", 150) or 150),
            max(line_pressure, edge_pressure + (12 if edge_pressure else 0))
        )
        y1 -= note_shift_up
        y2 -= note_shift_up

    # Leader follows the shifted paper center so the note remains visibly tied
    # to D7 even when it has been lifted away from the risk panel.
    bd=ImageDraw.Draw(base,"RGBA")
    card_mid_y = int((y1+y2)/2)
    if side=="left":
        bd.line((node[0]-8,node[1],x2+2,card_mid_y),fill=_rgba(colors.get("annotation_rule",colors["rule"]),88),width=1)
    else:
        bd.line((node[0]+8,node[1],x1-2,card_mid_y),fill=_rgba(colors.get("annotation_rule",colors["rule"]),88),width=1)

    pad=20
    note=Image.new("RGBA",(card_w+pad*2,card_h+pad*2),(0,0,0,0))
    nd=ImageDraw.Draw(note,"RGBA")
    rng=random.Random((index+1)*9137 + int(node[1]))
    if style=="blueprint_command":
        # Thin tracing-sheet / drafting-note geometry, with squared corners and datum
        # ticks instead of torn paper.  This is a real structural variant, not a recolour.
        poly=[(pad,pad),(pad+card_w,pad),(pad+card_w,pad+card_h),(pad,pad+card_h)]
        nd.rectangle((pad+5,pad+7,pad+card_w+5,pad+card_h+7),fill=colors["shadow"])
        nd.polygon(poly,fill=_rgba(colors["note_paper"],238),outline=colors["note_border"])
        tech=_rgba(colors.get("variant_overlay",colors["note_border"]),90)
        for xx in range(pad+20,pad+card_w-10,32):
            nd.line((xx,pad+52,xx,pad+card_h-10),fill=_rgba(tech,18),width=1)
        for yy in range(pad+58,pad+card_h-10,24):
            nd.line((pad+12,yy,pad+card_w-12,yy),fill=_rgba(tech,22),width=1)
        for x,y in [(pad+7,pad+7),(pad+card_w-7,pad+7),(pad+7,pad+card_h-7),(pad+card_w-7,pad+card_h-7)]:
            nd.line((x-7,y,x+7,y),fill=tech,width=1); nd.line((x,y-7,x,y+7),fill=tech,width=1)
    else:
        poly=_paper_card_polygon(pad,pad,pad+card_w,pad+card_h,rng,8 if special else 6)
        nd.polygon([(x+6,y+7) for x,y in poly],fill=colors["shadow"])
        nd.polygon([(x,y+3) for x,y in poly],fill=colors["card_edge"],outline=colors["note_border"])
        paper_fill=colors.get("note_paper_special",colors["note_paper"]) if special else colors["note_paper"]
        nd.polygon(poly,fill=paper_fill,outline=colors["note_border"])

        # Paper grain / pencil rules: subtle and deliberately irregular.
        for gy in range(pad+58,pad+card_h-14,24):
            if rng.random()<0.82:
                nd.line((pad+17,gy,pad+card_w-18,gy+rng.choice([-1,0,0,1])),fill=_rgba(colors.get("note_rule",colors["rule"]),28),width=1)

    # Header hierarchy differs by note class instead of seven identical form cards.
    if special:
        head_col=colors.get("special_day_head",colors["special_tag"])
        nd.polygon([(pad+9,pad+8),(pad+card_w-22,pad+7),(pad+card_w-17,pad+40),(pad+10,pad+43)],fill=head_col)
        nd.rectangle((pad+9,pad+8,pad+14,pad+card_h-10),fill=_rgba(colors.get("pencil_red",colors["route_red"]),145))
        class_label="PRIORITY NOTE"
    elif terminal:
        head_col=colors.get("terminal_day_head",colors.get("note_head",colors["card_edge"]))
        nd.polygon([(pad+11,pad+8),(pad+card_w-20,pad+6),(pad+card_w-15,pad+39),(pad+12,pad+42)],fill=head_col)
        class_label="FINAL OBJECTIVE"
    else:
        head_col=colors.get("normal_day_head",colors["note_head"])
        # short field-note strip instead of a full-width form header
        nd.polygon([(pad+12,pad+10),(pad+card_w-58,pad+8),(pad+card_w-52,pad+38),(pad+13,pad+40)],fill=head_col)
        class_label="FIELD NOTE"
    # Dark technical variants need an extra analogue tab so the Day notes do not dissolve into the map paper.
    if style in {"night_recon","blueprint_command"} and not special:
        tab_col=colors.get("normal_day_side_accent",colors.get("normal_accent",colors["note_head_rule"]))
        nd.rectangle((pad+9,pad+48,pad+14,pad+card_h-11),fill=_rgba(tab_col,155))
    nd.line((pad+15,pad+45,pad+card_w-18,pad+45),fill=colors["note_head_rule"],width=2)
    class_fill=colors.get("day_class_text",colors.get("muted",colors["ink_mid"]))
    nd.text((pad+card_w-92,pad+46),class_label,font=_font(s,8,True),fill=_rgba(class_fill,175))

    # Attachment cues vary by card. Blueprint notes use revision/crop marks rather
    # than clips/tape, again separating them from the physical-paper variants.
    if style=="blueprint_command":
        tech=_rgba(colors.get("variant_overlay",colors["note_border"]),115)
        nd.rectangle((pad+card_w-62,pad+8,pad+card_w-15,pad+29),outline=tech,width=1)
        nd.text((pad+card_w-56,pad+12),"REV A",font=_font(s,7,True),fill=tech)
    else:
        if index%3==0:
            nd.arc((pad+11,pad+6,pad+31,pad+31),190,510,fill=colors["clip"],width=2)
        elif index%3==1:
            nd.rectangle((pad+card_w-54,pad-1,pad+card_w-14,pad+12),fill=(205,188,145,105))
        else:
            nd.ellipse((pad+card_w-29,pad+14,pad+card_w-22,pad+21),fill=colors["rivet"],outline=colors["edge_dark"])
        nd.polygon([(pad+card_w-34,pad),(pad+card_w-4,pad+3),(pad+card_w-5,pad+30)],fill=colors["note_fold"])

    day=s.clean(str(info.get("day") or f"D{index+1}"))
    target=s.clean(str(info.get("target") or ""))
    head=day + (("  "+str(rcfg.get("target_label") or "目标")+" "+target) if target else "")
    if special:
        head_fill=colors.get("special_day_title_text",colors.get("special_text",colors["ink_dark"]))
    elif terminal:
        head_fill=colors.get("terminal_day_title_text",colors.get("normal_day_title_text",colors["ink_dark"]))
    else:
        head_fill=colors.get("normal_day_title_text",colors["ink_dark"])
    nd.text((pad+18,pad+13),head,font=_font(s,int(rcfg.get("day_title_size",19) or 19),True),fill=head_fill)

    has_metrics=bool(info.get("metric_items"))
    metric_h=58 if has_metrics else 0
    action_top=pad+57
    action_bottom=pad+card_h-(metric_h+12 if has_metrics else 12)
    action_font,lines,line_gap=_fit_action_lines(
        nd,s,action,card_w-54,action_bottom-action_top,preferred,
        int(rcfg.get("day_action_min_font_size",16) or 16),
        bold=action_bold,preferred_gap=action_line_gap
    )
    yy=action_top
    bb=nd.textbbox((0,0),"国Ag",font=action_font); lh=max(1,bb[3]-bb[1])
    for line in lines:
        stripped=line.lstrip()
        numbered=bool(re.match(r'^[1-9][\.、\)）:\s]',stripped))
        if not numbered:
            mark_col=colors["route_red"] if special else colors.get("normal_accent",colors["olive_rule"])
            nd.line((pad+18,yy+lh*0.55,pad+25,yy+lh*0.55),fill=mark_col,width=2)
            tx=pad+32
        else:
            tx=pad+18
        nd.text((tx,yy),line,font=action_font,fill=colors.get("action_ink",colors["ink_dark"]))
        yy+=lh+line_gap
    if has_metrics:
        tools=SharedRendererTools(s)
        my2=pad+card_h-7
        my1=my2-metric_h
        tools.draw_metric_icons(
            note, nd, guide, info,
            (pad+16,my1,pad+card_w-16,my2),
            colors["ink_dark"], colors.get("normal_accent",colors["olive_rule"]),
            bg=colors.get("panel_cell",colors["panel_paper"]),
            border=colors.get("panel_cell_border",colors["rule"])
        )

    if terminal:
        # Small completion stamp on the paper itself, separate from the node's flag.
        nd.rectangle((pad+card_w-92,pad+card_h-36,pad+card_w-15,pad+card_h-12),outline=_rgba(colors["route_red"],145),width=2)
        nd.text((pad+card_w-82,pad+card_h-32),"COMPLETE",font=_font(s,8,True),fill=_rgba(colors["route_red"],165))

    if style=="blueprint_command":
        # Drafting slips are aligned to the drawing grid with only minute registration skew.
        angle=rng.uniform(-0.28,0.28)
    elif terminal:
        angle=0.45+rng.uniform(-0.25,0.25)
    elif special:
        angle=(-1.1 if index%2==0 else 1.1)+rng.uniform(-0.35,0.35)
    else:
        angle=(-1.8 if index%2==0 else 1.55)+rng.uniform(-0.45,0.45)
    rot=note.rotate(angle,expand=True,resample=Image.Resampling.BICUBIC)
    base.alpha_composite(rot,(int(x1-(rot.width-card_w)/2),int(y1-(rot.height-card_h)/2)))

    d=ImageDraw.Draw(base,"RGBA")
    cx,cy=node; r=int(rcfg.get("node_radius",31) or 31)
    point_fill=colors["node_fill_special"] if special else colors["node_fill"]
    point_border=colors["node_border_special"] if special else colors.get("node_border_normal",colors["node_border"])
    point_outer=colors["node_outer_special"] if special else colors.get("node_outer_normal",colors["node_outer"])
    if style in {"night_recon","blueprint_command"} and not special:
        halo=colors.get("node_halo_normal",colors.get("normal_accent",colors["node_gold"]))
        d.ellipse((cx-r-11,cy-r-11,cx+r+11,cy+r+11),outline=_rgba(halo,165),width=3)
    d.ellipse((cx-r-7,cy-r-7,cx+r+7,cy+r+7),fill=point_outer,outline=colors["node_gold"],width=2)
    d.ellipse((cx-r-2,cy-r-2,cx+r+2,cy+r+2),outline=point_border,width=2)
    d.ellipse((cx-r+3,cy-r+3,cx+r-3,cy+r-3),fill=point_fill,outline=point_border,width=2)
    for ang in (0,90,180,270):
        a=math.radians(ang)
        d.line((cx+math.cos(a)*(r+3),cy+math.sin(a)*(r+3),cx+math.cos(a)*(r+10),cy+math.sin(a)*(r+10)),fill=point_border,width=2)
    label=day.replace("DAY","D").replace("Day","D")
    if special:
        node_text_col=colors.get("node_text_special",colors["node_text"])
    elif terminal:
        node_text_col=colors.get("node_text_terminal",colors.get("node_text_normal",colors["node_text"]))
    else:
        node_text_col=colors.get("node_text_normal",colors["node_text"])
    s.draw_center(d,(cx-r+4,cy-r+4,cx+r-4,cy+r-4),label,node_text_col,max_size=17,min_size=12,bold=True,max_lines=1,line_gap=0)
    if terminal:
        d.ellipse((cx-r-13,cy-r-13,cx+r+13,cy+r+13),outline=colors["route_red"],width=3)
        d.ellipse((cx-r-18,cy-r-18,cx+r+18,cy+r+18),outline=colors["node_gold"],width=1)
        _draw_flag(d,cx+r+14,cy-r+8,colors,0.88)
        d.text((cx-r-5,cy+r+25),"终点 / COMPLETE",font=_font(s,10,True),fill=colors["route_red"])
    if special:
        tag=s.clean(str(info.get("special_label") or "重点"))
        tw=min(142,max(62,int(_text_w(d,tag,_font(s,11,True))+18)))
        tx=cx-tw//2; ty=cy+r+10
        d.rectangle((tx,ty,tx+tw,ty+23),fill=colors["special_tag"],outline=colors["node_gold"],width=1)
        s.draw_center(d,(tx+3,ty+1,tx+tw-3,ty+22),tag,colors["special_text"],max_size=11,min_size=9,bold=True,max_lines=1,line_gap=0)

def _draw_risk_panel(base, guide, s, colors, rcfg, box):
    d=ImageDraw.Draw(base,"RGBA")
    risks=guide.get("risk") or []
    if isinstance(risks,str): risks=[x.strip() for x in risks.splitlines() if x.strip()]
    risks=[s.clean(str(x)) for x in risks if s.clean(str(x))]
    title=str(rcfg.get("risk_title") or "敌情分析 / THREAT ASSESSMENT")
    x1,y1,x2,y2=map(int,box)
    d.polygon([(x1+5,y1),(x2-6,y1),(x2,y1+7),(x2,y2-6),(x2-7,y2),(x1+6,y2),(x1,y2-6),(x1,y1+7)],fill=colors["panel_paper"],outline=colors["panel_border"])
    head_h=44
    d.polygon([(x1+5,y1),(x2-6,y1),(x2,y1+7),(x2,y1+head_h),(x1,y1+head_h),(x1,y1+7)],fill=colors["risk_head"],outline=colors["panel_border"])
    d.text((x1+24,y1+8),title,font=_font(s,19,True),fill=colors["risk_head_text"])
    rng=random.Random(y1*17+31)
    # Fewer wear specks keep the red stamp texture without making the PNG noisy.
    for _ in range(15):
        xx=rng.randint(x1+10,x2-12); yy=rng.randint(y1+5,y1+head_h-5)
        d.rectangle((xx,yy,xx+rng.randint(1,3),yy+rng.randint(1,2)),fill=colors["risk_wear"])
    if not risks:
        s.draw_left(d,(x1+22,y1+head_h+8,x2-20,y2-10),"暂无额外风险提示",colors["muted"],max_size=17,min_size=13,bold=True,max_lines=1,line_gap=0,valign="center")
        return
    content_top=y1+head_h+5; content_bottom=y2-8
    row_h=(content_bottom-content_top)/max(1,len(risks))
    base_size=int(rcfg.get("risk_font_size",19) or 19)
    min_size=int(rcfg.get("risk_min_font_size",14) or 14)
    bold=bool(rcfg.get("risk_bold",True))
    for i,risk in enumerate(risks):
        yy=int(content_top+i*row_h); ye=int(content_top+(i+1)*row_h)
        if i>0: d.line((x1+18,yy,x2-18,yy),fill=colors["rule"],width=1)
        d.polygon([(x1+24,yy+11),(x1+32,yy+25),(x1+16,yy+25)],fill=colors["warning"],outline=colors["edge_dark"])
        s.draw_left(d,(x1+45,yy+3,x2-20,ye-3),risk,colors["ink_dark"],max_size=base_size,min_size=min_size,bold=bold,max_lines=2,line_gap=3,valign="center")

def _draw_compass(draw, center, colors, style="parchment"):
    cx,cy=center
    r=82
    style=str(style or "parchment").lower()
    draw.ellipse((cx-r,cy-r,cx+r,cy+r),fill=colors["compass_bg"],outline=colors["compass"],width=3)
    draw.ellipse((cx-r+11,cy-r+11,cx+r-11,cy+r-11),outline=colors["compass_faint"],width=1)
    draw.ellipse((cx-r+24,cy-r+24,cx+r-24,cy+r-24),outline=colors["compass_faint"],width=1)
    for ang in range(0,360,30):
        a=math.radians(ang)
        x1=cx+math.cos(a)*(r-12); y1=cy+math.sin(a)*(r-12)
        x2=cx+math.cos(a)*(r+2); y2=cy+math.sin(a)*(r+2)
        draw.line((x1,y1,x2,y2),fill=colors["compass"],width=2 if ang%90==0 else 1)
    draw.polygon([(cx,cy-r+15),(cx-13,cy+12),(cx,cy+2),(cx+13,cy+12)],fill=colors["route_red"],outline=colors["edge_dark"])
    draw.polygon([(cx,cy+r-15),(cx-11,cy-10),(cx,cy-2),(cx+11,cy-10)],fill=colors["compass_blue"],outline=colors["edge_dark"])
    draw.ellipse((cx-6,cy-6,cx+6,cy+6),fill=colors["node_gold"],outline=colors["edge_dark"])
    if style=="night_recon":
        # Recon variant: bearing/range marks make the compass read like a night plotting instrument.
        draw.line((cx-r+16,cy,cx+r-16,cy),fill=_rgba(colors.get("variant_overlay",colors["compass_blue"]),70),width=1)
        draw.line((cx,cy-r+16,cx,cy+r-16),fill=_rgba(colors.get("variant_overlay",colors["compass_blue"]),70),width=1)
        draw.ellipse((cx-33,cy-33,cx+33,cy+33),outline=_rgba(colors.get("variant_overlay",colors["compass_blue"]),65),width=1)
    elif style=="blueprint_command":
        # Blueprint variant: instrument-style datum cross and range ticks.
        tech=_rgba(colors.get("variant_overlay",colors["compass_blue"]),92)
        draw.rectangle((cx-r+9,cy-r+9,cx+r-9,cy+r-9),outline=_rgba(tech,45),width=1)
        draw.line((cx-r+13,cy,cx+r-13,cy),fill=tech,width=1)
        draw.line((cx,cy-r+13,cx,cy+r-13),fill=tech,width=1)
        for ang in range(0,360,45):
            a=math.radians(ang)
            x1=cx+math.cos(a)*(r+5); y1=cy+math.sin(a)*(r+5)
            x2=cx+math.cos(a)*(r+11); y2=cy+math.sin(a)*(r+11)
            draw.line((x1,y1,x2,y2),fill=tech,width=1)


def _save_battle_png(img, out_path, guide, started, rcfg):
    """Save this parchment-heavy theme efficiently without changing other themes.

    A 256-colour indexed PNG is visually well suited to a low-saturation printed-map
    aesthetic and dramatically reduces the cost of paper grain/anti-aliased decoration.
    Set renderer.png_palette_colors to 0 to force full RGB output.
    """
    out_path=Path(out_path)
    out_path.parent.mkdir(parents=True,exist_ok=True)
    rgb=img.convert("RGB")
    palette=max(0,min(256,int(rcfg.get("png_palette_colors",256) or 0)))
    packed=rgb
    if palette>=16:
        try:
            packed=rgb.quantize(colors=palette,method=Image.Quantize.MEDIANCUT,dither=Image.Dither.NONE)
        except Exception:
            packed=rgb
    packed.save(out_path,"PNG",optimize=True,compress_level=9)
    cfg=guide.get("cfg") or {}
    perf=cfg.get("performance") if isinstance(cfg.get("performance"),dict) else {}
    if started is not None and bool(perf.get("print_timing",False)):
        print("[耗时] {}：{:.2f} 秒".format(out_path.name,time.perf_counter()-started))


def render(guide, out_path: Path, services):
    started=time.perf_counter()
    tools=SharedRendererTools(services)
    rcfg=_rcfg(guide)
    colors=tools.colors(guide,{
        "background":"#B89964","paper":"#C9AE79","paper_light":"#DDC89B","edge":"#6A482B","edge_dark":"#442B1B",
        "map_grid":"#765B3E24","map_grid_major":"#72553936","map_line":"#6E51362E","contour":"#6D51312F","faint_mark":"#66482932",
        "fold":"#65452B20","fold_highlight":"#FFF1C91A","annotation":"#66513A62","annotation_rule":"#65513A58",
        "ink_dark":"#432B20","ink_mid":"#523A2C","muted":"#735F49","rule":"#A28A66","shadow":"#3D291F45",
        "title_plate":"#CDB582","title_border":"#806039","title_rule":"#80633E","title_rule_faint":"#8C704848","title_ghost":"#704C3880","stamp_faint":"#79543E88",
        "card_edge":"#A78B5D","paper_highlight":"#F6E8C8A8","rivet":"#A78954",
        "pencil_red":"#8D3A31","pencil_highlight":"#B96554","pencil_wood":"#C6A36E","clip":"#68533F",
        "panel_paper":"#D3C097","panel_border":"#78603F","panel_head":"#596346","panel_head_text":"#F1E5C6","panel_cell":"#DED0AC","panel_cell_border":"#A89570","olive_rule":"#747A54",
        "reward_head":"#62523E","note_paper":"#D8C49A","note_border":"#806746","note_fold":"#B49A6D","note_head":"#C6AD7B","note_head_rule":"#876A45",
        "route_red":"#843C34","route_shadow":"#4A2E2638","route_blue":"#456B7994","route_decoy":"#79504A73",
        "node_outer":"#C3AB75","node_fill":"#91453C","node_fill_special":"#74342F","node_border":"#572D28","node_gold":"#B18F52","node_text":"#F1E4C4",
        "special_tag":"#6C3832","special_text":"#EFE1BF","risk_head":"#7A4036","risk_head_text":"#EFE1C1","risk_wear":"#D1B17D28","warning":"#A98535",
        "compass":"#66503B","compass_faint":"#8B7557","compass_blue":"#4C6B73","compass_bg":"#D3C19766",
        "primary":"#843C34","dark":"#432B20","light":"#DDC89B","chip":"#BFA77A",
    })

    # This theme intentionally targets a standard phone canvas, independent of content length.
    W=int(rcfg.get("canvas_width",1080) or 1080)
    H=int(rcfg.get("canvas_height",2340) or 2340)
    days=list(guide.get("days") or [])[:7]
    n=max(1,len(days))
    rcfg=dict(rcfg); rcfg["route_day_count_hint"]=n

    base=Image.new("RGBA",(W,H),colors["paper"])
    _draw_map_texture(base,colors,_rng(guide,"map-v2"),rcfg)
    # Semantic terrain sits below every information layer and makes the route feel geographic.
    _draw_terrain_features(base,colors,_rng(guide,"terrain-v3"),int(rcfg.get("route_start_y",324) or 324),int(rcfg.get("route_end_y",1792) or 1792))
    _draw_variant_overlay(base,colors,rcfg,_rng(guide,"variant-overlay-v1"))
    _draw_title(base,guide,services,colors,rcfg)

    # Smaller edge dossiers: secondary to the route. Upper-left remains open for D1/D2 flow.
    intel_x1=int(rcfg.get("intel_panel_x1",W-350) or (W-350)); intel_x2=int(rcfg.get("intel_panel_x2",W-44) or (W-44))
    # KPI / reward are deliberately treated as one matched stack.  Both notes
    # share exactly the same dimensions; moving the KPI down automatically moves
    # reward and compass down as well, preventing overlap between the three props.
    intel_h=int(rcfg.get("intel_note_height", rcfg.get("intel_reward_height", 212)) or 212)
    kpi_y1=int(rcfg.get("intel_kpi_y",238) or 238)
    intel_gap=int(rcfg.get("intel_note_gap",14) or 14)
    reward_y1=int(rcfg.get("intel_reward_y",kpi_y1+intel_h+intel_gap) or (kpi_y1+intel_h+intel_gap))
    # Enforce identical sizes even if an older variant still carries legacy
    # intel_kpi_height / intel_reward_height values.
    kpi_h=reward_h=intel_h
    _draw_kpi_panel(base,guide,services,tools,colors,rcfg,(intel_x1,kpi_y1,intel_x2,kpi_y1+kpi_h))
    _draw_reward_panel(base,guide,services,tools,colors,rcfg,(intel_x1,reward_y1,intel_x2,reward_y1+reward_h))

    # Route uses the central field and is guaranteed to end above the fixed threat/footer area.
    route_start=int(rcfg.get("route_start_y",324) or 324)
    route_end_target=int(rcfg.get("route_end_y",1792) or 1792)
    if n<=1:
        route_step=0
    else:
        route_step=max(190,min(310,int((route_end_target-route_start)/(n-1))))
    route_end=route_start+(n-1)*route_step
    pts=_route_points(W,route_start,route_step,n,_rng(guide,"route-v2"))
    _draw_map_annotations(base,services,colors,rcfg,_rng(guide,"annot-v2"),route_start,route_end)
    _draw_route(base,pts,colors,_rng(guide,"decoys-v3"))
    _draw_field_annotations(base,days,pts,services,colors,rcfg,_rng(guide,"field-notes-v3"))

    sides=["left","left","right","left","right","left","right"]
    for i,info in enumerate(days):
        _draw_day_card(base,guide,info,i,pts[i],services,colors,rcfg,sides[i%len(sides)])

    d=ImageDraw.Draw(base,"RGBA")
    compass_x=int(rcfg.get("compass_x",866) or 866)
    compass_y=int(rcfg.get("compass_y",780) or 780)
    # A compass radius is 82 px; preserve a visual gap below the matched intel notes.
    compass_y=max(compass_y, reward_y1+reward_h+104)
    _draw_compass(d,(compass_x,compass_y),colors,rcfg.get("map_variant_style","parchment"))

    # A faded file tag stays peripheral rather than competing with the route.
    tag_y=1834
    d.polygon([(W-250,tag_y),(W-58,tag_y),(W-51,tag_y+7),(W-51,tag_y+47),(W-58,tag_y+54),(W-250,tag_y+54)],fill=colors["panel_paper"],outline=colors["panel_border"])
    file_no=str(rcfg.get("file_id") or "FIELD-OPS-07")
    services.draw_center(d,(W-240,tag_y+4,W-62,tag_y+48),file_no,colors["muted"],max_size=13,min_size=10,bold=True,max_lines=1,line_gap=0)

    # Fixed bottom information band keeps the complete composition at exactly 1080x2340.
    risk_y=1906; risk_bottom=2144
    _draw_risk_panel(base,guide,services,colors,rcfg,(48,risk_y,W-48,risk_bottom))

    # QQ group / community contact replaces the former commander hint.
    fy=2161; fy2=2317
    footer_poly=[(92,fy+5),(W-94,fy),(W-84,fy+9),(W-84,fy2-8),(W-94,fy2),(92,fy2),(82,fy2-10),(82,fy+13)]
    d.polygon([(x+6,y+7) for x,y in footer_poly],fill=colors["shadow"])
    d.polygon(footer_poly,fill=colors["panel_paper"],outline=colors["panel_border"])
    d.line((108,fy+36,W-108,fy+36),fill=colors["title_rule_faint"],width=1)
    d.text((112,fy+10),"通讯联络 / QQ GROUP",font=_font(services,13,True),fill=colors["muted"])
    cfg=guide.get("cfg") or {}
    group_icon=services.resolve_path(cfg,cfg.get("watermark_group_icon")) if cfg.get("watermark_group_icon") else None
    icon_box=(112,fy+52,178,fy+118)
    if group_icon and Path(group_icon).exists():
        d.rectangle(icon_box,fill=colors["note_paper"],outline=colors["panel_border"],width=2)
        _paste_trimmed_icon(base,group_icon,(118,fy+58,172,fy+112),pad=0)
        text_x=198
    else:
        d.ellipse((116,fy+64,160,fy+108),outline=colors["olive_rule"],width=2)
        d.text((126,fy+72),"QQ",font=_font(services,13,True),fill=colors["olive_rule"])
        text_x=181
    group_text=_footer_group_text(guide,rcfg,services)
    services.draw_left(d,(text_x,fy+49,W-112,fy+123),group_text,colors["ink_dark"],max_size=int(rcfg.get("footer_font_size",20) or 20),min_size=15,bold=True,max_lines=2,line_gap=3,valign="center")
    d.text((text_x,fy+126),"加入后请查看群公告与最新活动说明",font=_font(services,13,False),fill=colors["muted"])

    _draw_tape(base,(10,H-73,118,H-43),(201,188,151,142),angle=24)
    _draw_tape(base,(W-132,H-79,W-20,H-49),(201,188,151,142),angle=-18)
    _save_battle_png(base,out_path,guide,started,rcfg)

