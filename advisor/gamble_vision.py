"""Icon-based gamble offer recognition.

D2R's resurrected graphics show the gamble offer as item ICONS in the
vendor's 10x10 grid — there is no text to OCR. This module reads the offer
by template-matching the item icons (98 px/cell alpha PNGs, downloaded by
tools/get_gamble_icons.py) inside the grid located by the same 3-point
calibration the auto-clicker uses (Shift+F10 → Calibrate clicks).

Result: the 14 items WITH their grid positions — the strongest possible
input for the seed search.
"""
import cv2
import numpy as np

from advisor.autoclicker import calib_ok, load_calib, save_calib
from d2rlootreader.cfg import REPOSITORY_DIR

ICON_DIR = REPOSITORY_DIR / "gamble_icons"
CELL = 98          # native icon asset scale: 98 px per inventory cell
MATCH_CELL = 98    # matching scale — twin shapes (Dagger vs Dirk) need the
                   # full detail; 64 px confuses them
# Anchor slack: a 2% cell-size estimate error shifts column 0 by 9*2px after
# canonical resize, so the window must absorb ~20-30px. Anything below half a
# cell (49) still snaps unambiguously to its own anchor.
SEARCH_PAD = 34
SCORE_MIN = 0.40   # reject matches below this (zero-mean NCC × color sim;
                   # true matches score 0.9+ on clean renders)

_base = None      # {code: (gray98, alpha98, w_cells, h_cells)}
_scaled = {}      # {(code, cell_px): (edge, mask, w_cells, h_cells)}


def vision_ready():
    """Icons downloaded? (The grid auto-locates; no calibration needed.)"""
    return ICON_DIR.is_dir() and any(ICON_DIR.glob("*.png"))


_icon_equiv = None


def icon_equiv():
    """{item_idx: canonical_idx} for items sharing the IDENTICAL icon asset
    (claw pairs: Cestus/Hatchet Hands, Claws/Blade Talons, Katar/Wrist
    Blade). No scanner — or player — can tell them apart on screen, so the
    seed search must treat them as equal."""
    global _icon_equiv
    if _icon_equiv is None:
        import hashlib
        from advisor.gamble_seed import item_index
        by_hash = {}
        for p in ICON_DIR.glob("*.png"):
            try:
                by_hash.setdefault(hashlib.md5(p.read_bytes()).hexdigest(),
                                   []).append(p.stem)
            except OSError:
                continue
        m = {}
        for codes in by_hash.values():
            if len(codes) < 2:
                continue
            idxs = sorted(i for i in (item_index(c) for c in codes) if i >= 0)
            for i in idxs[1:]:
                m[i] = idxs[0]
        _icon_equiv = m
    return _icon_equiv


def _edge(bgr_or_gray):
    """Per-channel Sobel magnitude. COLOR edges are the discriminator: a
    gold amulet and a silver belt buckle have near-identical gray edges but
    very different color ones (the icons are the game's own art)."""
    img = bgr_or_gray
    if img.ndim == 2:
        gx = cv2.Sobel(img, cv2.CV_32F, 1, 0, ksize=3)
        gy = cv2.Sobel(img, cv2.CV_32F, 0, 1, ksize=3)
        return cv2.magnitude(gx, gy)
    chans = []
    for c in range(3):
        gx = cv2.Sobel(img[:, :, c], cv2.CV_32F, 1, 0, ksize=3)
        gy = cv2.Sobel(img[:, :, c], cv2.CV_32F, 0, 1, ksize=3)
        chans.append(cv2.magnitude(gx, gy))
    return cv2.merge(chans)


def _load_base():
    """{code: (bgr, alpha, w_cells, h_cells)} at the native 98 px/cell."""
    global _base
    if _base is not None:
        return _base
    from advisor.gamble_seed import items
    dims = {it["code"]: (it["invw"], it["invh"]) for it in items()}
    out = {}
    for png in ICON_DIR.glob("*.png"):
        code = png.stem
        if code not in dims:
            continue
        icon = cv2.imread(str(png), cv2.IMREAD_UNCHANGED)
        if icon is None or icon.shape[2] < 4:
            continue
        w, h = dims[code]
        icon = cv2.resize(icon, (w * CELL, h * CELL), interpolation=cv2.INTER_AREA)
        out[code] = (icon[:, :, :3].copy(), icon[:, :, 3].copy(), w, h)
    _base = out
    return out


def _templates_at(cell):
    """Per-icon matching data at a cell size:
    (edge_t, mask, w, h, tmean, t0, sigma_t, maskb)

    edge_t/mask locate the best shift (masked edge NCC map); the actual
    identification score is masked ZERO-MEAN NCC on gray intensities (t0 =
    zero-meaned masked template, sigma_t its norm) times a mean-color
    similarity (tmean). Zero-mean correlation is what kills thin-template
    false matches and empty-cell phantoms without coverage hacks."""
    base = _load_base()
    out = {}
    k = 3 if cell < 60 else 5
    kernel = np.ones((k, k), np.uint8)
    for code, (bgr, alpha, w, h) in base.items():
        key = (code, cell)
        got = _scaled.get(key)
        if got is None:
            b = cv2.resize(bgr, (w * cell, h * cell),
                           interpolation=cv2.INTER_AREA)
            a = cv2.resize(alpha, (w * cell, h * cell),
                           interpolation=cv2.INTER_NEAREST)
            mask1 = cv2.erode((a > 128).astype(np.uint8) * 255, kernel)
            gray = cv2.cvtColor(b, cv2.COLOR_BGR2GRAY).astype(np.float32)
            maskb = mask1 > 0
            if not maskb.any():
                maskb = np.ones_like(mask1, dtype=bool)
                mask1 = maskb.astype(np.uint8) * 255
            tmean = b[maskb].mean(axis=0).astype(np.float32)
            t0 = np.zeros_like(gray)
            t0[maskb] = gray[maskb] - gray[maskb].mean()
            sigma_t = float(np.sqrt((t0 * t0).sum())) + 1e-6
            got = (_edge(gray), mask1, w, h, tmean, t0, sigma_t, maskb)
            _scaled[key] = got
        out[code] = got
    return out


def _load_templates():
    """Back-compat: canonical 98 px/cell templates."""
    return _templates_at(CELL)


_auto_cache = None  # (gx, gy, cell) of the last successfully located grid


def auto_locate_grid(img_bgr, scales=None, diag=None):
    """Find gamble-grid candidates WITHOUT calibration.

    The Ring icon always sits at grid cell (9,0) with the Amulet directly
    below at (9,1) — a distinctive vertical pair. Multi-scale match both
    icons over the whole frame; each plausible pair pins a grid origin and
    cell size (refined by the ring->amulet peak distance).
    diag: optional list — appended with (cell_px, pair_score) per scale.
    Returns a best-first list of (score, gx, gy, cell_px), or None."""
    global _auto_cache
    base = _load_base()
    if "rin" not in base or "amu" not in base:
        return None
    # gray is enough to LOCATE (candidates are validated by recognition);
    # color matching at 27 scales over a 4K frame would triple the time
    ring_gray = cv2.cvtColor(base["rin"][0], cv2.COLOR_BGR2GRAY)
    ring_alpha = base["rin"][1]
    amu_gray = cv2.cvtColor(base["amu"][0], cv2.COLOR_BGR2GRAY)
    amu_alpha = base["amu"][1]
    edge = _edge(cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY))
    h, w = edge.shape[:2]

    def pair_score(cell):
        """Match ring at each candidate spot, require amulet one cell below."""
        c = int(round(cell))
        if c < 18 or c > 220:
            return None
        ring_t = _edge(cv2.resize(ring_gray, (c, c)))
        ring_m = cv2.erode((cv2.resize(ring_alpha, (c, c),
                                       interpolation=cv2.INTER_NEAREST) > 128)
                           .astype(np.uint8) * 255, np.ones((3, 3), np.uint8))
        amu_t = _edge(cv2.resize(amu_gray, (c, c)))
        amu_m = cv2.erode((cv2.resize(amu_alpha, (c, c),
                                      interpolation=cv2.INTER_NEAREST) > 128)
                          .astype(np.uint8) * 255, np.ones((3, 3), np.uint8))
        res = cv2.matchTemplate(edge, ring_t, cv2.TM_CCORR_NORMED, mask=ring_m)
        res = np.nan_to_num(res, nan=0.0, posinf=0.0, neginf=0.0)
        res[res > 1.0001] = 0.0  # masked-NCC artifact: legit peaks are < 1
        resa = cv2.matchTemplate(edge, amu_t, cv2.TM_CCORR_NORMED, mask=amu_m)
        resa = np.nan_to_num(resa, nan=0.0, posinf=0.0, neginf=0.0)
        resa[resa > 1.0001] = 0.0
        best = None
        r = res.copy()
        for _ in range(10):  # top ring candidates, non-max suppressed
            _mn, mx, _mnl, (rx, ry) = cv2.minMaxLoc(r)
            if mx < 0.22:
                break
            r[max(0, ry - c // 2):ry + c // 2, max(0, rx - c // 2):rx + c // 2] = 0
            ay0, ax0 = ry + c, rx  # amulet expected one cell below
            pad = max(3, c // 6)
            ys, ye = max(0, ay0 - pad), min(resa.shape[0], ay0 + pad + 1)
            xs, xe = max(0, ax0 - pad), min(resa.shape[1], ax0 + pad + 1)
            if ys >= ye or xs >= xe:
                continue
            window = resa[ys:ye, xs:xe]
            amax = float(window.max())
            if amax < 0.22:
                continue
            # the ring->amulet peak distance IS one cell — a far better cell
            # estimate than the scan grid (its error is amplified 9x at col 0)
            ay_peak = ys + int(np.unravel_index(window.argmax(), window.shape)[0])
            cell_ref = float(ay_peak - ry)
            if not (0.8 * cell <= cell_ref <= 1.2 * cell):
                cell_ref = float(cell)
            gx, gy = rx - 9.0 * cell_ref, float(ry)
            if gx < -2 or gy < 0 or gx + 10 * cell_ref > w + 2 or gy + 10 * cell_ref > h:
                continue
            score = mx * amax
            if best is None or score > best[0]:
                best = (score, max(0.0, gx), gy, cell_ref)
        return best

    candidates = []
    for scale in (scales if scales is not None
                  else np.arange(0.30, 1.31, 0.05)):
        cell = CELL * scale
        got = pair_score(cell)
        if diag is not None:
            diag.append((round(float(cell), 1),
                         round(got[0], 3) if got else 0.0))
        if got:
            candidates.append(got)
    if not candidates:
        _auto_cache = None
        return None
    # a wrong-scale accidental pair can outscore the true one — return the
    # top few distinct locations; the caller validates each by actually
    # recognizing the offer (ring/amulet entry check)
    candidates.sort(key=lambda cnd: -cnd[0])
    distinct = []
    for score, gx, gy, cell in candidates:
        if any(abs(gx - dgx) < cell and abs(gy - dgy) < cell
               and 0.85 < cell / dcell < 1.18
               for _ds, dgx, dgy, dcell in distinct):
            continue
        distinct.append((score, gx, gy, cell))
        if len(distinct) >= 4:
            break
    return distinct


MARGIN_FRAC = 0.3  # crop margin (in cells) so locate error never cuts icons


def canonical_grid(img_bgr, gx, gy, cell):
    """Crop the grid WITH a margin and normalize to 98 px/cell.

    The auto-locate origin can be off by a few px (amplified 9x at column 0
    through the cell-size estimate); the margin keeps every icon fully
    inside the crop and the matcher's anchor-jitter window absorbs the
    drift. Returns (grid_bgr, origin_px) — anchors sit at origin + i*98."""
    m = cell * MARGIN_FRAC
    S = int(round(10 * cell + 2 * m))
    x0, y0 = int(round(gx - m)), int(round(gy - m))
    canvas = np.zeros((S, S, 3), dtype=np.uint8)
    xs, ys = max(0, x0), max(0, y0)
    xe = min(img_bgr.shape[1], x0 + S)
    ye = min(img_bgr.shape[0], y0 + S)
    if xe <= xs or ye <= ys:
        raise ValueError("grid outside the captured frame")
    canvas[ys - y0:ye - y0, xs - x0:xe - x0] = img_bgr[ys:ye, xs:xe]
    mm = int(round(MATCH_CELL * MARGIN_FRAC))
    out = 10 * MATCH_CELL + 2 * mm
    grid = cv2.resize(canvas, (out, out), interpolation=cv2.INTER_AREA)
    return grid, mm


def grid_from_locate(img_bgr, gx, gy, cell):
    return canonical_grid(img_bgr, gx, gy, cell)


def grid_from_calib(img_bgr, screen_rect, calib):
    """Crop the 10x10 store grid and resize to the canonical 980x980."""
    left, top = screen_rect[0], screen_rect[1]
    x00, y00 = calib["cell00"][0] - left, calib["cell00"][1] - top
    x99, y99 = calib["cell99"][0] - left, calib["cell99"][1] - top
    dx = (x99 - x00) / 9.0
    dy = (y99 - y00) / 9.0
    if dx < 8 or dy < 8:
        raise ValueError("calibration points too close — recalibrate")
    gx = x00 - dx / 2.0
    gy = y00 - dy / 2.0
    h, w = img_bgr.shape[:2]
    x0, y0 = int(round(gx)), int(round(gy))
    x1, y1 = int(round(gx + 10 * dx)), int(round(gy + 10 * dy))
    if x0 < 0 or y0 < 0 or x1 > w or y1 > h:
        raise ValueError("calibrated grid is outside the captured monitor — "
                         "recalibrate on the gamble screen")
    return canonical_grid(img_bgr, gx, gy, (dx + dy) / 2.0)


def match_offer(grid_bgr, cell=CELL, origin=0, debug_out=None):
    """Identify up to 14 items in a grid image at `cell` px per cell, with
    grid cell (0,0) anchored at pixel (origin, origin).

    Returns [(code, x, y, score)] sorted by grid position. Greedy best-first
    assignment with occupancy, masked NCC on edge images weighted by how
    much of the region's edge energy the template explains.
    """
    templates = _templates_at(cell)
    pad = max(6, int(cell * 0.35))
    gray_f = cv2.cvtColor(grid_bgr, cv2.COLOR_BGR2GRAY).astype(np.float32)
    edge = _edge(gray_f)
    bgr_f = grid_bgr.astype(np.float32)
    candidates = []
    for code, (tmpl, mask, w, h, tmean, t0, sigma_t, maskb) in templates.items():
        # the edge-NCC map only picks the best SHIFT within each anchor
        # window; identification is scored below with zero-mean NCC
        res = cv2.matchTemplate(edge, tmpl, cv2.TM_CCORR_NORMED, mask=mask)
        res = np.nan_to_num(res, nan=0.0, posinf=0.0, neginf=0.0)
        res[res > 1.0001] = 0.0  # masked-NCC artifact: legit peaks are < 1
        th, tw = tmpl.shape
        tnorm = float(np.sqrt((tmean * tmean).sum())) + 1e-6
        for x in range(0, 11 - w):
            for y in range(0, 11 - h):
                px, py = origin + x * cell, origin + y * cell
                y_lo, y_hi = max(0, py - pad), min(res.shape[0], py + pad + 1)
                x_lo, x_hi = max(0, px - pad), min(res.shape[1], px + pad + 1)
                window = res[y_lo:y_hi, x_lo:x_hi]
                if not window.size or float(window.max()) < 0.20:
                    continue
                wy, wx = np.unravel_index(int(window.argmax()), window.shape)
                ly, lx = y_lo + wy, x_lo + wx
                region = gray_f[ly:ly + th, lx:lx + tw]
                if region.shape != (th, tw):
                    continue
                rm = region[maskb]
                rc = rm - rm.mean()
                sigma_r = float(np.sqrt((rc * rc).sum())) + 1e-6
                # flat regions (empty felt) make ZNCC degenerate — a real
                # icon has intensity std far above a few gray levels
                if sigma_r < 4.0 * np.sqrt(len(rm)):
                    continue
                z = float((region * t0)[maskb].sum()) / (sigma_r * sigma_t)
                if z <= 0:
                    continue
                rmean = bgr_f[ly:ly + th, lx:lx + tw][maskb].mean(axis=0)
                rn = float(np.sqrt((rmean * rmean).sum())) + 1e-6
                sim = max(0.0, min(1.0, float((rmean * tmean).sum())
                                   / (rn * tnorm)))
                candidates.append((z * sim ** 4, code, x, y, w, h))
    candidates.sort(key=lambda c: -c[0])
    occupied = np.zeros((10, 10), dtype=bool)
    picked = []
    for score, code, x, y, w, h in candidates:
        if score < SCORE_MIN or len(picked) >= 14:
            break
        if occupied[y:y + h, x:x + w].any():
            continue
        occupied[y:y + h, x:x + w] = True
        picked.append((code, x, y, score))
    picked.sort(key=lambda p: (p[2], p[1]))
    if debug_out is not None:
        dbg = grid_bgr.copy()
        for code, x, y, score in picked:
            w, h = templates[code][2], templates[code][3]
            x0, y0 = origin + x * cell, origin + y * cell
            cv2.rectangle(dbg, (x0, y0),
                          (x0 + w * cell - 2, y0 + h * cell - 2), (0, 255, 0), 2)
            cv2.putText(dbg, f"{code} {score:.2f}", (x0 + 4, y0 + 18),
                        cv2.FONT_HERSHEY_SIMPLEX, max(0.4, cell / 160),
                        (0, 255, 255), 1 if cell < 60 else 2)
        cv2.imwrite(str(debug_out), dbg)
    return picked


def _entries_from_grid(grid, origin, debug_out=None):
    from advisor.gamble_seed import item_index
    picked = match_offer(grid, MATCH_CELL, origin, debug_out=debug_out)
    entries = [(item_index(code), x, y) for code, x, y, _s in picked]
    entries = [e for e in entries if e[0] >= 0]
    placed = {(x, y): idx for idx, x, y in entries}
    ring, amulet = item_index("rin"), item_index("amu")
    ok = placed.get((9, 0)) == ring and placed.get((9, 1)) == amulet
    return entries, ok


def scan_gamble_icons(img_bgr, screen_rect, debug_out=None, diag=None):
    """Full pipeline -> [(item_idx, x, y)] entries.

    Locates the grid automatically (ring/amulet anchor pair); a manual
    cell calibration, when present, is tried first. On success the cell
    calibration for the auto-clicker is refreshed automatically.
    Raises ValueError with guidance when no gamble grid is on screen."""
    calib = load_calib()
    if calib_ok(calib):
        try:
            grid, origin = grid_from_calib(img_bgr, screen_rect, calib)
            entries, ok = _entries_from_grid(grid, origin, debug_out=debug_out)
            if ok:
                return entries
        except ValueError:
            pass
    global _auto_cache

    def try_loc(gx, gy, cell):
        """Accept a candidate grid only if the offer actually reads back:
        ring/amulet anchors correct and most of the 14 items recognized."""
        try:
            grid, origin = canonical_grid(img_bgr, gx, gy, cell)
        except ValueError:
            return None
        entries, ok = _entries_from_grid(grid, origin, debug_out=debug_out)
        if not ok or len(entries) < 10:
            return None
        return entries

    def accept(gx, gy, cell, entries):
        global _auto_cache
        # keyed by monitor rect: a cache from monitor 2 used to be retried
        # (and on a false accept, SAVED into the clicker calibration)
        # against monitor 1's frame
        _auto_cache = (tuple(screen_rect), gx, gy, cell)
        # refresh the auto-clicker's cell calibration from the located grid
        left, top = screen_rect[0], screen_rect[1]
        calib["cell00"] = [left + gx + cell / 2.0, top + gy + cell / 2.0]
        calib["cell99"] = [left + gx + 9.5 * cell, top + gy + 9.5 * cell]
        save_calib(calib)
        return entries

    if _auto_cache is not None and _auto_cache[0] == tuple(screen_rect):
        entries = try_loc(*_auto_cache[1:])
        if entries is not None:
            return accept(*_auto_cache[1:], entries)
        _auto_cache = None
    locs = auto_locate_grid(img_bgr, diag=diag)
    if not locs:
        raise ValueError("no gamble grid found on screen — open the gamble "
                         "window (the one with the Refresh button) and press "
                         "F10 again")
    for _score, gx, gy, cell in locs:
        entries = try_loc(gx, gy, cell)
        if entries is not None:
            return accept(gx, gy, cell, entries)
    raise ValueError("gamble grid located but Ring@(9,0)/Amulet@(9,1) "
                     "not recognized — send debug/*_gamble_grid.png")
