"""Startup diagnostics: what is configured, what is missing and how it
degrades the app. Levels: error = a core feature is off, warn = a feature
is degraded, ok = informational."""
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def health_report(cfg, calib=None):
    """[(level, title, detail)] — everything worth telling the user."""
    from advisor.app import resolve_tesseract
    issues = []

    tess = resolve_tesseract(cfg)
    if tess and ("/" in tess or "\\" in tess) and not Path(tess).exists():
        issues.append((
            "error", "Tesseract path is wrong",
            f"'{tess}' does not exist — fix tesseract_cmd in Settings."))
    elif not tess:
        issues.append((
            "error", "Tesseract OCR not found",
            "Tooltip scans (F8/F9) are disabled. Install it from "
            "github.com/UB-Mannheim/tesseract/wiki or set tesseract_cmd "
            "in Settings."))

    from advisor.gamble_vision import ICON_DIR
    if not (ICON_DIR / "rin.png").exists():
        issues.append((
            "warn", "Gamble icons not downloaded",
            "The F10 icon scan falls back to OCR. They download "
            "automatically on start; check your internet connection."))

    if not (ROOT / "tools" / "dbm_validation" / "brute.worker.js").exists():
        issues.append((
            "warn", "Fast-search worker not downloaded",
            "Find seed uses the built-in engine (minutes instead of "
            "seconds). It downloads automatically on start."))
    elif not shutil.which("node"):
        issues.append((
            "warn", "Node.js not installed",
            "Find seed uses the built-in engine (minutes instead of "
            "seconds). Install Node.js from nodejs.org for site-speed "
            "search."))

    if calib is None:
        try:
            from advisor.autoclicker import load_calib
            calib = load_calib()
        except Exception:
            calib = {}
    if not calib.get("refresh"):
        issues.append((
            "ok", "Auto-clicker: Refresh button not set",
            "Optional — needed only to Execute plans. Set it in the Seed "
            "Finder (Shift+F10)."))
    if not (calib.get("sellzone") or calib.get("sellslot")):
        issues.append((
            "ok", "Auto-clicker: sell zone not set",
            "Optional — filler buys won't auto-sell back until you click "
            "'Set sell zone' in the Seed Finder."))
    return issues


def summary_line(issues):
    errors = sum(1 for lv, _t, _d in issues if lv == "error")
    warns = sum(1 for lv, _t, _d in issues if lv == "warn")
    if not errors and not warns:
        return "everything is configured"
    bits = []
    if errors:
        bits.append(f"{errors} problem(s)")
    if warns:
        bits.append(f"{warns} warning(s)")
    return ", ".join(bits)
