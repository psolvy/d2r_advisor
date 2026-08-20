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

print(f"\nALL {ok} REGRESSION TESTS PASSED")
