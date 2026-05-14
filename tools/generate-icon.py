"""Render the menu-bar template icon.

macOS template images are monochrome (black on transparent); the system
inverts them automatically for the dark menu bar. We render at 44 px to
look crisp on retina; rumps scales it to the menu-bar height.

Run once after changes to the icon design:
    .venv/bin/python tools/generate-icon.py
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parent.parent / "src" / "aa2g" / "assets" / "menubar.png"

SIZE = 44   # @2x size; rumps scales to ~22 in the menu bar
PAD = 4     # safe area to keep the glyph from clipping
INK = (0, 0, 0, 255)


def render(path: Path) -> None:
    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Notehead: filled ellipse, tilted left like a printed eighth note.
    head_w, head_h = 16, 12
    head_left = PAD
    head_top = SIZE - PAD - head_h
    draw.ellipse(
        (head_left, head_top, head_left + head_w, head_top + head_h),
        fill=INK,
    )

    # Stem: vertical bar rising from the right side of the notehead.
    stem_x = head_left + head_w - 3
    stem_top = PAD
    stem_bottom = head_top + head_h // 2
    draw.rectangle((stem_x, stem_top, stem_x + 3, stem_bottom), fill=INK)

    # Flag: a curl off the top of the stem, drawn as two stacked triangles.
    flag_tip_x = SIZE - PAD
    flag_top = (stem_x + 3, stem_top)
    flag_mid = (flag_tip_x, stem_top + 8)
    flag_low = (stem_x + 3, stem_top + 12)
    draw.polygon([flag_top, flag_mid, flag_low], fill=INK)

    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path, format="PNG", optimize=True)
    print(f"wrote {path} ({SIZE}x{SIZE})")


if __name__ == "__main__":
    render(OUT)
