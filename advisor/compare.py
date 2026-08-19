"""Gear compare: what a hovered item gains and loses vs the equipped one.

Both items come from the game's own Shift-compare view (two tooltips on
screen), parsed by the normal OCR pipeline. The diff is per affix
template — numeric params are compared, presence-only affixes become
gained/lost lines.
"""
GREEN = "#4dff64"
RED = "#ff6a4d"
DIM = "#9a9a9a"


def _render(tmpl, value):
    return tmpl.replace("#", str(value), 1) if "#" in tmpl else tmpl


def _affix_map(item):
    """template -> numeric value (first param) or True for flat affixes."""
    out = {}
    for entry in item.get("affixes") or []:
        tmpl, params = entry[0], entry[1]
        val = True
        for p in params or []:
            if isinstance(p, (int, float)):
                val = p
                break
        # duplicated templates (e.g. two resist lines) — keep the sum
        if tmpl in out and isinstance(out[tmpl], (int, float)) \
                and isinstance(val, (int, float)):
            out[tmpl] += val
        else:
            out[tmpl] = val
    return out


def diff_items(new_item, old_item, max_lines=16):
    """[(text, color)] — gains first, then losses, then changes."""
    new_a, old_a = _affix_map(new_item), _affix_map(old_item)
    gains, losses, changes = [], [], []
    def mark(sign, text):
        text = text.replace("  ", " ").strip()
        return text if text.startswith(sign) else f"{sign} {text}"

    for tmpl, nv in new_a.items():
        if tmpl not in old_a:
            gains.append((mark("+", _render(tmpl, nv if nv is not True
                                            else "")), GREEN))
            continue
        ov = old_a[tmpl]
        if isinstance(nv, (int, float)) and isinstance(ov, (int, float)) \
                and nv != ov:
            arrow = "▲" if nv > ov else "▼"
            color = GREEN if nv > ov else RED
            changes.append((f"{arrow} {_render(tmpl, f'{ov}→{nv}')}", color))
    for tmpl, ov in old_a.items():
        if tmpl not in new_a:
            losses.append((mark("−", _render(tmpl, ov if ov is not True
                                             else "")), RED))

    lines = gains + changes + losses
    if not lines:
        lines = [("stat lines are identical", DIM)]
    if len(lines) > max_lines:
        lines = lines[:max_lines] + [(f"… {len(lines) - max_lines} more",
                                      DIM)]
    old_name = old_item.get("name") or old_item.get("base") or "equipped"
    header = [(f"vs equipped: {old_name}", "#e8e8e8")]
    return header + lines
