#!/usr/bin/env python3
"""Generate the Aliasx app icon (icon.icns) with PIL + iconutil.

Design: a document whose name bar is highlighted, wrapped by a bold
rename arrow. Shapes only — no fonts — so it renders identically on any
machine, and the silhouette still reads at 16 px.
"""

from __future__ import annotations

import math
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent
SIZE = 1024

NAVY = (21, 24, 36, 255)
NAVY_SOFT = (38, 44, 62, 255)
YELLOW = (255, 210, 74, 255)
YELLOW_DARK = (219, 164, 28, 255)
PAPER = (246, 248, 252, 255)
PAPER_EDGE = (206, 213, 227, 255)
GRAY = (156, 165, 184, 255)


def arrow_head(draw, center, angle, size, fill):
    """Filled triangle at `center` pointing along `angle` (radians)."""
    tip = (center[0] + math.cos(angle) * size,
           center[1] + math.sin(angle) * size)
    left = (center[0] + math.cos(angle + 2.5) * size,
            center[1] + math.sin(angle + 2.5) * size)
    right = (center[0] + math.cos(angle - 2.5) * size,
             center[1] + math.sin(angle - 2.5) * size)
    draw.polygon([tip, left, right], fill=fill)


def build_document() -> Image.Image:
    """The sheet, on its own layer so it can be tilted as a whole."""
    w, h = 470, 610
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    fold = 120

    body = [(0, 0), (w - fold, 0), (w, fold), (w, h), (0, h)]
    d.polygon(body, fill=PAPER)
    d.line(body + [(0, 0)], fill=PAPER_EDGE, width=10, joint="curve")
    # folded corner
    d.polygon([(w - fold, 0), (w, fold), (w - fold, fold)], fill=PAPER_EDGE)

    # the file name, highlighted — this is the thing the app changes
    d.rounded_rectangle([54, 176, w - 96, 268], 30, fill=YELLOW,
                        outline=YELLOW_DARK, width=8)
    # the rest of the file, quiet
    for index, right in enumerate((w - 60, w - 120, w - 90)):
        top = 336 + index * 82
        d.rounded_rectangle([54, top, right, top + 44], 22, fill=GRAY)
    return img


def build_badge() -> Image.Image:
    """Round rename badge — a navy disc with a yellow arrow chasing itself.

    Kept as a separate, compact element rather than a big arc across the
    whole icon: at 16 px an arrow drawn over the sheet just merges with
    the highlighted name bar and both turn to mush.
    """
    size = 400
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    c, r = size // 2, size // 2 - 6
    d.ellipse([c - r, c - r, c + r, c + r], fill=NAVY)
    d.ellipse([c - r + 18, c - r + 18, c + r - 18, c + r - 18],
              fill=NAVY_SOFT)

    # Two arcs with their heads at opposite ends — the usual "cycle"
    # symbol. Both sweep clockwise, so both heads use the same tangent.
    ring, thick = r - 96, 40
    box = [c - ring, c - ring, c + ring, c + ring]
    for start, end in ((198, 330), (18, 150)):
        d.arc(box, start, end, fill=YELLOW, width=thick)
        a = math.radians(end + 10)
        point = (c + math.cos(a) * ring, c + math.sin(a) * ring)
        arrow_head(d, point, a + math.pi / 2, thick * 1.3, YELLOW)
    return img


def build_base() -> Image.Image:
    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    margin = 64
    draw.rounded_rectangle([margin, margin, SIZE - margin, SIZE - margin],
                           180, fill=NAVY)
    # soft inner panel so the white sheet is not floating on flat black
    draw.rounded_rectangle([margin + 46, margin + 46,
                            SIZE - margin - 46, SIZE - margin - 46],
                           140, fill=NAVY_SOFT)

    doc = build_document().rotate(5, expand=True, resample=Image.BICUBIC)
    img.alpha_composite(doc, (SIZE // 2 - doc.width // 2 - 54,
                              SIZE // 2 - doc.height // 2 - 66))

    badge = build_badge()
    img.alpha_composite(badge, (SIZE - badge.width - 122,
                                SIZE - badge.height - 122))
    return img


def main() -> int:
    base = build_base()
    iconset = HERE / "icon.iconset"
    iconset.mkdir(exist_ok=True)
    for px in (16, 32, 64, 128, 256, 512, 1024):
        base.resize((px, px), Image.LANCZOS).save(
            iconset / ("icon_%dx%d.png" % (px, px)))
        if px <= 512:
            base.resize((px * 2, px * 2), Image.LANCZOS).save(
                iconset / ("icon_%dx%d@2x.png" % (px, px)))
    base.save(HERE / "icon.png")
    subprocess.run(["iconutil", "-c", "icns", str(iconset),
                    "-o", str(HERE / "icon.icns")], check=True)
    print("wrote %s" % (HERE / "icon.icns"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
