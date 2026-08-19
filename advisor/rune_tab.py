"""Read the stash RUNES tab in one shot and set the season-goal counts.

The tab lays all 33 runes out in a fixed reading order (El … Zod), each
cell showing its count; runes you don't own are grayed out. A one-time
3-point calibration (hover El, then its RIGHT NEIGHBOR Eld — that pins
the exact cell pitch — then the last cell Zod) fixes the lattice with
no column guessing.

Per cell: OCR the count digits (tesseract, digit whitelist); when no
digits read, brightness decides owned=1 vs grayed=0.
"""
import re

import cv2
import numpy as np

from advisor.knowledge import RUNE_ORDER

CALIB_KEY = "runetab"  # [x_el, y_el, x_row_end, y_row_end, x_zod, y_zod]


def solve_lattice(p_first, p_row_end, p_below, total=33):
    """(cols, pitch_x, pitch_y) from three unambiguous cells: the FIRST
    cell, the LAST cell of the FIRST row, and the cell DIRECTLY BELOW the
    first (start of row 2).

    pitch_y comes from one exact row step; the column count divides the
    LONG first-row distance (hover jitter spreads over cols-1 gaps, so a
    ±10px hover can no longer shift the whole grid by a column — the old
    3-point guess did exactly that on the user's 10x4 tab)."""
    pitch_y = float(p_below[1] - p_first[1])
    if pitch_y <= 4:
        return None
    row_w = float(p_row_end[0] - p_first[0])
    if row_w <= 4:
        return None
    cols = round(row_w / pitch_y) + 1  # cells are square
    if cols < 2:
        return None
    pitch_x = row_w / (cols - 1)
    return cols, pitch_x, pitch_y


def _autocorr_pitch(sig, lo, hi):
    """Dominant period of a 1-D edge signal within [lo, hi] pixels."""
    sig = sig.astype(np.float32)
    sig -= sig.mean()
    n = len(sig)
    lo, hi = max(8, int(lo)), min(int(hi), n // 2)
    if hi <= lo:
        return None
    best, best_v = None, -1e18
    for lag in range(lo, hi):
        v = float(np.dot(sig[:-lag], sig[lag:]) / (n - lag))
        if v > best_v:
            best_v, best = v, lag
    return best


def _refine_pitch(gray, p_a, p_b, rough, horizontal=True):
    """Measure the exact cell pitch from the IMAGE between two rough
    anchor points — hover jitter stops mattering entirely."""
    h, w = gray.shape[:2]
    band = int(max(10, rough * 0.35))
    if horizontal:
        y = int(p_a[1])
        y0, y1 = max(0, y - band), min(h, y + band)
        x0 = max(0, int(min(p_a[0], p_b[0]) - rough))
        x1 = min(w, int(max(p_a[0], p_b[0]) + rough))
        strip = gray[y0:y1, x0:x1].astype(np.float32)
        sig = np.abs(np.diff(strip, axis=1)).sum(axis=0)
    else:
        x = int(p_a[0])
        x0, x1 = max(0, x - band), min(w, x + band)
        y0 = max(0, int(min(p_a[1], p_b[1]) - rough))
        y1 = min(h, int(max(p_a[1], p_b[1]) + rough * 4))
        strip = gray[y0:y1, x0:x1].astype(np.float32)
        sig = np.abs(np.diff(strip, axis=0)).sum(axis=1)
    got = _autocorr_pitch(sig, rough * 0.55, rough * 1.7)
    return float(got) if got else None


def _snap_axis(sig, pos, pitch):
    """Snap a coordinate to the middle of its cell: cell BORDERS are edge
    peaks ~pitch apart; the center sits between the two nearest."""
    lo_l = int(max(0, pos - 0.80 * pitch))
    hi_l = int(max(0, pos - 0.20 * pitch))
    lo_r = int(min(len(sig) - 1, pos + 0.20 * pitch))
    hi_r = int(min(len(sig) - 1, pos + 0.80 * pitch))
    if hi_l <= lo_l or hi_r <= lo_r:
        return pos
    left = lo_l + int(np.argmax(sig[lo_l:hi_l]))
    right = lo_r + int(np.argmax(sig[lo_r:hi_r]))
    if right - left < 0.5 * pitch or right - left > 1.5 * pitch:
        return pos
    return (left + right) / 2.0


def _snap_anchor(gray, p, pitch):
    """(x, y) moved to the exact center of the hovered cell."""
    h, w = gray.shape[:2]
    band = int(max(6, pitch * 0.25))
    x, y = int(p[0]), int(p[1])
    y0, y1 = max(0, y - band), min(h, y + band)
    x0, x1 = max(0, x - int(1.2 * pitch)), min(w, x + int(1.2 * pitch))
    strip = gray[y0:y1, x0:x1].astype(np.float32)
    sig_x = np.abs(np.diff(strip, axis=1)).sum(axis=0)
    nx = x0 + _snap_axis(sig_x, x - x0, pitch)
    xx0, xx1 = max(0, x - band), min(w, x + band)
    yy0, yy1 = max(0, y - int(1.2 * pitch)), min(h, y + int(1.2 * pitch))
    vstrip = gray[yy0:yy1, xx0:xx1].astype(np.float32)
    sig_y = np.abs(np.diff(vstrip, axis=0)).sum(axis=1)
    ny = yy0 + _snap_axis(sig_y, y - yy0, pitch)
    return nx, ny


def cell_centers(calib_pts, total=33, img=None, screen_rect=None):
    """calib_pts: 8 numbers — first cell, first-row END, cell BELOW the
    first, LAST cell. The last cell is anchored to its hovered point
    verbatim (mods park Zod on its own row). When `img` is given, the
    pitch is REFINED from the image itself via autocorrelation."""
    if len(calib_pts) < 8:
        return None
    p_first = calib_pts[0:2]
    p_row_end = calib_pts[2:4]
    p_below = calib_pts[4:6]
    p_last = calib_pts[6:8]
    rough = float(p_below[1] - p_first[1])  # ~one cell, jittery
    if rough <= 4:
        return None
    px = py = rough
    if img is not None:
        off = screen_rect or (0, 0)
        a = (p_first[0] - off[0], p_first[1] - off[1])
        b = (p_row_end[0] - off[0], p_row_end[1] - off[1])
        c = (p_below[0] - off[0], p_below[1] - off[1])
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) \
            if img.ndim == 3 else img
        # 1) exact pitches from LONG autocorrelation strips (a whole row
        #    of cell borders is a strong periodic signal)
        px = _refine_pitch(gray, a, b, rough, horizontal=True) or rough
        far = (a[0], a[1] + 5 * px)
        py = _refine_pitch(gray, a, far, px, horizontal=False) or px
        if not (0.6 * px <= py <= 1.6 * px):
            py = px  # square cells — reject a bad vertical estimate
        # 2) snap the anchors onto their cell centers using the exact
        #    pitch; reject snaps that disagree with the lattice
        def snap(p, pitch):
            n = _snap_anchor(gray, p, pitch)
            if abs(n[0] - p[0]) > 0.45 * pitch \
                    or abs(n[1] - p[1]) > 0.45 * pitch:
                return p
            return n
        na = snap(a, px)
        nb = snap(b, px)
        nl = snap((p_last[0] - off[0], p_last[1] - off[1]), px)
        p_first = (na[0] + off[0], na[1] + off[1])
        p_row_end = (nb[0] + off[0], nb[1] + off[1])
        p_last = (nl[0] + off[0], nl[1] + off[1])
    row_w = float(p_row_end[0] - p_first[0])
    cols = max(2, round(row_w / px) + 1)
    px = row_w / (cols - 1)  # spread residual jitter over the whole row
    out = []
    for i in range(total):
        r, c2 = divmod(i, cols)
        out.append((p_first[0] + c2 * px, p_first[1] + r * py))
    out[-1] = (float(p_last[0]), float(p_last[1]))
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
        # digits are near-white; the stone art tops out ~190 — thresholds
        # below that read art blobs as digits
        for thresh in (200, 175):
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
    got = cell_centers(calib_pts, total=len(names), img=img,
                       screen_rect=screen_rect)
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
        digits_zone = crop[int(ch * 0.50):, int(cw * 0.28):]
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
