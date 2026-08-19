"""Generate repository/runewords_full.json — runeword recipes with base types.

For each complete runeword: rune list (in order), socket count and the item
type codes it can be made in. Used by the advisor to list which runewords fit
a hovered white base. Source: d2data runes.json (cached in tools/_cache).

Usage:  python tools/gen_runewords.py
"""
import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CACHE = Path(__file__).resolve().parent / "_cache"
OUT = ROOT / "d2rlootreader" / "repository" / "runewords_full.json"

RUNE_NAMES = [
    "El", "Eld", "Tir", "Nef", "Eth", "Ith", "Tal", "Ral", "Ort", "Thul", "Amn",
    "Sol", "Shael", "Dol", "Hel", "Io", "Lum", "Ko", "Fal", "Lem", "Pul", "Um",
    "Mal", "Ist", "Gul", "Vex", "Ohm", "Lo", "Sur", "Ber", "Jah", "Cham", "Zod",
]
RUNE_BY_CODE = {f"r{i + 1:02d}": n for i, n in enumerate(RUNE_NAMES)}


def fetch(name):
    CACHE.mkdir(exist_ok=True)
    path = CACHE / name
    if not path.exists():
        print(f"downloading {name} ...")
        urllib.request.urlretrieve(
            "https://raw.githubusercontent.com/blizzhackers/d2data/master/json/" + name, path)
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def main():
    out = {}
    for entry in fetch("runes.json").values():
        if not entry.get("complete"):
            continue
        name = entry.get("*Rune Name") or entry.get("Name")
        if not name:
            continue
        runes = [RUNE_BY_CODE.get(entry.get(f"Rune{i}"))
                 for i in range(1, 7) if entry.get(f"Rune{i}")]
        types = [entry.get(f"itype{i}") for i in range(1, 7) if entry.get(f"itype{i}")]
        excl = [entry.get(f"etype{i}") for i in range(1, 4) if entry.get(f"etype{i}")]
        out[name] = {"runes": runes, "sockets": len(runes), "types": types}
        if excl:
            out[name]["exclude"] = excl

    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1, sort_keys=True)
    print(f"written {OUT} ({len(out)} runewords)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
