# -*- coding: utf-8 -*-
"""Album / player strategy renderer preserving the approved big-cover skeleton."""
from __future__ import annotations

from PIL import ImageDraw
from .shared import SharedRendererTools
from ._media_theme_common import mobile_canvas, rcfg, clean, target_text, special_text, day_metric_text, draw_footer

STYLE_IDS=("music_album",)


def render(guide,out_path,services):
    tools=SharedRendererTools(services); cfg=rcfg(guide)
    c=tools.colors(guide,{
        "background":"#15171B","cover":"#B65D50","panel":"#23262B","ink":"#F2F0EB","muted":"#A9ADB3",
        "accent":"#C9A54A","accent2":"#A9574D","line":"#444950","track":"#17191D","special":"#2C2324",
        "risk":"#342829","primary":"#C9A54A","dark":"#15171B","light":"#F2F0EB","chip":"#35383D"
    })
    W,H,img=mobile_canvas(services,c["background"]); d=ImageDraw.Draw(img)

    services.draw_left(d,(38,24,W-38,72),clean(services,guide.get("title"),"活动攻略"),c["ink"],max_size=36,min_size=27,bold=True,max_lines=1,valign="center")
    services.draw_left(d,(38,76,W-38,106),"音乐专辑 / 播放器 · SEVEN TRACKS",c["muted"],max_size=14,min_size=12,bold=False,max_lines=1,valign="center")

    # Big album art: dominant visual, as in the concept sketch.
    cover=(128,124,W-128,626)
    d.rounded_rectangle(cover,radius=20,fill=c["cover"],outline="#383A3E",width=3)
    cx=W//2; cy=372
    d.ellipse((cx-190,cy-190,cx+190,cy+190),fill="#242529",outline="#090A0B",width=5)
    for r in (155,125,95,65):
        d.ellipse((cx-r,cy-r,cx+r,cy+r),outline="#4B4E52",width=2)
    d.ellipse((cx-34,cy-34,cx+34,cy+34),fill=c["accent"])
    services.draw_center(d,(cover[0]+30,cover[3]-72,cover[2]-30,cover[3]-24),"GOBLIN / SEVEN TRACKS",c["ink"],max_size=24,min_size=19,bold=True,max_lines=1)

    # Album caption / edition.
    services.draw_left(d,(70,650,W-70,690),"TRACKLIST",c["ink"],max_size=24,min_size=19,bold=True,max_lines=1,valign="center")
    days=list(guide.get("days") or [])[:7]
    if days:
        services.draw_left(d,(70,692,W-70,722),"Edition · "+target_text(services,days[-1]),c["muted"],max_size=14,min_size=12,bold=False,max_lines=1,valign="center")

    # Tracklist rows use real song-like titles plus the real numbered operations.
    song_names=("开场序曲","前行节拍","资源间奏","中场变奏","再启节拍","收束前夜","最终回响")
    top=750; gap=3; y=top
    for i,info in enumerate(days):
        row_h=118 if i==6 else 88
        y1=y; y2=y1+row_h; y=y2+gap
        special=bool(special_text(services,info)) or i==6
        if special:
            d.rounded_rectangle((54,y1,W-54,y2),radius=9,fill=c["special"])
        services.draw_center(d,(68,y1+8,116,y1+36),f"{i+1:02d}",c["accent"] if special else c["muted"],max_size=14,min_size=12,bold=True,max_lines=1)
        track_title=song_names[min(i,len(song_names)-1)]
        if special_text(services,info):
            track_title=special_text(services,info)+" · "+track_title
        services.draw_left(d,(132,y1+4,W-260,y1+34),track_title,c["ink"],max_size=15,min_size=12,bold=True,max_lines=1,valign="center")
        services.draw_center(d,(W-245,y1+5,W-70,y1+34),clean(services,info.get("day"),f"D{i+1}")+" · "+target_text(services,info),c["muted"],max_size=11,min_size=9,bold=True,max_lines=1)
        services.draw_left(d,(132,y1+34,W-72,y2-22),clean(services,info.get("action"),"按计划执行"),c["ink"],
                           max_size=14 if i==6 else 13,min_size=9,bold=True,max_lines=4 if i==6 else 3,line_gap=1,valign="center")
        metric=day_metric_text(services,info,max_items=3)
        services.draw_left(d,(132,y2-22,W-72,y2-2),metric,c["muted"],max_size=9,min_size=7,bold=False,max_lines=1,valign="center")

    y+=12
    # Player/KPI rail in the approved bottom position.
    d.rounded_rectangle((55,y,W-55,y+104),radius=12,fill=c["panel"],outline=c["line"],width=2)
    kpis=tools.kpis(guide)[:3]
    for i,item in enumerate(kpis):
        x1=80+i*300
        services.draw_left(d,(x1,y+10,x1+210,y+36),clean(services,item.get("label"),"KPI"),c["muted"],max_size=11,min_size=9,bold=False,max_lines=1,valign="center")
        services.draw_left(d,(x1,y+38,x1+210,y+67),clean(services,item.get("value"),"—"),c["ink"],max_size=16,min_size=13,bold=True,max_lines=1,valign="center")
    d.line((88,y+82,W-120,y+82),fill="#5B6067",width=5)
    d.line((88,y+82,W-365,y+82),fill=c["accent"],width=5)
    d.ellipse((W-373,y+74,W-357,y+90),fill=c["ink"])
    y+=120

    d.rounded_rectangle((55,y,W-55,y+78),radius=12,fill=c["risk"],outline=c["accent2"],width=2)
    risks=tools.risk_items(guide)
    rtext=" · ".join(risks) if risks else "D3 / D7 不要跳过重点步骤。"
    services.draw_left(d,(80,y+8,W-78,y+70),"播放提醒："+rtext,c["ink"],max_size=13,min_size=10,bold=False,max_lines=2,line_gap=1,valign="center")
    y+=94
    d.rounded_rectangle((55,y,W-55,y+110),radius=11,fill=c["panel"],outline=c["line"],width=1)
    services.draw_left(d,(80,y+10,W-80,y+38),"BONUS TRACK / REWARD",c["accent"],max_size=16,min_size=13,bold=True,max_lines=1,valign="center")
    tools.draw_reward_icons(img,d,guide,(90,y+40,W-90,y+100),fg=c["ink"],accent=c["accent"],bg=None,border=None,max_items=4,show_names=True,text_fallback=True)

    draw_footer(img,d,guide,services,H-58,58,c["muted"],bg="#101216",line=c["line"])
    tools.save(img,out_path,guide)
