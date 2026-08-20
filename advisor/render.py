"""Canonical affix-template rendering.

One implementation instead of the three divergent copies that used to
live in overlay/ranges/compare (compare left '[skill]' brackets raw,
overlay replaced only one placeholder form per param).
Numbers (and 'a→b' change strings) fill '#'; words fill '[...]'.
"""


def _numlike(p):
    if isinstance(p, bool):
        return False
    return isinstance(p, (int, float)) or (isinstance(p, str) and "→" in p)


def render_affix(tmpl, params):
    if not isinstance(params, (list, tuple)):
        params = [params]
    out = tmpl
    for p in params:
        if _numlike(p):
            i = out.find("#")
            if i >= 0:
                out = out[:i] + str(p) + out[i + 1:]
        else:
            i = out.find("[")
            if i >= 0:
                j = out.find("]", i)
                out = out[:i] + str(p) + out[j + 1:] if j >= 0 else out
    return out
