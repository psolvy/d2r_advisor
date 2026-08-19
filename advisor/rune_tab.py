"""Read the stash RUNES tab in one shot and set the season-goal counts.

The tab lays all 33 runes out in a fixed reading order (El … Zod), each
cell showing its count; runes you don't own are grayed out. A one-time
3-point calibration (hover the El cell, the LAST cell of the FIRST row,
then the LAST rune cell = Zod) pins the lattice — the column count is
solved from the three points, no manual grid math.

Per cell: OCR the count digits (tesseract, digit whitelist); when no
digits read, brightness decides owned=1 vs grayed=0.
"""
import re

import cv2
import numpy as np

from advisor.knowledge import RUNE_ORDER

CALIB_KEY = "runetab"  # [x_el, y_el, x_row_end, y_row_end, x_zod, y_zod]


def solve_lattice(p_el, p_row_end, p_zod, total=33):
    """(cols, pitch_x, pitch_y) from the three calibration points."""
    best = None
    for cols in range(4, 14):
        px = (p_row_end[0] - p_el[0]) / max(1, cols - 1)
        if px <= 4:
            continue
        rows = (total + cols - 1) // cols
        if rows < 2:
            continue
        last_col = (total - 1) % cols
        py = (p_zod[1] - p_el[1]) / (rows - 1)
        if py <= 4:
            continue
        err = abs((p_el[0] + last_col * px) - p_zod[0])
        if best is None or err < best[0]:
            best = (err, cols, px, py)
    if best is None:
        return None
    _err, cols, px, py = best
    return cols, px, py


def cell_centers(calib_pts, total=33):
    p_el = calib_pts[0:2]
    p_row_end = calib_pts[2:4]
    p_zod = calib_pts[4:6]
    got = solve_lattice(p_el, p_row_end, p_zod, total)
    if got is None:
        return None
    cols, px, py = got
    out = []
    for i in range(total):
        r, c = divmod(i, cols)
        out.append((p_el[0] + c * px, p_el[1] + r * py))
    return out, px, py


def _ocr_digits(crop, tesseract_cmd=None):
    """Count digits are small white glyphs with a dark outline in the
    cell corner — a plain WHITE threshold beats Otsu (the item art
    behind them wrecks a global threshold)."""
    try:
        import pytesseract
        if tesseract_cmd:
            pytesseract.pytesseract.tesseract_cmd = tesseract_cmd
        g = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        g = cv2.resize(g, None, fx=4, fy=4, interpolation=cv2.INTER_CUBIC)
        for thresh in (185, 150):
            _, bw = cv2.threshold(g, thresh, 255, cv2.THRESH_BINARY)
            if cv2.countNonZero(bw) < 8:
                continue
            bw = 255 - bw  # tesseract prefers dark text on light
            txt = pytesseract.image_to_string(
                bw, config="--psm 7 -c tessedit_char_whitelist=0123456789")
            m = re.search(r"\d+", txt or "")
            if m:
                return int(m.group(0))
        return None
    except Exception:
        return None


# the mod's GEMS tab: quality columns (Chipped→Perfect) × gem-type rows
GEM_QUALITIES = ["Chipped", "Flawed", "", "Flawless", "Perfect"]
GEM_TYPES = ["Amethyst", "Topaz", "Sapphire", "Emerald", "Ruby", "Diamond",
             "Skull"]
GEM_ORDER = [f"{q} {t}".strip() for t in GEM_TYPES for q in GEM_QUALITIES]


def scan_counted_tab(img, calib_pts, names, screen_rect=None,
                     tesseract_cmd=None, debug_out=None):
    """Generic fixed-layout counted tab (runes, gems): {name: count}."""
    return _scan(img, calib_pts, names, screen_rect, tesseract_cmd,
                 debug_out=debug_out)


def scan_rune_tab(img, calib_pts, screen_rect=None, tesseract_cmd=None):
    """{rune: count} read from a full-screen capture. img is BGR."""
    return _scan(img, calib_pts, RUNE_ORDER, screen_rect, tesseract_cmd)


def _scan(img, calib_pts, names, screen_rect=None, tesseract_cmd=None,
          debug_out=None):
    got = cell_centers(calib_pts, total=len(names))
    if got is None:
        return None
    centers, px, py = got
    off_x = screen_rect[0] if screen_rect else 0
    off_y = screen_rect[1] if screen_rect else 0
    cell = int(min(px, py))
    half = max(8, int(cell * 0.48))
    counts = {}
    h, w = img.shape[:2]
    dbg = img.copy() if debug_out else None
    for rune, (cx, cy) in zip(names, centers):
        x, y = int(cx - off_x), int(cy - off_y)
        x0, x1 = max(0, x - half), min(w, x + half)
        y0, y1 = max(0, y - half), min(h, y + half)
        if x1 - x0 < 8 or y1 - y0 < 8:
            counts[rune] = 0
            continue
        crop = img[y0:y1, x0:x1]
        # counts render in the BOTTOM-RIGHT corner of the cell
        ch, cw = crop.shape[:2]
        digits_zone = crop[int(ch * 0.55):, int(cw * 0.35):]
        n = _ocr_digits(digits_zone, tesseract_cmd)
        src = "ocr"
        if n is None:
            # no digits read: owned cells are bright, missing ones grayed
            g = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
            n = 1 if float(g.mean()) > 55 and float(g.std()) > 28 else 0
            src = "fb"
        counts[rune] = n
        if dbg is not None:
            color = (60, 220, 60) if src == "ocr" else (60, 160, 255)
            cv2.rectangle(dbg, (x0, y0), (x1, y1), color, 2)
            cv2.putText(dbg, f"{rune}:{n}", (x0 + 2, y0 + 16),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.45, color, 1,
                        cv2.LINE_AA)
    if dbg is not None:
        cv2.imwrite(str(debug_out), dbg)
    return counts
