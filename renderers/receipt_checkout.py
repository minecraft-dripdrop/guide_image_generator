# -*- coding: utf-8 -*-
"""Long receipt strategy renderer following the approved receipt sketch."""
from __future__ import annotations

from PIL import ImageDraw
from .shared import SharedRendererTools
from ._media_theme_common import mobile_canvas, rcfg, clean, target_text, target_level_number, special_text, day_metric_text, draw_footer

STYLE_IDS=("receipt_checkout",)


def _tear(draw,y,w,bg):
    step=28
    for x in range(118,w-118,step):
        draw.polygon([(x,y),(x+step//2,y-12),(x+step,y)],fill=bg)


def render(guide,out_path,services):
    tools=SharedRendererTools(services); cfg=rcfg(guide)
    c=tools.colors(guide,{
        "background":"#D8D4CE","paper":"#FFFDF7","ink":"#25221E","muted":"#77716A",
        "rule":"#6D6861","accent":"#B83F34","special":"#F5E1DB","coupon":"#F7E8E3",
        "gift":"#D0AA4C","primary":"#B83F34","dark":"#25221E","light":"#FFFDF7","chip":"#ECE6DE"
    })
    W,H,img=mobile_canvas(services,c["background"]); d=ImageDraw.Draw(img)
    paper=(112,112,W-112,H-70)
    d.rounded_rectangle(paper,radius=9,fill=c["paper"],outline="#B8B0A5",width=2)
    _tear(d,112,W,c["background"])

    # Receipt header exactly as a physical receipt, not a generic title/KPI block.
    services.draw_center(d,(145,140,W-145,188),"GOBLIN MART",c["ink"],max_size=30,min_size=24,bold=True,max_lines=1)
    services.draw_center(d,(145,188,W-145,226),clean(services,guide.get("title"),"七日攻略结算单"),c["ink"],max_size=18,min_size=15,bold=True,max_lines=1)
    services.draw_center(d,(145,226,W-145,258),"STRATEGY RECEIPT",c["muted"],max_size=13,min_size=11,bold=False,max_lines=1)
    d.line((150,274,W-150,274),fill=c["rule"],width=2)
    services.draw_left(d,(155,288,700,318),"DAY / 每日操作名称",c["ink"],max_size=13,min_size=11,bold=True,max_lines=1,valign="center")
    services.draw_center(d,(W-270,288,W-150,318),"目标档位",c["ink"],max_size=13,min_size=11,bold=True,max_lines=1)

    days=list(guide.get("days") or [])[:7]
    top=328; row_h=128; gap=2
    for i,info in enumerate(days):
        y1=top+i*(row_h+gap); y2=y1+row_h
        special=bool(special_text(services,info))
        if special:
            d.rectangle((150,y1,W-150,y2),fill=c["special"])
        stage_names=("开场","推进","资源","调整","推进","收束","终章")
        services.draw_left(d,(158,y1+8,230,y1+38),clean(services,info.get("day"),f"D{i+1}"),c["ink"],max_size=17,min_size=14,bold=True,max_lines=1,valign="center")
        opname=special_text(services,info) or stage_names[min(i,len(stage_names)-1)]
        services.draw_left(d,(238,y1+8,420,y1+38),opname,c["accent"] if special else c["ink"],max_size=14,min_size=11,bold=True,max_lines=1,valign="center")
        services.draw_center(d,(W-250,y1+7,W-165,y1+38),target_level_number(services,info),c["ink"],max_size=17,min_size=14,bold=True,max_lines=1)
        services.draw_left(d,(210,y1+38,W-170,y1+94),clean(services,info.get("action"),"按计划执行"),c["ink"],
                           max_size=int(cfg.get("day_action_font_size",16) or 16),min_size=10,bold=True,max_lines=4,line_gap=2,valign="center")
        metric=day_metric_text(services,info,max_items=4)
        services.draw_left(d,(210,y1+94,W-170,y2-6),metric,c["muted"],max_size=11,min_size=9,bold=False,max_lines=2,line_gap=1,valign="center")
        d.line((150,y2,W-150,y2),fill="#D8D1C8",width=1)

    y=top+len(days)*(row_h+gap)+18
    d.line((150,y,W-150,y),fill=c["ink"],width=2)
    y+=16
    # KPI fields as subtotal-style lines near the bottom, matching the sketch.
    kpis=tools.kpis(guide)[:3]
    for item in kpis:
        services.draw_left(d,(165,y,430,y+32),clean(services,item.get("label"),"KPI"),c["ink"],max_size=13,min_size=11,bold=False,max_lines=1,valign="center")
        services.draw_center(d,(W-310,y,W-165,y+32),clean(services,item.get("value"),"—"),c["ink"],max_size=14,min_size=12,bold=True,max_lines=1)
        y+=42

    # Printed red-note coupon.
    d.rounded_rectangle((160,y+8,W-160,y+88),radius=7,fill=c["coupon"],outline=c["accent"],width=2)
    risks=tools.risk_items(guide)
    rtext=" · ".join(risks) if risks else "D3 / D7 先做重点操作。"
    services.draw_left(d,(185,y+18,W-185,y+78),"REMINDER："+rtext,c["accent"],max_size=13,min_size=10,bold=False,max_lines=2,line_gap=1,valign="center")
    y+=112

    # Free-gift line stays inline, not a large generic reward card.
    services.draw_left(d,(165,y,W-600,y+34),"FREE GIFT / REWARD",c["ink"],max_size=13,min_size=11,bold=True,max_lines=1,valign="center")
    tools.draw_reward_icons(img,d,guide,(430,y-4,W-165,y+72),fg=c["ink"],accent=c["gift"],bg=None,border=None,max_items=4,show_names=False,text_fallback=True)
    y+=92
    d.line((150,y,W-150,y),fill=c["ink"],width=3)
    services.draw_left(d,(165,y+14,470,y+56),"TOTAL / D7",c["ink"],max_size=22,min_size=18,bold=True,max_lines=1,valign="center")
    services.draw_center(d,(W-310,y+14,W-165,y+56),"完成",c["accent"],max_size=22,min_size=18,bold=True,max_lines=1)

    # Barcode region.
    by=min(H-160,y+76)
    x=190
    while x<W-190:
        width=2 if ((x//8)%3) else 5
        d.line((x,by,x,by+58),fill=c["ink"],width=width)
        x+=9

    draw_footer(img,d,guide,services,H-64,64,c["muted"],bg=c["paper"],line=c["rule"])
    tools.save(img,out_path,guide)
