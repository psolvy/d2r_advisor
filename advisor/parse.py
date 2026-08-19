"""Robust parsing wrapper around d2rlootreader's ItemParser.

OCR of a real screen often leaves noise lines before the item name.
We try parsing with several leading-line offsets and keep the best result.
"""
import re

from d2rlootreader.item_parser import ItemParser

# Prefixes that appear on plain (non-magic) bases.
_BASE_PREFIX = re.compile(r"^\W*(superior|inferior|cracked|damaged|crude|low quality|gemmed)\s+", re.I)

_QUALITY_WEIGHT = {
    "Unique": 5,
    "Set": 5,
    "Runeword": 5,
    "Rare": 4,
    "Crafted": 4,
    "Magic": 3,
    "Base": 1,
    "Unknown": 0,
    None: 0,
}


def _zero_param_affixes(item):
    """Affixes whose first numeric value read as 0 — no D2 affix rolls 0,
    so these are always OCR misreads."""
    count = 0
    for tmpl, params in item.get("affixes") or []:
        if "#" in tmpl and params and params[0] == 0:
            count += 1
    return count


def _score(item) -> float:
    s = float(_QUALITY_WEIGHT.get(item.get("quality"), 0))
    if item.get("base"):
        s += 3
    if item.get("name"):
        s += 1
    s += len(item.get("affixes") or []) * 0.6
    s += len(item.get("stats") or {}) * 0.4
    s += len(item.get("requirements") or {}) * 0.2
    s -= _zero_param_affixes(item) * 0.5  # prefer the variant that read the digits
    return s


def parse_tooltip(lines, max_offset=6, quality_hint=None):
    """Parse OCR lines into an item dict, tolerating leading noise lines."""
    best, best_score, best_offset = None, -1.0, 0
    for offset in range(0, min(max_offset, max(0, len(lines) - 1)) + 1):
        candidate = ItemParser(lines[offset:], quality_hint=quality_hint).parse_item_lines_to_json()
        sc = _score(candidate)
        if sc > best_score:
            best_score, best, best_offset = sc, candidate, offset
    if best is None:
        best = ItemParser(lines, quality_hint=quality_hint).parse_item_lines_to_json()

    # A "Base" whose first line is much longer than the matched base name is
    # almost certainly a Magic/Rare item whose OCR'd name didn't fuzzy-match.
    # With a color hint the quality is already trusted — skip the heuristic.
    base = best.get("base")
    if quality_hint is None and best.get("quality") == "Base" and base and best_offset < len(lines):
        name_line = _BASE_PREFIX.sub("", lines[best_offset]).strip()
        name_line = re.sub(r"[\W_]+$", "", name_line)  # trailing OCR junk
        if len(name_line) > len(base) + 5:
            best["quality"] = "Magic"
            best["name"] = name_line

    # Superior bases: the matcher strips the prefix — restore it in the
    # display name (superior status matters: better stats, Larzuk-only sockets).
    if best.get("quality") == "Base" and best.get("base"):
        for ln in lines[:2]:
            if ln.strip().lower().startswith("superior "):
                best["name"] = f"Superior {best['base']}"
                best["superior"] = True
                break

    best["tooltip"] = lines
    return _sanitize_affixes(best)


# Hard game-data bounds for parsed affix values. OCR loves turning a closing
# bracket into a digit ("Socketed (2)" -> 21); trailing digits are stripped
# until the value is plausible.
_AFFIX_BOUNDS = {
    "Socketed (#)": (1, 6),
}


def _sanitize_affixes(item):
    fixed = []
    for entry in item.get("affixes") or []:
        tmpl, params = entry[0], list(entry[1] or [])
        bounds = _AFFIX_BOUNDS.get(tmpl)
        if bounds and params and isinstance(params[0], int):
            lo, hi = bounds
            v = params[0]
            s = str(v)
            while len(s) > 1 and not (lo <= int(s) <= hi):
                s = s[:-1]
            if lo <= int(s) <= hi:
                params[0] = int(s)
        fixed.append((tmpl, params))
    item["affixes"] = fixed
    return item


# --------------------------------------------------------------- runeword rescue
# Runeword titles ("Spirit") render in the huge gold font that OCR garbles
# most often. When that happens the parser falls back to Unique with the
# garbage as the name — and the base matcher can then grab a look-alike base
# ("Spirit" fuzzy-hits the druid pelt "Blood Spirit"). But a runeword can be
# identified from OTHER lines too: its name line or the quoted rune string
# ('TalThulOrtAmn' segments uniquely into Tal+Thul+Ort+Amn).

_RUNE_NAMES = sorted(
    ("el", "eld", "tir", "nef", "eth", "ith", "tal", "ral", "ort", "thul",
     "amn", "sol", "shael", "dol", "hel", "io", "lum", "ko", "fal", "lem",
     "pul", "um", "mal", "ist", "gul", "vex", "ohm", "lo", "sur", "ber",
     "jah", "cham", "zod"), key=len, reverse=True)
_RUNESTRING_RE = re.compile(r"^[\'\"‘’“”]?([A-Za-z]{4,40})"
                            r"[\'\"‘’“”]?$")
_known_db_cache = None


def _segment_runes(line):
    """'TalThulOrtAmn' -> ['tal','thul','ort','amn'], or None."""
    m = _RUNESTRING_RE.match(line.strip())
    if not m:
        return None
    t = m.group(1).lower()
    out, i = [], 0
    while i < len(t):
        for r in _RUNE_NAMES:
            if t.startswith(r, i):
                out.append(r)
                i += len(r)
                break
        else:
            return None
    return out if len(out) >= 2 else None


def _known_db():
    global _known_db_cache
    if _known_db_cache is None:
        import json
        from d2rlootreader.cfg import REPOSITORY_DIR

        def load(fn):
            try:
                with open(REPOSITORY_DIR / fn, encoding="utf-8") as f:
                    return json.load(f)
            except (FileNotFoundError, json.JSONDecodeError):
                return {}

        rw = load("runewords_full.json")
        _known_db_cache = {
            "rw_names": list(rw.keys()),
            "rw_full": rw,
            "rw_by_runes": {tuple(r.lower() for r in v.get("runes", [])): k
                            for k, v in rw.items()},
            "uniques": {k.lower() for k in load("uniques.json")},
            "sets": {k.lower() for k in load("set.json")},
            "bases": load("bases.json"),
        }
    return _known_db_cache


def _name_known(item):
    """Did the parsed name actually match the databases for its quality?"""
    db = _known_db()
    name = (item.get("name") or "").strip().lower()
    q = item.get("quality")
    if q == "Unique":
        return name in db["uniques"]
    if q == "Set":
        return name in db["sets"]
    if q == "Runeword":
        return name in {n.lower() for n in db["rw_names"]}
    return True


def _adjusted_score(item):
    """_score plus DB-trust: matched names are worth keeping, garbage names
    (digit-ridden junk the Unique fallback kept) are worth abandoning."""
    s = _score(item)
    name = (item.get("name") or "").strip()
    if item.get("quality") in ("Unique", "Set", "Runeword"):
        if _name_known(item):
            s += 2.0
        else:
            s -= 1.0
    if name:
        digits = sum(ch.isdigit() for ch in name)
        has_word = any(sum(ch.isalpha() for ch in t) >= 4
                       for t in name.split())
        if digits / max(1, len(name)) > 0.2 or not has_word:
            s -= 2.0
    return s


def _fix_runeword_base(item):
    """A runeword can only exist in bases its recipe allows (Spirit: swords
    and shields — never a druid pelt, even if 'Blood Spirit' fuzzy-matched
    the garbled title). Re-match the base among LEGAL bases, or drop it."""
    if item.get("quality") != "Runeword" or not item.get("name"):
        return item
    from advisor.runewords import _fits
    db = _known_db()
    rw = db["rw_full"].get(item["name"])
    if not rw:
        return item
    base = item.get("base")
    if base and item.get("slot") and _fits(rw, item["slot"], base):
        return item
    legal = {n: v for n, v in db["bases"].items()
             if isinstance(v, dict) and _fits(rw, v.get("slot"), n)}
    from rapidfuzz import fuzz, process
    best = None
    for ln in (item.get("tooltip") or [])[:5]:
        # base lines are pure item names — stat lines (digits/colons) would
        # only produce false matches ("Defense: 142" -> "Defender")
        if ":" in ln or any(ch.isdigit() for ch in ln):
            continue
        s = re.sub(r"[^A-Za-z ]", "", ln).strip()
        if len(s) < 3:
            continue
        m = process.extractOne(s, list(legal.keys()), scorer=fuzz.ratio,
                               processor=str.lower, score_cutoff=80)
        if m and (best is None or m[1] > best[1]):
            best = m
    if best:
        name = best[0]
        item["base"] = name
        item["slot"] = legal[name].get("slot")
        item["tier"] = legal[name].get("tier")
    else:
        # a wrong base is worse than none — ranges/advice key off the name
        item["base"] = None
        item["slot"] = None
        item["tier"] = None
    return item


def _runeword_rescue(item):
    """Requalify a garbled-title 'Unique' as the runeword it really is."""
    if item.get("quality") != "Unique":
        return item
    db = _known_db()
    if (item.get("name") or "").strip().lower() in db["uniques"]:
        return item  # a real unique matched — trust it
    lines = item.get("tooltip") or []
    from rapidfuzz import fuzz, process
    rw_name = None
    for ln in lines[:6]:
        s = re.sub(r"[^A-Za-z ]", "", ln).strip()
        if len(s) >= 4:
            m = process.extractOne(s, db["rw_names"], scorer=fuzz.ratio,
                                   processor=str.lower, score_cutoff=87)
            if m:
                rw_name = m[0]
                break
        runes = _segment_runes(ln)
        if runes:
            rw_name = db["rw_by_runes"].get(tuple(runes))
            if rw_name:
                break
    if not rw_name:
        return item
    fixed = ItemParser([rw_name] + lines[1:],
                       quality_hint="Runeword").parse_item_lines_to_json()
    if fixed.get("quality") == "Runeword":
        fixed["tooltip"] = lines
        return _sanitize_affixes(fixed)
    return item


_CHARM_RE = re.compile(r"\b(small|large|grand)\s+ch[a-z]*", re.I)


def _charm_base_recovery(item):
    """Charm names truncate in OCR ("Lizard's Small Cha…") and the charm
    rules key on the base — recover it from any partial mention in the name
    or the first tooltip lines. Only fires when no base was recognized."""
    if item.get("base") or item.get("quality") not in ("Magic", "Unique",
                                                       "Base", "Unknown"):
        return item
    hay = [item.get("name") or ""] + list((item.get("tooltip") or [])[:3])
    for txt in hay:
        m = _CHARM_RE.search(txt)
        if m:
            base = f"{m.group(1).title()} Charm"
            entry = _known_db()["bases"].get(base)
            item["base"] = base
            if isinstance(entry, dict):
                item["slot"] = entry.get("slot") or item.get("slot")
                item["tier"] = entry.get("tier") or item.get("tier")
            break
    return item


_affix_name_map_cache = None


def _affix_name_map():
    """{prefix/suffix name (lower) -> affix template}, unambiguous only."""
    global _affix_name_map_cache
    if _affix_name_map_cache is None:
        import json
        from d2rlootreader.cfg import REPOSITORY_DIR
        m = {}
        try:
            with open(REPOSITORY_DIR / "ranges.json", encoding="utf-8") as f:
                tiers = json.load(f).get("affix_tiers", {})
        except (FileNotFoundError, json.JSONDecodeError):
            tiers = {}
        for tmpl, entries in tiers.items():
            for t in entries:
                n = (t.get("name") or "").lower()
                if not n:
                    continue
                if n in m and m[n] != tmpl:
                    m[n] = None  # same name on different stats — ambiguous
                elif n not in m:
                    m[n] = tmpl
        _affix_name_map_cache = {k: v for k, v in m.items() if v}
    return _affix_name_map_cache


def _magic_affix_synthesis(item):
    """A Magic item's prefix/suffix GUARANTEE stats ("of Good Luck" IS magic
    find). The name renders big and OCRs well even when a stat line doesn't —
    synthesize any guaranteed stat missing from the parsed affixes with
    value 0: the zero-policy already treats 0 as 'unknown, err toward keep'
    and the popup flags it."""
    if item.get("quality") != "Magic" or not item.get("name"):
        return item
    name_map = _affix_name_map()
    if not name_map:
        return item
    name = item["name"].strip().lower()
    if " of " in f" {name} ":
        pre, _, suf = f" {name} ".partition(" of ")
        parts = [pre.strip(), ("of " + suf).strip()]
    else:
        parts = [name]
    have = {a[0] for a in item.get("affixes") or []}
    for part in parts:
        tmpl = name_map.get(part)
        if tmpl and tmpl not in have:
            item.setdefault("affixes", []).append((tmpl, [0]))
    return item


GOOD_ENOUGH = 7.0  # early-exit score: confident quality + base + some affixes


def parse_best(line_variants, quality_hint=None):
    """Parse OCR variants (lazily) and return the best-scoring item.

    Stops early as soon as a variant parses confidently, so the second
    (slower) OCR pass only runs when the first one was poor.
    """
    best, best_score = None, -1.0
    seen = []
    variant_items = []
    for lines in line_variants:
        seen.append(lines)
        item = parse_tooltip(lines, quality_hint=quality_hint)
        variant_items.append(item)
        sc = _score(item)
        if sc > best_score:
            best_score, best = sc, item
        # Only stop early on a confident *named* item — a "Base" parse can be
        # a misread Unique/Set, so always try the next OCR variant for those.
        # A zero-valued affix is a misread digit: give the next pass a chance.
        # Unknown names (mod items) have no database to validate rolls
        # against — force the second pass so digits get a second opinion.
        if (best_score >= GOOD_ENOUGH and best.get("quality") != "Base"
                and _zero_param_affixes(best) == 0 and _name_known(best)):
            break
    if best is None:
        best = parse_tooltip([], quality_hint=quality_hint)

    # Second opinion: a gold/green hint from a junk line above the tooltip
    # forces Unique/Set onto items that are really Magic/Rare. When the name
    # matched nothing, re-parse hint-free and keep whichever reads better.
    cands = [best]
    if best.get("quality") in ("Unique", "Set") and not _name_known(best):
        for lines in seen:
            cands.append(parse_tooltip(lines, quality_hint=None))
    cands = [_fix_runeword_base(_runeword_rescue(c)) for c in cands]
    best = _charm_base_recovery(max(cands, key=_adjusted_score))
    best = _magic_affix_synthesis(best)

    # Digit cross-check: when the OCR passes disagree on an affix value
    # ('+13' vs '+15' — 3/5 confusion in the game font), keep the chosen
    # value but FLAG it so the popup says "check by eye" instead of
    # presenting a silent misread as fact.
    uncertain = {}
    chosen = {t: p for t, p in best.get("affixes") or []}
    for other in variant_items:
        if other is best:
            continue
        for tmpl, params in other.get("affixes") or []:
            if tmpl not in chosen:
                continue
            a = next((p for p in chosen[tmpl] or []
                      if isinstance(p, (int, float))
                      and not isinstance(p, bool)), None)
            b = next((p for p in params or []
                      if isinstance(p, (int, float))
                      and not isinstance(p, bool)), None)
            if a is not None and b is not None and a != b and 0 not in (a, b):
                uncertain.setdefault(tmpl, set()).update((a, b))
    if uncertain:
        best["uncertain"] = {t: sorted(v) for t, v in uncertain.items()}
    return best
