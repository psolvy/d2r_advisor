"""Generate repository/gamble.json — gambling targets per gamble-screen base.

For every base on the gamble screen: which uniques/sets can roll on it and
the chase magic affixes, each with the affix/quality level needed. The
advisor computes the required character level at runtime
(ilvl = clvl-5..clvl+4, plus the circlet family's hidden magic level).

Usage:  python tools/gen_gamble.py   (run from anywhere)
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gen_ranges import SIMPLE, SKILL_TABS, fetch  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "d2rlootreader" / "repository" / "gamble.json"

# Affix codes worth gambling for.
CHASE_CODES = {"ama", "sor", "nec", "pal", "bar", "dru", "ass",
               "skilltab", "cast1", "cast2", "cast3", "mag%"}


def affix_label(row, i):
    code = row.get(f"mod{i}code")
    lo, hi = row.get(f"mod{i}min") or 0, row.get(f"mod{i}max") or 0
    r = str(lo) if lo == hi else f"{lo}-{hi}"
    if code == "skilltab":
        try:
            tab = SKILL_TABS[int(row.get(f"mod{i}param"))][0]
        except (KeyError, ValueError, TypeError):
            return None
        return f"+{r} to {tab}"
    entry = SIMPLE.get(code)
    if not entry:
        return None
    return entry[0].format(r=r)


def main():
    # base code -> (name, type, magic lvl); code -> tier chain (norm/uber/ultra)
    info = {}
    chains = {}
    for src in ("weapons.json", "armor.json", "misc.json"):
        for e in fetch(src).values():
            if e.get("code") and e.get("name"):
                info[e["code"]] = (e["name"], e.get("type"), int(e.get("magic lvl") or 0))
                chain = [e["code"]]
                for k in ("ubercode", "ultracode"):
                    c = e.get(k)
                    if c and c not in chain:
                        chain.append(c)
                chains[e["code"]] = chain

    gamble_codes = [v["code"] for v in fetch("gamble.json").values() if v.get("code")]

    from display_names import display_name
    uniques_by_code = {}
    for it in fetch("uniqueitems.json").values():
        if it.get("spawnable") and not it["index"].startswith(("PreCrafted", "Unique ", "Crafted ")):
            uniques_by_code.setdefault(it.get("code"), []).append(
                {"name": display_name(it["index"]),
                 "alvl": int(it.get("lvl") or 1)})
    sets_by_code = {}
    for it in fetch("setitems.json").values():
        sets_by_code.setdefault(it.get("item"), []).append(
            {"name": it["index"], "alvl": int(it.get("lvl") or 1)})

    # chase affixes grouped by item type code
    affixes_by_type = {}
    for src in ("magicprefix.json", "magicsuffix.json"):
        for row in fetch(src).values():
            if not row.get("spawnable") or not row.get("Name"):
                continue
            if row.get("mod1code") not in CHASE_CODES:
                continue
            label = affix_label(row, 1)
            if not label:
                continue
            lvl = int(row.get("level") or 1)
            for i in range(1, 8):
                t = row.get(f"itype{i}")
                if t:
                    cur = affixes_by_type.setdefault(t, {})
                    # same label may exist at several levels; keep the lowest
                    if label not in cur or lvl < cur[label]:
                        cur[label] = lvl

    out = {}
    for code in gamble_codes:
        name, itype, maglvl = info.get(code, (None, None, 0))
        if not name:
            continue
        # Gambled bases can upgrade to exceptional/elite versions — include
        # uniques of the whole tier chain (how a Circlet gamble hits Griffon's).
        uniques, sets_ = [], []
        for c in chains.get(code, [code]):
            uniques += uniques_by_code.get(c, [])
            sets_ += sets_by_code.get(c, [])
        uniques = sorted(uniques, key=lambda u: -u["alvl"])[:6]
        sets_ = sorted(sets_, key=lambda u: -u["alvl"])[:4]
        chase = [{"label": lbl, "alvl": lvl}
                 for lbl, lvl in sorted(affixes_by_type.get(itype, {}).items(),
                                        key=lambda kv: -kv[1])][:6]
        out[name] = {"maglvl": maglvl, "uniques": uniques, "sets": sets_, "affixes": chase}

    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1, sort_keys=True)
    print(f"written {OUT} ({len(out)} gamble bases)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
