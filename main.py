"""D2R Item Advisor — thin launcher.

All app code lives in advisor/app.py. This file must stay LIGHT: on
Windows, multiprocessing workers re-import __main__ (this file) — if it
imported cv2/tkinter/the app, every seed-search worker would load ~300MB
and the machine runs out of commit memory ("paging file is too small").
"""
import multiprocessing
import sys

if getattr(sys, "frozen", False):
    # The exe is a WINDOWED build (tray app, no console): sys.stdout is
    # None there and every print() would crash — route it to a log file
    # in the state dir (tray menu "Open log" shows it). Opening it next
    # to the exe died instantly under Program Files (read-only).
    from advisor.paths import STATE_DIR, migrate_legacy
    migrate_legacy()  # move state older builds wrote into _internal
    _log = open(STATE_DIR / "advisor.log", "a",
                encoding="utf-8", buffering=1)
    sys.stdout = sys.stderr = _log

if __name__ != "__mp_main__":  # real runs and tests, not worker bootstrap
    from advisor.app import *  # noqa: F401,F403
    from advisor.app import (App, load_config, resolve_rules_file,  # noqa: F401
                             resolve_tesseract, get_cursor_pos)

if __name__ == "__main__":
    # In the PyInstaller exe, worker processes re-run the exe itself —
    # without freeze_support they would boot the whole app in a loop.
    multiprocessing.freeze_support()
    App().run()
