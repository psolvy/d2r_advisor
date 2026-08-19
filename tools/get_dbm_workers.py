"""Download the DBM gambling simulator's worker scripts for LOCAL use.

brute.worker.js powers the fast seed-search path (advisor/brute_host.js
runs it in Node worker_threads at website speed); search.worker.js is used
by the tools/dbm_validation harnesses to check our port bit-for-bit.

These files are the site authors' code and are NOT redistributed with this
repository — this script fetches them onto your machine, the same way your
browser does when you open the site. Without them everything still works:
the seed search falls back to the built-in numpy engine (slower).

The workers live at content-hashed URLs (/assets/brute.worker-<hash>.js)
that change when the site redeploys, so they are discovered from the
site's bundles on every run.
"""
import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "tools" / "dbm_validation"
BASE = "https://gambling.diablo.deadlybossmods.com"
WANTED = ["brute.worker", "search.worker"]


def _get(url):
    return urllib.request.urlopen(url, timeout=30).read()


def find_worker_urls():
    """index.html -> bundle scripts -> worker asset paths."""
    html = _get(BASE + "/").decode("utf-8", "replace")
    scripts = re.findall(r'src="(/assets/[\w.-]+\.js)"', html)
    scripts += re.findall(r'"(/assets/[\w.-]+\.js)"', html)
    found = {}
    for src in dict.fromkeys(scripts):
        try:
            js = _get(BASE + src).decode("utf-8", "replace")
        except Exception:
            continue
        for path in re.findall(r'(/assets/[\w-]+\.worker-[\w-]+\.js)', js):
            for stem in WANTED:
                if path.startswith("/assets/" + stem + "-"):
                    found.setdefault(stem, path)
        if len(found) == len(WANTED):
            break
    return found


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    have = [s for s in WANTED
            if (OUT / f"{s}.js").exists()
            and (OUT / f"{s}.js").stat().st_size > 0]
    if len(have) == len(WANTED):
        print(f"already present: {', '.join(s + '.js' for s in have)} "
              f"-> {OUT}")
        return 0
    try:
        found = find_worker_urls()
    except Exception as e:
        print(f"FAIL: cannot reach the site ({e})")
        print("note: the app still works — the seed search just uses the "
              "slower built-in engine")
        return 1
    fail = 0
    for stem in WANTED:
        dest = OUT / f"{stem}.js"
        if dest.exists() and dest.stat().st_size > 0:
            continue
        path = found.get(stem)
        if not path:
            print(f"FAIL {stem}.js: not found in the site bundles")
            fail += 1
            continue
        try:
            dest.write_bytes(_get(BASE + path))
            print(f"downloaded {stem}.js  ({path})")
        except Exception as e:
            print(f"FAIL {stem}.js: {e}")
            fail += 1
    if fail:
        print("note: the app still works — the seed search just uses the "
              "slower built-in engine")
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
