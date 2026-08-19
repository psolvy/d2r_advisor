"""Season goals: runes you have vs runewords you are building.

State lives in season_goals.json next to config (never committed).
Runes are auto-collected from scans (with a dedupe window so re-scanning
the same rune doesn't double-count) and adjustable by hand in the Season
Goals window. Rune counts are a SHARED pool — each goal shows what is
missing against that pool.
"""
import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATE_FILE = ROOT / "season_goals.json"

# ladder-start classics — seeded on first run, editable in the UI
DEFAULT_GOALS = ["Stealth", "Lore", "Rhyme", "Ancients' Pledge", "Smoke",
                 "Insight", "Spirit"]

_DEDUPE_S = 90  # same rune scanned again within this window = same drop


def _runewords():
    with open(ROOT / "d2rlootreader" / "repository" / "runewords_full.json",
              encoding="utf-8") as f:
        return json.load(f)


def load_state():
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            st = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        st = {}
    st.setdefault("runes", {})
    st.setdefault("goals", list(DEFAULT_GOALS))
    st.setdefault("made", [])
    st.setdefault("_last_scan", {})
    return st


def save_state(st):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(st, f, indent=1)


def add_scanned_rune(rune):
    """Auto-count a scanned rune drop; dedupes rapid re-scans.
    Returns True when the count actually increased."""
    st = load_state()
    now = time.time()
    if now - float(st["_last_scan"].get(rune, 0)) < _DEDUPE_S:
        st["_last_scan"][rune] = now
        save_state(st)
        return False
    st["_last_scan"][rune] = now
    st["runes"][rune] = st["runes"].get(rune, 0) + 1
    save_state(st)
    return True


def adjust_rune(rune, delta):
    st = load_state()
    st["runes"][rune] = max(0, st["runes"].get(rune, 0) + delta)
    if st["runes"][rune] == 0:
        st["runes"].pop(rune, None)
    save_state(st)
    return st


def goal_progress(st=None):
    """[(goal, [(rune, need, have)], complete_bool)] for tracked goals."""
    st = st or load_state()
    rw = _runewords()
    have = st["runes"]
    out = []
    for goal in st["goals"]:
        runes = (rw.get(goal) or {}).get("runes") or []
        need = {}
        for r in runes:
            need[r] = need.get(r, 0) + 1
        rows = [(r, n, have.get(r, 0)) for r, n in need.items()]
        out.append((goal, rows, all(h >= n for _r, n, h in rows)))
    return out


def rune_popup_lines(rune):
    """Popup lines for a scanned rune: which tracked goals it advances.
    [(text, ready_bool)] — at most 3, ready goals first."""
    st = load_state()
    lines = []
    for goal, rows, complete in goal_progress(st):
        if not any(r == rune for r, _n, _h in rows):
            continue
        missing = [f"{r}×{n - h}" if n - h > 1 else r
                   for r, n, h in rows if h < n]
        if complete:
            lines.append((f"🏁 {goal}: ALL RUNES READY — make it!", True))
        else:
            lines.append((f"goal {goal}: missing {', '.join(missing)}",
                          False))
    lines.sort(key=lambda x: not x[1])
    return lines[:3]


def mark_made(goal):
    """Subtract the goal's runes from the pool and log it as made."""
    st = load_state()
    rw = _runewords()
    for r in (rw.get(goal) or {}).get("runes") or []:
        if st["runes"].get(r, 0) > 0:
            st["runes"][r] -= 1
            if st["runes"][r] == 0:
                st["runes"].pop(r)
    st["made"].append(goal)
    save_state(st)
    return st


def set_goals(goals):
    st = load_state()
    st["goals"] = list(goals)
    save_state(st)
    return st


def all_runeword_names():
    return sorted(_runewords().keys())
