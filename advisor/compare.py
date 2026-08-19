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


def _render(tmpl, params):
    """Fill EVERY # with successive params ('Adds #-# ...' -> 'Adds 1-3')."""
    if not isinstance(params, (list, tuple)):
        params = [params]
    out = tmpl
    for p in params:
        if "#" not in out:
            break
        out = out.replace("#", str(p), 1)
    return out


def _affix_map(item):
    """template -> (numeric_params_tuple, all_params). The numeric tuple
    is what gets compared; the full list is what gets rendered."""
    out = {}
    for entry in item.get("affixes") or []:
        tmpl, params = entry[0], entry[1]
        nums = tuple(p for p in params or [] if _num(p))
        if tmpl in out:
            prev_n, prev_p = out[tmpl]
            if len(prev_n) == 1 and len(nums) == 1:
                out[tmpl] = ((prev_n[0] + nums[0],), prev_p)  # summed dupes
        else:
            out[tmpl] = (nums, list(params or []))
    return out


def diff_items(new_item, old_item, max_lines=16):
    """[(text, color)] — gains first, then losses, then changes."""
    new_a, old_a = _affix_map(new_item), _affix_map(old_item)
    gains, losses, changes = [], [], []
    def mark(sign, text):
        text = text.replace("  ", " ").strip()
        return text if text.startswith(sign) else f"{sign} {text}"

    for tmpl, (nn, nparams) in new_a.items():
        if tmpl not in old_a:
            gains.append((mark("+", _render(tmpl, nparams)), GREEN))
            continue
        on = old_a[tmpl][0]
        if nn == on:
            continue
        if nn and on and len(nn) == len(on):
            up = sum(nn) > sum(on)
            arrow, color = ("▲", GREEN) if up else ("▼", RED)
            if len(nn) == 1:
                text = _render(tmpl, [f"{on[0]}→{nn[0]}"])
            else:  # ranges: full new value + the old one in brackets
                text = (_render(tmpl, list(nn))
                        + f"  (was {'-'.join(str(v) for v in on)})")
            changes.append((f"{arrow} {text}", color))
        else:
            # one side didn't read as numbers — show the new line neutrally
            changes.append((f"◈ {_render(tmpl, nparams)} — equipped value "
                            "unreadable", "#ffd94d"))
    for tmpl, (_on, oparams) in old_a.items():
        if tmpl not in new_a:
            losses.append((mark("−", _render(tmpl, oparams)), RED))

    lines = gains + changes + losses
    if not lines:
        lines = [("stat lines are identical", DIM)]
    if len(lines) > max_lines:
        lines = lines[:max_lines] + [(f"… {len(lines) - max_lines} more",
                                      DIM)]
    old_name = old_item.get("name") or old_item.get("base") or "equipped"
    header = [(f"vs equipped: {old_name}", "#e8e8e8")]
    return header + lines
