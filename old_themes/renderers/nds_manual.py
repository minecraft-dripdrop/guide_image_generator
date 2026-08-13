# -*- coding: utf-8 -*-
"""Renderer module for ``nds_manual``."""
import math
import random
import time
from pathlib import Path
from PIL import Image, ImageDraw
from .shared import SharedRendererTools

STYLE_IDS = ("nds_manual",)


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
    """NDS 游戏说明书：大量留白、细线、步骤编号与注意事项。"""
    started=time.perf_counter()
    c=_renderer_colors(guide,{"background":"#F4F4F0","text":"#25282A","primary":"#D63A36","dark":"#1F5E83","light":"#E7F1F5","chip":"#C6DCE8","rule":"#868C90"})
    img=Image.new("RGBA",(W,H),c["background"]); d=ImageDraw.Draw(img)
    # 说明书页边与裁切标记
    d.rectangle((42,38,W-42,H-64),fill="#FFFFFF",outline="#B5B8BA",width=2)
    for x,y in [(42,38),(W-42,38),(42,H-64),(W-42,H-64)]:
        d.line((x-16,y,x+16,y),fill=c["primary"],width=2); d.line((x,y-16,x,y+16),fill=c["primary"],width=2)
    d.text((68,66),"HOW TO PLAY",font=get_font(20,True),fill=c["primary"])
    d.text((W-184,68),"P. 07",font=get_font(18,True),fill=c["dark"])
    draw_left(d,(68,104,W-68,214),guide.get("title") or "活动攻略",c["text"],max_size=46,min_size=28,bold=True,max_lines=2,line_gap=3,valign="center")
    if guide.get("subtitle"):
        draw_left(d,(70,210,W-70,254),guide.get("subtitle"),c["dark"],max_size=18,min_size=13,bold=False,max_lines=1,line_gap=0,valign="center")
    _renderer_rule(d,(68,274,W-68,274),c["text"],2)
    d.text((68,300),"BASIC DATA",font=get_font(18,True),fill=c["dark"])
    _renderer_draw_kpis_with_icons(img,d,guide,(68,336,W-68,440),c["text"],c["primary"],fill=None,border=c["rule"],compact=True)
    _renderer_rule(d,(68,462,W-68,462),"#C4C6C8",1)
    d.text((68,482),"ITEMS",font=get_font(15,True),fill=c["dark"]); _renderer_draw_reward_icons(img,d,guide,(150,472,W-68,580),c["text"],c["primary"],max_items=6,show_names=True)
    days=guide.get("days") or []
    top=612; bottom=1870; rows=math.ceil(len(days)/2); gapx=42; gapy=20; cw=(W-136-gapx)/2; rh=(bottom-top-gapy*max(0,rows-1))/max(1,rows)
    for i,info in enumerate(days):
        r=i//2; col=i%2; x1=68+col*(cw+gapx); y1=top+r*(rh+gapy); x2=x1+cw; y2=y1+rh
        d.ellipse((int(x1),int(y1+2),int(x1+54),int(y1+56)),fill=c["primary"])
        draw_center(d,(x1,y1+2,x1+54,y1+56),str(i+1),"#FFFFFF",max_size=22,min_size=18,bold=True,max_lines=1)
        d.text((int(x1+68),int(y1+4)),"STEP",font=get_font(12,True),fill=c["rule"])
        draw_left(d,(x1+68,y1+22,x2,y1+58),_renderer_day_title(info),c["dark"],max_size=20,min_size=13,bold=True,max_lines=1,line_gap=0,valign="center")
        _renderer_rule(d,(x1+68,y1+62,x2,y1+62),c["primary"],2)
        draw_left(d,(x1,y1+76,x2,y2-44),info.get("action") or "",c["text"],max_size=18,min_size=12,bold=False,max_lines=6,line_gap=4,valign="top")
        if info.get("metric_items"):
            _renderer_draw_metric_icons(img,d,guide,info,(x1,y2-42,x2,y2-4),c["rule"],c["primary"])
    risks=_renderer_risk_items(guide)
    ry=1905
    d.rectangle((68,ry,W-68,H-104),fill=c.get("light","#E7F1F5"),outline=c["primary"],width=2)
    d.rectangle((68,ry,202,ry+46),fill=c["primary"])
    draw_center(d,(72,ry+2,198,ry+44),"CAUTION!","#FFFFFF",max_size=16,min_size=12,bold=True,max_lines=1)
    body="\n".join("!  "+x for x in risks[:4]) if risks else "!  到达目标档位后及时停止，保留剩余资源。"
    draw_left(d,(92,ry+62,W-92,H-120),body,c["text"],max_size=17,min_size=11,bold=False,max_lines=8,line_gap=7,valign="top")
    _renderer_footer_plain(d,guide,"#6C7275",line="#C9CCCE",bg="#FFFFFF",height=58)
    _renderer_save(img,out_path,guide,started)
