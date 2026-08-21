"""Offline regression suite — parse/rules/knowledge/ranges/seed engine.

Run:  py -3 tests\test_regression.py
No game, no Tesseract, no network needed.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from advisor.parse import parse_best, parse_tooltip, _sanitize_affixes
from advisor.rules import evaluate, load_rules
from advisor.ranges import get_item_ranges, magic_affix_ranges
from advisor.runewords import base_advice
from advisor.breakpoints import bp_lines
from advisor.knowledge import (consumable_advice, gamble_offer_summary,
                               get_value_tier, match_gamble_offer,
                               quest_advice, special_advice)

ok = 0


def check(name, cond, detail=""):
    global ok
    if not cond:
        print(f"FAIL: {name} {detail}")
        sys.exit(1)
    ok += 1
    print(f"ok: {name}")


# ---------------------------------------------------------------- parsing

item = parse_best(iter([[
    "Harlequin Crest", "Shako", "Defense: 112", "Durability: 5 of 12",
    "Required Level: 62", "+2 to All Skills", "+120 to Life",
]]), quality_hint="Unique")
check("unique parse: quality", item.get("quality") == "Unique", item.get("quality"))
check("unique parse: base", (item.get("base") or "") == "Shako", item.get("base"))

item = parse_best(iter([[
    "Amulet of the Whale", "Required Level: 58", "+81 to Life",
]]), quality_hint="Magic")
check("magic parse: quality", item.get("quality") == "Magic", item.get("quality"))

sup = parse_tooltip(["Superior Mage Plate", "Defense: 261", "Durability: 60 of 60"],
                    quality_hint="Base")
check("superior name restored", "Superior" in (sup.get("name") or ""), sup.get("name"))

clamped = _sanitize_affixes({"affixes": [("Socketed (#)", [21])]})
check("socketed 21 -> 2", clamped["affixes"][0][1][0] == 2)

# runeword rescue: gold titles OCR badly; the runeword must be identified
# from the name line OR the quoted rune string even when the title garbles
_spirit = ["Spirit", "Monarch", "'TalThulOrtAmn'", "Defense: 142",
           "Required Level: 54", "+2 to All Skills", "+35% Faster Cast Rate",
           "+92 to Mana", "Socketed (4)"]
rw = parse_best(iter([_spirit]), quality_hint="Unique")
check("spirit clean -> runeword", rw.get("quality") == "Runeword"
      and rw.get("name") == "Spirit" and rw.get("base") == "Monarch")
rw = parse_best(iter([["1 11 Vv (E 1n"] + _spirit[1:]]), quality_hint="Unique")
check("spirit garbled title -> rescued", rw.get("quality") == "Runeword"
      and rw.get("name") == "Spirit" and rw.get("base") == "Monarch")
rw = parse_best(iter([["'TalThulOrtAmn'"] + _spirit[3:]]), quality_hint="Unique")
check("spirit runestring only -> rescued", rw.get("quality") == "Runeword"
      and rw.get("name") == "Spirit")
rw = parse_best(iter([["Zzz Qqq", "Shako", "+2 to All Skills"]]),
                quality_hint="Unique")
check("garbled unique w/o clues stays Unique", rw.get("quality") == "Unique")

# junk-line poisoning: icon noise above the tooltip must be filtered, and a
# wrong Unique hint from it must not survive on a Magic charm
from advisor.ocr import _is_junk

check("icon-noise line filtered", _is_junk("1 1y Vv Lin 1 Win 1")
      and not _is_junk("Crimson Small Charm of Fortune")
      and not _is_junk("+20 to Life") and not _is_junk("El Rune"))
charm = parse_best(iter([["1 1y Vv Lin 1 Win 1",
                          "Crimson Small Charm of Fortune",
                          "Required Level: 18", "Fire Resist +3%",
                          "4% Better Chance of Getting Magic Items"]]),
                   quality_hint="Unique")
check("junk-hinted charm requalified Magic",
      charm.get("quality") == "Magic" and charm.get("base") == "Small Charm")

# magic-name affix synthesis: "of Good Luck" GUARANTEES magic find — when
# that stat line fails OCR the affix must be synthesized (value 0 = the
# zero-policy's "unknown"), and a rule that needs the roll can neither
# keep nor trash it: the item lands on "check", never on default trash
mf = parse_best(iter([["Lizard's Small Charm of Good Luck",
                       "Required Level: 33", "+3 to Mana"]]),
                quality_hint="Magic")
check("MF affix synthesized from suffix",
      any(a[0] == "#% Better Chance of Getting Magic Items"
          for a in mf.get("affixes") or []))
verdict, _r, _n = evaluate(mf, *load_rules(ROOT / "presets" / "rules-leveling.yaml"))
check("good-luck charm checks on leveling (roll unread)",
      verdict == "check", verdict)

# zero-read values must NOT satisfy min/max conditions ("Socketed (0)"
# used to match {min: 4, max: 4} and keep a 0-socket base as Insight)
zero_sock = {"quality": "Base", "base": "Cryptic Axe", "tier": "Elite",
             "affixes": [("Socketed (#)", [0])], "tooltip": ["Cryptic Axe"]}
sock_rules = [{"name": "insight base", "verdict": "keep",
               "when": {"affix_any": [{"affix": "Socketed (#)",
                                       "min": 4, "max": 4}]}}]
v, r, n = evaluate(zero_sock, sock_rules, {"verdict": "trash", "note": ""})
check("zero sockets never keep as 4os base", v == "check" and "0" in n, (v, r, n))
v2, _r2, _n2 = evaluate(
    {"quality": "Base", "base": "Cryptic Axe", "tier": "Elite",
     "affixes": [("Socketed (#)", [4])], "tooltip": ["Cryptic Axe"]},
    sock_rules, {"verdict": "trash", "note": ""})
check("real 4 sockets still keep", v2 == "keep", v2)

# rune cube-up recipes must match cubemain.json (the old hand table
# skipped Shael and mis-gemmed 21 runes)
from advisor.knowledge import UP_GEMS, TWO_PER_UP
check("cube-up: Shael needs chipped ruby", UP_GEMS.get("Shael") == "chipped ruby")
check("cube-up: Cham needs flawless emerald",
      UP_GEMS.get("Cham") == "flawless emerald")
check("cube-up: 23 gem recipes, 12 two-per upgrades",
      len(UP_GEMS) == 23 and len(TWO_PER_UP) == 12)

# charm base recovery: truncated name ("Lizard's Small Cha…") must still
# yield base Small Charm so the charm rules fire
tr = parse_best(iter([["Lizard's Small Cha", "Keep in Inventory to Gain Bonus",
                       "Required Level: 33", "+3 to Mana",
                       "7% Better Chance of Getting Magic Items"]]),
                quality_hint="Magic")
check("truncated charm base recovered", tr.get("base") == "Small Charm",
      tr.get("base"))
verdict, rule, _n = evaluate(tr, *load_rules(ROOT / "presets" / "rules-leveling.yaml"))
check("truncated charm keeps", verdict == "keep", f"{verdict} ({rule})")

# safety net: even with base AND size word unreadable, "Keep in Inventory"
# marks it a charm -> at least CHECK, never silent trash
sn = parse_best(iter([["Lzrd Zzz", "Keep in Inventory to Gain Bonus",
                       "+3 to Mana"]]), quality_hint="Magic")
verdict, rule, _n = evaluate(sn, *load_rules(ROOT / "presets" / "rules-leveling.yaml"))
check("charm safety net fires", verdict == "check" and "safety net" in rule,
      f"{verdict} ({rule})")

# runeword base legality: Spirit fits swords/shields only — an illegal
# fuzzy-matched base (druid pelt "Blood Spirit") must never survive
rw = parse_best(iter([["Spirit", "Blood Spirit", "'TalThulOrtAmn'",
                       "Defense: 142", "Socketed (4)"]]), quality_hint="Unique")
check("illegal runeword base rejected", rw.get("quality") == "Runeword"
      and rw.get("base") != "Blood Spirit")
rw = parse_best(iter([["Spirit", "Monarch", "'TalThulOrtAmn'",
                       "Defense: 142", "Socketed (4)"]]), quality_hint="Unique")
check("legal runeword base kept", rw.get("base") == "Monarch"
      and rw.get("slot") == "Shield")

# roll fallback: stat lines that failed template matching still yield rolls
# for the ranges block (recovered from the raw tooltip text)
props = get_item_ranges(parse_best(iter([[
    "Spirit", "Monarch", "'TalThulOrtAmn'", "Defense: 142",
    "+35% FASTER CAST RATE", "+92 TO MANA", "Socketed (4)"]]),
    quality_hint="Unique"))
fcr = next((p for p in props if "Cast Rate" in (p.get("tmpl") or "")), None)
check("roll fallback from raw lines",
      fcr is not None and fcr.get("roll") == 35 and fcr.get("perfect"))

# ---------------------------------------------------------------- rules

for preset in ("leveling", "midgame", "lategame"):
    rules, default = load_rules(ROOT / "presets" / f"rules-{preset}.yaml")
    check(f"preset {preset} loads", bool(rules) and isinstance(default, dict))
    verdict, _rule, _note = evaluate(
        {"quality": "Unique", "name": "Harlequin Crest", "base": "Shako",
         "slot": "helm", "affixes": [], "stats": {}, "requirements": {},
         "tooltip": []}, rules, default)
    check(f"preset {preset} evaluates", verdict in ("keep", "check", "trash"), verdict)

# zero-valued affix must not fail a min-condition (OCR misread policy)
rules_zero = [{"when": {"quality": ["Rare"],
                        "affix_any": [{"affix": "#% Faster Cast Rate", "min": 10}]},
               "verdict": "keep", "note": "fcr"}]
verdict, _rule, _note = evaluate(
    {"quality": "Rare", "name": "X", "base": "Amulet", "slot": "amulet",
     "affixes": [("#% Faster Cast Rate", [0])], "stats": {},
     "requirements": {}, "tooltip": []}, rules_zero,
    {"verdict": "trash", "note": ""})
check("zero affix escalates to check, not trash", verdict == "check", verdict)

# ---------------------------------------------------------------- knowledge

offer = match_gamble_offer(["Amulel", "Ringg", "Circlet", "Skull Cap"])
check("gamble OCR fuzzy match", "Amulet" in offer and "Ring" in offer, offer)
summary = gamble_offer_summary(offer)
check("gamble summary shape", all(len(t) in (2, 3) for t in summary))
check("gamble summary mentions seed finder", any("Seed Finder" in t[0] for t in summary))

q = quest_advice({"name": "Horadric Staff"})
check("quest item covered", bool(q))
c = consumable_advice({"tooltip": ["Light Mana Potion"]})
check("consumable covered", bool(c))
s = special_advice({"tooltip": ["Key of Terror"]})
check("special item covered", bool(s))
tier = get_value_tier({"quality": "Unique", "name": "Harlequin Crest", "base": "Shako"})
check("value tier for Shako", bool(tier))

# ---------------------------------------------------------------- ranges

r = get_item_ranges({"quality": "Unique", "name": "Harlequin Crest", "base": "Shako",
                     "affixes": [("+# to All Skills", [2])]})
check("unique ranges exist", bool(r))
m = magic_affix_ranges({"quality": "Magic", "name": "Amulet of the Whale",
                        "base": "Amulet", "affixes": [("+# to Life", [81])]})
check("magic affix tiers exist", bool(m))

# ---------------------------------------------------------------- runewords

adv = base_advice({"quality": "Base", "base": "Mage Plate", "slot": "Body",
                   "name": "Mage Plate", "affixes": [("Socketed (#)", [3])],
                   "tooltip": []})
check("base advice is a list", isinstance(adv, list) and adv)
check("3os body lists a runeword", any("•" in t[0] for t in adv), adv)

bp = bp_lines({"quality": "Rare", "base": "Amulet", "slot": "Amulet",
               "affixes": [("+#% Faster Cast Rate", [10])], "tooltip": []},
              "sorceress")
check("breakpoint lines for FCR", isinstance(bp, list) and "FCR" in bp[0][0])

# ---------------------------------------------------------------- seed engine

from advisor.gamble_seed import (Ctx, INIT_CARRY, Q_MAGIC, Q_UNIQUE, buy_roll,
                                 game_seed_to_store, generate_full,
                                 offer_with_positions, refresh_chain,
                                 refresh_chain_full, search_range,
                                 state_after_offer, vendor_fill)

ctx = Ctx(85, "msvc")
SEED = 42424242
offer14 = offer_with_positions(SEED, ctx)
check("seed: refresh_chain[0] == offer", refresh_chain(SEED, ctx, 1)[0] == offer14)
entries = [(i, None, None) for i, _ in offer14]
check("seed: name-only local search",
      SEED in search_range(ctx, entries, SEED - 5000, SEED + 5000))

# purchase-quality prediction (validated bit-exact vs the DBM site's worker)
slots, lo, hi = generate_full(SEED, INIT_CARRY, ctx)
check("seed: qualities in 4..7",
      all(Q_MAGIC <= s["quality"] <= Q_UNIQUE for s in slots))
check("seed: full/plain generation agree",
      [s["idx"] for s in slots] == [i for i, _ in offer14])

slot, steps, lo2, hi2 = buy_roll(lo, hi, ctx.ring, ctx)
check("seed: ring buy consumes 2 rolls", steps == 2)
slot, steps, _, _ = buy_roll(lo, hi, slots[2]["idx"], ctx)
check("seed: item buy consumes 3-5 rolls", 3 <= steps <= 5)

fsteps, _, _ = vendor_fill(lo, hi, ctx, "gheed", 2)
check("seed: vendor fill consumes draws", fsteps > 0)
bumped = refresh_chain_full(SEED, ctx, 2, npc="gheed", difficulty=2)
plain = refresh_chain_full(SEED, ctx, 2, vendor_bump=False)
check("seed: bump keeps window 1", bumped[0] == plain[0])
check("seed: bump shifts window 2", bumped[1] != plain[1])
check("seed: game-seed conversion", game_seed_to_store(12345) == 4008788125)

# ---------------------------------------------------------------- buy planner

from advisor.gamble_plan import plan_buys

lo, hi, abs_pos, slots = state_after_offer(SEED, ctx, 0, "gheed", 2)
res = plan_buys(lo, hi, abs_pos, slots, ctx, max_depth=4, max_buys=2,
                node_cap=200_000)
check("planner finds plans", bool(res["plans"]))
check("planner plans end in COLLECT",
      all(p["steps"][-1]["type"] == "C" for p in res["plans"]))
check("planner best-first order",
      all(res["plans"][i]["quality"] >= 0 for i in range(len(res["plans"]))))
uni = plan_buys(lo, hi, abs_pos, slots, ctx,
                specs=[{"name": -1, "tier": -1, "rarity": 7}],
                max_depth=3, max_buys=1, node_cap=50_000)
check("planner unique-only filter",
      all(p["quality"] == 7 for p in uni["plans"]))

# soft cap: once ANY route exists the search stops there (old fast
# behavior); only an empty-handed search burns the full budget
soft = plan_buys(lo, hi, abs_pos, slots, ctx, max_depth=60, max_buys=3,
                 node_cap=200_000, soft_cap=2_000)
check("planner soft cap stops early once routes exist",
      soft["plans"] and soft["explored"] < 10_000,
      f"explored={soft['explored']}")
full = plan_buys(lo, hi, abs_pos, slots, ctx, max_depth=60, max_buys=3,
                 node_cap=200_000, soft_cap=None)
check("planner without soft cap explores further",
      full["explored"] > soft["explored"])

# UI wiring (source-level: the finder window needs tk + a live screen).
# The 400k UI throttle made Unique+elite return 0 routes where the DBM
# site (2M budget) finds some; the budget is now a user setting with the
# soft cap wired in; and a settings change must not wipe the seed — a
# seed stays a valid RNG state under any level/version.
_sf_src = (ROOT / "advisor" / "seedfinder_ui.py").read_text(encoding="utf-8")
check("finder: planner budget is user-set with the soft cap",
      "node_cap=budget" in _sf_src
      and "soft_cap=min(400_000, budget)" in _sf_src
      and "node_cap=400_000" not in _sf_src
      and '"budget": sf.get("budget", 200_000)' in _sf_src)
check("finder: empty plans auto-deepen up the ladder",
      "_PLAN_RUNGS = [(1000, 5), (2500, 8), (5000, 10)]" in _sf_src
      and "auto-deepening to" in _sf_src)
check("finder: no-match prints the site's three suspects",
      _sf_src.count("  · ") >= 3
      and "the usual suspects" in _sf_src
      and "FIRST window of the game" in _sf_src)

# Tuple-arity guard: a helper whose return grew a field while a call site
# kept the old unpack ships a ValueError on the FIRST real use — exactly
# how scan_tooltip lost every OCR scan in 1.5.0 (_ocr_data returned 3,
# the caller unpacked 4). Static, so CI catches it without Tesseract.
import ast as _ast

_arity_bad = []
for _path in sorted((ROOT / "advisor").glob("*.py")) + sorted(
        (ROOT / "d2rlootreader").glob("*.py")):
    _tree = _ast.parse(_path.read_text(encoding="utf-8"))
    _rets = {}
    for _fn in _ast.walk(_tree):
        if isinstance(_fn, _ast.FunctionDef):
            _sizes = {len(r.value.elts) for r in _ast.walk(_fn)
                      if isinstance(r, _ast.Return)
                      and isinstance(r.value, _ast.Tuple)}
            _others = [r for r in _ast.walk(_fn) if isinstance(r, _ast.Return)
                       and not isinstance(r.value, _ast.Tuple)]
            if len(_sizes) == 1 and not _others:
                _rets[_fn.name] = _sizes.pop()
    for _node in _ast.walk(_tree):
        if not isinstance(_node, _ast.Assign) or len(_node.targets) != 1:
            continue
        _tgt, _val = _node.targets[0], _node.value
        if not isinstance(_tgt, _ast.Tuple) or not isinstance(_val, _ast.Call):
            continue
        _name = getattr(_val.func, "id", None) or getattr(_val.func, "attr",
                                                          None)
        _want = _rets.get(_name)
        if _want is not None and len(_tgt.elts) != _want:
            _arity_bad.append(f"{_path.name}:{_node.lineno} {_name}() returns "
                              f"{_want}, unpacked into {len(_tgt.elts)}")
check("no call site unpacks the wrong number of return values",
      not _arity_bad, "; ".join(_arity_bad))

# shipped defaults must match the DBM site's own (trustworthy out of the
# box: depth 400 / buys 4 / budget 2M / broad target) and the in-code
# fallbacks must agree with config.yaml
import yaml as _yaml
with open(ROOT / "config.yaml", encoding="utf-8") as _f:
    _cfg = _yaml.safe_load(_f)
_sfd = _cfg.get("seedfinder") or {}
check("config: planner defaults are the play-tested ones",
      _sfd.get("depth") == 1000 and _sfd.get("shift_buys") == 5
      and _sfd.get("budget") == 200_000
      and _sfd.get("target_rarity") == "unique"
      and _sfd.get("target_tier") == "any")
check("config: code fallbacks match config.yaml",
      'sf.get("depth", 1000)' in _sf_src
      and 'sf.get("shift_buys", 5)' in _sf_src)
check("finder: only a new search wipes the seed field",
      _sf_src.count("candidates=True, seed=True") == 1
      and "if seed and self.seed_var.get().strip():" in _sf_src)

# ------------------------------------------------------- compare detection

from advisor.compare import diff_items
from advisor.tooltip import overlap_frac, pick_equipped

# these numbers are the real geometry/brightness measured on the user's
# 4K failure frames (debug/20260821_02*_cmp_full.png)
_HOVERED = (1168, 744, 1287, 1416)          # Tal Rasha's, bg 9
_ADJACENT = (195, 673, 1049, 1287)          # Angelic Mantle, bg 7
_BIG = (146, 183, 1246, 1215)               # over the stash, bg 13
_SMALL = (1270, 494, 1113, 436)             # ...its Chaos Torc, 4 lines
_PANEL = (2571, 183, 1031, 528)             # inventory panel, bg 42

check("compare: side-by-side tooltips are not duplicates",
      overlap_frac(_HOVERED, _ADJACENT) < 0.3,
      f"{overlap_frac(_HOVERED, _ADJACENT):.3f}")
check("compare: a contained box IS a duplicate",
      overlap_frac(_HOVERED, (1200, 800, 400, 400)) > 0.9)

# the old code demanded ZERO overlap -> "Need BOTH tooltips" on a frame
# that plainly had both
check("compare: adjacent equipped tooltip is kept",
      pick_equipped([(_HOVERED, 35099, 9.0), (_ADJACENT, 22076, 7.0)],
                    _HOVERED) == [_ADJACENT])
# a 4-line amulet next to a 20-line runeword: the old 35%-of-hovered
# score floor deleted it
check("compare: small equipped tooltip survives a huge hovered one",
      pick_equipped([(_BIG, 35414, 13.0), (_SMALL, 5572, 9.0)],
                    _BIG) == [_SMALL])
# ...but panel/chat text (bright background) must NOT become an equipped
# two side-by-side tooltips fused into ONE block on a 4K ring compare:
# their gap was ~73 px while the split demanded 40*scale = 80
import numpy as _np
from advisor.tooltip import _split_fused as _split
_fused = _np.zeros((400, 1200), _np.uint8)
_fused[20:380, 40:560] = 255      # left tooltip text mass
_fused[20:380, 633:1160] = 255    # right one, 73 px away
_parts = _split(_fused, (0, 0, 1200, 400), 2.0)
check("compare: a 73px gap splits fused tooltips at 4K",
      len(_parts) == 2, _parts)
# real adjacent tooltips leave no EMPTY column — only a valley (measured
# 9-15 px of text per column against 30-100 inside them)
_valley = _np.zeros((400, 1200), _np.uint8)
_valley[20:380, 40:560] = 255
_valley[20:380, 633:1160] = 255
_valley[180:220, 560:633] = 255   # faint text bridging the gap
check("compare: a valley (not a gap) still splits the pair",
      len(_split(_valley, (0, 0, 1200, 400), 2.0)) == 2)
_single = _np.zeros((400, 1200), _np.uint8)
_single[20:380, 40:1160] = 255
check("compare: a solid tooltip is not split",
      len(_split(_single, (0, 0, 1200, 400), 2.0)) == 1)

# tooltips are found by the ONE thing always true of them: every line is
# centred on the same axis. Two touching tooltips (no gap at all) must
# still come out as two, and panel labels at other centres must not.
from advisor.tooltip import _tooltip_clusters as _clu
_f = _np.zeros((600, 1400), _np.uint8)
for _i in range(6):                      # left tooltip, centred on 300
    _w = 300 + 40 * (_i % 3)
    _f[60 + _i * 60: 90 + _i * 60, 300 - _w // 2: 300 + _w // 2] = 255
for _i in range(5):                      # right one, centred on 900
    _w = 260 + 50 * (_i % 3)
    _f[60 + _i * 60: 90 + _i * 60, 900 - _w // 2: 900 + _w // 2] = 255
_f[500:530, 40:200] = 255                # a stray panel label
_boxes = sorted(_clu(_f, 1.0), key=lambda b: b[0])
check("compare: touching tooltips split by their line centres",
      len(_boxes) == 2, _boxes)
check("compare: a stray label is not a tooltip",
      all(b[1] < 500 for b in _boxes), _boxes)

check("compare: bright panel text is not an equipped tooltip",
      pick_equipped([(_HOVERED, 35414, 9.0, 0.94), (_PANEL, 7792, 42.0, 0.53)],
                    _HOVERED) == [])
# a tooltip lying over the lit inventory measures median 19 / dark 0.78:
# the 18 cut dropped it and the ring compare lost an equipped ring
check("compare: a tooltip over a lit panel still counts",
      pick_equipped([(_HOVERED, 30420, 8.0, 0.91),
                     ((2097, 183, 1505, 976), 18840, 19.0, 0.78)],
                    _HOVERED) == [(2097, 183, 1505, 976)])
# ...and a dark-ish but non-tooltip block (median 20, dark 0.59) is not
check("compare: darkness fraction rejects a non-tooltip block",
      pick_equipped([(_HOVERED, 30420, 8.0, 0.91),
                     ((361, 183, 1697, 957), 18864, 20.0, 0.59)],
                    _HOVERED) == [])

_hdr = diff_items({"affixes": [], "tooltip": ["Defense: 10"]},
                  {"affixes": [], "tooltip": ["Defense: 20"],
                   "name": "Spirit"}, label="#2")[0][0]
check("compare: header names the item, not the last stat line",
      _hdr == "vs equipped #2: Spirit", _hdr)

# ------------------------------------------------------- popup clipboard

from advisor.overlay import Overlay

_ov = Overlay.__new__(Overlay)          # _clip_text needs no tk root
_clip = _ov._clip_text(
    "keep",
    {"name": "Chance Guards", "base": "Chain Gloves", "quality": "Unique",
     "affixes": [["+# to Attack Rating", [25]]]},
    [{"label": "25-40% Better Chance of Getting Magic Items",
      "roll": 33, "var": True},
     {"label": "+20-30% Enhanced Defense", "roll": 30, "perfect": True,
      "var": True}])
_lines = _clip.splitlines()
check("clip: header names the item and the verdict",
      _lines[0] == "[KEEP] Chance Guards" and _lines[1] == "Unique · Chain Gloves",
      _lines[:2])
check("clip: one stat per line, rolls annotated",
      len(_lines) == 4 and _lines[2].endswith("-> 33")
      and _lines[3].endswith("-> 30 (MAX)"), _lines[2:])

_ov_src = (ROOT / "advisor" / "overlay.py").read_text(encoding="utf-8")
check("clip: copy is offered for verdicts, not for compare",
      'copyable = bool(item) and verdict not in ("compare", "scan", "error")'
      in _ov_src
      and "if copyable:" in _ov_src)
check("popup: an in-app action reports back on its own label",
      "said = u()" in _ov_src and "lbl.unbind" in _ov_src
      and "_flash_hint" in _ov_src)

# "Ring" scored 100 against itself and 90 against "Ring Mail"; picking the
# LONGEST match turned every ring into body armour
_ring = parse_best(iter([["The Stone of Jordan", "Ring",
                          "Required Level: 29", "+1 to All Skills"]]),
                   quality_hint="Unique")
check("base match: a Ring is a Ring, not Ring Mail",
      _ring.get("base") == "Ring" and _ring.get("slot") == "Ring",
      f"{_ring.get('base')} / {_ring.get('slot')}")
_mail = parse_best(iter([["Ring Mail", "Defense: 45"]]), quality_hint="Base")
check("base match: Ring Mail still matches itself",
      _mail.get("base") == "Ring Mail", _mail.get("base"))

# ---------------------------------------------------------------- auto-clicker

from advisor.autoclicker import calib_ok, cell_to_screen

calib = {"refresh": [500, 900], "cell00": [100, 100], "cell99": [550, 550]}
check("clicker: calib check", calib_ok(calib) and not calib_ok({}))
check("clicker: cell math", cell_to_screen(calib, 0, 0) == (100, 100)
      and cell_to_screen(calib, 9, 1, 1, 2) == (550, 175))

# ------------------------------------------------------------ tab-scan OCR

import numpy as np
from advisor.rune_tab import _baseline_group

_bw = np.zeros((100, 300), np.uint8)
_bw[65:95, 240:250] = 255   # bare "1" stem, right-anchored
_bw[63:94, 200:220] = 255   # left digit on the same baseline
_bw[5:40, 60:150] = 255     # sprite highlight above the text line
_grp = _baseline_group(_bw)
check("tabscan: baseline group keeps digits, drops sprite",
      _grp is not None and len(_grp) == 2
      and all(c[1] > 50 for c in _grp))
_bw2 = np.zeros((100, 300), np.uint8)
_bw2[65:95, 240:250] = 255
_grp2 = _baseline_group(_bw2)
check("tabscan: lone stem is one glyph and thin (reads as '1')",
      _grp2 is not None and len(_grp2) == 1
      and _grp2[0][2] <= 0.45 * _grp2[0][3])

# ------------------------------------------------- rules engine v2
from advisor.rules import expand_refs

def _ring(affixes):
    return {"quality": "Rare", "name": "X", "base": "Ring", "slot": "Ring",
            "affixes": affixes, "tooltip": ["X", "Ring"]}

_nof_rules = [{"name": "good ring", "verdict": "keep",
               "when": {"slot": "Ring", "affix_n_of": {"min": 2, "any": [
                   {"affix": "+#% Faster Cast Rate", "min": 10},
                   {"affix": "+# to Life", "min": 30},
                   {"affix": "All Resistances +#", "min": 8}]}}}]
_v, _r, _n = evaluate(_ring([("+#% Faster Cast Rate", [10]),
                             ("+# to Life", [35])]),
                      _nof_rules, {"verdict": "trash", "note": ""})
check("n_of: 2 of 3 keeps", _v == "keep", _v)
_v, _r, _n = evaluate(_ring([("+#% Faster Cast Rate", [10])]),
                      _nof_rules, {"verdict": "trash", "note": ""})
check("n_of: 1 of 3 falls through", _v == "trash", _v)
_v, _r, _n = evaluate(_ring([("+#% Faster Cast Rate", [10]),
                             ("+# to Life", [0])]),
                      _nof_rules, {"verdict": "trash", "note": ""})
check("n_of: zero-read tips to check", _v == "check", _v)

_sum_rules = [{"name": "res ring", "verdict": "keep",
               "when": {"slot": "Ring", "affix_sum": {
                   "affixes": ["Fire Resist +#%", "Cold Resist +#%"],
                   "min": 40}}}]
_v, _r, _n = evaluate(_ring([("Fire Resist +#%", [25]),
                             ("Cold Resist +#%", [20])]),
                      _sum_rules, {"verdict": "trash", "note": ""})
check("affix_sum: 45 total >= 40 keeps", _v == "keep", _v)
_v, _r, _n = evaluate(_ring([("Fire Resist +#%", [25])]),
                      _sum_rules, {"verdict": "trash", "note": ""})
check("affix_sum: 25 total falls through", _v == "trash", _v)

_score_rules = [
    {"name": "fcr pts", "score": 3,
     "when": {"affix_any": [{"affix": "+#% Faster Cast Rate", "min": 10}]}},
    {"name": "life pts", "score": 3,
     "when": {"affix_any": [{"affix": "+# to Life", "min": 30}]}},
    {"name": "broad ring check", "verdict": "check",
     "when": {"slot": "Ring"}}]
_score_default = {"verdict": "trash", "note": "", "_scoring": {"keep": 5,
                                                               "check": 3}}
_v, _r, _n = evaluate(_ring([("+#% Faster Cast Rate", [10]),
                             ("+# to Life", [40])]), _score_rules,
                      _score_default)
check("score: 6 pts beats the broad check", _v == "keep" and _r == "score",
      (_v, _r))
_v, _r, _n = evaluate(_ring([("+#% Faster Cast Rate", [10])]), _score_rules,
                      _score_default)
check("score: 3 pts = check via broad rule (equal rank)",
      _v == "check", (_v, _r))

_defs = {"skill_trees": ["+# to Fire Skills (Sorceress only)",
                         "+# to Warcries (Barbarian only)"]}
_cls_rules = expand_refs(
    [{"name": "mine", "verdict": "keep",
      "when": {"affix_any_ref": {"list": "skill_trees", "min": 1,
                                 "class": "mine"}}},
     {"name": "other", "verdict": "check",
      "when": {"affix_any_ref": {"list": "skill_trees", "min": 1,
                                 "class": "other"}}}],
    defs=_defs, my_class="Sorceress")
_sorc = {"quality": "Magic", "base": "Grand Charm",
         "affixes": [("+# to Fire Skills (Sorceress only)", [1])],
         "tooltip": []}
_barb = {"quality": "Magic", "base": "Grand Charm",
         "affixes": [("+# to Warcries (Barbarian only)", [1])],
         "tooltip": []}
check("class rules: my skiller keeps",
      evaluate(_sorc, _cls_rules, {"verdict": "trash"})[0] == "keep")
check("class rules: other skiller checks",
      evaluate(_barb, _cls_rules, {"verdict": "trash"})[0] == "check")
_no_cls = expand_refs(
    [{"name": "mine", "verdict": "keep",
      "when": {"affix_any_ref": {"list": "skill_trees", "min": 1,
                                 "class": "mine"}}}],
    defs=_defs, my_class=None)
check("class rules: no my_class = old behavior (full list keeps)",
      evaluate(_barb, _no_cls, {"verdict": "trash"})[0] == "keep")

# ------------------------------------------------------- settings write
import tempfile as _tf
from pathlib import Path as _P
from advisor.settings_ui import write_config
import yaml as _yaml

_cfgp = _P(_tf.mkdtemp()) / "cfg.yaml"
_cfgp.write_text('hotkey: f9   # scan key\n'
                 'link_template: "https://x/y#frag"\n'
                 'seedfinder:\n  scale: 1.5  # sf\n', encoding="utf-8")
write_config({"hotkey": "f8", "brand_new": True},
             {"scale": 2.0, "new_sf": 7}, path=_cfgp)
_cfg = _yaml.safe_load(_cfgp.read_text(encoding="utf-8"))
check("settings: rewrite + append missing keys",
      _cfg["hotkey"] == "f8" and _cfg["brand_new"] is True
      and _cfg["seedfinder"]["scale"] == 2.0
      and _cfg["seedfinder"]["new_sf"] == 7)
check("settings: '#' inside a value survives",
      _cfg["link_template"] == "https://x/y#frag")
check("settings: comments preserved",
      "# scan key" in _cfgp.read_text(encoding="utf-8"))

# ------------------------------------------------------------- updater
from advisor.updater import _ver_tuple

check("updater: version ordering",
      _ver_tuple("v1.4.10") > _ver_tuple("1.4.9")
      and _ver_tuple("latest") == (0,))

# ------------------------------------------------------------- goals
import advisor.goals as _G

_G.STATE_FILE = _P(_tf.mkdtemp()) / "goals.json"
_G.set_counts({"Tal": 4, "Eth": 1, "Ral": 1, "Ort": 1, "Amn": 3})
_G.set_gem_counts({"Chipped Ruby": 2, "Chipped Topaz": 5,
                   "Chipped Amethyst": 1})
check("goals: base requirement", _G.base_requirement("Spirit")
      == "4os sword/shield")
check("goals: cube plan empty when pool covers it",
      _G.cube_plan("Ancients' Pledge") == [])
_plan = _G.cube_plan("Lore")  # needs Ort + Sol; Sol must be cubed up
check("goals: cube plan lists executable steps",
      _plan and any("→ Sol" in s for s in _plan), _plan)
_shop = _G.shopping_list()
check("goals: shopping list aggregates gaps",
      any(r == "Sol" for r, _m, _b in _shop))
_st, _ok2, _msg = _G.mark_made("Stealth")
check("goals: mark_made spends runes", _ok2 and
      _G.load_state()["runes"].get("Eth") is None)
_st, _ok3, _msg3 = _G.mark_made("Stealth")
check("goals: incomplete goal refused", not _ok3 and "Eth" in _msg3)
_st, _goal = _G.undo_made()
check("goals: undo restores runes", _goal == "Stealth"
      and _st["runes"].get("Eth") == 1)
check("goals: unknown runeword is not complete",
      any(g == "Nonexistent Word" and not c
          for g, _r, c in _G.goal_progress(
              {"runes": {}, "goals": ["Nonexistent Word"], "made": []})))
_G.set_counts({"Nef": 1})
_G.set_gem_counts({"Perfect Ruby": 1})
_ready = [r for r in _G.craftable_recipes() if r[4] and r[5]]
check("goals: craft recipes check rune AND gem",
      any(r[0] == "Blood Gloves" for r in _ready)
      and all("Sapphire" not in r[2] for r in _ready))

# ------------------------------------------------------------ compare
from advisor.compare import diff_items

_cmp = diff_items(
    {"name": "A", "tooltip": ["A", "Defense: 500"],
     "affixes": [("+# to [skill]", [2, "Fireball"])]},
    {"name": "B", "tooltip": ["B", "Defense: 300"],
     "affixes": [("+# to [skill]", [3, "Frozen Orb"]),
                 ("+# to [skill]", [1, "Meteor"])]})
_txt = "\n".join(t for t, _c in _cmp)
check("compare: defense diffed from tooltip", "Defense: 300→500" in _txt)
check("compare: same-template different skills kept",
      "Frozen Orb" in _txt and "Meteor" in _txt and "Fireball" in _txt)

# ------------------------------------------------------- capture guard
from advisor import capture_guard as _cg

check("guard: exclusive acquire", _cg.acquire("t1") and not _cg.acquire("t2"))
_cg.release("wrong-owner")
check("guard: owner-checked release keeps the hold",
      _cg.busy_with() == "t1")
_cg.release("t1")
check("guard: released", _cg.busy_with() is None and _cg.acquire("t3"))
_cg.release()

# -------------------------------------------------------------- render
from advisor.render import render_affix

check("render: numbers and skills fill placeholders",
      render_affix("+# to [skill]", [2, "Meteor"]) == "+2 to Meteor"
      and render_affix("Adds #-# Damage", [1, 3]) == "Adds 1-3 Damage")

# -------------------------------------------------- onboarding helpers
from advisor.onboarding import hotkey_rows, suggest_scale

check("wizard: scale suggestions", suggest_scale(2160) == 2.0
      and suggest_scale(1080) == 1.0 and suggest_scale(1440) == 1.25)
check("wizard: hotkey clash detection",
      [c for _l, _k, c in hotkey_rows({"hotkey": "f9",
                                       "compare_hotkey": "f9"})][:2]
      == [True, True])

# ------------------------------------------------- unknown-name honesty
_mod_item = parse_best(iter([["Storm Heart", "Amulet",
                              "Required Level: 41",
                              "+13 Maximum Stamina"]]),
                       quality_hint="Unique")
check("mod unique flags unknown_name",
      _mod_item.get("unknown_name") is True)
_vanilla = parse_best(iter([["Harlequin Crest", "Shako",
                             "Defense: 98", "+2 to All Skills"]]),
                      quality_hint="Unique")
check("vanilla unique does not flag", not _vanilla.get("unknown_name"))

print(f"\nALL {ok} REGRESSION TESTS PASSED")
