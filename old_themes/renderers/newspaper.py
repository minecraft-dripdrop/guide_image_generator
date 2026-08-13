# -*- coding: utf-8 -*-
"""Renderer module for ``newspaper``."""
import math
import random
import time
from pathlib import Path
from PIL import Image, ImageDraw
from .shared import SharedRendererTools

STYLE_IDS = ("newspaper",)


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
    """报纸版式：黑白印刷、多栏文字流、少量强调色。"""
    started=time.perf_counter()
    c=_renderer_colors(guide,{"background":"#F1EBD9","text":"#171717","primary":"#8A1C1C","dark":"#171717","light":"#EEE5CE","chip":"#C9BEA4","rule":"#2A2A2A"})
    img=Image.new("RGBA",(W,H),c["background"]); d=ImageDraw.Draw(img)
    d.rectangle((40,36,W-40,H-64),fill="#FAF7ED",outline="#292929",width=2)
    d.text((60,60),"MAPLE DAILY",font=get_font(22,True),fill=c["primary"])
    draw_center(d,(60,84,W-60,176),"冒险岛攻略日报",c["text"],max_size=48,min_size=36,bold=True,max_lines=1)
    _renderer_rule(d,(60,184,W-60,184),c["text"],5); _renderer_rule(d,(60,194,W-60,194),c["text"],1)
    d.text((62,206),"攻略 · 活动 · 资源规划",font=get_font(13,False),fill="#555555")
    d.text((W-350,206),_renderer_author(guide),font=get_font(13,False),fill="#555555")
    draw_center(d,(68,246,W-68,360),guide.get("title") or "活动攻略",c["text"],max_size=47,min_size=30,bold=True,max_lines=2,line_gap=2)
    if guide.get("subtitle"):
        draw_center(d,(92,356,W-92,400),guide.get("subtitle"),"#555555",max_size=18,min_size=13,bold=False,max_lines=1,line_gap=0)
    _renderer_rule(d,(60,418,W-60,418),"#777777",1)
    # 导语 + 数据侧栏
    draw_left(d,(62,438,650,586),"本期整理活动资源路线与按日操作顺序。核心原则：按目标档位控制消耗，达到节点后停止，避免提前透支后续资源。",c["text"],max_size=18,min_size=12,bold=False,max_lines=6,line_gap=5,valign="top")
    d.line((676,438,676,590),fill=c["text"],width=1)
    d.text((700,438),"数据一览",font=get_font(18,True),fill=c["primary"])
    _renderer_draw_kpis_with_icons(img,d,guide,(696,472,W-66,586),c["text"],c["primary"],compact=True,vertical=True)
    _renderer_rule(d,(60,608,W-60,608),c["text"],2)
    # 三栏正文
    days=guide.get("days") or []
    cols=3; x0=60; gap=24; cw=(W-120-gap*2)/3; top=636; bottom=1852
    for col in [1,2]:
        x=int(x0+col*cw+(col-0.5)*gap); d.line((x,top,x,bottom),fill="#B7B1A4",width=1)
    # 每栏顺序排 day，使用报纸标题而不是卡片
    col_heights=[top,top,top]
    for i,info in enumerate(days):
        col=i%3; x1=x0+col*(cw+gap); x2=x1+cw; y=col_heights[col]
        d.text((int(x1),int(y)),_renderer_day_title(info),font=get_font(19,True),fill=c["primary"])
        y+=34
        d.line((int(x1),int(y),int(x2),int(y)),fill=c["text"],width=1); y+=12
        action=clean(str(info.get("action") or ""))
        # 估算固定高度，避免复杂流排
        draw_left(d,(x1,y,x2,y+210),action,c["text"],max_size=16,min_size=11,bold=False,max_lines=9,line_gap=4,valign="top")
        y+=214
        if info.get("metric_items"):
            _renderer_draw_metric_icons(img,d,guide,info,(x1,y,x2,y+44),"#666666",c["primary"])
            y+=50
        col_heights[col]=y+28
    # 奖励与风险放底部横栏
    _renderer_rule(d,(60,1870,W-60,1870),c["text"],4)
    d.text((60,1890),"兑换建议",font=get_font(20,True),fill=c["primary"])
    _renderer_draw_reward_icons(img,d,guide,(60,1922,550,2048),c["text"],c["primary"],max_items=5,show_names=True)
    d.line((574,1890,574,2180),fill="#999384",width=1)
    d.text((600,1890),"风险提示",font=get_font(20,True),fill=c["primary"])
    risks=_renderer_risk_items(guide)
    body="\n".join("• "+x for x in risks[:5]) if risks else "• 到达目标档位后停止；按实际资源余量调整。"
    draw_left(d,(600,1924,W-64,2180),body,c["text"],max_size=15,min_size=10,bold=False,max_lines=10,line_gap=6,valign="top")
    _renderer_footer_plain(d,guide,"#555555",line=c["text"],bg="#FAF7ED",height=58)
    _renderer_save(img,out_path,guide,started)
