"""Generate assets/icon.ico — a gold gem on a dark plate, D2 style.

Draws with OpenCV and writes a multi-size ICO (PNG-compressed entries).

Usage:  python tools/gen_icon.py
"""
import struct
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "assets" / "icon.ico"
PREVIEW = ROOT / "assets" / "icon_preview.png"

GOLD = (119, 179, 199, 255)        # BGRA — D2 unique gold
GOLD_DARK = (60, 110, 140, 255)
GOLD_LIGHT = (170, 220, 235, 255)
BG = (18, 12, 26, 255)             # dark maroon plate
BORDER = (80, 130, 155, 255)


def draw(size):
    img = np.zeros((size, size, 4), np.uint8)
    s = size / 256.0

    def pt(x, y):
        return int(x * s), int(y * s)

    # rounded dark plate with gold border
    r = int(40 * s)
    cv2.rectangle(img, pt(8, 8), pt(248, 248), BG, -1, cv2.LINE_AA)
    for thickness, color in ((int(max(2, 10 * s)), BORDER),):
        cv2.rectangle(img, pt(8, 8), pt(248, 248), color, thickness, cv2.LINE_AA)
    # corner cut (D2 plaque feel)
    cv2.line(img, pt(8, 60), pt(60, 8), BORDER, int(max(2, 8 * s)), cv2.LINE_AA)
    cv2.line(img, pt(196, 248), pt(248, 196), BORDER, int(max(2, 8 * s)), cv2.LINE_AA)

    # gem: crown (trapezoid) + pavilion (triangle)
    crown = np.array([pt(70, 100), pt(186, 100), pt(216, 128), pt(40, 128)], np.int32)
    pav = np.array([pt(40, 128), pt(216, 128), pt(128, 224)], np.int32)
    cv2.fillPoly(img, [crown], GOLD_DARK, cv2.LINE_AA)
    cv2.fillPoly(img, [pav], GOLD, cv2.LINE_AA)
    # table facet
    table = np.array([pt(96, 100), pt(160, 100), pt(186, 128), pt(70, 128)], np.int32)
    cv2.fillPoly(img, [table], GOLD, cv2.LINE_AA)
    # facet lines
    lw = int(max(1, 5 * s))
    cv2.line(img, pt(40, 128), pt(216, 128), GOLD_LIGHT, lw, cv2.LINE_AA)
    cv2.line(img, pt(96, 100), pt(70, 128), GOLD_LIGHT, lw, cv2.LINE_AA)
    cv2.line(img, pt(160, 100), pt(186, 128), GOLD_LIGHT, lw, cv2.LINE_AA)
    cv2.line(img, pt(70, 128), pt(128, 224), GOLD_LIGHT, lw, cv2.LINE_AA)
    cv2.line(img, pt(186, 128), pt(128, 224), GOLD_LIGHT, lw, cv2.LINE_AA)
    # glint
    cv2.circle(img, pt(105, 112), int(max(2, 8 * s)), (255, 255, 255, 255), -1, cv2.LINE_AA)
    return img


def to_png_bytes(img):
    ok, buf = cv2.imencode(".png", img)
    if not ok:
        raise RuntimeError("png encode failed")
    return buf.tobytes()


def write_ico(path, sizes=(256, 48, 32, 16)):
    entries = []
    blobs = []
    offset = 6 + 16 * len(sizes)
    for size in sizes:
        png = to_png_bytes(draw(size))
        entries.append(struct.pack(
            "<BBBBHHII",
            size if size < 256 else 0, size if size < 256 else 0,
            0, 0, 1, 32, len(png), offset,
        ))
        blobs.append(png)
        offset += len(png)
    with open(path, "wb") as f:
        f.write(struct.pack("<HHH", 0, 1, len(sizes)))
        for e in entries:
            f.write(e)
        for b in blobs:
            f.write(b)


def main():
    OUT.parent.mkdir(exist_ok=True)
    write_ico(OUT)
    cv2.imwrite(str(PREVIEW), draw(256))
    print(f"written {OUT} and {PREVIEW}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
