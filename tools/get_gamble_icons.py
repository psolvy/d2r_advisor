"""Download the gamble item icons (98 px per inventory cell, alpha PNGs)
from the DBM gambling simulator's assets into repository/gamble_icons/.

They are the templates for icon-based offer recognition (advisor/
gamble_vision.py) — the resurrected-graphics gamble window has no text
to OCR, only icons. Re-run after tools/update_repository.py if the item
pool ever changes.
"""
import json
import os
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "d2rlootreader" / "repository" / "gamble_icons"
BASE_URL = "https://gambling.diablo.deadlybossmods.com/items/{}.png"


def main():
    with open(ROOT / "d2rlootreader" / "repository" / "gamble_engine.json",
              encoding="utf-8") as f:
        data = json.load(f)
    codes = {"rin", "amu", "ci0", "ci1", "ci2", "ci3"}
    for platform in data["pool_orders"].values():
        for pool in platform.values():
            codes.update(pool)
    OUT.mkdir(parents=True, exist_ok=True)
    ok = fail = skip = 0
    for code in sorted(codes):
        dest = OUT / f"{code}.png"
        if dest.exists() and dest.stat().st_size > 0:
            skip += 1
            continue
        try:
            data = urllib.request.urlopen(
                BASE_URL.format(code), timeout=30).read()
            # atomic: two racing processes (update-restart overlap) must
            # never leave a half-written template on disk
            tmp = dest.with_suffix(f".{os.getpid()}.tmp")
            tmp.write_bytes(data)
            os.replace(tmp, dest)
            ok += 1
        except Exception as e:
            print(f"FAIL {code}: {e}")
            fail += 1
    print(f"{ok} downloaded, {skip} already present, {fail} failed "
          f"({len(codes)} codes) -> {OUT}")
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
