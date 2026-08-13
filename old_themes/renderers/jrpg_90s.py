# -*- coding: utf-8 -*-
"""Renderer module for ``jrpg_90s``."""
import math
import random
import time
from pathlib import Path
from PIL import Image, ImageDraw
from .shared import SharedRendererTools

STYLE_IDS = ("jrpg_90s",)


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
    """90 年代日系 RPG 攻略本：粗线、状态栏、星号与硬边窗口。"""
    started=time.perf_counter()
    c=_renderer_colors(guide,{"background":"#D9C79B","text":"#1D1B16","primary":"#2D5E9E","dark":"#172F52","light":"#EADFB9","chip":"#B69A5F","panel":"#F3E8C8","accent":"#A52A2A"})
    img=Image.new("RGBA",(W,H),c["background"]); d=ImageDraw.Draw(img)
    # 像旧攻略本的双线页边
    d.rectangle((34,34,W-34,H-68),fill=c.get("panel","#F3E8C8"),outline="#1D1B16",width=4)
    d.rectangle((44,44,W-44,H-78),outline="#6A5A3B",width=1)
    d.rectangle((60,58,W-60,132),fill=c["dark"])
    d.text((82,76),"RPG MASTER GUIDE",font=get_font(24,True),fill="#FFFFFF")
    d.text((W-278,82),"DATA FILE No.07",font=get_font(15,True),fill="#F3D26A")
    draw_left(d,(64,148,W-64,264),guide.get("title") or "活动攻略",c["text"],max_size=48,min_size=30,bold=True,max_lines=2,line_gap=2,valign="center")
    d.rectangle((64,282,W-64,420),fill="#20242A",outline="#111111",width=4)
    d.text((82,296),"■ DATA",font=get_font(19,True),fill="#F3D26A")
    _renderer_draw_kpis_with_icons(img,d,guide,(82,326,W-82,406),"#FFFFFF","#A7D1FF",compact=True,pixel=True)
    d.text((70,448),"★ REWARD",font=get_font(19,True),fill=c.get("accent","#A52A2A"))
    _renderer_draw_reward_icons(img,d,guide,(70,470,W-70,566),c["text"],c.get("accent","#A52A2A"),max_items=6,show_names=True)
    days=guide.get("days") or []
    top=590; bottom=1848; rows=math.ceil(len(days)/2); gapx=18; gapy=14; cw=(W-140-gapx)/2; rh=(bottom-top-gapy*max(0,rows-1))/max(1,rows)
    for i,info in enumerate(days):
        r=i//2; col=i%2; x1=70+col*(cw+gapx); y1=top+r*(rh+gapy); x2=x1+cw; y2=y1+rh
        d.rectangle((int(x1),int(y1),int(x2),int(y2)),fill="#F8EFD3",outline="#1D1B16",width=3)
        d.rectangle((int(x1+5),int(y1+5),int(x2-5),int(y1+48)),fill=c["primary"],outline="#1D1B16",width=1)
        title=("▶ "+_renderer_day_title(info))
        draw_left(d,(x1+16,y1+7,x2-10,y1+46),title,"#FFFFFF",max_size=18,min_size=12,bold=True,max_lines=1,line_gap=0,valign="center")
        draw_left(d,(x1+16,y1+62,x2-16,y2-54),info.get("action") or "",c["text"],max_size=18,min_size=11,bold=False,max_lines=6,line_gap=4,valign="top")
        if info.get("metric_items"):
            _renderer_draw_metric_icons(img,d,guide,info,(x1+12,y2-46,x2-12,y2-10),c["dark"],c["primary"],bg="#D8C99E",border="#7A6841")
    risks=_renderer_risk_items(guide)
    ry=1880
    d.rectangle((70,ry,W-70,H-110),fill="#FFF3C8",outline=c.get("accent","#A52A2A"),width=4)
    d.text((88,ry+18),"▶ POINT!",font=get_font(21,True),fill=c.get("accent","#A52A2A"))
    body="\n".join("★ "+x for x in risks[:4]) if risks else "★ 到档即停，剩余资源进入下一阶段。"
    draw_left(d,(92,ry+62,W-92,H-126),body,c["text"],max_size=18,min_size=11,bold=False,max_lines=8,line_gap=6,valign="top")
    _renderer_footer_plain(d,guide,c["text"],line="#6A5A3B",bg=c.get("panel","#F3E8C8"),height=62)
    _renderer_save(img,out_path,guide,started)
