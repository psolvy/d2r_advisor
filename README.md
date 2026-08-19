# D2R Item Advisor

[![CI](https://github.com/psolvy/d2r_advisor/actions/workflows/ci.yml/badge.svg)](https://github.com/psolvy/d2r_advisor/actions/workflows/ci.yml)
[![License: GPL-3.0](https://img.shields.io/badge/License-GPLv3-blue.svg)](LICENSE)

Hover an item in Diablo II: Resurrected, press **F8** — a verdict pops up
next to the cursor: **KEEP / CHECK / TRASH** (plus the recognized item and
the rule that fired).

For uniques and sets the verdict shows the **full stat list with roll
ranges**: variable stats are highlighted and the recognized roll is
compared against its range (★ MAX = perfect roll). Item quality is pinned
by the **color of the name line** in the tooltip (green = set, gold =
unique/runeword, yellow = rare, blue = magic), so even an item missing
from the name database is never mistaken for a plain gray base.

Everything works from screenshots and OCR only — **no game memory is
read, nothing is injected into the process** (the safest class of tools;
still, any third-party program is formally a gray area under Blizzard's
ToS — use at your own risk).

> **Scope note.** The item advisor (verdicts, roll ranges, runeword /
> craft / gamble advice) reads your screen and works **anywhere —
> online and offline alike**. Only the **gambling seed features**
> (Seed Finder, refresh forecasts, buy planner, auto-clicker) are
> **single player / offline only**: the seed mechanics exist only where
> the RNG runs locally — online/ladder RNG is server-side and cannot be
> predicted or influenced by this tool (or any tool); that part is
> provided for offline play and educational interest in the game's RNG
> internals.

<p align="center">
  <img src="docs/img/verdict.png" width="600"
       alt="F9 verdict popup: Harlequin Crest — CHECK, S-tier, full roll ranges">
</p>

*A real F9 scan: the popup pins the quality by the tooltip name color,
matches the unique, shows the S-tier value verdict and every stat with
its roll range — clickable name opens the item's page.*

## Requirements

- Windows 10/11
- **English game client** (the OCR model is trained on the English D2R font)
- In game settings: **Options → Interface → Large Font Mode = ON**
  (large tooltip font — greatly improves recognition accuracy)
- **Tesseract OCR** — needed only for the tooltip verdicts (F8/F9), every
  other feature works without it:
  `winget install UB-Mannheim.TesseractOCR` (or the installer from
  https://github.com/UB-Mannheim/tesseract/wiki)
- Optional: **Node.js** (https://nodejs.org) — turns the seed search from
  minutes into seconds

## Installation — standalone exe (recommended)

1. Download **d2r-advisor-…-windows-x64.zip** from
   [Releases](https://github.com/psolvy/d2r_advisor/releases), unpack
   anywhere, run `d2r-advisor.exe`.
2. The app lives in the **system tray** (check the `^` overflow area).
   Double-click the icon → **Settings**, with a health panel that says if
   anything is missing (e.g. Tesseract) and what that disables.
3. On first run it downloads the gamble icons and fast-search workers
   automatically and adds itself to the **Start Menu**.

## Installation — from source (only if you prefer to)

1. Install Python 3.9+ — https://www.python.org/downloads/ (check
   **Add python.exe to PATH** in the installer).
2. Double-click `install.bat` — installs Tesseract (via winget), the
   Python dependencies, and the assets that are not part of the
   repository (see
   [Licensing](#licensing-and-third-party-content)).
3. Start with `run.bat` (a console window appears — the exe build uses
   `advisor.log` instead).

Either way, run the game in **Windowed** or **Windowed Fullscreen**
mode — in exclusive fullscreen the overlay may not show above the game.

## Usage

1. Start the app (`d2r-advisor.exe` or `run.bat`).
2. In game, open the inventory and hover an item so its tooltip shows.
3. Press **F8** (keep the mouse on the item). The verdict appears in
   ~1-2 seconds.
4. Click the verdict popup to dismiss it.

## Customization

The app lives in the **system tray**: double-click the icon for
**Settings** — every config value is editable there (hotkeys, rules
preset, scales, Seed Finder defaults, tesseract path…), with a health
panel on top that says what is not configured yet (e.g. Tesseract
missing) and what that disables. "Save & Restart" applies everything.
The standalone exe also hides its console into the tray and adds itself
to the Start Menu on first run.

Everything the UI edits is plain `config.yaml`, editable by hand too:

- `config.yaml` — hotkeys, **rules preset**, display time, roll ranges
  on/off, tesseract path, debug.
- Rule presets (`preset:` in config.yaml):
  - `leveling` — ladder start / leveling: all runes and gems, skillers,
    charms with low thresholds, bases for Insight/Spirit;
  - `midgame` — 75+: runes from Shael up, flawless/perfect gems, higher
    thresholds, bases for CoH/Exile;
  - `lategame` — endgame: only Pul+, perfects, top charms; uniques/sets
    are "check" (the roll decides, ranges shown in the popup);
  - `custom` — your own `rules.yaml` in the project root (a copy of
    leveling by default).
  The rule format is documented at the top of every preset
  (`presets/*.yaml`).

Exact affix templates for rules live in
`d2rlootreader/repository/affixes.json` (numbers are replaced with `#`,
e.g. `"+#% Faster Cast Rate"`).

For white bases the verdict lists **runewords that fit the base and its
socket count** (respecting the base's maximum sockets); for unsocketed
bases — the cube/Larzuk recipes to punch sockets.

Additionally:
- **runes**: cube upgrade recipe + runewords using the rune;
- **gems**: upgrade path and uses (GC rerolls, crafts);
- **uniques/sets**: S/A/B/C value tier from the curated database
  (`repository/value_tiers.json` — edit to match the current market);
- **verdict sound** (high = keep, mid = check, low = trash) — `sounds`
  in the config;
- **scan journal** `history.log` (JSON lines) — `history` in the config.

**Underlined lines in the popup are clickable** — a click opens the
browser with details (runeword, craft recipe, unique page). Configure the
destination via `link_template` in config.yaml (web search by default;
diablo2.io etc. work too). Clicking a link keeps the popup open; clicking
anywhere else closes it.

Cube and crafts:
- **magic item on a craftable base** → craft recipes (Blood / Caster /
  Hit Power / Safety) with the required rune and gem;
- **unique/rare on a non-elite base** → tier upgrade recipe
  (runes + gem → new base);
- **set item** → the other set pieces and the green set bonuses with
  piece thresholds;
- **vendor/gamble tooltip** (a Cost/Buy line) → advice whether the base
  is worth gambling.

## Gambling: F10 and the Seed Finder (Shift+F10)

*(offline characters only — online gambling is rolled on Blizzard's
servers and no simulator can predict it)*

<p align="center">
  <img src="docs/img/seedfinder.png" width="900"
       alt="Gamble Seed Finder: offer grid, found seed, refresh forecast, buy plan">
</p>

*A live session: the offer filled itself from the F10 icon scan, "Find
seed" swept all 2³² seeds and found it, the forecast lists upcoming
refreshes, and the planner routed to a UNIQUE — the glowing slot on the
grid is where it will sit when you buy it.*

- **F10** on the gamble screen: reads the whole offer and copies the list
  to the clipboard. In **resurrected graphics** the gamble window shows
  icons without text, so reading is **icon-based** (template matching,
  icons in `repository/gamble_icons/`). The grid is located
  **automatically** (via the Ring+Amulet pair in the top-right corner) —
  no calibration needed; grid **positions** are recognized too, so the
  auto-clicker only needs the Refresh button set ("Set Refresh button").
  In **legacy graphics** (text list) OCR works as before.

  <p align="center">
    <img src="docs/img/gamble-vision.png" width="560"
         alt="Icon recognition: every offer item boxed with its match confidence">
  </p>

  *What the recognizer sees: every item boxed on the auto-located grid
  with its template-match confidence (this debug view is saved to
  `debug/` on every F10 scan).*
- The Seed Finder window is a modern dark UI with the **site-style visual
  10×10 grid**: the offer is shown as icons; click a cell to pick an item
  (searchable dropdown with icons), right-click removes. The window is
  freely resizable; scale via `seedfinder_scale` in config.yaml.
- **Shift+F10** — the **Gamble Seed Finder**: a full local port of the
  [gambling.diablo.deadlybossmods.com](https://gambling.diablo.deadlybossmods.com/)
  simulator (engine, buy planner and vendor fill validated **bit-exact**
  against the site's workers). Everything the site does, plus:
  - the offer is **pre-filled automatically** from the last F10 scan — no
    manual entry, just correct OCR mistakes if any;
  - **grid positions are optional**: a full 14-item list is enough
    (the site always requires positions);
  - "Find seed" brute-forces all 2^32 seeds on all cores (seconds via the
    site's own kernel in Node, minutes on the built-in engine), fills the
    Seed field and immediately prints upcoming refreshes;
  - the forecast shows **purchase quality**: which slot of which refresh
    becomes **UNIQUE / SET / rare** (the whole point of the simulator);
  - "Plan buys" — the **buy planner** (a port of the site's
    search.worker): finds the shortest route of refreshes and
    pool-shifting buys to a target item (any unique/set/rare, or a
    specific base + quality + tier);
  - "Execute plan" — the **auto-clicker**: clicks the chosen plan through
    in game (refresh = button click, buy = right-click on the cell) with
    a focus countdown and live progress. Grid cells calibrate
    **automatically on the F10 scan**; you only set the Refresh button
    ("Set Refresh button") and the "**Set sell zone**" — the empty
    inventory area where purchases land: filler buys are **auto-sold
    back** (Ctrl+click, consumes no RNG). ESC is the emergency stop.
    After a run (or a stop) the RNG state is **applied automatically** —
    the grid, forecasts and planner continue from the current moment;
  - "Find offset (after buys)" — manual purchases shift the RNG stream;
    enter the current offer and the offset resyncs;
  - selectors: platform (PC=msvc/consoles), version (D2R/classic/RoW),
    NPC and difficulty (they drive the "vendor fill" — the vendor
    inventory top-up on window open that shifts all later refreshes),
    an "in-game seed" checkbox for seeds taken from the game.

Offline tests (no game, no Tesseract): `py -3 tests\test_regression.py`.

After a game patch, refresh the knowledge bases:
`python tools/update_repository.py`, then `python tools/gen_ranges.py`,
`python tools/gen_runewords.py` and `python tools/gen_cube.py`
(data comes from [blizzhackers/d2data](https://github.com/blizzhackers/d2data)).

## If recognition is poor

1. Enable Large Font Mode (mandatory).
2. Set `debug: true` in `config.yaml`, press F8 on the problematic item —
   `debug/` gets `*_full.png` and `*_crop.png`. If `_crop.png` is not the
   tooltip, the detector missed — share the images so it can be tuned.
3. Tooltips over dark textures (equipped gear on the left) read worse —
   keep the item in the right-side inventory bag.

## How it works

`F8` → full-screen screenshot (mss) → dark tooltip rectangle search near
the cursor (OpenCV) → D2R font OCR (Tesseract + the trained
`d2r.traineddata` model) → stat parsing into JSON (fuzzy matching against
the unique/set/affix database from
[d2r-loot-reader](https://github.com/lucekdudek/d2r-loot-reader)) → your
rules from `rules.yaml` → verdict popup (tkinter).

## Licensing and third-party content

The tool is distributed under **GPL-3.0-or-later** (see LICENSE): it
contains code and data from
[d2r-loot-reader](https://github.com/lucekdudek/d2r-loot-reader)
(GPL-3.0-or-later) and the D2R font OCR model from the horadricapp
project (MIT). Item tables are generated from
[blizzhackers/d2data](https://github.com/blizzhackers/d2data) dumps.

**What is NOT in the repository** (and why): content we do not own is
not redistributed — `install.bat` (step 4) or
`python tools/setup_assets.py` downloads it to your machine at install
time, exactly the way a browser does when you open the corresponding
sites (the standalone exe does the same on first run):

- `d2rlootreader/repository/gamble_icons/` — item icons (Blizzard art,
  served by the DBM site) — needed for icon-based F10 recognition;
  without them the OCR fallback still works;
- `tools/dbm_validation/*.worker.js` — the workers of the
  [gambling.diablo.deadlybossmods.com](https://gambling.diablo.deadlybossmods.com/)
  simulator — give "website speed" in Find seed; without them the search
  runs on the built-in numpy engine (slower);
- `tools/_cache/` — d2data JSON dumps, fetched by the generators
  automatically.

Blizzard Entertainment is not affiliated with this project. Diablo® II
is a trademark of Blizzard Entertainment. Using third-party programs is
formally a gray area under the game's ToS — use at your own risk.

## CI / CD

- **CI** (`.github/workflows/ci.yml`): every PR and every push to `main`
  — compile all modules + 54 offline engine/parser/planner tests
  (Windows, Python 3.12 and 3.13). Icon tests skip automatically when
  the icons are not downloaded (they never are in CI — see above).
- **CD** (`.github/workflows/release.yml`), two paths:
  - a merge to `main` triggers CI, and a **green CI** then triggers the
    release build automatically (CI → CD), refreshing the rolling
    **`latest` pre-release** with a source zip and a standalone
    **PyInstaller exe** bundle;
  - a `v*` tag cuts a **versioned release** with the same two artifacts
    and auto-generated notes: `git tag v1.0.1 && git push origin v1.0.1`.

Contributions welcome — see [CONTRIBUTING.md](CONTRIBUTING.md); bugs and
feature requests go through the
[issue templates](../../issues/new/choose).
