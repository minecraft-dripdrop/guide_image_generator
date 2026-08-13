# -*- coding: utf-8 -*-
"""Renderer module for ``pixel_menu``."""
import math
import random
import time
from pathlib import Path
from PIL import Image, ImageDraw
from .shared import SharedRendererTools

STYLE_IDS = ("pixel_menu",)


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
    """复古像素游戏菜单：深色窗口、像素硬边、选择光标与状态栏。"""
    started=time.perf_counter()
    c=_renderer_colors(guide,{"background":"#11172B","text":"#F5F2DD","primary":"#55D9E6","dark":"#27345C","light":"#B6F4F7","chip":"#53669C","window":"#17213F","border":"#E7E4D0","gold":"#F2D56B"})
    img=Image.new("RGBA",(W,H),c["background"]); d=ImageDraw.Draw(img)
    def pxwin(box, fill=None, accent=None, w=6):
        x1,y1,x2,y2=map(int,box); fill=fill or c.get("window","#17213F"); accent=accent or c.get("border","#E7E4D0")
        d.rectangle((x1,y1,x2,y2),fill=fill)
        d.rectangle((x1,y1,x2,y2),outline=accent,width=w)
        d.rectangle((x1+w+4,y1+w+4,x2-w-4,y2-w-4),outline=c.get("chip","#53669C"),width=2)
        # 四角像素缺口
        s=w+6
        for bx,by in [(x1,y1),(x2-s,y1),(x1,y2-s),(x2-s,y2-s)]: d.rectangle((bx,by,bx+s,by+s),fill=c["background"])
    pxwin((44,42,W-44,236),w=7)
    d.text((74,68),"GOBLIN / STRATEGY",font=get_font(18,True),fill=c.get("gold","#F2D56B"))
    draw_left(d,(74,102,W-76,186),guide.get("title") or "活动攻略",c["text"],max_size=38,min_size=24,bold=True,max_lines=2,line_gap=2,valign="center")
    d.text((74,196),"> PRESS START TO FOLLOW PLAN",font=get_font(13,True),fill=c["primary"])
    # STATUS window
    pxwin((44,260,W-44,426),w=6)
    d.text((72,282),"STATUS",font=get_font(18,True),fill=c["primary"])
    _renderer_draw_kpis_with_icons(img,d,guide,(72,320,W-72,402),c["text"],"#9DA9D0",compact=True,pixel=True)
    # ITEM window
    pxwin((44,448,W-44,586),w=6)
    d.text((72,486),"ITEM GET",font=get_font(16,True),fill=c.get("gold","#F2D56B"))
    _renderer_draw_reward_icons(img,d,guide,(176,466,W-70,574),c["text"],c.get("gold","#F2D56B"),max_items=6,show_names=True,pixel=True)
    # 主菜单 + 右侧详情，真正像 RPG 菜单而不是卡片网格
    menu_x1,menu_x2=44,342; detail_x1,detail_x2=362,W-44; top=610; bottom=1870
    pxwin((menu_x1,top,menu_x2,bottom),w=6); pxwin((detail_x1,top,detail_x2,bottom),w=6)
    d.text((72,636),"PLAN",font=get_font(18,True),fill=c["primary"])
    days=guide.get("days") or []
    item_h=min(130,(bottom-top-90)/max(1,len(days)))
    yy=684
    for i,info in enumerate(days):
        active=(i==0)
        if active: d.rectangle((64,int(yy-4),322,int(yy+item_h-10)),fill="#243A64")
        cursor="▶" if active else "  "
        d.text((72,int(yy+8)),cursor+clean(str(info.get("day") or f"DAY {i+1}")),font=get_font(17,True),fill=(c.get("gold","#F2D56B") if active else c["text"]))
        target=clean(str(info.get("target") or ""))
        if target: d.text((104,int(yy+42)),"TARGET "+target,font=get_font(11,True),fill="#9DA9D0")
        yy+=item_h
    d.text((392,636),"COMMAND",font=get_font(18,True),fill=c["primary"])
    yy=684
    detail_h=(bottom-yy-18)/max(1,len(days))
    for i,info in enumerate(days):
        y1=yy+i*detail_h; y2=y1+detail_h-6
        d.text((394,int(y1+2)),f"{i+1:02d}",font=get_font(13,True),fill=c.get("gold","#F2D56B"))
        draw_left(d,(438,y1,detail_x2-20,y1+32),_renderer_day_title(info),c["text"],max_size=15,min_size=10,bold=True,max_lines=1,line_gap=0,valign="center")
        draw_left(d,(438,y1+34,detail_x2-20,y2-28),info.get("action") or "",c["text"],max_size=13,min_size=9,bold=False,max_lines=4,line_gap=2,valign="top")
        if info.get("metric_items"): _renderer_draw_metric_icons(img,d,guide,info,(438,y2-28,detail_x2-20,y2),"#9DA9D0",c["primary"],pixel=True)
        if i<len(days)-1: d.line((392,int(y2+3),detail_x2-18,int(y2+3)),fill="#53669C",width=1)
    risks=_renderer_risk_items(guide)
    pxwin((44,1894,W-44,H-104),w=6)
    d.text((72,1918),"WARNING",font=get_font(18,True),fill="#FF8F82")
    body="  ".join("! "+x for x in risks[:4]) if risks else "! STOP WHEN TARGET RANK IS REACHED"
    draw_left(d,(72,1956,W-72,H-126),body,c["text"],max_size=14,min_size=9,bold=False,max_lines=6,line_gap=5,valign="top")
    _renderer_footer_plain(d,guide,"#9DA9D0",line=c.get("chip","#53669C"),bg=c["background"],height=62)
    _renderer_save(img,out_path,guide,started)
