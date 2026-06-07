"""Build a GitHub social preview image from the Robot Escape Room sim hero.

The output is ``docs/images/social_preview.png``. Upload that PNG in
GitHub repository settings as the social preview image.

The preview frames a still from the README hero
(``robot_escape_room.gif`` — the Foxglove/RViz-style live simulation) so
a shared link unfurls the escape-game demo at a glance: stacked-floor map,
``/tf`` robot motion, mission HUD, and event log.

Run from the repository root:

    python examples/build_social_preview.py
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).parent
ROOT = HERE.parent
# Mid-run frame: route is green, HUD populated, robot mid-leg on the map.
DEMO_GIF = ROOT / "docs" / "images" / "robot_escape_room.gif"
DEMO_FRAME_INDEX = 80
OUT_PATH = ROOT / "docs" / "images" / "social_preview.png"

W, H = 1280, 640
INK = (248, 250, 252)
MUTED = (148, 163, 184)
PANEL = (15, 23, 42)
ACCENT = (34, 211, 238)
AMBER = (245, 158, 11)
GREEN = (34, 197, 94)
PURPLE = (168, 85, 247)


def _font(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold
        else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf" if bold
        else "/usr/share/fonts/dejavu/DejaVuSans.ttf",
    ]
    for raw in paths:
        path = Path(raw)
        if path.exists():
            return ImageFont.truetype(str(path), size)
    return ImageFont.load_default()


FONT_TITLE = _font(42, bold=True)
FONT_SUB = _font(28)
FONT_SMALL = _font(21)
FONT_BADGE = _font(20, bold=True)


def _rounded(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int, int, int],
    radius: int,
    fill,
    outline=None,
    width: int = 1,
) -> None:
    draw.rounded_rectangle(xy, radius=radius, fill=fill, outline=outline, width=width)


def _load_demo_frame() -> Image.Image:
    if not DEMO_GIF.exists():
        raise FileNotFoundError(
            f"{DEMO_GIF} does not exist; regenerate the hero with "
            "`python examples/record_escape_room_sim.py`"
        )
    gif = Image.open(DEMO_GIF)
    gif.seek(min(DEMO_FRAME_INDEX, gif.n_frames - 1))
    return gif.convert("RGB")


def _badge(draw: ImageDraw.ImageDraw, x: int, y: int, label: str, color) -> int:
    tw = int(draw.textlength(label, font=FONT_BADGE))
    _rounded(draw, (x, y, x + tw + 34, y + 40), 20, (30, 41, 59), color, 2)
    draw.ellipse((x + 14, y + 14, x + 24, y + 24), fill=color)
    draw.text((x + 32, y + 8), label, font=FONT_BADGE, fill=INK)
    return x + tw + 34


def main() -> None:
    frame = _load_demo_frame()

    img = Image.new("RGB", (W, H), (7, 11, 21))
    draw = ImageDraw.Draw(img)

    for x in range(0, W, 44):
        draw.line([(x, 0), (x - 120, H)], fill=(30, 41, 59), width=1)
    for y in range(0, H, 44):
        draw.line([(0, y), (W, y)], fill=(30, 41, 59), width=1)

    draw.text((54, 36), "robot-escape-room", font=FONT_TITLE, fill=INK)
    draw.text(
        (58, 98), "Every cost function, one self-solving escape game",
        font=FONT_SUB, fill=MUTED,
    )
    draw.text(
        (58, 136),
        "1280×720 dashboard: map/tf · topics · waypoints · timeline",
        font=FONT_SMALL, fill=MUTED,
    )
    bx = 58
    for label, color in (
        ("block_edges", AMBER),
        ("resolve_goal", PURPLE),
        ("prefer_elevator", ACCENT),
        ("escaped", GREEN),
    ):
        bx = _badge(draw, bx, 176, label, color) + 12

    panel = (40, 232, 1240, 620)
    _rounded(draw, panel, 22, PANEL, (51, 65, 85), 2)
    inner_w = panel[2] - panel[0] - 36
    fw, fh = frame.size
    scaled_h = round(inner_w * fh / fw)
    hero = frame.resize((inner_w, scaled_h), Image.Resampling.LANCZOS)
    px = panel[0] + 18
    py = panel[1] + ((panel[3] - panel[1]) - scaled_h) // 2
    img.paste(hero, (px, py))
    draw.rectangle((px, py, px + inner_w - 1, py + scaled_h - 1),
                   outline=(71, 85, 105), width=1)

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    img.save(OUT_PATH, optimize=True)
    print(f"wrote {OUT_PATH.relative_to(ROOT)} ({OUT_PATH.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
