# -*- coding: utf-8 -*-
"""Television-news special renderer based on the approved vertical concept."""
from __future__ import annotations

from PIL import ImageDraw
from .shared import SharedRendererTools
from ._media_theme_common import mobile_canvas, rcfg, clean, target_text, special_text, day_metric_text, draw_footer

STYLE_IDS=("tv_news",)


def _person(draw,cx,cy,scale,skin,body,outline):
    r=int(38*scale)
    draw.ellipse((cx-r,cy-r,cx+r,cy+r),fill=skin,outline=outline,width=max(2,int(3*scale)))
    bw=int(62*scale); bh=int(115*scale)
    draw.rounded_rectangle((cx-bw,cy+r-3,cx+bw,cy+r+bh),radius=int(22*scale),fill=body,outline=outline,width=max(2,int(3*scale)))


def render(guide,out_path,services):
    tools=SharedRendererTools(services); cfg=rcfg(guide)
    c=tools.colors(guide,{
        "background":"#101823","navy":"#1B3148","screen":"#314A63","screen2":"#21364B",
        "red":"#E12632","white":"#F5F7FA","muted":"#B2BDC7","ink":"#172533",
        "light_panel":"#F2F5F8","line":"#91A3B4","ticker":"#F5F7F9",
        "primary":"#E12632","dark":"#172533","light":"#FFFFFF","chip":"#DDE7EE"
    })
    W,H,img=mobile_canvas(services,c["background"]); d=ImageDraw.Draw(img)

    # Top news brand / live indicators.
    services.draw_left(d,(38,22,W-38,70),clean(services,guide.get("title"),"活动攻略"),c["white"],
                       max_size=36,min_size=27,bold=True,max_lines=1,valign="center")
    services.draw_left(d,(38,74,W-38,104),"电视新闻特别节目 · 竖屏直播",c["muted"],
                       max_size=14,min_size=12,bold=False,max_lines=1,valign="center")
    d.rounded_rectangle((42,118,210,182),radius=9,fill=c["red"])
    services.draw_center(d,(42,118,210,182),"NEWS 7",c["white"],max_size=23,min_size=18,bold=True,max_lines=1)
    d.rounded_rectangle((W-182,118,W-42,182),radius=9,fill=c["navy"],outline=c["line"],width=2)
    services.draw_center(d,(W-182,118,W-42,182),"LIVE", "#FF5A63",max_size=22,min_size=18,bold=True,max_lines=1)

    # Main broadcast frame: dominant visual in the approved sketch.
    vx1,vy1,vx2,vy2=42,220,W-42,650
    d.rectangle((vx1,vy1,vx2,vy2),fill=c["screen"],outline=c["line"],width=3)
    _person(d,330,398,1.7,"#F0CFAD","#C48A5F",c["white"])
    # remote live inset
    ix1,iy1,ix2,iy2=W-370,265,W-84,493
    d.rectangle((ix1,iy1,ix2,iy2),fill=c["screen2"],outline="#B9C7D4",width=2)
    _person(d,(ix1+ix2)//2,iy1+90,.75,"#F0CFAD","#86ABC7",c["white"])
    services.draw_center(d,(ix1+10,iy2-52,ix2-10,iy2-14),"现场连线",c["white"],max_size=13,min_size=11,bold=False,max_lines=1)
    # guide-title lower third inside video
    d.rectangle((vx1,vy2-74,vx2,vy2),fill="#193149")
    services.draw_left(d,(vx1+20,vy2-65,vx2-20,vy2-12),clean(services,guide.get("subtitle"),"七日攻略特别报道"),c["white"],
                       max_size=17,min_size=13,bold=True,max_lines=2,line_gap=2,valign="center")

    # Breaking block is a separate large band, not a generic D7 card.
    days=list(guide.get("days") or [])[:7]
    d7=days[6] if len(days)>=7 else {}
    d.rectangle((42,676,W-42,824),fill=c["red"])
    services.draw_left(d,(66,694,W-66,742),"BREAKING NEWS",c["white"],max_size=28,min_size=22,bold=True,max_lines=1,valign="center")
    breaking=(clean(services,d7.get("day"),"D7")+" · "+clean(services,d7.get("action"),"最终资源收束")) if d7 else "D7 · 最终资源收束"
    services.draw_left(d,(66,748,W-66,810),breaking,c["white"],max_size=18,min_size=13,bold=True,max_lines=2,line_gap=2,valign="center")

    # Rundown: editorial summary word first, then the real numbered operations.
    services.draw_left(d,(52,842,W-52,880),"今日节目单 / RUN DOWN",c["white"],max_size=21,min_size=17,bold=True,max_lines=1,valign="center")
    stage_names=("开场","推进","资源","调整","推进","收束","终章")
    top=886; gap=4
    y=top
    for i,info in enumerate(days):
        row_h=104 if i==6 else 66
        y1=y; y2=y1+row_h; y=y2+gap
        special=bool(special_text(services,info)) or i==6
        slug=c["red"] if special else c["navy"]
        d.rectangle((55,y1,137,y2),fill=slug)
        services.draw_center(d,(55,y1,137,y2),clean(services,info.get("day"),f"D{i+1}"),c["white"],max_size=16,min_size=13,bold=True,max_lines=1)
        summary=special_text(services,info) or stage_names[min(i,len(stage_names)-1)]
        services.draw_center(d,(150,y1+5,256,y2-5),summary,c["red"] if special else "#D9E5EF",
                             max_size=15,min_size=11,bold=True,max_lines=2,line_gap=1)
        services.draw_left(d,(274,y1+4,W-190,y2-21),clean(services,info.get("action"),"按计划执行"),c["white"],
                           max_size=14 if i==6 else 13,min_size=10,bold=True,max_lines=4 if i==6 else 3,line_gap=1,valign="center")
        services.draw_center(d,(W-175,y1+7,W-58,y1+33),target_text(services,info),"#FFD5D8" if special else c["muted"],
                             max_size=12,min_size=10,bold=True,max_lines=1)
        metric=day_metric_text(services,info,max_items=3)
        services.draw_left(d,(274,y2-22,W-58,y2-2),metric,c["muted"],max_size=9,min_size=7,bold=False,max_lines=1,valign="center")

    # Bottom broadcast data rail (KPI), reward flash and ticker reminder.
    y+=6
    d.rectangle((42,y,W-42,y+92),fill=c["ticker"])
    d.rectangle((42,y,230,y+92),fill=c["navy"])
    services.draw_center(d,(50,y+8,222,y+84),"攻略速报",c["white"],max_size=19,min_size=16,bold=True,max_lines=1)
    kpis=tools.kpis(guide)[:3]
    if kpis:
        cw=(W-42-230-24)//len(kpis)
        for i,item in enumerate(kpis):
            x1=250+i*cw; x2=250+(i+1)*cw-8
            services.draw_left(d,(x1,y+10,x2,y+35),clean(services,item.get("label"),"KPI"),c["muted"],max_size=11,min_size=9,bold=False,max_lines=1,valign="center")
            services.draw_left(d,(x1,y+37,x2,y+82),clean(services,item.get("value"),"—"),c["ink"],max_size=20,min_size=15,bold=True,max_lines=1,valign="center")
    y+=108
    d.rounded_rectangle((42,y,W-42,y+164),radius=14,fill=c["light_panel"],outline=c["line"],width=2)
    services.draw_left(d,(62,y+10,W-62,y+42),"战利品快讯 / REWARD",c["red"],max_size=18,min_size=15,bold=True,max_lines=1,valign="center")
    tools.draw_reward_icons(img,d,guide,(70,y+48,W-70,y+154),fg=c["ink"],accent=c["red"],bg=None,border=None,max_items=4,show_names=True,text_fallback=True)
    y+=180
    d.rectangle((42,y,W-42,y+70),fill=c["red"])
    risks=tools.risk_items(guide)
    rtext=" · ".join(risks) if risks else "按每日操作执行，重点关注 D3 / D7。"
    services.draw_left(d,(60,y+8,W-60,y+62),"NEWS ALERT："+rtext,c["white"],max_size=14,min_size=11,bold=True,max_lines=2,line_gap=1,valign="center")

    draw_footer(img,d,guide,services,H-62,62,c["white"],bg=c["navy"],line=c["red"])
    tools.save(img,out_path,guide)
