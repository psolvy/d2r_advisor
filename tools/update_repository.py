"""Merge new game content from d2data into the local repository JSONs.

Adds missing uniques, set items, runewords and base items (slot/tier) so the
fuzzy matcher knows current-patch names. Safe to re-run any time; existing
entries are never overwritten. Run gen_ranges.py afterwards.

Usage:  python tools/update_repository.py
"""
import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CACHE = Path(__file__).resolve().parent / "_cache"
REPO = ROOT / "d2rlootreader" / "repository"

D2DATA_RAW = "https://raw.githubusercontent.com/blizzhackers/d2data/master/json/"

RUNE_NAMES = [
    "El", "Eld", "Tir", "Nef", "Eth", "Ith", "Tal", "Ral", "Ort", "Thul", "Amn",
    "Sol", "Shael", "Dol", "Hel", "Io", "Lum", "Ko", "Fal", "Lem", "Pul", "Um",
    "Mal", "Ist", "Gul", "Vex", "Ohm", "Lo", "Sur", "Ber", "Jah", "Cham", "Zod",
]
RUNE_BY_CODE = {f"r{i + 1:02d}": n for i, n in enumerate(RUNE_NAMES)}

# d2data item type -> repository slot vocabulary
TYPE_SLOT = {
    "swor": "Sword", "knif": "Dagger", "club": "Club", "hamm": "Hammer",
    "mace": "Mace", "staf": "Staff", "grim": "Grimoire", "tpot": "Throwing",
    "tors": "Body", "axe": "Axe", "pole": "Polearm", "spea": "Spear",
    "wand": "Wand", "scep": "Scepter", "bow": "Bow", "xbow": "Crossbow",
    "jave": "Javelin", "helm": "Helm", "shie": "Shield", "boot": "Boots",
    "glov": "Gloves", "belt": "Belt", "orb": "Orb", "h2h": "Katar",
}

SKIP_UNIQUE_PREFIXES = ("PreCrafted ", "Unique ", "Crafted ")


def fetch(name):
    CACHE.mkdir(exist_ok=True)
    path = CACHE / name
    if not path.exists():
        print(f"downloading {name} ...")
        urllib.request.urlretrieve(D2DATA_RAW + name, path)
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_repo(name):
    with open(REPO / name, encoding="utf-8") as f:
        return json.load(f)


def save_repo(name, data):
    with open(REPO / name, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1, sort_keys=True)


def tier_of(entry):
    code = entry.get("code")
    if code and code == entry.get("ultracode"):
        return "Elite"
    if code and code == entry.get("ubercode"):
        return "Exceptional"
    return "Normal"


def main():
    added = {"bases": 0, "uniques": 0, "sets": 0, "runewords": 0}
    warnings = []

    # ---- bases -------------------------------------------------------------
    bases = load_repo("bases.json")
    by_lower = {k.lower(): k for k in bases}
    for src in ("weapons.json", "armor.json"):
        for entry in fetch(src).values():
            name = entry.get("name")
            if not name:
                continue
            existing = by_lower.get(name.lower())
            if existing is None:
                slot = TYPE_SLOT.get(entry.get("type"))
                if not slot:
                    warnings.append(f"base '{name}': unknown type '{entry.get('type')}', skipped")
                    continue
                bases[name] = {"slot": slot, "tier": tier_of(entry)}
                by_lower[name.lower()] = name
                existing = name
                added["bases"] += 1
            # Max socket count (Larzuk/cube cap) — used for runeword advice.
            sock = entry.get("gemsockets")
            if sock not in (None, ""):
                bases[existing]["maxsock"] = int(sock)
    save_repo("bases.json", bases)
    known_lower = set(by_lower)  # base-name check for uniques/sets below

    # ---- uniques -----------------------------------------------------------
    from display_names import display_name
    uniques = load_repo("uniques.json")
    uniq_lower = {k.lower() for k in uniques}
    for entry in fetch("uniqueitems.json").values():
        name = display_name(entry.get("index"))
        if not name or not entry.get("spawnable"):
            continue
        if name.startswith(SKIP_UNIQUE_PREFIXES):
            continue
        if name.lower() in uniq_lower:
            continue
        base = entry.get("*ItemName") or ""
        uniques[name] = base
        uniq_lower.add(name.lower())
        added["uniques"] += 1
        if base and base.lower() not in known_lower:
            warnings.append(f"unique '{name}': base '{base}' not in bases.json")
    save_repo("uniques.json", uniques)

    # ---- set items ---------------------------------------------------------
    sets = load_repo("set.json")
    set_lower = {k.lower() for k in sets}
    for entry in fetch("setitems.json").values():
        name = entry.get("index")
        if not name or name.lower() in set_lower:
            continue
        base = entry.get("*ItemName") or ""
        sets[name] = base
        set_lower.add(name.lower())
        added["sets"] += 1
        if base and base.lower() not in known_lower:
            warnings.append(f"set item '{name}': base '{base}' not in bases.json")
    save_repo("set.json", sets)

    # ---- runewords ---------------------------------------------------------
    runewords = load_repo("runewords.json")
    rw_lower = {k.lower() for k in runewords}
    for entry in fetch("runes.json").values():
        if not entry.get("complete"):
            continue
        name = entry.get("*Rune Name") or entry.get("Name")
        if not name or name.lower() in rw_lower:
            continue
        runes = "".join(
            RUNE_BY_CODE.get(entry.get(f"Rune{i}") or "", "?") for i in range(1, 7)
            if entry.get(f"Rune{i}")
        )
        runewords[name] = runes
        rw_lower.add(name.lower())
        added["runewords"] += 1
    save_repo("runewords.json", runewords)

    print("added:", added)
    for w in warnings:
        print("WARN:", w)
    print("Now run: python tools/gen_ranges.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
