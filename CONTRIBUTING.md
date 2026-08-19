# Contributing to D2R Item Advisor

Thanks for taking the time to contribute! This document covers the
workflow for code changes, bug reports and feature requests.

## Bugs and feature requests

Open a [GitHub issue](../../issues/new/choose) and pick the matching
template:

- **Bug report** — attach the `debug/*_full.png` / `*_crop.png` pair for
  recognition bugs (set `debug: true` in `config.yaml` and press F8/F10
  on the problematic item first), the console output, and your
  game/graphics settings (Large Font Mode, resolution, legacy vs
  resurrected graphics).
- **Feature request** — describe the problem you are solving, not only
  the solution; for gamble/seed-finder features include how the DBM site
  handles it (if it does).

## Development setup

```bash
git clone git@github.com:psolvy/d2r_advisor.git
cd d2r_advisor
pip install -r requirements.txt
python tools/setup_assets.py   # icons + fast-search workers (not in git)
python main.py
```

Windows is the only supported platform for the app itself (screen
capture, global hotkeys, the auto-clicker); the engine and parsers are
pure Python and testable anywhere.

## Tests

```bash
python tests/test_regression.py   # 54 offline tests: engine, parser, planner
python tests/test_vision.py       # icon recognition (skips without icons)
```

- Every PR must keep `test_regression.py` green — CI runs it on Python
  3.12 and 3.13.
- Engine changes (`advisor/gamble_seed.py`, `advisor/gamble_plan.py`)
  must stay **bit-exact** against the DBM site's workers: run the
  harnesses in `tools/dbm_validation/` (`validate_planner.py`,
  `validate_fill.py`; they need Node.js and
  `python tools/get_dbm_workers.py`).
- New behavior needs a test in `tests/test_regression.py` — the suite is
  plain asserts, no framework.

## Pull requests

1. Fork/branch from `main`.
2. Make the change; keep the code style of the surrounding file
   (module-level docstrings, comments explain *why*, not *what*).
3. Run the tests above.
4. Open a PR — CI must pass before review. A merge to `main` triggers CI
   again and, when green, the CD pipeline refreshes the rolling
   `latest` pre-release automatically.

Versioned releases are cut by tagging: `git tag v1.x.y && git push
origin v1.x.y` (maintainers only).

## What not to commit

Never commit content the repository cannot legally redistribute — the
`.gitignore` already covers it:

- `d2rlootreader/repository/gamble_icons/` (Blizzard art),
- `tools/dbm_validation/*.worker.js` and the other DBM site files,
- `tools/_cache/` (d2data dumps),
- personal state: `debug/`, `history.log`, `gamble_clicks.json`.

`tools/setup_assets.py` fetches all of it locally; the standalone exe
does the same on first run.

## Updating the knowledge bases after a game patch

```bash
python tools/update_repository.py
python tools/gen_ranges.py
python tools/gen_runewords.py
python tools/gen_cube.py
python tools/gen_gamble.py
```

Unique display names sometimes differ from the game files' internal
names — add new mismatches to `tools/display_names.py` (the tooltip
shows "Lenymo", the txt says "Lenyms Cord"; OCR matches what the screen
shows).
