"""Verdict engine: match a parsed item against user rules (rules.yaml).

Rules are evaluated top-down; the first matching rule wins.
Verdicts: keep / check / trash.
"""

from pathlib import Path

import yaml

VERDICTS = ("keep", "check", "trash")

_DEFS_FILE = Path(__file__).resolve().parents[1] / "presets" / "_common.yaml"


def _load_defs():
    try:
        return yaml.safe_load(_DEFS_FILE.read_text(encoding="utf-8")) or {}
    except OSError:
        return {}


def expand_refs(rules, defs=None, my_class=None):
    """Resolve affix_any_ref / affix_all_ref against presets/_common.yaml:
    {list: skill_trees, min: 1} becomes one {affix: name, min: 1}
    condition per name. The 21-entry skiller list and the 28-entry
    +2-skills list used to be copy-pasted across all four rule files.

    An optional class filter makes rules class-aware:
      {list: skill_trees, min: 1, class: mine}  -> only templates that
        mention my_class ("(Sorceress only)"); with NO my_class
        configured the filter is ignored (full list — old behavior);
      {list: skill_trees, min: 1, class: other} -> only templates of
        OTHER classes; with no my_class it expands to nothing (the rule
        never fires)."""
    defs = _load_defs() if defs is None else defs
    mc = (my_class or "").strip().lower()
    for rule in rules:
        when = rule.get("when") or {}
        for key in ("affix_any", "affix_all"):
            ref = when.pop(key + "_ref", None)
            if not ref:
                continue
            names = defs.get(ref.get("list")) or []
            cls = ref.get("class")
            if cls == "mine" and mc:
                names = [n for n in names if mc in n.lower()]
            elif cls == "other":
                names = [n for n in names if mc not in n.lower()] if mc \
                    else []
            extra = {k: v for k, v in ref.items()
                     if k not in ("list", "class")}
            when[key] = (when.get(key) or []) + [
                {"affix": n, **extra} for n in names]
    return rules


def load_rules(path, my_class=None):
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    rules = expand_refs(data.get("rules", []), my_class=my_class)
    default = data.get("default", {"verdict": "trash", "note": ""})
    # score-rule thresholds ride along inside default (signature stays
    # (rules, default) for every existing caller)
    if isinstance(data.get("scoring"), dict):
        default = dict(default)
        default["_scoring"] = data["scoring"]
    return rules, default


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

    # "at least N of these" — what rare ring/amulet evaluation needs
    # ("any 2 of: FCR, dual leech, +life, +res"). A zero-read value can
    # neither count nor be dismissed: when reads-as-0 conds could tip the
    # count over the bar, the rule goes indeterminate.
    n_of = when.get("affix_n_of")
    if n_of:
        need = int(n_of.get("min", 1))
        results = [_affix_cond_ok(item, c) for c in n_of.get("any", [])]
        hits = sum(1 for r in results if r is True)
        maybe = sum(1 for r in results if r is None)
        if hits < need:
            if hits + maybe >= need:
                indeterminate = True
            else:
                return False

    # sum of numeric params across several templates (every occurrence
    # counts) — e.g. total resistances over the four single-res affixes
    asum = when.get("affix_sum")
    if asum:
        wanted = set(_as_list(asum.get("affixes")) or [])
        total, zero_seen = 0, False
        for entry in item.get("affixes") or []:
            if entry[0] not in wanted:
                continue
            val = next((p for p in entry[1] or []
                        if isinstance(p, (int, float))
                        and not isinstance(p, bool)), None)
            if val == 0:
                zero_seen = True
            elif val is not None:
                total += val
        if "min" in asum and total < asum["min"]:
            if zero_seen:
                indeterminate = True
            else:
                return False
        if "max" in asum and total > asum["max"]:
            return False

    # A rule that would need a value that read as 0 can neither match nor
    # reject — the caller skips it and flags the item for eye-checking.
    return None if indeterminate else True


_RANK = {"keep": 2, "check": 1, "trash": 0}


def evaluate(item, rules, default):
    """Return (verdict, rule_name, note).

    Rules with a `score: N` field (no verdict) accumulate points instead
    of deciding; a top-level `scoring: {keep: X, check: Y}` block in the
    rules file converts the total. The score verdict wins over a normal
    first-match verdict only when it is BETTER (keep > check > trash) —
    precise scored rules can no longer be shadowed by an earlier broad
    rule, and broad safety nets still catch everything else."""
    unreadable = None
    score = 0
    for rule in rules:
        got = _matches(item, rule.get("when", {}))
        if got is None and unreadable is None:
            unreadable = rule.get("name", "unnamed rule")
            continue
        if not got:
            continue
        if "score" in rule and "verdict" not in rule:
            score += rule["score"]
            continue
        verdict = rule.get("verdict", "check")
        sv = _score_verdict(score, default)
        if sv and _RANK[sv] > _RANK.get(verdict, 1):
            return (sv, "score", f"{score} points")
        return verdict, rule.get("name", "unnamed rule"), rule.get("note", "")
    sv = _score_verdict(score, default)
    if sv:
        return (sv, "score", f"{score} points")
    if unreadable and default.get("verdict", "trash") == "trash":
        # Don't trash an item a rule couldn't judge because of a misread.
        return ("check", unreadable,
                "a value read as 0 — check by eye")
    return default.get("verdict", "trash"), "default", default.get("note", "")


def _score_verdict(score, default):
    thresholds = default.get("_scoring")
    if not thresholds or score <= 0:
        return None
    if score >= thresholds.get("keep", 1 << 30):
        return "keep"
    if score >= thresholds.get("check", 1 << 30):
        return "check"
    return None
