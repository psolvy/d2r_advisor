"""Self-update from GitHub releases.

check() compares advisor.version against the newest release tag of
psolvy/d2r_advisor (public API, no auth). Applying:

- frozen exe (onedir): download the windows-x64 zip, extract next to the
  install, spawn a swap .bat that waits for the app to exit, copies the
  new build over (KEEPING config.yaml / gamble_clicks.json / advisor.log
  and the downloaded icons+workers), restarts the exe;
- source checkout with .git: `git pull --ff-only` + pip install, restart;
- source zip without .git: just open the releases page.
"""
import json
import os
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

from advisor.version import __version__

REPO = "psolvy/d2r_advisor"
API_LATEST = f"https://api.github.com/repos/{REPO}/releases/latest"
RELEASES_URL = f"https://github.com/{REPO}/releases"
ROOT = Path(__file__).resolve().parents[1]


def _ver_tuple(s):
    s = s.strip().lstrip("vV")
    try:
        return tuple(int(x) for x in s.split(".")[:3])
    except ValueError:
        return (0,)


def check(timeout=15):
    """(newer_available, latest_tag, exe_asset_url) — never raises."""
    try:
        req = urllib.request.Request(
            API_LATEST, headers={"Accept": "application/vnd.github+json",
                                 "User-Agent": "d2r-advisor"})
        data = json.load(urllib.request.urlopen(req, timeout=timeout))
    except Exception:
        return False, None, None
    tag = data.get("tag_name") or ""
    newer = _ver_tuple(tag) > _ver_tuple(__version__)
    asset = next((a["browser_download_url"]
                  for a in data.get("assets", [])
                  if a["name"].endswith("windows-x64.zip")), None)
    return newer, tag, asset


def apply_update(asset_url, on_step=print):
    """Start the update; returns True when the app should QUIT (the swap
    script or the relaunch takes over)."""
    if getattr(sys, "frozen", False):
        return _update_frozen(asset_url, on_step)
    if (ROOT / ".git").exists():
        return _update_git(on_step)
    import webbrowser
    webbrowser.open(RELEASES_URL)
    on_step("no .git here — download the new build from the releases page")
    return False


def _update_git(on_step):
    on_step("git pull --ff-only …")
    r = subprocess.run(["git", "pull", "--ff-only"], cwd=str(ROOT),
                       capture_output=True, text=True, timeout=300)
    on_step((r.stdout or r.stderr).strip()[:400])
    if r.returncode != 0:
        return False
    on_step("pip install -r requirements.txt …")
    subprocess.run([sys.executable, "-m", "pip", "install", "-q", "-r",
                    str(ROOT / "requirements.txt")], timeout=900)
    subprocess.Popen([sys.executable, str(ROOT / "main.py")],
                     cwd=str(ROOT), creationflags=0x00000010)
    return True


def _update_frozen(asset_url, on_step):
    if not asset_url:
        return False
    exe_dir = Path(sys.executable).parent
    tmp = Path(tempfile.mkdtemp(prefix="d2r-advisor-update-"))
    zpath = tmp / "update.zip"
    on_step(f"downloading {asset_url.rsplit('/', 1)[-1]} …")
    urllib.request.urlretrieve(asset_url, zpath)
    on_step("unpacking …")
    with zipfile.ZipFile(zpath) as z:
        z.extractall(tmp)
    new_dir = next((p for p in tmp.iterdir()
                    if p.is_dir() and (p / "d2r-advisor.exe").exists()), None)
    if new_dir is None:
        on_step("unexpected archive layout — update aborted")
        return False
    # the swap runs after we exit; user data and downloaded assets survive.
    # NOTE: no `timeout` here — it needs a real console and dies inside a
    # windowless cmd, which silently broke the whole swap. ping is the
    # console-free delay; findstr matches the padded pid exactly.
    pid = os.getpid()
    log = exe_dir / "update.log"
    bat = tmp / "swap.bat"
    bat.write_text(
        "@echo off\n"
        f"echo swap started %date% %time% > \"{log}\"\n"
        ":wait\n"
        "ping -n 2 127.0.0.1 >nul\n"
        f"tasklist /FI \"PID eq {pid}\" 2>nul | findstr /C:\" {pid} \" >nul\n"
        "if not errorlevel 1 goto wait\n"
        f"echo app exited, copying >> \"{log}\"\n"
        f"robocopy \"{new_dir}\" \"{exe_dir}\" /E /NFL /NDL /NJH /NJS "
        "/XF config.yaml gamble_clicks.json advisor.log rules.yaml "
        f">> \"{log}\" 2>&1\n"
        f"echo robocopy exit %errorlevel% >> \"{log}\"\n"
        f"start \"\" \"{exe_dir / 'd2r-advisor.exe'}\"\n"
        f"rd /s /q \"{tmp}\"\n",
        encoding="ascii")
    on_step("restarting with the new build …")
    subprocess.Popen(["cmd", "/c", str(bat)],
                     creationflags=0x08000000,  # CREATE_NO_WINDOW
                     close_fds=True)
    return True
