"""Preset lint: catch rules that can NEVER fire before players do.

A rule whose affix template has a typo, or whose base/slot name does not
exist in the repository, silently matches nothing — the item falls
through to the wrong verdict. Run on every preset + rules.yaml; CI runs
this too.

    python tools/validate_presets.py
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import yaml

REPO = ROOT / "d2rlootreader" / "repository"
VERDICTS = {"keep", "check", "trash"}
# "Unknown" is what the parser emits when the name line didn't read
QUALITIES = {"Base", "Magic", "Rare", "Crafted", "Set", "Unique", "Runeword",
             "Unknown"}
COND_KEYS = {"quality", "slot", "tier", "base_any", "name_any", "ethereal",
             "text_any", "text_all", "line_any", "affix_all", "affix_any",
             "no_base", "sockets_min", "sockets_max", "level_max",
             "level_min"}


def _load(name):
    with open(REPO / name, encoding="utf-8") as f:
        return json.load(f)


def main():
    affixes = set(_load("affixes.json"))
    bases = _load("bases.json")
    base_names = {b.lower() for b in bases}
    slots = {v.get("slot") for v in bases.values()}
    known_names = {n.lower() for n in _load("uniques.json")}
    known_names |= {n.lower() for n in _load("set.json")}
    known_names |= {n.lower() for n in _load("runewords_full.json")}

    files = sorted((ROOT / "presets").glob("rules-*.yaml"))
    files.append(ROOT / "rules.yaml")
    errors = warnings = 0

    for path in files:
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        rules = data.get("rules", [])
        problems = []

        def err(msg):
            problems.append(("ERROR", msg))

        def warn(msg):
            problems.append(("warn", msg))

        seen_names = set()
        for i, rule in enumerate(rules, 1):
            label = f"rule {i} ({rule.get('name', '?')})"
            if rule.get("verdict") not in VERDICTS:
                err(f"{label}: bad verdict {rule.get('verdict')!r}")
            if rule.get("name") in seen_names:
                warn(f"{label}: duplicate rule name")
            seen_names.add(rule.get("name"))
            when = rule.get("when") or {}
            if not when:
                warn(f"{label}: empty when — matches EVERYTHING")
            for key in when:
                if key not in COND_KEYS:
                    err(f"{label}: unknown condition {key!r}")
            for q in (when.get("quality") or []) if isinstance(
                    when.get("quality"), list) else (
                    [when["quality"]] if when.get("quality") else []):
                if q not in QUALITIES:
                    err(f"{label}: unknown quality {q!r}")
            for s in (when.get("slot") or []) if isinstance(
                    when.get("slot"), list) else (
                    [when["slot"]] if when.get("slot") else []):
                if s not in slots:
                    err(f"{label}: unknown slot {s!r}")
            # the engine matches base_any/name_any as SUBSTRINGS
            for b in when.get("base_any") or []:
                if not any(b.lower() in bn for bn in base_names):
                    err(f"{label}: base {b!r} matches no base in bases.json")
            for n in when.get("name_any") or []:
                if not any(n.lower() in kn for kn in known_names):
                    warn(f"{label}: name {n!r} matches no known item")
            for ck in ("affix_all", "affix_any"):
                for cond in when.get(ck) or []:
                    t = cond.get("affix")
                    if t not in affixes:
                        err(f"{label}: affix template {t!r} not in "
                            "affixes.json — this condition NEVER fires")
                    extra = set(cond) - {"affix", "min", "max", "param"}
                    if extra:
                        err(f"{label}: unknown affix keys {sorted(extra)}")

        tag = "OK" if not problems else ""
        print(f"== {path.name}: {len(rules)} rules {tag}")
        for lv, msg in problems:
            print(f"   [{lv}] {msg}")
            if lv == "ERROR":
                errors += 1
            else:
                warnings += 1

    print(f"\n{errors} error(s), {warnings} warning(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
