"""Extract planner/vendor data from the DBM bundles into gamble_engine.json."""
import json
import re
from pathlib import Path

HERE = Path(__file__).parent
OUT = HERE.parents[1] / "d2rlootreader" / "repository" / "gamble_engine.json"

sw = (HERE / "search.worker.js").read_text(encoding="utf8")
rj = (HERE / "render.js").read_text(encoding="utf8")


def js_array(src, name):
    m = re.search(re.escape(name) + r"=\[", src)
    assert m, name
    i = m.end() - 1
    depth = 0
    for j in range(i, len(src)):
        if src[j] == "[":
            depth += 1
        elif src[j] == "]":
            depth -= 1
            if depth == 0:
                return json.loads(src[i:j + 1])
    raise ValueError(name)


def js_object(src, name):
    m = re.search(re.escape(name) + r"=\{", src)
    assert m, name
    i = m.end() - 1
    depth = 0
    for j in range(i, len(src)):
        if src[j] == "{":
            depth += 1
        elif src[j] == "}":
            depth -= 1
            if depth == 0:
                raw = src[i:j + 1]
                raw = raw.replace("!0", "true").replace("!1", "false")
                raw = re.sub(r"([{,])([A-Za-z_][A-Za-z0-9_]*):", r'\1"\2":', raw)
                return json.loads(raw)
    raise ValueError(name)


unique_lvl = js_array(sw, "ne")   # per-item min qlvl for a unique to exist, -1 none
set_lvl = js_array(sw, "ae")     # per-item min qlvl for a set item, -1 none
assert len(unique_lvl) == 659 and len(set_lvl) == 659

npc_index = js_object(rj, "we")   # gheed:0 ...
npc_caps = js_array(rj, "ge")     # normal-difficulty level caps per npc index
specs = js_object(rj, "xe")       # per-npc store fill specs
extras = js_object(rj, "pe")      # per-npc extra rows (potions/keys)

data = json.loads(OUT.read_text(encoding="utf8"))
data["unique_lvl"] = unique_lvl
data["set_lvl"] = set_lvl
data["quality_thresholds"] = {"unique": 50, "set": 100, "rare": 10000, "den": 100000}
data["versions"] = {
    "d2": {"label": "Diablo II Classic", "row_pool": False,
           "reassemble_vendor": False, "reroll_bought_slot": False,
           "game_seed_warmup": 3},
    "d2r": {"label": "Diablo II Resurrected", "row_pool": False,
            "reassemble_vendor": True, "reroll_bought_slot": True,
            "game_seed_warmup": 4},
    "row": {"label": "Diablo II Reign of the Warlock", "row_pool": True,
            "reassemble_vendor": True, "reroll_bought_slot": True,
            "game_seed_warmup": 4},
}
data["vendor_fill"] = {"npc_index": npc_index, "npc_caps": npc_caps,
                       "specs": specs, "extras": extras}

OUT.write_text(json.dumps(data), encoding="utf8")
ok_uni = sum(1 for v in unique_lvl if v >= 0)
ok_set = sum(1 for v in set_lvl if v >= 0)
print(f"unique-capable items: {ok_uni}, set-capable: {ok_set}")
print(f"npcs: {list(npc_index)}, caps {npc_caps}")
for npc, lst in specs.items():
    print(f"  {npc}: {len(lst)} fill specs, extras {len(extras.get(npc, []))}")
print("gamble_engine.json updated")
