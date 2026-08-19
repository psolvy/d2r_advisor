"""Auto-clicker: executes a gamble buy plan in game.

A plan (from advisor.gamble_plan) is a list of steps: R = click the
Refresh button, B/C = right-click (buy) the item at grid cell (x, y).
Screen positions come from a 3-point calibration stored in config.yaml:
the Refresh button, the CENTER of grid cell (0,0) and of cell (9,9).

Safety: ESC aborts between clicks; each step waits `delay` seconds so the
game UI can settle. The game window must stay focused and the gamble
screen open for the whole run.
"""
import ctypes
import json
import sys
import time
from pathlib import Path

IS_WINDOWS = sys.platform == "win32"

CALIB_KEYS = ("refresh", "cell00", "cell99")
CALIB_FILE = Path(__file__).resolve().parents[1] / "gamble_clicks.json"


def load_calib():
    try:
        with open(CALIB_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_calib(calib):
    with open(CALIB_FILE, "w", encoding="utf-8") as f:
        json.dump(calib, f)


def get_cursor_pos():
    class POINT(ctypes.Structure):
        _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]
    p = POINT()
    ctypes.windll.user32.GetCursorPos(ctypes.byref(p))
    return (p.x, p.y)


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", ctypes.c_ushort), ("wScan", ctypes.c_ushort),
                ("dwFlags", ctypes.c_ulong), ("time", ctypes.c_ulong),
                ("dwExtraInfo", ctypes.c_void_p)]


class _INPUT(ctypes.Structure):
    class _U(ctypes.Union):
        _fields_ = [("ki", _KEYBDINPUT), ("pad", ctypes.c_byte * 32)]
    _anonymous_ = ("u",)
    _fields_ = [("type", ctypes.c_ulong), ("u", _U)]


def _ctrl(down):
    """Hold/release Ctrl as a HARDWARE SCAN CODE (0x1D). D2R polls scan
    codes — a plain keybd_event virtual key can be ignored, which turned
    the Ctrl+click sell into a bare click."""
    flags = 0x0008 | (0 if down else 0x0002)  # SCANCODE (| KEYUP)
    inp = _INPUT(type=1)  # INPUT_KEYBOARD
    inp.ki = _KEYBDINPUT(0, 0x1D, flags, 0, None)
    ctypes.windll.user32.SendInput(1, ctypes.byref(inp),
                                   ctypes.sizeof(_INPUT))
    # belt and braces: also set the async VK state for UIs that read it
    ctypes.windll.user32.keybd_event(0x11, 0x1D, 0 if down else 0x0002, 0)


def _click(x, y, right=False, settle=0.06, ctrl=False):
    u = ctypes.windll.user32
    u.SetCursorPos(int(round(x)), int(round(y)))
    time.sleep(settle)
    if ctrl:
        _ctrl(True)                        # Ctrl+click = sell to vendor
        time.sleep(0.08)
    if right:
        u.mouse_event(0x0008, 0, 0, 0, 0)  # right down
        time.sleep(0.02)
        u.mouse_event(0x0010, 0, 0, 0, 0)  # right up
    else:
        u.mouse_event(0x0002, 0, 0, 0, 0)  # left down
        time.sleep(0.02)
        u.mouse_event(0x0004, 0, 0, 0, 0)  # left up
    if ctrl:
        time.sleep(0.08)
        _ctrl(False)


def calib_ok(calib):
    return (isinstance(calib, dict)
            and all(isinstance(calib.get(k), (list, tuple))
                    and len(calib[k]) == 2 for k in CALIB_KEYS))


def cell_to_screen(calib, x, y, invw=1, invh=1):
    """Screen point at the center of an invw x invh item whose top-left
    grid cell is (x, y)."""
    x00, y00 = calib["cell00"]
    x99, y99 = calib["cell99"]
    dx = (x99 - x00) / 9.0
    dy = (y99 - y00) / 9.0
    return (x00 + (x + (invw - 1) / 2.0) * dx,
            y00 + (y + (invh - 1) / 2.0) * dy)


def sell_points(calib):
    """Inventory points to Ctrl+click after a filler buy. A 'sellzone'
    (two hovered corners) beats a single 'sellslot': the game packs small
    items bottom-right but larger ones elsewhere — sweeping every cell of
    the kept-empty zone catches the purchase wherever it landed (Ctrl+click
    on an empty cell is a no-op). Cell pitch comes from the store-grid
    calibration (inventory cells are the same size)."""
    z = calib.get("sellzone")
    if z and calib_ok(calib):
        x1, y1, x2, y2 = z
        x00, y00 = calib["cell00"]
        x99, y99 = calib["cell99"]
        dx = abs(x99 - x00) / 9.0 or 30.0
        dy = abs(y99 - y00) / 9.0 or 30.0
        nx = max(1, int(round(abs(x2 - x1) / dx)) + 1)
        ny = max(1, int(round(abs(y2 - y1) / dy)) + 1)
        sx = (x2 - x1) / (nx - 1) if nx > 1 else 0
        sy = (y2 - y1) / (ny - 1) if ny > 1 else 0
        return [(x1 + i * sx, y1 + j * sy)
                for j in range(ny) for i in range(nx)]
    if calib.get("sellslot"):
        return [tuple(calib["sellslot"])]
    return []


def execute_plan(steps, items_table, calib, delay=0.8, on_step=None,
                 stop=None):
    """Click through a plan. steps: gamble_plan plan['steps']. Returns
    (done_count, error_or_None). Aborts on ESC, stop event, or an
    unplaced item."""
    if not IS_WINDOWS:
        return 0, "auto-clicker is Windows-only"
    if not calib_ok(calib):
        return 0, "not calibrated — run Calibrate clicks first"
    try:
        import keyboard
    except ImportError:
        keyboard = None
    done = 0
    for i, s in enumerate(steps):
        if stop is not None and stop.is_set():
            return done, "stopped"
        if keyboard is not None and keyboard.is_pressed("esc"):
            return done, "aborted with ESC"
        if s["type"] == "R":
            if on_step:
                on_step(i, "click Refresh")
            _click(*calib["refresh"])
        else:
            if s["x"] < 0 or s["y"] < 0:
                return done, f"step {i + 1}: item has no grid position"
            it = items_table[s["idx"]]
            px, py = cell_to_screen(calib, s["x"], s["y"],
                                    it["invw"], it["invh"])
            if on_step:
                verb = "BUY" if s["type"] == "B" else "COLLECT"
                on_step(i, f"{verb} {it['name']} @({s['x']},{s['y']})")
            _click(px, py, right=True)
            # filler buys sell straight back: Ctrl+click across the sell
            # zone — the purchase gets sold wherever it landed (selling
            # consumes no RNG). Never the COLLECT step — that is the target.
            pts = sell_points(calib) if s["type"] == "B" else []
            if pts:
                time.sleep(delay)  # let the item land in the inventory
                if on_step:
                    on_step(i, f"sell back {it['name']} "
                               f"(Ctrl+click sweep, {len(pts)} cells)")
                for px2, py2 in pts:
                    if stop is not None and stop.is_set():
                        return done + 1, "stopped"
                    _click(px2, py2, ctrl=True, settle=0.04)
                    time.sleep(0.12)
        done += 1
        time.sleep(delay)
    return done, None
