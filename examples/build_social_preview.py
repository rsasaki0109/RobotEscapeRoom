"""Build a GitHub social preview image from the recorded demo GIF.

The output is ``docs/images/social_preview.png``. Upload that PNG in
GitHub repository settings as the social preview image.

Run from the repository root:

    python examples/build_social_preview.py
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).parent
ROOT = HERE.parent
DEMO_GIF = ROOT / "docs" / "images" / "18_semantic_navigation_demo.gif"
OUT_PATH = ROOT / "docs" / "images" / "social_preview.png"

W, H = 1280, 640
INK = (15, 23, 42)
MUTED = (71, 85, 105)
PANEL = (255, 255, 255)
ACCENT = (225, 29, 72)
TEAL = (14, 165, 233)


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


FONT_TITLE = _font(44, bold=True)
FONT_SUB = _font(30)
FONT_SMALL = _font(23)
FONT_BADGE = _font(22, bold=True)


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
            f"{DEMO_GIF} does not exist; run examples/record_semantic_navigation_demo.py first"
        )
    gif = Image.open(DEMO_GIF)
    gif.seek(56)
    return gif.convert("RGB")


def main() -> None:
    frame = _load_demo_frame()
    preview = frame.resize((527, 296), Image.Resampling.LANCZOS)

    img = Image.new("RGB", (W, H), (241, 245, 249))
    draw = ImageDraw.Draw(img)

    # Soft paper-like background grid.
    for x in range(0, W, 40):
        draw.line([(x, 0), (x, H)], fill=(226, 232, 240), width=1)
    for y in range(0, H, 40):
        draw.line([(0, y), (W, y)], fill=(226, 232, 240), width=1)

    _rounded(draw, (52, 64, 575, 576), 28, PANEL, (203, 213, 225), 2)
    draw.text((92, 111), "semantic-toponav", font=FONT_TITLE, fill=INK)
    draw.text((96, 205), "Semantic topological navigation", font=FONT_SUB, fill=MUTED)
    draw.text((96, 247), "for language goals, graph routes,", font=FONT_SUB, fill=MUTED)
    draw.text((96, 289), "waypoints, and fleet reservations.", font=FONT_SUB, fill=MUTED)

    badges = [
        ("resolve_goal", TEAL),
        ("A* topology route", ACCENT),
        ("semantic waypoints", (245, 158, 11)),
        ("ROS2/Nav2 adapter", (34, 197, 94)),
    ]
    bx, by = 96, 370
    for label, color in badges:
        tw = int(draw.textlength(label, font=FONT_BADGE))
        _rounded(draw, (bx, by, bx + tw + 34, by + 42), 21, (248, 250, 252), color, 2)
        draw.ellipse((bx + 14, by + 15, bx + 24, by + 25), fill=color)
        draw.text((bx + 32, by + 9), label, font=FONT_BADGE, fill=INK)
        by += 52

    _rounded(draw, (615, 64, 1228, 576), 28, PANEL, (203, 213, 225), 2)
    _rounded(draw, (647, 105, 1196, 536), 18, (15, 23, 42), None)
    draw.rectangle((669, 124, 1174, 164), fill=(255, 255, 255))
    draw.text((691, 132), "recorded demo from multi_floor_office.yaml", font=FONT_SMALL, fill=MUTED)
    img.paste(preview, (669, 176))
    draw.line([(669, 500), (1174, 500)], fill=ACCENT, width=6)

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    img.save(OUT_PATH, optimize=True)
    print(f"wrote {OUT_PATH.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
