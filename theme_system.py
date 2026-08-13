#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""攻略图生成器 themes/ 目录加载与校验。兼容 Python 3.9。"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Iterable, List, Optional, Tuple


class ThemeError(ValueError):
    """主题配置格式或选择错误。"""


def _load_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ThemeError(f"缺少主题文件：{path}")
    except json.JSONDecodeError as exc:
        raise ThemeError(f"主题 JSON 格式错误：{path.name}（第 {exc.lineno} 行）")
    if not isinstance(data, dict):
        raise ThemeError(f"主题 JSON 顶层必须是对象：{path.name}")
    return data


def deep_merge(base: object, override: object) -> dict:
    """递归合并 dict；列表与标量由 override 整体替换。"""
    result = dict(base) if isinstance(base, dict) else {}
    if not isinstance(override, dict):
        return result
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _resolve_refs(value: object, root: dict) -> object:
    """解析 $colors.primary 这类主题内引用。"""
    if isinstance(value, str) and value.startswith("$"):
        current: object = root
        for part in value[1:].split("."):
            if not isinstance(current, dict) or part not in current:
                raise ThemeError(f"主题配置引用不存在：{value}")
            current = current[part]
        return current
    if isinstance(value, dict):
        return {k: _resolve_refs(v, root) for k, v in value.items()}
    if isinstance(value, list):
        return [_resolve_refs(v, root) for v in value]
    return value


def _version_tuple(value: object) -> tuple:
    parts = [int(x) for x in re.findall(r"\d+", str(value or "0"))[:4]]
    while len(parts) < 4:
        parts.append(0)
    return tuple(parts)


def _safe_id(value: object, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ThemeError(f"主题包缺少 {field}")
    allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-.")
    if any(ch not in allowed for ch in text) or text in {".", ".."}:
        raise ThemeError(f"{field} 只能包含字母、数字、下划线、短横线和点：{text}")
    return text


class ThemePackage:
    """themes/ 下的一个主题目录。"""

    def __init__(self, directory: Path, engine_version: Optional[str] = None):
        self.directory = Path(directory).resolve()
        self.manifest_path = self.directory / "manifest.json"
        self.manifest = _load_json(self.manifest_path)

        schema = int(self.manifest.get("schema_version", 1))
        if schema != 1:
            raise ThemeError(f"暂不支持主题 schema_version={schema}：{self.directory.name}")

        self.id = _safe_id(self.manifest.get("id"), "id")
        self.name = str(self.manifest.get("name") or self.id).strip()
        self.version = str(self.manifest.get("version") or "0.0.0").strip()
        self.description = str(self.manifest.get("description") or "").strip()
        self.engine_min_version = str(self.manifest.get("engine_min_version") or "0").strip()
        if engine_version and _version_tuple(engine_version) < _version_tuple(self.engine_min_version):
            raise ThemeError(
                f"主题 {self.name} 需要生成器 {self.engine_min_version} 或更高版本；当前为 {engine_version}"
            )
        self.preview = self._optional_path(self.manifest.get("preview"))

        entry_config = str(self.manifest.get("entry_config") or "theme.json")
        self.base_config_path = self._inside_path(entry_config)
        self.base_config = _load_json(self.base_config_path)

        raw_variants = self.manifest.get("variants") or []
        if not isinstance(raw_variants, list) or not raw_variants:
            raise ThemeError(f"主题包至少需要一个 variants 条目：{self.id}")

        self.variants: List[dict] = []
        seen_ids = set()
        seen_legacy = set()
        for index, raw in enumerate(raw_variants, 1):
            if not isinstance(raw, dict):
                raise ThemeError(f"主题 {self.id} 的第 {index} 个变体格式错误")
            variant_id = _safe_id(raw.get("id"), "variant.id")
            if variant_id in seen_ids:
                raise ThemeError(f"主题 {self.id} 存在重复变体：{variant_id}")
            seen_ids.add(variant_id)

            config_rel = str(raw.get("config") or f"variants/{variant_id}.json")
            config_path = self._inside_path(config_rel)
            variant = dict(raw)
            variant["id"] = variant_id
            variant["name"] = str(raw.get("name") or variant_id).strip()
            variant["config_path"] = config_path
            variant["preview_path"] = self._optional_path(raw.get("preview"))
            legacy = raw.get("legacy_number")
            if legacy is not None:
                try:
                    legacy = int(legacy)
                except (TypeError, ValueError):
                    raise ThemeError(f"主题 {self.id}/{variant_id} 的 legacy_number 必须是整数")
                if legacy <= 0 or legacy in seen_legacy:
                    raise ThemeError(f"主题 {self.id} 的 legacy_number 无效或重复：{legacy}")
                seen_legacy.add(legacy)
            variant["legacy_number"] = legacy
            self.variants.append(variant)

        # 加载时即校验所有变体，避免生成到一半才失败。
        for variant in self.variants:
            self.resolve(variant["id"])

    def _inside_path(self, relative: object) -> Path:
        text = str(relative or "").strip()
        if not text:
            raise ThemeError(f"主题 {self.id if hasattr(self, 'id') else self.directory.name} 存在空路径")
        candidate = (self.directory / text).resolve()
        try:
            candidate.relative_to(self.directory)
        except ValueError:
            raise ThemeError(f"主题包路径越界：{text}")
        return candidate

    def _optional_path(self, relative: object) -> Optional[Path]:
        if not relative:
            return None
        return self._inside_path(relative)

    def get_variant(self, variant_id: str) -> dict:
        for variant in self.variants:
            if variant["id"] == variant_id:
                return variant
        raise ThemeError(f"主题 {self.name} 没有配色变体：{variant_id}")

    def get_variant_by_legacy_number(self, number: int) -> Optional[dict]:
        for variant in self.variants:
            if variant.get("legacy_number") == number:
                return variant
        return None

    def resolve(self, variant_id: str) -> dict:
        variant = self.get_variant(variant_id)
        # theme.json is intentionally re-read on every resolve.
        # The generator can stay open while users tweak theme parameters.
        self.base_config = _load_json(self.base_config_path)
        variant_config = _load_json(variant["config_path"])
        merged = deep_merge(self.base_config, variant_config)
        merged = _resolve_refs(merged, merged)
        colors = merged.get("colors")
        if not isinstance(colors, dict):
            raise ThemeError(f"主题 {self.id}/{variant_id} 缺少 colors")
        for key in ("primary", "dark", "light", "chip"):
            value = colors.get(key)
            if not isinstance(value, str) or not value.startswith("#"):
                raise ThemeError(f"主题 {self.id}/{variant_id} 缺少合法颜色 colors.{key}")

        return {
            "theme_id": self.id,
            "theme_name": self.name,
            "theme_version": self.version,
            "theme_dir": str(self.directory),
            "variant_id": variant["id"],
            "variant_name": variant["name"],
            "variant_legacy_number": variant.get("legacy_number"),
            "config": merged,
            # palette 保留旧名称，但现在向渲染器暴露整个 colors 对象。
            # 新主题因此可以控制卡片、正文、风险区和底栏，不需要修改主脚本。
            "palette": dict(colors),
        }


class ThemeManager:
    """扫描并选择 themes/ 下的主题目录。"""

    def __init__(self, themes_dir: Path, engine_version: Optional[str] = None):
        self.engine_version = str(engine_version or "").strip() or None
        self.themes_dir = Path(themes_dir).resolve()
        self.themes_dir.mkdir(parents=True, exist_ok=True)
        self.themes: List[ThemePackage] = []
        self.errors: List[str] = []
        self.reload()

    def reload(self) -> None:
        self.themes = []
        self.errors = []
        for manifest in sorted(self.themes_dir.glob("*/manifest.json"), key=lambda p: p.parent.name.lower()):
            try:
                theme = ThemePackage(manifest.parent, self.engine_version)
                if any(existing.id == theme.id for existing in self.themes):
                    raise ThemeError(f"重复主题 id：{theme.id}")
                self.themes.append(theme)
            except Exception as exc:
                self.errors.append(f"{manifest.parent.name}: {exc}")

    def require_themes(self) -> None:
        if not self.themes:
            details = "；".join(self.errors) if self.errors else "themes 目录中没有主题包"
            raise ThemeError(f"没有可用主题：{details}")

    def get(self, theme_id: str) -> ThemePackage:
        for theme in self.themes:
            if theme.id == theme_id:
                return theme
        available = "、".join(t.id for t in self.themes) or "无"
        raise ThemeError(f"找不到主题：{theme_id}；可用主题：{available}")

    def resolve(self, theme_id: str, variant_id: str) -> dict:
        return self.get(theme_id).resolve(variant_id)

    def resolve_legacy_color(self, number: int) -> dict:
        matches: List[Tuple[ThemePackage, dict]] = []
        for theme in self.themes:
            variant = theme.get_variant_by_legacy_number(number)
            if variant:
                matches.append((theme, variant))
        if not matches:
            raise ThemeError(f"没有主题声明旧版配色编号：{number}")
        if len(matches) > 1:
            labels = "、".join(f"{t.id}/{v['id']}" for t, v in matches)
            raise ThemeError(f"旧版配色编号 {number} 在多个主题中重复：{labels}")
        theme, variant = matches[0]
        return theme.resolve(variant["id"])

    def list_lines(self) -> List[str]:
        lines = []
        for theme in self.themes:
            variants = "、".join(v["name"] for v in theme.variants)
            lines.append(f"{theme.name} [{theme.id}] v{theme.version}：{variants}")
        return lines
