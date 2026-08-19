# DBM Gamble Seed Algorithm — reverse-engineered spec

Source: `gambling.diablo.deadlybossmods.com` client bundles
(`brute.worker-CNNbTWOV.js`, `search.worker-CJXuxRm1.js`), extracted 2026-08-06.
Data tables live in `d2rlootreader/repository/gamble_engine.json`.

## RNG — Diablo II multiply-with-carry (MWC)

State: 32-bit `lo`, 32-bit `carry`. One advance:

```
state64 = lo * 0x6AC690C5 + carry
lo'     = state64 & 0xFFFFFFFF
carry'  = state64 >> 32
```

(The JS computes this with 16-bit halves: o=37061, c=27334, where
0x6AC690C5 = o + (c << 16).)

The MWC state maps to the multiplicative group modulo
`be = 0x6AC690C5 * 2^32 - 1`; k advances multiply the combined state
`lo + carry*2^32` by `0x6AC690C5^k mod be`. The bundle precomputes the
6-step jump (`0x6AC690C5^6 mod be`) to iterate candidate seeds cheaply.

## Seed semantics

A gamble **store seed** is a 32-bit value `S`. The offer generated for
seed `S` starts from RNG state `advance^6(lo=S, carry=666)` — i.e. carry
is initialized to 666 and the RNG is warmed up 6 times. The site's
"offset" scan generates from `advance^k(S, 666)` for k = 0..maxOffset;
offset 6 reproduces the original offer, larger offsets model reforges /
future rolls.

## Offer generation (14 items)

Inputs: character level `clvl` (clamped 1..99), platform pool order
(msvc / musl / freebsd / stable / gcc / msvc-std / reverse; each has a
`base` pool of 125 codes and a `row` pool of 121), item table
(code, qlvl, invw, invh, uber-index, ultra-index).

Precompute `glvlTab[u] = clamp(clvl - 5 + u)` for u = 0..9, where values
< 6 clamp to 5 and > 98 clamp to 99. `levelCount[g]` = how many pool
items have qlvl <= g (pools are level-ordered, so the qualifying items
are exactly the first `levelCount` entries). If `levelCount` is a power
of two the pick uses a bit-mask, otherwise a modulo.

For each of the 14 slots (slot 0 and 1 are forced Ring and Amulet — the
RNG is still consumed exactly the same way):

1. advance; `d = lo % 10`; gamble level `g = glvlTab[d]`
2. advance; `i = lo & mask(d)` if levelCount(d) is a power of two else
   `lo % levelCount(d)`; item = pool[i] (overridden to ring/amulet for
   slots 0/1; ring and amulet have no uber version so step 3 is a no-op
   for them)
3. exceptional/elite upgrade: if the item has an uber (exceptional)
   version `F`: chance `E = (g - qlvl(F)) * 90 + 1` per 10000; if E > 0:
   advance; upgraded if `lo % 10000 < E`; otherwise if it has an ultra
   (elite) version `D`: chance `Q = (g - qlvl(D)) * 33 + 1` per 10000;
   if Q > 0: advance; upgraded if `lo % 10000 < Q`.
   Display: an upgraded Circlet/Coronet displays as Coronet (ci1);
   other items keep their base display.
4. advance (trailing roll).

## Store grid packing

The 14 items are packed into the vendor's 10x10 grid in generation
order:

- height <= 1 (flat) items: scan columns right-to-left
  (x = 10-invw .. 0), rows top-to-bottom; place at the first fit.
- taller items: scan columns left-to-right (x = 0 .. 10-invw), for each
  column rows top-to-bottom (y = 0 .. 10-invh); place at first fit.

Position key = x*16 + y. Items that don't fit are invisible.

## Seed search

The user enters 1..14 observed items **with their grid positions**; the
top-left (0,0) item must be included and must be 2+ cells tall (flat
items pack to the right, so (0,0) is always a tall item). Brute force
all 2^32 seeds: generate, early-reject when the first tall item drawn
differs from the observed (0,0) item, finally pack the grid and require
every observed (item, position) pair to match.

Constants: exceptional weight 90/10000 per level-diff (+1), elite
33/10000 per level-diff (+1). Some console builds have uncertain pool
order entries — the search then treats them as wildcard groups bound on
first use (current PS5 data has none).

## Purchase quality (the point of it all)

The "trailing" 4th roll per slot is the **quality roll**: `q = lo % 100000`
against thresholds z=50 (unique), re=100 (set), xe=10000 (rare):

- `q < 50` → **unique**, if the (tier-upgraded) item has a unique with
  qlvl <= gamble ilvl (per-item table `unique_lvl`, 352 eligible items)
- `q < 150` → **set**, if eligible (`set_lvl`, 112 items); a sub-50 roll
  falls through to set/rare when no unique is eligible
- `q < 10150` → **rare**
- else → **magic**

So the simulator knows, for every slot of every future refresh, what the
item BECOMES when bought. Port: `generate_full` / `Ctx.quality_of`.

## Buying (be / fe)

Buying a slot consumes rolls and (D2R) rerolls the slot:

1. non-ring/amulet: 1 roll (circlet family flips Circlet/Coronet on bit 0)
2. 1 roll: new ilvl = clamp(clvl - 5 + lo % 10)
3. 0-2 rolls: exceptional/elite upgrade (weights 90/33 as in generation)
4. 1 roll: quality

Total 2 (jewelry) or 3-5 rolls. Port: `buy_roll`.

## Vendor fill ("reassemble vendor", D2R)

Opening the store ALSO fills the NPC's regular inventory, consuming draws
between the first window and the first refresh — omitting it desyncs all
refresh predictions. Per NPC (gheed/elzix/alkor/jamella/anya) there is a
spec list; cap ilvl = clvl+5 (capped per NPC in Normal); for each spec with
level <= ilvl: if ilvl < 25 roll count in [nmin,nmax] and consume that many
draws; if magic and mlvl <= ilvl: count in [mmin, mmax + (1 or R(1,2)+1)]
and, when difficulty != Normal and clvl > 25, consume that many draws;
extras consume 1 draw each under the same difficulty gate. Ranged roll
R(a,b) consumes 1 draw (bitmask when the range is a power of two).
Port: `vendor_fill` (validated on all 5 NPCs x 3 difficulties).

## Versions & game seed

- `d2` (Classic): no vendor fill, bought slot is removed, base pools.
- `d2r` (Resurrected): vendor fill, bought slot rerolls. Default.
- `row` (Reign of the Warlock mod): as d2r with the `row` pools.

The in-game seed maps to the store seed via 3 (d2) / 4 (d2r) warm-up
advances from (seed, 666), taking the resulting lo. Port:
`game_seed_to_store`.

## search.worker (buy planner, function qe)

BFS over store states from (lo, hi, absPos, window). Node expansions:

1. **Refresh** — generate the next window (site ye = our generate_full).
2. **Collect** — buy a slot whose (display item, tier, quality) matches a
   target spec {nameIdx|-1, tier|-1, rarity|-1}; default specs = any
   set/rare/unique. Terminal (collected=1). Score = rank(quality)*10+tier,
   rank: unique 3, set 2, rare 1.
3. **Shift-buy** — buy junk purely to advance the RNG. Candidates: the
   cheapest item (level*100+w*h) per roll-consumption class 2..5 (jewelry
   always 2; 3+Ge(item, peeked ilvl, peeked exc roll) otherwise). Only
   when rerollBoughtSlot and buys < maxBuys.

Dedup on (absPos, collected, window). Caps: 2e6 nodes, 30 plans, plans
deduped by outcome (display item, quality, tier) counting alternate routes;
sorted by score desc, depth asc, absPos asc. Steps carry the grid position
of the clicked slot (packing the pre-step window).

Port: `advisor/gamble_plan.py::plan_buys` — validated bit-exact against
the site's worker (plans, explored/nodes/outcomes) on randomized cases
across levels/platforms/depths. The auto-clicker (`advisor/autoclicker.py`)
executes a chosen plan in game from a 3-point screen calibration.
