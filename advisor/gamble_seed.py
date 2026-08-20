"""Native port of the DBM gamble seed engine (see docs/dbm-gamble-algorithm.md).

Implements: the D2 MWC RNG, gamble offer generation for a store seed,
store-grid packing, brute-force seed search (numpy-vectorized), and
future-offer prediction by RNG offset.

Data: repository/gamble_engine.json (extracted from the DBM site bundles).
"""
import json

import numpy as np

from d2rlootreader.cfg import REPOSITORY_DIR

MULT = 0x6AC690C5
MASK32 = 0xFFFFFFFF
INIT_CARRY = 666
WARMUP = 6
EXC_W = 90
ELI_W = 33

# Purchase quality roll: step % 100000 → <50 unique, <150 set, <10150 rare,
# else magic (eligibility per item via unique_lvl/set_lvl tables).
Q_MAGIC, Q_SET, Q_RARE, Q_UNIQUE = 4, 5, 6, 7
QUALITY_NAMES = {Q_MAGIC: "Magic", Q_SET: "SET", Q_RARE: "Rare", Q_UNIQUE: "UNIQUE"}
_Z_UNI, _Z_SET, _Z_RARE = 50, 100, 10000

_data = None


def _load():
    global _data
    if _data is None:
        with open(REPOSITORY_DIR / "gamble_engine.json", encoding="utf-8") as f:
            _data = json.load(f)
    return _data


def items():
    return _load()["items"]


def item_index(code_or_name):
    low = code_or_name.lower()
    for i, it in enumerate(items()):
        if it["code"] == low or it["name"].lower() == low:
            return i
    return -1


def platforms():
    return list(_load()["pool_orders"].keys())


def poolable_codes():
    """Codes that can actually appear in a gamble offer (any platform's
    pools + the forced ring/amulet + the circlet family) — the item table
    itself carries 659 entries including gems/quest junk that can never
    show up at the vendor."""
    d = _load()
    codes = {"rin", "amu", "ci0", "ci1"}
    for plat in d["pool_orders"].values():
        for pool in plat.values():
            codes.update(pool)
    return codes


def rng_next(lo, hi):
    s = lo * MULT + hi
    return s & MASK32, s >> 32


def advance_n(lo, hi, n):
    for _ in range(n):
        lo, hi = rng_next(lo, hi)
    return lo, hi


def versions():
    return _load()["versions"]


def game_seed_to_store(seed, version="d2r"):
    """The seed shown in game maps to the store seed after a few warm-up
    advances (3 for classic, 4 for D2R) — the site's 'game seed' input."""
    warm = _load()["versions"][version]["game_seed_warmup"]
    lo, _hi = advance_n(seed & MASK32, INIT_CARRY, warm)
    return lo


class Ctx:
    """Search/generation context for one (level, platform, pool) setup."""

    def __init__(self, level, platform="msvc", row_pool=None, version="d2r"):
        d = _load()
        self.items = d["items"]
        self.version = d["versions"][version]
        self.version_name = version
        if row_pool is None:
            row_pool = self.version["row_pool"]
        order = d["pool_orders"][platform]["row" if row_pool else "base"]
        idx = {it["code"]: i for i, it in enumerate(self.items)}
        self.pool = [idx[c] for c in order]
        self.level = max(1, min(99, int(level)))
        self.glvl = []
        for u in range(10):
            g = self.level - 5 + u
            g = 5 if g < 6 else 99 if g > 98 else g
            self.glvl.append(g)
        self.level_count = []
        for g in self.glvl:
            n = sum(1 for i in self.pool if self.items[i]["level"] <= g)
            self.level_count.append(n)
        self.pick_mask = [n - 1 if n and not (n & (n - 1)) else 0 for n in self.level_count]
        self.ring = idx["rin"]
        self.amulet = idx["amu"]
        self.ci0 = idx.get("ci0", -1)
        self.ci1 = idx.get("ci1", -1)
        self.ci2 = idx.get("ci2", -1)
        self.ci3 = idx.get("ci3", -1)
        self.uniq_lvl = d.get("unique_lvl") or [-1] * len(self.items)
        self.set_lvl = d.get("set_lvl") or [-1] * len(self.items)

    def display_idx(self, base_idx, tier):
        """Item shown for a base at upgrade tier 0/1/2 (the site's U())."""
        if base_idx < 0 or tier == 0:
            return base_idx
        it = self.items[base_idx]
        n = it["uber"] if tier == 1 else it["ultra"]
        return base_idx if n < 0 else n

    def _te(self, base, tiered):
        # elite circlet-family upgrades display as Coronet (site's te())
        if tiered in (self.ci2, self.ci3):
            return self.ci1
        return base

    def quality_of(self, roll, item_idx, ilvl):
        """Purchase quality from the trailing roll % 100000 (site's ue())."""
        if roll >= _Z_UNI + _Z_SET + _Z_RARE:
            return Q_MAGIC
        q = Q_RARE
        sl = self.set_lvl[item_idx]
        if roll < _Z_UNI + _Z_SET and 0 <= sl <= ilvl:
            q = Q_SET
        ul = self.uniq_lvl[item_idx]
        if roll < _Z_UNI and 0 <= ul <= ilvl:
            q = Q_UNIQUE
        return q


def generate_offer(seed, ctx, offset=0):
    """The 14 displayed items for a store seed at a given RNG offset.

    Offset 0 is the canonical offer (site seed semantics): generation
    starts directly from (seed, carry=666); the forced ring/amulet slots
    consume the first six advances — the same six the site's brute kernel
    skips via its warm-up jump."""
    lo, hi = advance_n(seed & MASK32, INIT_CARRY, offset)
    out, _, _ = generate_from_state(lo, hi, ctx)
    return out


def generate_full(lo, hi, ctx):
    """One offer with full purchase info per slot (the site's ye()):
    [{'idx': display base, 'tier': 0/1/2, 'quality': 4 magic/5 set/6 rare/
    7 unique}]. The quality tells what the item BECOMES when bought — that
    is the whole point of the simulator. Returns (slots, lo, hi)."""
    out = []
    for slot in range(14):
        lo, hi = rng_next(lo, hi)
        d = lo % 10
        g = ctx.glvl[d]
        n = ctx.level_count[d]
        if n < 1:
            u = 0
        else:
            lo, hi = rng_next(lo, hi)
            mask = ctx.pick_mask[d]
            u = (lo & mask) if mask else lo % n
        item = ctx.pool[u]
        if slot == 0:
            item = ctx.ring
        elif slot == 1:
            item = ctx.amulet
        tier = 0
        it = ctx.items[item]
        if it["uber"] >= 0:
            e = (g - ctx.items[it["uber"]]["level"]) * EXC_W + 1
            if e > 0:
                lo, hi = rng_next(lo, hi)
                if lo % 10000 < e:
                    tier = 1
                elif it["ultra"] >= 0:
                    q = (g - ctx.items[it["ultra"]]["level"]) * ELI_W + 1
                    if q > 0:
                        lo, hi = rng_next(lo, hi)
                        if lo % 10000 < q:
                            tier = 2
        tiered = item if tier == 0 else (it["uber"] if tier == 1 else it["ultra"])
        lo, hi = rng_next(lo, hi)
        qual = ctx.quality_of(lo % 100000, tiered, g)
        out.append({"idx": ctx._te(item, tiered), "tier": tier, "quality": qual})
    return out, lo, hi


def generate_from_state(lo, hi, ctx):
    """One offer from an RNG state; returns (items, lo, hi) with the state
    advanced past the generation — chaining calls yields successive
    refreshes exactly as refresh-spam does in game."""
    slots, lo, hi = generate_full(lo, hi, ctx)
    return [s["idx"] for s in slots], lo, hi


def buy_roll(lo, hi, item_idx, ctx):
    """Gambling (buying) item_idx: the rolls the purchase consumes and the
    item that refills the slot (D2R rerolls bought slots — the site's be()).
    Returns (slot dict, steps, lo, hi)."""
    steps = 0
    r = item_idx
    if item_idx not in (ctx.ring, ctx.amulet):
        lo, hi = rng_next(lo, hi)
        steps += 1
        if item_idx in (ctx.ci0, ctx.ci1):
            r = ctx.ci1 if (lo & 1) else ctx.ci0
    lo, hi = rng_next(lo, hi)
    steps += 1
    g = ctx.level - 5 + lo % 10
    g = 5 if g < 6 else 99 if g > 98 else g
    tier = 0
    it = ctx.items[r]
    if it["uber"] >= 0:
        e = (g - ctx.items[it["uber"]]["level"]) * EXC_W + 1
        if e > 0:
            lo, hi = rng_next(lo, hi)
            steps += 1
            if lo % 10000 < e:
                tier = 1
            elif it["ultra"] >= 0:
                q = (g - ctx.items[it["ultra"]]["level"]) * ELI_W + 1
                if q > 0:
                    lo, hi = rng_next(lo, hi)
                    steps += 1
                    if lo % 10000 < q:
                        tier = 2
    lo, hi = rng_next(lo, hi)
    steps += 1
    tiered = r if tier == 0 else (it["uber"] if tier == 1 else it["ultra"])
    qual = ctx.quality_of(lo % 100000, tiered, g)
    return {"idx": ctx._te(r, tiered), "tier": tier, "quality": qual}, steps, lo, hi


def vendor_fill(lo, hi, ctx, npc="gheed", difficulty=2):
    """Draws consumed filling the NPC's regular store inventory when the
    store opens (D2R "reassemble vendor"). This shifts every refresh after
    the first — omitting it desyncs predictions. difficulty: 0 normal,
    1 nightmare, 2 hell. Returns (steps, lo, hi)."""
    vf = _load()["vendor_fill"]
    row_pool = ctx.version["row_pool"]
    cap = vf["npc_caps"][vf["npc_index"][npc]]
    i = ctx.level + 5
    if difficulty == 0 and i > cap:
        i = cap
    m = difficulty != 0 and ctx.level > 25
    steps = 0

    def step():
        nonlocal lo, hi, steps
        lo, hi = rng_next(lo, hi)
        steps += 1
        return lo

    def rng_range(a, b):
        if b + 1 <= a:
            return a
        r = (b + 1 - a) & MASK32
        n = step()
        return a + ((n & (r - 1)) if (r & (r - 1)) == 0 else n % r)

    def only_ok(spec):
        o = spec.get("only")
        return o is None or o == ("row" if row_pool else "base")

    for v in vf["specs"][npc]:
        if not only_ok(v) or v["level"] > i:
            continue
        if i < 25:
            cnt = rng_range(v["nmin"], v["nmax"])
            for _ in range(cnt):
                step()
        if v.get("magic") and v["mlvl"] <= i:
            u = 1
            if i >= 25:
                u = rng_range(1, 2) + 1
            top = v["mmax"] + u
            c = v["mmin"]
            if c < top:
                c = rng_range(c, top - 1)
            if m:
                for _ in range(c):
                    step()
    for v in vf["extras"][npc]:
        if only_ok(v) and m:
            step()
    return steps, lo, hi


def count_steps(lo, hi, nlo, nhi, limit=100000):
    """Advances from (lo,hi) to (nlo,nhi) along the stream (small counts)."""
    steps = 0
    while (lo, hi) != (nlo, nhi):
        lo, hi = rng_next(lo, hi)
        steps += 1
        if steps > limit:
            raise RuntimeError("state mismatch while counting draws")
    return steps


def state_after_offer(seed, ctx, offset=0, npc="gheed", difficulty=2,
                      vendor_bump=None):
    """The store state right after the offer at `offset` is on screen —
    the starting point for the buy planner. Applies the vendor fill at
    store open (offset 0, D2R). Returns (lo, hi, abs_pos, slots)."""
    lo, hi = advance_n(seed & MASK32, INIT_CARRY, offset)
    slots, nlo, nhi = generate_full(lo, hi, ctx)
    steps = count_steps(lo, hi, nlo, nhi, limit=200)
    if vendor_bump is None:
        vendor_bump = (ctx.version["reassemble_vendor"] and offset == 0
                       and npc is not None)
    if vendor_bump:
        fill, nlo, nhi = vendor_fill(nlo, nhi, ctx, npc, difficulty)
        steps += fill
    return nlo, nhi, offset + steps, slots


def refresh_chain_full(seed, ctx, n, offset=0, npc="gheed", difficulty=2,
                       vendor_bump=None):
    """The next n offers (with quality/tier per slot) if you keep refreshing
    without buying. In D2R, opening the store also fills the NPC's regular
    inventory, consuming extra draws between the first window and the first
    refresh (the "vendor bump") — applied when offset==0 unless disabled.

    Buying items consumes extra rolls, which shifts later refreshes — resync
    with find_offsets after purchases and pass the found offset here.
    """
    lo, hi = advance_n(seed & MASK32, INIT_CARRY, offset)
    if vendor_bump is None:
        vendor_bump = (ctx.version["reassemble_vendor"] and offset == 0
                       and npc is not None)
    offers = []
    for k in range(n):
        slots, lo, hi = generate_full(lo, hi, ctx)
        pos = pack_grid([s["idx"] for s in slots], ctx)
        offers.append([dict(s, pos=p) for s, p in zip(slots, pos)])
        if k == 0 and vendor_bump:
            _steps, lo, hi = vendor_fill(lo, hi, ctx, npc, difficulty)
    return offers


def chain_from_state(lo, hi, ctx, n):
    """The next n windows generated straight from an RNG state (used after
    tracked buys, where the state is no longer on a window boundary).
    Returns (offers like refresh_chain_full, post_states) where
    post_states[k] = (lo, hi) AFTER window k was generated."""
    offers = []
    post = []
    for _ in range(n):
        slots, lo, hi = generate_full(lo, hi, ctx)
        pos = pack_grid([s["idx"] for s in slots], ctx)
        offers.append([dict(s, pos=p) for s, p in zip(slots, pos)])
        post.append((lo, hi))
    return offers, post


def chain_offsets(seed, ctx, n, offset=0, npc="gheed", difficulty=2,
                  vendor_bump=None):
    """The RNG offset at which each of the next n windows STARTS — lets the
    UI 'apply' a previewed refresh as the current state (the site's jump-
    to-node)."""
    lo, hi = advance_n(seed & MASK32, INIT_CARRY, offset)
    if vendor_bump is None:
        vendor_bump = (ctx.version["reassemble_vendor"] and offset == 0
                       and npc is not None)
    offs = []
    cur = offset
    for k in range(n):
        offs.append(cur)
        _slots, nlo, nhi = generate_full(lo, hi, ctx)
        cur += count_steps(lo, hi, nlo, nhi, limit=500)
        lo, hi = nlo, nhi
        if k == 0 and vendor_bump:
            steps, lo, hi = vendor_fill(lo, hi, ctx, npc, difficulty)
            cur += steps
    return offs


def refresh_chain(seed, ctx, n, offset=0, npc="gheed", difficulty=2,
                  vendor_bump=None):
    """refresh_chain_full reduced to [(item_idx, pos)] per offer."""
    full = refresh_chain_full(seed, ctx, n, offset, npc, difficulty, vendor_bump)
    return [[(s["idx"], s["pos"]) for s in offer] for offer in full]


def pack_grid(item_idxs, ctx):
    """Place items in the 10x10 store grid; returns [(x, y) or None]."""
    grid = [[0] * 10 for _ in range(10)]
    pos = []
    for idx in item_idxs:
        w, h = ctx.items[idx]["invw"], ctx.items[idx]["invh"]
        placed = None
        if h <= 1:
            for x in range(10 - w, -1, -1):
                for y in range(10):
                    if all(grid[y][xx] == 0 for xx in range(x, x + w)):
                        for xx in range(x, x + w):
                            grid[y][xx] = 1
                        placed = (x, y)
                        break
                if placed:
                    break
        else:
            for x in range(0, 10 - w + 1):
                for y in range(0, 10 - h + 1):
                    if all(grid[yy][xx] == 0 for yy in range(y, y + h)
                           for xx in range(x, x + w)):
                        for yy in range(y, y + h):
                            for xx in range(x, x + w):
                                grid[yy][xx] = 1
                        placed = (x, y)
                        break
                if placed:
                    break
        pos.append(placed)
    return pos


def offer_with_positions(seed, ctx, offset=0):
    idxs = generate_offer(seed, ctx, offset)
    return list(zip(idxs, pack_grid(idxs, ctx)))


def _canon(idx, equiv):
    """Some items share the IDENTICAL icon asset (claw pairs) — the screen
    cannot distinguish them, so comparisons collapse them to one id."""
    if equiv and idx in equiv:
        return equiv[idx]
    return idx


def verify_state(lo, hi, ctx, entries, equiv=None):
    """entries: [(item_idx, x, y)] where x/y may be None (position unknown).

    Positioned entries must sit at their grid cell; unpositioned ones must
    be present in the offer (as a multiset, beyond the positioned ones).
    equiv: {idx: canonical idx} for identical-icon items."""
    items_, _, _ = generate_from_state(lo, hi, ctx)
    placed = {p: i for i, p in zip(items_, pack_grid(items_, ctx)) if p is not None}
    have = {}
    for i in items_:
        c = _canon(i, equiv)
        have[c] = have.get(c, 0) + 1
    need = {}
    for idx, x, y in entries:
        c = _canon(idx, equiv)
        if x is None or y is None:
            need[c] = need.get(c, 0) + 1
        else:
            if _canon(placed.get((x, y)), equiv) != c:
                return False
            have[c] = have.get(c, 0) - 1
    for c, cnt in need.items():
        if have.get(c, 0) < cnt:
            return False
    return True


def verify_seed(seed, ctx, entries, offset=0, equiv=None):
    """entries: [(item_idx, x, y)], x/y may be None. True if the offer at
    the given offset matches all of them."""
    lo, hi = advance_n(seed & MASK32, INIT_CARRY, offset)
    return verify_state(lo, hi, ctx, entries, equiv=equiv)


def _norm_entries(entries):
    out = []
    for idx, x, y in entries:
        x = None if x is None else int(x)
        y = None if y is None else int(y)
        if (x is None) != (y is None):
            raise ValueError("an entry needs either both x and y or neither")
        out.append((int(idx), x, y))
    return out


def _obs_counts(entries):
    counts = {}
    for idx, _x, _y in entries:
        counts[idx] = counts.get(idx, 0) + 1
    return counts


# ---------------------------------------------------------------------------
# Vectorized brute force

def _v_advance(lo, hi, mask=None):
    s = lo.astype(np.uint64) * np.uint64(MULT) + hi
    nlo = (s & np.uint64(MASK32))
    nhi = (s >> np.uint64(32))
    if mask is None:
        return nlo, nhi
    return np.where(mask, nlo, lo), np.where(mask, nhi, hi)


def _v_advance_ip(lo, hi, s):
    """Unmasked advance IN PLACE (lo/hi owned, s = uint64 scratch of the
    same length) — the hot path is memory-bound, allocations cost real %."""
    np.multiply(lo, np.uint64(MULT), out=s)
    s += hi
    np.bitwise_and(s, np.uint64(MASK32), out=lo)
    np.right_shift(s, np.uint64(32), out=hi)


def _tables(ctx, equiv=None):
    items_arr = _load()["items"]
    canon = np.arange(len(items_arr), dtype=np.int64)
    for k, v in (equiv or {}).items():
        canon[int(k)] = int(v)
    return {
        "invh": np.array([it["invh"] for it in items_arr], dtype=np.int64),
        "lvl": np.array([it["level"] for it in items_arr], dtype=np.int64),
        "uber": np.array([it["uber"] for it in items_arr], dtype=np.int64),
        "ultra": np.array([it["ultra"] for it in items_arr], dtype=np.int64),
        "pool": np.array(ctx.pool, dtype=np.int64),
        "glvl": np.array(ctx.glvl, dtype=np.uint64),
        "lcount": np.array(ctx.level_count, dtype=np.uint64),
        "pmask": np.array(ctx.pick_mask, dtype=np.uint64),
        "canon": canon,
    }


def _scan_states(ctx, lo, hi, t, first_tall, obs_lookup):
    """Generate up to 14 slots for a batch of RNG states with early pruning
    AND lane compaction: once a filter kills most lanes, the dead ones are
    physically dropped, so later slots cost almost nothing — the vector
    equivalent of the site's per-seed early exit (~20x fewer ops/seed).

    first_tall: canonical item id that must be the first tall item drawn,
    or None. obs_lookup: bool array over canonical ids (complete-offer
    mode). Returns (gen(14, m), surviving original lane indices)."""
    n = lo.shape[0]
    idx = np.arange(n, dtype=np.int64)
    gen = np.zeros((14, n), dtype=np.int64)
    lo = lo.astype(np.uint64, copy=True)  # owned: advances run in place
    hi = hi.astype(np.uint64, copy=True)
    scratch = np.empty(n, dtype=np.uint64)
    # slots 0/1 are forced Ring/Amulet: no pick, no possible upgrade — just
    # three raw advances each (d, pick, trailing), full width, unmasked
    for _ in range(6):
        _v_advance_ip(lo, hi, scratch)
    gen[0] = ctx.ring
    gen[1] = ctx.amulet
    seen_tall = np.zeros(n, dtype=bool)
    # lenient filter constants for the circlet family: a picked Circlet/
    # Coronet may DISPLAY as Coronet after an upgrade roll, so at the
    # cheap pre-filter stage a ci pick passes if EITHER form would
    ci1c = int(t["canon"][ctx.ci1]) if ctx.ci1 >= 0 else -1
    ci1_first_ok = first_tall is not None and ci1c == first_tall
    ci1_obs_ok = obs_lookup is not None and ci1c >= 0 and bool(obs_lookup[ci1c])
    for slot in range(2, 14):
        # ---- cheap phase (full width): two advances + pick + filter.
        # Rejected lanes are dropped BEFORE the upgrade-roll math — their
        # RNG state no longer matters, and they are the vast majority.
        if scratch.shape[0] != lo.shape[0]:
            scratch = np.empty(lo.shape[0], dtype=np.uint64)
        _v_advance_ip(lo, hi, scratch)
        d = (lo % np.uint64(10)).astype(np.int64)
        _v_advance_ip(lo, hi, scratch)
        msk = t["pmask"][d]
        i = np.where(msk != 0, lo & msk, lo % np.maximum(t["lcount"][d], 1))
        item = t["pool"][i.astype(np.int64)]
        ci = t["canon"][item]
        is_ci = ((item == ctx.ci0) | (item == ctx.ci1)) if ctx.ci0 >= 0 \
            else np.zeros(item.shape[0], dtype=bool)
        ok = np.ones(item.shape[0], dtype=bool)
        first_here = None
        if first_tall is not None:
            tall = t["invh"][item] > 1
            first_here = tall & ~seen_tall
            passes = ci == first_tall
            if ci1_first_ok:
                passes |= is_ci
            ok &= ~first_here | passes
        if obs_lookup is not None:
            passes = obs_lookup[ci]
            if ci1_obs_ok:
                passes |= is_ci
            ok &= passes
        m = int(ok.sum())
        if m == 0:
            return gen[:, :0], idx[:0]
        if m < ok.shape[0]:
            keep = np.nonzero(ok)[0]
            lo, hi = lo[keep].copy(), hi[keep].copy()
            gen = gen[:, keep]
            idx = idx[keep]
            seen_tall = seen_tall[keep]
            d, item, ci, is_ci = d[keep], item[keep], ci[keep], is_ci[keep]
            if first_here is not None:
                first_here = first_here[keep]
            if first_tall is not None:
                tall = tall[keep]

        # ---- expensive phase (survivors only): upgrade rolls + exact
        # display filter + trailing advance
        g = t["glvl"][d]
        ub = t["uber"][item]
        has_exc = ub >= 0
        e = np.where(has_exc, (g.astype(np.int64) - np.where(has_exc, t["lvl"][np.maximum(ub, 0)], 0)) * EXC_W + 1, 0)
        roll_exc = e > 0
        lo, hi = _v_advance(lo, hi, roll_exc)
        upg = roll_exc & ((lo % np.uint64(10000)).astype(np.int64) < e)
        ul = t["ultra"][item]
        q = np.where(ul >= 0, (g.astype(np.int64) - np.where(ul >= 0, t["lvl"][np.maximum(ul, 0)], 0)) * ELI_W + 1, 0)
        roll_eli = roll_exc & ~upg & (ul >= 0) & (q > 0)
        lo, hi = _v_advance(lo, hi, roll_eli)
        upg = upg | (roll_eli & ((lo % np.uint64(10000)).astype(np.int64) < q))
        if ctx.ci0 >= 0:
            item = np.where(upg & is_ci, ctx.ci1, item)
        gen[slot] = item
        # exact recheck only where the display could have changed (ci picks)
        if is_ci.any():
            ci = t["canon"][item]
            ok = np.ones(item.shape[0], dtype=bool)
            if first_tall is not None:
                ok &= ~first_here | (ci == first_tall)
            if obs_lookup is not None:
                ok &= obs_lookup[ci]
            ok |= ~is_ci
            m = int(ok.sum())
            if m == 0:
                return gen[:, :0], idx[:0]
            if m < ok.shape[0]:
                keep = np.nonzero(ok)[0]
                lo, hi = lo[keep].copy(), hi[keep].copy()
                gen = gen[:, keep]
                idx = idx[keep]
                seen_tall = seen_tall[keep]
                if first_tall is not None:
                    tall = tall[keep]
        if first_tall is not None:
            seen_tall |= tall
        if scratch.shape[0] != lo.shape[0]:
            scratch = np.empty(lo.shape[0], dtype=np.uint64)
        _v_advance_ip(lo, hi, scratch)
    return gen, idx


def _prepare_filters(entries, complete, equiv=None):
    """Shared validation for search_range/find_offsets. Returns
    (entries, first_tall_canon, obs_lookup, obs_counts, complete) — the
    filter values are canonicalized for identical-icon equivalence."""
    entries = _norm_entries(entries)
    if not entries:
        raise ValueError("no items entered")
    first_tall = next((idx for idx, x, y in entries if x == 0 and y == 0), None)
    if first_tall is not None:
        first_tall = _canon(first_tall, equiv)
    if complete is None:
        complete = len(entries) >= 14
    if first_tall is None and not complete:
        raise ValueError("need either the item at grid (0,0) with its position, "
                         "or the complete 14-item offer (positions optional)")
    obs_lookup = None
    if complete:
        obs_lookup = np.zeros(len(_load()["items"]), dtype=bool)
        for idx, _x, _y in entries:
            obs_lookup[_canon(idx, equiv)] = True
    counts = {}
    for idx, _x, _y in entries:
        c = _canon(idx, equiv)
        counts[c] = counts.get(c, 0) + 1
    return entries, first_tall, obs_lookup, counts, complete


def search_range(ctx, entries, start, end, progress=None, chunk=1 << 22,
                 complete=None, equiv=None):
    """Brute-force seeds in [start, end); returns list of matches.

    entries: [(item_idx, x, y)] observed; x/y may be None. Needs either the
    (0,0) item positioned, or all 14 items listed (complete-offer mode —
    the auto-fill path, positions not required). equiv maps identical-icon
    item ids to one canonical id (the screen can't tell them apart).
    """
    entries, first_tall, obs_lookup, obs_counts, complete = \
        _prepare_filters(entries, complete, equiv)
    t = _tables(ctx, equiv)

    matches = []
    pos = start
    while pos < end:
        n = min(chunk, end - pos)
        seeds = np.arange(pos, pos + n, dtype=np.uint64)
        lo = seeds & np.uint64(MASK32)
        hi = np.full(n, INIT_CARRY, dtype=np.uint64)
        gen, surv = _scan_states(ctx, lo, hi, t, first_tall, obs_lookup)
        if surv.size:
            # observed multiset must be contained in the generated 14
            ok = np.ones(surv.size, dtype=bool)
            cgen = t["canon"][gen]
            for idx, cnt in obs_counts.items():
                ok &= (cgen == idx).sum(axis=0) >= cnt
            for s in seeds[surv[ok]]:
                if verify_seed(int(s), ctx, entries, equiv=equiv):
                    matches.append(int(s))
        pos += n
        if progress:
            if progress(pos - start, end - start) is False:
                break
    return matches


def find_offsets(seed, ctx, entries, max_offset=1 << 20, progress=None,
                 chunk=1 << 17, complete=None, equiv=None):
    """Resync after buying: buys consume extra RNG rolls, so later offers no
    longer line up with refresh_chain. Scan offsets k = 0..max_offset for
    states advance^k(seed, 666) whose offer matches the observed entries.
    Offset 0 is the original offer. Returns the matching offsets."""
    entries, first_tall, obs_lookup, obs_counts, complete = \
        _prepare_filters(entries, complete, equiv)
    t = _tables(ctx, equiv)
    l, h = seed & MASK32, INIT_CARRY
    out = []
    k0 = 0
    while k0 < max_offset:
        n = min(chunk, max_offset - k0)
        lo = np.empty(n, dtype=np.uint64)
        hi = np.empty(n, dtype=np.uint64)
        for j in range(n):
            lo[j] = l
            hi[j] = h
            l, h = rng_next(l, h)
        gen, surv = _scan_states(ctx, lo, hi, t, first_tall, obs_lookup)
        if surv.size:
            ok = np.ones(surv.size, dtype=bool)
            cgen = t["canon"][gen]
            for idx, cnt in obs_counts.items():
                ok &= (cgen == idx).sum(axis=0) >= cnt
            for j in surv[ok]:
                if verify_state(int(lo[j]), int(hi[j]), ctx, entries,
                                equiv=equiv):
                    out.append(k0 + int(j))
        k0 += n
        if progress:
            if progress(k0, max_offset) is False:
                break
    return out


# ---------------------------------------------------------------------------
# Full-space search with worker processes

def _search_worker(args):
    level, platform, row_pool, entries, start, end, complete, equiv = args
    ctx = Ctx(level, platform, row_pool)
    return search_range(ctx, [tuple(e) for e in entries], start, end,
                        complete=complete, equiv=equiv)


_POOL = None  # (executor, workers) — kept alive between searches
_POOL_LOCK = None  # created lazily (threading import kept out of workers)


def _pool_lock():
    global _POOL_LOCK
    if _POOL_LOCK is None:
        import threading
        _POOL_LOCK = threading.Lock()
    return _POOL_LOCK


def _norm_workers(workers):
    import os
    # workers are light (numpy only — main.py is a thin launcher), but the
    # game needs RAM/cores too: cap the fleet
    return workers or max(1, min((os.cpu_count() or 4) - 2, 10))


def _get_pool(workers):
    # locked: the UI prewarm thread and a starting search used to race
    # here and one ProcessPoolExecutor leaked with all its processes
    global _POOL
    import concurrent.futures as cf
    with _pool_lock():
        return _get_pool_locked(workers, cf)


def _get_pool_locked(workers, cf):
    global _POOL
    if _POOL is not None:
        ex, w = _POOL
        if w == workers and not getattr(ex, "_broken", False):
            return ex
        try:
            ex.shutdown(wait=False, cancel_futures=True)
        except Exception:
            pass
        _POOL = None
    ex = cf.ProcessPoolExecutor(max_workers=workers)
    _POOL = (ex, workers)
    return ex


def _drop_pool():
    global _POOL
    with _pool_lock():
        if _POOL is not None:
            try:
                _POOL[0].shutdown(wait=False, cancel_futures=True)
            except Exception:
                pass
            _POOL = None


def node_available():
    import shutil
    return shutil.which("node") is not None


def _search_full_node(level, platform, entries, on_progress=None, stop=None,
                      row_pool=False, on_match=None, equiv=None,
                      on_engine=None):
    """Fast path: the DBM site's OWN brute kernel running in Node
    worker_threads (advisor/brute_host.js) — website-class speed. Requires
    fully positioned entries. Twin-icon entries are dropped from the node
    payload (its kernel matches exact items) and every reported seed is
    re-verified by our engine with equivalence on."""
    import json as _json
    import subprocess
    import tempfile
    from pathlib import Path
    entries = _norm_entries(entries)
    twins = set()
    groups = {}
    for k, v in (equiv or {}).items():
        twins.add(int(k))
        twins.add(int(v))
        groups.setdefault(int(v), {int(v)}).add(int(k))
    # the node kernel needs positioned, exact-item entries; the rest of the
    # observation still constrains via our python verify on its matches
    node_entries = [e for e in entries
                    if e[1] is not None and e[0] not in twins]
    zero = next((e for e in entries
                 if e[1] == 0 and e[2] == 0), None)
    if zero is None:
        raise ValueError("needs the (0,0) item positioned")
    if zero[0] in twins:
        # identical-icon claw at (0,0): the kernel matches exact items, so
        # run it once per twin variant (still seconds each)
        canon = equiv.get(zero[0], zero[0])
        variants = sorted(groups.get(canon, {zero[0]}))
        entry_sets = [node_entries + [(v, 0, 0)] for v in variants]
    else:
        entry_sets = [node_entries + ([zero] if zero not in node_entries
                                      else [])]
    here = Path(__file__).resolve().parent
    worker = here.parent / "tools" / "dbm_validation" / "brute.worker.js"
    if not worker.exists():
        # without this check a dead node drained an empty stdout and the
        # search returned [] as a legitimate "0 candidates"
        raise ValueError("brute.worker.js not downloaded yet")
    ctx = Ctx(level, platform, row_pool)
    matches = []
    total = 1 << 32
    n_runs = len(entry_sets)
    creation = subprocess.CREATE_NO_WINDOW if hasattr(
        subprocess, "CREATE_NO_WINDOW") else 0
    import shutil as _shutil
    import threading as _th
    node_exe = _shutil.which("node") or "node"
    from advisor.paths import STATE_DIR
    err_path = STATE_DIR / "debug" / "node_search.log"
    err_path.parent.mkdir(exist_ok=True)
    hello_sent = [False]

    def run_one(run_i, nentries):
        job = {"params": {"level": int(level), "rowPool": bool(row_pool),
                          "poolOrder": platform,
                          "entries": [{"idx": i, "x": x, "y": y}
                                      for i, x, y in nentries]},
               "chunkBits": 24}
        jf = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False,
                                         encoding="utf-8")
        jf.write(_json.dumps(job))
        jf.close()
        err_f = open(err_path, "a", encoding="utf-8", errors="replace")
        proc = subprocess.Popen(
            [node_exe, str(here / "brute_host.js"), jf.name],
            stdout=subprocess.PIPE, stderr=err_f, text=True,
            creationflags=creation)
        try:
            if stop is not None:
                def _watch():
                    while proc.poll() is None:
                        if stop.wait(0.2):
                            try:
                                proc.kill()
                            except Exception:
                                pass
                            return
                _th.Thread(target=_watch, daemon=True).start()
            saw_done = False
            for line in proc.stdout:
                try:
                    m = _json.loads(line)
                except ValueError:
                    continue
                if m.get("type") == "progress" and on_progress:
                    on_progress((run_i * total + int(m["done"])) // n_runs,
                                total)
                elif m.get("type") == "hello" and on_engine:
                    if not hello_sent[0]:
                        hello_sent[0] = True
                        extra = (f", {n_runs} twin variants"
                                 if n_runs > 1 else "")
                        on_engine("node", f"site kernel, "
                                          f"{m.get('threads')} threads{extra}")
                elif m.get("type") == "error":
                    raise RuntimeError(f"node worker: {m.get('error')}")
                elif m.get("type") == "match":
                    s = int(m["seed"]) & MASK32
                    # exact verify vs OUR bit-exact engine, twins included
                    if verify_seed(s, ctx, entries, equiv=equiv) \
                            and s not in matches:
                        matches.append(s)
                        if on_match:
                            on_match(s)
                elif m.get("type") == "done":
                    saw_done = True
                    break
            if not saw_done and not (stop is not None and stop.is_set()):
                rc = proc.poll()
                raise RuntimeError(
                    f"node exited (rc={rc}) before finishing — "
                    "see debug\\node_search.log")
        finally:
            try:
                proc.kill()
            except Exception:
                pass
            try:
                err_f.close()
            except Exception:
                pass
            try:
                Path(jf.name).unlink()
            except OSError:
                pass

    try:
        err_path.write_text("", encoding="utf-8")
    except OSError:
        pass
    for run_i, nentries in enumerate(entry_sets):
        if stop is not None and stop.is_set():
            break
        run_one(run_i, nentries)
    return sorted(matches)


def prewarm_pool(workers=None):
    """Spawn the worker processes ahead of time (a few seconds on Windows)
    so Find seed starts instantly. Safe to call repeatedly."""
    workers = _norm_workers(workers)
    ex = _get_pool(workers)
    for _ in range(workers):
        ex.submit(int, 0)
    return workers


def search_full(level, platform, entries, on_progress=None, stop=None,
                row_pool=False, workers=None, slice_bits=22, complete=None,
                on_match=None, equiv=None, on_engine=None):
    """Search all 2^32 seeds using a process pool.

    on_progress(done_seeds, total_seeds) after each finished slice (22-bit
    slices → the first update lands within seconds, then continuously);
    on_match(seed) fires LIVE as candidates surface, before the search ends;
    stop: threading.Event to cancel. Returns sorted list of matches.
    """
    import concurrent.futures as cf
    # fail fast on bad entries before spawning workers
    entries, _ft, _ol, _oc, complete = _prepare_filters(entries, complete, equiv)
    if node_available():
        try:
            # website-class fast path: the site's own kernel under node
            return _search_full_node(level, platform, entries,
                                     on_progress=on_progress, stop=stop,
                                     row_pool=row_pool, on_match=on_match,
                                     equiv=equiv, on_engine=on_engine)
        except ValueError as e:
            if on_engine:
                on_engine("python", f"node ineligible: {e}")
        except Exception as e:
            if on_engine:
                on_engine("python", f"node failed: {type(e).__name__}: {e} "
                                    "(see debug\\node_search.log)")
    elif on_engine:
        on_engine("python", "node.exe not found — install Node.js for "
                            "website-speed searches")
    equiv = {int(k): int(v) for k, v in (equiv or {}).items()} or None
    total = 1 << 32
    step = 1 << slice_bits
    jobs = [(level, platform, row_pool, [list(e) for e in entries], s,
             min(s + step, total), complete, equiv)
            for s in range(0, total, step)]
    matches = []
    done = 0
    workers = _norm_workers(workers)
    # Windowed submission + stop polling on a REUSED pre-warmed pool. On
    # Stop the worker PROCESSES are terminated outright — letting running
    # slices finish (or the pool's exit handler join them) left
    # "stopping…" hanging for minutes.
    ex = _get_pool(workers)
    job_iter = iter(jobs)
    inflight = set()
    try:
        while True:
            if stop is not None and stop.is_set():
                break
            while len(inflight) < workers * 3:
                j = next(job_iter, None)
                if j is None:
                    break
                inflight.add(ex.submit(_search_worker, j))
            if not inflight:
                break
            finished, inflight = cf.wait(inflight, timeout=0.3,
                                         return_when=cf.FIRST_COMPLETED)
            for fut in finished:
                try:
                    got = fut.result()
                except Exception:
                    got = []
                matches += got
                if on_match:
                    for s in got:
                        on_match(s)
                done += step
            if finished and on_progress:
                on_progress(min(done, total), total)
    finally:
        if stop is not None and stop.is_set():
            try:  # hard stop: kill workers, don't wait out their slices
                for p in list(getattr(ex, "_processes", {}).values()):
                    p.terminate()
            except Exception:
                pass
            _drop_pool()  # the pool is broken after the kill
        # normal completion keeps the warm pool for the next search
    return sorted(matches)
