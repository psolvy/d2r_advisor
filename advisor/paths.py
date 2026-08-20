"""Where mutable state lives.

Source checkout: the repo root — the dev flow is unchanged.

Frozen exe: every module's __file__ resolves inside <install>\\_internal
(PyInstaller 6 onedir), so config, goals, calibration, history and debug
frames all landed in a folder that (a) looks like build internals and
(b) is unwritable when the app is installed under Program Files — the
windowed exe then died or silently dropped every save. State moves to
%LOCALAPPDATA%\\d2r-advisor, with a one-time migration of files older
builds wrote into _internal (including the shipped default config.yaml
on first run).
"""
import os
import shutil
import sys
from pathlib import Path

PKG_ROOT = Path(__file__).resolve().parents[1]  # _internal when frozen

_MIGRATE = ["config.yaml", "rules.yaml", "season_goals.json",
            "gamble_clicks.json", "history.log", "history.log.1"]


def _frozen():
    return getattr(sys, "frozen", False)


def _compute_state_dir():
    if not _frozen():
        return PKG_ROOT
    base = os.environ.get("LOCALAPPDATA")
    root = Path(base) if base else Path.home() / "AppData" / "Local"
    d = root / "d2r-advisor"
    try:
        d.mkdir(parents=True, exist_ok=True)
    except OSError:
        return PKG_ROOT  # last resort: the old behavior
    return d


STATE_DIR = _compute_state_dir()


def migrate_legacy():
    """Move state files older builds left inside _internal. Safe to call
    every start; never overwrites files already in STATE_DIR."""
    if not _frozen() or STATE_DIR == PKG_ROOT:
        return
    for name in _MIGRATE:
        old, new = PKG_ROOT / name, STATE_DIR / name
        if old.exists() and not new.exists():
            try:
                shutil.move(str(old), str(new))
            except OSError:
                pass
    old_dbg = PKG_ROOT / "debug"
    new_dbg = STATE_DIR / "debug"
    if old_dbg.is_dir() and not new_dbg.exists():
        try:
            shutil.move(str(old_dbg), str(new_dbg))
        except OSError:
            pass
