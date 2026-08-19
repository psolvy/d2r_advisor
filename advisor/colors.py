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


def detect_title_quality(crop_bgr, debug_out=None):
    """Classify the tooltip's title line by its text color.

    Returns 'Unique' / 'Set' / 'Rare' / 'Magic' / 'Crafted' / 'Base',
    or None when no confident title line is found. Gold titles are reported
    as 'Unique' (runewords share the color).

    The crop usually has padding around the tooltip, and bright inventory
    icons can sit right above the title — so we segment the mask into
    text-*lines* and take the topmost blob that is line-shaped: wide,
    sparse (text, not a solid icon) and roughly centered in the crop.
    """
    if crop_bgr is None or crop_bgr.size == 0:
        return None
    h, w = crop_bgr.shape[:2]
    scale = max(0.5, h / 640.0)  # crop of a whole tooltip is ~640px at 1080p
    img = crop_bgr.astype(np.int16)
    bright = crop_bgr.max(axis=2) > 90

    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
    masks = {}
    for quality, (b, g, r), tol in _QUALITY_PALETTE:
        m = (
            (np.abs(img[:, :, 0] - b) < tol)
            & (np.abs(img[:, :, 1] - g) < tol)
            & (np.abs(img[:, :, 2] - r) < tol)
            & bright
        )
        m = cv2.morphologyEx(m.astype(np.uint8), cv2.MORPH_OPEN, kernel)
        if quality in masks:
            masks[quality] |= m.astype(bool)
        else:
            masks[quality] = m.astype(bool)

    any_mask = np.zeros((h, w), dtype=np.uint8)
    for m in masks.values():
        any_mask |= m.astype(np.uint8)

    # Merge characters into horizontal line blobs.
    k_line = cv2.getStructuringElement(cv2.MORPH_RECT, (max(15, int(24 * scale)), 3))
    lines_img = cv2.morphologyEx(any_mask * 255, cv2.MORPH_CLOSE, k_line)
    contours, _ = cv2.findContours(lines_img, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    boxes = []
    for c in contours:
        x, y, bw, bh = cv2.boundingRect(c)
        if bw < w * 0.22:                       # too narrow for a title line
            continue
        if bh > 42 * scale or bh < 5:           # not text-line shaped
            continue
        cx = x + bw / 2.0
        if not (w * 0.2 < cx < w * 0.8):        # titles are centered in the tooltip
            continue
        blob = any_mask[y:y + bh, x:x + bw]
        density = cv2.countNonZero(blob) / float(bw * bh)
        if density > 0.6:                       # solid = an icon, not text
            continue
        boxes.append((y, x, bw, bh))
    boxes.sort()

    # Topmost line-shaped blob that classifies confidently wins.
    for y, x, bw, bh in boxes[:3]:
        region = slice(y, y + bh), slice(x, x + bw)
        counts = {q: int(m[region].sum()) for q, m in masks.items()}
        total = sum(counts.values())
        if total < 25:
            continue
        quality, count = max(counts.items(), key=lambda kv: kv[1])
        if count < 25 or count < 0.5 * total:
            continue
        if debug_out is not None:
            debug_out["box"] = (x, y, bw, bh)
            debug_out["counts"] = counts
        return quality
    return None
