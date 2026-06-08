"""Burn readable captions onto Foxglove capture frames for the README hero.

Maps each PNG frame to the escape-room timeline proportionally and draws a
title bar, status line, and colour legend so the 3D replay is self-explanatory
at README width.

    python scripts/foxglove_hero/overlay_escape_room_frames.py /tmp/erframes
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[2]
TIMELINE_PATH = ROOT / "docs/foxglove/robot_escape_room_timeline.json"

BG = (8, 14, 28)
BAR = (12, 22, 42)
TEXT = (248, 250, 252)
MUTED = (148, 163, 184)
CYAN = (34, 211, 238)
PINK = (244, 63, 94)
RED = (248, 113, 113)
GREEN = (34, 197, 94)
AMBER = (245, 158, 11)


def _font(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    family = "DejaVuSans-Bold" if bold else "DejaVuSans"
    for raw in (
        f"/usr/share/fonts/truetype/dejavu/{family}.ttf",
        f"/usr/share/fonts/dejavu/{family}.ttf",
    ):
        path = Path(raw)
        if path.exists():
            return ImageFont.truetype(str(path), size)
    return ImageFont.load_default()


FONT_TITLE = _font(26, bold=True)
FONT_STATUS = _font(22, bold=True)
FONT_LEGEND = _font(16)
FONT_BADGE = _font(14, bold=True)


def _load_timeline() -> list[dict]:
    data = json.loads(TIMELINE_PATH.read_text(encoding="utf-8"))
    return data["frames"]


def _caption_at(frames: list[dict], idx: int, total: int) -> dict:
    if not frames or total <= 0:
        return {"turn": 0, "caption": "", "detail": ""}
    t_idx = min(int(idx * len(frames) / total), len(frames) - 1)
    return frames[t_idx]


def _round_rect(draw, xy, radius, fill, outline=None, width=1):
    draw.rounded_rectangle(xy, radius=radius, fill=fill, outline=outline, width=width)


def _legend_chip(draw, x, y, color, label):
    _round_rect(draw, (x, y, x + 148, y + 28), 10, (18, 30, 52), (51, 65, 85), 1)
    draw.ellipse((x + 10, y + 9, x + 22, y + 21), fill=color)
    draw.text((x + 30, y + 5), label, font=FONT_BADGE, fill=TEXT)


def annotate(path: Path, meta: dict) -> None:
    img = Image.open(path).convert("RGBA")
    w, h = img.size
    top_h, bot_h = 56, 64
    out = Image.new("RGBA", (w, h + top_h + bot_h), BG)
    out.paste(img, (0, top_h))

    draw = ImageDraw.Draw(out, "RGBA")
    draw.rectangle((0, 0, w, top_h), fill=BAR)
    draw.rectangle((0, h + top_h, w, h + top_h + bot_h), fill=BAR)
    draw.line([(0, top_h), (w, top_h)], fill=(51, 65, 85), width=2)
    draw.line([(0, h + top_h), (w, h + top_h)], fill=(51, 65, 85), width=2)

    draw.text((18, 14), "robot-escape-room", font=FONT_TITLE, fill=TEXT)
    draw.text((300, 18), "3D sim · real A* replan each turn", font=FONT_LEGEND, fill=MUTED)

    _round_rect(draw, (w - 108, 12, w - 18, 42), 14, (6, 78, 59), (45, 212, 191), 1)
    draw.text((w - 63, 18), "live", font=FONT_BADGE, fill=(167, 243, 208), anchor="ma")

    caption = meta.get("caption", "")
    detail = meta.get("detail", "")
    turn = meta.get("turn", 0)
    draw.text((18, h + top_h + 10), f"Turn {turn}", font=FONT_STATUS, fill=AMBER)
    draw.text((110, h + top_h + 10), caption, font=FONT_STATUS, fill=TEXT)
    if detail:
        draw.text((18, h + top_h + 36), detail, font=FONT_LEGEND, fill=MUTED)

    lx = w - 620
    _legend_chip(draw, lx, 14, CYAN, "cyan = traveled")
    _legend_chip(draw, lx + 158, 14, PINK, "pink = planned")
    _legend_chip(draw, lx + 316, 14, RED, "red = locked")

    out.convert("RGB").save(path)


def main() -> None:
    frames_dir = Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/erframes")
    timeline = _load_timeline()
    paths = sorted(frames_dir.glob("f*.png"))
    if not paths:
        raise SystemExit(f"no frames in {frames_dir}")

    for idx, path in enumerate(paths):
        annotate(path, _caption_at(timeline, idx, len(paths)))
    print(f"annotated {len(paths)} frames in {frames_dir}")


if __name__ == "__main__":
    main()
