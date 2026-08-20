"""Verdict engine: match a parsed item against user rules (rules.yaml).

Rules are evaluated top-down; the first matching rule wins.
Verdicts: keep / check / trash.
"""

import yaml

VERDICTS = ("keep", "check", "trash")


def load_rules(path):
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return data.get("rules", []), data.get("default", {"verdict": "trash", "note": ""})


def _as_list(v):
    if v is None:
        return None
    return v if isinstance(v, list) else [v]


def _affix_value(item, template, param_index=0):
    """Return the numeric param of an affix if present, else None."""
    for entry in item.get("affixes") or []:
        tmpl, params = entry[0], entry[1]
        if tmpl == template:
            if not params:
                return 0
            try:
                return params[param_index]
            except (IndexError, TypeError):
                return 0
    return None


def _affix_cond_ok(item, cond):
    """True / False / None — None means the value read as 0 (an OCR
    misread; no D2 affix rolls 0) so the condition is INDETERMINATE.
    The old behavior treated 0 as a match, which let 'Socketed (0)'
    satisfy {min: 4, max: 4} and keep a 0-socket base as an Insight
    candidate."""
    template = cond.get("affix")
    val = _affix_value(item, template, cond.get("param", 0))
    if val is None:
        return False
    if val == 0 and "#" in (template or ""):
        return None
    if "min" in cond and not (isinstance(val, (int, float)) and val >= cond["min"]):
        return False
    if "max" in cond and not (isinstance(val, (int, float)) and val <= cond["max"]):
        return False
    return True


def _matches(item, when):
    q = _as_list(when.get("quality"))
    if q and item.get("quality") not in q:
        return False

    slot = _as_list(when.get("slot"))
    if slot and item.get("slot") not in slot:
        return False

    tier = _as_list(when.get("tier"))
    if tier and item.get("tier") not in tier:
        return False

    base_any = _as_list(when.get("base_any"))
    if base_any:
        base = (item.get("base") or "").lower()
        if not any(s.lower() in base for s in base_any):
            return False

    # no_base: true — matches only items with NO recognized base (runes, gems,
    # misread lines). Keeps base items like "Rune Sword" out of rune catch-alls.
    if when.get("no_base") and item.get("base"):
        return False

    name_any = _as_list(when.get("name_any"))
    if name_any:
        name = (item.get("name") or "").lower()
        if not any(s.lower() in name for s in name_any):
            return False

    # Substring match across all raw tooltip lines (runes/gems/jewels say
    # "Can be Inserted into Socketed Items" and have no parsed base).
    text_any = _as_list(when.get("text_any"))
    if text_any:
        joined = "\n".join(item.get("tooltip") or []).lower()
        if not any(s.lower() in joined for s in text_any):
            return False

    # Like text_any, but ALL substrings must be present somewhere in the tooltip.
    text_all = _as_list(when.get("text_all"))
    if text_all:
        joined = "\n".join(item.get("tooltip") or []).lower()
        if not all(s.lower() in joined for s in text_all):
            return False

    # Exact (whole-line, case-insensitive) match against any tooltip line —
    # for rune/gem names where substrings collide ("Um Rune" vs "Lum Rune").
    line_any = _as_list(when.get("line_any"))
    if line_any:
        lines = {ln.strip().lower() for ln in item.get("tooltip") or []}
        if not any(s.lower() in lines for s in line_any):
            return False

    if when.get("ethereal"):
        # The game line is "Ethereal (Cannot Be Repaired)" — the bare affix
        # match can miss it, so fall back to a raw tooltip substring.
        if _affix_value(item, "Ethereal") is None and _affix_value(
                item, "Ethereal (Cannot be Repaired)") is None:
            joined = " ".join(item.get("tooltip") or []).lower()
            if "ethereal" not in joined:
                return False

    indeterminate = False
    for cond in when.get("affix_all", []):
        ok = _affix_cond_ok(item, cond)
        if ok is False:
            return False
        if ok is None:
            indeterminate = True

    affix_any = when.get("affix_any", [])
    if affix_any:
        results = [_affix_cond_ok(item, c) for c in affix_any]
        if not any(r is True for r in results):
            if any(r is None for r in results):
                indeterminate = True
            else:
                return False

    # A rule that would need a value that read as 0 can neither match nor
    # reject — the caller skips it and flags the item for eye-checking.
    return None if indeterminate else True


def evaluate(item, rules, default):
    """Return (verdict, rule_name, note)."""
    unreadable = None
    for rule in rules:
        got = _matches(item, rule.get("when", {}))
        if got is None and unreadable is None:
            unreadable = rule.get("name", "unnamed rule")
            continue
        if got:
            return (
                rule.get("verdict", "check"),
                rule.get("name", "unnamed rule"),
                rule.get("note", ""),
            )
    if unreadable and default.get("verdict", "trash") == "trash":
        # Don't trash an item a rule couldn't judge because of a misread.
        return ("check", unreadable,
                "a value read as 0 — check by eye")
    return default.get("verdict", "trash"), "default", default.get("note", "")
