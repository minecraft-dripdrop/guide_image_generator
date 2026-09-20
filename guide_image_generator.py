#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Guide Image Generator.

- 从 Excel / JSON 读取攻略图数据。
- 通过 themes/ + renderers/ 分发到各主题渲染器。
- 支持单图生成、全主题预览、总览拼图和 HTML 预览图库。
"""
from __future__ import annotations

import ast
import hashlib
import inspect
import json
import math
import html
import re
import sys
import zipfile
from functools import lru_cache
from typing import Optional
import xml.etree.ElementTree as ET
from pathlib import Path

from theme_system import ThemeError, ThemeManager

try:
    from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageChops
except ImportError:
    print("缺少 Pillow，请先安装：python -m pip install pillow")
    if len(sys.argv) == 1:
        input("按回车退出...")
    raise SystemExit(2)

KEYWORD = "攻略图"
OUT_DIR_NAME = "output"
INPUT_DIR_NAME = "excel"
W, H = 1080, 2340
ENGINE_VERSION = "35.9"

RUNTIME_THEME_ID = None
RUNTIME_VARIANT_ID = None
RUNTIME_LEGACY_COLOR = None
THEME_MANAGER = None
# 记录双击交互模式中“刚才每张攻略图选择的主题/配色”，
# 供“重新加载配置并立即重新生成”复用，避免再次询问。
LAST_THEME_SELECTIONS = {}
CUSTOM_FONT_REGULAR = None
CUSTOM_FONT_BOLD = None

# 全主题预览的持久化成品缓存版本。修改签名结构时递增，旧缓存会自动失效。
RENDER_CACHE_SCHEMA = 1


def program_root_dir():
    """返回主 Python 脚本所在目录，所有固定程序目录均以这里为根。"""
    return Path(__file__).resolve().parent


def output_root_dir():
    """输出固定保存在主 Python 脚本同级的 output 文件夹。"""
    return program_root_dir() / OUT_DIR_NAME


def output_directory_for_book(book):
    """每个工作簿在 output 下使用独立子目录，避免输入目录影响输出位置。"""
    book = Path(book).expanduser().resolve()
    return output_root_dir() / safe_filename(book.stem)

QUALITY_COLOR_MAP = {
    "white": "#CBD6E2",
    "green": "#4CCB7A",
    "blue": "#4B8BFF",
    "purple": "#9B59FF",
    "orange": "#F39C12",
    "red": "#E74C3C",
    "gold": "#D4AF37",
    "pink": "#FF6BCB",
    "chaoyue": "#7A64FF",
    "jueshi": "#57D8A4",
}

QUALITY_RANK = {
    "white": 1,
    "green": 2,
    "blue": 3,
    "purple": 4,
    "orange": 5,
    "red": 6,
    "pink": 7,
    "chaoyue": 8,
    "jueshi": 9,
}

SPECIAL_QUALITY_GRADIENTS = {
    # 参考游戏边框：蓝/紫/粉 与 绿/青
    "chaoyue": ("#4F9DFF", "#C44BFF"),
    "jueshi": ("#6FDF5B", "#63E8FF"),
}

NS_MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
NS_REL_DOC = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
NS_REL_PKG = "http://schemas.openxmlformats.org/package/2006/relationships"
THEME_INDEX_KEYS = [
    "dk1", "lt1", "dk2", "lt2",
    "accent1", "accent2", "accent3", "accent4", "accent5", "accent6",
    "hlink", "folHlink",
]


# -----------------------------------------------------------------------------
# 运行时性能缓存
# -----------------------------------------------------------------------------

@lru_cache(maxsize=256)
def _load_rgba_cached(path_text, mtime_ns):
    """只从硬盘读取一次图片；mtime 变化后自动使用新缓存键。"""
    with Image.open(path_text) as opened:
        opened.load()
        return opened.convert("RGBA")


def load_rgba_image(path):
    """返回可安全修改的 RGBA 副本，避免反复 Image.open。"""
    path = Path(path).resolve()
    try:
        mtime_ns = path.stat().st_mtime_ns
    except OSError:
        mtime_ns = 0
    return _load_rgba_cached(str(path), mtime_ns).copy()


@lru_cache(maxsize=96)




@lru_cache(maxsize=96)




@lru_cache(maxsize=128)




def _path_cache_key(path):
    path = Path(path).resolve()
    try:
        mtime_ns = path.stat().st_mtime_ns
    except OSError:
        mtime_ns = 0
    return str(path), int(mtime_ns)


@lru_cache(maxsize=384)
def _contain_layer_cached(path_text, mtime_ns, max_w, max_h, bg_key):
    """缓存常用图标缩放结果；同一图标在多张攻略图中无需重复缩放。"""
    im = _load_rgba_cached(path_text, mtime_ns).copy()
    max_w, max_h = max(1, int(max_w)), max(1, int(max_h))
    im.thumbnail((max_w, max_h), Image.Resampling.LANCZOS)
    layer = Image.new("RGBA", (max_w, max_h), (0, 0, 0, 0))
    if bg_key:
        layer.alpha_composite(Image.new("RGBA", (max_w, max_h), bg_key), (0, 0))
    ox = (max_w - im.width) // 2
    oy = (max_h - im.height) // 2
    layer.alpha_composite(im, (ox, oy))
    return layer


@lru_cache(maxsize=96)






@lru_cache(maxsize=96)




def col_num(cell_ref: str) -> int:
    m = re.match(r"([A-Z]+)", cell_ref.upper())
    if not m:
        return 0
    n = 0
    for ch in m.group(1):
        n = n * 26 + ord(ch) - 64
    return n

def row_num(cell_ref: str) -> int:
    m = re.search(r"(\d+)$", cell_ref)
    return int(m.group(1)) if m else 0

def clean(v: str) -> str:
    v = (v or "").replace("\r", "").strip()
    if v.endswith(".0"):
        try:
            return str(int(float(v)))
        except Exception:
            pass
    return v

def safe_filename(name):
    return re.sub(r'[\\/:*?"<>|]+', "_", name).strip(" .") or "攻略图"

def workbook_sheet_targets(z: zipfile.ZipFile) -> dict[str, str]:
    wb = ET.fromstring(z.read("xl/workbook.xml"))
    rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
    rid_to_target = {}
    for rel in rels.findall(f".//{{{NS_REL_PKG}}}Relationship"):
        rid_to_target[rel.attrib.get("Id","")] = rel.attrib.get("Target","")
    result = {}
    for sh in wb.findall(f".//{{{NS_MAIN}}}sheet"):
        name = sh.attrib.get("name","")
        rid = sh.attrib.get(f"{{{NS_REL_DOC}}}id","")
        target = rid_to_target.get(rid,"")
        if not target:
            continue
        if target.startswith("/xl/"):
            path = target.lstrip("/")
        elif target.startswith("xl/"):
            path = target
        else:
            path = "xl/" + target.lstrip("/")
        result[name] = path
    return result

def read_theme_colors(z: zipfile.ZipFile) -> dict[int, str]:
    path = "xl/theme/theme1.xml"
    if path not in z.namelist():
        return {}
    root = ET.fromstring(z.read(path))
    clr_scheme = None
    for node in root.iter():
        if node.tag.endswith("}clrScheme"):
            clr_scheme = node
            break
    if clr_scheme is None:
        return {}
    result = {}
    for idx, key in enumerate(THEME_INDEX_KEYS):
        target = None
        for node in list(clr_scheme):
            if node.tag.endswith("}" + key):
                target = node
                break
        if target is None or not list(target):
            continue
        color_node = list(target)[0]
        val = color_node.attrib.get("lastClr") or color_node.attrib.get("val")
        if val and len(val) >= 6:
            result[idx] = "#" + val[-6:].upper()
    return result

def apply_tint(hex_color: str, tint: float) -> str:
    if not hex_color or not re.fullmatch(r"#[0-9A-Fa-f]{6}", hex_color):
        return hex_color
    r = int(hex_color[1:3], 16)
    g = int(hex_color[3:5], 16)
    b = int(hex_color[5:7], 16)
    def f(c):
        if tint < 0:
            return round(c * (1 + tint))
        return round(c + (255 - c) * tint)
    return "#{:02X}{:02X}{:02X}".format(
        max(0, min(255, f(r))),
        max(0, min(255, f(g))),
        max(0, min(255, f(b))),
    )

def resolve_color(node, theme_colors: dict[int, str]) -> Optional[str]:
    if node is None:
        return None
    rgb = node.attrib.get("rgb")
    if rgb:
        if len(rgb) == 8:
            return "#" + rgb[-6:].upper()
        if len(rgb) == 6:
            return "#" + rgb.upper()
    theme = node.attrib.get("theme")
    if theme is not None:
        try:
            color = theme_colors.get(int(theme))
            if color:
                tint = float(node.attrib.get("tint", "0"))
                return apply_tint(color, tint)
        except Exception:
            pass
    indexed = node.attrib.get("indexed")
    indexed_map = {
        "0": "#000000", "1": "#FFFFFF", "2": "#FF0000", "3": "#00FF00",
        "4": "#0000FF", "5": "#FFFF00", "6": "#FF00FF", "7": "#00FFFF",
        "8": "#000000", "9": "#FFFFFF",
    }
    return indexed_map.get(indexed)

def read_shared_strings(z: zipfile.ZipFile, theme_colors) -> list[dict]:
    if "xl/sharedStrings.xml" not in z.namelist():
        return []
    root = ET.fromstring(z.read("xl/sharedStrings.xml"))
    result = []
    for si in root.findall(f".//{{{NS_MAIN}}}si"):
        direct_t = si.find(f"{{{NS_MAIN}}}t")
        runs = []
        if direct_t is not None:
            txt = direct_t.text or ""
            runs = [{"text": txt, "color": None, "bold": False, "explicit_color": False}]
        else:
            for r in si.findall(f"{{{NS_MAIN}}}r"):
                t = r.find(f"{{{NS_MAIN}}}t")
                txt = t.text if t is not None and t.text else ""
                rpr = r.find(f"{{{NS_MAIN}}}rPr")
                color = None
                bold = False
                explicit = False
                if rpr is not None:
                    color_node = rpr.find(f"{{{NS_MAIN}}}color")
                    if color_node is not None:
                        color = resolve_color(color_node, theme_colors)
                        explicit = color is not None
                    bold = rpr.find(f"{{{NS_MAIN}}}b") is not None
                runs.append({"text": txt, "color": color, "bold": bold, "explicit_color": explicit})
        text = "".join(r["text"] for r in runs)
        result.append({"text": text, "runs": runs})
    return result

def read_styles(z: zipfile.ZipFile, theme_colors):
    if "xl/styles.xml" not in z.namelist():
        return [], [], []
    root = ET.fromstring(z.read("xl/styles.xml"))
    fills_node = root.find(f"{{{NS_MAIN}}}fills")
    fonts_node = root.find(f"{{{NS_MAIN}}}fonts")
    xfs_node = root.find(f"{{{NS_MAIN}}}cellXfs")
    fills = list(fills_node) if fills_node is not None else []
    fonts = list(fonts_node) if fonts_node is not None else []
    xfs = list(xfs_node) if xfs_node is not None else []
    parsed_fonts = []
    for font in fonts:
        color = resolve_color(font.find(f"{{{NS_MAIN}}}color"), theme_colors)
        bold = font.find(f"{{{NS_MAIN}}}b") is not None
        parsed_fonts.append({"color": color, "bold": bold})
    return fills, xfs, parsed_fonts

def cell_fill(style_id: Optional[int], fills, xfs, default: str) -> str:
    if style_id is None or style_id < 0 or style_id >= len(xfs):
        return default
    try:
        fill_id = int(xfs[style_id].attrib.get("fillId", "0"))
        if not (0 <= fill_id < len(fills)):
            return default
        pf = fills[fill_id].find(f"{{{NS_MAIN}}}patternFill")
        if pf is None:
            return default
        fg = pf.find(f"{{{NS_MAIN}}}fgColor")
        if fg is None:
            return default
        raw = fg.attrib.get("rgb", "")
        if len(raw) == 8:
            return "#" + raw[-6:].upper()
        if len(raw) == 6:
            return "#" + raw.upper()
    except Exception:
        pass
    return default

def cell_font(style_id: Optional[int], xfs, parsed_fonts):
    if style_id is None or not (0 <= style_id < len(xfs)):
        return {"color": None, "bold": False}
    try:
        font_id = int(xfs[style_id].attrib.get("fontId", "0"))
        if 0 <= font_id < len(parsed_fonts):
            return parsed_fonts[font_id]
    except Exception:
        pass
    return {"color": None, "bold": False}

def parse_inline_rich(c, theme_colors):
    is_node = c.find(f"{{{NS_MAIN}}}is")
    if is_node is None:
        return {"text": "", "runs": []}
    direct_t = is_node.find(f"{{{NS_MAIN}}}t")
    if direct_t is not None:
        txt = direct_t.text or ""
        return {"text": txt, "runs": [{"text": txt, "color": None, "bold": False, "explicit_color": False}]}
    runs = []
    for r in is_node.findall(f"{{{NS_MAIN}}}r"):
        t = r.find(f"{{{NS_MAIN}}}t")
        txt = t.text if t is not None and t.text else ""
        rpr = r.find(f"{{{NS_MAIN}}}rPr")
        color = None
        bold = False
        explicit = False
        if rpr is not None:
            color_node = rpr.find(f"{{{NS_MAIN}}}color")
            if color_node is not None:
                color = resolve_color(color_node, theme_colors)
                explicit = color is not None
            bold = rpr.find(f"{{{NS_MAIN}}}b") is not None
        runs.append({"text": txt, "color": color, "bold": bold, "explicit_color": explicit})
    return {"text": "".join(r["text"] for r in runs), "runs": runs}

def read_sheet(z, path, shared, theme_colors, xfs, parsed_fonts):
    root = ET.fromstring(z.read(path))
    values, styles, rich = {}, {}, {}
    for c in root.findall(f".//{{{NS_MAIN}}}c"):
        ref = c.attrib.get("r", "")
        if not ref:
            continue
        style_id = None
        if "s" in c.attrib:
            try:
                style_id = int(c.attrib["s"])
                styles[ref] = style_id
            except Exception:
                pass
        t = c.attrib.get("t", "")
        v = c.find(f"{{{NS_MAIN}}}v")
        rs = None
        if t == "inlineStr":
            item = parse_inline_rich(c, theme_colors)
            value = item["text"]
            rs = item["runs"]
        elif v is None:
            value = ""
        elif t == "s":
            try:
                item = shared[int(v.text or "0")]
                value = item["text"]
                rs = [dict(x) for x in item["runs"]]
            except Exception:
                value = ""
        elif t == "e":
            value = "#FORMULA_ERROR"
        else:
            value = v.text or ""
        value = clean(value)
        values[ref] = value
        if value:
            whole_font = cell_font(style_id, xfs, parsed_fonts)
            if not rs:
                rs = [{
                    "text": value,
                    "color": whole_font["color"],
                    "bold": whole_font["bold"],
                    "explicit_color": whole_font["color"] is not None,
                }]
            else:
                for run in rs:
                    if not run.get("explicit_color"):
                        run["color"] = whole_font["color"]
                    if not run.get("bold"):
                        run["bold"] = whole_font["bold"]
            rich[ref] = rs
    return values, styles, rich

def build_matrix(values):
    by_row = {}
    for ref, value in values.items():
        r, c = row_num(ref), col_num(ref)
        if r and c and value:
            by_row.setdefault(r, {})[c] = (ref, value)
    return by_row

def find_day_header(by_row):
    for r, cells in sorted(by_row.items()):
        texts = {c: v for c, (_, v) in cells.items()}
        has_day = any(v in {"天数","日期"} or v.lower() in {"day","days"} for v in texts.values())
        has_target = any("目标" in v or "档位" in v for v in texts.values())
        has_action = any("今天" in v or "操作" in v or "做这些" in v or "执行" in v for v in texts.values())
        if has_day and has_target and has_action:
            return r
    return None

def find_header_col(headers, patterns):
    for c, text in headers.items():
        low = text.lower()
        if any(p.lower() in low for p in patterns):
            return c
    return None

def looks_like_budget_value(text: str) -> bool:
    """判断一段文字是否更像“105000钻+12500翡翠”这类预算值，而不是攻略标题。"""
    s = clean(str(text))
    if not s or "攻略" in s or "活动" in s:
        return False

    # 纯数字 / 带常见数量单位的数字也属于 KPI 值，不应成为标题。
    if re.fullmatch(r"[0-9][0-9,]*(?:\.[0-9]+)?(?:[wWkK万千])?", s):
        return True

    amount = r"[0-9][0-9,]*(?:\.[0-9]+)?(?:[wWkK万千])?"
    resource = r"[^0-9+＋/／，、;；|\s]+"
    part = rf"(?:{amount}\s*{resource}|{resource}\s*{amount})"
    return re.fullmatch(rf"\s*{part}(?:\s*(?:\+|＋|/|／|，|、|;|；|\|)\s*{part})*\s*", s) is not None


def parse_day_marker(day_text: str):
    """
    兼容把特殊日标记直接写在 Day 单元格前面的旧写法，例如：
    - 爆发日 Day4
    - 【收尾日】Day7

    推荐写法仍是：A15=爆发日，B15=Day4。
    返回：(规范化后的 day 文本, 内联特殊日标记)。
    """
    raw = clean(str(day_text))
    if not raw:
        return raw, ""

    # 只把 DayX 前面的“XX日”识别成特殊标记，避免误拆正常标题。
    m = re.match(
        r'^\s*[\[【(（]?([^\]】)）:：|｜/\\\-\s]{1,12}日)[\]】)）]?[：:|｜/\\\-\s]*(Day\s*\d+.*)$',
        raw,
        flags=re.IGNORECASE,
    )
    if m:
        marker = clean(m.group(1))
        day = clean(m.group(2)).replace("Day ", "Day")
        return day, marker

    return raw, ""


def _column_letters(index: int) -> str:
    """1-based column number -> Excel column letters."""
    try:
        n = int(index)
    except Exception:
        return ""
    if n <= 0:
        return ""
    out = []
    while n:
        n, rem = divmod(n - 1, 26)
        out.append(chr(65 + rem))
    return "".join(reversed(out))


def _read_cell_formulas(z: zipfile.ZipFile, sheet_path: str) -> dict[str, str]:
    """Read raw formula text without changing the existing cached-value parser."""
    try:
        root = ET.fromstring(z.read(sheet_path))
    except Exception:
        return {}
    formulas = {}
    for c in root.findall(f".//{{{NS_MAIN}}}c"):
        ref = c.attrib.get("r", "")
        f = c.find(f"{{{NS_MAIN}}}f")
        if ref and f is not None and clean(f.text or ""):
            formulas[ref] = clean(f.text or "")
    return formulas


def _parse_single_cell_formula_ref(formula: str):
    """Parse a direct cross-sheet reference such as Sheet1!C20 or 'A B'!$C$20."""
    text = clean(str(formula or ""))
    if text.startswith("="):
        text = text[1:].strip()
    m = re.fullmatch(
        r"(?:'((?:[^']|'')+)'|([^!]+))!\$?([A-Za-z]+)\$?(\d+)",
        text,
    )
    if not m:
        return None
    sheet_name = (m.group(1) or m.group(2) or "").replace("''", "'").strip()
    if not sheet_name:
        return None
    return sheet_name, m.group(3).upper(), int(m.group(4))


def _as_float(value):
    text = clean(str(value or "")).replace(",", "")
    if not text:
        return None
    try:
        number = float(text)
    except Exception:
        return None
    if not math.isfinite(number):
        return None
    return number


def _find_tier_thresholds_in_workbook(z, targets, shared, theme_colors, xfs, parsed_fonts):
    """Find the workbook's tier threshold table (档位 / 累积积分) as real numeric data."""
    ordered = []
    preferred = ["基础计算设置"]
    for name in preferred:
        if name in targets:
            ordered.append((name, targets[name]))
    ordered.extend((name, path) for name, path in targets.items() if name not in preferred)

    for _sheet_name, sheet_path in ordered:
        try:
            values, _styles, _rich = read_sheet(
                z, sheet_path, shared, theme_colors, xfs, parsed_fonts
            )
        except Exception:
            continue
        by_row = build_matrix(values)
        for header_row, cells in sorted(by_row.items()):
            header_text = {c: clean(v) for c, (_, v) in cells.items()}
            tier_col = next(
                (c for c, text in header_text.items() if text in {"档位", "奖励档位", "积分档位"}),
                None,
            )
            points_col = next(
                (c for c, text in header_text.items() if text in {"累积积分", "累计积分", "档位积分", "积分要求"}),
                None,
            )
            if not tier_col or not points_col:
                continue

            thresholds = []
            for row in range(header_row + 1, min(header_row + 16, max(by_row.keys(), default=header_row) + 1)):
                row_cells = by_row.get(row, {})
                label = clean(row_cells.get(tier_col, ("", ""))[1])
                value = _as_float(row_cells.get(points_col, ("", ""))[1])
                m = re.fullmatch(r"第\s*(\d+)\s*档", label)
                if not m or value is None or value <= 0:
                    continue
                thresholds.append({
                    "tier": int(m.group(1)),
                    "label": f"第{int(m.group(1))}档",
                    "value": float(value),
                })
            if len(thresholds) >= 2:
                thresholds.sort(key=lambda item: item["tier"])
                return thresholds
    return []


def read_day_tier_progress_context(z, sheet_path, values, shared, theme_colors, xfs, parsed_fonts):
    """Resolve per-Day tier score + workbook tier thresholds.

    Preferred contract (new workbooks): the guide sheet exposes an explicit
    ``当日档位积分`` column beside Day1~Day7.  The renderer can therefore consume
    the final display value directly from the guide sheet, while the tier
    thresholds still come from the workbook's 档位/累积积分 table (normally
    ``基础计算设置!A6:B10``).

    Older workbooks remain compatible: when that explicit score column is
    absent (or a particular Day is blank), fall back to the historical rule of
    following the 目标档位 formula into the calculation sheet and reading the
    adjacent score cell.
    """
    by_row = build_matrix(values)
    header_row = find_day_header(by_row)
    if not header_row:
        return {}
    headers = {c: v for c, (_, v) in sorted(by_row.get(header_row, {}).items())}
    day_col = find_header_col(headers, ["天数", "日期", "day"])
    target_col = find_header_col(headers, ["目标档位", "目标", "档位"])
    score_col = find_header_col(
        headers,
        ["当日档位积分", "当天档位积分", "每日档位积分", "档位积分"],
    )
    if not day_col:
        return {}

    targets = workbook_sheet_targets(z)
    thresholds = _find_tier_thresholds_in_workbook(
        z, targets, shared, theme_colors, xfs, parsed_fonts
    )
    if not thresholds:
        return {}
    max_value = float(thresholds[-1]["value"])
    if max_value <= 0:
        return {}

    result = {}

    # New explicit interface: read the score straight from the guide sheet.
    # This is intentionally preferred even when the cell itself contains a
    # formula, because read_sheet() already exposes Excel's cached result.
    if score_col:
        score_letter = _column_letters(score_col)
        for row in range(header_row + 1, header_row + 32):
            cells = by_row.get(row, {})
            raw_day = cells.get(day_col, ("", ""))[1]
            if not raw_day:
                continue
            day, _marker = parse_day_marker(raw_day)
            if not is_valid_day_label(day):
                continue
            score = _as_float(cells.get(score_col, ("", ""))[1])
            if score is None or score < 0:
                continue
            result[row] = {
                "score": float(score),
                "max": max_value,
                "thresholds": [dict(item) for item in thresholds],
                "source_cell": f"{score_letter}{row}",
                "source_mode": "guide_score_column",
            }

    # Backward-compatible fallback for old sheets or isolated blank score cells.
    if not target_col:
        return result

    formulas = _read_cell_formulas(z, sheet_path)
    source_values_cache = {}
    target_letter = _column_letters(target_col)

    for row in range(header_row + 1, header_row + 32):
        if row in result:
            continue
        cells = by_row.get(row, {})
        raw_day = cells.get(day_col, ("", ""))[1]
        if not raw_day:
            continue
        day, _marker = parse_day_marker(raw_day)
        if not is_valid_day_label(day):
            continue

        formula = formulas.get(f"{target_letter}{row}")
        ref = _parse_single_cell_formula_ref(formula)
        if not ref:
            continue
        source_sheet, source_col_letters, source_row = ref
        source_path = targets.get(source_sheet)
        if not source_path:
            continue

        if source_sheet not in source_values_cache:
            try:
                source_values, _styles, _rich = read_sheet(
                    z, source_path, shared, theme_colors, xfs, parsed_fonts
                )
                source_values_cache[source_sheet] = source_values
            except Exception:
                source_values_cache[source_sheet] = {}
        source_values = source_values_cache[source_sheet]

        source_col = col_num(source_col_letters)
        score_ref = f"{_column_letters(source_col + 1)}{source_row}"
        score = _as_float(source_values.get(score_ref, ""))
        if score is None or score < 0:
            continue

        # Safety check: the referenced target label should match the visible guide target.
        visible_target = clean(cells.get(target_col, ("", ""))[1])
        source_target = clean(source_values.get(f"{source_col_letters}{source_row}", ""))
        if visible_target and source_target and visible_target != source_target:
            continue

        result[row] = {
            "score": float(score),
            "max": max_value,
            "thresholds": [dict(item) for item in thresholds],
            "source_sheet": source_sheet,
            "source_cell": score_ref,
            "source_mode": "legacy_target_formula",
        }
    return result

def is_valid_day_label(day_text: str) -> bool:
    """判断“天数”列是否真的是 Day 行，而不是后续的风险/提醒标题。"""
    s = clean(str(day_text))
    if not s:
        return False

    # 常见写法：Day1 / Day 1 / D1 / 第1天 / 1天。
    # Day1（首日）这类旧写法也兼容；纯数字则必须整格只有日序号，
    # 避免把“1092个……”之类风险正文误识别成 Day。
    if re.match(r"^(?:day\s*\d+|d\s*\d+)(?:\s*.*)?$", s, flags=re.IGNORECASE):
        return True
    if re.match(r"^(?:第\s*\d+\s*[天日]|\d+\s*[天日])(?:\s*.*)?$", s):
        return True
    if re.fullmatch(r"\d+", s):
        try:
            return 1 <= int(s) <= 31
        except ValueError:
            return False
    return False


def find_kpi_label_row(by_row, day_header_row):
    """
    找顶部 KPI 标签所在行。

    标题应位于这行之前；预算值、期望值则位于这行之后。
    用这个边界把“标题识别”和“KPI 数值识别”彻底分开。
    """
    best_row = None
    best_score = -1
    for r in range(1, day_header_row):
        cells = by_row.get(r, {})
        if not cells:
            continue
        labels = [clean(v) for _, v in cells.values() if clean(v)]
        if not labels:
            continue

        score = 0
        if any("预算" in v for v in labels):
            score += 3
        score += sum(1 for v in labels if any(k in v for k in ["期望", "预计", "预期"]))

        # 至少命中“预算”，或者同一行存在两个以上期望类标签，才视为 KPI 标签行。
        if score >= 3 or sum(1 for v in labels if any(k in v for k in ["期望", "预计", "预期"])) >= 2:
            if score > best_score:
                best_row = r
                best_score = score

    return best_row


def find_title(by_row, day_header_row, fallback_title="活动攻略"):
    """
    从 Excel 顶部读取标题。

    标题只在 KPI 标签行之前寻找。
    因此 B6 这类“105000钻+12500翡翠”的预算值永远不会被误当标题，
    同时 B2 / A1 等 Excel 标题仍会被直接读取。
    """
    kpi_row = find_kpi_label_row(by_row, day_header_row)
    limit = (kpi_row - 1) if kpi_row else min(day_header_row - 1, 6)
    limit = max(1, min(limit, day_header_row - 1))

    candidates = []
    strong_candidates = []
    for r in range(1, limit + 1):
        for c, (ref, raw_v) in sorted(by_row.get(r, {}).items()):
            v = clean(raw_v)
            if not v:
                continue
            if any(x in v for x in ["预算", "期望", "预计", "预期", "主爆发", "可兑换", "风险提示"]):
                continue
            # 不再把“核心”作为通用排除词；否则“2超越核心氪金攻略”会被误伤。
            if any(v.startswith(x) for x in ["攻略核心", "核心策略", "总体策略", "核心：", "核心:"]):
                continue
            if looks_like_budget_value(v):
                continue

            item = (r, c, ref, v)
            candidates.append(item)
            # Excel 标题通常含“攻略 / 活动 / 派对”等字样；强匹配优先。
            if any(k in v for k in ["攻略", "活动", "派对"]):
                strong_candidates.append(item)

    if strong_candidates:
        return strong_candidates[0]
    if candidates:
        return candidates[0]
    return (1, 1, "A1", fallback_title or "活动攻略")

def find_subtitle(by_row, title_row, day_header_row):
    """读取可选副标题。

    优先识别“副标题：xxx”这类明确写法；否则在标题行之后、KPI 标签行之前，
    选择第一条不像 KPI、作者、奖励或核心策略的短文本。没有合适内容时返回空串。
    """
    kpi_row = find_kpi_label_row(by_row, day_header_row)
    end_row = (kpi_row - 1) if kpi_row else min(day_header_row - 1, title_row + 4)
    if end_row <= title_row:
        return ""

    explicit = []
    candidates = []
    for r in range(title_row + 1, end_row + 1):
        for _, (_, raw_v) in sorted(by_row.get(r, {}).items()):
            v = clean(raw_v)
            if not v:
                continue
            m = re.match(r"^\s*(?:副标题|副题|小标题)\s*[：:]\s*(.+)$", v)
            if m and clean(m.group(1)):
                explicit.append(clean(m.group(1)))
                continue
            if any(k in v for k in ["预算", "期望", "预计", "预期", "可兑换", "兑换奖励", "风险提示"]):
                continue
            if any(v.startswith(k) for k in ["攻略核心", "核心策略", "总体策略", "核心：", "核心:", "攻略制作", "作者", "制作人"]):
                continue
            if looks_like_budget_value(v) or len(v) > 48:
                continue
            candidates.append(v)

    if explicit:
        return explicit[0]
    return candidates[0] if candidates else ""

def find_reward(by_row, day_header_row):
    for r in range(1, day_header_row):
        for c, (ref, v) in by_row.get(r, {}).items():
            if "可兑换" in v or "兑换奖励" in v:
                return r, c, ref, v
    return None

def find_core(by_row, day_header_row):
    for r in range(1, day_header_row):
        for c, (_, v) in by_row.get(r, {}).items():
            s = v.strip()
            if (s.startswith("攻略核心") or s.startswith("核心策略")
                or s.startswith("总体策略") or s.startswith("核心：")
                or s.startswith("核心:")):
                tail = re.sub(r"^[^：:]*[：:]", "", s).strip()
                if tail:
                    return s
    return ""

def find_kpis(by_row, title_row, day_header_row):
    """
    找顶部 KPI（预算 / 期望普通 / 期望高级）。

    KPI 扫描不依赖 title_row 起点。即使标题缺失、标题位置变化，
    也会在按天计划表之前独立扫描 KPI，避免“预算被误认成标题 -> KPI 全部消失”。
    """
    best = []
    best_score = (-1, -1)
    for label_row in range(1, day_header_row):
        labels = by_row.get(label_row, {})
        if not labels:
            continue
        for offset in (1, 2, 3):
            value_row = label_row + offset
            if value_row >= day_header_row:
                continue
            vals = by_row.get(value_row, {})
            pairs = []
            semantic_hits = 0
            for c, (_, label) in sorted(labels.items()):
                if c not in vals:
                    continue
                value = vals[c][1]
                if not label or not value:
                    continue
                if any(x in label for x in ["可兑换","核心","风险","执行版","手机","主爆发"]):
                    continue
                if len(label) > 20:
                    continue
                display_value = format_count_number(value) if any(x in label for x in ["期望", "预计", "预期"]) else value
                pairs.append((label, display_value))
                if any(x in label for x in ["预算", "期望", "预计", "预期"]):
                    semantic_hits += 1

            # 优先选“像 KPI 的标签更多”的组合，再比较栏位数量。
            score = (semantic_hits, len(pairs))
            if pairs and score > best_score:
                best = pairs
                best_score = score

    best = [
        (label, value) for label, value in best
        if "主爆发" not in label and "执行版" not in label and "手机全屏" not in label
    ]
    return best[:3]

def find_risk(by_row, day_end_row):
    """
    读取风险 / 提醒，并按“Excel 行 / 单元格内换行”拆成独立条目。

    day_end_row 必须传“最后一个真实 Day 所在行”，不能再用
    header_row + len(days) 推算。这样即使用户删除或插入空白行，
    Day7 后面的【风险提示】仍然能稳定找到。
    """
    risk_row = None
    risk_col = None
    risk_headers = ("风险提示", "风险", "重要提醒", "提醒", "注意事项", "注意")
    for r, cells in sorted(by_row.items()):
        if r <= day_end_row:
            continue
        for c, (_, v) in cells.items():
            text = clean(v)
            if not text:
                continue
            if any(text == header or text.startswith(header + "：") or text.startswith(header + ":")
                   for header in risk_headers):
                risk_row, risk_col = r, c
                break
        if risk_row:
            break
    if not risk_row:
        return []

    parts = []
    punctuation_only = {".", "。", "-", "—", "--", "——", "·", "•"}
    for r in range(risk_row + 1, risk_row + 20):
        cells = by_row.get(r, {})
        raw = ""
        if risk_col in cells and cells[risk_col][1]:
            raw = cells[risk_col][1]
        else:
            candidates = [clean(v) for _, v in cells.values() if len(clean(v)) >= 4]
            if candidates:
                raw = candidates[0]

        if not raw:
            continue

        for line in str(raw).replace("\r", "").split("\n"):
            line = clean(line)
            if line and line not in punctuation_only:
                parts.append(line)

    return parts



def format_count_number(value: str) -> str:
    """道具/次数类数量统一显示为整数，避免公式缓存浮点尾差。

    使用四舍五入（正数 .5 向上），不保留千分位，适用于期望兑换、
    Day1~Day7 的剩余/累积/期望等数量。
    """
    value = clean(value)
    try:
        n = float(value)
    except Exception:
        return value
    if n >= 0:
        rounded_n = math.floor(n + 0.5)
    else:
        rounded_n = math.ceil(n - 0.5)
    return str(int(rounded_n))


def get_theme_manager(require_themes=True):
    """按脚本目录加载已安装主题包。"""
    global THEME_MANAGER
    if THEME_MANAGER is None:
        themes_dir = Path(__file__).resolve().parent / "themes"
        THEME_MANAGER = ThemeManager(themes_dir, engine_version=ENGINE_VERSION)
    if require_themes:
        THEME_MANAGER.require_themes()
    return THEME_MANAGER


def theme_output_label(selection):
    """经典主题保持旧文件名；其他主题同时带主题名与变体名。"""
    if selection.get("theme_id") == "classic_clean":
        return selection.get("variant_name") or selection.get("variant_id") or "主题"
    return "{}_{}".format(
        selection.get("theme_name") or selection.get("theme_id") or "主题",
        selection.get("variant_name") or selection.get("variant_id") or "默认",
    )


def strip_json_comments(text: str) -> str:
    """
    删除 JSONC 风格注释，同时保留字符串内部的 //、/* */。

    支持：
      // 单行注释
      /* 多行注释 */

    注意：仍不要保留多余的末尾逗号。
    """
    out = []
    i = 0
    in_string = False
    escaped = False
    n = len(text)

    while i < n:
        ch = text[i]

        if in_string:
            out.append(ch)
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            i += 1
            continue

        if ch == '"':
            in_string = True
            out.append(ch)
            i += 1
            continue

        if ch == "/" and i + 1 < n and text[i + 1] == "/":
            i += 2
            while i < n and text[i] not in "\r\n":
                i += 1
            continue

        if ch == "/" and i + 1 < n and text[i + 1] == "*":
            i += 2
            while i + 1 < n and not (text[i] == "*" and text[i + 1] == "/"):
                i += 1
            i = min(n, i + 2)
            continue

        out.append(ch)
        i += 1

    return "".join(out)


def load_json_with_comments(path: Path):
    """读取 JSON；同时兼容写在 .json 文件中的 // 和 /* */ 注释。"""
    raw = Path(path).read_text(encoding="utf-8")
    return json.loads(strip_json_comments(raw))


def load_config(base_dir: Path):
    """
    config.json 优先顺序：
    1. Excel 同目录
    2. py 脚本同目录
    3. 当前工作目录
    """
    candidates = [
        Path(base_dir) / "config.json",
        Path(__file__).resolve().parent / "config.json",
        Path.cwd() / "config.json",
    ]
    cfg_path = next((p for p in candidates if p.exists()), None)
    if cfg_path is None:
        return {}

    try:
        data = load_json_with_comments(cfg_path)
        data["_config_dir"] = str(cfg_path.parent.resolve())
        data["_script_dir"] = str(Path(__file__).resolve().parent)
        return data
    except Exception as exc:
        print(f"[警告] config.json 读取失败：{exc}")
        return {}


def deep_merge_config(base, override):
    """递归合并配置：dict 递归合并，list/标量由活动配置整体覆盖。"""
    if not isinstance(base, dict):
        base = {}
    result = dict(base)
    if not isinstance(override, dict):
        return result
    for key, value in override.items():
        if key.startswith("_"):
            continue
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge_config(result.get(key), value)
        else:
            result[key] = value
    return result


def normalized_workbook_stem(stem: str) -> str:
    """去掉常见的下载/副本编号，方便 夏日派对攻略(5).xlsx 复用 夏日派对攻略.json。"""
    s = clean(stem)
    patterns = [
        r"\s*[\(（]\d+[\)）]\s*$",
        r"\s*[-_ ]?(?:副本|copy)\s*\d*\s*$",
    ]
    old = None
    while s and s != old:
        old = s
        for pat in patterns:
            s = re.sub(pat, "", s, flags=re.IGNORECASE).strip()
    return s or clean(stem)


def activity_config_candidates(book: Path):
    """返回该 Excel 对应的活动配置候选路径，按优先级排列。

    推荐命名：
      夏日派对攻略.xlsx -> 夏日派对攻略.json
      夏日派对攻略(5).xlsx -> 夏日派对攻略.json

    同时继续识别旧命名的 *.config.json。
    """
    book = Path(book).resolve()
    script_dir = Path(__file__).resolve().parent
    stem = book.stem
    norm = normalized_workbook_stem(stem)

    candidates = [
        book.parent / f"{stem}.json",
    ]
    if norm != stem:
        candidates.append(book.parent / f"{norm}.json")

    candidates.append(script_dir / f"{stem}.json")
    if norm != stem:
        candidates.append(script_dir / f"{norm}.json")

    # 兼容旧命名。
    candidates.append(book.parent / f"{stem}.config.json")
    if norm != stem:
        candidates.append(book.parent / f"{norm}.config.json")
    candidates.append(script_dir / f"{stem}.config.json")
    if norm != stem:
        candidates.append(script_dir / f"{norm}.config.json")

    for folder in [book.parent / "activity_configs", script_dir / "activity_configs"]:
        candidates.append(folder / f"{stem}.json")
        if norm != stem:
            candidates.append(folder / f"{norm}.json")

    out = []
    seen = set()
    for c in candidates:
        key = str(c)
        if key not in seen:
            seen.add(key)
            out.append(c)
    return out


def expected_activity_config_name(book: Path) -> str:
    """给提示信息使用的推荐活动配置文件名。"""
    return f"{normalized_workbook_stem(Path(book).stem)}.json"

def load_config_for_book(book: Path):
    """
    配置分两层：
    1. config.json：放所有活动共用的作者、作者 QQ 头像、群信息、头像框样式、
       预算资源、奖励物品库和品质边框。
    2. <Excel基础文件名>.json：放本活动独有的标题区布局微调参数和四类活动图标。

    活动级 header.background / header.banner 已全局废弃；页面背景统一由主题控制。
    """
    book = Path(book).resolve()
    base = load_config(book.parent)
    cfg = dict(base)

    activity_path = next((p for p in activity_config_candidates(book) if p.exists()), None)
    if activity_path is None:
        expected = expected_activity_config_name(book)
        cfg["_workbook_dir"] = str(book.parent)
        cfg["_missing_activity_config"] = True
        cfg["_expected_activity_config"] = expected
        print("")
        print("[提示] 这个 Excel 没有找到对应的活动配置 JSON。")
        print(f"       Excel：{book.name}")
        print(f"       请新建：{expected}")
        print("       可以复制【活动配置模板.json】后改名，再填写 activity_icons 等活动参数。")
        print("       页面背景统一由主题控制；不再需要 header.background / header.banner。")
        return cfg

    try:
        override = load_json_with_comments(activity_path)
        cfg = deep_merge_config(cfg, override)
        cfg["_activity_config_dir"] = str(activity_path.parent.resolve())
        cfg["_activity_config_path"] = str(activity_path.resolve())
        cfg["_workbook_dir"] = str(book.parent)
        cfg["_missing_activity_config"] = False
        print(f"活动配置：{activity_path.name}")
        return cfg
    except Exception as exc:
        print(f"[警告] 活动配置读取失败：{activity_path.name}：{exc}")
        cfg["_workbook_dir"] = str(book.parent)
        cfg["_missing_activity_config"] = True
        return cfg

def _path_roots(cfg):
    roots = []
    for raw_root in [
        cfg.get("_activity_config_dir"),
        cfg.get("_workbook_dir"),
        cfg.get("_config_dir"),
        cfg.get("_script_dir"),
        str(Path.cwd()),
    ]:
        if raw_root:
            root = Path(raw_root)
            if root not in roots:
                roots.append(root)
    return roots


def resolve_path(cfg: dict, path_value: Optional[str]) -> Optional[Path]:
    """
    解析素材路径，并缓存结果。

    优化点：
    - 相同路径只解析一次；
    - 只有精确路径失败时才建立一次文件名索引；
    - 不再为每个缺失路径反复 rglob 整个目录。
    """
    if not path_value:
        return None

    raw = str(path_value).replace("\\", "/").strip()
    cache = cfg.setdefault("_runtime_path_cache", {}) if isinstance(cfg, dict) else {}
    if raw in cache:
        cached = cache[raw]
        return Path(cached) if cached else None

    p = Path(raw)
    if p.is_absolute():
        result = p.resolve() if p.exists() else None
        cache[raw] = str(result) if result else ""
        return result

    roots = _path_roots(cfg)
    for root in roots:
        candidate = (root / p).resolve()
        if candidate.exists():
            cache[raw] = str(candidate)
            return candidate

    perf = cfg.get("performance") if isinstance(cfg, dict) else {}
    perf = perf if isinstance(perf, dict) else {}
    if not bool(perf.get("recursive_path_fallback", True)):
        cache[raw] = ""
        return None

    root_key = tuple(str(root.resolve()) for root in roots if root.exists())
    index_info = cfg.get("_runtime_file_index") if isinstance(cfg, dict) else None
    if not isinstance(index_info, dict) or index_info.get("roots") != root_key:
        filename_index = {}
        for root in roots:
            if not root.exists():
                continue
            try:
                for candidate in root.rglob("*"):
                    if candidate.is_file():
                        filename_index.setdefault(candidate.name.lower(), str(candidate.resolve()))
            except Exception:
                pass
        index_info = {"roots": root_key, "files": filename_index}
        if isinstance(cfg, dict):
            cfg["_runtime_file_index"] = index_info

    found = (index_info.get("files") or {}).get(p.name.lower())
    cache[raw] = found or ""
    return Path(found) if found else None

# -----------------------------------------------------------------------------
# 纯代码装饰标题栏
# -----------------------------------------------------------------------------
# 标题栏不读取本地图片，也不读取 ui_decorations。传入的 fill_color 就是当前
# 攻略主题色，所有明暗、边框、星饰和流光均在这里实时生成。


def _hex_rgb(hex_color: str):
    hex_color = (hex_color or "#000000").strip()
    if not re.fullmatch(r"#[0-9A-Fa-f]{6}", hex_color):
        hex_color = "#000000"
    return tuple(int(hex_color[i:i+2], 16) for i in (1, 3, 5))


def _rgba(hex_color, alpha=255):
    r, g, b = _hex_rgb(hex_color)
    return (r, g, b, max(0, min(255, int(alpha))))


def _lerp(a, b, t):
    return int(round(a + (b - a) * t))


def _lerp_rgb(c1, c2, t):
    return tuple(_lerp(c1[i], c2[i], t) for i in range(3))















































def _draw_four_point_star(draw, center, radius, fill, outline=None, width=1, inner_ratio=0.20):
    """细长四角星；在高倍图层绘制后缩小。"""
    cx, cy = center
    r = max(2.0, float(radius))
    inner = max(1.0, r * float(inner_ratio))
    pts = [
        (cx, cy-r), (cx+inner*0.45, cy-inner*0.70),
        (cx+r, cy), (cx+inner*0.45, cy+inner*0.70),
        (cx, cy+r), (cx-inner*0.45, cy+inner*0.70),
        (cx-r, cy), (cx-inner*0.45, cy-inner*0.70),
    ]
    pts = [(int(round(x)), int(round(y))) for x, y in pts]
    draw.polygon(pts, fill=fill)
    if outline:
        draw.line(pts + [pts[0]], fill=outline, width=max(1, int(width)), joint="curve")




def _draw_facet_diamond(draw, center, rx, ry, fill, dark, light, outline, width=1):
    """带切面感的菱形宝石。"""
    cx, cy = center
    outer = [(cx,cy-ry),(cx+rx,cy),(cx,cy+ry),(cx-rx,cy)]
    outer = [(int(x),int(y)) for x,y in outer]
    draw.polygon(outer, fill=fill)
    draw.line(outer+[outer[0]], fill=outline, width=max(1,int(width)), joint="curve")
    draw.polygon([(int(cx),int(cy-ry)),(int(cx+rx),int(cy)),(int(cx),int(cy))], fill=light)
    draw.polygon([(int(cx),int(cy)),(int(cx+rx),int(cy)),(int(cx),int(cy+ry))], fill=dark)
    draw.polygon([(int(cx-rx),int(cy)),(int(cx),int(cy)),(int(cx),int(cy+ry))], fill=_rgba(apply_tint(fill, -0.10), 255))
    inset = 0.58
    inner = [(cx,cy-ry*inset),(cx+rx*inset,cy),(cx,cy+ry*inset),(cx-rx*inset,cy)]
    inner=[(int(x),int(y)) for x,y in inner]
    draw.line(inner+[inner[0]], fill=(255,255,255,135), width=max(1,int(width*0.75)), joint="curve")





@lru_cache(maxsize=96)
def _draw_code_title_layer(size, fill_color, supersample=5):
    """纯代码简洁标题栏：圆角胶囊、两端小收口、内外四枚菱形星饰。"""
    width, height = map(int, size)
    s = max(4, int(supersample))
    sw, sh = max(1, width*s), max(1, height*s)
    canvas = Image.new("RGBA", (sw, sh), (0, 0, 0, 0))

    body_h = int(sh * 0.72)
    by1 = int((sh - body_h) * 0.50)
    by2 = by1 + body_h
    bx1 = int(sw * 0.070)
    bx2 = int(sw * 0.930)
    radius = body_h // 2
    mid_y = (by1 + by2) // 2

    shadow = Image.new("RGBA", (sw, sh), (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow)
    sd.rounded_rectangle(
        (bx1, by1 + 1.6*s, bx2, by2 + 2.4*s),
        radius=radius,
        fill=(28, 38, 42, 46),
    )
    shadow = shadow.filter(ImageFilter.GaussianBlur(1.25*s))
    canvas.alpha_composite(shadow)

    d = ImageDraw.Draw(canvas)
    edge = _rgba(apply_tint(fill_color, -0.28), 245)
    inner_edge = (255, 255, 255, 62)
    diamond = "#FFEEA6"
    outer_diamond = _rgba(apply_tint(fill_color, 0.63), 215)

    point_len = int(body_h * 0.20)
    point_half_h = int(body_h * 0.18)
    for side in (-1, 1):
        anchor = bx1 if side < 0 else bx2
        d.polygon([
            (anchor - side*int(point_len*0.50), mid_y - point_half_h),
            (anchor - side*point_len, mid_y),
            (anchor - side*int(point_len*0.50), mid_y + point_half_h),
            (anchor + side*int(point_len*0.15), mid_y),
        ], fill=_rgba(apply_tint(fill_color, -0.04), 255))

    grad = Image.new("RGBA", (sw, sh), (0, 0, 0, 0))
    gd = ImageDraw.Draw(grad)
    top = _hex_rgb(apply_tint(fill_color, 0.10))
    bottom = _hex_rgb(apply_tint(fill_color, -0.06))
    for yy in range(by1, by2 + 1):
        u = (yy - by1) / max(1, by2 - by1)
        c = _lerp_rgb(top, bottom, u)
        gd.line((bx1, yy, bx2, yy), fill=(*c, 255), width=1)
    mask = Image.new("L", (sw, sh), 0)
    ImageDraw.Draw(mask).rounded_rectangle((bx1, by1, bx2, by2), radius=radius, fill=255)
    grad.putalpha(mask)
    canvas.alpha_composite(grad)

    d = ImageDraw.Draw(canvas)
    d.rounded_rectangle((bx1, by1, bx2, by2), radius=radius, outline=edge, width=max(1, int(0.85*s)))
    d.rounded_rectangle(
        (bx1 + 1.6*s, by1 + 1.6*s, bx2 - 1.6*s, by2 - 1.6*s),
        radius=max(2*s, radius - 1.6*s),
        outline=inner_edge,
        width=max(1, int(0.45*s)),
    )

    for side in (-1, 1):
        inner_cx = bx1 + body_h*0.48 if side < 0 else bx2 - body_h*0.48
        _draw_facet_diamond(
            d, (inner_cx, mid_y), body_h*0.105, body_h*0.105,
            diamond, "#E8CA70", "#FFFCDC", diamond,
            max(1, int(0.48*s)),
        )
        outer_cx = bx1 - body_h*0.56 if side < 0 else bx2 + body_h*0.56
        _draw_four_point_star(d, (outer_cx, mid_y), body_h*0.072, outer_diamond, inner_ratio=0.22)

    return canvas.resize((width, height), Image.LANCZOS)

def draw_decorative_title(base, draw, box, text, fill_color, cfg=None, text_color="#FFF8DD"):
    """纯代码简洁装饰标题栏；宽度按标题字数自适应并在给定区域内居中。"""
    x1, y1, x2, y2 = map(int, box)
    available_w = max(1, x2 - x1)

    # 用实际文字宽度决定胶囊宽度。固定左右留白用于收口和菱形装饰，
    # 避免短标题占满整行、长标题又显得拥挤。
    measure_font = get_font(30, True)
    bb = draw.textbbox((0, 0), str(text), font=measure_font)
    measured_w = bb[2] - bb[0]
    # 在文字两侧保留适度呼吸空间；相较上一版略微放宽，但仍按字宽自适应。
    desired_w = int(math.ceil(measured_w + 164))
    desired_w = max(268, min(available_w, desired_w))
    center_x = (x1 + x2) // 2
    bx1 = int(round(center_x - desired_w / 2))
    bx2 = bx1 + desired_w
    by1, by2 = y1 + 3, y2 - 7

    layer = _draw_code_title_layer((bx2-bx1, by2-by1), fill_color, supersample=5)
    base.alpha_composite(layer, (bx1, by1))

    # 两侧保留稳定留白，并把文字再上移约 2px，让视觉中心更贴近胶囊主体。
    side_pad = min(70, max(52, int((bx2-bx1) * 0.16)))
    text_box = (bx1 + side_pad, by1 - 4, bx2 - side_pad, by2 - 5)
    draw_center(draw, (text_box[0], text_box[1]+1, text_box[2], text_box[3]+1), text,
                apply_tint(fill_color, -0.38), max_size=30, min_size=17, bold=True, max_lines=1)
    draw_center(draw, text_box, text, text_color, max_size=30, min_size=17, bold=True, max_lines=1)

@lru_cache(maxsize=64)
def _module_frame_layer_cached(width, height, color, fill, radius, ornate):
    """缓存模块外框图层；2 倍超采样兼顾平滑度和速度。"""
    w, h = max(1, int(width)), max(1, int(height))
    s = 2
    layer = Image.new("RGBA", (w*s, h*s), (0,0,0,0))

    shadow = Image.new("RGBA", layer.size, (0,0,0,0))
    sd = ImageDraw.Draw(shadow)
    sd.rounded_rectangle((3*s, 4*s, (w-3)*s, (h-2)*s), radius=radius*s, fill=(25,35,40,38))
    shadow = shadow.filter(ImageFilter.GaussianBlur(1.8*s))
    layer.alpha_composite(shadow)

    d = ImageDraw.Draw(layer)
    outer = _rgba(apply_tint(color, -0.10), 225)
    inner = _rgba(apply_tint(color, 0.48), 205)
    d.rounded_rectangle((2*s,2*s,(w-2)*s,(h-3)*s), radius=radius*s, fill=_rgba(fill,255), outline=outer, width=2*s)
    d.rounded_rectangle((9*s,9*s,(w-9)*s,(h-10)*s), radius=max(4*s,(radius-7)*s), outline=inner, width=1*s)
    d.line((18*s, 12*s, (w-18)*s, 12*s), fill=(255,255,255,150), width=1*s)

    if ornate:
        nail_r = 3.7*s
        positions = ((14*s,14*s),((w-14)*s,14*s),(14*s,(h-15)*s),((w-14)*s,(h-15)*s))
        for cx, cy in positions:
            d.ellipse((cx-nail_r+0.8*s, cy-nail_r+1.1*s, cx+nail_r+0.8*s, cy+nail_r+1.1*s), fill=(25,35,40,42))
            d.ellipse((cx-nail_r,cy-nail_r,cx+nail_r,cy+nail_r), fill=_rgba(apply_tint(color,0.28),245), outline=_rgba(apply_tint(color,-0.26),225), width=max(1,int(0.8*s)))
            d.ellipse((cx-1.45*s,cy-1.45*s,cx+1.45*s,cy+1.45*s), fill=_rgba(apply_tint(color,-0.08),225))
            d.ellipse((cx-1.9*s,cy-2.1*s,cx-0.35*s,cy-0.55*s), fill=(255,255,255,185))

    return layer.resize((w,h), Image.Resampling.LANCZOS)


def draw_module_frame(base, draw, box, color, fill="#FBFEFC", radius=22, ornate=True):
    """统一模块外框：使用缓存图层，避免每次创建超大蒙版并重复模糊。"""
    x1, y1, x2, y2 = map(int, box)
    w, h = max(1, x2-x1), max(1, y2-y1)
    layer = _module_frame_layer_cached(w, h, str(color), str(fill), int(radius), bool(ornate))
    base.alpha_composite(layer, (x1,y1))

def recommended_special_badge_width(cfg: dict, label: str, text_width_px: float, height=64):
    """简洁徽章宽度仅由文字决定。"""
    return max(116, min(144, int(round(float(text_width_px) + 44))))



@lru_cache(maxsize=32)
def _draw_code_special_badge_layer(size, supersample=3):
    """简洁收尾日徽章：长方形与倒三角合成单一轮廓，不显示连接缝。"""
    width, height = map(int, size)
    s = max(4, int(supersample))
    sw, sh = max(1, width*s), max(1, height*s)
    canvas = Image.new("RGBA", (sw, sh), (0, 0, 0, 0))

    margin_x = int(6*s)
    top_y = int(3*s)
    rect_bottom = int(sh * 0.58)
    apex_y = sh - int(4*s)
    shoulder_y = rect_bottom - int(1*s)

    # 先把矩形与倒三角合并成同一张蒙版，所有边框都从整体蒙版生成，
    # 因而连接处不会出现横向分割线。
    mask = Image.new("L", (sw, sh), 0)
    md = ImageDraw.Draw(mask)
    md.rounded_rectangle((margin_x, top_y, sw-margin_x, rect_bottom), radius=int(4*s), fill=255)
    md.polygon([
        (margin_x, shoulder_y),
        (sw-margin_x, shoulder_y),
        (sw//2, apex_y),
    ], fill=255)

    shadow = Image.new("RGBA", (sw, sh), (0, 0, 0, 0))
    shadow_mask = Image.new("L", (sw, sh), 0)
    shadow_mask.paste(mask, (0, int(2.1*s)))
    shadow_mask = shadow_mask.filter(ImageFilter.GaussianBlur(1.15*s))
    shadow.putalpha(shadow_mask)
    shadow.paste((74, 45, 6, 74), (0, 0, sw, sh), shadow_mask)
    canvas.alpha_composite(shadow)

    # 整体外描边。
    border_px = max(1, int(1.55*s))
    outer_mask = mask.filter(ImageFilter.MaxFilter(border_px*2 + 1))
    border_layer = Image.new("RGBA", (sw, sh), (168, 105, 18, 0))
    border_layer.putalpha(outer_mask)
    canvas.alpha_composite(border_layer)

    grad = Image.new("RGBA", (sw, sh), (0, 0, 0, 0))
    gd = ImageDraw.Draw(grad)
    top = _hex_rgb("#FFD969")
    mid = _hex_rgb("#EFB63B")
    bottom = _hex_rgb("#D28C18")
    for yy in range(sh):
        u = yy/max(1, sh-1)
        c = _lerp_rgb(top, mid, u/0.58) if u < 0.58 else _lerp_rgb(mid, bottom, (u-0.58)/0.42)
        gd.line((0, yy, sw, yy), fill=(*c, 255), width=1)
    grad.putalpha(mask)
    canvas.alpha_composite(grad)

    # 单一轮廓的内圈线，同样沿合并后的整体形状生成。
    inset_px = max(2, int(4.5*s))
    line_px = max(1, int(0.8*s))
    inner_outer = mask.filter(ImageFilter.MinFilter(inset_px*2 + 1))
    inner_inner = mask.filter(ImageFilter.MinFilter((inset_px + line_px)*2 + 1))
    inner_ring = ImageChops.subtract(inner_outer, inner_inner)
    inner_layer = Image.new("RGBA", (sw, sh), (255, 230, 135, 0))
    inner_layer.putalpha(inner_ring.point(lambda v: int(v * 0.90)))
    canvas.alpha_composite(inner_layer)

    # 只保留顶部轻微高光，不在矩形和三角连接处画任何线。
    d = ImageDraw.Draw(canvas)
    d.line((margin_x+int(10*s), top_y+int(4*s), sw-margin_x-int(10*s), top_y+int(4*s)),
           fill=(255, 250, 210, 145), width=max(1, int(0.6*s)))

    return canvas.resize((width, height), Image.LANCZOS)

def draw_special_day_badge(base, draw, box, text, primary, cfg=None):
    """固定黄色、纯代码绘制的简洁收尾日徽章；文字带清晰深金描边。"""
    x1, y1, x2, y2 = map(int, box)
    layer = _draw_code_special_badge_layer((x2-x1, y2-y1), supersample=3)
    base.alpha_composite(layer, (x1, y1))
    rect_bottom = y1 + int((y2-y1)*0.58)
    text_box = (x1+10, y1+1, x2-10, rect_bottom-2)

    font, lines, heights, total = fit_text(
        draw, text, text_box, max_size=20, min_size=11,
        bold=True, max_lines=1, line_gap=0
    )
    line = lines[0] if lines else str(text)
    tw = text_width(draw, line, font)
    tx = (text_box[0] + text_box[2] - tw) / 2
    ty = text_box[1] + (text_box[3] - text_box[1] - total) / 2
    # 先画轻微投影，再用 1px 深金描边提升浅色字在黄色底上的可读性。
    draw.text((tx, ty + 1), line, font=font, fill="#7D4807", stroke_width=2, stroke_fill="#7D4807")
    draw.text((tx, ty), line, font=font, fill="#FFFDF2", stroke_width=2, stroke_fill="#9A5B0B")




def draw_action_content(base, draw, box, text, color, highlight=False):
    """普通日居中对齐；Day7/特殊全宽日使用紧凑的 2×2 正常字重排版。"""
    lines=[clean(line) for line in str(text).replace("\r","").split("\n") if clean(line)]
    x1,y1,x2,y2=map(int,box)
    if highlight and len(lines)>=4 and (x2-x1)>=700:
        rows=[lines[:2],lines[2:4]]
        col_gap=18
        col_w=(x2-x1-col_gap)/2

        # 先选择一套四项都能容纳的统一字号，再根据真实字高紧密排列两行。
        chosen=None
        for size in range(19, 11, -1):
            font=get_font(size, False)
            bbs=[draw.textbbox((0,0), line, font=font) for line in lines[:4]]
            widths=[bb[2]-bb[0] for bb in bbs]
            heights=[bb[3]-bb[1] for bb in bbs]
            line_h=max(heights) if heights else size
            if max(widths, default=0) <= col_w-12 and line_h*2+5 <= y2-y1:
                chosen=(font,bbs,line_h)
                break
        if chosen is None:
            font=get_font(12, False)
            bbs=[draw.textbbox((0,0), line, font=font) for line in lines[:4]]
            line_h=max((bb[3]-bb[1] for bb in bbs), default=12)
        else:
            font,bbs,line_h=chosen

        row_gap=3
        total_h=line_h*2+row_gap
        start_y=y1+((y2-y1)-total_h)/2
        for ridx,row in enumerate(rows):
            visual_y=start_y+ridx*(line_h+row_gap)
            for cidx,line in enumerate(row):
                bb=bbs[ridx*2+cidx]
                tw=bb[2]-bb[0]
                cx1=x1+cidx*(col_w+col_gap)
                tx=cx1+(col_w-tw)/2-bb[0]
                ty=visual_y-bb[1]
                draw.text((tx,ty),line,font=font,fill=color)
        return
    draw_centered_aligned_lines(draw,box,text,color,max_size=21,min_size=13,bold=False,line_gap=1)


def activity_icon(cfg: dict, key: str):
    """读取活动 JSON 中 activity_icons 的图标。"""
    mapping = cfg.get("activity_icons") or {}
    if not isinstance(mapping, dict):
        return None
    return resolve_path(cfg, mapping.get(key))


def default_budget_icon(cfg: dict):
    """预算 KPI 的默认图标取通用 budget_resources 中的钻石；没有则取第一种预算资源。"""
    catalog = budget_resource_catalog(cfg)
    for item in catalog:
        if any(clean(a) in {"钻", "钻石"} for a in item.get("aliases", [])):
            return item.get("icon")
    return catalog[0].get("icon") if catalog else None


def config_kpi_icon(cfg: dict, label: str, idx: int):
    """顶部 KPI 图标：预算来自通用配置，普通/高级兑换来自活动配置。"""
    cl = clean(str(label))
    if "预算" in cl or idx == 0:
        return default_budget_icon(cfg)

    if idx == 1:
        icon = activity_icon(cfg, "expected_normal")
        if icon:
            return icon
    if idx == 2:
        icon = activity_icon(cfg, "expected_advanced")
        if icon:
            return icon

    # 兼容旧版 kpis 写法。
    items = cfg.get("kpis") or []
    for item in items:
        if clean(str(item.get("label", ""))) == cl:
            return resolve_path(cfg, item.get("icon"))
    if idx < len(items):
        return resolve_path(cfg, items[idx].get("icon"))
    return None

def build_render_kpis(kpis, cfg):
    """把解析得到的 KPI 转成最终渲染卡片。

    - 单一预算资源：仍然是一张预算卡
    - 多预算资源：拆成多张独立预算卡（如钻石预算、翡翠预算）
    - 期望 KPI 保持原样
    """
    render_kpis = []
    for idx, (label, value) in enumerate(kpis or []):
        cl = clean(str(label))
        if "预算" in cl:
            comps = parse_budget_components(value, cfg)
            if len(comps) >= 2:
                for comp in comps:
                    resource = clean(str(comp.get("resource", ""))) or "资源"
                    render_kpis.append({
                        "label": f"{resource}预算",
                        "value": clean(str(comp.get("amount", value))),
                        "icon": comp.get("icon") or config_kpi_icon(cfg, label, idx),
                        "budget_components": [],
                    })
            else:
                render_kpis.append({
                    "label": label,
                    "value": value,
                    "icon": config_kpi_icon(cfg, label, idx),
                    "budget_components": comps,
                })
        else:
            render_kpis.append({
                "label": label,
                "value": value,
                "icon": config_kpi_icon(cfg, label, idx),
                "budget_components": [],
            })
    return render_kpis


def budget_resource_catalog(cfg: dict):
    """
    读取 config.json 的 budget_resources。

    示例：
    "budget_resources": [
      {"name":"钻石", "aliases":["钻", "钻石"], "icon":"images/gem_purple.png"},
      {"name":"翡翠", "aliases":["翡翠"], "icon":"images/gem_jade.png"}
    ]
    """
    result = []
    for item in cfg.get("budget_resources") or []:
        name = clean(str(item.get("name", "")))
        aliases = [clean(str(x)) for x in (item.get("aliases") or []) if clean(str(x))]
        if name and name not in aliases:
            aliases.insert(0, name)
        if not name and aliases:
            name = aliases[0]
        if not name:
            continue
        result.append({
            "name": name,
            "aliases": aliases,
            "icon": resolve_path(cfg, item.get("icon")),
            "icon_raw": item.get("icon"),
        })
    return result


def match_budget_resource(cfg: dict, resource_name: str):
    target = re.sub(r"\s+", "", clean(resource_name)).lower()
    if not target:
        return None
    for item in budget_resource_catalog(cfg):
        for alias in item.get("aliases", []):
            a = re.sub(r"\s+", "", clean(alias)).lower()
            if a and (target == a or target in a or a in target):
                return item
    return None


def format_budget_amount(raw: str) -> str:
    """预算金额不加千分位逗号；仅清理用户输入里已有的逗号。

    例如：
      105000 -> 105000
      12,500 -> 12500
      4.5w -> 4.5w
    """
    raw = clean(str(raw)).replace(",", "")
    return raw


def budget_amount_is_zero(amount_raw: str) -> bool:
    """判断预算资源数量是否为 0；支持 0、0.0、0w、0万 等写法。"""
    s = clean(str(amount_raw)).replace(",", "")
    s = re.sub(r"[wWkK万千]$", "", s).strip()
    try:
        return abs(float(s)) < 1e-12
    except Exception:
        return False


def parse_budget_components(value: str, cfg: dict):
    """
    将预算值拆成多个资源。支持：
      45000钻 + 1200翡翠
      4.5w钻/2000翡翠
      钻石45000，翡翠1200

    数量为 0 的资源自动隐藏：
      105000钻石 + 0翡翠 -> 只显示钻石
      0钻石 + 5000翡翠 -> 只显示翡翠

    纯数字（例如 45000）返回空列表，继续走旧版“数字 + KPI 默认图标”。
    """
    text = clean(str(value))
    if not text or not re.search(r"[^0-9.,\s]", text):
        return []

    parts = [clean(x) for x in re.split(r"\s*(?:\+|/|／|，|、|;|；|\||\n)\s*", text) if clean(x)]
    out = []
    parsed_count = 0
    for part in parts:
        m = re.match(r"^([0-9][0-9,]*(?:\.[0-9]+)?(?:[wWkK万千])?)\s*([^0-9\s].*?)$", part)
        if not m:
            m2 = re.match(r"^([^0-9\s].*?)\s*([0-9][0-9,]*(?:\.[0-9]+)?(?:[wWkK万千])?)$", part)
            if m2:
                resource_raw, amount_raw = m2.group(1), m2.group(2)
            else:
                continue
        else:
            amount_raw, resource_raw = m.group(1), m.group(2)

        parsed_count += 1

        # 预算中为 0 的资源不显示，也不占一行。
        if budget_amount_is_zero(amount_raw):
            continue

        resource_raw = clean(resource_raw).strip("：:=")
        meta = match_budget_resource(cfg, resource_raw) or {}
        if meta.get("icon_raw") and not meta.get("icon"):
            print(f"[警告] 预算资源『{meta.get('name') or resource_raw}』图标找不到：{meta.get('icon_raw')}")
        elif not meta:
            print(f"[提示] 预算资源『{resource_raw}』尚未在 config.json 的 budget_resources 中配置图标。")
        out.append({
            "amount": format_budget_amount(amount_raw),
            "resource": meta.get("name") or resource_raw,
            "icon": meta.get("icon"),
            "icon_raw": meta.get("icon_raw"),
        })

    # 如果是多资源格式但全部为 0，显示单独的 0，避免回退成“0钻+0翡翠”。
    if parsed_count and not out:
        return [{"amount": "0", "resource": "", "icon": None, "icon_raw": None}]

    return out

def config_day_icon(cfg: dict, metric_item: dict):
    """Day 四个状态气泡的图标。

    新版活动配置只需要四个语义位置：
    - expected_normal / expected_advanced
    - lottery / random_box

    Excel 里的实际名称可以自由变化，例如：
    香草冰淇淋 -> 普通卷轴
    梦幻冰淇淋 -> 高级卷轴
    刮刮券 -> 制作券
    """
    label = clean(str(metric_item.get("label", "")))
    role = metric_item.get("role")
    index = int(metric_item.get("index", 0) or 0)

    if role == "expected":
        key = "expected_normal" if index == 0 else "expected_advanced"
        icon = activity_icon(cfg, key)
        if icon:
            return icon

    if role == "status":
        # “随机箱/宝箱/箱”优先判断为第二类状态，其余第一个状态按抽奖道具处理。
        if any(k in label for k in ["随机箱", "宝箱"]):
            icon = activity_icon(cfg, "random_box")
            if icon:
                return icon
        key = "lottery" if index == 0 else "random_box"
        icon = activity_icon(cfg, key)
        if icon:
            return icon

    # 兼容旧版 day_icons。
    mapping = cfg.get("day_icons") or {}
    if isinstance(mapping, dict):
        if label in mapping:
            return resolve_path(cfg, mapping.get(label))
        values = list(mapping.values())
        if 0 <= index < len(values):
            return resolve_path(cfg, values[index])
    return None

def build_item_catalog(cfg: dict):
    """构建并缓存奖励物品目录，避免每张物品卡都重复创建列表。"""
    cached = cfg.get("_runtime_item_catalog") if isinstance(cfg, dict) else None
    if isinstance(cached, list):
        return cached

    source = cfg.get("featured_items")
    if source is None:
        source = cfg.get("item_catalog", [])

    out = []
    for item in source or []:
        out.append({
            "name": clean(str(item.get("name", ""))),
            "icon": item.get("icon"),
            "quality": item.get("quality"),
            "text_color": item.get("text_color"),
            "rank_badge": clean(str(item.get("rank_badge", ""))).upper(),
            "is_fragment": bool(item.get("is_fragment", item.get("fragment", False))),
            "item_type": clean(str(item.get("item_type", ""))).lower(),
            "aliases": [
                clean(str(x))
                for x in (item.get("aliases") or [])
                if clean(str(x))
            ],
        })
    if isinstance(cfg, dict):
        cfg["_runtime_item_catalog"] = out
    return out

def find_item_meta(name: str, catalog: list[dict]):
    n = clean(name)
    for item in catalog:
        if item["name"] == n:
            return item
    for item in catalog:
        if item["name"] and item["name"] in n:
            return item
        if n and n in item["name"]:
            return item
        if any(alias == n or alias in n or n in alias for alias in item.get("aliases", [])):
            return item
    return None

def color_for_item(name: str, runs: list[dict]):
    if not runs:
        return None
    full = "".join(run.get("text", "") for run in runs)
    pos = full.find(name)
    if pos < 0:
        return None
    end = pos + len(name)
    index = 0
    colors = []
    for run in runs:
        txt = run.get("text", "")
        run_end = index + len(txt)
        if run_end > pos and index < end:
            color = run.get("color")
            if color:
                colors.append(color)
        index = run_end
    return colors[0] if colors else None

def _reward_strip_terminal_punctuation(text: str) -> str:
    return clean(str(text)).strip("。．.；;，,")


def _reward_is_fully_parenthesized(text: str) -> bool:
    s = clean(text)
    if len(s) < 2 or s[0] != "(" or s[-1] != ")":
        return False
    depth = 0
    for i, ch in enumerate(s):
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth < 0:
                return False
            if depth == 0 and i != len(s) - 1:
                return False
    return depth == 0


def _split_reward_top_level(text: str):
    """只在括号外拆分 + / 或，返回 (terms, connectors)。"""
    s = clean(str(text)).replace("（", "(").replace("）", ")")
    terms = []
    connectors = []
    buf = []
    depth = 0
    i = 0
    while i < len(s):
        ch = s[i]
        if ch == "(":
            depth += 1
            buf.append(ch)
            i += 1
            continue
        if ch == ")":
            depth = max(0, depth - 1)
            buf.append(ch)
            i += 1
            continue

        if depth == 0:
            matched = None
            step = 1
            if s.startswith("或者", i):
                matched, step = "或", 2
            elif ch == "或":
                matched = "或"
            elif ch in "+＋":
                matched = "+"
            if matched:
                term = _reward_strip_terminal_punctuation("".join(buf))
                if term:
                    terms.append(term)
                    connectors.append(matched)
                buf = []
                i += step
                continue

        buf.append(ch)
        i += 1

    term = _reward_strip_terminal_punctuation("".join(buf))
    if term:
        terms.append(term)

    # connectors 的标准含义是“terms[i] 与 terms[i+1] 之间的连接符”。
    if len(connectors) > max(0, len(terms) - 1):
        connectors = connectors[:len(terms)-1]
    return terms, connectors


def _parse_reward_item_token(token: str, reward_runs: list[dict], catalog: list[dict]):
    s = _reward_strip_terminal_punctuation(token)
    m = re.match(r"^(.*?)(?:[x×*]\s*([0-9]+))\s*$", s)
    if m:
        name = clean(m.group(1))
        qty = m.group(2)
    else:
        name = s
        qty = "1"
    if not name:
        return None

    meta = find_item_meta(name, catalog) or {}
    return {
        "type": "item",
        "name": name,
        "qty": qty,
        "icon": meta.get("icon"),
        "quality": meta.get("quality"),
        "rank_badge": meta.get("rank_badge") or "",
        "is_fragment": bool(meta.get("is_fragment")) or meta.get("item_type") == "fragment" or "碎片" in name,
        "text_color": color_for_item(name, reward_runs),
    }


def _make_reward_bundle(nodes):
    flat = []
    for node in nodes or []:
        if node and node.get("type") == "bundle":
            flat.extend(node.get("items") or [])
        elif node:
            flat.append(node)
    if len(flat) == 1:
        return flat[0]
    return {"type": "bundle", "items": flat}


def _parse_reward_parenthetical_expression(text: str, reward_runs: list[dict], catalog: list[dict]):
    """括号内按常规语义解析：+ 组成一套，或 分隔不同方案。"""
    terms, connectors = _split_reward_top_level(text)
    if not terms:
        return None

    # 先按“或”切成多个方案；每个方案里的“+”组成 bundle。
    option_term_groups = []
    current_terms = [terms[0]]
    for idx, connector in enumerate(connectors):
        next_term = terms[idx + 1]
        if connector == "或":
            option_term_groups.append(current_terms)
            current_terms = [next_term]
        else:
            current_terms.append(next_term)
    option_term_groups.append(current_terms)

    options = []
    for group in option_term_groups:
        factors = [_parse_reward_factor(x, reward_runs, catalog) for x in group]
        factors = [x for x in factors if x]
        if factors:
            options.append(_make_reward_bundle(factors))

    if not options:
        return None
    if len(options) == 1:
        return options[0]
    return {"type": "choice", "options": options}


def _parse_reward_factor(text: str, reward_runs: list[dict], catalog: list[dict]):
    s = _reward_strip_terminal_punctuation(text).replace("（", "(").replace("）", ")")
    if _reward_is_fully_parenthesized(s):
        return _parse_reward_parenthetical_expression(s[1:-1], reward_runs, catalog)
    return _parse_reward_item_token(s, reward_runs, catalog)


def parse_reward_items(reward_text: str, reward_runs: list[dict], catalog: list[dict]):
    """
    从 Excel 的“可兑换...”文字拆出奖励表达式，并保留括号语义。

    兼容原来的线性写法：
      A 或 B + C  ->  (A 或 B) + C

    新增括号组合写法：
      A 或 (B + C) -> 在同一个“或”选择框中显示：A  或  [B + C]

    返回顶层节点列表；每个节点带 connector_before，后续再合并成显示单元。
    """
    text = clean(reward_text)
    text = re.sub(r"^[^：:]*[：:]\s*", "", text)
    text = _reward_strip_terminal_punctuation(text)
    if not text:
        return []

    terms, connectors = _split_reward_top_level(text)
    nodes = []
    for i, term in enumerate(terms):
        node = _parse_reward_factor(term, reward_runs, catalog)
        if not node:
            continue
        node = dict(node)
        node["connector_before"] = connectors[i - 1] if i > 0 and i - 1 < len(connectors) else None
        nodes.append(node)
    return nodes

def parse_guide(sheet_name, values, styles, rich, fills, xfs, parsed_fonts, theme_selection, cfg, tier_progress_by_row=None):
    by_row = build_matrix(values)
    header_row = find_day_header(by_row)
    if not header_row:
        raise ValueError("没有找到按天计划表。表头至少需要【天数】【今天只做这些/操作】【目标档位】。")
    headers = {c: v for c, (_, v) in sorted(by_row.get(header_row, {}).items())}
    day_col = find_header_col(headers, ["天数","日期","day"])
    action_col = find_header_col(headers, ["今天只做这些","今天","操作","执行"])
    target_col = find_header_col(headers, ["目标档位","目标","档位"])
    if not day_col or not action_col or not target_col:
        raise ValueError("按天计划表缺少【天数/操作/目标档位】列。")

    status_cols = []
    expected_cols = []
    for c, h in headers.items():
        if c in {day_col, action_col, target_col}:
            continue
        if any(k in h for k in ["期望", "预计", "预期"]):
            expected_cols.append(c)
            continue
        if any(k in h for k in ["剩余", "累积", "累计", "持有", "库存"]):
            status_cols.append(c)
    status_cols = status_cols[:2]
    expected_cols = expected_cols[:2]

    metric_cols = status_cols + expected_cols

    days = []
    last_day_row = header_row
    r = header_row + 1
    while r <= header_row + 31 and len(days) < 7:
        cells = by_row.get(r, {})
        raw_day = cells.get(day_col, ("", ""))[1]
        if not raw_day:
            # 空白行只是版式，不再作为 Day 表结束条件。这样用户删/加空白行
            # 都不会改变后续风险提示的识别结果。
            r += 1
            continue

        # Day 左侧单元格作为通用“特殊日”标记。
        # 例如：A15=爆发日 / 收尾日 / 氪金日，B15=Day4。
        pre_day_marker = ""
        if (day_col - 1) in cells:
            pre_day_marker = clean(cells.get(day_col - 1, ("", ""))[1])

        day, inline_marker = parse_day_marker(raw_day)
        if not is_valid_day_label(day):
            # 只接受真实 Day 标记。尤其不能把 Day7 后的“风险提示”或正文
            # 当成 Day8/Day9；这是删掉空白行后风险模块消失的根因。
            r += 1
            continue

        special_label = pre_day_marker or inline_marker
        action = cells.get(action_col, ("",""))[1]
        target = cells.get(target_col, ("",""))[1]

        metric_items = []

        for idx, c in enumerate(status_cols):
            value = cells.get(c, ("",""))[1]
            if not value:
                continue
            metric_items.append({
                "label": headers[c],
                "value": format_count_number(value),
                "role": "status",
                "index": idx,
            })

        for idx, c in enumerate(expected_cols):
            value = cells.get(c, ("",""))[1]
            if not value:
                continue
            metric_items.append({
                "label": headers[c],
                "value": format_count_number(value),
                "role": "expected",
                "index": idx,
            })

        days.append({
            "day": day,
            "special_label": special_label,
            "action": action,
            "target": target,
            "metric_items": metric_items[:4],
            "tier_progress": (tier_progress_by_row or {}).get(r),
        })
        last_day_row = r
        r += 1

    if not days:
        raise ValueError("没有读取到按天执行数据。")

    fallback_title = re.sub(r"攻略图$", "攻略", clean(sheet_name)) or "活动攻略"
    title_row, _, title_ref, title = find_title(by_row, header_row, fallback_title=fallback_title)
    subtitle = find_subtitle(by_row, title_row, header_row)
    reward_info = find_reward(by_row, header_row)
    reward = reward_info[3] if reward_info else ""
    reward_ref = reward_info[2] if reward_info else ""
    reward_runs = rich.get(reward_ref, []) if reward_ref else []
    reward_fill = cell_fill(styles.get(reward_ref), fills, xfs, "#F8CBAD") if reward_ref else "#F8CBAD"
    core = find_core(by_row, header_row)
    kpis = find_kpis(by_row, title_row, header_row)
    risk = find_risk(by_row, last_day_row)
    palette_name = theme_selection["variant_name"]
    palette = theme_selection["palette"]

    bad = []
    check_values = [title, reward, core, subtitle] + list(risk) + [x for p in kpis for x in p]
    for value in check_values:
        if any(e in value for e in ["#FORMULA_ERROR","#NAME?","#REF!"]):
            bad.append(value[:20])
    for d in days:
        blob = d["action"] + d["target"] + "".join(m["label"] + m["value"] for m in d["metric_items"])
        if any(e in blob for e in ["#FORMULA_ERROR","#NAME?","#REF!"]):
            bad.append(d["day"])
    if bad:
        raise ValueError("有公式缓存错误。请先用 Excel 打开、等待公式计算完成并保存，再运行脚本。")

    catalog = build_item_catalog(cfg)
    reward_items = parse_reward_items(reward, reward_runs, catalog)

    if cfg.get("watermark"):
        watermark = str(cfg["watermark"])
    else:
        watermark = "欢迎加入冒险者日记萌新交流群：1040094624"

    return {
        "sheet": sheet_name,
        "title": title,
        "subtitle": subtitle,
        "theme_id": theme_selection["theme_id"],
        "theme_name": theme_selection["theme_name"],
        "theme_version": theme_selection["theme_version"],
        "theme_dir": theme_selection["theme_dir"],
        "variant_id": theme_selection["variant_id"],
        "variant_name": theme_selection["variant_name"],
        "theme_config": theme_selection["config"],
        "palette_name": palette_name,
        "palette": palette,
        "kpis": kpis,
        "core": core,
        "reward": reward,
        "reward_runs": reward_runs,
        "reward_fill": reward_fill,
        "reward_items": reward_items,
        "risk": risk,
        "days": days,
        "cfg": cfg,
        "watermark": watermark,
    }

def apply_font_config(cfg: Optional[dict]):
    """允许在通用 config.json 中通过 font_regular / font_bold 指定字体。"""
    global CUSTOM_FONT_REGULAR, CUSTOM_FONT_BOLD
    CUSTOM_FONT_REGULAR = None
    CUSTOM_FONT_BOLD = None
    if not isinstance(cfg, dict):
        return

    regular_raw = cfg.get("font_regular") or cfg.get("font") or cfg.get("font_path")
    bold_raw = cfg.get("font_bold") or cfg.get("font_bold_path") or regular_raw

    regular_path = resolve_path(cfg, regular_raw) if regular_raw else None
    bold_path = resolve_path(cfg, bold_raw) if bold_raw else None

    if regular_path and regular_path.exists():
        CUSTOM_FONT_REGULAR = str(regular_path)
    if bold_path and bold_path.exists():
        CUSTOM_FONT_BOLD = str(bold_path)

    # 字体路径改变后清空字体对象缓存，避免跨工作簿沿用旧字体。
    _get_font_cached.cache_clear()
    _font_path_cached.cache_clear()

@lru_cache(maxsize=16)
def _font_path_cached(bold, custom_regular, custom_bold):
    if bold and custom_bold and Path(custom_bold).exists():
        return custom_bold
    if (not bold) and custom_regular and Path(custom_regular).exists():
        return custom_regular
    if bold and custom_regular and Path(custom_regular).exists() and not custom_bold:
        return custom_regular

    candidates = []
    if sys.platform.startswith("win"):
        if bold:
            candidates += [r"C:\Windows\Fonts\msyhbd.ttc", r"C:\Windows\Fonts\simhei.ttf"]
        candidates += [r"C:\Windows\Fonts\msyh.ttc", r"C:\Windows\Fonts\simhei.ttf", r"C:\Windows\Fonts\simsun.ttc"]
    else:
        if bold:
            candidates += ["/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"]
        candidates += ["/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]
    for path_text in candidates:
        if Path(path_text).exists():
            return path_text
    return None




@lru_cache(maxsize=256)
def _get_font_cached(size, bold, custom_regular, custom_bold):
    path_text = _font_path_cached(bool(bold), custom_regular, custom_bold)
    return ImageFont.truetype(path_text, size=int(size)) if path_text else ImageFont.load_default()


def get_font(size, bold=False):
    return _get_font_cached(max(1, int(size)), bool(bold), CUSTOM_FONT_REGULAR, CUSTOM_FONT_BOLD)

def text_width(draw, text, font):
    b = draw.textbbox((0,0), text, font=font)
    return b[2] - b[0]

def wrap_text(draw, text, font, max_width):
    lines = []
    for para in (text or "").replace("\r","").split("\n"):
        if not para:
            lines.append("")
            continue
        line = ""
        for ch in para:
            test = line + ch
            if line and text_width(draw, test, font) > max_width:
                lines.append(line)
                line = ch
            else:
                line = test
        if line:
            lines.append(line)
    return lines or [""]

def fit_text(draw, text, box, max_size, min_size, bold=False, max_lines=4, line_gap=6):
    x1, y1, x2, y2 = box
    for size in range(max_size, min_size-1, -2):
        font = get_font(size, bold)
        lines = wrap_text(draw, text, font, x2-x1)
        if len(lines) > max_lines:
            continue
        heights, total = [], 0
        for line in lines:
            bb = draw.textbbox((0,0), line or " ", font=font)
            h = bb[3] - bb[1]
            heights.append(h)
            total += h
        total += line_gap * max(0, len(lines)-1)
        if total <= y2-y1:
            return font, lines, heights, total
    font = get_font(min_size, bold)
    lines = wrap_text(draw, text, font, x2-x1)[:max_lines]
    heights, total = [], 0
    for line in lines:
        bb = draw.textbbox((0,0), line or " ", font=font)
        h = bb[3] - bb[1]
        heights.append(h)
        total += h
    total += line_gap * max(0, len(lines)-1)
    return font, lines, heights, total

def draw_center(draw, box, text, color, max_size=32, min_size=18, bold=False, max_lines=4, line_gap=6):
    x1, y1, x2, y2 = box
    font, lines, heights, total = fit_text(draw, text, box, max_size, min_size, bold, max_lines, line_gap)
    y = y1 + (y2-y1-total)/2
    for line, h in zip(lines, heights):
        w = text_width(draw, line, font)
        draw.text(((x1+x2-w)/2, y), line, font=font, fill=color)
        y += h + line_gap

def draw_left(draw, box, text, color, max_size=28, min_size=14, bold=False, max_lines=4, line_gap=5, valign="center"):
    """在盒子内左对齐绘制自动换行文字。"""
    x1, y1, x2, y2 = box
    font, lines, heights, total = fit_text(draw, text, box, max_size, min_size, bold, max_lines, line_gap)
    if valign == "top":
        y = y1
    else:
        y = y1 + (y2 - y1 - total) / 2
    for line, h in zip(lines, heights):
        draw.text((x1, y), line, font=font, fill=color)
        y += h + line_gap


def choose_shared_kpi_label_size(draw, labels, max_width, max_size=29, min_size=13):
    labels = [clean(str(x)) for x in (labels or []) if clean(str(x))]
    if not labels:
        return max_size
    for size in range(max_size, min_size - 1, -1):
        font = get_font(size, True)
        if all(text_width(draw, label, font) <= max_width for label in labels):
            return size
    return min_size


def draw_centered_aligned_lines(draw, box, text, color, max_size=21, min_size=13, bold=False, line_gap=2):
    """多行文本：整体居中，但每行左边起点一致，用于 Day 文案序号对齐。"""
    x1, y1, x2, y2 = map(int, box)
    raw_lines = [clean(line) for line in str(text).replace("\r", "").split("\n") if clean(line)]
    if not raw_lines:
        return
    chosen = None
    for size in range(max_size, min_size - 1, -1):
        font = get_font(size, bold)
        widths, heights = [], []
        for line in raw_lines:
            bb = draw.textbbox((0, 0), line, font=font)
            widths.append(bb[2] - bb[0])
            heights.append(bb[3] - bb[1])
        block_w = max(widths) if widths else 0
        total_h = sum(heights) + line_gap * max(0, len(raw_lines) - 1)
        if block_w <= (x2 - x1) and total_h <= (y2 - y1):
            chosen = (font, widths, heights, block_w, total_h)
            break
    if chosen is None:
        font = get_font(min_size, bold)
        widths, heights = [], []
        for line in raw_lines:
            bb = draw.textbbox((0, 0), line, font=font)
            widths.append(bb[2] - bb[0])
            heights.append(bb[3] - bb[1])
        block_w = max(widths) if widths else 0
        total_h = sum(heights) + line_gap * max(0, len(raw_lines) - 1)
    else:
        font, widths, heights, block_w, total_h = chosen
    block_x = x1 + ((x2 - x1) - block_w) / 2
    y = y1 + ((y2 - y1) - total_h) / 2
    for line, h in zip(raw_lines, heights):
        draw.text((block_x, y), line, font=font, fill=color)
        y += h + line_gap


def draw_warning_icon(base, draw, box, fill="#F4C64E", outline="#9A6A12", text_color="#6E4500"):
    """高分辨率绘制的精细警告三角：柔和圆角、双层边缘和自绘感叹号。"""
    x1, y1, x2, y2 = map(int, box)
    width, height = max(1, x2-x1), max(1, y2-y1)
    s = 5
    sw, sh = width*s, height*s
    layer = Image.new("RGBA", (sw, sh), (0,0,0,0))

    margin = 2.2*s
    top = (sw/2, margin)
    left = (margin, sh-margin)
    right = (sw-margin, sh-margin)
    pts = [top, right, left]

    # 柔影。
    shadow = Image.new("RGBA", (sw,sh), (0,0,0,0))
    sd = ImageDraw.Draw(shadow)
    shifted=[(px+0.7*s,py+1.1*s) for px,py in pts]
    sd.polygon(shifted, fill=(78,48,4,85))
    shadow=shadow.filter(ImageFilter.GaussianBlur(0.9*s))
    layer.alpha_composite(shadow)

    d = ImageDraw.Draw(layer)
    # 外轮廓先铺底，再缩进绘制主体，避免低分辨率 polygon 的锯齿。
    d.polygon(pts, fill=_rgba(outline,255))
    d.line(pts+[top], fill=_rgba(outline,255), width=max(1,int(1.2*s)), joint="curve")

    inner_margin=4.1*s
    inner_top=(sw/2, inner_margin)
    inner_left=(inner_margin, sh-inner_margin)
    inner_right=(sw-inner_margin, sh-inner_margin)
    inner_pts=[inner_top,inner_right,inner_left]

    # 轻微纵向渐变。
    mask=Image.new("L",(sw,sh),0)
    ImageDraw.Draw(mask).polygon(inner_pts,fill=255)
    grad=Image.new("RGBA",(sw,sh),(0,0,0,0))
    gd=ImageDraw.Draw(grad)
    c_top=_hex_rgb(apply_tint(fill,0.18))
    c_bottom=_hex_rgb(apply_tint(fill,-0.06))
    for yy in range(sh):
        c=_lerp_rgb(c_top,c_bottom,yy/max(1,sh-1))
        gd.line((0,yy,sw,yy),fill=(*c,255),width=1)
    grad.putalpha(mask)
    layer.alpha_composite(grad)

    d=ImageDraw.Draw(layer)
    d.line(inner_pts+[inner_top], fill=(255,236,151,205), width=max(1,int(0.55*s)), joint="curve")
    # 左上侧高光。
    d.line((inner_left[0]+2.0*s,inner_left[1]-2.2*s,sw/2,inner_top[1]+2.0*s),
           fill=(255,250,205,150),width=max(1,int(0.55*s)))

    # 自绘感叹号：圆角短杆 + 圆点，比字体缩放更清晰稳定。
    cx=sw/2
    stem_w=2.5*s
    stem_top=sh*0.30
    stem_bottom=sh*0.61
    d.rounded_rectangle((cx-stem_w/2,stem_top,cx+stem_w/2,stem_bottom),
                        radius=stem_w/2,fill=_rgba(text_color,255))
    dot_r=1.55*s
    dot_cy=sh*0.73
    d.ellipse((cx-dot_r,dot_cy-dot_r,cx+dot_r,dot_cy+dot_r),fill=_rgba(text_color,255))
    d.line((cx-stem_w*0.18,stem_top+0.8*s,cx-stem_w*0.18,stem_bottom-1.0*s),
           fill=(255,245,190,85),width=max(1,int(0.35*s)))

    layer=layer.resize((width,height),Image.LANCZOS)
    base.alpha_composite(layer,(x1,y1))


def draw_center_text_with_trailing_icon(base, draw, box, text, color, icon_path=None, max_size=36, min_size=16, bold=True, gap=8):
    """
    在一个盒子里把“文本 + 小图标”整体居中。
    例如：105000 [钻石图标]
    这样图标不会挤压上面的标签排版。
    """
    x1, y1, x2, y2 = map(int, box)
    icon_exists = icon_path is not None and Path(icon_path).exists()

    for size in range(max_size, min_size - 1, -2):
        font = get_font(size, bold)
        bb = draw.textbbox((0, 0), text, font=font)
        tw = bb[2] - bb[0]
        th = bb[3] - bb[1]
        icon_size = min(th + 4, 30) if icon_exists else 0
        total_w = tw + (gap + icon_size if icon_exists else 0)
        if total_w <= (x2 - x1) - 8 and th <= (y2 - y1) - 4:
            group_x = x1 + ((x2 - x1) - total_w) / 2
            y = y1 + ((y2 - y1) - th) / 2 - bb[1]
            draw.text((group_x, y), text, font=font, fill=color)
            if icon_exists:
                ix1 = int(group_x + tw + gap)
                iy1 = int(y1 + ((y2 - y1) - icon_size) / 2)
                draw_image_contain(base, Path(icon_path), (ix1, iy1, ix1 + icon_size, iy1 + icon_size))
            return

    # fallback
    draw_center(draw, box, text, color, max_size=min_size, min_size=min_size, bold=bold, max_lines=1)






def _hex_rgb(color, fallback="#3A3024"):
    s = str(color or fallback).strip()
    if not re.fullmatch(r"#[0-9A-Fa-f]{6}", s):
        s = fallback
    return tuple(int(s[i:i+2], 16) for i in (1, 3, 5))








# -----------------------------------------------------------------------------
# 可配置左右分栏标题区
# -----------------------------------------------------------------------------













































































def rounded(draw, box, radius, fill, outline=None, width=1):
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)




def draw_image_contain(base: Image.Image, img_path: Path, box, bg=None):
    x1, y1, x2, y2 = map(int, box)
    try:
        max_w, max_h = x2 - x1, y2 - y1
        path_text, mtime_ns = _path_cache_key(img_path)
        bg_key = tuple(bg) if isinstance(bg, (list, tuple)) else bg
        layer = _contain_layer_cached(
            path_text, mtime_ns, max_w, max_h, bg_key
        ).copy()
        base.alpha_composite(layer, (x1, y1))
        return True
    except Exception:
        return False

def _resource_prefers_emerald(item):
    name = clean(str(item.get("resource", "")))
    return "翡翠" in name or "绿宝石" in name


def draw_kpi_resource_rows(base, draw, box, components, color):
    """多资源预算：每行绘制“数值 + 对应小图标”。"""
    x1, y1, x2, y2 = map(int, box)
    items = list(components or [])[:3]
    if not items:
        return
    gap = 3
    row_h = max(26, int(((y2-y1)-gap*(len(items)-1))/len(items)))
    for i, item in enumerate(items):
        ry1 = y1 + i*(row_h+gap)
        ry2 = min(y2, ry1+row_h)
        amount = clean(str(item.get("amount", "")))
        icon = item.get("icon")
        resource = clean(str(item.get("resource", "")))
        text = amount if icon else clean(f"{amount} {resource}")
        draw_center_text_with_trailing_icon(
            base, draw, (x1, ry1, x2, ry2), text, color,
            icon_path=icon, max_size=31 if len(items) > 1 else 39,
            min_size=17, bold=True, gap=7
        )


def draw_kpi_card(base, draw, box, label, value, palette, icon_path=None, budget_components=None, label_size=None):
    """KPI 卡片：颜色与表面样式全部由主题包控制。"""
    x1, y1, x2, y2 = map(int, box)
    card_fill = palette.get("kpi_card", palette.get("card", "#FFFFFF"))
    card_border = palette.get("kpi_border", palette.get("border", "#D7DDE6"))
    label_color = palette.get("kpi_label", palette.get("dark", "#303740"))
    value_color = palette.get("kpi_value", "#303740")
    rounded(draw, (x1, y1, x2, y2), 20, card_fill, card_border, 2)

    components = list(budget_components or [])
    big_icon = icon_path
    if components:
        if len(components) == 1:
            big_icon = components[0].get("icon") or icon_path
        else:
            emerald = next((item for item in components if _resource_prefers_emerald(item)), None)
            big_icon = (emerald or components[0]).get("icon") or icon_path

    card_h = y2-y1
    compact = card_h <= 104
    if compact:
        # 经典简洁主题的紧凑 KPI：减少纵向占用，把高度留给 Day1~Day7。
        # 图标、标签和值仍保持明确的视觉层级，但不再强制 120px 高卡片。
        circle_size = min(72, max(50, card_h-18), max(50, int((x2-x1)*0.24)))
        circle_pad = 11
        label_top = y1 + 7
        label_h = max(27, int(card_h * 0.39))
        value_top = label_top + label_h - 2
        value_bottom = y2 - 7
        label_max = 21
        label_min = 12
        value_max = 32
        value_min = 18
    else:
        circle_size = min(94, card_h-30, max(70, int((x2-x1)*0.30)))
        circle_pad = 16
        label_top = y1 + 10
        label_h = 58
        value_top = y1 + 58
        value_bottom = y2 - 16
        label_max = 29
        label_min = 13
        value_max = 43
        value_min = 22

    cx1 = x1 + circle_pad
    cy1 = y1 + (card_h-circle_size)//2
    cx2, cy2 = cx1+circle_size, cy1+circle_size
    circle_fill = palette.get("icon_circle", apply_tint(palette.get("light", "#EEF3F7"), 0.15))
    circle_border = palette.get("icon_circle_border", palette.get("chip", "#D7E3DB"))
    draw.ellipse((cx1, cy1, cx2, cy2), fill=circle_fill, outline=circle_border, width=2)
    if big_icon and Path(big_icon).exists():
        inset = max(7 if compact else 9, circle_size//9)
        draw_image_contain(base, Path(big_icon), (cx1+inset, cy1+inset, cx2-inset, cy2-inset))
    else:
        draw_center(draw, (cx1+5, cy1+5, cx2-5, cy2-5), "图标", label_color, max_size=15 if compact else 17, min_size=10, bold=True, max_lines=1)

    tx1 = cx2 + (10 if compact else 14)
    tx2 = x2 - (9 if compact else 12)
    if label_size:
        effective_label_size = min(int(label_size), label_max)
        draw_center(draw, (tx1, label_top, tx2, label_top+label_h), label, label_color,
                    max_size=effective_label_size, min_size=max(label_min, effective_label_size-2), bold=True, max_lines=1, line_gap=0)
    else:
        draw_center(draw, (tx1, label_top, tx2, label_top+label_h), label, label_color,
                    max_size=label_max, min_size=label_min, bold=True, max_lines=1, line_gap=0)
    value_box = (tx1, value_top, tx2, value_bottom)

    if components:
        if len(components) == 1:
            amount = clean(str(components[0].get("amount", value)))
            draw_center(draw, value_box, amount, value_color, max_size=value_max, min_size=value_min, bold=True, max_lines=1)
        else:
            draw_kpi_resource_rows(base, draw, value_box, components, value_color)
        return

    shown = clean(str(value))
    if any(k in clean(label) for k in ["期望", "预计", "预期"]):
        shown = format_count_number(shown)
    draw_center(draw, value_box, shown, value_color, max_size=value_max, min_size=value_min, bold=True, max_lines=1)










def quality_border_color(q):
    return QUALITY_COLOR_MAP.get(str(q or "").lower(), "#CBD6E2")

_QUALITY_GRADIENT_CACHE = {}






def draw_gradient_rounded_border(base, box, radius, color1, color2, width=4, fill="#FFFFFF"):
    """绘制渐变圆角外边框。"""
    x1, y1, x2, y2 = map(int, box)
    w = max(1, x2 - x1)
    h = max(1, y2 - y1)

    # 先画内部底色
    draw = ImageDraw.Draw(base)
    draw.rounded_rectangle((x1, y1, x2, y2), radius=radius, fill=fill)

    grad = Image.new("RGBA", (w, h), (0,0,0,0))
    gd = ImageDraw.Draw(grad)

    for yy in range(h):
        t = yy / max(1, h - 1)
        r = round(color1[0] * (1-t) + color2[0] * t)
        g = round(color1[1] * (1-t) + color2[1] * t)
        b = round(color1[2] * (1-t) + color2[2] * t)
        gd.line((0, yy, w, yy), fill=(r, g, b, 255))

    outer = Image.new("L", (w, h), 0)
    od = ImageDraw.Draw(outer)
    od.rounded_rectangle((0, 0, w-1, h-1), radius=radius, fill=255)

    inner = Image.new("L", (w, h), 0)
    idr = ImageDraw.Draw(inner)
    inset = width
    idr.rounded_rectangle(
        (inset, inset, w-1-inset, h-1-inset),
        radius=max(1, radius-inset),
        fill=255
    )

    # 使用 Pillow 原生运算替代 Python 逐像素双重循环。
    border_mask = ImageChops.subtract(outer, inner)
    grad.putalpha(border_mask)
    base.alpha_composite(grad, (x1, y1))


def reward_node_weight(node):
    if not node:
        return 1
    typ = node.get("type", "item")
    if typ == "item":
        return 1
    if typ == "bundle":
        return max(1, sum(reward_node_weight(x) for x in (node.get("items") or [])))
    if typ == "choice":
        return max(2, sum(reward_node_weight(x) for x in (node.get("options") or [])))
    return 1


def _without_reward_connector(node):
    out = dict(node or {})
    out.pop("connector_before", None)
    out["weight"] = reward_node_weight(out)
    return out


def build_reward_display_units(items):
    """把奖励节点按连接关系合并为显示单元，同时保留括号 bundle。"""
    units = []
    for raw_node in items or []:
        connector = raw_node.get("connector_before")
        node = _without_reward_connector(raw_node)
        if connector == "或" and units:
            last = units.pop()
            if last.get("type") == "choice":
                options = list(last.get("options") or []) + [node]
            else:
                options = [last, node]
            choice = {"type": "choice", "options": options}
            choice["weight"] = reward_node_weight(choice)
            units.append(choice)
        else:
            units.append(node)
    return units




def reward_item_quality(item, cfg):
    meta = find_item_meta(item.get("name", ""), build_item_catalog(cfg)) or {}
    return str(meta.get("quality") or item.get("quality") or "").lower()


def reward_node_quality(node, cfg):
    if not node:
        return ""
    typ = node.get("type", "item")
    if typ == "item":
        return reward_item_quality(node, cfg)
    children = node.get("items") if typ == "bundle" else node.get("options")
    return highest_quality(children or [], cfg)


def highest_quality(items, cfg):
    """返回节点列表中品质最高的品质 key。未知品质按最低处理。"""
    best_q = ""
    best_rank = -1
    for item in items or []:
        q = reward_node_quality(item, cfg)
        rank = QUALITY_RANK.get(q, 0)
        if rank > best_rank:
            best_q = q
            best_rank = rank
    return best_q


def _item_rank_badge_spec(meta, cfg):
    key = clean(str((meta or {}).get("rank_badge") or "")).upper()
    if not key:
        return None
    mapping = cfg.get("item_rank_badges") or {}
    if not isinstance(mapping, dict):
        return None
    raw = mapping.get(key) or mapping.get(key.lower())
    if not raw:
        return None
    if isinstance(raw, str):
        raw = {"path": raw}
    if not isinstance(raw, dict) or not raw.get("path"):
        return None
    spec = dict(raw)
    spec["key"] = key
    return spec


def draw_item_rank_badge(base, icon_box, meta, cfg):
    """把 S / SS / SSS 图片叠加在品质背景框左下角。"""
    spec = _item_rank_badge_spec(meta, cfg)
    if not spec:
        return
    path = resolve_path(cfg, spec.get("path"))
    if not path or not Path(path).exists():
        return
    try:
        badge = load_rgba_image(path)
    except Exception:
        return

    x1, y1, x2, y2 = map(int, icon_box)
    # 品质框通常以 contain 方式居中绘制；用实际居中的正方形区域定位，
    # 避免在宽卡片中把角标误放到整块内容区的最左边。
    raw_w = max(1, x2 - x1)
    raw_h = max(1, y2 - y1)
    side = min(raw_w, raw_h)
    x1 = x1 + (raw_w - side) // 2
    x2 = x1 + side
    y1 = y1 + (raw_h - side) // 2
    y2 = y1 + side
    iw = ih = side
    width_ratio = float(spec.get("width_ratio", 0.42))
    max_height_ratio = float(spec.get("max_height_ratio", 0.34))
    target_w = max(1, int(round(iw * width_ratio)))
    target_h = max(1, int(round(badge.height * target_w / max(1, badge.width))))
    max_h = max(1, int(round(ih * max_height_ratio)))
    if target_h > max_h:
        target_h = max_h
        target_w = max(1, int(round(badge.width * target_h / max(1, badge.height))))
    badge = badge.resize((target_w, target_h), Image.LANCZOS)

    visual = cfg.get("reward_item_visual") or {}
    if not isinstance(visual, dict):
        visual = {}
    try:
        ox_ratio = float(spec.get("offset_x_ratio", visual.get("rank_badge_offset_x_ratio", -0.03)))
    except Exception:
        ox_ratio = -0.03
    try:
        oy_ratio = float(spec.get("offset_y_ratio", visual.get("rank_badge_offset_y_ratio", 0.03)))
    except Exception:
        oy_ratio = 0.03
    ox = int(round(side * ox_ratio))
    oy = int(round(side * oy_ratio))
    px = x1 + ox
    py = y2 - target_h + oy
    base.alpha_composite(badge, (px, py))


def _item_fragment_badge_spec(meta, cfg):
    """返回碎片角标配置；碎片物品即使没有图片素材也会使用文字兜底。"""
    meta = meta or {}
    name = clean(str(meta.get("name") or ""))
    raw_flag = meta.get("is_fragment")
    is_fragment = bool(raw_flag) or clean(str(meta.get("item_type") or "")).lower() == "fragment" or "碎片" in name
    if not is_fragment:
        return None

    raw = cfg.get("item_fragment_badge") or cfg.get("fragment_badge") or {}
    if isinstance(raw, str):
        raw = {"path": raw}
    if not isinstance(raw, dict):
        raw = {}
    spec = dict(raw)
    spec.setdefault("text", "碎")
    spec.setdefault("size_ratio", 0.30)
    spec.setdefault("max_size_ratio", 0.34)
    spec.setdefault("offset_x", 2)
    spec.setdefault("offset_y", -2)
    return spec


def draw_item_fragment_badge(base, icon_box, meta, cfg):
    """把碎片标记叠加在品质背景框右上角，定位方式与左下角段位角标一致。"""
    spec = _item_fragment_badge_spec(meta, cfg)
    if not spec:
        return

    x1, y1, x2, y2 = map(int, icon_box)
    raw_w = max(1, x2 - x1)
    raw_h = max(1, y2 - y1)
    side = min(raw_w, raw_h)
    x1 = x1 + (raw_w - side) // 2
    x2 = x1 + side
    y1 = y1 + (raw_h - side) // 2
    y2 = y1 + side

    # 优先使用配置的碎片角标图片；没有素材时画一个小“碎”角标，保证逻辑可直接使用。
    path = resolve_path(cfg, spec.get("path")) if spec.get("path") else None
    if path and Path(path).exists():
        try:
            badge = load_rgba_image(path)
            width_ratio = float(spec.get("width_ratio", spec.get("size_ratio", 0.30)))
            max_height_ratio = float(spec.get("max_height_ratio", spec.get("max_size_ratio", 0.34)))
            target_w = max(1, int(round(side * width_ratio)))
            target_h = max(1, int(round(badge.height * target_w / max(1, badge.width))))
            max_h = max(1, int(round(side * max_height_ratio)))
            if target_h > max_h:
                target_h = max_h
                target_w = max(1, int(round(badge.width * target_h / max(1, badge.height))))
            badge = badge.resize((target_w, target_h), Image.LANCZOS)
            visual = cfg.get("reward_item_visual") or {}
            if not isinstance(visual, dict):
                visual = {}
            try:
                ox_ratio = float(visual.get("fragment_badge_offset_x_ratio", spec.get("offset_x_ratio", 0.03)))
            except Exception:
                ox_ratio = 0.03
            try:
                oy_ratio = float(visual.get("fragment_badge_offset_y_ratio", spec.get("offset_y_ratio", -0.03)))
            except Exception:
                oy_ratio = -0.03
            ox = int(round(side * ox_ratio))
            oy = int(round(side * oy_ratio))
            px = x2 - target_w + ox
            py = y1 + oy
            base.alpha_composite(badge, (px, py))
            return
        except Exception:
            pass

    d = ImageDraw.Draw(base)
    ratio = float(spec.get("size_ratio", 0.30))
    badge_side = max(1, int(round(side * ratio)))
    visual = cfg.get("reward_item_visual") or {}
    if not isinstance(visual, dict):
        visual = {}
    try:
        ox_ratio = float(visual.get("fragment_badge_offset_x_ratio", spec.get("offset_x_ratio", 0.03)))
    except Exception:
        ox_ratio = 0.03
    try:
        oy_ratio = float(visual.get("fragment_badge_offset_y_ratio", spec.get("offset_y_ratio", -0.03)))
    except Exception:
        oy_ratio = -0.03
    ox = int(round(side * ox_ratio))
    oy = int(round(side * oy_ratio))
    bx2 = x2 + ox
    by1 = y1 + oy
    bx1 = bx2 - badge_side
    by2 = by1 + badge_side
    radius = max(4, badge_side // 4)
    fill = spec.get("fill", "#5B3A8A")
    outline = spec.get("outline", "#F1DDFF")
    text_color = spec.get("text_color", "#FFFFFF")
    d.rounded_rectangle((bx1, by1, bx2, by2), radius=radius, fill=fill, outline=outline, width=1)
    text = clean(str(spec.get("text") or "碎"))[:1] or "碎"
    font = get_font(max(1, int(round(badge_side * 0.60))), True)
    bb = d.textbbox((0, 0), text, font=font)
    tw, th = bb[2] - bb[0], bb[3] - bb[1]
    tx = bx1 + (badge_side - tw) / 2 - bb[0]
    ty = by1 + (badge_side - th) / 2 - bb[1]
    d.text((tx, ty), text, font=font, fill=text_color)


def reward_item_text_color(item, meta, q, cfg):
    """奖励名称默认跟随品质色；配置中的 text_color 可显式覆盖。"""
    explicit = clean(str((meta or {}).get("text_color") or ""))
    if explicit:
        return explicit

    # 默认启用。确实需要继续读取 Excel 富文本颜色时，可在 config.json 中设为 false。
    if cfg.get("reward_text_follow_quality", True):
        color = quality_border_color(q)
        # 白品质的原始边框色太浅，作为文字时稍微压暗以保证可读性。
        if str(q or "").lower() == "white":
            return apply_tint(color, -0.36)
        return color

    return item.get("text_color") or "#203864"


def reward_icon_content_box(icon_box, has_quality_frame, cfg):
    """按品质框边长的固定比例计算物品本体区域。

    使用相对比例而不是固定像素内缩，避免小尺寸奖励框里的物品被压得过小。
    统一以实际居中的正方形
    品质框为基准，物品、品质框的比例随整体缩放保持不变。
    """
    x1, y1, x2, y2 = map(int, icon_box)
    raw_w = max(1, x2 - x1)
    raw_h = max(1, y2 - y1)
    side = min(raw_w, raw_h)
    sx1 = x1 + (raw_w - side) // 2
    sy1 = y1 + (raw_h - side) // 2

    visual = cfg.get("reward_item_visual") or {}
    if not isinstance(visual, dict):
        visual = {}
    key = "icon_ratio_in_frame" if has_quality_frame else "icon_ratio_plain"
    default_ratio = 0.84 if has_quality_frame else 0.92
    try:
        ratio = float(visual.get(key, default_ratio))
    except Exception:
        ratio = default_ratio
    ratio = max(0.35, min(1.0, ratio))

    content_side = max(1, int(round(side * ratio)))
    cx = sx1 + side / 2.0
    cy = sy1 + side / 2.0
    ix1 = int(round(cx - content_side / 2.0))
    iy1 = int(round(cy - content_side / 2.0))
    return (ix1, iy1, ix1 + content_side, iy1 + content_side)


def _draw_quality_card_background(base, draw, box, q, radius=16, palette=None):
    x1, y1, x2, y2 = map(int, box)
    palette = palette or {}
    outline = quality_border_color(q)
    card_fill = palette.get("reward_card", palette.get("card", "#FFFFFF"))
    if q in SPECIAL_QUALITY_GRADIENTS:
        c1, c2 = SPECIAL_QUALITY_GRADIENTS[q]
        c1 = tuple(int(c1.lstrip("#")[i:i+2], 16) for i in (0, 2, 4))
        c2 = tuple(int(c2.lstrip("#")[i:i+2], 16) for i in (0, 2, 4))
        draw_gradient_rounded_border(base, (x1, y1, x2, y2), radius, c1, c2, width=4, fill=card_fill)
    else:
        rounded(draw, (x1, y1, x2, y2), radius, card_fill, outline=outline, width=3)


def draw_exchange_item_content(base, draw, box, item, cfg, palette):
    """只绘制物品内容，不绘制整张物品卡外框。"""
    x1, y1, x2, y2 = map(int, box)
    meta = find_item_meta(item["name"], build_item_catalog(cfg)) or {}
    q = str(meta.get("quality") or item.get("quality") or "").lower()

    icon_path = resolve_path(cfg, meta.get("icon")) if meta.get("icon") else None
    border_path = None
    qmap = cfg.get("quality_borders") or {}
    if q and isinstance(qmap, dict):
        border_path = resolve_path(cfg, qmap.get(str(q)))

    # 品质背景框尺寸不动，只把真正的物品图标放入更小的内部区域。
    icon_box = (x1 + 18, y1 + 10, x2 - 18, y1 + 82)
    if icon_path:
        if border_path:
            draw_image_contain(base, border_path, icon_box)
            draw_image_contain(base, icon_path, reward_icon_content_box(icon_box, True, cfg))
        else:
            draw_image_contain(base, icon_path, reward_icon_content_box(icon_box, False, cfg))
    else:
        rounded(draw, icon_box, 12, palette["light"])
        draw_center(draw, icon_box, "物品图", palette["dark"], max_size=16, min_size=11, bold=True, max_lines=2)

    # 左下角段位标记 + 右上角碎片标记，都以完整品质背景框为定位基准。
    draw_item_rank_badge(base, icon_box, meta, cfg)
    fragment_meta = dict(meta)
    fragment_meta.setdefault("name", item.get("name", ""))
    if "is_fragment" in item:
        fragment_meta["is_fragment"] = bool(item.get("is_fragment"))
    draw_item_fragment_badge(base, icon_box, fragment_meta, cfg)

    name_color = reward_item_text_color(item, meta, q, cfg)
    title = f"{item['name']} ×{item['qty']}"
    draw_center(
        draw, (x1 + 4, y1 + 88, x2 - 4, y2 - 6),
        title, name_color,
        max_size=17, min_size=10, bold=True, max_lines=2, line_gap=1
    )


def draw_reward_bundle_content(base, draw, box, bundle, cfg, palette):
    """绘制括号中的“B + C”组合；二者必须一起兑换。"""
    x1, y1, x2, y2 = map(int, box)
    items = bundle.get("items") or []
    if not items:
        return

    # 只画边框，不铺背景色：明确这是一个不可拆分组合，又不让内容被“淡化”。
    rounded(
        draw, (x1, y1, x2, y2), 14,
        None,
        outline=apply_tint(palette["primary"], 0.46), width=2
    )
    pad_x = 5
    pad_y = 1
    plus_gap = 28
    weights = [reward_node_weight(x) for x in items]
    total_weight = max(1, sum(weights))
    usable = x2 - x1 - pad_x * 2 - plus_gap * max(0, len(items) - 1)
    cursor = x1 + pad_x
    boxes = []
    for node, weight in zip(items, weights):
        nw = usable * weight / total_weight
        bx1 = int(round(cursor))
        bx2 = int(round(cursor + nw))
        b = (bx1, y1 + pad_y, bx2, y2 - pad_y)
        boxes.append(b)
        draw_reward_node_content(base, draw, b, node, cfg, palette)
        cursor = bx2 + plus_gap

    for i in range(1, len(boxes)):
        cx = (boxes[i-1][2] + boxes[i][0]) / 2
        draw_center(
            draw, (int(cx-14), y1+6, int(cx+14), y2-6),
            "+", apply_tint(palette["dark"], 0.12),
            max_size=20, min_size=15, bold=True, max_lines=1
        )


def draw_reward_node_content(base, draw, box, node, cfg, palette):
    typ = (node or {}).get("type", "item")
    if typ == "bundle":
        draw_reward_bundle_content(base, draw, box, node, cfg, palette)
    elif typ == "choice":
        draw_reward_choice_group(base, draw, box, node.get("options") or [], cfg, palette)
    else:
        draw_exchange_item_content(base, draw, box, node, cfg, palette)


def draw_reward_choice_group(base, draw, box, options, cfg, palette, item_h=116):
    """绘制“方案 A 或 方案 B”；每个方案既可以是单品，也可以是括号组合。"""
    x1, y1, x2, y2 = map(int, box)
    options = options or []
    if not options:
        return

    q = highest_quality(options, cfg)
    _draw_quality_card_background(base, draw, (x1, y1, x2, y2), q, radius=18, palette=palette)

    pad_x = 10
    pad_y = 4
    or_gap = 38
    weights = [reward_node_weight(x) for x in options]
    total_weight = max(1, sum(weights))
    inner_w = x2 - x1 - pad_x * 2 - or_gap * max(0, len(options)-1)
    cursor = x1 + pad_x
    boxes = []
    for node, weight in zip(options, weights):
        nw = inner_w * weight / total_weight
        bx1 = int(round(cursor))
        bx2 = int(round(cursor + nw))
        b = (bx1, y1 + pad_y, bx2, y2 - pad_y)
        boxes.append(b)
        draw_reward_node_content(base, draw, b, node, cfg, palette)
        cursor = bx2 + or_gap

    for i in range(1, len(boxes)):
        cx = (boxes[i - 1][2] + boxes[i][0]) / 2
        draw_center(
            draw,
            (int(cx - 16), y1 + 8, int(cx + 16), y2 - 8),
            "或", palette.get("secondary_text", "#5F6670"),
            max_size=18, min_size=14, bold=True, max_lines=1
        )







def draw_day_metric_bubbles(base, draw, box, metric_items, cfg, palette):
    """Day 卡片底部气泡：显示顺序改为“文字 + 图标 + 数量”。"""
    x1, y1, x2, y2 = map(int, box)
    items = metric_items[:4]
    if not items:
        return
    cols = 2
    rows = math.ceil(len(items) / cols)
    gap = 8
    bubble_w = (x2 - x1 - gap) / cols
    bubble_h = (y2 - y1 - gap * (rows - 1)) / rows

    def display_label(label):
        s = clean(label)
        s = re.sub(r"^(期望|预计|预期)", "", s).strip()
        return s or clean(label)

    for i, item in enumerate(items):
        rr, cc = divmod(i, cols)
        bx1 = int(x1 + cc * (bubble_w + gap))
        by1 = int(y1 + rr * (bubble_h + gap))
        bx2 = int(bx1 + bubble_w)
        by2 = int(by1 + bubble_h)
        rounded(draw, (bx1, by1, bx2, by2), 14, palette.get("metric_card", palette.get("card", "#FFFFFF")), outline=palette.get("metric_border", palette.get("border", "#CBD3DA")), width=2)

        icon = config_day_icon(cfg, item)
        has_icon = bool(icon and Path(icon).exists())
        label = display_label(item["label"])
        value = clean(str(item["value"]))
        icon_size = min(24, by2 - by1 - 8)

        chosen = None
        for lsize in range(13, 8, -1):
            lfont = get_font(lsize, True)
            lbb = draw.textbbox((0,0), label, font=lfont)
            lw = lbb[2] - lbb[0]
            lh = lbb[3] - lbb[1]
            for vsize in range(18, 10, -1):
                vfont = get_font(vsize, True)
                vbb = draw.textbbox((0,0), value, font=vfont)
                vw = vbb[2] - vbb[0]
                vh = vbb[3] - vbb[1]
                total_w = lw + (8 if has_icon else 0) + (icon_size if has_icon else 0) + 8 + vw
                if total_w <= (bx2 - bx1 - 16) and max(lh, vh) <= (by2 - by1 - 6):
                    chosen = (lfont, vfont, lbb, vbb, lw, vw, lh, vh)
                    break
            if chosen:
                break
        if chosen is None:
            lfont = get_font(9, True)
            vfont = get_font(11, True)
            lbb = draw.textbbox((0,0), label, font=lfont)
            vbb = draw.textbbox((0,0), value, font=vfont)
            lw = lbb[2] - lbb[0]
            vw = vbb[2] - vbb[0]
            lh = lbb[3] - lbb[1]
            vh = vbb[3] - vbb[1]
        else:
            lfont, vfont, lbb, vbb, lw, vw, lh, vh = chosen
        total_w = lw + (8 if has_icon else 0) + (icon_size if has_icon else 0) + 8 + vw
        start_x = bx1 + ((bx2 - bx1) - total_w) / 2
        ly = by1 + ((by2 - by1) - lh) / 2 - lbb[1]
        vy = by1 + ((by2 - by1) - vh) / 2 - vbb[1]
        draw.text((start_x, ly), label, font=lfont, fill=palette.get("secondary_text", "#4B5563"))
        cur_x = start_x + lw + 8
        if has_icon:
            iy1 = int(by1 + ((by2 - by1) - icon_size) / 2)
            draw_image_contain(base, Path(icon), (int(cur_x), iy1, int(cur_x + icon_size), iy1 + icon_size))
            cur_x += icon_size + 8
        draw.text((cur_x, vy), value, font=vfont, fill=palette.get("metric_text", "#303740"))



# -----------------------------------------------------------------------------
# 模块化版式渲染入口
# -----------------------------------------------------------------------------

# Classic-only artwork/layout lives in renderers/classic.py; the main engine
# only dispatches to the renderer and keeps shared drawing/data APIs.

_RENDERER_SERVICES = None


def renderer_style(guide):
    """从主题配置中读取 renderer.style；空值保持经典版式兼容。"""
    theme_cfg = guide.get("theme_config") or {}
    renderer_cfg = theme_cfg.get("renderer") if isinstance(theme_cfg.get("renderer"), dict) else {}
    return clean(str(renderer_cfg.get("style") or "classic_cards")) or "classic_cards"


def renderer_services():
    """建立主引擎与独立 renderer 模块之间的稳定依赖边界。"""
    global _RENDERER_SERVICES
    if _RENDERER_SERVICES is None:
        from renderers.services import RendererServices
        _RENDERER_SERVICES = RendererServices.from_engine_namespace(globals())
    return _RENDERER_SERVICES


def render(guide, out_path: Path):
    """统一渲染入口：自动发现 renderers/ 中与 renderer.style 对应的模块。"""
    from renderers.registry import get_renderer

    style = renderer_style(guide)
    renderer = get_renderer(style)
    if renderer is None:
        print("[主题提示] 未识别 renderer.style={}，回退经典卡片布局。".format(style))
        renderer = get_renderer("classic_cards")
    if renderer is None:
        raise RuntimeError("经典 renderer 未加载，无法生成攻略图。")
    return renderer(guide, out_path, renderer_services())


def guide_sheet_sort_key(item):
    """优先按表名中的“4.5w / 10.5万”数值升序排列，便于逐张选择主题与配色。"""
    sheet_name = item[0] if isinstance(item, (tuple, list)) else str(item)
    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:w|W|万)", sheet_name)
    if m:
        return (0, float(m.group(1)), sheet_name)
    m = re.search(r"(\d+(?:\.\d+)?)", sheet_name)
    if m:
        return (1, float(m.group(1)), sheet_name)
    return (2, float("inf"), sheet_name)


def list_guide_sheets(book: Path):
    """只读取工作簿结构，返回按顺序排列的“攻略图”工作表。"""
    with zipfile.ZipFile(book, "r") as z:
        targets = workbook_sheet_targets(z)
    return sorted([(n,p) for n,p in targets.items() if KEYWORD in n], key=guide_sheet_sort_key)


def process_book(book: Path, selected_sheet_names=None, reuse_last_selections=False):
    out_dir = output_directory_for_book(book)
    out_dir.mkdir(parents=True, exist_ok=True)
    cfg = load_config_for_book(book)
    apply_font_config(cfg)

    # 统一 HTML 预览目录（正常生成也输出到这里，供统一 HTML 展示）
    preview_dir = out_dir
    preview_dir.mkdir(parents=True, exist_ok=True)
    preview_index = load_preview_index(preview_dir)

    with zipfile.ZipFile(book, "r") as z:
        targets = workbook_sheet_targets(z)
        theme_colors = read_theme_colors(z)
        shared = read_shared_strings(z, theme_colors)
        fills, xfs, parsed_fonts = read_styles(z, theme_colors)
        target_sheets = sorted([(n,p) for n,p in targets.items() if KEYWORD in n], key=guide_sheet_sort_key)

        if selected_sheet_names is not None:
            wanted=set(selected_sheet_names)
            target_sheets=[item for item in target_sheets if item[0] in wanted]

        if not target_sheets:
            print(f"[跳过] {book.name}：没有选中的'{KEYWORD}'工作表")
            return 0,0

        ok=0
        total_sheets=len(target_sheets)
        for seq,(sheet_name,sheet_path) in enumerate(target_sheets,1):
            try:
                cache_key = (str(Path(book).resolve()), str(sheet_name))
                selection = None
                if reuse_last_selections:
                    cached = LAST_THEME_SELECTIONS.get(cache_key)
                    if cached:
                        try:
                            selection = get_theme_manager().resolve(
                                cached.get("theme_id"), cached.get("variant_id")
                            )
                            print(
                                "复用刚才主题：{} [{} / {}]".format(
                                    sheet_name, selection["theme_name"], selection["variant_name"]
                                )
                            )
                        except Exception as exc:
                            print(f"[提示] 无法复用刚才的主题选择，将重新询问：{exc}")
                            selection = None
                if selection is None:
                    selection = prompt_theme_selection(
                        f"【{seq}/{total_sheets}】{book.name} → {sheet_name}",
                        fixed_theme_id=RUNTIME_THEME_ID,
                        fixed_variant_id=RUNTIME_VARIANT_ID,
                        legacy_color=RUNTIME_LEGACY_COLOR,
                    )
                LAST_THEME_SELECTIONS[cache_key] = {
                    "theme_id": selection.get("theme_id"),
                    "variant_id": selection.get("variant_id"),
                }
                print(
                    "开始生成：{} [{} / {}]".format(
                        sheet_name, selection["theme_name"], selection["variant_name"]
                    )
                )

                values,styles,rich=read_sheet(
                    z,sheet_path,shared,theme_colors,xfs,parsed_fonts
                )
                tier_progress_by_row = read_day_tier_progress_context(
                    z, sheet_path, values, shared, theme_colors, xfs, parsed_fonts
                )
                guide=parse_guide(
                    sheet_name,values,styles,rich,
                    fills,xfs,parsed_fonts,
                    selection,cfg,
                    tier_progress_by_row=tier_progress_by_row
                )

                # 正常生成也放到全主题预览目录下，和全主题预览共用同一套路径结构
                sheet_preview_dir = preview_dir / safe_filename(sheet_name)
                sheet_preview_dir.mkdir(parents=True, exist_ok=True)
                theme_folder = sheet_preview_dir / safe_filename(
                    "{}_v{}".format(selection["theme_name"], selection["theme_version"])
                )
                theme_folder.mkdir(parents=True, exist_ok=True)
                out = theme_folder / "01_{}.png".format(safe_filename(selection["variant_name"]))

                render(guide,out)
                ok+=1
                print(
                    "  OK  {} -> {} [{} / {}]".format(
                        sheet_name, out.name, guide["theme_name"], guide["variant_name"]
                    )
                )

                # 将本次正常生成的记录追加到 preview_index，供统一 HTML 展示
                record = {
                    "path": str(out.resolve()),
                    "theme_id": selection.get("theme_id"),
                    "theme_name": selection.get("theme_name"),
                    "theme_version": selection.get("theme_version"),
                    "variant_id": selection.get("variant_id"),
                    "variant_name": selection.get("variant_name"),
                }
                # 以 sheet 为单位聚合；同一 sheet 多次生成不同变体时追加
                existing = preview_index.get(sheet_name, {"records": [], "contact_sheet": None, "count": 0})
                existing_records = existing.get("records", [])
                # 去重：同主题+同变体已存在则替换，否则追加
                dup_idx = None
                for i, r in enumerate(existing_records):
                    if (r.get("theme_id") == record["theme_id"] and
                        r.get("variant_id") == record["variant_id"]):
                        dup_idx = i
                        break
                if dup_idx is not None:
                    existing_records[dup_idx] = record
                else:
                    existing_records.append(record)
                preview_index[sheet_name] = {
                    "records": existing_records,
                    "contact_sheet": existing.get("contact_sheet"),
                    "count": len(existing_records),
                }
                save_preview_index(preview_dir, preview_index)
                html_path = rebuild_excel_preview_html(preview_dir, book.stem)
                if html_path:
                    print("  统一 HTML 预览：{}".format(html_path))

            except Exception as exc:
                print(f"  FAIL {sheet_name}")
                print(f"       {exc}")
        return ok,len(target_sheets)


def all_theme_selections(theme_id=None):
    """返回已安装主题的全部变体选择；可限定为一个主题。"""
    manager = get_theme_manager()
    themes = [manager.get(theme_id)] if theme_id else list(manager.themes)
    selections = []
    for theme in themes:
        for variant in theme.variants:
            selections.append(theme.resolve(variant["id"]))
    return selections


def _preview_label(record):
    return "{} v{} / {}".format(
        record.get("theme_name") or record.get("theme_id") or "主题",
        record.get("theme_version") or "0.0.0",
        record.get("variant_name") or record.get("variant_id") or "配色",
    )


def build_preview_contact_sheet(records, out_path, title):
    """将全部主题结果缩略排版成一张便于快速比较的总览图。"""
    if not records:
        return None
    count = len(records)
    cols = 5 if count >= 13 else 4 if count >= 7 else 3 if count >= 4 else count
    rows = math.ceil(count / cols)
    margin, gap_x, gap_y = 30, 18, 22
    thumb_w = 190
    thumb_h = round(thumb_w * H / W)
    label_h, header_h = 58, 104
    cell_w, cell_h = thumb_w, thumb_h + label_h
    sheet_w = margin * 2 + cols * cell_w + (cols - 1) * gap_x
    sheet_h = header_h + margin + rows * cell_h + (rows - 1) * gap_y + margin

    canvas = Image.new("RGB", (sheet_w, sheet_h), "#EEF1F6")
    draw = ImageDraw.Draw(canvas)
    title_font = get_font(30, bold=True)
    sub_font = get_font(17)
    label_font = get_font(17, bold=True)
    version_font = get_font(14)
    draw.text((margin, 22), title, font=title_font, fill="#223044")
    draw.text((margin, 65), "共 {} 张｜同目录 HTML 可点击查看完整大图".format(count), font=sub_font, fill="#637086")

    for index, record in enumerate(records):
        row, col = divmod(index, cols)
        x = margin + col * (cell_w + gap_x)
        y = header_h + margin + row * (cell_h + gap_y)
        draw.rounded_rectangle((x-5, y-5, x+cell_w+5, y+cell_h+5), radius=12, fill="#FFFFFF", outline="#CFD6E2", width=2)
        with Image.open(record["path"]) as opened:
            thumb = opened.convert("RGB")
            thumb.thumbnail((thumb_w, thumb_h), Image.Resampling.LANCZOS)
        canvas.paste(thumb, (x + (thumb_w-thumb.width)//2, y + (thumb_h-thumb.height)//2))
        theme_text = "{} / {}".format(record["theme_name"], record["variant_name"])
        version_text = "{} · v{}".format(record["theme_id"], record["theme_version"])
        f = label_font
        if draw.textbbox((0, 0), theme_text, font=f)[2] > thumb_w - 14:
            f = get_font(14, bold=True)
        draw.text((x+7, y+thumb_h+7), theme_text, font=f, fill="#263449")
        draw.text((x+7, y+thumb_h+34), version_text, font=version_font, fill="#778397")

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out_path, "JPEG", quality=91, optimize=True)
    return out_path


def build_preview_html(records, out_path, title, contact_sheet_path=None):
    """生成无需服务器的本地响应式预览图库。"""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cards = []
    for record in records:
        rel = Path(record["path"]).resolve().relative_to(out_path.parent.resolve()).as_posix()
        cards.append(
            '<article class="card"><a href="{src}" target="_blank"><img loading="lazy" src="{src}" alt="{label}"></a>'
            '<div class="meta"><strong>{theme}</strong><span>{variant}</span><small>{theme_id} · v{version}</small></div></article>'.format(
                src=html.escape(rel, quote=True), label=html.escape(_preview_label(record), quote=True),
                theme=html.escape(str(record["theme_name"])), variant=html.escape(str(record["variant_name"])),
                theme_id=html.escape(str(record["theme_id"])), version=html.escape(str(record["theme_version"])),
            )
        )
    contact_link = ""
    if contact_sheet_path:
        rel_contact = Path(contact_sheet_path).resolve().relative_to(out_path.parent.resolve()).as_posix()
        contact_link = '<a class="button" href="{}" target="_blank">打开总览拼图</a>'.format(html.escape(rel_contact, quote=True))
    document = """<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title><style>:root{{color-scheme:dark}}*{{box-sizing:border-box}}body{{margin:0;background:#0d111b;color:#edf2ff;font-family:"Microsoft YaHei","PingFang SC",sans-serif}}header{{position:sticky;top:0;z-index:3;padding:20px 28px;background:rgba(13,17,27,.94);backdrop-filter:blur(12px);border-bottom:1px solid #293247}}h1{{margin:0 0 8px;font-size:25px}}p{{margin:0;color:#aeb8cd}}.button{{display:inline-block;margin-top:12px;padding:8px 13px;border-radius:8px;background:#6678df;color:white;text-decoration:none}}main{{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:22px;padding:26px}}.card{{overflow:hidden;border:1px solid #2b354b;border-radius:13px;background:#171d2a;box-shadow:0 8px 24px rgba(0,0,0,.28)}}.card a{{display:block;background:#080b12}}.card img{{display:block;width:100%;height:auto}}.meta{{display:grid;gap:4px;padding:13px 14px 15px}}.meta strong{{font-size:17px}}.meta span{{color:#c8d0e3}}.meta small{{color:#7f8aa1}}@media(max-width:520px){{main{{padding:14px;gap:14px}}header{{padding:16px}}}}</style></head><body><header><h1>{title}</h1><p>共 {count} 张。点击任意图片查看完整尺寸。</p>{contact}</header><main>{cards}</main></body></html>""".format(title=html.escape(title), count=len(records), contact=contact_link, cards="\n".join(cards))
    out_path.write_text(document, encoding="utf-8")
    return out_path

def build_excel_preview_html(sheet_data, out_path, excel_name):
    """
    为整个 Excel 生成一个可切换查看不同攻略图（Sheet）的 HTML 预览。
    """
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    def _make_rel(path_str, base_path):
        """计算相对路径；兼容路径不在子目录下的情况（如旧版残留记录）。"""
        try:
            return Path(path_str).resolve().relative_to(base_path.resolve()).as_posix()
        except ValueError:
            import os
            return os.path.relpath(
                str(Path(path_str).resolve()), str(base_path.resolve())
            ).replace("\\", "/")

    tabs_html = []
    panels_html = []

    for idx, (sheet_name, data) in enumerate(sheet_data.items()):
        sheet_id = "sheet-" + str(idx)
        is_first = (idx == 0)

        tab_class = "sheet-tab active" if is_first else "sheet-tab"
        tabs_html.append(
            '<button class="' + tab_class + '" id="tab-' + sheet_id + '" data-sheet="' + sheet_id + '" '
            'onclick="switchSheet(&#39;' + sheet_id + '&#39;)">' + html.escape(sheet_name) + '</button>'
        )

        records = data.get("records", [])
        contact_path = data.get("contact_sheet")

        cards = []
        for record in records:
            rel = _make_rel(record["path"], out_path.parent)
            cards.append(
                '<article class="card"><a href="' + html.escape(rel, quote=True) + '" target="_blank">'
                '<img loading="lazy" src="' + html.escape(rel, quote=True) + '" alt="'
                + html.escape(_preview_label(record), quote=True) + '"></a>'
                '<div class="meta"><strong>' + html.escape(str(record.get("theme_name", ""))) + '</strong>'
                '<span>' + html.escape(str(record.get("variant_name", ""))) + '</span>'
                '<small>' + html.escape(str(record.get("theme_id", ""))) + ' · v'
                + html.escape(str(record.get("theme_version", ""))) + '</small></div></article>'
            )

        contact_link = ""
        if contact_path and Path(contact_path).exists():
            rel_contact = _make_rel(contact_path, out_path.parent)
            contact_link = (
                '<a class="contact-link" href="' + html.escape(rel_contact, quote=True) + '" target="_blank">'
                '打开总览拼图</a>'
            )

        panel_class = "sheet-panel active" if is_first else "sheet-panel"
        cards_html = "".join(cards) if cards else '<div class="empty-state">该攻略图没有成功生成任何主题预览</div>'

        panel_html = (
            '<div class="' + panel_class + '" id="panel-' + sheet_id + '">\n'
            '    <div class="panel-header">\n'
            '        <div>\n'
            '            <div class="panel-title">' + html.escape(sheet_name) + '</div>\n'
            '            <div class="panel-meta">共 ' + str(len(records)) + ' 种主题效果</div>\n'
            '        </div>\n'
            '        ' + contact_link + '\n'
            '    </div>\n'
            '    <div class="card-grid">\n'
            '        ' + cards_html + '\n'
            '    </div>\n'
            '</div>'
        )
        panels_html.append(panel_html)

    total_sheets = len(sheet_data)
    total_variants = sum(d.get("count", 0) for d in sheet_data.values())
    js_excel_name = json.dumps(excel_name, ensure_ascii=False)

    lines = [
        '<!doctype html>',
        '<html lang="zh-CN">',
        '<head>',
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width,initial-scale=1">',
        '<title>' + html.escape(excel_name) + ' | 攻略图全主题预览</title>',
        '<style>',
        ':root{color-scheme:dark}',
        '*{box-sizing:border-box;margin:0;padding:0}',
        'body{margin:0;background:#0d111b;color:#edf2ff;font-family:"Microsoft YaHei","PingFang SC",sans-serif;min-height:100vh}',
        'header{position:sticky;top:0;z-index:10;padding:20px 28px;background:rgba(13,17,27,0.94);backdrop-filter:blur(12px);border-bottom:1px solid #293247}',
        'h1{margin:0 0 8px;font-size:25px}',
        '.subtitle{color:#aeb8cd;margin:0}',
        '.sheet-nav{display:flex;gap:8px;padding:16px 28px;background:rgba(13,17,27,0.6);border-bottom:1px solid #1e2535;overflow-x:auto;flex-wrap:wrap}',
        '.sheet-tab{padding:8px 18px;border-radius:8px;background:#1a2030;border:1px solid #2b354b;color:#8b95a8;cursor:pointer;font-size:14px;transition:all 0.2s;white-space:nowrap}',
        '.sheet-tab:hover{background:#252d42;color:#c8d0e3}',
        '.sheet-tab.active{background:#6678df;color:white;border-color:#6678df}',
        'main{padding:26px 28px}',
        '.sheet-panel{display:none}',
        '.sheet-panel.active{display:block}',
        '.panel-header{display:flex;align-items:center;justify-content:space-between;margin-bottom:20px;flex-wrap:wrap;gap:12px}',
        '.panel-title{font-size:20px;color:#c8d0e3}',
        '.panel-meta{color:#7f8aa1;font-size:14px;margin-top:4px}',
        '.contact-link{display:inline-flex;align-items:center;gap:6px;padding:6px 14px;border-radius:6px;background:#1a2030;border:1px solid #2b354b;color:#8b95a8;text-decoration:none;font-size:13px;transition:all 0.2s}',
        '.contact-link:hover{background:#252d42;color:#c8d0e3}',
        '.card-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:22px}',
        '.card{overflow:hidden;border:1px solid #2b354b;border-radius:13px;background:#171d2a;box-shadow:0 8px 24px rgba(0,0,0,0.28);transition:transform 0.2s,box-shadow 0.2s}',
        '.card:hover{transform:translateY(-2px);box-shadow:0 12px 32px rgba(0,0,0,0.4)}',
        '.card a{display:block;background:#080b12}',
        '.card img{display:block;width:100%;height:auto}',
        '.meta{display:grid;gap:4px;padding:13px 14px 15px}',
        '.meta strong{font-size:17px;color:#edf2ff}',
        '.meta span{color:#c8d0e3}',
        '.meta small{color:#7f8aa1}',
        '.empty-state{text-align:center;padding:60px 20px;color:#5f6670}',
        '@media(max-width:520px){main{padding:14px}header{padding:16px}.sheet-nav{padding:12px 16px}.card-grid{gap:14px}.panel-header{flex-direction:column;align-items:flex-start}}',
        '</style>',
        '</head>',
        '<body>',
        '<header>',
        '<h1>' + html.escape(excel_name) + '</h1>',
        '<p class="subtitle">共 ' + str(total_sheets) + ' 张攻略图 · ' + str(total_variants) + ' 种主题效果 · 点击标签切换查看</p>',
        '</header>',
        '<nav class="sheet-nav">',
    ]
    lines.extend(tabs_html)
    lines.append('</nav>')
    lines.append('<main>')
    lines.extend(panels_html)
    lines.append('</main>')
    lines.append('<script>')
    lines.append('function switchSheet(sheetId) {')
    lines.append('  document.querySelectorAll(".sheet-tab").forEach(t => t.classList.remove("active"));')
    lines.append('  document.querySelectorAll(".sheet-panel").forEach(p => p.classList.remove("active"));')
    lines.append('  document.getElementById("tab-" + sheetId).classList.add("active");')
    lines.append('  document.getElementById("panel-" + sheetId).classList.add("active");')
    lines.append('  localStorage.setItem("lastSheet_" + ' + js_excel_name + ', sheetId);')
    lines.append('}')
    lines.append('(function() {')
    lines.append('  var key = "lastSheet_" + ' + js_excel_name + ';')
    lines.append('  var last = localStorage.getItem(key);')
    lines.append('  var tabs = document.querySelectorAll(".sheet-tab");')
    lines.append('  if (last && document.getElementById("tab-" + last)) {')
    lines.append('    switchSheet(last);')
    lines.append('  } else if (tabs.length > 0) {')
    lines.append('    switchSheet(tabs[0].dataset.sheet);')
    lines.append('  }')
    lines.append('})();')
    lines.append('</script>')
    lines.append('</body>')
    lines.append('</html>')

    document = "\n".join(lines)
    out_path.write_text(document, encoding="utf-8")
    return out_path



# -----------------------------------------------------------------------------
# 全主题预览：持久化增量渲染缓存
# -----------------------------------------------------------------------------

_RENDER_DEPENDENCY_SUFFIXES = {
    ".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff",
    ".ttf", ".otf", ".ttc", ".json", ".jsonc",
}


def _stable_cache_value(value):
    """把配置整理成可稳定 JSON 化的值；运行时私有键（_xxx）不参与签名。"""
    if isinstance(value, dict):
        return {
            str(k): _stable_cache_value(v)
            for k, v in sorted(value.items(), key=lambda item: str(item[0]))
            if not str(k).startswith("_")
        }
    if isinstance(value, (list, tuple)):
        return [_stable_cache_value(v) for v in value]
    if isinstance(value, set):
        return sorted((_stable_cache_value(v) for v in value), key=lambda x: repr(x))
    if isinstance(value, Path):
        return str(value)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _json_digest(value):
    payload = json.dumps(
        _stable_cache_value(value), ensure_ascii=False,
        sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


@lru_cache(maxsize=1024)
def _file_digest_cached(path_text, mtime_ns, size_bytes):
    """同一进程内相同版本文件只做一次内容 SHA256。"""
    h = hashlib.sha256()
    with open(path_text, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _file_digest(path):
    path = Path(path).resolve()
    try:
        st = path.stat()
    except OSError:
        return None
    if not path.is_file():
        return None
    return _file_digest_cached(str(path), int(st.st_mtime_ns), int(st.st_size))


def _cache_path_label(path):
    """缓存里优先保存相对工程根目录的路径，避免无意义的绝对路径噪声。"""
    path = Path(path).resolve()
    root = program_root_dir().resolve()
    try:
        return str(path.relative_to(root)).replace("\\", "/")
    except Exception:
        return str(path).replace("\\", "/")


def _fingerprint_files(paths):
    result = []
    seen = set()
    for raw in paths:
        if not raw:
            continue
        try:
            p = Path(raw).resolve()
        except Exception:
            continue
        key = str(p)
        if key in seen:
            continue
        seen.add(key)
        digest = _file_digest(p)
        result.append({
            "path": _cache_path_label(p),
            "sha256": digest or "MISSING",
        })
    result.sort(key=lambda item: item["path"])
    return result


def _iter_dependency_path_strings(value):
    """从配置中提取看起来像素材/字体/JSON 文件的路径字符串。"""
    if isinstance(value, dict):
        for k, v in value.items():
            if str(k).startswith("_"):
                continue
            yield from _iter_dependency_path_strings(v)
        return
    if isinstance(value, (list, tuple, set)):
        for v in value:
            yield from _iter_dependency_path_strings(v)
        return
    if not isinstance(value, str):
        return
    raw = value.strip().replace("\\", "/")
    if not raw or len(raw) > 1024:
        return
    try:
        suffix = Path(raw).suffix.lower()
    except Exception:
        return
    if suffix in _RENDER_DEPENDENCY_SUFFIXES:
        yield raw


def _resolve_cache_dependency(raw_path, cfg=None, theme_dir=None):
    """按 renderer 实际常用根目录解析一个配置素材路径；不存在时返回 None。"""
    raw = str(raw_path or "").strip().replace("\\", "/")
    if not raw:
        return None
    p = Path(raw)
    if p.is_absolute():
        return p.resolve() if p.exists() else None

    roots = []
    for candidate in [
        program_root_dir(),
        Path(theme_dir) if theme_dir else None,
        Path(cfg.get("_activity_config_dir")) if isinstance(cfg, dict) and cfg.get("_activity_config_dir") else None,
        Path(cfg.get("_workbook_dir")) if isinstance(cfg, dict) and cfg.get("_workbook_dir") else None,
        Path(cfg.get("_config_dir")) if isinstance(cfg, dict) and cfg.get("_config_dir") else None,
        Path(cfg.get("_script_dir")) if isinstance(cfg, dict) and cfg.get("_script_dir") else None,
    ]:
        if candidate is not None and candidate not in roots:
            roots.append(candidate)
    for root in roots:
        try:
            candidate = (root / p).resolve()
            if candidate.is_file():
                return candidate
        except Exception:
            pass

    # 与主程序 resolve_path 的兼容逻辑保持一致；它还支持文件名递归兜底。
    if isinstance(cfg, dict):
        try:
            found = resolve_path(cfg, raw)
            if found and Path(found).is_file():
                return Path(found).resolve()
        except Exception:
            pass
    return None


def _config_dependency_fingerprints(value, cfg=None, theme_dir=None):
    """配置路径既记录原始声明，也记录解析后的文件内容，文件新增/替换均会失效。"""
    result = []
    seen_raw = set()
    for raw in _iter_dependency_path_strings(value):
        if raw in seen_raw:
            continue
        seen_raw.add(raw)
        resolved = _resolve_cache_dependency(raw, cfg=cfg, theme_dir=theme_dir)
        result.append({
            "declared": raw,
            "resolved": _cache_path_label(resolved) if resolved else "MISSING",
            "sha256": _file_digest(resolved) if resolved else "MISSING",
        })
    result.sort(key=lambda item: item["declared"])
    return result


def _relative_import_path(source_path, level, module_name, alias_name=None):
    """把 renderer 内的相对 import 尽量解析到同工程 .py 文件。"""
    source_path = Path(source_path).resolve()
    base = source_path.parent
    for _ in range(max(0, int(level or 0) - 1)):
        base = base.parent
    parts = [p for p in str(module_name or "").split(".") if p]
    if not parts and alias_name:
        parts = [p for p in str(alias_name).split(".") if p]
    if not parts:
        return None
    candidate = base.joinpath(*parts)
    py_file = candidate.with_suffix(".py")
    if py_file.is_file():
        return py_file.resolve()
    init_file = candidate / "__init__.py"
    if init_file.is_file():
        return init_file.resolve()
    return None


def _renderer_python_dependencies(style):
    """递归收集当前 renderer 自己实际 import 的 renderers/*.py 依赖。"""
    from renderers.registry import get_renderer

    renderer = get_renderer(style) or get_renderer("classic_cards")
    if renderer is None:
        return []
    try:
        first = Path(inspect.getsourcefile(renderer) or inspect.getfile(renderer)).resolve()
    except Exception:
        return []

    renderers_root = (program_root_dir() / "renderers").resolve()
    pending = [first]
    seen = set()
    result = []
    while pending:
        path = Path(pending.pop()).resolve()
        if str(path) in seen or not path.is_file():
            continue
        try:
            path.relative_to(renderers_root)
        except Exception:
            continue
        seen.add(str(path))
        result.append(path)
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except Exception:
            continue
        for node in ast.walk(tree):
            target = None
            if isinstance(node, ast.ImportFrom):
                if node.level:
                    if node.module:
                        target = _relative_import_path(path, node.level, node.module)
                        if target:
                            pending.append(target)
                    else:
                        for alias in node.names:
                            target = _relative_import_path(path, node.level, None, alias.name)
                            if target:
                                pending.append(target)
                elif node.module and node.module.startswith("renderers."):
                    target = program_root_dir() / (node.module.replace(".", "/") + ".py")
                    if target.is_file():
                        pending.append(target.resolve())
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith("renderers."):
                        target = program_root_dir() / (alias.name.replace(".", "/") + ".py")
                        if target.is_file():
                            pending.append(target.resolve())

    # registry/services 属于所有 renderer 的公共调用链，也参与失效判断。
    for common in [
        renderers_root / "registry.py",
        renderers_root / "services.py",
        renderers_root / "__init__.py",
    ]:
        if common.is_file() and str(common.resolve()) not in seen:
            result.append(common.resolve())
    return result


def _theme_config_source_files(selection):
    """基础 theme/manifest 影响全部变体；当前 variant JSON 只影响当前变体。"""
    result = []
    theme_dir = Path(selection.get("theme_dir") or "")
    if not theme_dir.is_dir():
        return result
    for name in ["manifest.json", "theme.json"]:
        p = theme_dir / name
        if p.is_file():
            result.append(p)
    variant_id = clean(str(selection.get("variant_id") or ""))
    if variant_id:
        p = theme_dir / "variants" / (variant_id + ".json")
        if p.is_file():
            result.append(p)
    return result


def _workbook_render_style_digest(z):
    """Excel 样式/主题会影响文字与奖励底色；这些属于工作簿级公共依赖。"""
    h = hashlib.sha256()
    for name in ["xl/styles.xml", "xl/theme/theme1.xml"]:
        h.update(name.encode("utf-8"))
        try:
            h.update(z.read(name))
        except Exception:
            h.update(b"MISSING")
    return h.hexdigest()


def _sheet_render_digest(values, styles, rich, workbook_style_digest, tier_progress_by_row=None):
    return _json_digest({
        "values": values,
        "styles": styles,
        "rich": rich,
        "workbook_style": workbook_style_digest,
        "tier_progress": tier_progress_by_row or {},
    })


def _theme_render_signature(sheet_digest, selection, cfg):
    """构建单一 Sheet + Theme + Variant 的精确渲染签名。"""
    style = clean(str(((selection.get("config") or {}).get("renderer") or {}).get("style") or "classic_cards"))
    theme_dir = selection.get("theme_dir")

    global_source_files = [Path(__file__).resolve()]
    theme_system_path = program_root_dir() / "theme_system.py"
    if theme_system_path.is_file():
        global_source_files.append(theme_system_path)

    payload = {
        "schema": RENDER_CACHE_SCHEMA,
        "engine_version": ENGINE_VERSION,
        "sheet_digest": sheet_digest,
        "global_sources": _fingerprint_files(global_source_files),
        "renderer_sources": _fingerprint_files(_renderer_python_dependencies(style)),
        "theme_sources": _fingerprint_files(_theme_config_source_files(selection)),
        "selection": {
            "theme_id": selection.get("theme_id"),
            "theme_name": selection.get("theme_name"),
            "theme_version": selection.get("theme_version"),
            "variant_id": selection.get("variant_id"),
            "variant_name": selection.get("variant_name"),
            "config": selection.get("config") or {},
            "palette": selection.get("palette") or {},
        },
        "theme_assets": _config_dependency_fingerprints(
            selection.get("config") or {}, cfg=cfg, theme_dir=theme_dir
        ),
        "global_config": _stable_cache_value(cfg),
        "global_config_assets": _config_dependency_fingerprints(cfg, cfg=cfg),
    }
    return _json_digest(payload)


def _render_cache_path(base_out_dir):
    return Path(base_out_dir) / "render_cache.json"


def load_render_cache(base_out_dir):
    """读取全主题预览成品缓存；损坏/旧版本自动按空缓存处理。"""
    path = _render_cache_path(base_out_dir)
    if not path.exists():
        return {"schema": RENDER_CACHE_SCHEMA, "entries": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if int(data.get("schema", -1)) != RENDER_CACHE_SCHEMA:
            return {"schema": RENDER_CACHE_SCHEMA, "entries": {}}
        entries = data.get("entries")
        if not isinstance(entries, dict):
            entries = {}
        return {"schema": RENDER_CACHE_SCHEMA, "entries": entries}
    except Exception:
        return {"schema": RENDER_CACHE_SCHEMA, "entries": {}}


def save_render_cache(base_out_dir, cache):
    """原子保存渲染缓存，避免中断时留下半截 JSON。"""
    path = _render_cache_path(base_out_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": RENDER_CACHE_SCHEMA,
        "entries": (cache or {}).get("entries", {}),
    }
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _render_cache_key(sheet_name, selection):
    return "{}\n{}\n{}".format(
        str(sheet_name),
        str(selection.get("theme_id") or ""),
        str(selection.get("variant_id") or ""),
    )


def _cached_output_is_valid(entry, signature, out_path):
    if not isinstance(entry, dict) or entry.get("signature") != signature:
        return False
    out_path = Path(out_path)
    if not out_path.is_file():
        return False
    try:
        st = out_path.stat()
    except OSError:
        return False
    if int(st.st_size) <= 0:
        return False
    if entry.get("path") and str(Path(entry.get("path")).resolve()) != str(out_path.resolve()):
        return False
    cached_size = entry.get("output_size")
    cached_mtime = entry.get("output_mtime_ns")
    if cached_size is not None and int(cached_size) != int(st.st_size):
        return False
    if cached_mtime is not None and int(cached_mtime) != int(st.st_mtime_ns):
        return False
    return True


def _update_render_cache_entry(cache, key, signature, out_path):
    out_path = Path(out_path).resolve()
    st = out_path.stat()
    cache.setdefault("entries", {})[key] = {
        "signature": signature,
        "path": str(out_path),
        "output_size": int(st.st_size),
        "output_mtime_ns": int(st.st_mtime_ns),
    }


def _preview_index_path(base_out_dir):
    return Path(base_out_dir) / "preview_index.json"


def load_preview_index(base_out_dir):
    """读取已存在的预览索引；没有则返回空字典。"""
    path = _preview_index_path(base_out_dir)
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_preview_index(base_out_dir, index):
    """保存预览索引到 JSON。"""
    path = _preview_index_path(base_out_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=2)


def rebuild_excel_preview_html(base_out_dir, excel_name):
    """根据 preview_index.json 重建统一 HTML；没有索引则跳过。"""
    index = load_preview_index(base_out_dir)
    if not index:
        return None
    sheet_data = {}
    for sheet_name, data in index.items():
        sheet_data[sheet_name] = {
            "records": data.get("records", []),
            "contact_sheet": data.get("contact_sheet"),
            "count": data.get("count", 0),
        }
    out_path = Path(base_out_dir) / "打开全主题预览.html"
    return build_excel_preview_html(sheet_data, out_path, excel_name)

def process_book_theme_preview(book: Path, selected_sheet_names=None, theme_id=None):
    """一次生成全部主题/变体；未变化的成品直接命中持久化增量缓存。"""
    base_out_dir = output_directory_for_book(book)
    base_out_dir.mkdir(parents=True, exist_ok=True)
    cfg = load_config_for_book(book)
    apply_font_config(cfg)
    selections = all_theme_selections(theme_id=theme_id)
    if not selections:
        raise ThemeError("没有可用于预览的主题或配色变体")

    preview_index = load_preview_index(base_out_dir)
    render_cache = load_render_cache(base_out_dir)

    with zipfile.ZipFile(book, "r") as z:
        targets = workbook_sheet_targets(z)
        theme_colors = read_theme_colors(z)
        shared = read_shared_strings(z, theme_colors)
        fills, xfs, parsed_fonts = read_styles(z, theme_colors)
        workbook_style_digest = _workbook_render_style_digest(z)
        target_sheets = sorted([(n, p) for n, p in targets.items() if KEYWORD in n], key=guide_sheet_sort_key)
        if selected_sheet_names is not None:
            wanted = set(selected_sheet_names)
            target_sheets = [item for item in target_sheets if item[0] in wanted]
        if not target_sheets:
            print(f"[跳过] {book.name}：没有选中的'{KEYWORD}'工作表")
            return 0, 0

        total_ok = 0
        total_expected = len(target_sheets) * len(selections)
        total_cache_hits = 0
        total_rerendered = 0

        for sheet_seq, (sheet_name, sheet_path) in enumerate(target_sheets, 1):
            print("\n全主题预览：{}【{}/{}】共 {} 种效果".format(
                sheet_name, sheet_seq, len(target_sheets), len(selections)
            ))
            values, styles, rich = read_sheet(z, sheet_path, shared, theme_colors, xfs, parsed_fonts)
            tier_progress_by_row = read_day_tier_progress_context(
                z, sheet_path, values, shared, theme_colors, xfs, parsed_fonts
            )
            sheet_digest = _sheet_render_digest(
                values, styles, rich, workbook_style_digest, tier_progress_by_row
            )
            sheet_dir = base_out_dir / safe_filename(sheet_name)
            sheet_dir.mkdir(parents=True, exist_ok=True)
            records = []
            sheet_cache_hits = 0
            sheet_rerendered = 0

            for index, selection in enumerate(selections, 1):
                try:
                    theme_folder = sheet_dir / safe_filename(
                        "{}_v{}".format(selection["theme_name"], selection["theme_version"])
                    )
                    theme_folder.mkdir(parents=True, exist_ok=True)
                    out = theme_folder / "{:02d}_{}.png".format(
                        index, safe_filename(selection["variant_name"])
                    )

                    signature = _theme_render_signature(sheet_digest, selection, cfg)
                    cache_key = _render_cache_key(sheet_name, selection)
                    cache_entry = (render_cache.get("entries") or {}).get(cache_key)

                    record = {
                        "path": str(out.resolve()),
                        "theme_id": selection["theme_id"],
                        "theme_name": selection["theme_name"],
                        "theme_version": selection["theme_version"],
                        "variant_id": selection["variant_id"],
                        "variant_name": selection["variant_name"],
                    }

                    if _cached_output_is_valid(cache_entry, signature, out):
                        records.append(record)
                        total_ok += 1
                        total_cache_hits += 1
                        sheet_cache_hits += 1
                        print("  [{:02d}/{:02d}] [缓存] {} v{} / {}".format(
                            index, len(selections),
                            selection["theme_name"], selection["theme_version"],
                            selection["variant_name"]
                        ))
                        continue

                    guide = parse_guide(
                        sheet_name, values, styles, rich,
                        fills, xfs, parsed_fonts, selection, cfg,
                        tier_progress_by_row=tier_progress_by_row
                    )
                    render(guide, out)
                    _update_render_cache_entry(render_cache, cache_key, signature, out)
                    records.append(record)
                    total_ok += 1
                    total_rerendered += 1
                    sheet_rerendered += 1
                    print("  [{:02d}/{:02d}] [生成] {} v{} / {}".format(
                        index, len(selections),
                        selection["theme_name"], selection["theme_version"],
                        selection["variant_name"]
                    ))
                except Exception as exc:
                    print("  [失败] {} / {}：{}".format(
                        selection.get("theme_name"), selection.get("variant_name"), exc
                    ))

            # 每个 sheet 完成后先落盘缓存；中途退出也不会丢掉已经成功的结果。
            save_render_cache(base_out_dir, render_cache)

            contact = None
            if records:
                title = "{}｜{}｜全主题效果预览".format(book.stem, sheet_name)
                contact = build_preview_contact_sheet(
                    records, sheet_dir / "00_全主题总览.jpg", title
                )
                print("  总览拼图：{}".format(contact))

            print("  缓存命中：{}；重新生成：{}".format(sheet_cache_hits, sheet_rerendered))

            # 合并到 preview_index：已有记录保留，同 theme+variant 替换，新记录追加
            existing = preview_index.get(sheet_name, {"records": [], "contact_sheet": None, "count": 0})
            existing_records = existing.get("records", [])
            for new_record in records:
                dup_idx = None
                for i, r in enumerate(existing_records):
                    if (r.get("theme_id") == new_record["theme_id"] and
                        r.get("variant_id") == new_record["variant_id"]):
                        dup_idx = i
                        break
                if dup_idx is not None:
                    existing_records[dup_idx] = new_record
                else:
                    existing_records.append(new_record)
            preview_index[sheet_name] = {
                "records": existing_records,
                "contact_sheet": str(contact.resolve()) if contact else (existing.get("contact_sheet") or None),
                "count": len(existing_records),
            }
            save_preview_index(base_out_dir, preview_index)

            html_path = rebuild_excel_preview_html(base_out_dir, book.stem)
            if html_path:
                print("  统一 HTML 预览：{}".format(html_path))

        print("\n[增量缓存] 命中 {} 张；实际重新生成 {} 张。".format(total_cache_hits, total_rerendered))
        return total_ok, total_expected


def prompt_generation_mode():
    rows = ["正常生成：逐张手动选择主题与配色", "全主题预览：生成所有已安装主题及全部配色", "单主题预览：一次生成所选主题的全部配色"]
    return _prompt_number("请选择生成方式：", rows, "请输入生成方式编号：")

def default_excel_directory():
    """返回双击运行时的默认 Excel/JSON 输入目录，并确保目录存在。"""
    folder = Path(__file__).resolve().parent / INPUT_DIR_NAME
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def find_books_for_double_click():
    """只扫描 excel 文件夹中的 Excel；命令行仍可传入任意路径。"""
    base = default_excel_directory()
    allowed = {".xlsx", ".xlsm"}
    return sorted(
        (p for p in base.iterdir() if p.is_file() and p.suffix.lower() in allowed and not p.name.startswith("~$")),
        key=lambda p: p.name.lower(),
    )

def _parse_selection_tokens(raw, count):
    raw=clean(str(raw)).lower()
    if raw in {"", "0", "a", "all", "全部"}:
        return list(range(count))
    result=[]
    for token in re.split(r"[,，;；\s]+",raw):
        if not token:
            continue
        m=re.fullmatch(r"(\d+)\s*[-~至]\s*(\d+)",token)
        if m:
            a,b=int(m.group(1)),int(m.group(2))
            lo,hi=sorted((a,b))
            for n in range(lo,hi+1):
                if 1<=n<=count and n-1 not in result:
                    result.append(n-1)
            continue
        if token.isdigit():
            n=int(token)
            if 1<=n<=count and n-1 not in result:
                result.append(n-1)
            else:
                raise ValueError
        else:
            raise ValueError
    if not result:
        raise ValueError
    return result


def prompt_multi_select(title, items, item_label="项目"):
    print("\n"+title)
    for i,item in enumerate(items,1):
        print(f"  {i}. {item}")
    print("  0. 全部")
    print("可输入单个编号、多个编号（如 1,3）或范围（如 1-3）；直接回车等同全部。")
    while True:
        raw=input(f"请选择{item_label}：").strip()
        try:
            indices=_parse_selection_tokens(raw,len(items))
            return indices
        except ValueError:
            print("输入无效，请输入列表中的编号、逗号分隔编号、范围，或 0 表示全部。")

def variant_menu_label(variant):
    name = str(variant.get("name") or variant.get("id") or "配色")
    description = str(variant.get("description") or "").strip()
    return f"{name}（{description}）" if description else name


def _prompt_number(title, rows, prompt_text):
    print("")
    print(title)
    for index, label in enumerate(rows, 1):
        print(f"  {index}. {label}")
    print("直接回车使用第 1 项。")
    while True:
        raw = input(prompt_text).strip()
        if raw == "":
            return 0
        try:
            value = int(raw)
        except ValueError:
            print(f"请输入 1~{len(rows)}。")
            continue
        if 1 <= value <= len(rows):
            return value - 1
        print(f"请输入 1~{len(rows)}。")


def prompt_theme_selection(label=None, fixed_theme_id=None, fixed_variant_id=None, legacy_color=None):
    """手动或命令行明确选择主题与配色；不再根据标题自动选色。"""
    manager = get_theme_manager()

    if legacy_color is not None:
        return manager.resolve_legacy_color(int(legacy_color))

    if fixed_theme_id:
        theme = manager.get(fixed_theme_id)
    elif len(manager.themes) == 1:
        theme = manager.themes[0]
    else:
        rows = [f"{t.name} [{t.id}]" for t in manager.themes]
        title = f"请选择 {label} 的主题：" if label else "请选择主题："
        theme = manager.themes[_prompt_number(title, rows, "请输入主题编号：")]

    if fixed_variant_id:
        return theme.resolve(fixed_variant_id)

    if len(theme.variants) == 1:
        return theme.resolve(theme.variants[0]["id"])

    if label:
        title = f"请选择 {label} 的配色（主题：{theme.name}）："
    else:
        title = f"请选择配色（主题：{theme.name}）："
    rows = [variant_menu_label(v) for v in theme.variants]
    variant = theme.variants[_prompt_number(title, rows, "请输入配色编号：")]
    return theme.resolve(variant["id"])


def interactive_post_run():
    print("")
    print("接下来你可以继续输入指令：")
    print("  1 = 重新选择攻略图与生成方式")
    print("  2 = 重新加载 JSON / 主题配置，并按刚才选择立即重新生成")
    print("  3 = 重新扫描 excel 文件夹并重新选择")
    print("  4 = 退出")
    print("")
    while True:
        cmd = input("请输入 1 / 2 / 3 / 4：").strip()
        if cmd in {"1", "2", "3", "4"}:
            return cmd
        print("请输入 1 / 2 / 3 / 4。")


def reload_runtime_configuration():
    """强制刷新运行期间可修改的配置。

    config.json 与活动 JSON 本身会在 process_book() 每次调用时重新读取；
    这里另外刷新 ThemeManager，使 theme.json / variants / manifest 的变化也能
    在同一个 Python 进程里立刻生效。Python renderer 源码本身不在这里热重载。
    """
    try:
        manager = get_theme_manager(require_themes=False)
        manager.reload()
        print("[已刷新] theme.json / variant / manifest；config.json 与活动 JSON 将在生成时重新读取。")
    except Exception as exc:
        print(f"[配置刷新警告] {exc}")

def print_cli_help():
    script_name = Path(__file__).name
    print(f"攻略图生成器 V{ENGINE_VERSION}（themes 目录版）")
    print("")
    print(f"用法：python {script_name} [选项] Excel文件...")
    print("")
    print("主题选项：")
    print("  --theme, -t ID         固定主题 ID")
    print("  --variant, -v ID       固定主题内的配色变体 ID")
    print("  --color, -c 1~8        兼容旧版配色编号；编号由主题包声明")
    print("  --list-themes          查看已安装主题与变体")
    print("  --preview-all-themes   为每张攻略图生成全部主题及全部配色预览")
    print("  --preview-theme ID     为每张攻略图生成指定主题的全部配色预览")
    print("")
    print("未指定主题或变体时，程序会逐张手动询问；不再自动选色。")


def main():
    global RUNTIME_THEME_ID, RUNTIME_VARIANT_ID, RUNTIME_LEGACY_COLOR

    args = sys.argv[1:]
    theme_arg = None
    variant_arg = None
    color_arg = None
    list_themes = False
    preview_all_themes = False
    preview_theme_id = None
    show_help = False
    book_args = []

    i = 0
    while i < len(args):
        arg = args[i]
        if arg in {"--theme", "-t"} and i + 1 < len(args):
            theme_arg = args[i + 1].strip()
            i += 2
            continue
        if arg in {"--variant", "-v"} and i + 1 < len(args):
            variant_arg = args[i + 1].strip()
            i += 2
            continue
        if arg in {"--color", "-c"} and i + 1 < len(args):
            try:
                color_arg = int(args[i + 1])
            except ValueError:
                print("--color 必须是主题包声明的正整数编号。")
                return 2
            i += 2
            continue
        if arg == "--preview-all-themes":
            preview_all_themes = True
            i += 1
            continue
        if arg == "--preview-theme" and i + 1 < len(args):
            preview_theme_id = args[i + 1].strip()
            i += 2
            continue
        if arg == "--list-themes":
            list_themes = True
            i += 1
            continue
        if arg in {"--help", "-h"}:
            show_help = True
            i += 1
            continue
        if arg.startswith("-"):
            print(f"未知选项：{arg}")
            print_cli_help()
            return 2
        book_args.append(arg)
        i += 1

    manager = get_theme_manager(require_themes=False)
    print(f"攻略图生成器 V{ENGINE_VERSION}")
    if manager.themes:
        print("已加载主题：" + "；".join(f"{t.name} [{t.id}] v{t.version}" for t in manager.themes))
    else:
        print("已加载主题：无")
    print("")
    if manager.errors:
        for error in manager.errors:
            print(f"[主题警告] {error}")

    if show_help:
        print_cli_help()
        return 0

    if list_themes:
        print("已安装主题：")
        for line in manager.list_lines():
            print("  " + line)
        if not book_args:
            return 0

    try:
        manager.require_themes()
    except Exception as exc:
        print(exc)
        return 2

    if preview_all_themes and preview_theme_id:
        print("--preview-all-themes 不能与 --preview-theme 同时使用。")
        return 2
    if (preview_all_themes or preview_theme_id) and (theme_arg or variant_arg or color_arg is not None):
        print("预览模式不能与 --theme / --variant / --color 同时使用。")
        return 2
    if preview_theme_id:
        try:
            manager.get(preview_theme_id)
        except Exception as exc:
            print(exc)
            return 2

    if color_arg is not None and (theme_arg or variant_arg):
        print("--color 不能与 --theme / --variant 同时使用。")
        return 2

    if preview_all_themes or preview_theme_id:
        RUNTIME_THEME_ID = None
        RUNTIME_VARIANT_ID = None
        RUNTIME_LEGACY_COLOR = None
        if preview_theme_id:
            chosen_theme = manager.get(preview_theme_id)
            print("预览模式：{} [{}] v{} 的全部配色。".format(chosen_theme.name, chosen_theme.id, chosen_theme.version))
        else:
            print("预览模式：全部已安装主题及全部配色。")
    elif color_arg is not None:
        if color_arg <= 0:
            print("自动选色已移除；--color 请输入主题包声明的正整数编号。")
            return 2
        try:
            selection = manager.resolve_legacy_color(color_arg)
        except Exception as exc:
            print(exc)
            return 2
        RUNTIME_LEGACY_COLOR = color_arg
        RUNTIME_THEME_ID = None
        RUNTIME_VARIANT_ID = None
        print(
            "命令行固定配色：{} / {}（旧编号 {}）".format(
                selection["theme_name"], selection["variant_name"], color_arg
            )
        )
    else:
        if variant_arg and not theme_arg:
            if len(manager.themes) == 1:
                theme_arg = manager.themes[0].id
            else:
                print("安装多个主题时，使用 --variant 必须同时指定 --theme。")
                return 2
        try:
            if theme_arg:
                theme = manager.get(theme_arg)
                if variant_arg:
                    theme.get_variant(variant_arg)
        except Exception as exc:
            print(exc)
            return 2
        RUNTIME_THEME_ID = theme_arg
        RUNTIME_VARIANT_ID = variant_arg
        RUNTIME_LEGACY_COLOR = None
        if theme_arg and variant_arg:
            selected = manager.resolve(theme_arg, variant_arg)
            print(f"命令行固定主题：{selected['theme_name']} / {selected['variant_name']}")
        elif theme_arg:
            print(f"命令行固定主题：{manager.get(theme_arg).name}；每张攻略图手动选择配色。")
        else:
            print("未指定主题与配色：每张攻略图均手动选择；不使用自动选色。")

    double_click = len(sys.argv) == 1

    if double_click:
        while True:
            books=find_books_for_double_click()
            if not books:
                excel_dir = default_excel_directory()
                print("excel 文件夹中没有找到 .xlsx 或 .xlsm 文件。")
                print(f"请把 Excel 和对应的同名 JSON 放入：{excel_dir}")
                input("\n按回车退出...")
                return 1

            book_indices=prompt_multi_select(
                f"excel 文件夹中共找到 {len(books)} 个 Excel 文件，请先选择要生成的 Excel：",
                [b.name for b in books],
                item_label="Excel"
            )
            selected_books=[books[i] for i in book_indices]

            plan={}
            for book in selected_books:
                sheets=list_guide_sheets(book)
                if not sheets:
                    print(f"[跳过] {book.name}：没有表名包含‘{KEYWORD}’")
                    continue
                sheet_indices=prompt_multi_select(
                    f"Excel【{book.name}】中找到 {len(sheets)} 张攻略图，请选择：",
                    [name for name,_ in sheets],
                    item_label="攻略图"
                )
                plan[book]=[sheets[i][0] for i in sheet_indices]

            if not plan:
                print("没有选中任何可生成的攻略图。")
                continue

            RUNTIME_THEME_ID = None
            RUNTIME_VARIANT_ID = None
            RUNTIME_LEGACY_COLOR = None
            generation_mode = prompt_generation_mode()
            preview_theme_choice = None
            if generation_mode == 2:
                themes = get_theme_manager().themes
                rows = ["{} [{}] v{}".format(t.name, t.id, t.version) for t in themes]
                chosen = themes[_prompt_number("请选择要预览全部配色的主题：", rows, "请输入主题编号：")]
                preview_theme_choice = chosen.id

            reuse_last_selections = False
            while True:
                total_ok=0
                total=0
                for book,sheet_names in plan.items():
                    try:
                        print(f"\n处理：{book.name}")
                        if generation_mode == 0:
                            ok,count=process_book(
                                book, selected_sheet_names=sheet_names,
                                reuse_last_selections=reuse_last_selections
                            )
                        else:
                            ok,count=process_book_theme_preview(
                                book, selected_sheet_names=sheet_names,
                                theme_id=preview_theme_choice
                            )
                        total_ok+=ok
                        total+=count
                    except Exception as exc:
                        print(f"\n[失败] {book.name}")
                        print(exc)

                print("\n"+"="*58)
                print(f"完成：成功生成 {total_ok}/{total} 张攻略图效果")
                print(f"输出目录：{output_root_dir()}\\工作簿名\\")
                print("="*58)

                cmd=interactive_post_run()
                if cmd == "2":
                    print("\n正在重新加载配置，并按刚才的 Excel / 攻略图 / 主题选择重新生成……")
                    reload_runtime_configuration()
                    reuse_last_selections = True
                    continue
                if cmd in {"1", "3"}:
                    break
                return 0 if total_ok==total else 1

            # 回到最外层，重新扫描/选择 Excel 与生成方式。
            continue

    books = [Path(x).expanduser().resolve() for x in book_args]
    if not books:
        print_cli_help()
        return 2

    total_ok = 0
    total = 0
    for book in books:
        if not book.is_file():
            print(f"[跳过] 找不到：{book}")
            continue
        try:
            if preview_all_themes or preview_theme_id:
                ok, count = process_book_theme_preview(book, theme_id=preview_theme_id)
            else:
                ok, count = process_book(book)
            total_ok += ok
            total += count
        except Exception as exc:
            print(f"\n[失败] {book.name}")
            print(exc)

    print("\n" + "="*58)
    print(f"完成：成功生成 {total_ok}/{total} 张攻略图效果")
    print(f"输出目录：{output_root_dir()}\\工作簿名\\")
    print("="*58)
    return 0 if total_ok == total else 1

if __name__ == "__main__":
    raise SystemExit(main())
