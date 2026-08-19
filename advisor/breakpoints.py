"""FCR/FHR breakpoint hints.

When the hovered item has Faster Cast Rate or Faster Hit Recovery and the
user set `my_class` in config.yaml, show that class's breakpoint ladder so
they can judge whether this piece helps reach the next frame step.
(IAS breakpoints depend on the weapon and skill — out of scope.)
"""

FCR = {
    "amazon": [7, 14, 22, 32, 48, 68, 99, 152],
    "assassin": [8, 16, 27, 42, 65, 102, 174],
    "barbarian": [9, 20, 37, 63, 105, 200],
    "druid": [4, 10, 19, 30, 46, 68, 99, 163],
    "necromancer": [9, 18, 30, 48, 75, 125],
    "paladin": [9, 18, 30, 48, 75, 125],
    "sorceress": [9, 20, 37, 63, 105, 200],
}
FHR = {
    "amazon": [6, 13, 20, 32, 52, 86, 174],
    "assassin": [7, 15, 27, 48, 86, 200],
    "barbarian": [7, 15, 27, 48, 86, 200],
    "druid": [3, 7, 13, 19, 29, 42, 63, 99, 174],
    "necromancer": [5, 10, 16, 26, 39, 56, 86, 152],
    "paladin": [7, 15, 27, 48, 86, 200],
    "sorceress": [5, 9, 14, 20, 30, 42, 60, 86, 142, 280],
}

_STATS = [
    ("+#% Faster Cast Rate", "FCR", FCR),
    ("+#% Faster Hit Recovery", "FHR", FHR),
]


def bp_lines(item, my_class):
    """[(text, color)] breakpoint ladders for this item's FCR/FHR, or None."""
    cls = (my_class or "").strip().lower()
    if not cls:
        return None
    lines = []
    affixes = dict((t, p) for t, p in (item or {}).get("affixes") or [])
    for tmpl, label, table in _STATS:
        params = affixes.get(tmpl)
        bps = table.get(cls)
        if not params or not bps:
            continue
        val = params[0] if params and isinstance(params[0], int) else "?"
        ladder = "/".join(str(b) for b in bps)
        lines.append((f"{label} breakpoints ({cls}): {ladder} — this piece: +{val}",
                      "#9ecfff"))
    return lines or None
