"""Bit-exact validation of the Python planner against the site's search.worker."""
import json
import random
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, r"C:\Users\solopa\env\d2r-advisor")
HERE = Path(__file__).parent

from advisor.gamble_seed import Ctx, state_after_offer
from advisor.gamble_plan import plan_buys

random.seed(20260819)
CASES = []
for _ in range(8):
    CASES.append({
        "seed": random.getrandbits(32),
        "level": random.choice([12, 45, 60, 75, 85, 92, 99]),
        "platform": random.choice(["msvc", "gcc", "freebsd", "msvc-std"]),
        "maxDepth": random.choice([3, 4]),
        "maxBuys": random.choice([1, 2]),
    })

fails = 0
for n, case in enumerate(CASES):
    ctx = Ctx(case["level"], case["platform"], version="d2r")
    lo, hi, abs_pos, slots = state_after_offer(case["seed"], ctx,
                                               vendor_bump=False)
    win = [{"idx": s["idx"], "quality": s["quality"], "tier": s["tier"]}
           for s in slots]
    worker_input = {
        "lo": lo, "hi": hi, "absPos": abs_pos, "win": win,
        "level": case["level"], "rowPool": False,
        "poolOrder": case["platform"], "wcBinds": [],
        "rerollBoughtSlot": True,
        "maxDepth": case["maxDepth"], "maxBuys": case["maxBuys"],
        "specs": [],
    }
    inp = HERE / f"case_{n}.json"
    inp.write_text(json.dumps(worker_input), encoding="utf8")
    js = json.loads(subprocess.run(
        ["node", str(HERE / "run_worker.js"), str(inp)],
        capture_output=True, text=True, check=True).stdout)

    py = plan_buys(lo, hi, abs_pos, slots, ctx,
                   max_depth=case["maxDepth"], max_buys=case["maxBuys"])

    def norm_plan(p, js_side):
        if js_side:
            steps = [(s["type"], s["slot"], s["baseIdx"], s["x"], s["y"],
                      s["cost"], s["recvIdx"], s["recvQuality"], s["recvTier"])
                     for s in p["steps"]]
            return (steps, p["recvIdx"], p["quality"], p["tier"], p["baseIdx"],
                    p["endAbs"], p["depth"], p["buys"], p["routes"])
        steps = [(s["type"], s["slot"], s["idx"], s["x"], s["y"], s["cost"],
                  s["recv"]["idx"] if s["recv"] else -1,
                  s["recv"]["quality"] if s["recv"] else 0,
                  s["recv"]["tier"] if s["recv"] else 0)
                 for s in p["steps"]]
        return (steps, p["recv_idx"], p["quality"], p["tier"], p["base_idx"],
                p["end_abs"], p["depth"], p["buys"], p["routes"])

    js_plans = [norm_plan(p, True) for p in js["plans"]]
    py_plans = [norm_plan(p, False) for p in py["plans"]]
    meta_js = (js["explored"], js["nodes"], js["capped"], js["outcomes"])
    meta_py = (py["explored"], py["nodes"], py["capped"], py["outcomes"])
    ok = js_plans == py_plans
    meta_ok = meta_js == meta_py
    print(f"case {n}: lvl {case['level']} {case['platform']} depth "
          f"{case['maxDepth']} buys {case['maxBuys']} -> plans "
          f"{len(py_plans)} {'MATCH' if ok else 'MISMATCH'}; meta "
          f"{'match' if meta_ok else f'{meta_js} vs {meta_py}'}")
    if not ok:
        fails += 1
        for a, b in zip(js_plans, py_plans):
            if a != b:
                print(" js:", a[1:], "\n py:", b[1:])
                for x, y in zip(a[0], b[0]):
                    if x != y:
                        print("  step js", x, "\n  step py", y)
                break
        if len(js_plans) != len(py_plans):
            print(f"  count js {len(js_plans)} vs py {len(py_plans)}")

print("ALL PLANNER CASES MATCH" if fails == 0 else f"{fails} FAILURES")
sys.exit(1 if fails else 0)
