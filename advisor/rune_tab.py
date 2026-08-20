"""Read the stash RUNES tab in one shot and set the season-goal counts.

The tab lays all 33 runes out in a fixed reading order (El … Zod), each
cell showing its count; runes you don't own are grayed out. A one-time
4-point calibration (first cell, END of the top row, the cell BELOW the
first, the LAST cell) pins the lattice; the pitch is then refined from
the image itself and anchors snap to cell centers.

Per cell: OCR the count digits (tesseract, digit whitelist); when no
digits read, brightness decides owned=1 vs grayed=0.
"""
import re

import cv2
import numpy as np

from advisor.knowledge import RUNE_ORDER




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


def _digit_clusters(bw):
    """Runs of tightly-spaced glyphs, RIGHTMOST first. The game
    right-aligns counts to the cell border, so the number is usually the
    right-anchored cluster; stone-art highlights split off at the gaps
    and are tried later only if the better clusters fail to OCR."""
    n, _lbl, stats, _c = cv2.connectedComponentsWithStats(bw)
    H = bw.shape[0]
    comps = [tuple(stats[i]) for i in range(1, n)
             if 0.25 * H <= stats[i][3] <= 0.95 * H and stats[i][4] >= 12]
    if not comps:
        return []
    comps.sort(key=lambda s: s[0])
    heights = [c[3] for c in comps]
    gap_max = max(12, int(0.9 * (sum(heights) / len(heights))))
    groups = [[comps[0]]]
    for c in comps[1:]:
        prev = groups[-1][-1]
        if c[0] - (prev[0] + prev[2]) <= gap_max:
            groups[-1].append(c)
        else:
            groups.append([c])
    boxes = []
    for grp in reversed(groups):  # rightmost first
        boxes.append((min(c[0] for c in grp), min(c[1] for c in grp),
                      max(c[0] + c[2] for c in grp),
                      max(c[1] + c[3] for c in grp)))
    return boxes


def _baseline_group(bw):
    """Digit glyphs of the count in a WIDE bottom band: the count is
    right-anchored, so the rightmost valid glyph fixes the text baseline;
    sprite highlights sit above it and are dropped by the overlap test.
    Returns the left-to-right component list, or None."""
    n, _lbl, stats, _c = cv2.connectedComponentsWithStats(bw)
    H = bw.shape[0]
    comps = [tuple(stats[i]) for i in range(1, n)
             if 0.25 * H <= stats[i][3] <= 0.85 * H and stats[i][4] >= 12]
    if not comps:
        return None
    ref = max(comps, key=lambda s: s[0] + s[2])
    ry0, ry1 = ref[1], ref[1] + ref[3]
    keep = [c for c in comps
            if min(ry1, c[1] + c[3]) - max(ry0, c[1])
            >= 0.5 * min(ref[3], c[3])]
    keep.sort(key=lambda s: s[0])
    gap = max(12, int(1.2 * ref[3]))
    grp = [keep[-1]]
    for c in reversed(keep[:-1]):
        if grp[0][0] - (c[0] + c[2]) <= gap:
            grp.insert(0, c)
        else:
            break
    return grp


def _ocr_digits_band(crop, tesseract_cmd=None):
    """Count OCR for cells where the sprite bleeds into the digit zone
    (gems): find the baseline glyph group, OCR its bbox, validate the
    digit count against the glyph count, and rescue per glyph — a bare
    stem is a '1' tesseract refuses to read on its own. Tuned to 35/35
    on a raw 4K gems-tab frame."""
    try:
        import os
        import pytesseract
        from d2rlootreader.cfg import TESSDATA_DIR
        if tesseract_cmd:
            pytesseract.pytesseract.tesseract_cmd = tesseract_cmd
        os.environ["TESSDATA_PREFIX"] = str(TESSDATA_DIR)
        g = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        g = cv2.resize(g, None, fx=4, fy=4, interpolation=cv2.INTER_CUBIC)

        def read(image, psm=7):
            txt = pytesseract.image_to_string(
                image, lang="d2r",
                config=f"--psm {psm} -c tessedit_char_whitelist=0123456789")
            m = re.search(r"\d+", txt or "")
            return m.group(0) if m else None

        def glyph(bw, c):
            x, y, ww, hh, _a = c
            if ww <= 0.45 * hh:
                return "1"
            pad = 10
            return read(255 - bw[max(0, y - pad):y + hh + pad,
                                 max(0, x - pad):x + ww + pad], psm=10)

        for thresh in (210, 235):
            _, bw = cv2.threshold(g, thresh, 255, cv2.THRESH_BINARY)
            if cv2.countNonZero(bw) < 8:
                continue
            grp = _baseline_group(bw)
            if not grp:
                continue
            x0 = min(c[0] for c in grp)
            y0 = min(c[1] for c in grp)
            x1 = max(c[0] + c[2] for c in grp)
            y1 = max(c[1] + c[3] for c in grp)
            pad = 14
            got = read(255 - bw[max(0, y0 - pad):y1 + pad,
                                max(0, x0 - pad):x1 + pad])
            if got and len(got) == len(grp):
                return int(got)
            digits = [glyph(bw, c) for c in grp]
            if all(digits):
                return int("".join(digits))
            if got:
                return int(got)
        return None
    except Exception:
        return None


def _ocr_digits(crop, tesseract_cmd=None):
    """Count digits use the game font — the bundled d2r model reads them
    where eng failed. Threshold 210 won a grid search on a real 4K
    frame; 235 is the fallback for brighter render settings."""
    try:
        import os
        import pytesseract
        from d2rlootreader.cfg import TESSDATA_DIR
        if tesseract_cmd:
            pytesseract.pytesseract.tesseract_cmd = tesseract_cmd
        os.environ["TESSDATA_PREFIX"] = str(TESSDATA_DIR)
        g = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        g = cv2.resize(g, None, fx=4, fy=4, interpolation=cv2.INTER_CUBIC)
        def read(image):
            txt = pytesseract.image_to_string(
                image, lang="d2r",
                config="--psm 7 -c tessedit_char_whitelist=0123456789")
            m = re.search(r"\d+", txt or "")
            return m.group(0) if m else None

        for thresh in (210, 235):
            _, bw = cv2.threshold(g, thresh, 255, cv2.THRESH_BINARY)
            if cv2.countNonZero(bw) < 8:
                continue
            # proven primary: the whole (narrow) zone — live-verified;
            # the glyph-cluster pass only RESCUES cells that read nothing
            got = read(255 - bw)
            if got is None:
                for x0, y0, x1, y1 in _digit_clusters(bw)[:2]:
                    pad = 14
                    sub = 255 - bw[max(0, y0 - pad):y1 + pad,
                                   max(0, x0 - pad):x1 + pad]
                    got = read(sub)
                    if got:
                        break
            if got:
                return int(got)
        return None
    except Exception:
        return None


# the mod's GEMS tab (user-verified): QUALITY per row (Chipped→Perfect
# top to bottom), TYPE per column starting with Diamond
GEM_QUALITIES = ["Chipped", "Flawed", "", "Flawless", "Perfect"]
GEM_TYPES = ["Diamond", "Emerald", "Ruby", "Topaz", "Amethyst", "Sapphire",
             "Skull"]
GEM_ORDER = [f"{q} {t}".strip() for q in GEM_QUALITIES for t in GEM_TYPES]


def scan_counted_tab(img, calib_pts, names, screen_rect=None,
                     tesseract_cmd=None, debug_out=None, band=False):
    """Generic fixed-layout counted tab (runes, gems): {name: count}.
    band=True uses the wide-band baseline OCR — needed for gems, whose
    bright sprites bleed into the narrow digit zone."""
    return _scan(img, calib_pts, names, screen_rect, tesseract_cmd,
                 debug_out=debug_out, band=band)



def _scan(img, calib_pts, names, screen_rect=None, tesseract_cmd=None,
          debug_out=None, band=False):
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
    if debug_out:
        # RAW frame too: annotation lines cross the digit zones and make
        # the annotated image useless for offline OCR tuning
        base = str(debug_out)
        raw_path = (base[:-4] + "_raw.png") if base.endswith(".png") \
            else base + "_raw.png"
        cv2.imwrite(raw_path, img)
    for rune, (cx, cy) in zip(names, centers):
        x, y = int(cx - off_x), int(cy - off_y)
        x0, x1 = max(0, x - half), min(w, x + half)
        y0, y1 = max(0, y - half), min(h, y + half)
        if x1 - x0 < 8 or y1 - y0 < 8:
            counts[rune] = 0
            continue
        crop = img[y0:y1, x0:x1]
        # counts render at the BOTTOM-RIGHT of the cell — the proven
        # narrow zone (14/14 live); the in-OCR cluster rescue handles
        # cells where this zone reads nothing. band mode widens the zone
        # left (2-digit counts start before the cell center) and relies
        # on baseline filtering to shed sprite highlights
        dz_x0 = int(max(0, cx - off_x + (-0.45 if band else 0.02) * px))
        dz_x1 = int(round(min(w, cx - off_x + 0.66 * px)))
        dz_y0 = int(max(0, cy - off_y + 0.05 * py))
        dz_y1 = int(round(min(h, cy - off_y + (0.62 if band else 0.60) * py)))
        digits_zone = img[dz_y0:dz_y1, dz_x0:dz_x1]
        ocr = _ocr_digits_band if band else _ocr_digits
        n = ocr(digits_zone, tesseract_cmd) if digits_zone.size else None
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
