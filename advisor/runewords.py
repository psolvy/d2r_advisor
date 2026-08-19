"""Runeword advice for white bases.

Given a parsed Base-quality item (slot, base name, socket count), list the
runewords that fit it — exact socket matches first, then other socket counts —
and, for socketless bases, the socket-adding recipes (Larzuk / cube).

Data: repository/runewords_full.json (see tools/gen_runewords.py).
"""
import json

from advisor.links import recipe_url, runeword_url
from d2rlootreader.cfg import REPOSITORY_DIR

# d2data item-type code -> advisor slot names it covers.
_TYPE_SLOTS = {
    "weap": ["Sword", "Axe", "Polearm", "Spear", "Staff", "Wand", "Scepter", "Mace",
             "Club", "Hammer", "Dagger", "Bow", "Crossbow", "Javelin", "Katar", "Orb",
             "Grimoire"],
    "mele": ["Sword", "Axe", "Polearm", "Spear", "Staff", "Wand", "Scepter", "Mace",
             "Club", "Hammer", "Dagger", "Katar", "Orb", "Grimoire"],
    "miss": ["Bow", "Crossbow"],
    "axe": ["Axe"], "club": ["Club"], "hamm": ["Hammer"], "mace": ["Mace"],
    "pole": ["Polearm"], "scep": ["Scepter"], "staf": ["Staff"], "swor": ["Sword"],
    "wand": ["Wand"], "knif": ["Dagger"], "spea": ["Spear"], "h2h": ["Katar"],
    "orb": ["Orb"], "grim": ["Grimoire"],
    "tors": ["Body"], "helm": ["Helm"], "pelt": ["Helm"], "phlm": ["Helm"],
    "circ": ["Helm"],
    "shld": ["Shield"], "head": ["Shield"],
    # paladin-shield-only: resolved via base name, see _is_pala_shield
    "pala": [], "ashd": [],
}

_PALA_SHIELD_NAMES = (
    "targe", "rondache", "heraldic", "aerin", "crown shield", "akaran", "protector",
    "gilded", "royal shield", "vortex", "kurast", "zakarum", "kite of haste",
)

# Cube recipes that add 1-6 random sockets to a NORMAL-quality (white) item.
_SOCKET_RECIPES = {
    "weapon": "Ral + Amn + P.Amethyst + weapon",
    "Body": "Tal + Thul + P.Topaz + armor",
    "Helm": "Ral + Thul + P.Sapphire + helm",
    "Shield": "Tal + Amn + P.Ruby + shield",
}
_WEAPON_SLOTS = set(_TYPE_SLOTS["weap"])

_data = None
_bases = None


def _load():
    global _data
    if _data is None:
        try:
            with open(REPOSITORY_DIR / "runewords_full.json", encoding="utf-8") as f:
                _data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            _data = {}
    return _data


def _max_sockets(base_name):
    """The base's socket cap (Larzuk gives at most this many), or None."""
    global _bases
    if _bases is None:
        try:
            with open(REPOSITORY_DIR / "bases.json", encoding="utf-8") as f:
                _bases = {k.lower(): v for k, v in json.load(f).items()}
        except (FileNotFoundError, json.JSONDecodeError):
            _bases = {}
    entry = _bases.get((base_name or "").lower())
    return entry.get("maxsock") if isinstance(entry, dict) else None


def _is_pala_shield(base_name):
    b = (base_name or "").lower()
    return any(s in b for s in _PALA_SHIELD_NAMES)


def _fits(rw, slot, base_name):
    slots = set()
    for t in rw.get("types", []):
        slots.update(_TYPE_SLOTS.get(t, []))
        if t in ("pala", "ashd") and _is_pala_shield(base_name):
            slots.add("Shield")
    for t in rw.get("exclude", []):
        slots.difference_update(_TYPE_SLOTS.get(t, []))
    return slot in slots


def runewords_for(slot, base_name):
    """Runewords that can be made in this base, as {sockets: [names]}.

    Respects the base's socket cap — a Skull Cap (max 2) never lists
    3-socket runewords.
    """
    cap = _max_sockets(base_name)
    by_sockets = {}
    for name, rw in _load().items():
        if cap is not None and rw["sockets"] > cap:
            continue
        if _fits(rw, slot, base_name):
            by_sockets.setdefault(rw["sockets"], []).append(name)
    for names in by_sockets.values():
        names.sort()
    return by_sockets


def _sockets_of(item):
    for tmpl, params in item.get("affixes") or []:
        if tmpl == "Socketed (#)" and params and isinstance(params[0], int):
            return params[0]
    return 0


def base_advice(item, max_lines=8):
    """Overlay lines [(text, color)] for a Base-quality item, or None."""
    if (item or {}).get("quality") != "Base" or not item.get("slot"):
        return None
    slot, base = item["slot"], item.get("base") or ""
    by_sockets = runewords_for(slot, base)
    if not by_sockets:
        return None

    sockets = _sockets_of(item)
    cap = _max_sockets(base)
    lines = []
    accent, dim = "#ffd94d", "#9a9a9a"

    if sockets > 0:
        exact = by_sockets.get(sockets, [])
        cap_txt = ""
        if cap:
            cap_txt = " (base max)" if sockets >= cap else f" (base max: {cap})"
        if exact:
            lines.append((f"Runewords for {sockets} sockets{cap_txt}:", accent))
            for name in exact[:5]:
                rw = _load()[name]
                lines.append((f"• {name} — {' + '.join(rw['runes'])}", "#e8e8e8",
                              runeword_url(name)))
        else:
            lines.append((f"No runeword uses exactly {sockets} sockets in a {slot.lower()}{cap_txt}", dim))
    else:
        recipe = _SOCKET_RECIPES.get(slot) or (
            _SOCKET_RECIPES["weapon"] if slot in _WEAPON_SLOTS else None)
        cube_link = recipe_url("cube socket recipe")
        if cap:
            lines.append((f"No sockets — {base} takes up to {cap}. Larzuk: {cap} guaranteed, or cube:", accent))
            if recipe:
                lines.append((f"• {recipe} → random 1-{cap} sockets (plain white item, not superior)",
                              "#e8e8e8", cube_link))
        else:
            lines.append(("No sockets — Larzuk quest (max sockets) or cube:", accent))
            if recipe:
                lines.append((f"• {recipe} → random sockets (plain white item, not superior)",
                              "#e8e8e8", cube_link))

    others = {n: names for n, names in sorted(by_sockets.items()) if n != sockets}
    if others:
        parts = [f"{n}os: {', '.join(names[:3])}{'…' if len(names) > 3 else ''}"
                 for n, names in others.items()]
        text = "Also in this base — " + " · ".join(parts)
        lines.append((text, dim, recipe_url(f"runewords for {slot.lower()}")))

    return lines[:max_lines]
