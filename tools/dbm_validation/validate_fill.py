"""Validate vendor_fill against render.js's own ye() across the matrix."""
import json
import random
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, r"C:\Users\solopa\env\d2r-advisor")
HERE = Path(__file__).parent

from advisor.gamble_seed import Ctx, vendor_fill

random.seed(7)
cases = []
for npc in ("gheed", "elzix", "alkor", "jamella", "anya"):
    for difficulty in (0, 1, 2):
        for level in (5, 12, 19, 20, 24, 25, 26, 30, 45, 85, 99):
            cases.append({"lo": random.getrandbits(32),
                          "hi": random.getrandbits(16),
                          "npc": npc, "rowPool": False,
                          "level": level, "difficulty": difficulty})
inp = HERE / "fill_cases.json"
inp.write_text(json.dumps(cases), encoding="utf8")
js = json.loads(subprocess.run(["node", str(HERE / "run_fill.js"), str(inp)],
                               capture_output=True, text=True, check=True).stdout)

fails = 0
for c, expect in zip(cases, js):
    ctx = Ctx(c["level"], "msvc", version="d2r")
    steps, lo, hi = vendor_fill(c["lo"], c["hi"], ctx, c["npc"], c["difficulty"])
    got = {"steps": steps, "lo": lo, "hi": hi}
    if got != expect:
        fails += 1
        print(f"MISMATCH {c['npc']} lvl {c['level']} diff {c['difficulty']}: "
              f"py {got} vs js {expect}")
print(f"{len(cases)} fill cases, "
      + ("ALL MATCH" if fails == 0 else f"{fails} FAILURES"))
sys.exit(1 if fails else 0)
