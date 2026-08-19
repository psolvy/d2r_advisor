"""Tooltip detection.

The D2R tooltip is a column of bright, centered text lines over a dark
translucent box. Dark-box detection fails in dark scenes, so we detect the
*text cluster* instead: bright pixels, morphologically merged into lines and
then into blocks; the best block near the cursor is the tooltip.
"""
import cv2
import numpy as np

from advisor.colors import text_mask


def _text_bright(img_bgr):
    """Denoised mask of tooltip-text-colored pixels."""
    raw_mask = text_mask(img_bgr)
    return cv2.morphologyEx(raw_mask, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3)))


def _detect_blocks(bright, scale, block_h):
    """Merge characters into lines, lines into blocks; return bounding boxes."""
    k_line = cv2.getStructuringElement(cv2.MORPH_RECT, (max(15, int(26 * scale)), max(3, int(5 * scale))))
    k_block = cv2.getStructuringElement(cv2.MORPH_RECT, (max(3, int(6 * scale)), max(15, int(block_h * scale))))
    m = cv2.morphologyEx(bright, cv2.MORPH_CLOSE, k_line)
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, k_block)
    contours, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    return [cv2.boundingRect(c) for c in contours]


def _cursor_dist(box, cursor):
    if cursor is None:
        return 0.0
    x, y, w, h = box
    cx, cy = cursor
    dx = max(x - cx, cx - (x + w), 0)
    dy = max(y - cy, cy - (y + h), 0)
    return (dx * dx + dy * dy) ** 0.5


def _evaluate(bright, gray, boxes, scale, W, cursor):
    """Score candidate boxes. Returns (best, best_score, rejected_near_cursor).

    Scoring favors blocks that are near the cursor, reasonably large and —
    crucially — sit on a DARK background: real tooltips are translucent dark
    boxes, while icon grids / tab bars / HUD art are much brighter behind
    their text.

    rejected_near_cursor collects blocks that failed the filters but contain
    the cursor — usually the tooltip over-merged with a whole UI panel into
    one huge sparse block; the caller re-detects inside those.
    """
    best, best_score = None, 0.0
    rejected_near_cursor = []
    for x, y, w, h in boxes:
        if w < 110 * scale or h < 70 * scale:
            continue
        contains = (cursor is not None
                    and x <= cursor[0] <= x + w and y <= cursor[1] <= y + h)
        block = bright[y:y + h, x:x + w]
        density = cv2.countNonZero(block) / float(w * h)
        rows = (block.sum(axis=1) > 0).astype(np.uint8)
        row_groups = int(np.count_nonzero(np.diff(rows) == 1)) + int(rows[0])
        # Text blocks are sparse-ish (dense = UI art) and have several rows.
        ok = (w <= W * 0.7 and 0.03 <= density <= 0.55 and row_groups >= 3)
        if not ok:
            if contains and (density < 0.03 or w > W * 0.7):
                rejected_near_cursor.append((x, y, w, h))
            continue
        non_text = gray[y:y + h, x:x + w][block == 0]
        bg = float(non_text.mean()) if non_text.size else 255.0
        score = (float(w * h) ** 0.5
                 / (1.0 + _cursor_dist((x, y, w, h), cursor) / (100.0 * scale))
                 / (1.0 + max(0.0, bg - 25.0) / 10.0))
        if score > best_score:
            best_score, best = score, (x, y, w, h)
    return best, best_score, rejected_near_cursor


def find_tooltip(img_bgr, cursor=None):
    """Return (crop, (x, y, w, h)) of the most likely tooltip, or (None, None)."""
    H, W = img_bgr.shape[:2]
    scale = H / 1080.0
    bright = _text_bright(img_bgr)
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)

    boxes = _detect_blocks(bright, scale, 64)
    best, best_score, rejected = _evaluate(bright, gray, boxes, scale, W, cursor)

    # If the winner is far from the cursor while a rejected over-merged block
    # sits right under it (tooltip fused with an inventory/stash panel), split
    # that block with a tighter vertical kernel and look again inside it.
    if cursor is not None and rejected:
        best_dist = _cursor_dist(best, cursor) if best else float("inf")
        if best is None or best_dist > 150 * scale:
            for rx, ry, rw, rh in rejected:
                sub = bright[ry:ry + rh, rx:rx + rw]
                # 40*scale: wide enough to keep the title line attached to the
                # stats (line pitch ~28px at 1080p), narrow enough not to
                # re-fuse with panel headers ~90px away.
                sub_boxes = [(rx + bx, ry + by, bw, bh)
                             for bx, by, bw, bh in _detect_blocks(sub, scale, 40)]
                b2, s2, _ = _evaluate(bright, gray, sub_boxes, scale, W, cursor)
                if b2 is not None and _cursor_dist(b2, cursor) < best_dist:
                    best, best_score, best_dist = b2, s2, _cursor_dist(b2, cursor)

    if best is None:
        return None, None

    x, y, w, h = best
    # Generous padding: top rescues a missed title line; the sides rescue
    # clipped line ends ("Socketed (3" losing its number). Junk filters drop
    # any UI text that comes along with the extra area.
    pad_x, pad_top, pad_bottom = int(50 * scale), int(45 * scale), int(18 * scale)
    x0, y0 = max(0, x - pad_x), max(0, y - pad_top)
    x1, y1 = min(W, x + w + pad_x), min(H, y + h + pad_bottom)
    return img_bgr[y0:y1, x0:x1], (x0, y0, x1 - x0, y1 - y0)


def find_two_tooltips(img_bgr, cursor=None):
    """The game's Shift-compare shows TWO tooltips: the hovered item near
    the cursor and the equipped one over the paperdoll. Returns
    (hovered_crop, equipped_crop) — either may be None."""
    H, W = img_bgr.shape[:2]
    scale = H / 1080.0
    bright = _text_bright(img_bgr)
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    boxes = _detect_blocks(bright, scale, 64)

    scored = []
    for x, y, w, h in boxes:
        if w < 110 * scale or h < 70 * scale or w > W * 0.7:
            continue
        block = bright[y:y + h, x:x + w]
        density = cv2.countNonZero(block) / float(w * h)
        rows = (block.sum(axis=1) > 0).astype(np.uint8)
        row_groups = int(np.count_nonzero(np.diff(rows) == 1)) + int(rows[0])
        if not (0.03 <= density <= 0.55 and row_groups >= 3):
            continue
        non_text = gray[y:y + h, x:x + w][block == 0]
        bg = float(non_text.mean()) if non_text.size else 255.0
        if bg > 90:  # tooltips sit on dark translucent boxes
            continue
        scored.append(((x, y, w, h), float(w * h)))
    if not scored:
        return None, None
    scored.sort(key=lambda b: _cursor_dist(b[0], cursor))
    hovered = scored[0][0]

    def overlaps(a, b):
        ax, ay, aw, ah = a
        bx, by, bw, bh = b
        return ax < bx + bw and bx < ax + aw and ay < by + bh and by < ay + ah

    equipped = next((b for b, _a in scored[1:]
                     if not overlaps(b, hovered)), None)

    def crop(box):
        if box is None:
            return None
        x, y, w, h = box
        pad_x, pad_t, pad_b = int(50 * scale), int(45 * scale), int(18 * scale)
        x0, y0 = max(0, x - pad_x), max(0, y - pad_t)
        x1, y1 = min(W, x + w + pad_x), min(H, y + h + pad_b)
        return img_bgr[y0:y1, x0:x1]

    return crop(hovered), crop(equipped)


def fallback_region(img_bgr, cursor, width=760, height=640):
    """Fixed crop around the cursor when detection fails."""
    H, W = img_bgr.shape[:2]
    scale = H / 1080.0
    width, height = int(width * scale), int(height * scale)
    if cursor is None:
        return img_bgr, (0, 0, W, H)
    cx, cy = cursor
    x0 = max(0, min(W - width, cx - width // 2))
    y0 = max(0, min(H - height, cy - height + int(60 * scale)))
    return img_bgr[y0:y0 + height, x0:x0 + width], (x0, y0, width, height)
