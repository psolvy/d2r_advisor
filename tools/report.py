"""Session report from history.log.

Summarizes your scans: verdict counts, keeps by quality, runes found (with
cube-up progress and runewords you could complete), and the most-hit rules.

Usage:  python tools/report.py [--today]
"""
import json
import re
import sys
from collections import Counter
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:  # Windows consoles default to cp1252 — force UTF-8 for the dashes etc.
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

RUNE_RE = re.compile(r"^([A-Za-z]+) Rune$")


def load_entries(only_today=False):
    entries = []
    try:
        with open(ROOT / "history.log", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    e = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if only_today and not str(e.get("time", "")).startswith(date.today().isoformat()):
                    continue
                entries.append(e)
    except FileNotFoundError:
        pass
    return entries


def main():
    only_today = "--today" in sys.argv
    entries = load_entries(only_today)
    scope = "today" if only_today else "all time"
    if not entries:
        print(f"history.log has no scans ({scope}). Play a bit first!")
        return 0

    print(f"=== D2R Item Advisor — session report ({scope}, {len(entries)} scans) ===\n")

    verdicts = Counter(e.get("verdict") for e in entries)
    print("Verdicts: " + " · ".join(f"{v}: {n}" for v, n in verdicts.most_common()))

    keeps = [e for e in entries if e.get("verdict") == "keep"]
    by_quality = Counter(e.get("quality") or "?" for e in keeps)
    print("Keeps by quality: " + (" · ".join(f"{q}: {n}" for q, n in by_quality.most_common()) or "—"))

    named = Counter(e.get("name") for e in keeps
                    if e.get("name") and e.get("quality") in ("Unique", "Set", "Runeword"))
    if named:
        print("\nNamed keeps:")
        for name, n in named.most_common(15):
            print(f"  {n}× {name}")

    runes = Counter()
    for e in entries:
        m = RUNE_RE.match((e.get("name") or "").strip())
        if m:
            runes[m.group(1).capitalize()] += 1
    if runes:
        from advisor.knowledge import RUNE_ORDER
        ordered = sorted(runes.items(), key=lambda kv: RUNE_ORDER.index(kv[0])
                         if kv[0] in RUNE_ORDER else 99)
        print("\nRunes scanned: " + " · ".join(f"{r}×{n}" for r, n in ordered))
        # Which runewords could be completed from scanned runes alone?
        try:
            with open(ROOT / "d2rlootreader" / "repository" / "runewords_full.json",
                      encoding="utf-8") as f:
                rws = json.load(f)
            makeable = [name for name, rw in sorted(rws.items())
                        if all(runes.get(r, 0) >= Counter(rw["runes"])[r]
                               for r in set(rw["runes"]))]
            if makeable:
                print("Runewords covered by scanned runes: " + ", ".join(makeable[:12])
                      + ("…" if len(makeable) > 12 else ""))
        except (FileNotFoundError, json.JSONDecodeError):
            pass

    rules = Counter(e.get("rule") for e in entries if e.get("rule"))
    print("\nTop rules hit:")
    for rule, n in rules.most_common(8):
        print(f"  {n}× {rule}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
