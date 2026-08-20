"""Gear compare: what a hovered item gains and loses vs the equipped one.

Both items come from the game's own Shift-compare view (two tooltips on
screen), parsed by the normal OCR pipeline. The diff is per affix
template — numeric params are compared, presence-only affixes become
gained/lost lines.
"""
GREEN = "#4dff64"
RED = "#ff6a4d"
DIM = "#9a9a9a"


def _num(v):
    """Real number, never a bool (isinstance(True, int) is True!)."""
    return isinstance(v, (int, float)) and not isinstance(v, bool)


from advisor.render import render_affix as _render


def _affix_map(item):
    """(template, non-numeric params) -> (numeric_params_tuple, all_params).
    Keying on the non-numeric params too keeps '+2 to Fireball' and
    '+1 to Meteor' (same template, different skill) as separate rows —
    a plain template key silently dropped the second one and reported
    '+3 Fireball' vs '+3 Frozen Orb' as no change."""
    out = {}
    for entry in item.get("affixes") or []:
        tmpl, params = entry[0], entry[1]
        nums = tuple(p for p in params or [] if _num(p))
        words = tuple(p for p in params or [] if not _num(p))
        key = (tmpl, words)
        if key in out:
            prev_n, prev_p = out[key]
            if len(prev_n) == 1 and len(nums) == 1:
                out[key] = ((prev_n[0] + nums[0],), prev_p)  # summed dupes
        else:
            out[key] = (nums, list(params or []))
    return out


# stat lines worth diffing that the parser does NOT emit as affixes —
# pulled straight from the raw tooltip. (label, lower_is_better)
_STAT_LINES = [
    ("Defense", False),
    ("Required Strength", True),
    ("Required Dexterity", True),
    ("Required Level", True),
]


def _tooltip_stats(item):
    """{label: number} for defense/requirement lines in the raw tooltip."""
    import re
    out = {}
    for ln in item.get("tooltip") or []:
        for label, _low in _STAT_LINES:
            m = re.match(rf"\s*{label}\s*:?\s*(\d+)\s*$", ln, re.I)
            if m:
                out[label] = int(m.group(1))
    return out


def diff_items(new_item, old_item, max_lines=16, label=""):
    """[(text, color)] — gains first, then losses, then changes.
    label distinguishes sections when there are two equipped items
    ('vs equipped ring 1: …')."""
    new_a, old_a = _affix_map(new_item), _affix_map(old_item)
    gains, losses, changes = [], [], []
    def mark(sign, text):
        text = text.replace("  ", " ").strip()
        return text if text.startswith(sign) else f"{sign} {text}"

    for key, (nn, nparams) in new_a.items():
        tmpl = key[0]
        if key not in old_a:
            gains.append((mark("+", _render(tmpl, nparams)), GREEN))
            continue
        on = old_a[key][0]
        if nn == on:
            continue
        if nn and on and len(nn) == len(on):
            up = sum(nn) > sum(on)
            arrow, color = ("▲", GREEN) if up else ("▼", RED)
            if len(nn) == 1:
                idx = next((i for i, p in enumerate(nparams) if _num(p)), 0)
                shown = list(nparams)
                shown[idx] = f"{on[0]}→{nn[0]}"
                text = _render(tmpl, shown)
            else:  # ranges: full new value + the old one in brackets
                text = (_render(tmpl, list(nn))
                        + f"  (was {'-'.join(str(v) for v in on)})")
            changes.append((f"{arrow} {text}", color))
        else:
            # one side didn't read as numbers — show the new line neutrally
            changes.append((f"◈ {_render(tmpl, nparams)} — equipped value "
                            "unreadable", "#ffd94d"))
    for key, (_on, oparams) in old_a.items():
        if key not in new_a:
            losses.append((mark("−", _render(key[0], oparams)), RED))

    # Defense / requirements come from the raw tooltip — the single most
    # important armour number was previously not diffed at all
    ns, os_ = _tooltip_stats(new_item), _tooltip_stats(old_item)
    stats = []
    for label, lower_better in _STAT_LINES:
        a, b = os_.get(label), ns.get(label)
        if a is None or b is None or a == b:
            continue
        better = (b < a) if lower_better else (b > a)
        arrow, color = ("▲", GREEN) if better else ("▼", RED)
        stats.append((f"{arrow} {label}: {a}→{b}", color))

    lines = stats + gains + changes + losses
    if not lines:
        lines = [("stat lines are identical", DIM)]
    if len(lines) > max_lines:
        lines = lines[:max_lines] + [(f"… {len(lines) - max_lines} more",
                                      DIM)]
    old_name = old_item.get("name") or old_item.get("base") or "equipped"
    tag = f" {label}" if label else ""
    header = [(f"vs equipped{tag}: {old_name}", "#e8e8e8")]
    return header + lines
