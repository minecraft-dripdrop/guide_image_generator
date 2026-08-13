#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""攻略图生成器可视化编辑器。兼容 Python 3.9。"""
from __future__ import annotations

import copy
import json
import os
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Optional

try:
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox, colorchooser
    from PIL import Image, ImageTk, ImageDraw
except ImportError as exc:
    raise SystemExit("缺少 Tkinter 或 Pillow，请安装完整 Python 与 Pillow。") from exc

import guide_image_generator as engine

APP_VERSION = "33.0.0"
ROOT = Path(__file__).resolve().parent
INPUT_DIR = ROOT / engine.INPUT_DIR_NAME
OUTPUT_DIR = ROOT / engine.OUT_DIR_NAME


def _get(data, path, default=None):
    cur = data
    for key in path.split("."):
        if not isinstance(cur, dict) or key not in cur:
            return default
        cur = cur[key]
    return cur


def _set(data, path, value):
    cur = data
    parts = path.split(".")
    for key in parts[:-1]:
        nxt = cur.get(key)
        if not isinstance(nxt, dict):
            nxt = {}
            cur[key] = nxt
        cur = nxt
    cur[parts[-1]] = value


def _pair(value, default):
    if isinstance(value, (list, tuple)) and len(value) >= 2:
        try:
            return float(value[0]), float(value[1])
        except (TypeError, ValueError):
            pass
    return default


def _box(value, default):
    if isinstance(value, (list, tuple)) and len(value) >= 4:
        try:
            return tuple(float(x) for x in value[:4])
        except (TypeError, ValueError):
            pass
    return default


def _json_clone(value):
    return json.loads(json.dumps(value, ensure_ascii=False))


class VisualProjectModel:
    """与 Tk 界面解耦的工作簿、配置和渲染模型。"""

    def __init__(self):
        INPUT_DIR.mkdir(parents=True, exist_ok=True)
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        self.book: Optional[Path] = None
        self.sheet_names = []
        self.activity_path: Optional[Path] = None
        self.activity_raw = {}
        self.base_config = {}
        self.manager = engine.get_theme_manager(require_themes=False)
        try:
            engine.sync_theme_packages_and_report(self.manager)
        except Exception:
            pass
        self.manager.require_themes()

    def list_books(self):
        files = []
        for pattern in ("*.xlsx", "*.xlsm"):
            files.extend(INPUT_DIR.glob(pattern))
        return sorted(set(p.resolve() for p in files), key=lambda p: p.name.lower())

    def load_book(self, book):
        self.book = Path(book).expanduser().resolve()
        if not self.book.exists():
            raise FileNotFoundError(self.book)
        with zipfile.ZipFile(self.book, "r") as z:
            targets = engine.workbook_sheet_targets(z)
        self.sheet_names = sorted(
            [name for name in targets if engine.KEYWORD in name],
            key=engine.guide_sheet_sort_key,
        )
        if not self.sheet_names:
            raise ValueError("该 Excel 中没有包含“攻略图”的工作表。")
        self.base_config = engine.load_config(self.book.parent)
        self.activity_path = next(
            (p for p in engine.activity_config_candidates(self.book) if p.exists()),
            self.book.parent / engine.expected_activity_config_name(self.book),
        )
        if self.activity_path.exists():
            self.activity_raw = engine.load_json_with_comments(self.activity_path)
            if not isinstance(self.activity_raw, dict):
                self.activity_raw = {}
        else:
            self.activity_raw = {}
        return list(self.sheet_names)

    def effective_config(self, activity_override=None):
        raw = self.activity_raw if activity_override is None else activity_override
        cfg = engine.deep_merge_config(self.base_config, raw)
        cfg["_config_dir"] = str(self.book.parent.resolve()) if self.book else str(INPUT_DIR.resolve())
        cfg["_script_dir"] = str(ROOT)
        cfg["_workbook_dir"] = str(self.book.parent.resolve()) if self.book else str(INPUT_DIR.resolve())
        if self.activity_path:
            cfg["_activity_config_dir"] = str(self.activity_path.parent.resolve())
            cfg["_activity_config_path"] = str(self.activity_path.resolve())
            cfg["_missing_activity_config"] = not self.activity_path.exists()
        return cfg

    def theme_rows(self):
        return [(t.id, t.name, t.version) for t in self.manager.themes]

    def variants(self, theme_id):
        theme = self.manager.get(theme_id)
        return [(v["id"], v["name"]) for v in theme.variants]

    def selection(self, theme_id, variant_id):
        return self.manager.resolve(theme_id, variant_id)

    def build_guide(self, sheet_name, theme_id, variant_id, activity_override=None):
        if not self.book:
            raise ValueError("尚未选择 Excel。")
        cfg = self.effective_config(activity_override)
        engine.apply_font_config(cfg)
        selection = self.selection(theme_id, variant_id)
        with zipfile.ZipFile(self.book, "r") as z:
            targets = engine.workbook_sheet_targets(z)
            if sheet_name not in targets:
                raise ValueError(f"找不到工作表：{sheet_name}")
            theme_colors = engine.read_theme_colors(z)
            shared = engine.read_shared_strings(z, theme_colors)
            fills, xfs, parsed_fonts = engine.read_styles(z, theme_colors)
            values, styles, rich = engine.read_sheet(
                z, targets[sheet_name], shared, theme_colors, xfs, parsed_fonts
            )
        guide = engine.parse_guide(
            sheet_name,
            values,
            styles,
            rich,
            fills,
            xfs,
            parsed_fonts,
            selection,
            cfg,
        )
        return guide

    def render_header(self, sheet_name, theme_id, variant_id, activity_override=None):
        guide = self.build_guide(sheet_name, theme_id, variant_id, activity_override)
        return engine.render_header_preview(guide)

    def render_full(self, sheet_name, theme_id, variant_id, activity_override=None, out_path=None):
        guide = self.build_guide(sheet_name, theme_id, variant_id, activity_override)
        if out_path is None:
            fd, name = tempfile.mkstemp(prefix="guide_gui_preview_", suffix=".png")
            os.close(fd)
            out_path = Path(name)
        else:
            out_path = Path(out_path)
            out_path.parent.mkdir(parents=True, exist_ok=True)
        engine.render(guide, out_path)
        with Image.open(out_path) as opened:
            image = opened.convert("RGB").copy()
        return image, out_path, guide

    def save_activity(self, data):
        if not self.activity_path:
            raise ValueError("没有活动配置保存路径。")
        self.activity_path.parent.mkdir(parents=True, exist_ok=True)
        self.activity_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        self.activity_raw = _json_clone(data)
        return self.activity_path


class VisualGuideEditor(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"攻略图可视化生成器 V{APP_VERSION}")
        self.geometry("1460x900")
        self.minsize(1160, 720)
        self.model = VisualProjectModel()
        self.activity_work = {}
        self.preview_pil = None
        self.preview_photo = None
        self.preview_item = None
        self.preview_scale = 1.0
        self.preview_origin = (0, 0)
        self._drag_banner = None
        self.preview_mode = tk.StringVar(value="header")
        self.auto_preview = tk.BooleanVar(value=True)
        self._preview_after = None
        self._updating_controls = False
        self._field_vars = {}
        self._build_ui()
        self._load_initial_books()

    # -------------------------- UI construction --------------------------
    def _build_ui(self):
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        toolbar = ttk.Frame(self, padding=(10, 8))
        toolbar.grid(row=0, column=0, sticky="ew")
        toolbar.columnconfigure(9, weight=1)

        ttk.Label(toolbar, text="Excel").grid(row=0, column=0, padx=(0, 5))
        self.book_combo = ttk.Combobox(toolbar, width=30, state="readonly")
        self.book_combo.grid(row=0, column=1, padx=(0, 8))
        self.book_combo.bind("<<ComboboxSelected>>", self._on_book_selected)
        ttk.Button(toolbar, text="浏览…", command=self._browse_book).grid(row=0, column=2, padx=(0, 12))

        ttk.Label(toolbar, text="工作表").grid(row=0, column=3, padx=(0, 5))
        self.sheet_combo = ttk.Combobox(toolbar, width=22, state="readonly")
        self.sheet_combo.grid(row=0, column=4, padx=(0, 12))
        self.sheet_combo.bind("<<ComboboxSelected>>", lambda _e: self.schedule_preview())

        ttk.Label(toolbar, text="主题").grid(row=0, column=5, padx=(0, 5))
        self.theme_combo = ttk.Combobox(toolbar, width=17, state="readonly")
        self.theme_combo.grid(row=0, column=6, padx=(0, 8))
        self.theme_combo.bind("<<ComboboxSelected>>", self._on_theme_selected)

        ttk.Label(toolbar, text="配色").grid(row=0, column=7, padx=(0, 5))
        self.variant_combo = ttk.Combobox(toolbar, width=16, state="readonly")
        self.variant_combo.grid(row=0, column=8, padx=(0, 12))
        self.variant_combo.bind("<<ComboboxSelected>>", lambda _e: self.schedule_preview())

        ttk.Button(toolbar, text="刷新预览", command=self.refresh_preview).grid(row=0, column=10, padx=4)
        ttk.Button(toolbar, text="保存设置", command=self.save_settings).grid(row=0, column=11, padx=4)
        ttk.Button(toolbar, text="生成当前图", command=self.generate_current).grid(row=0, column=12, padx=4)
        ttk.Button(toolbar, text="生成全部", command=self.generate_all).grid(row=0, column=13, padx=4)

        pane = ttk.Panedwindow(self, orient=tk.HORIZONTAL)
        pane.grid(row=1, column=0, sticky="nsew")

        left = ttk.Frame(pane, width=420)
        right = ttk.Frame(pane)
        pane.add(left, weight=0)
        pane.add(right, weight=1)

        left.rowconfigure(0, weight=1)
        left.columnconfigure(0, weight=1)
        notebook = ttk.Notebook(left)
        notebook.grid(row=0, column=0, sticky="nsew", padx=(10, 5), pady=(4, 8))

        banner_tab = self._scroll_tab(notebook)
        bg_tab = self._scroll_tab(notebook)
        title_tab = self._scroll_tab(notebook)
        output_tab = self._scroll_tab(notebook)
        notebook.add(banner_tab[0], text="Banner")
        notebook.add(bg_tab[0], text="背景")
        notebook.add(title_tab[0], text="标题区")
        notebook.add(output_tab[0], text="输出")

        self._build_banner_controls(banner_tab[1])
        self._build_background_controls(bg_tab[1])
        self._build_title_controls(title_tab[1])
        self._build_output_controls(output_tab[1])

        right.rowconfigure(1, weight=1)
        right.columnconfigure(0, weight=1)
        preview_bar = ttk.Frame(right, padding=(8, 6))
        preview_bar.grid(row=0, column=0, sticky="ew")
        ttk.Label(preview_bar, text="预览模式：").pack(side=tk.LEFT)
        ttk.Radiobutton(preview_bar, text="标题区（快速）", variable=self.preview_mode, value="header", command=self.refresh_preview).pack(side=tk.LEFT)
        ttk.Radiobutton(preview_bar, text="完整长图", variable=self.preview_mode, value="full", command=self.refresh_preview).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Checkbutton(preview_bar, text="调整时自动预览", variable=self.auto_preview).pack(side=tk.LEFT, padx=(18, 0))
        self.status_var = tk.StringVar(value="请选择 Excel。")
        ttk.Label(preview_bar, textvariable=self.status_var).pack(side=tk.RIGHT)

        canvas_frame = ttk.Frame(right)
        canvas_frame.grid(row=1, column=0, sticky="nsew", padx=(5, 10), pady=(0, 8))
        canvas_frame.rowconfigure(0, weight=1)
        canvas_frame.columnconfigure(0, weight=1)
        self.canvas = tk.Canvas(canvas_frame, bg="#25282d", highlightthickness=0)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        ybar = ttk.Scrollbar(canvas_frame, orient=tk.VERTICAL, command=self.canvas.yview)
        xbar = ttk.Scrollbar(canvas_frame, orient=tk.HORIZONTAL, command=self.canvas.xview)
        ybar.grid(row=0, column=1, sticky="ns")
        xbar.grid(row=1, column=0, sticky="ew")
        self.canvas.configure(yscrollcommand=ybar.set, xscrollcommand=xbar.set)
        self.canvas.bind("<Configure>", lambda _e: self._display_preview())
        self.canvas.bind("<ButtonPress-1>", self._canvas_press)
        self.canvas.bind("<B1-Motion>", self._canvas_drag)
        self.canvas.bind("<ButtonRelease-1>", self._canvas_release)

    def _scroll_tab(self, notebook):
        outer = ttk.Frame(notebook)
        outer.rowconfigure(0, weight=1)
        outer.columnconfigure(0, weight=1)
        canvas = tk.Canvas(outer, highlightthickness=0, width=400)
        bar = ttk.Scrollbar(outer, orient=tk.VERTICAL, command=canvas.yview)
        inner = ttk.Frame(canvas, padding=10)
        win = canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.configure(yscrollcommand=bar.set)
        canvas.grid(row=0, column=0, sticky="nsew")
        bar.grid(row=0, column=1, sticky="ns")
        inner.bind("<Configure>", lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfigure(win, width=e.width))
        return outer, inner

    def _section(self, parent, title):
        box = ttk.LabelFrame(parent, text=title, padding=8)
        box.pack(fill=tk.X, pady=(0, 9))
        box.columnconfigure(1, weight=1)
        return box

    def _track_field_var(self, path, var):
        self._field_vars[path] = var
        var.trace_add("write", lambda *_: self._on_field_changed())
        return var

    def _entry_row(self, parent, row, label, path, var, width=10, browse=None):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=(0, 8), pady=3)
        ent = ttk.Entry(parent, textvariable=self._track_field_var(path, var), width=width)
        ent.grid(row=row, column=1, sticky="ew", pady=3)
        if browse:
            ttk.Button(parent, text="浏览…", command=browse).grid(row=row, column=2, padx=(6, 0), pady=3)
        return ent

    def _scale_row(self, parent, row, label, path, var, from_, to, resolution=1.0):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=(0, 8), pady=3)
        frame = ttk.Frame(parent)
        frame.grid(row=row, column=1, columnspan=2, sticky="ew", pady=3)
        frame.columnconfigure(0, weight=1)
        scale = ttk.Scale(frame, variable=self._track_field_var(path, var), from_=from_, to=to)
        scale.grid(row=0, column=0, sticky="ew")
        spin = ttk.Spinbox(frame, textvariable=var, from_=from_, to=to, increment=resolution, width=8)
        spin.grid(row=0, column=1, padx=(7, 0))
        return scale

    def _check_row(self, parent, row, label, path, var):
        cb = ttk.Checkbutton(parent, text=label, variable=self._track_field_var(path, var))
        cb.grid(row=row, column=0, columnspan=3, sticky="w", pady=3)
        return cb

    def _combo_row(self, parent, row, label, path, var, values):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=(0, 8), pady=3)
        cb = ttk.Combobox(parent, textvariable=self._track_field_var(path, var), values=values, state="readonly")
        cb.grid(row=row, column=1, columnspan=2, sticky="ew", pady=3)
        return cb

    def _build_banner_controls(self, parent):
        box = self._section(parent, "Banner 图片")
        self.banner_path = tk.StringVar()
        self._entry_row(box, 0, "图片", "header.banner.path", self.banner_path, browse=lambda: self._choose_image(self.banner_path))
        self.banner_fit = tk.StringVar(value="contain")
        self._combo_row(box, 1, "适配", "header.banner.fit", self.banner_fit, ["contain", "cover", "stretch"])
        self.banner_scale = tk.DoubleVar(value=0.9)
        self._scale_row(box, 2, "缩放", "header.banner.scale", self.banner_scale, 0.20, 3.00, 0.01)
        self.banner_opacity = tk.IntVar(value=255)
        self._scale_row(box, 3, "透明度", "header.banner.opacity", self.banner_opacity, 0, 255, 1)
        self.banner_off_x = tk.IntVar(value=0)
        self._scale_row(box, 4, "图片偏移 X", "header.banner.offset.0", self.banner_off_x, -500, 500, 1)
        self.banner_off_y = tk.IntVar(value=0)
        self._scale_row(box, 5, "图片偏移 Y", "header.banner.offset.1", self.banner_off_y, -500, 500, 1)
        self.banner_mirror_h = tk.BooleanVar(value=False)
        self._check_row(box, 6, "水平镜像", "header.banner.mirror_horizontal", self.banner_mirror_h)
        self.banner_mirror_v = tk.BooleanVar(value=False)
        self._check_row(box, 7, "垂直镜像", "header.banner.mirror_vertical", self.banner_mirror_v)
        self.banner_trim = tk.BooleanVar(value=True)
        self._check_row(box, 8, "自动裁透明边", "header.banner.trim_transparent", self.banner_trim)

        box2 = self._section(parent, "Banner 显示区域")
        self.banner_x1 = tk.IntVar(value=18)
        self.banner_y1 = tk.IntVar(value=94)
        self.banner_x2 = tk.IntVar(value=378)
        self.banner_y2 = tk.IntVar(value=274)
        self._scale_row(box2, 0, "左边 X1", "header.banner.box.0", self.banner_x1, -200, 1080, 1)
        self._scale_row(box2, 1, "顶部 Y1", "header.banner.box.1", self.banner_y1, -100, 500, 1)
        self._scale_row(box2, 2, "右边 X2", "header.banner.box.2", self.banner_x2, 0, 1280, 1)
        self._scale_row(box2, 3, "底部 Y2", "header.banner.box.3", self.banner_y2, 0, 600, 1)

    def _build_background_controls(self, parent):
        box = self._section(parent, "标题背景")
        self.bg_path = tk.StringVar()
        self._entry_row(box, 0, "图片", "header.background.path", self.bg_path, browse=lambda: self._choose_image(self.bg_path))
        self.bg_fit = tk.StringVar(value="cover")
        self._combo_row(box, 1, "适配", "header.background.fit", self.bg_fit, ["cover", "contain", "stretch"])
        self.bg_scale = tk.DoubleVar(value=1.0)
        self._scale_row(box, 2, "缩放", "header.background.scale", self.bg_scale, 0.20, 3.00, 0.01)
        self.bg_focal_x = tk.DoubleVar(value=0.5)
        self._scale_row(box, 3, "焦点 X", "header.background.focal_point.0", self.bg_focal_x, 0.0, 1.0, 0.01)
        self.bg_focal_y = tk.DoubleVar(value=0.5)
        self._scale_row(box, 4, "焦点 Y", "header.background.focal_point.1", self.bg_focal_y, 0.0, 1.0, 0.01)
        self.bg_off_x = tk.IntVar(value=0)
        self._scale_row(box, 5, "偏移 X", "header.background.offset.0", self.bg_off_x, -500, 500, 1)
        self.bg_off_y = tk.IntVar(value=0)
        self._scale_row(box, 6, "偏移 Y", "header.background.offset.1", self.bg_off_y, -500, 500, 1)
        self.bg_blur = tk.DoubleVar(value=0.0)
        self._scale_row(box, 7, "模糊", "header.background.blur", self.bg_blur, 0, 30, 0.1)
        self.bg_overlay = tk.IntVar(value=0)
        self._scale_row(box, 8, "蒙版透明度", "header.background.overlay_alpha", self.bg_overlay, 0, 255, 1)
        self.bg_mirror_h = tk.BooleanVar(value=False)
        self._check_row(box, 9, "水平镜像", "header.background.mirror_horizontal", self.bg_mirror_h)
        self.bg_mirror_v = tk.BooleanVar(value=False)
        self._check_row(box, 10, "垂直镜像", "header.background.mirror_vertical", self.bg_mirror_v)

    def _build_title_controls(self, parent):
        header = self._section(parent, "标题区尺寸")
        self.header_height = tk.IntVar(value=280)
        self._scale_row(header, 0, "标题区高度", "header.height", self.header_height, 180, 520, 1)

        title = self._section(parent, "主标题横条")
        self.title_left = tk.IntVar(value=90)
        self.title_right = tk.IntVar(value=1070)
        self.title_top = tk.IntVar(value=30)
        self.title_height = tk.IntVar(value=150)
        self.title_font = tk.IntVar(value=56)
        self.title_min_font = tk.IntVar(value=44)
        self.title_y_shift = tk.IntVar(value=0)
        self.title_color = tk.StringVar(value="#FFFBE8")
        self._scale_row(title, 0, "左边", "header.title.left", self.title_left, 0, 1000, 1)
        self._scale_row(title, 1, "右边", "header.title.right", self.title_right, 180, 1080, 1)
        self._scale_row(title, 2, "顶部", "header.title.top", self.title_top, 0, 400, 1)
        self._scale_row(title, 3, "高度", "header.title.height", self.title_height, 72, 260, 1)
        self._scale_row(title, 4, "字号", "header.title.font_size", self.title_font, 20, 100, 1)
        self._scale_row(title, 5, "最小字号", "header.title.min_font_size", self.title_min_font, 12, 80, 1)
        self._scale_row(title, 6, "文字上下偏移", "header.title.text_y_shift", self.title_y_shift, -60, 60, 1)
        self._entry_row(title, 7, "文字颜色", "header.title.text_color", self.title_color)
        ttk.Button(title, text="选择颜色", command=self._choose_title_color).grid(row=7, column=2, padx=(6, 0))

        author = self._section(parent, "作者胶囊")
        self.author_top = tk.IntVar(value=176)
        self.author_off_x = tk.IntVar(value=0)
        self.author_off_y = tk.IntVar(value=0)
        self.author_font = tk.IntVar(value=27)
        self.author_avatar = tk.IntVar(value=58)
        self._scale_row(author, 0, "顶部", "header.author.top", self.author_top, 0, 500, 1)
        self._scale_row(author, 1, "偏移 X", "header.author.offset_x", self.author_off_x, -400, 400, 1)
        self._scale_row(author, 2, "偏移 Y", "header.author.offset_y", self.author_off_y, -200, 200, 1)
        self._scale_row(author, 3, "字号", "header.author.font_size", self.author_font, 12, 60, 1)
        self._scale_row(author, 4, "头像尺寸", "header.author.avatar_size", self.author_avatar, 20, 100, 1)

    def _build_output_controls(self, parent):
        box = self._section(parent, "生成与保存")
        ttk.Button(box, text="保存到活动 JSON", command=self.save_settings).grid(row=0, column=0, columnspan=3, sticky="ew", pady=4)
        ttk.Button(box, text="生成当前工作表", command=self.generate_current).grid(row=1, column=0, columnspan=3, sticky="ew", pady=4)
        ttk.Button(box, text="生成该 Excel 全部攻略图", command=self.generate_all).grid(row=2, column=0, columnspan=3, sticky="ew", pady=4)
        ttk.Button(box, text="打开输出文件夹", command=self.open_output).grid(row=3, column=0, columnspan=3, sticky="ew", pady=4)
        ttk.Button(box, text="重新读取 JSON", command=self.reload_activity).grid(row=4, column=0, columnspan=3, sticky="ew", pady=4)
        ttk.Label(
            box,
            text="调整内容会先保存在内存中；只有点击“保存设置”或“生成”时才会写入活动 JSON。",
            wraplength=330,
            justify=tk.LEFT,
        ).grid(row=5, column=0, columnspan=3, sticky="w", pady=(10, 2))

    # -------------------------- loading and values --------------------------
    def _load_initial_books(self):
        books = self.model.list_books()
        self._book_paths = books
        self.book_combo["values"] = [p.name for p in books]
        themes = self.model.theme_rows()
        self._theme_ids = [row[0] for row in themes]
        self.theme_combo["values"] = [f"{name} v{version}" for _, name, version in themes]
        if themes:
            default_idx = next((i for i, row in enumerate(themes) if row[0] == "classic_clean"), 0)
            self.theme_combo.current(default_idx)
            self._on_theme_selected()
        if books:
            self.book_combo.current(0)
            self._on_book_selected()

    def _browse_book(self):
        path = filedialog.askopenfilename(
            title="选择攻略 Excel",
            initialdir=str(INPUT_DIR),
            filetypes=[("Excel", "*.xlsx *.xlsm"), ("所有文件", "*.*")],
        )
        if not path:
            return
        p = Path(path).resolve()
        if p not in getattr(self, "_book_paths", []):
            self._book_paths.append(p)
            self.book_combo["values"] = [x.name for x in self._book_paths]
        self.book_combo.current(self._book_paths.index(p))
        self._on_book_selected()

    def _on_book_selected(self, _event=None):
        try:
            idx = self.book_combo.current()
            if idx < 0:
                return
            sheets = self.model.load_book(self._book_paths[idx])
            self.sheet_combo["values"] = sheets
            if sheets:
                self.sheet_combo.current(0)
            self.activity_work = _json_clone(self.model.activity_raw)
            self._load_controls_from_effective()
            self.status_var.set(f"已加载：{self.model.book.name}")
            self.refresh_preview()
        except Exception as exc:
            messagebox.showerror("读取失败", str(exc))

    def _on_theme_selected(self, _event=None):
        idx = self.theme_combo.current()
        if idx < 0 or not getattr(self, "_theme_ids", None):
            return
        theme_id = self._theme_ids[idx]
        variants = self.model.variants(theme_id)
        self._variant_ids = [v[0] for v in variants]
        self.variant_combo["values"] = [v[1] for v in variants]
        if variants:
            self.variant_combo.current(0)
        self.schedule_preview()

    def _theme_selection_ids(self):
        ti = self.theme_combo.current()
        vi = self.variant_combo.current()
        if ti < 0 or vi < 0:
            raise ValueError("请选择主题和配色。")
        return self._theme_ids[ti], self._variant_ids[vi]

    def _load_controls_from_effective(self):
        cfg = self.model.effective_config(self.activity_work)
        self._updating_controls = True
        try:
            banner = _get(cfg, "header.banner", {}) or {}
            bg = _get(cfg, "header.background", {}) or {}
            title = _get(cfg, "header.title", {}) or {}
            author = _get(cfg, "header.author", {}) or {}
            header_h = int(_get(cfg, "header.height", 280) or 280)
            b_box = _box(banner.get("box"), (18, 94, 378, header_h - 6))
            b_off = _pair(banner.get("offset"), (banner.get("offset_x", 0), banner.get("offset_y", 0)))
            bg_off = _pair(bg.get("offset"), (bg.get("offset_x", 0), bg.get("offset_y", 0)))
            focal = _pair(bg.get("focal_point"), (0.5, 0.5))
            values = {
                "header.banner.path": banner.get("path", ""),
                "header.banner.fit": banner.get("fit", "contain"),
                "header.banner.scale": float(banner.get("scale", 0.9) or 0.9),
                "header.banner.opacity": int(banner.get("opacity", 255) or 255),
                "header.banner.offset.0": int(b_off[0]),
                "header.banner.offset.1": int(b_off[1]),
                "header.banner.mirror_horizontal": bool(banner.get("mirror_horizontal", False)),
                "header.banner.mirror_vertical": bool(banner.get("mirror_vertical", False)),
                "header.banner.trim_transparent": bool(banner.get("trim_transparent", True)),
                "header.banner.box.0": int(b_box[0]),
                "header.banner.box.1": int(b_box[1]),
                "header.banner.box.2": int(b_box[2]),
                "header.banner.box.3": int(b_box[3]),
                "header.background.path": bg.get("path", ""),
                "header.background.fit": bg.get("fit", "cover"),
                "header.background.scale": float(bg.get("scale", 1.0) or 1.0),
                "header.background.focal_point.0": float(focal[0]),
                "header.background.focal_point.1": float(focal[1]),
                "header.background.offset.0": int(bg_off[0]),
                "header.background.offset.1": int(bg_off[1]),
                "header.background.blur": float(bg.get("blur", 0) or 0),
                "header.background.overlay_alpha": int(bg.get("overlay_alpha", 0) or 0),
                "header.background.mirror_horizontal": bool(bg.get("mirror_horizontal", False)),
                "header.background.mirror_vertical": bool(bg.get("mirror_vertical", False)),
                "header.height": header_h,
                "header.title.left": int(title.get("left", 90) or 90),
                "header.title.right": int(title.get("right", 1070) or 1070),
                "header.title.top": int(title.get("top", 30) or 30),
                "header.title.height": int(title.get("height", 150) or 150),
                "header.title.font_size": int(title.get("font_size", 56) or 56),
                "header.title.min_font_size": int(title.get("min_font_size", 44) or 44),
                "header.title.text_y_shift": int(title.get("text_y_shift", 0) or 0),
                "header.title.text_color": title.get("text_color", "#FFFBE8"),
                "header.author.top": int(author.get("top", 176) or 176),
                "header.author.offset_x": int(author.get("offset_x", 0) or 0),
                "header.author.offset_y": int(author.get("offset_y", 0) or 0),
                "header.author.font_size": int(author.get("font_size", 27) or 27),
                "header.author.avatar_size": int(author.get("avatar_size", 58) or 58),
            }
            for path, var in self._field_vars.items():
                if path in values:
                    var.set(values[path])
        finally:
            self._updating_controls = False

    def _collect_activity(self):
        data = _json_clone(self.activity_work)
        # Scalar fields
        scalar_paths = [
            "header.banner.path", "header.banner.fit", "header.banner.scale", "header.banner.opacity",
            "header.banner.mirror_horizontal", "header.banner.mirror_vertical", "header.banner.trim_transparent",
            "header.background.path", "header.background.fit", "header.background.scale", "header.background.blur",
            "header.background.overlay_alpha", "header.background.mirror_horizontal", "header.background.mirror_vertical",
            "header.height", "header.title.left", "header.title.right", "header.title.top", "header.title.height",
            "header.title.font_size", "header.title.min_font_size", "header.title.text_y_shift", "header.title.text_color",
            "header.author.top", "header.author.offset_x", "header.author.offset_y", "header.author.font_size", "header.author.avatar_size",
        ]
        for path in scalar_paths:
            value = self._field_vars[path].get()
            if path.endswith(".path"):
                value = str(value).strip()
            _set(data, path, value)
        _set(data, "header.banner.offset", [self.banner_off_x.get(), self.banner_off_y.get()])
        _set(data, "header.banner.box", [self.banner_x1.get(), self.banner_y1.get(), self.banner_x2.get(), self.banner_y2.get()])
        _set(data, "header.background.offset", [self.bg_off_x.get(), self.bg_off_y.get()])
        _set(data, "header.background.focal_point", [self.bg_focal_x.get(), self.bg_focal_y.get()])
        return data

    # -------------------------- events and preview --------------------------
    def _on_field_changed(self):
        if self._updating_controls:
            return
        if self.auto_preview.get():
            self.schedule_preview()

    def schedule_preview(self):
        if self._preview_after is not None:
            try:
                self.after_cancel(self._preview_after)
            except Exception:
                pass
        self._preview_after = self.after(350, self.refresh_preview)

    def refresh_preview(self):
        self._preview_after = None
        if not self.model.book or not self.sheet_combo.get():
            return
        try:
            self.config(cursor="watch")
            self.update_idletasks()
            activity = self._collect_activity()
            theme_id, variant_id = self._theme_selection_ids()
            sheet = self.sheet_combo.get()
            self.status_var.set("正在生成预览…")
            self.update_idletasks()
            if self.preview_mode.get() == "full":
                image, temp_path, _guide = self.model.render_full(sheet, theme_id, variant_id, activity)
                try:
                    Path(temp_path).unlink(missing_ok=True)
                except Exception:
                    pass
            else:
                image = self.model.render_header(sheet, theme_id, variant_id, activity)
            self.preview_pil = image
            self._display_preview()
            self.status_var.set(f"预览完成：{theme_id}/{variant_id}")
        except Exception as exc:
            self.status_var.set("预览失败")
            messagebox.showerror("预览失败", str(exc))
        finally:
            self.config(cursor="")

    def _display_preview(self):
        if self.preview_pil is None:
            return
        cw = max(100, self.canvas.winfo_width() - 28)
        ch = max(100, self.canvas.winfo_height() - 28)
        scale = min(cw / self.preview_pil.width, ch / self.preview_pil.height)
        # 标题区预览允许放大到接近原尺寸；完整长图以完整可见为主。
        if self.preview_mode.get() == "header":
            scale = min(1.0, max(0.25, scale))
        else:
            scale = max(0.15, scale)
        size = (max(1, int(self.preview_pil.width * scale)), max(1, int(self.preview_pil.height * scale)))
        shown = self.preview_pil.resize(size, Image.Resampling.LANCZOS)
        self.preview_photo = ImageTk.PhotoImage(shown)
        self.canvas.delete("all")
        x = max(14, (cw + 28 - size[0]) // 2)
        y = 14
        self.preview_item = self.canvas.create_image(x, y, anchor="nw", image=self.preview_photo)
        self.preview_scale = scale
        self.preview_origin = (x, y)
        if self.preview_mode.get() == "header":
            bx1, by1, bx2, by2 = self.banner_x1.get(), self.banner_y1.get(), self.banner_x2.get(), self.banner_y2.get()
            self.canvas.create_rectangle(
                x + bx1 * scale, y + by1 * scale,
                x + bx2 * scale, y + by2 * scale,
                outline="#00E5FF", width=2, dash=(6, 4), tags=("banner_box",),
            )
            self.canvas.create_text(
                x + bx1 * scale + 7, y + by1 * scale + 7,
                anchor="nw", text="拖动 Banner", fill="#00E5FF", tags=("banner_box",),
            )
        self.canvas.configure(scrollregion=(0, 0, max(cw + 28, x + size[0] + 14), size[1] + 28))

    def _canvas_press(self, event):
        if self.preview_mode.get() != "header" or not self.preview_pil:
            return
        cx, cy = self.canvas.canvasx(event.x), self.canvas.canvasy(event.y)
        items = self.canvas.find_overlapping(cx-2, cy-2, cx+2, cy+2)
        if not any("banner_box" in self.canvas.gettags(item) for item in items):
            return
        self._drag_banner = (
            cx, cy,
            self.banner_x1.get(), self.banner_y1.get(),
            self.banner_x2.get(), self.banner_y2.get(),
        )

    def _canvas_drag(self, event):
        if not self._drag_banner:
            return
        cx, cy = self.canvas.canvasx(event.x), self.canvas.canvasy(event.y)
        sx, sy, x1, y1, x2, y2 = self._drag_banner
        dx = int(round((cx - sx) / max(0.001, self.preview_scale)))
        dy = int(round((cy - sy) / max(0.001, self.preview_scale)))
        self._updating_controls = True
        try:
            self.banner_x1.set(x1 + dx); self.banner_y1.set(y1 + dy)
            self.banner_x2.set(x2 + dx); self.banner_y2.set(y2 + dy)
        finally:
            self._updating_controls = False
        # 仅移动选框，松开鼠标后再重新渲染。
        self._display_preview()

    def _canvas_release(self, _event):
        if self._drag_banner:
            self._drag_banner = None
            self.schedule_preview()

    # -------------------------- file and generation actions --------------------------
    def _choose_image(self, var):
        initial = ROOT / "assets"
        path = filedialog.askopenfilename(
            title="选择图片",
            initialdir=str(initial if initial.exists() else ROOT),
            filetypes=[("图片", "*.png *.jpg *.jpeg *.webp"), ("所有文件", "*.*")],
        )
        if not path:
            return
        p = Path(path).resolve()
        try:
            value = p.relative_to(ROOT).as_posix()
        except ValueError:
            try:
                value = p.relative_to(self.model.book.parent).as_posix()
            except Exception:
                value = str(p)
        var.set(value)

    def _choose_title_color(self):
        color = colorchooser.askcolor(color=self.title_color.get(), title="选择标题文字颜色")[1]
        if color:
            self.title_color.set(color.upper())

    def save_settings(self, quiet=False):
        try:
            data = self._collect_activity()
            path = self.model.save_activity(data)
            self.activity_work = _json_clone(data)
            self.status_var.set(f"已保存：{path.name}")
            if not quiet:
                messagebox.showinfo("保存成功", f"设置已保存到：\n{path}")
            return True
        except Exception as exc:
            messagebox.showerror("保存失败", str(exc))
            return False

    def reload_activity(self):
        if not self.model.book:
            return
        try:
            self.model.load_book(self.model.book)
            self.activity_work = _json_clone(self.model.activity_raw)
            self._load_controls_from_effective()
            self.refresh_preview()
        except Exception as exc:
            messagebox.showerror("重新读取失败", str(exc))

    def generate_current(self):
        if not self.save_settings(quiet=True):
            return
        try:
            self.config(cursor="watch")
            self.update_idletasks()
            theme_id, variant_id = self._theme_selection_ids()
            sheet = self.sheet_combo.get()
            selection = self.model.selection(theme_id, variant_id)
            suffix = engine.safe_filename(engine.theme_output_label(selection))
            out = engine.output_directory_for_book(self.model.book) / f"{engine.safe_filename(sheet)}_{suffix}.png"
            image, _out_path, _guide = self.model.render_full(sheet, theme_id, variant_id, self.activity_work, out)
            self.preview_pil = image
            self.preview_mode.set("full")
            self._display_preview()
            self.status_var.set(f"生成完成：{out.name}")
            engine.open_output_directory(out.parent)
        except Exception as exc:
            messagebox.showerror("生成失败", str(exc))
        finally:
            self.config(cursor="")

    def generate_all(self):
        if not self.save_settings(quiet=True):
            return
        try:
            self.config(cursor="watch")
            self.update_idletasks()
            theme_id, variant_id = self._theme_selection_ids()
            old_theme, old_variant = engine.RUNTIME_THEME_ID, engine.RUNTIME_VARIANT_ID
            engine.RUNTIME_THEME_ID = theme_id
            engine.RUNTIME_VARIANT_ID = variant_id
            try:
                ok, total = engine.process_book(self.model.book)
            finally:
                engine.RUNTIME_THEME_ID = old_theme
                engine.RUNTIME_VARIANT_ID = old_variant
            self.status_var.set(f"生成完成：{ok}/{total}")
            if ok:
                engine.open_output_directory(engine.output_directory_for_book(self.model.book))
            if ok != total:
                messagebox.showwarning("部分生成失败", f"成功 {ok}/{total} 张，请查看控制台信息。")
        except Exception as exc:
            messagebox.showerror("生成失败", str(exc))
        finally:
            self.config(cursor="")

    def open_output(self):
        if self.model.book:
            path = engine.output_directory_for_book(self.model.book)
        else:
            path = OUTPUT_DIR
        path.mkdir(parents=True, exist_ok=True)
        engine.open_output_directory(path)


def main():
    app = VisualGuideEditor()
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
