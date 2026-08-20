"""Text-color mask for D2R tooltips.

Tooltip text uses a small fixed palette (white/gray, magic blue, set green,
rare yellow, unique gold, crafted orange, red). Masking by these colors
removes most background noise (item icons, scenery) before detection/OCR.
"""
import cv2
import numpy as np

# (B, G, R), per-channel tolerance
_PALETTE = [
    ((255, 255, 255), 80),   # white
    ((180, 180, 180), 55),   # gray (unmet reqs dimmed, misc)
    ((255, 105, 105), 70),   # magic blue
    ((0, 252, 0), 80),       # set green
    ((100, 255, 255), 70),   # rare yellow
    ((119, 179, 199), 55),   # unique/set-bonus gold
    ((0, 168, 255), 60),     # crafted orange
    ((77, 77, 255), 70),     # red (requirements not met)
]


def text_mask(img_bgr):
    """Binary mask (uint8 0/255) of pixels matching tooltip text colors."""
    img = img_bgr.astype(np.int16)
    mask = np.zeros(img.shape[:2], dtype=bool)
    for (b, g, r), tol in _PALETTE:
        m = (
            (np.abs(img[:, :, 0] - b) < tol)
            & (np.abs(img[:, :, 1] - g) < tol)
            & (np.abs(img[:, :, 2] - r) < tol)
        )
        mask |= m
    # Text pixels must also be reasonably bright OR strongly colored;
    # drop very dark matches (shadowy background).
    bright = img_bgr.max(axis=2) > 90
    mask &= bright
    return (mask.astype(np.uint8)) * 255


def classify_line_quality(img_bgr, box, pad=3):
    """Classify one text line (x, y, w, h box in img coordinates) by color.

    Used with OCR word boxes: the box tightly wraps the item-name text, so a
    simple dominant-palette-color vote is reliable. Returns a quality string
    or None.
    """
    if img_bgr is None or img_bgr.size == 0 or not box:
        return None
    H, W = img_bgr.shape[:2]
    x, y, w, h = box
    x0, y0 = max(0, int(x) - pad), max(0, int(y) - pad)
    x1, y1 = min(W, int(x + w) + pad), min(H, int(y + h) + pad)
    if x1 <= x0 or y1 <= y0:
        return None
    region = img_bgr[y0:y1, x0:x1].astype(np.int16)
    bright = img_bgr[y0:y1, x0:x1].max(axis=2) > 90

    counts = {}
    for quality, (b, g, r), tol in _QUALITY_PALETTE:
        m = (
            (np.abs(region[:, :, 0] - b) < tol)
            & (np.abs(region[:, :, 1] - g) < tol)
            & (np.abs(region[:, :, 2] - r) < tol)
            & bright
        )
        counts[quality] = counts.get(quality, 0) + int(m.sum())

    total = sum(counts.values())
    if total < 20:
        return None
    quality, count = max(counts.items(), key=lambda kv: kv[1])
    if count < 20 or count < 0.5 * total:
        return None
    return quality


def line_is_unmet(img_bgr, box, pad=3):
    """True when the text line renders RED — the game paints requirement
    lines red when the character does not meet them."""
    if img_bgr is None or img_bgr.size == 0 or not box:
        return False
    H, W = img_bgr.shape[:2]
    x, y, w, h = box
    x0, y0 = max(0, int(x) - pad), max(0, int(y) - pad)
    x1, y1 = min(W, int(x + w) + pad), min(H, int(y + h) + pad)
    if x1 <= x0 or y1 <= y0:
        return False
    region = img_bgr[y0:y1, x0:x1].astype(np.int16)
    bright = img_bgr[y0:y1, x0:x1].max(axis=2) > 90
    red = ((np.abs(region[:, :, 0] - 77) < 70)
           & (np.abs(region[:, :, 1] - 77) < 70)
           & (np.abs(region[:, :, 2] - 255) < 70) & bright)
    text = np.zeros(region.shape[:2], dtype=bool)
    for (b, g, r), tol in _PALETTE:
        text |= ((np.abs(region[:, :, 0] - b) < tol)
                 & (np.abs(region[:, :, 1] - g) < tol)
                 & (np.abs(region[:, :, 2] - r) < tol))
    text &= bright
    n_red, n_text = int(red.sum()), int(text.sum())
    return n_red >= 20 and n_red > 0.5 * max(1, n_text)


# Item-name colors -> quality. Gold is Unique *or* Runeword (the parser
# disambiguates by name). Order matters only for readability.
_QUALITY_PALETTE = [
    ("Set", (0, 252, 0), 80),
    ("Magic", (255, 105, 105), 70),
    ("Rare", (100, 255, 255), 55),
    ("Unique", (119, 179, 199), 50),
    ("Crafted", (0, 168, 255), 55),
    ("Base", (255, 255, 255), 55),
    ("Base", (180, 180, 180), 45),
]


