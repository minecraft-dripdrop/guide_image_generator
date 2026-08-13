# -*- coding: utf-8 -*-
"""Renderer module for ``xp_forum``."""
import hashlib
import random
import re
import time
from datetime import datetime, timedelta
from pathlib import Path
from PIL import Image, ImageDraw
from .shared import SharedRendererTools

STYLE_IDS = ("xp_forum",)


def _clean_text(clean, value, default=""):
    text = clean(str(value or ""))
    return text or default


def _merge_xp_forum_cfg(guide, clean):
    cfg = guide.get("cfg") or {}
    theme_cfg = guide.get("theme_config") or {}
    renderer_cfg = theme_cfg.get("renderer") if isinstance(theme_cfg.get("renderer"), dict) else {}
    xp_cfg = {}
    if isinstance(renderer_cfg, dict):
        xp_cfg.update(renderer_cfg)
    if isinstance(cfg.get("xp_forum"), dict):
        xp_cfg.update(cfg.get("xp_forum"))

    author_cfg = cfg.get("author") if isinstance(cfg.get("author"), dict) else {}
    author_name = _clean_text(clean, xp_cfg.get("author_name") or xp_cfg.get("poster_name") or author_cfg.get("text"), "球球别打我")
    author_title = _clean_text(clean, xp_cfg.get("author_title") or xp_cfg.get("poster_title"), "Lv.70 攻略组")
    author_badge = _clean_text(clean, xp_cfg.get("author_badge"), "主题作者 · 精华★★★")
    reply_badge = _clean_text(clean, xp_cfg.get("reply_badge"), "楼主更新")
    avatar_raw = xp_cfg.get("avatar") or author_cfg.get("qq_avatar") or author_cfg.get("avatar") or author_cfg.get("icon")
    reply_users = xp_cfg.get("reply_users") if isinstance(xp_cfg.get("reply_users"), list) else []
    date_prefix = _clean_text(clean, xp_cfg.get("date_prefix"), "2005-08")

    top_post_time = _clean_text(clean, xp_cfg.get("top_post_time"), "2005-08-21 13:29")
    reward_post_time = _clean_text(clean, xp_cfg.get("reward_post_time"), "2005-08-21 13:35")
    tip_post_time = _clean_text(clean, xp_cfg.get("tip_post_time"), "2005-08-29 14:08")
    day_post_times = xp_cfg.get("day_post_times") if isinstance(xp_cfg.get("day_post_times"), list) else []

    return {
        "forum_name": _clean_text(clean, xp_cfg.get("forum_name"), "冒险者日记论坛"),
        "forum_section": _clean_text(clean, xp_cfg.get("forum_section"), "攻略交流区"),
        "forum_breadcrumb": _clean_text(clean, xp_cfg.get("forum_breadcrumb"), "首页  >  活动攻略  >  精华主题"),
        "toolbar_text": _clean_text(clean, xp_cfg.get("toolbar_text"), "主题列表 | 搜索 | 精华区 | 我的收藏"),
        "floor_toolbar_text": _clean_text(clean, xp_cfg.get("floor_toolbar_text"), "引用 | 回复 | 评分 | 只看该作者"),
        "author_name": author_name,
        "author_title": author_title,
        "author_badge": author_badge,
        "reply_badge": reply_badge,
        "avatar_raw": avatar_raw,
        "default_reply_avatar": xp_cfg.get("default_reply_avatar"),
        "reply_users": reply_users,
        "reward_floor_title": _clean_text(clean, xp_cfg.get("reward_floor_title"), "可兑换奖励"),
        "tip_floor_title": _clean_text(clean, xp_cfg.get("tip_floor_title"), "注意事项"),
        "show_window_controls": bool(xp_cfg.get("show_window_controls", True)),
        "show_post_tools": bool(xp_cfg.get("show_post_tools", True)),
        "show_floor_tools": bool(xp_cfg.get("show_floor_tools", False)),
        "top_post_time": top_post_time,
        "reward_post_time": reward_post_time,
        "tip_post_time": tip_post_time,
        "day_post_times": day_post_times,
        "date_prefix": date_prefix,
        "day_random_time_start": _clean_text(clean, xp_cfg.get("day_random_time_start"), "09:00"),
        "day_random_time_end": _clean_text(clean, xp_cfg.get("day_random_time_end"), "22:30"),
        "day_time_random_seed": _clean_text(clean, xp_cfg.get("day_time_random_seed"), "default"),
        "target_label_cn": _clean_text(clean, xp_cfg.get("target_label_cn"), "目标"),
        "day_action_font_size": max(16, int(xp_cfg.get("day_action_font_size", 22) or 22)),
        "day_action_min_font_size": max(15, int(xp_cfg.get("day_action_min_font_size", 16) or 16)),
        "day_action_max_lines": max(2, int(xp_cfg.get("day_action_max_lines", 8) or 8)),
        "day_action_line_gap": max(0, int(xp_cfg.get("day_action_line_gap", 5) or 5)),
        "risk_tip_font_size": max(15, int(xp_cfg.get("risk_tip_font_size", 19) or 19)),
        "risk_tip_min_font_size": max(14, int(xp_cfg.get("risk_tip_min_font_size", 15) or 15)),
        "risk_tip_line_gap": max(0, int(xp_cfg.get("risk_tip_line_gap", 5) or 5)),
        "user_panel_width": max(180, min(210, int(xp_cfg.get("user_panel_width", 194) or 194))),
        "post_column_gap": max(14, min(24, int(xp_cfg.get("post_column_gap", 18) or 18))),
    }


def _day_title_cn(info, xp_cfg, clean):
    """XP 论坛标题只保留中文目标，不显示 TARGET / TIER 英文。"""
    day = _clean_text(clean, info.get("day"), "DAY")
    target = _clean_text(clean, info.get("target"), "")
    if not target:
        return day
    cn = _clean_text(clean, xp_cfg.get("target_label_cn"), "目标")
    label = (cn + " " + target).strip() if cn else target
    return day + "｜" + label


def _resolve_floor_user(index, xp_cfg, clean):
    users = xp_cfg.get("reply_users") or []
    if index < len(users) and isinstance(users[index], dict):
        item = users[index]
        return {
            "name": _clean_text(clean, item.get("name"), xp_cfg["author_name"]),
            "title": _clean_text(clean, item.get("title"), xp_cfg["author_title"]),
            "badge": _clean_text(clean, item.get("badge"), xp_cfg["reply_badge"]),
            "avatar": item.get("avatar") or xp_cfg.get("default_reply_avatar"),
        }
    return {
        "name": xp_cfg["author_name"],
        "title": xp_cfg["author_title"],
        "badge": xp_cfg["reply_badge"],
        "avatar": xp_cfg.get("default_reply_avatar"),
    }


def _parse_dt(text):
    try:
        return datetime.strptime(str(text).strip(), "%Y-%m-%d %H:%M")
    except Exception:
        return None


def _parse_hm(text, default_h=9, default_m=0):
    try:
        s = str(text).strip()
        h, m = s.split(":", 1)
        h = max(0, min(23, int(h)))
        m = max(0, min(59, int(m)))
        return h, m
    except Exception:
        return default_h, default_m


def _build_default_day_times(day_count, xp_cfg, guide):
    if day_count <= 0:
        return []
    top_dt = _parse_dt(xp_cfg.get("top_post_time"))
    tip_dt = _parse_dt(xp_cfg.get("tip_post_time"))
    if not top_dt or not tip_dt or tip_dt <= top_dt:
        # fallback old behavior
        return [f"{xp_cfg.get('date_prefix', '2005-08')}-{min(28,22+i):02d} 13:{29+i:02d}" for i in range(day_count)]

    date_pool = []
    cur = (top_dt + timedelta(days=1)).date()
    end_date = (tip_dt - timedelta(days=1)).date()
    while cur <= end_date:
        date_pool.append(cur)
        cur += timedelta(days=1)

    if not date_pool:
        date_pool = [(top_dt + timedelta(days=i+1)).date() for i in range(day_count)]
    if len(date_pool) >= day_count:
        dates = date_pool[:day_count]
    else:
        dates = []
        span_days = max(1, (tip_dt.date() - top_dt.date()).days - 1)
        for i in range(day_count):
            offset = max(1, min(span_days, int(round((i + 1) * span_days / (day_count + 1)))))
            dates.append((top_dt + timedelta(days=offset)).date())

    sh, sm = _parse_hm(xp_cfg.get("day_random_time_start"), 9, 0)
    eh, em = _parse_hm(xp_cfg.get("day_random_time_end"), 22, 30)
    start_minutes = sh * 60 + sm
    end_minutes = max(start_minutes, eh * 60 + em)
    seed_src = f"{guide.get('title','')}|{xp_cfg.get('top_post_time')}|{xp_cfg.get('tip_post_time')}|{xp_cfg.get('day_time_random_seed','default')}"
    rng = random.Random(int(hashlib.md5(seed_src.encode('utf-8')).hexdigest()[:8], 16))
    out = []
    for d in dates:
        mins = rng.randint(start_minutes, end_minutes)
        hh = mins // 60
        mm = mins % 60
        out.append(f"{d.strftime('%Y-%m-%d')} {hh:02d}:{mm:02d}")
    return out


def _pseudo_uid(name):
    base = int(hashlib.md5(str(name).encode("utf-8")).hexdigest()[:6], 16)
    return 100000 + (base % 899999)


def _user_meta_lines(name, title, badge):
    uid = _pseudo_uid(name)
    posts = 20 + (uid % 780)
    rank = (uid % 9) + 1
    return [
        title,
        badge,
        f"UID:{uid}",
        f"帖子:{posts}  等级:{rank}",
    ]


def _draw_square_avatar(base, box, avatar_path, fallback_text, services, ring="#6C89B3", fill="#D8E6F8", outline_width=2):
    x1, y1, x2, y2 = map(int, box)
    size = max(24, min(x2 - x1, y2 - y1))
    cx = x1 + ((x2 - x1) - size) // 2
    cy = y1 + ((y2 - y1) - size) // 2
    layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    d.rectangle((0, 0, size - 1, size - 1), fill="#FFFFFF", outline=ring, width=max(1, int(outline_width)))
    inset = 3
    inner = size - inset * 2
    pasted = False
    try:
        if avatar_path and Path(avatar_path).exists():
            avatar = Image.open(avatar_path).convert("RGBA")
            side = min(avatar.width, avatar.height)
            left = (avatar.width - side) // 2
            top = (avatar.height - side) // 2
            avatar = avatar.crop((left, top, left + side, top + side)).resize((inner, inner), Image.LANCZOS)
            layer.alpha_composite(avatar, (inset, inset))
            pasted = True
    except Exception:
        pasted = False
    if not pasted:
        d.rectangle((inset, inset, inset + inner - 1, inset + inner - 1), fill=fill)
        services.draw_center(d, (inset, inset, inset + inner, inset + inner), fallback_text[:2], ring, max_size=max(12, int(size * 0.34)), min_size=10, bold=True, max_lines=1)
    base.alpha_composite(layer, (cx, cy))


def _draw_user_panel(base, draw, box, *, name, title, badge, avatar_path, floor_text, services, colors, xp_cfg):
    x1, y1, x2, y2 = map(int, box)
    draw.rectangle((x1, y1, x2, y2), fill=colors.get("side", "#EDF3FA"), outline=colors.get("post_outline", "#9FB4CF"), width=1)
    services.draw_center(draw, (x1 + 8, y1 + 8, x2 - 8, y1 + 32), floor_text, colors.get("link", "#174EA6"), max_size=16, min_size=12, bold=True, max_lines=1)

    # 宽版左右资料结构：头像 + 文字作为一个整体在左侧方框内居中。
    # V35.32 把头像放大到与右侧整组文字接近同高，避免头像显得过小。
    panel_w = max(1, x2 - x1)
    try:
        avatar_size = max(52, int(xp_cfg.get("user_avatar_size", 74) or 74))
    except Exception:
        avatar_size = 74
    try:
        gap = max(5, int(xp_cfg.get("user_avatar_text_gap", 8) or 8))
    except Exception:
        gap = 8
    try:
        side_pad = max(7, int(xp_cfg.get("user_panel_inner_pad", 10) or 10))
    except Exception:
        side_pad = 10
    try:
        line_h = max(12, int(xp_cfg.get("user_meta_line_height", 14) or 14))
    except Exception:
        line_h = 14
    name_h = max(17, int(xp_cfg.get("user_name_line_height", 18) or 18))
    max_avatar = max(52, panel_w - side_pad * 2 - gap - 78)
    avatar_size = min(avatar_size, max_avatar)
    text_w = max(78, panel_w - side_pad * 2 - avatar_size - gap)
    group_w = avatar_size + gap + text_w
    group_x = x1 + max(side_pad, (panel_w - group_w) // 2)

    meta_lines = _user_meta_lines(name, title, badge)
    text_h = name_h + len(meta_lines) * line_h
    group_h = max(avatar_size, text_h)

    has_status = (y2 - y1) >= 150
    content_top = y1 + 38
    content_bottom = (y2 - 31) if has_status else (y2 - 8)
    available_h = max(group_h, content_bottom - content_top)
    group_y = content_top + max(0, (available_h - group_h) // 2)

    avatar_y = group_y + max(0, (group_h - avatar_size) // 2)
    avatar_box = (group_x, avatar_y, group_x + avatar_size, avatar_y + avatar_size)
    _draw_square_avatar(base, avatar_box, avatar_path, name[:1] if name else "Q", services,
                        ring=colors.get("avatar_ring", colors.get("dark", "#6C89B3")),
                        fill=colors.get("avatar_fill", colors.get("light", "#D8E6F8")),
                        outline_width=colors.get("avatar_outline_width", 2))

    tx1 = group_x + avatar_size + gap
    tx2 = tx1 + text_w
    services.draw_left(draw, (tx1, group_y, tx2, group_y + name_h), name,
                       colors.get("link", "#174EA6"), max_size=13, min_size=10,
                       bold=True, max_lines=1, line_gap=0, valign="center")

    for idx, line in enumerate(meta_lines):
        ly1 = group_y + name_h + idx * line_h
        ly2 = ly1 + line_h
        services.draw_left(draw, (tx1, ly1, tx2, ly2), line,
                           colors.get("dark" if idx >= 2 else "text", "#173C78"),
                           max_size=(10 if idx < 2 else 9), min_size=8, bold=False,
                           max_lines=1, line_gap=0, valign="center")

    if has_status:
        draw.line((x1 + 10, y2 - 26, x2 - 10, y2 - 26), fill=colors.get("chip", "#B9CDE8"), width=1)
        services.draw_left(draw, (x1 + 10, y2 - 24, x2 - 10, y2 - 8), "在线状态：离线",
                           colors.get("dark", "#173C78"), max_size=9, min_size=8,
                           bold=False, max_lines=1, line_gap=0, valign="center")


def _draw_window_controls(draw, box, colors):
    x1, y1, x2, y2 = map(int, box)
    btn_w, btn_h, gap = 22, 18, 3
    total_w = btn_w * 3 + gap * 2
    sx = x2 - total_w - 8
    sy = y1 + 7
    draw.rectangle((sx, sy, sx + btn_w, sy + btn_h), fill=colors.get("control_bg", "#EAF3FF"), outline=colors.get("control_border", "#6B8FC9"), width=1)
    draw.line((sx + 6, sy + 13, sx + btn_w - 6, sy + 13), fill=colors.get("control_symbol", "#123A74"), width=2)
    sx2 = sx + btn_w + gap
    draw.rectangle((sx2, sy, sx2 + btn_w, sy + btn_h), fill=colors.get("control_bg", "#EAF3FF"), outline=colors.get("control_border", "#6B8FC9"), width=1)
    draw.rectangle((sx2 + 6, sy + 5, sx2 + btn_w - 6, sy + btn_h - 5), outline=colors.get("control_symbol", "#123A74"), width=2)
    sx3 = sx2 + btn_w + gap
    draw.rectangle((sx3, sy, sx3 + btn_w, sy + btn_h), fill=colors.get("control_close", "#D86A60"), outline=colors.get("control_close_border", "#96423C"), width=1)
    draw.line((sx3 + 7, sy + 5, sx3 + btn_w - 7, sy + btn_h - 5), fill="#FFFFFF", width=2)
    draw.line((sx3 + btn_w - 7, sy + 5, sx3 + 7, sy + btn_h - 5), fill="#FFFFFF", width=2)


def _estimate_day_height(info):
    """Estimate by actual operation count, not only explicit newline count."""
    action = str(info.get("action") or "")
    chunks = [
        x.strip() for x in re.split(
            r"(?:\r?\n|[；;]+|(?=(?:[1-9][\.、\)）:]|[①②③④⑤⑥⑦⑧⑨⑩])\s*))",
            action
        )
        if x and x.strip()
    ]
    steps = max(2, len(chunks))
    metric_count = len(info.get("metric_items") or [])
    # Three normal operations + a readable status bar should not be compressed
    # into the old 150px forum reply.
    return 178 + max(0, steps - 3) * 24 + (8 if metric_count > 2 else 0)

def _compute_floor_heights(content_h, day_infos, tip_text, risk_font_size=17):
    gap = 10
    desired = [182, 198] + [_estimate_day_height(info) for info in day_infos]
    tip_lines = max(2, len([x for x in str(tip_text or "").splitlines() if x.strip()]))
    desired.append(178 + max(0, tip_lines - 2) * max(18, int(risk_font_size) + 2))
    n = len(desired)
    available = content_h - gap * (n - 1)
    base_total = sum(desired)
    mins = [172, 186] + [172] * len(day_infos) + [168]

    if base_total < available:
        extra = available - base_total
        weights = [1.0, 1.0] + [1.1] * len(day_infos) + [1.0]
        total_w = sum(weights)
        adds = [int(extra * w / total_w) for w in weights]
        rem = extra - sum(adds)
        for i in range(rem):
            adds[i % n] += 1
        heights = [desired[i] + adds[i] for i in range(n)]
    else:
        overflow = base_total - available
        shrink_caps = [max(0, desired[i] - mins[i]) for i in range(n)]
        heights = list(desired)
        total_cap = sum(shrink_caps)
        if total_cap > 0:
            shrinks = [min(shrink_caps[i], int(overflow * (shrink_caps[i] / total_cap))) for i in range(n)]
            rem = overflow - sum(shrinks)
            idx = 0
            while rem > 0 and idx < n * 8:
                i = idx % n
                if shrinks[i] < shrink_caps[i]:
                    shrinks[i] += 1
                    rem -= 1
                idx += 1
            heights = [desired[i] - shrinks[i] for i in range(n)]
        else:
            heights = mins
    return heights



def _draw_kpis_icon_top(base, draw, guide, services, rtools, colors, box, show_labels=False):
    """XP forum KPI layout: resource icon on top, numeric value below."""
    items = rtools.kpis(guide)
    if not items:
        return
    x1, y1, x2, y2 = map(int, box)
    count = len(items)
    gap = 14
    total_gap = gap * max(0, count - 1)
    cell_w = (x2 - x1 - total_gap) / max(1, count)
    h = max(1, y2 - y1)
    icon_size = max(34, min(58, int(h * 0.54), int(cell_w * 0.42)))
    label_h = 18 if show_labels else 0
    value_top = y1 + icon_size + 6

    for i, item in enumerate(items):
        cx1 = int(round(x1 + i * (cell_w + gap)))
        cx2 = int(round(cx1 + cell_w))
        if i > 0:
            divider_x = cx1 - gap // 2
            draw.line((divider_x, y1 + 6, divider_x, y2 - 6), fill=colors.get("separator", "#E2E8F0"), width=1)

        icon = item.get("icon")
        has_icon = bool(icon and Path(icon).exists())
        ix1 = int(cx1 + (cell_w - icon_size) / 2)
        iy1 = y1 + 2
        ibox = (ix1, iy1, ix1 + icon_size, iy1 + icon_size)
        if has_icon:
            services.draw_image_contain(base, Path(icon), ibox)
        else:
            draw.rectangle(ibox, fill=colors.get("icon_placeholder", "#F6F9FD"), outline=colors.get("chip", "#B9CDE8"), width=1)
            label = _clean_text(services.clean, item.get("label"), "?")
            services.draw_center(draw, ibox, label[:1], colors.get("link", "#174EA6"), max_size=20, min_size=12, bold=True, max_lines=1)

        value = _clean_text(services.clean, item.get("value"), "—")
        value_bottom = y2 - label_h
        services.draw_center(draw, (cx1 + 4, value_top, cx2 - 4, value_bottom), value, colors.get("text", "#222222"), max_size=25, min_size=15, bold=True, max_lines=2, line_gap=0)

        if show_labels:
            label = _clean_text(services.clean, item.get("label"), "")
            services.draw_center(draw, (cx1 + 4, y2 - label_h, cx2 - 4, y2), label, colors.get("muted", "#65758A"), max_size=10, min_size=8, bold=False, max_lines=1, line_gap=0)



def _draw_kpi_stack(base, draw, guide, services, rtools, colors, box):
    items = rtools.kpis(guide)
    if not items:
        return
    x1, y1, x2, y2 = map(int, box)
    count = len(items)
    gap = 12
    cell_w = (x2 - x1 - gap * max(0, count - 1)) / max(1, count)
    total_h = y2 - y1
    for i, item in enumerate(items):
        a = int(round(x1 + i * (cell_w + gap)))
        b = int(round(a + cell_w))
        label = services.clean(str(item.get("label") or ""))
        value = services.clean(str(item.get("value") or ""))
        # 有些表格把预算 KPI 只写成“预算”；尽量从预算资源解析结果推导成“钻石预算”等。
        if label in ("预算", "资源预算"):
            comps = item.get("budget_components") or []
            if comps and isinstance(comps[0], dict):
                resource = services.clean(str(comps[0].get("resource") or ""))
                if resource:
                    label = resource + "预算"
        icon = item.get("icon")

        # 三段式：标题 / 图标 / 数字，尽量保持上下间隔接近一致
        label_h = max(24, min(34, int(total_h * 0.18)))
        value_h = max(28, min(40, int(total_h * 0.23)))
        icon_size = max(32, min(52, int(min(cell_w * 0.56, total_h * 0.28))))
        remaining = total_h - label_h - value_h - icon_size
        spacing = max(8, int(remaining / 4))

        label_top = y1 + spacing
        icon_top = label_top + label_h + spacing
        value_top = icon_top + icon_size + spacing

        # top: label（稍微放大）
        services.draw_center(draw, (a + 4, label_top, b - 4, label_top + label_h), label, colors.get("dark", "#173C78"), max_size=16, min_size=13, bold=True, max_lines=1)

        # middle: icon（往下放一点）
        ix1 = int(a + (cell_w - icon_size) / 2)
        iy1 = int(icon_top)
        if icon and Path(icon).exists():
            services.draw_image_contain(base, Path(icon), (ix1, iy1, ix1 + icon_size, iy1 + icon_size))
        else:
            draw.rectangle((ix1, iy1, ix1 + icon_size, iy1 + icon_size), outline=colors.get("link", "#174EA6"), width=1)
            services.draw_center(draw, (ix1, iy1, ix1 + icon_size, iy1 + icon_size), "?", colors.get("link", "#174EA6"), max_size=16, min_size=10, bold=True, max_lines=1)

        # bottom: value
        services.draw_center(draw, (a + 4, value_top, b - 4, y2 - spacing), value, colors.get("text", "#222222"), max_size=24, min_size=17, bold=True, max_lines=2)

def _draw_floor_tools(draw, services, colors, box, text):
    x1, y1, x2, y2 = map(int, box)
    draw.line((x1, y1, x2, y1), fill=colors.get("separator", "#D7DFEA"), width=1)
    services.draw_left(draw, (x1 + 2, y1 + 2, x2, y2), text, colors.get("link", "#174EA6"), max_size=10, min_size=8, bold=False, max_lines=1, line_gap=0, valign="center")


def _draw_floor_block(img, draw, guide, services, rtools, colors, xp_cfg, *, left_box, right_box, floor_no, user, avatar_path, header_title, meta_time, body_mode, body_payload):
    _draw_user_panel(img, draw, left_box, name=user["name"], title=user["title"], badge=user["badge"], avatar_path=avatar_path, floor_text=floor_no, services=services, colors=colors, xp_cfg=xp_cfg)
    rx1, ry1, rx2, ry2 = map(int, right_box)
    services.draw_left(draw, (rx1, ry1 + 8, rx2, ry1 + 32), header_title, colors.get("link", "#174EA6"), max_size=19, min_size=15, bold=True, max_lines=1, line_gap=0, valign="center")
    draw.text((rx1, ry1 + 34), meta_time, font=services.get_font(11, False), fill=colors.get("meta", "#888888"))
    draw.line((rx1, ry1 + 50, rx2, ry1 + 50), fill=colors.get("separator", "#D7DFEA"), width=1)

    tools_h = 18 if xp_cfg.get("show_floor_tools", False) else 0
    content_bottom = ry2 - tools_h - 4
    if body_mode == "kpis":
        _draw_kpi_stack(img, draw, guide, services, rtools, colors, (rx1, ry1 + 56, rx2, content_bottom))
    elif body_mode == "reward":
        rtools.draw_reward_icons(img, draw, guide, (rx1, ry1 + 58, rx2, content_bottom), colors["text"], colors["link"], max_items=4, show_names=True)
    elif body_mode == "day":
        info = body_payload
        metric_h = 42 if info.get("metric_items") else 0
        action_bottom = content_bottom - metric_h - (6 if metric_h else 0)
        services.draw_left(
            draw, (rx1, ry1 + 56, rx2, action_bottom),
            info.get("action") or "", colors["text"],
            max_size=xp_cfg.get("day_action_font_size", 22),
            min_size=min(xp_cfg.get("day_action_min_font_size", 16), xp_cfg.get("day_action_font_size", 22)),
            bold=False, max_lines=xp_cfg.get("day_action_max_lines", 8),
            line_gap=xp_cfg.get("day_action_line_gap", 5), valign="top"
        )
        if metric_h:
            rtools.draw_metric_icons(
                img, draw, guide, info,
                (rx1, content_bottom - metric_h, rx2, content_bottom),
                colors.get("metric_text", "#666666"), colors["link"]
            )
    elif body_mode == "tip":
        body = body_payload
        services.draw_left(
            draw, (rx1, ry1 + 56, rx2, content_bottom), body,
            colors.get("tip_text", "#C62828"),
            max_size=xp_cfg.get("risk_tip_font_size", 19),
            min_size=min(xp_cfg.get("risk_tip_min_font_size", 15), xp_cfg.get("risk_tip_font_size", 19)),
            bold=True, max_lines=10, line_gap=xp_cfg.get("risk_tip_line_gap", 5), valign="top"
        )

    if tools_h:
        _draw_floor_tools(draw, services, colors, (rx1, ry2 - tools_h, rx2, ry2), xp_cfg.get("floor_toolbar_text", "引用 | 回复 | 评分 | 只看该作者"))


def render(guide, out_path: Path, services):
    W, H = services.W, services.H
    clean = services.clean
    get_font = services.get_font
    resolve_path = services.resolve_path
    r = SharedRendererTools(services)

    started = time.perf_counter()
    xp_cfg = _merge_xp_forum_cfg(guide, clean)
    colors = r.colors(guide, {
        "background": "#D6E3F3",
        "text": "#222222",
        "primary": "#2B5DAA",
        "dark": "#173C78",
        "light": "#E8F0FA",
        "chip": "#B9CDE8",
        "bar": "#4C78B8",
        "table": "#FFFFFF",
        "side": "#EDF3FA",
        "link": "#174EA6",
        "reward": "#FFFFFF",
        "tip": "#FFFDF2",
        "tip_side": "#FFF4C9",
        "tip_border": "#D4B65B",
        "tip_text": "#C62828",
        "window_bg": "#FFFFFF",
        "window_border": "#6787B4",
        "chrome": "#2E63B5",
        "chrome_border": "#5E86CC",
        "chrome_highlight": "#9FC0F8",
        "nav_bg": "#ECE9D8",
        "nav_border": "#ACA899",
        "toolbar_bg": "#F7F4E9",
        "toolbar_border": "#C9C1AA",
        "toolbar_text": "#4C617A",
        "bar_outline": "#31598F",
        "bar_subtext": "#EAF2FF",
        "post": "#FFFFFF",
        "top_post": "#F7F9FC",
        "post_outline": "#9FB4CF",
        "separator": "#D7DFEA",
        "meta": "#888888",
        "muted": "#65758A",
        "metric_text": "#666666",
        "icon_placeholder": "#F6F9FD",
        "avatar_ring": "#6C89B3",
        "avatar_fill": "#D8E6F8",
        "avatar_outline_width": 2,
        "control_bg": "#EAF3FF",
        "control_border": "#6B8FC9",
        "control_symbol": "#123A74",
        "control_close": "#D86A60",
        "control_close_border": "#96423C",
        "footer_text": "#385D8A",
        "footer_line": "#9FB4CF",
        "footer_bg": "#EAF1F8",
    })

    author_avatar = resolve_path(guide.get("cfg") or {}, xp_cfg.get("avatar_raw")) if xp_cfg.get("avatar_raw") else None
    days = guide.get("days") or []
    risks = r.risk_items(guide)
    tip_body = ("\n".join("[注意] " + x for x in risks[:5]) if risks else "[注意] 到档即停，避免资源透支。")
    default_day_times = _build_default_day_times(len(days), xp_cfg, guide)

    img = Image.new("RGBA", (W, H), colors["background"])
    d = ImageDraw.Draw(img)
    d.rectangle((24, 26, W - 24, H - 62), fill=colors.get("window_bg", "#FFFFFF"), outline=colors.get("window_border", "#6787B4"), width=1)

    d.rounded_rectangle((24, 26, W - 24, 74), radius=6, fill=colors.get("chrome", "#2E63B5"), outline=colors.get("chrome_border", "#5E86CC"), width=1)
    d.line((30, 34, W - 30, 34), fill=colors.get("chrome_highlight", "#9FC0F8"), width=1)
    d.text((42, 39), f"{xp_cfg['forum_name']} - {xp_cfg['forum_section']}", font=get_font(17, True), fill="#FFFFFF")
    if xp_cfg.get("show_window_controls", True):
        _draw_window_controls(d, (24, 26, W - 24, 74), colors)

    d.rectangle((24, 74, W - 24, 104), fill=colors.get("nav_bg", "#ECE9D8"), outline=colors.get("nav_border", "#ACA899"), width=1)
    d.text((42, 82), xp_cfg["forum_breadcrumb"], font=get_font(13, False), fill=colors.get("nav_text", colors.get("link", "#174EA6")))
    if xp_cfg.get("show_post_tools", True):
        d.rectangle((24, 104, W - 24, 126), fill=colors.get("toolbar_bg", "#F7F4E9"), outline=colors.get("toolbar_border", "#C9C1AA"), width=1)
        d.text((42, 109), xp_cfg["toolbar_text"], font=get_font(12, False), fill=colors.get("toolbar_text", "#4C617A"))
        title_top = 140
    else:
        title_top = 128

    d.rectangle((40, title_top, W - 40, title_top + 74), fill=colors.get("bar", "#4C78B8"), outline=colors.get("bar_outline", "#31598F"), width=1)
    d.text((58, title_top + 15), "[精华] " + clean(str(guide.get("title") or "活动攻略")), font=get_font(26, True), fill="#FFFFFF")
    d.text((58, title_top + 49), "楼主：" + r.author(guide) + "    收藏本帖 | 打印 | 只看楼主", font=get_font(12, False), fill=colors.get("bar_subtext", "#EAF2FF"))

    left_x1 = 40
    left_x2 = left_x1 + int(xp_cfg.get("user_panel_width", 150))
    right_x1 = left_x2 + int(xp_cfg.get("post_column_gap", 14))
    right_x2 = W - 58
    content_top = title_top + 86
    content_bottom = H - 106
    gap = 10

    heights = _compute_floor_heights(content_bottom - content_top, days, tip_body, xp_cfg.get("risk_tip_font_size", 17))
    # order: top, reward, day..., tip
    top_h = heights[0]
    reward_h = heights[1]
    day_heights = heights[2:2 + len(days)]
    tip_h = heights[-1]

    current_y = content_top

    # #1 概览
    y1, y2 = current_y, current_y + top_h
    d.rectangle((40, y1, W - 40, y2), fill=colors.get("top_post", "#F7F9FC"), outline=colors.get("post_outline", "#9FB4CF"), width=1)
    _draw_floor_block(img, d, guide, services, r, colors, xp_cfg,
                      left_box=(left_x1, y1, left_x2, y2),
                      right_box=(right_x1, y1, right_x2, y2),
                      floor_no="#1",
                      user={"name": xp_cfg["author_name"], "title": xp_cfg["author_title"], "badge": xp_cfg["author_badge"]},
                      avatar_path=author_avatar,
                      header_title="资源概览",
                      meta_time=f"发表于 {xp_cfg['top_post_time']}",
                      body_mode="kpis",
                      body_payload=None)
    current_y = y2 + gap

    # #2 奖励楼
    y1, y2 = current_y, current_y + reward_h
    d.rectangle((40, y1, W - 40, y2), fill=colors.get("reward", "#FFFFFF"), outline=colors.get("post_outline", "#9FB4CF"), width=1)
    reward_user = _resolve_floor_user(0, xp_cfg, clean)
    reward_avatar = resolve_path(guide.get("cfg") or {}, reward_user.get("avatar")) if reward_user.get("avatar") else None
    _draw_floor_block(img, d, guide, services, r, colors, xp_cfg,
                      left_box=(left_x1, y1, left_x2, y2),
                      right_box=(right_x1, y1, right_x2, y2),
                      floor_no="#2",
                      user=reward_user,
                      avatar_path=reward_avatar,
                      header_title=xp_cfg["reward_floor_title"],
                      meta_time=f"发表于 {xp_cfg['reward_post_time']}",
                      body_mode="reward",
                      body_payload=None)
    current_y = y2 + gap

    for i, info in enumerate(days):
        y1, y2 = current_y, current_y + day_heights[i]
        d.rectangle((40, y1, W - 40, y2), fill=colors.get("post", "#FFFFFF"), outline=colors.get("post_outline", "#9FB4CF"), width=1)
        user = _resolve_floor_user(i + 1, xp_cfg, clean)
        avatar = resolve_path(guide.get("cfg") or {}, user.get("avatar")) if user.get("avatar") else None
        if i < len(xp_cfg.get("day_post_times") or []):
            post_time = _clean_text(clean, xp_cfg["day_post_times"][i], default_day_times[i] if i < len(default_day_times) else "")
        else:
            post_time = default_day_times[i] if i < len(default_day_times) else f"{xp_cfg['date_prefix']}-{min(28,22+i):02d} 13:{29+i:02d}"
        _draw_floor_block(img, d, guide, services, r, colors, xp_cfg,
                          left_box=(left_x1, y1, left_x2, y2),
                          right_box=(right_x1, y1, right_x2, y2),
                          floor_no=f"#{i+3}",
                          user=user,
                          avatar_path=avatar,
                          header_title=_day_title_cn(info,xp_cfg,clean),
                          meta_time=f"发表于 {post_time}",
                          body_mode="day",
                          body_payload=info)
        current_y = y2 + gap

    y1, y2 = current_y, content_bottom
    d.rectangle((40, y1, W - 40, y2), fill=colors.get("tip", "#FFFDF2"), outline=colors.get("tip_border", "#D4B65B"), width=1)
    tip_user = _resolve_floor_user(len(days) + 1, xp_cfg, clean)
    tip_avatar = resolve_path(guide.get("cfg") or {}, tip_user.get("avatar")) if tip_user.get("avatar") else None
    tip_colors = dict(colors)
    tip_colors["side"] = colors.get("tip_side", "#FFF4C9")
    _draw_floor_block(img, d, guide, services, r, tip_colors, xp_cfg,
                      left_box=(left_x1, y1, left_x2, y2),
                      right_box=(right_x1, y1, right_x2, y2),
                      floor_no=f"#{len(days)+3}",
                      user=tip_user,
                      avatar_path=tip_avatar,
                      header_title=xp_cfg["tip_floor_title"],
                      meta_time=f"发表于 {xp_cfg['tip_post_time']}",
                      body_mode="tip",
                      body_payload=tip_body)

    r.footer_plain(
        d, guide, colors.get("footer_text", colors.get("dark", "#385D8A")),
        line=colors.get("footer_line", colors.get("post_outline", "#9FB4CF")),
        bg=colors.get("footer_bg", colors.get("light", "#EAF1F8")), height=70
    )
    r.save(img, out_path, guide, started)
