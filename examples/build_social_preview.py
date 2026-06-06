"""Build a GitHub social preview image from the perception→navigation hero.

The output is ``docs/images/social_preview.png``. Upload that PNG in
GitHub repository settings as the social preview image.

The preview frames a single still of the README hero
(``25_visual_hero.gif``) as a full-width strip so a shared link unfurls
the whole loop at a glance — the robot's camera frame, the CLIP cosine
match against the place gallery, and the A* route filled in to the goal.

Run from the repository root:

    python examples/build_social_preview.py
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).parent
ROOT = HERE.parent
# The hero is wide (~3.4:1) and white-backed; frame 13 is the most
# legible single still — the full route is green and the goal is reached.
DEMO_GIF = ROOT / "docs" / "images" / "25_visual_hero.gif"
DEMO_FRAME_INDEX = 13
# Crop off the hero's own suptitle (top band); this preview supplies its
# own title, and the per-panel headings below it survive the crop.
HERO_CROP_TOP = 48
OUT_PATH = ROOT / "docs" / "images" / "social_preview.png"

W, H = 1280, 640
INK = (15, 23, 42)
MUTED = (71, 85, 105)
PANEL = (255, 255, 255)
ACCENT = (225, 29, 72)
TEAL = (14, 165, 233)
AMBER = (245, 158, 11)
GREEN = (22, 163, 74)


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
            f"{DEMO_GIF} does not exist; regenerate the hero with "
            "`python examples/record_visual_hero.py` (needs the [vlm,viz] extras)"
        )
    gif = Image.open(DEMO_GIF)
    gif.seek(min(DEMO_FRAME_INDEX, gif.n_frames - 1))
    frame = gif.convert("RGB")
    w, h = frame.size
    return frame.crop((0, HERO_CROP_TOP, w, h))


def _badge(
    draw: ImageDraw.ImageDraw, x: int, y: int, label: str, color
) -> int:
    """Draw a pill badge at ``(x, y)``; return its right edge."""
    tw = int(draw.textlength(label, font=FONT_BADGE))
    _rounded(draw, (x, y, x + tw + 34, y + 42), 21, (248, 250, 252), color, 2)
    draw.ellipse((x + 14, y + 15, x + 24, y + 25), fill=color)
    draw.text((x + 32, y + 9), label, font=FONT_BADGE, fill=INK)
    return x + tw + 34


def main() -> None:
    frame = _load_demo_frame()

    img = Image.new("RGB", (W, H), (241, 245, 249))
    draw = ImageDraw.Draw(img)

    # Soft paper-like background grid.
    for x in range(0, W, 40):
        draw.line([(x, 0), (x, H)], fill=(226, 232, 240), width=1)
    for y in range(0, H, 40):
        draw.line([(0, y), (W, y)], fill=(226, 232, 240), width=1)

    # --- title band -------------------------------------------------
    draw.text((54, 40), "semantic-toponav", font=FONT_TITLE, fill=INK)
    draw.text(
        (58, 104), "Perception → navigation, in one glance",
        font=FONT_SUB, fill=MUTED,
    )
    draw.text(
        (58, 146),
        "real CLIP:  camera frame → cosine match → grounded node → A* route",
        font=FONT_SMALL, fill=MUTED,
    )
    # A few stage badges, color-keyed to the hero panels.
    bx = 58
    for label, color in (
        ("camera", TEAL),
        ("CLIP cosine", AMBER),
        ("grounded node", ACCENT),
        ("route progress", GREEN),
    ):
        bx = _badge(draw, bx, 190, label, color) + 14

    # --- hero strip, full width ------------------------------------
    panel = (40, 248, 1240, 628)
    _rounded(draw, panel, 22, PANEL, (203, 213, 225), 2)
    inner_w = (panel[2] - panel[0]) - 36          # 18 px padding each side
    fw, fh = frame.size
    scaled_h = round(inner_w * fh / fw)
    hero = frame.resize((inner_w, scaled_h), Image.Resampling.LANCZOS)
    px = panel[0] + 18
    py = panel[1] + ((panel[3] - panel[1]) - scaled_h) // 2
    img.paste(hero, (px, py))
    draw.rectangle((px, py, px + inner_w - 1, py + scaled_h - 1),
                   outline=(203, 213, 225), width=1)

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    img.save(OUT_PATH, optimize=True)
    print(f"wrote {OUT_PATH.relative_to(ROOT)} ({OUT_PATH.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
