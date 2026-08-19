"""One-shot setup: fetch every asset the repository does not ship.

Run once after cloning (install.bat does it for you):

    python tools/setup_assets.py

Downloads, all for local use only:
  1. gamble item icons  (icon-based F10 offer recognition)
  2. DBM worker scripts (website-speed seed search + validation)

Everything degrades gracefully if a download fails: OCR still works, the
seed search falls back to the built-in numpy engine.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import get_dbm_workers
import get_gamble_icons


def main():
    print("== gamble icons ==")
    rc1 = get_gamble_icons.main()
    print("== DBM workers ==")
    rc2 = get_dbm_workers.main()
    return 1 if (rc1 or rc2) else 0


if __name__ == "__main__":
    sys.exit(main())
