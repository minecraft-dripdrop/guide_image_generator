# -*- coding: utf-8 -*-
"""Renderer module for ``magazine_2005``."""
import math
import random
import time
from pathlib import Path
from PIL import Image, ImageDraw
from .shared import SharedRendererTools

STYLE_IDS = ("magazine_2005",)


def render(guide, out_path: Path, services):
    W, H = services.W, services.H
    clean = services.clean
    draw_center = services.draw_center
    draw_left = services.draw_left
    draw_image_contain = services.draw_image_contain
    get_font = services.get_font
    r = SharedRendererTools(services)
    _renderer_colors = r.colors
    _renderer_risk_items = r.risk_items
    _renderer_kpis = r.kpis
    _renderer_author = r.author
    _renderer_save = r.save
    _renderer_rule = r.rule
    _renderer_text = r.text
    _renderer_footer_plain = r.footer_plain
    _renderer_day_title = r.day_title
    _renderer_metric_text = r.metric_text
    _renderer_draw_simple_kpis = r.draw_simple_kpis
    _renderer_reward_summary = r.reward_summary
    _renderer_draw_reward_icons = r.draw_reward_icons
    _renderer_draw_kpis_with_icons = r.draw_kpis_with_icons
    _renderer_draw_metric_icons = r.draw_metric_icons
    """2005 年电玩杂志攻略页：硬边、多栏、编号、编辑批注。"""
    started = time.perf_counter()
    c = _renderer_colors(guide, {
        "background":"#EDE3C7", "paper":"#F7EED7", "text":"#25211A",
        "primary":"#D65325", "dark":"#512A1B", "light":"#F3D69B", "chip":"#D7BA7E",
        "ink":"#25211A", "rule":"#6E5942", "note":"#FFE06B"
    })
    img = Image.new("RGBA", (W,H), c["background"])
    d = ImageDraw.Draw(img)
    # 纸张噪点/旧印刷网点
    rng = random.Random("magazine:"+str(guide.get("sheet")))
    for _ in range(1400):
        x=rng.randrange(W); y=rng.randrange(H)
        shade = rng.choice(["#E6D9B8","#F4E8CB","#D8C9A6"])
        d.point((x,y), fill=shade)
    d.rectangle((28,24,W-28,H-62), fill=c.get("paper","#F7EED7"), outline=c.get("rule","#6E5942"), width=3)
    # 杂志刊头
    d.rectangle((48,48,W-48,132), fill=c["ink"])
    d.text((68,62), "GAME STRATEGY FILE", font=get_font(28,True), fill=c.get("light","#F3D69B"))
    d.text((W-260,66), "VOL.2005 / SPECIAL", font=get_font(16,True), fill="#FFFFFF")
    title = guide.get("title") or "活动攻略"
    draw_left(d,(56,150,W-330,292),title,c["primary"],max_size=54,min_size=34,bold=True,max_lines=2,line_gap=3,valign="center")
    subtitle = clean(str(guide.get("subtitle") or ""))
    if subtitle:
        draw_left(d,(60,288,W-330,338),subtitle,c["dark"],max_size=20,min_size=14,bold=False,max_lines=1,line_gap=0,valign="center")
    # 右上角“封面贴纸”式情报块
    d.polygon([(790,148),(1018,148),(994,318),(770,318)], fill=c["primary"], outline=c["ink"])
    draw_center(d,(792,162,997,217),"攻略速报", "#FFFFFF",max_size=25,min_size=18,bold=True,max_lines=1)
    draw_center(d,(792,220,997,302),_renderer_author(guide),"#FFFFFF",max_size=16,min_size=11,bold=False,max_lines=2)
    _renderer_rule(d,(52,348,W-52,348),c["ink"],5)
    _renderer_rule(d,(52,358,W-52,358),c["primary"],2)
    # 数据栏与奖励栏
    d.text((58,378),"01 / QUICK DATA",font=get_font(22,True),fill=c["ink"])
    _renderer_draw_kpis_with_icons(img,d,guide,(58,416,W-58,532),c["ink"],c["primary"],fill="#FFF9E9",border=c["rule"],compact=True)
    d.text((58,558),"02 / EXCHANGE PICK",font=get_font(22,True),fill=c["ink"])
    d.rectangle((58,594,W-58,708),fill=c.get("light","#F3D69B"),outline=c["ink"],width=2)
    _renderer_draw_reward_icons(img,d,guide,(78,600,W-78,700),c["ink"],c["primary"],max_items=6,show_names=True)
    # 两栏流程，不对称硬边卡
    d.text((58,740),"03 / DAY-BY-DAY WALKTHROUGH",font=get_font(24,True),fill=c["ink"])
    days=guide.get("days") or []
    top=790; bottom=1850; gapx=24; gapy=18; cols=2; rows=math.ceil(len(days)/2)
    cw=(W-116-gapx)/2; rh=(bottom-top-gapy*max(0,rows-1))/max(1,rows)
    for i,info in enumerate(days):
        r=i//2; col=i%2
        x1=58+col*(cw+gapx); y1=top+r*(rh+gapy); x2=x1+cw; y2=y1+rh
        # 偶数项偏移制造杂志不规则节奏
        if col==1 and r%2==0: y1+=8; y2+=8
        d.rectangle((int(x1),int(y1),int(x2),int(y2)),fill="#FFF9E9",outline=c["ink"],width=3)
        d.rectangle((int(x1),int(y1),int(x1+76),int(y1+44)),fill=c["ink"])
        d.text((int(x1+13),int(y1+8)),f"{i+1:02d}",font=get_font(19,True),fill="#FFFFFF")
        draw_left(d,(x1+90,y1+5,x2-12,y1+49),_renderer_day_title(info),c["primary"],max_size=21,min_size=14,bold=True,max_lines=1,line_gap=0,valign="center")
        _renderer_rule(d,(x1+14,y1+56,x2-14,y1+56),c.get("rule","#6E5942"),1)
        action=clean(str(info.get("action") or ""))
        draw_left(d,(x1+16,y1+66,x2-16,y2-54),action,c["ink"],max_size=19,min_size=12,bold=False,max_lines=6,line_gap=3,valign="top")
        if info.get("metric_items"):
            _renderer_draw_metric_icons(img,d,guide,info,(x1+12,y2-46,x2-12,y2-10),c["dark"],c["primary"],bg=c.get("light","#F3D69B"))
        special=clean(str(info.get("special_label") or ""))
        if special:
            # 黄色编辑贴纸
            d.polygon([(int(x2-118),int(y1-8)),(int(x2-10),int(y1+2)),(int(x2-16),int(y1+40)),(int(x2-124),int(y1+30))],fill=c.get("note","#FFE06B"),outline=c["ink"])
            draw_center(d,(x2-120,y1-5,x2-14,y1+34),special,c["ink"],max_size=14,min_size=10,bold=True,max_lines=1)
    # 风险 / 编辑部批注
    risks=_renderer_risk_items(guide)
    y1=1884
    d.rectangle((58,y1,W-58,H-92),fill="#FFF9E9",outline=c["primary"],width=4)
    d.rectangle((58,y1,268,y1+52),fill=c["primary"])
    draw_center(d,(64,y1+2,262,y1+50),"EDITOR'S NOTE","#FFFFFF",max_size=18,min_size=13,bold=True,max_lines=1)
    note="\n".join("◆ "+x for x in risks[:4]) if risks else "◆ 关键节点按实际资源量微调，避免为冲档过度消耗。"
    draw_left(d,(84,y1+68,W-84,H-112),note,c["ink"],max_size=19,min_size=12,bold=False,max_lines=8,line_gap=7,valign="top")
    _renderer_footer_plain(d,guide,c["ink"],line=c["ink"],bg=c.get("paper","#F7EED7"),height=58)
    _renderer_save(img,out_path,guide,started)
