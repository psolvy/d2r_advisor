"""Season goals: runes you have vs runewords you are building.

State lives in season_goals.json next to config (never committed).
Rune counts come from the one-shot stash-tab scans (or the +/- buttons)
in the Season Goals window — hover scans deliberately do NOT touch the
counters. Counts are a SHARED pool — each goal shows what is missing
against that pool.
"""
import json
import os
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
from advisor.paths import STATE_DIR
STATE_FILE = STATE_DIR / "season_goals.json"

# ladder-start classics — seeded on first run, editable in the UI
DEFAULT_GOALS = ["Stealth", "Lore", "Rhyme", "Ancients' Pledge", "Smoke",
                 "Insight", "Spirit"]

_RW_CACHE = None


def _runewords():
    global _RW_CACHE
    if _RW_CACHE is None:
        try:
            with open(ROOT / "d2rlootreader" / "repository"
                      / "runewords_full.json", encoding="utf-8") as f:
                _RW_CACHE = json.load(f)
        except (OSError, json.JSONDecodeError):
            # a missing repo file must not kill the Goals window
            _RW_CACHE = {}
    return _RW_CACHE


def load_state():
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            st = json.load(f)
    except FileNotFoundError:
        st = {}
    except json.JSONDecodeError:
        # never silently discard the pool — keep the corrupt file around
        try:
            os.replace(STATE_FILE, str(STATE_FILE) + ".corrupt")
            print(f"WARNING: {STATE_FILE.name} was corrupt — saved as "
                  f"{STATE_FILE.name}.corrupt, starting fresh")
        except OSError:
            pass
        st = {}
    st.setdefault("runes", {})
    st.setdefault("goals", list(DEFAULT_GOALS))
    st.setdefault("made", [])
    return st


def save_state(st):
    # atomic: a crash mid-write must not truncate the season pool
    tmp = str(STATE_FILE) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(st, f, indent=1)
    os.replace(tmp, STATE_FILE)


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


# item-type codes in runewords_full.json -> human labels
_TYPE_LABELS = {
    "shld": "shield", "ashd": "shield", "pala": "paladin shield",
    "head": "necro head", "tors": "body armor", "helm": "helm",
    "swor": "sword", "axe": "axe", "mace": "mace", "club": "club",
    "hamm": "hammer", "scep": "scepter", "wand": "wand", "staf": "staff",
    "pole": "polearm", "spea": "spear", "knif": "dagger", "h2h": "claw",
    "miss": "bow/crossbow", "grim": "grim helm", "mele": "melee weapon",
    "weap": "weapon",
}


def base_requirement(goal):
    """'3os shield/body armor' — the base a runeword needs; '' if unknown."""
    spec = _runewords().get(goal) or {}
    sockets, types = spec.get("sockets"), spec.get("types") or []
    if not sockets:
        return ""
    labels = []
    for t in types:
        lbl = _TYPE_LABELS.get(t, t)
        if lbl not in labels:
            labels.append(lbl)
    return f"{sockets}os " + ("/".join(labels) if labels else "any base")


def shopping_list(st=None):
    """[(rune, missing_total, goals_blocked)] aggregated across tracked
    UNFINISHED goals — what to farm next, most-blocking first."""
    st = st or load_state()
    missing, blocked = {}, {}
    for goal, rows, complete in goal_progress(st):
        if complete:
            continue
        for r, n, h in rows:
            if h < n and not r.endswith("?"):
                missing[r] = missing.get(r, 0) + (n - h)
                blocked[r] = blocked.get(r, 0) + 1
    order = {r: i for i, r in enumerate(_rune_order())}
    out = [(r, missing[r], blocked[r]) for r in missing]
    out.sort(key=lambda t: (-t[2], -order.get(t[0], 0)))
    return out


# --------------------------------------------------------- cube upgrades

def _two_per_up():
    from advisor.knowledge import TWO_PER_UP
    return TWO_PER_UP


def _up_gems():
    from advisor.knowledge import UP_GEMS
    return UP_GEMS


def _rune_order():
    from advisor.knowledge import RUNE_ORDER
    return RUNE_ORDER


def _solve(per_copy, copies, runes_pool, gems_pool, allow_up, steps=None):
    """Can `copies` copies be made from the pools, optionally cubing
    lower runes (and their gems) up? With `steps` given, records the
    upgrade chain as (lower, per, gem, count, target) tuples."""
    order = _rune_order()
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
        per = 2 if lower in _two_per_up() else 3
        gem = _up_gems().get(lower)
        if gem:
            gem = gem.title()  # knowledge stores 'chipped amethyst'
            if gems.get(gem, 0) < d:
                return False
            gems[gem] = gems.get(gem, 0) - d
        if steps is not None:
            steps.append((lower, per, gem, d, r))
        demand[lower] = demand.get(lower, 0) + per * d
    return True


def _feasible(per_copy, copies, runes_pool, gems_pool, allow_up):
    return _solve(per_copy, copies, runes_pool, gems_pool, allow_up)


def cube_plan(goal, st=None):
    """Executable upgrade chain for ONE copy of the goal, lowest rune
    first: ['3× Tal + Chipped Ruby → Ral ×2', …]. Empty list = makeable
    from the pool as-is; None = not makeable even with cube-ups."""
    st = st or load_state()
    runes = (_runewords().get(goal) or {}).get("runes") or []
    if not runes:
        return None
    per = {}
    for r in runes:
        per[r] = per.get(r, 0) + 1
    steps = []
    if not _solve(per, 1, st["runes"], st.get("gems"), True, steps):
        return None
    lines = []
    for lower, per_n, gem, d, target in reversed(steps):
        gem_txt = f" + {gem}" if gem else ""
        times = f" ×{d}" if d > 1 else ""
        lines.append(f"{per_n}× {lower}{gem_txt} → {target}{times}")
    return lines


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

_GEM_SHORT = {"P.Amethyst": "Perfect Amethyst", "P.Ruby": "Perfect Ruby",
              "P.Sapphire": "Perfect Sapphire",
              "P.Emerald": "Perfect Emerald", "P.Topaz": "Perfect Topaz",
              "P.Diamond": "Perfect Diamond", "P.Skull": "Perfect Skull"}


def craftable_recipes(allow_up=False, st=None):
    """Real craft recipes from cube.json checked against BOTH pools:
    [(result, rune, gem, bases_str, rune_ok, gem_ok)] — recipes whose
    rune AND gem are in stock first. The old panel only counted four
    perfect gems and ignored the rune half entirely."""
    st = st or load_state()
    runes, gems = st.get("runes") or {}, st.get("gems") or {}
    try:
        with open(ROOT / "d2rlootreader" / "repository" / "cube.json",
                  encoding="utf-8") as f:
            crafts = json.load(f).get("crafts") or []
    except (OSError, json.JSONDecodeError):
        return []
    out = []
    for c in crafts:
        rune, gem = c.get("rune"), _GEM_SHORT.get(c.get("gem"),
                                                  c.get("gem") or "")
        gtype = gem.split()[-1] if gem else ""
        rune_ok = runes.get(rune, 0) > 0
        gem_ok = (gems.get(gem, 0) > 0 or
                  (allow_up and gtype
                   and _perfect_equivalents(gems, gtype) > 0))
        out.append((c.get("result") or "?", rune or "?", gem or "?",
                    "/".join(c.get("bases") or []), rune_ok, gem_ok))
    out.sort(key=lambda t: (not (t[4] and t[5]), t[0]))
    return out


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
        if not runes:
            # unknown/renamed runeword — all([]) used to render it as a
            # completed goal; show it as broken instead
            out.append((goal, [("unknown runeword?", 1, 0)], False))
            continue
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
    """Subtract the goal's runes from the pool and log it as made.
    Returns (state, ok, msg) — an incomplete goal is refused instead of
    silently eating whatever runes the pool does have."""
    st = load_state()
    rw = _runewords()
    runes = (rw.get(goal) or {}).get("runes") or []
    if not runes:
        return st, False, f"unknown runeword: {goal}"
    need = {}
    for r in runes:
        need[r] = need.get(r, 0) + 1
    missing = [f"{r}×{n - st['runes'].get(r, 0)}" for r, n in need.items()
               if st["runes"].get(r, 0) < n]
    if missing:
        return st, False, f"missing {', '.join(missing)}"
    for r in runes:
        st["runes"][r] -= 1
        if st["runes"][r] == 0:
            st["runes"].pop(r)
    st["made"].append({"goal": goal, "ts": time.time(), "runes": need})
    save_state(st)
    return st, True, ""


def undo_made(st=None):
    """Undo the last 'I made it': restore its runes to the pool.
    Returns (state, goal_or_None)."""
    st = st or load_state()
    for i in range(len(st["made"]) - 1, -1, -1):
        entry = st["made"][i]
        if isinstance(entry, dict):  # old entries were bare strings — no
            st["made"].pop(i)        # rune record, nothing to restore
            for r, n in (entry.get("runes") or {}).items():
                st["runes"][r] = st["runes"].get(r, 0) + n
            save_state(st)
            return st, entry.get("goal")
        break
    return st, None


def set_goals(goals):
    st = load_state()
    st["goals"] = list(goals)
    save_state(st)
    return st


def all_runeword_names():
    return sorted(_runewords().keys())
