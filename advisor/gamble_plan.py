"""Buy planner — native port of the DBM site's search.worker (function qe).

Given the current RNG state at the gamble vendor, explores refresh / buy /
collect sequences (BFS with dedup) to find the shortest paths to target
items (uniques / sets / rares by default). "Buy" steps spend gold on cheap
junk purely to shift the RNG stream; each purchase consumes 2-5 rolls and
(in D2R) rerolls the bought slot.

See docs/dbm-gamble-algorithm.md for the full spec.
"""
from advisor.gamble_seed import (EXC_W, ELI_W, Q_RARE, Q_SET, Q_UNIQUE,
                                 buy_roll, generate_full, pack_grid, rng_next)

NODE_CAP = 2_000_000
PLAN_CAP = 30

# default targets: any set / rare / unique outcome
DEFAULT_SPECS = ({"name": -1, "tier": -1, "rarity": Q_RARE},
                 {"name": -1, "tier": -1, "rarity": Q_SET},
                 {"name": -1, "tier": -1, "rarity": Q_UNIQUE})

_RANK = {Q_UNIQUE: 3, Q_SET: 2, Q_RARE: 1}


def _score(quality, tier):
    return _RANK.get(quality, 0) * 10 + tier


def _cheapness(ctx, idx):
    it = ctx.items[idx]
    return it["level"] * 100 + it["invw"] * it["invh"]


def _upgrade_rolls(ctx, idx, g, exc_roll):
    """How many upgrade rolls buying idx would consume (site's Ge())."""
    it = ctx.items[idx]
    if it["uber"] < 0:
        return 0
    e = (g - ctx.items[it["uber"]]["level"]) * EXC_W + 1
    if e <= 0:
        return 0
    if exc_roll < e or it["ultra"] < 0 or (g - ctx.items[it["ultra"]]["level"]) * ELI_W + 1 <= 0:
        return 1
    return 2


class _Node:
    __slots__ = ("parent", "step_type", "step_slot", "step_cost", "lo", "hi",
                 "abs_pos", "depth", "buys", "collected", "qual", "win")

    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)


def _win_key(win):
    return tuple((s["idx"], s["tier"], s["quality"]) if s is not None else None
                 for s in win)


def _match(specs, ctx, idx, tier, quality):
    disp = ctx.display_idx(idx, tier)
    for sp in specs:
        if sp["name"] != -1 and sp["name"] != disp and sp["name"] != idx:
            continue
        if sp["tier"] != -1 and sp["tier"] != tier:
            continue
        if sp["rarity"] != -1 and sp["rarity"] != quality:
            continue
        return True
    return False


def plan_buys(lo, hi, abs_pos, win, ctx, specs=None, max_depth=5, max_buys=3,
              node_cap=NODE_CAP, soft_cap=None, reroll_bought=None,
              progress=None, stop=None):
    """Explore refresh/buy sequences from the current store state.

    win: the current 14 slots as [{'idx','tier','quality'} or None (bought,
    classic behavior)]. specs: targets [{'name': item idx or -1, 'tier':
    0/1/2/-1, 'rarity': 4/5/6/7/-1}]. soft_cap: once at least one route is
    found, stop expanding here (the fast path); only an empty-handed search
    runs on to node_cap. Returns {'plans': [...], 'explored', 'nodes',
    'capped', 'outcomes'} — plans sorted best-first, each with the step
    list (type R refresh / B shift-buy / C collect, slot, grid x/y).
    """
    specs = list(specs) if specs else list(DEFAULT_SPECS)
    if reroll_bought is None:
        reroll_bought = ctx.version["reroll_bought_slot"]
    node_cap = min(node_cap, NODE_CAP)
    win = [dict(s) if s is not None else None for s in win]

    nodes = [_Node(parent=-1, step_type=0, step_slot=-1, step_cost=0,
                   lo=lo, hi=hi, abs_pos=abs_pos, depth=0, buys=0,
                   collected=0, qual=0, win=win)]
    seen = {(abs_pos, 0, _win_key(win))}
    queue = [0]
    terminals = []
    explored = 0
    capped = False
    head = 0
    while head < len(queue):
        k = queue[head]
        head += 1
        v = nodes[k]
        explored += 1
        if progress and not (explored & 4095):
            progress(explored, len(nodes))
        if stop is not None and stop.is_set():
            break
        if v.collected >= 1 or v.depth >= max_depth:
            continue
        if len(nodes) >= node_cap or (soft_cap is not None and terminals
                                      and len(nodes) >= soft_cap):
            capped = True
            continue

        # peek the next rolls once — buy costs depend on them
        plo, phi = rng_next(v.lo, v.hi)          # base-flip roll
        plo, phi = rng_next(plo, phi)
        g = ctx.level - 5 + plo % 10
        g = 5 if g < 6 else 99 if g > 98 else g  # ilvl a buy would roll
        plo, phi = rng_next(plo, phi)
        exc_roll = plo % 10000                   # exceptional roll a buy would see

        # refresh child
        slots, nlo, nhi = generate_full(v.lo, v.hi, ctx)
        cost = _gen_cost(v.lo, v.hi, nlo, nhi)
        npos = v.abs_pos + cost
        key = (npos, v.collected, _win_key(slots))
        if key not in seen:
            seen.add(key)
            nodes.append(_Node(parent=k, step_type=1, step_slot=-1,
                               step_cost=cost, lo=nlo, hi=nhi, abs_pos=npos,
                               depth=v.depth + 1, buys=v.buys,
                               collected=v.collected, qual=v.qual, win=slots))
            queue.append(len(nodes) - 1)

        # collect children: buy a slot that matches a target
        for m, s in enumerate(v.win):
            if s is None:
                continue
            if not _match(specs, ctx, s["idx"], s["tier"], s["quality"]):
                continue
            if reroll_bought:
                new_slot, steps, blo, bhi = buy_roll(v.lo, v.hi, s["idx"], ctx)
                nwin = list(v.win)
                nwin[m] = new_slot
            else:
                steps, blo, bhi = 0, v.lo, v.hi
                nwin = list(v.win)
                nwin[m] = None
            tpos = v.abs_pos + steps
            key = (tpos, 1, _win_key(nwin))
            if key not in seen:
                seen.add(key)
                nodes.append(_Node(parent=k, step_type=3, step_slot=m,
                                   step_cost=steps, lo=blo, hi=bhi,
                                   abs_pos=tpos, depth=v.depth + 1,
                                   buys=v.buys, collected=1,
                                   qual=v.qual + _score(s["quality"], s["tier"]),
                                   win=nwin))
                terminals.append(len(nodes) - 1)
                queue.append(len(nodes) - 1)

        # shift-buy children: cheapest item per roll-consumption class 2..5
        if reroll_bought and v.buys < max_buys:
            best = [-1] * 6
            best_cost = [0] * 6
            for m, s in enumerate(v.win):
                if s is None:
                    continue
                p = s["idx"]
                if p == ctx.ring or p == ctx.amulet:
                    cls = 2
                else:
                    cls = 3 + _upgrade_rolls(ctx, p, g, exc_roll)
                if cls < 2 or cls > 5:
                    continue
                cheap = _cheapness(ctx, p)
                if best[cls] < 0 or cheap < best_cost[cls]:
                    best[cls] = m
                    best_cost[cls] = cheap
            for cls in range(2, 6):
                m = best[cls]
                if m < 0:
                    continue
                s = v.win[m]
                new_slot, steps, blo, bhi = buy_roll(v.lo, v.hi, s["idx"], ctx)
                nwin = list(v.win)
                nwin[m] = new_slot
                bpos = v.abs_pos + steps
                key = (bpos, v.collected, _win_key(nwin))
                if key not in seen:
                    seen.add(key)
                    nodes.append(_Node(parent=k, step_type=2, step_slot=m,
                                       step_cost=steps, lo=blo, hi=bhi,
                                       abs_pos=bpos, depth=v.depth + 1,
                                       buys=v.buys + 1, collected=v.collected,
                                       qual=v.qual, win=nwin))
                    queue.append(len(nodes) - 1)

    terminals.sort(key=lambda i: (-nodes[i].qual, nodes[i].depth,
                                  nodes[i].abs_pos))
    plans = []
    outcome_index = {}
    used = set()
    outcomes = 0
    for t in terminals:
        if t in used:
            continue
        v = nodes[t]
        par = nodes[v.parent]
        got = par.win[v.step_slot]
        disp = ctx.display_idx(got["idx"], got["tier"])
        okey = (disp, got["quality"], got["tier"])
        hit = outcome_index.get(okey)
        if hit is not None:
            if hit >= 0:
                plans[hit]["routes"] += 1
            continue
        outcomes += 1
        if len(plans) >= PLAN_CAP:
            outcome_index[okey] = -1
            continue
        chain = []
        i = t
        while i >= 0:
            chain.append(i)
            i = nodes[i].parent
        chain.reverse()
        steps = []
        for j in range(1, len(chain)):
            s = nodes[chain[j]]
            prev = nodes[chain[j - 1]]
            if s.step_type == 1:
                steps.append({"type": "R", "slot": -1, "idx": -1, "x": -1,
                              "y": -1, "cost": s.step_cost, "recv": None,
                              "win": s.win,
                              "lo": s.lo, "hi": s.hi, "abs": s.abs_pos})
            else:
                slot = s.step_slot
                bought = prev.win[slot]
                # site packs removed slots as item 0 (only classic has them)
                pos = pack_grid([w["idx"] if w is not None else 0
                                 for w in prev.win], ctx)[slot]
                steps.append({
                    "type": "C" if s.step_type == 3 else "B",
                    "slot": slot, "idx": bought["idx"],
                    "x": pos[0] if pos else -1, "y": pos[1] if pos else -1,
                    "cost": s.step_cost,
                    "recv": {"idx": ctx.display_idx(bought["idx"], bought["tier"]),
                             "quality": bought["quality"],
                             "tier": bought["tier"]},
                    "win": s.win,
                    "lo": s.lo, "hi": s.hi, "abs": s.abs_pos})
        outcome_index[okey] = len(plans)
        plans.append({"steps": steps, "recv_idx": disp,
                      "quality": got["quality"], "tier": got["tier"],
                      "base_idx": got["idx"], "end_abs": v.abs_pos,
                      "depth": v.depth, "buys": v.buys, "routes": 1})
        i = t
        while i >= 0:
            used.add(i)
            i = nodes[i].parent
    return {"plans": plans, "explored": explored, "nodes": len(nodes),
            "capped": capped, "outcomes": outcomes}


def _gen_cost(lo, hi, nlo, nhi):
    """Advances consumed between two states along the same stream.

    generate_full doesn't count its steps; recover the count by walking
    from (lo,hi) to (nlo,nhi) — bounded (14 slots * max 5 rolls)."""
    steps = 0
    while (lo, hi) != (nlo, nhi):
        lo, hi = rng_next(lo, hi)
        steps += 1
        if steps > 80:
            raise RuntimeError("state mismatch while counting draws")
    return steps
