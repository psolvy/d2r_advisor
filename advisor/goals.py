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


def set_counts(counts):
    """Replace the whole rune pool — the scanned stash tab is
    authoritative."""
    st = load_state()
    st["runes"] = {r: int(n) for r, n in counts.items() if int(n) > 0}
    save_state(st)
    return st


def set_gem_counts(counts):
    st = load_state()
    st["gems"] = {g: int(n) for g, n in counts.items() if int(n) > 0}
    save_state(st)
    return st


# --------------------------------------------------------- cube upgrades

# 2 lower runes per upgrade from Pul upward, 3 below; the gem consumed
# when upgrading FROM that rune (None = no gem needed)
_TWO_PER_UP = {"Pul", "Um", "Mal", "Ist", "Gul", "Vex", "Ohm", "Lo", "Sur",
               "Ber", "Jah", "Cham"}


def _up_gems():
    from advisor.knowledge import _UP_GEMS
    return _UP_GEMS


def _rune_order():
    from advisor.knowledge import RUNE_ORDER
    return RUNE_ORDER


def _feasible(per_copy, copies, runes_pool, gems_pool, allow_up):
    """Can `copies` copies be made from the pools, optionally cubing
    lower runes (and their gems) up?"""
    order = _rune_order()
    idx = {r: i for i, r in enumerate(order)}
    pool = dict(runes_pool)
    gems = dict(gems_pool or {})
    demand = {}
    for r, n in per_copy.items():
        demand[r] = demand.get(r, 0) + n * copies
    for i in range(len(order) - 1, -1, -1):
        r = order[i]
        d = demand.get(r, 0)
        if not d:
            continue
        take = min(pool.get(r, 0), d)
        d -= take
        if not d:
            continue
        if not allow_up or i == 0:
            return False
        lower = order[i - 1]
        per = 2 if lower in _TWO_PER_UP else 3
        gem = _up_gems().get(lower)
        if gem:
            gem = gem.title()  # knowledge stores 'chipped amethyst'
            if gems.get(gem, 0) < d:
                return False
            gems[gem] = gems.get(gem, 0) - d
        demand[lower] = demand.get(lower, 0) + per * d
    return True


def craftable_runewords(allow_up=False, st=None, limit=40):
    """[(name, count, runes_str)] — every runeword makeable RIGHT NOW,
    best counts first. allow_up counts cube-upgrading lower runes/gems."""
    st = st or load_state()
    rw = _runewords()
    out = []
    for name, spec in rw.items():
        runes = spec.get("runes") or []
        if not runes:
            continue
        per = {}
        for r in runes:
            per[r] = per.get(r, 0) + 1
        # exponential probe + binary search — the old flat loop capped
        # the count at 20 (Tal 30 + Eth 21 showed "Stealth x20")
        n = 0
        step = 1
        while step and _feasible(per, n + step, st["runes"],
                                 st.get("gems"), allow_up):
            n += step
            step = min(step * 2, 999 - n)
        lo, hi = n, n + max(step, 1)
        while lo + 1 < hi:
            mid = (lo + hi) // 2
            if _feasible(per, mid, st["runes"], st.get("gems"), allow_up):
                lo = mid
            else:
                hi = mid
        n = lo
        if n:
            out.append((name, n, " ".join(runes)))
    out.sort(key=lambda t: (-t[1], t[0]))
    return out[:limit]


def _perfect_equivalents(gems, gtype):
    """Perfect gems of a type makeable by cubing 3 lower -> 1 higher."""
    q = ["Chipped", "Flawed", "", "Flawless", "Perfect"]
    have = [gems.get(f"{lvl} {gtype}".strip(), 0) for lvl in q]
    carry = 0
    for lvl in range(4):
        carry = (have[lvl] + carry) // 3
    return have[4] + carry


# craft families: the perfect gem is fixed; the rune varies by slot
CRAFT_GEMS = {"Caster": "Perfect Amethyst", "Blood": "Perfect Ruby",
              "Hit Power": "Perfect Sapphire", "Safety": "Perfect Emerald"}


def craft_lines(allow_up=False):
    """[(text, ok)] — perfect-gem stock per craft family + reroll info.
    allow_up also counts perfects cubeable from lower qualities."""
    st = load_state()
    gems = st.get("gems") or {}
    out = []
    for family, gem in CRAFT_GEMS.items():
        gtype = gem.split()[-1]
        n = (_perfect_equivalents(gems, gtype) if allow_up
             else gems.get(gem, 0))
        tag = " incl. cube-ups" if allow_up else ""
        out.append((f"{family} crafts: {gem} ×{n}{tag} "
                    "(+ jewel + slot rune)", n > 0))
    skulls = (_perfect_equivalents(gems, "Skull") if allow_up
              else gems.get("Perfect Skull", 0))
    if skulls:
        out.append((f"Perfect Skull ×{skulls} — rare rerolls / socket "
                    "quests", True))
    total_perfect = sum(n for g, n in gems.items() if g.startswith("Perfect"))
    out.append((f"perfect gems total: {total_perfect} — 3× same quality "
                "rerolls a Grand Charm", total_perfect >= 3))
    return out


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
