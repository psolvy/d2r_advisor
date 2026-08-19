"""End-to-end test of icon-based offer recognition on a synthetic screenshot.

Covers the zero-setup path: NO calibration — the grid must auto-locate via
the Ring/Amulet anchor pair, and the scan must then auto-save the cell
calibration for the auto-clicker. The user's real gamble_clicks.json is
preserved and restored.

Run:  py -3 tests\test_vision.py  (needs repository/gamble_icons — see
tools/get_gamble_icons.py).
"""
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import cv2
import numpy as np

from advisor.gamble_seed import Ctx, items, offer_with_positions
from advisor import autoclicker
from advisor import gamble_vision as gv

# The icons are third-party art fetched at setup time (not in the repo) —
# without them there is nothing to test, which is a SKIP, not a failure.
if not (gv.ICON_DIR / "rin.png").exists():
    print("SKIP: repository/gamble_icons missing — run "
          "'python tools/setup_assets.py' to fetch them")
    sys.exit(0)

SEED = 987654321
ctx = Ctx(85, "msvc")
it = items()
offer = offer_with_positions(SEED, ctx)

# --- compose a fake monitor capture: 3840x2160, grid at (400, 300), 63 px/cell
CELLPX = 63.0
GX, GY = 400, 300
img = np.full((2160, 3840, 3), 18, dtype=np.uint8)
noise = np.random.default_rng(1).integers(0, 12, img.shape, dtype=np.uint8)
img = cv2.add(img, noise)
img[GY:GY + 630, GX:GX + 630] = (24, 16, 40)  # red 'cannot afford' tint

for idx, pos in offer:
    if pos is None:
        continue
    x, y = pos
    code = it[idx]["code"]
    w, h = it[idx]["invw"], it[idx]["invh"]
    icon = cv2.imread(str(gv.ICON_DIR / f"{code}.png"), cv2.IMREAD_UNCHANGED)
    icon = cv2.resize(icon, (int(w * CELLPX), int(h * CELLPX)),
                      interpolation=cv2.INTER_AREA)
    a = icon[:, :, 3:4].astype(np.float32) / 255.0
    px, py = int(GX + x * CELLPX), int(GY + y * CELLPX)
    roi = img[py:py + icon.shape[0], px:px + icon.shape[1]].astype(np.float32)
    img[py:py + icon.shape[0], px:px + icon.shape[1]] = (
        roi * (1 - a) + icon[:, :, :3].astype(np.float32) * a * 0.88
    ).astype(np.uint8)

LEFT, TOP = 4300, 0
screen_rect = (LEFT, TOP, 3840, 2160)
expect = sorted((i, p[0], p[1]) for i, p in offer if p is not None)

_orig = autoclicker.load_calib()
if autoclicker.CALIB_FILE.exists():
    os.remove(autoclicker.CALIB_FILE)   # force the auto-locate path
try:
    t0 = time.time()
    entries = gv.scan_gamble_icons(img, screen_rect)
    dt = time.time() - t0
    got = sorted(entries)
    print(f"auto-located + recognized {len(got)}/{len(expect)} items in {dt:.1f}s")
    for e in [e for e in expect if e not in got]:
        print("  MISSING:", it[e[0]]["name"], e[1:])
    for e in [e for e in got if e not in expect]:
        print("  EXTRA:  ", it[e[0]]["name"], e[1:])
    assert got == expect, "recognition mismatch (auto-locate path)"

    # cells must have been auto-saved for the auto-clicker
    calib = autoclicker.load_calib()
    assert "cell00" in calib and "cell99" in calib, "cells not auto-saved"
    c00 = calib["cell00"]
    assert abs(c00[0] - (LEFT + GX + CELLPX / 2)) < CELLPX / 2
    assert abs(c00[1] - (TOP + GY + CELLPX / 2)) < CELLPX / 2
    print("ok: cell calibration auto-saved from the located grid")

    # cached second scan should be faster and identical
    t0 = time.time()
    entries2 = gv.scan_gamble_icons(img, screen_rect)
    print(f"ok: cached re-scan identical in {time.time() - t0:.1f}s")
    assert sorted(entries2) == expect

    # resolution sweep: same offer at 1080p-through-4K cell sizes
    def compose(cellpx, gx0, gy0, fw, fh):
        frame = np.full((fh, fw, 3), 18, dtype=np.uint8)
        frame[gy0:gy0 + int(10 * cellpx), gx0:gx0 + int(10 * cellpx)] = (24, 16, 40)
        for idx, pos in offer:
            if pos is None:
                continue
            x, y = pos
            code = it[idx]["code"]
            w, h = it[idx]["invw"], it[idx]["invh"]
            ic = cv2.imread(str(gv.ICON_DIR / f"{code}.png"), cv2.IMREAD_UNCHANGED)
            ic = cv2.resize(ic, (int(w * cellpx), int(h * cellpx)),
                            interpolation=cv2.INTER_AREA)
            al = ic[:, :, 3:4].astype(np.float32) / 255.0
            px2, py2 = int(gx0 + x * cellpx), int(gy0 + y * cellpx)
            roi = frame[py2:py2 + ic.shape[0], px2:px2 + ic.shape[1]].astype(np.float32)
            frame[py2:py2 + ic.shape[0], px2:px2 + ic.shape[1]] = (
                roi * (1 - al) + ic[:, :, :3].astype(np.float32) * al * 0.9
            ).astype(np.uint8)
        return frame

    for cellpx, fw, fh in ((40.0, 1920, 1080), (52.0, 2560, 1440),
                           (76.0, 3840, 2160), (90.0, 3840, 2160)):
        gv._auto_cache = None
        frame = compose(cellpx, 210, 140, fw, fh)
        got2 = sorted(gv.scan_gamble_icons(frame, (0, 0, fw, fh)))
        assert got2 == expect, f"mismatch at cell {cellpx}px"
        print(f"ok: cell {cellpx:.0f}px ({fw}x{fh}) -> 14/14")
    print("ALL VISION TESTS PASSED")
finally:
    if _orig:
        autoclicker.save_calib(_orig)
    elif autoclicker.CALIB_FILE.exists():
        os.remove(autoclicker.CALIB_FILE)
