"""Generate repository/cube.json — craft recipes and base tier-upgrade chains.

- crafts: parsed from cubemain.json descriptions (authoritative for the
  current patch, including D2R's expanded craft base lists). Each craft's
  base list is expanded through exceptional/elite versions ("upg" inputs).
- tier_up: base name -> next-tier base name (for unique/rare upgrade advice).

Usage:  python tools/gen_cube.py
"""
import json
import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CACHE = Path(__file__).resolve().parent / "_cache"
OUT = ROOT / "d2rlootreader" / "repository" / "cube.json"

_CRAFT_RE = re.compile(
    r"^1 Magic (?P<base>.+?) \+ 1 Jewel \+ (?:1 )?(?P<rune>\w+) Rune \+ (?:1 )?Perfect (?P<gem>\w+)"
    r"\s*->\s*(?P<out>.+)$"
)


def fetch(name):
    CACHE.mkdir(exist_ok=True)
    path = CACHE / name
    if not path.exists():
        print(f"downloading {name} ...")
        urllib.request.urlretrieve(
            "https://raw.githubusercontent.com/blizzhackers/d2data/master/json/" + name, path)
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def build_code_maps():
    """code -> name, and code -> (normcode, ubercode, ultracode)."""
    names, chains = {}, {}
    for src in ("weapons.json", "armor.json", "misc.json"):
        for entry in fetch(src).values():
            code, name = entry.get("code"), entry.get("name")
            if code and name:
                names[code] = name
                chains[code] = (entry.get("normcode"), entry.get("ubercode"),
                                entry.get("ultracode"))
    return names, chains


def main():
    names, chains = build_code_maps()

    # ---- tier-up map: normal -> exceptional -> elite ------------------------
    tier_up = {}
    for code, (norm, uber, ultra) in chains.items():
        name = names.get(code)
        if not name:
            continue
        if code == norm and uber and uber != code and names.get(uber):
            tier_up[name] = names[uber]
        elif code == uber and ultra and ultra != code and names.get(ultra):
            tier_up[name] = names[ultra]

    # ---- craft recipes ------------------------------------------------------
    crafts = []
    for entry in fetch("cubemain.json").values():
        if not isinstance(entry, dict) or "crf" not in str(entry.get("output", "")):
            continue
        m = _CRAFT_RE.match(entry.get("description", ""))
        if not m:
            print("WARN: unparsed craft:", entry.get("description"))
            continue
        base = m.group("base").strip()
        # "upg" input flag: the recipe accepts the base and its upgraded tiers.
        bases = [base]
        if "upg" in str(entry.get("input 1", "")):
            b = base
            while b in tier_up:
                b = tier_up[b]
                bases.append(b)
        craft_type = m.group("out").rsplit(" ", 1)[0]  # "Hit Power Helm" -> "Hit Power"
        crafts.append({
            "type": craft_type,
            "result": m.group("out").strip(),
            "bases": bases,
            "rune": m.group("rune"),
            "gem": f"P.{m.group('gem')}",
        })

    with open(OUT, "w", encoding="utf-8") as f:
        json.dump({"crafts": crafts, "tier_up": tier_up}, f, ensure_ascii=False, indent=1)
    print(f"written {OUT}: {len(crafts)} crafts, {len(tier_up)} tier-up links")
    return 0


if __name__ == "__main__":
    sys.exit(main())
