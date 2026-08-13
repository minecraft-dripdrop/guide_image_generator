# -*- coding: utf-8 -*-
"""Shared reward-item artwork renderer for all theme renderers.

This module deliberately handles only the *item artwork layer*:
- metadata lookup
- quality frame
- item icon
- S / SS / SSS rank badge
- fragment badge (top-right)
- optional transparent-margin trimming
- optional sticker-ready transparent composition

Individual theme renderers still own their surrounding card, typography and
layout.  This keeps standard item visuals consistent while allowing special
styles such as handwritten stickers to add their own treatment afterwards.
"""
from __future__ import annotations

import re
from pathlib import Path

from PIL import Image, ImageDraw


_RANK_PREFIX_RE = re.compile(r"^\s*(SSS|SS|S)(?=[A-Za-z0-9\u3400-\u9fff])", re.IGNORECASE)


class RewardItemRenderer:
    """Theme-neutral reward item artwork helper."""

    def __init__(self, services, guide):
        self.s = services
        self.guide = guide
        self.cfg = guide.get("cfg") or {}
        self.catalog = services.build_item_catalog(self.cfg)
        qmap = self.cfg.get("quality_borders") or {}
        self.quality_borders = qmap if isinstance(qmap, dict) else {}

    def _rank_from_name(self, name):
        text = self.s.clean(str(name or "")).upper()
        m = _RANK_PREFIX_RE.match(text)
        return m.group(1).upper() if m else ""

    def resolve(self, item):
        item = item or {}
        name = self.s.clean(str(item.get("name") or "物品"))
        meta = dict(self.s.find_item_meta(name, self.catalog) or {})
        if not meta:
            # Conservative alias fallback for common box-name wording changes,
            # e.g. “SS限定烙印箱” vs catalog “SS限定烙印自选箱”.
            compact = name.replace("自选", "").replace(" ", "")
            for candidate in self.catalog:
                cname = self.s.clean(str(candidate.get("name") or ""))
                if compact and cname.replace("自选", "").replace(" ", "") == compact:
                    meta = dict(candidate)
                    break

        # Explicit item metadata wins, then catalog metadata, then safe prefix
        # inference.  This makes names such as “SS限定烙印箱” retain their SS
        # badge even when the catalog entry is not an exact textual match.
        rank = self.s.clean(str(item.get("rank_badge") or meta.get("rank_badge") or "")).upper()
        if not rank:
            rank = self._rank_from_name(name)
        if rank:
            meta["rank_badge"] = rank

        # Explicit item flag wins; catalog flag / item_type follows; names containing
        # “碎片” are inferred automatically so existing Excel files need no changes.
        if "is_fragment" in item:
            is_fragment = bool(item.get("is_fragment"))
        elif "fragment" in item:
            is_fragment = bool(item.get("fragment"))
        else:
            is_fragment = bool(meta.get("is_fragment")) or str(meta.get("item_type") or "").lower() == "fragment" or "碎片" in name
        meta["is_fragment"] = is_fragment

        icon_path = self.s.resolve_path(self.cfg, meta.get("icon") or item.get("icon"))
        quality = str(meta.get("quality") or item.get("quality") or "").lower().strip()
        frame_path = self.s.resolve_path(self.cfg, self.quality_borders.get(quality)) if quality else None
        return {
            "item": item,
            "name": name,
            "meta": meta,
            "rank": rank,
            "is_fragment": is_fragment,
            "quality": quality,
            "icon_path": icon_path,
            "frame_path": frame_path,
        }

    @staticmethod
    def _custom_inset_box(box, inset):
        x1, y1, x2, y2 = map(int, box)
        try:
            inset = max(0, int(inset))
        except Exception:
            inset = 0
        inset = min(inset, max(0, min((x2 - x1) // 3, (y2 - y1) // 3)))
        return (x1 + inset, y1 + inset, x2 - inset, y2 - inset)

    def _draw_trimmed_contain(self, base, icon_path, box):
        try:
            src = Image.open(icon_path).convert("RGBA")
            alpha = src.getchannel("A")
            bbox = alpha.getbbox()
            if bbox:
                src = src.crop(bbox)
            x1, y1, x2, y2 = map(int, box)
            tw, th = max(1, x2 - x1), max(1, y2 - y1)
            src.thumbnail((tw, th), Image.LANCZOS)
            px = x1 + (tw - src.width) // 2
            py = y1 + (th - src.height) // 2
            base.alpha_composite(src, (int(px), int(py)))
            return True
        except Exception:
            return False

    def _rank_badge_asset_exists(self, rank):
        if not rank:
            return False
        mapping = self.cfg.get("item_rank_badges") or {}
        if not isinstance(mapping, dict):
            return False
        raw = mapping.get(rank) or mapping.get(rank.lower())
        if isinstance(raw, str):
            path = raw
        elif isinstance(raw, dict):
            path = raw.get("path")
        else:
            path = None
        resolved = self.s.resolve_path(self.cfg, path) if path else None
        return bool(resolved and Path(resolved).exists())

    def _draw_rank_badge(self, base, box, resolved):
        rank = resolved.get("rank") or ""
        if not rank:
            return

        meta = resolved.get("meta") or {}
        if self._rank_badge_asset_exists(rank):
            # Canonical engine helper, so positioning/scaling stays consistent
            # with the classic renderer.
            self.s.draw_item_rank_badge(base, box, meta, self.cfg)
            return

        # Safe visual fallback: never silently lose S / SS / SSS just because
        # the optional image asset is absent.
        x1, y1, x2, y2 = map(int, box)
        # Match the canonical image-badge positioning: quality frames are drawn
        # as a centered square even when the surrounding reward card is wide.
        # Anchoring the text fallback to the raw card box put the S badge on the
        # far-left edge of the card instead of the lower-left of the item frame.
        raw_w = max(1, x2 - x1)
        raw_h = max(1, y2 - y1)
        side = max(1, min(raw_w, raw_h))
        x1 = x1 + (raw_w - side) // 2
        x2 = x1 + side
        y1 = y1 + (raw_h - side) // 2
        y2 = y1 + side
        h = max(1, int(round(side * 0.30)))
        font = self.s.get_font(max(1, int(round(h * 0.70))), True)
        d = ImageDraw.Draw(base)
        tw = self.s.text_width(d, rank, font)
        pad_x = max(2, int(round(side * 0.07)))
        w = max(h, int(round(tw + pad_x * 2)))
        visual = self.cfg.get("reward_item_visual") or {}
        if not isinstance(visual, dict):
            visual = {}
        try:
            ox_ratio = float(visual.get("rank_badge_offset_x_ratio", -0.03))
        except Exception:
            ox_ratio = -0.03
        try:
            oy_ratio = float(visual.get("rank_badge_offset_y_ratio", 0.03))
        except Exception:
            oy_ratio = 0.03
        bx1 = x1 + int(round(side * ox_ratio))
        by2 = y2 + int(round(side * oy_ratio))
        by1 = by2 - h
        bx2 = bx1 + w
        d.rounded_rectangle(
            (bx1, by1, bx2, by2),
            radius=max(3, h // 4),
            fill="#1A1720",
            outline="#FFD45A",
            width=1,
        )
        bb = d.textbbox((0, 0), rank, font=font)
        th = bb[3] - bb[1]
        ty = by1 + (h - th) / 2 - bb[1]
        d.text((bx1 + (w - tw) / 2, ty), rank, font=font, fill="#FFF3BA")

    def _draw_fragment_badge(self, base, box, resolved):
        if not resolved.get("is_fragment"):
            return
        meta = dict(resolved.get("meta") or {})
        meta["is_fragment"] = True
        self.s.draw_item_fragment_badge(base, box, meta, self.cfg)

    def draw_icon(
        self,
        base,
        item,
        box,
        *,
        draw_quality_frame=True,
        assume_quality_frame=False,
        frame_inset=None,
        plain_inset=None,
        trim_transparent=False,
        draw_rank=True,
    ):
        """Draw one reward item using the shared standard artwork rules.

        Returns the resolved metadata dict so the caller can handle placeholders
        or theme-specific text colours without repeating metadata lookup.
        """
        resolved = self.resolve(item)
        icon_path = resolved.get("icon_path")
        frame_path = resolved.get("frame_path")

        has_real_frame = bool(frame_path and Path(frame_path).exists())
        if draw_quality_frame and has_real_frame:
            self.s.draw_image_contain(base, Path(frame_path), box)

        # Any reward that *intends* to use a quality frame is a standard reward
        # component.  Its internal geometry is global and must not vary by theme:
        # quality frame = 100%, icon = reward_item_visual.icon_ratio_in_frame,
        # with rank/fragment badges anchored to the same outer box.
        #
        # ``frame_inset`` is intentionally retained in the public signature for
        # backward compatibility, but no longer changes framed rewards.  Special
        # frameless styles (handwritten stickers, explicitly frame-less themes)
        # may still use ``plain_inset`` to own their artwork treatment.
        intends_quality_frame = bool(draw_quality_frame and resolved.get("quality"))
        framed_for_inset = bool(intends_quality_frame or assume_quality_frame)
        if framed_for_inset:
            content_box = self.s.reward_icon_content_box(box, True, self.cfg)
        elif plain_inset is not None:
            content_box = self._custom_inset_box(box, plain_inset)
        else:
            content_box = self.s.reward_icon_content_box(box, False, self.cfg)

        if icon_path and Path(icon_path).exists():
            ok = False
            if trim_transparent:
                ok = self._draw_trimmed_contain(base, Path(icon_path), content_box)
            if not ok:
                self.s.draw_image_contain(base, Path(icon_path), content_box)

        if draw_rank:
            self._draw_rank_badge(base, box, resolved)
        self._draw_fragment_badge(base, box, resolved)
        return resolved

    def compose_art(
        self,
        item,
        canvas_size=160,
        *,
        include_quality_frame=False,
        trim_transparent=False,
        margin_ratio=0.08,
    ):
        """Return transparent RGBA artwork suitable for later style treatment.

        Handwritten themes use this with ``include_quality_frame=False`` and then
        add the notebook sticker outline around the *combined icon + rank badge*.
        """
        try:
            side = max(64, int(canvas_size))
        except Exception:
            side = 160
        layer = Image.new("RGBA", (side, side), (0, 0, 0, 0))
        margin = max(8, int(round(side * float(margin_ratio))))
        box = (margin, margin, side - margin, side - margin)
        resolved = self.draw_icon(
            layer,
            item,
            box,
            draw_quality_frame=include_quality_frame,
            assume_quality_frame=include_quality_frame,
            trim_transparent=trim_transparent,
            draw_rank=True,
        )
        if not resolved.get("icon_path") or not Path(resolved.get("icon_path")).exists():
            return None
        alpha = layer.getchannel("A")
        bbox = alpha.getbbox()
        if not bbox:
            return layer
        x1, y1, x2, y2 = bbox
        pad = 2
        return layer.crop((max(0, x1 - pad), max(0, y1 - pad), min(side, x2 + pad), min(side, y2 + pad)))
