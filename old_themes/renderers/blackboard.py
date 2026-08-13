# -*- coding: utf-8 -*-
"""Renderer module for ``blackboard``."""
import math
import random
import time
from pathlib import Path
from PIL import Image, ImageDraw
from .shared import SharedRendererTools

STYLE_IDS = ("blackboard",)


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
    """黑板战术分析：粉笔标题、流程箭头和战术节点。"""
    started=time.perf_counter()
    c=_renderer_colors(guide,{"background":"#173F36","text":"#F4F1DF","primary":"#F2D36A","dark":"#E8E3D0","light":"#BBD9C2","chip":"#70A58D","chalk":"#F4F1DF","red":"#F09A88"})
    img=Image.new("RGBA",(W,H),c["background"]); d=ImageDraw.Draw(img)
    rng=random.Random("chalk:"+str(guide.get("sheet")))
    # 粉笔灰噪点
    for _ in range(1900):
        x=rng.randrange(W); y=rng.randrange(H); v=rng.randrange(55,95)
        d.point((x,y),fill=(255,255,255,v))
    d.rectangle((34,34,W-34,H-66),outline="#C79C54",width=8)
    draw_center(d,(70,70,W-70,172),guide.get("title") or "活动攻略",c.get("chalk","#F4F1DF"),max_size=46,min_size=30,bold=True,max_lines=2,line_gap=2)
    d.line((120,188,W-120,188),fill=c["primary"],width=4)
    d.text((80,216),"作战资源",font=get_font(20,True),fill=c["primary"])
    _renderer_draw_kpis_with_icons(img,d,guide,(80,252,W-80,360),c["text"],c["primary"],fill=None,border=None,compact=True)
    d.text((80,390),"兑换目标：",font=get_font(18,True),fill=c["primary"])
    _renderer_draw_reward_icons(img,d,guide,(208,374,W-84,462),c["text"],c["primary"],max_items=6,show_names=True)
    # 战术流程：左右交替节点 + 箭头
    days=guide.get("days") or []
    top=488; bottom=1810; row_h=(bottom-top)/max(1,len(days)); center_x=W//2
    for i,info in enumerate(days):
        y=top+i*row_h
        left=(i%2==0)
        x1=88 if left else 584; x2=496 if left else 992
        # 节点直角边框，略带双线模拟粉笔
        d.rectangle((x1,int(y),x2,int(y+row_h-26)),outline=c["text"],width=3)
        d.rectangle((x1+5,int(y+5),x2-5,int(y+row_h-31)),outline="#8AB9A5",width=1)
        draw_left(d,(x1+14,y+8,x2-12,y+42),_renderer_day_title(info),c["primary"],max_size=18,min_size=12,bold=True,max_lines=1,line_gap=0,valign="center")
        draw_left(d,(x1+14,y+48,x2-14,y+row_h-60),info.get("action") or "",c["text"],max_size=15,min_size=10,bold=False,max_lines=5,line_gap=3,valign="top")
        if info.get("metric_items"):
            _renderer_draw_metric_icons(img,d,guide,info,(x1+14,y+row_h-60,x2-14,y+row_h-30),c.get("light","#BBD9C2"),c["primary"])
        # 中轴箭头
        cy=int(y+(row_h-26)/2); ax1=x2+8 if left else x1-8; ax2=center_x
        d.line((ax1,cy,ax2,cy),fill=c["primary"],width=3)
        if left: d.polygon([(center_x,cy),(center_x-14,cy-8),(center_x-14,cy+8)],fill=c["primary"])
        else: d.polygon([(center_x,cy),(center_x+14,cy-8),(center_x+14,cy+8)],fill=c["primary"])
        if i<len(days)-1:
            ny=int(y+row_h-13); d.line((center_x,cy,center_x,ny),fill=c["primary"],width=3)
            d.polygon([(center_x,ny),(center_x-8,ny-14),(center_x+8,ny-14)],fill=c["primary"])
    risks=_renderer_risk_items(guide)
    ry=1840
    d.text((90,ry),"⚠ 风险区",font=get_font(22,True),fill=c.get("red","#F09A88"))
    body="\n".join("× "+x for x in risks[:4]) if risks else "× 到档后继续消耗\n× 为随机奖励过度追高"
    draw_left(d,(100,ry+46,W-100,H-120),body,c.get("red","#F09A88"),max_size=18,min_size=11,bold=True,max_lines=8,line_gap=8,valign="top")
    _renderer_footer_plain(d,guide,c["text"],line="#C79C54",bg=c["background"],height=60)
    _renderer_save(img,out_path,guide,started)
