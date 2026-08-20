"""Terror Zone widget: current + next zone from a community API.

Both known providers require a free token (put it in Settings):
- d2runewizard.com  -> tz_api_url https://d2runewizard.com/api/terror-zone
- d2emu.com         -> tz_api_url https://www.d2emu.com/api/v1/tz

The parser is defensive: it walks whatever JSON comes back and pulls the
current/next zone names, so minor API format changes don't break it.
"""
import json
import urllib.error
import urllib.request

import tkinter as tk

_open_window = None


def fetch(cfg, timeout=15):
    """(current, next, error) — zone name strings or None."""
    url = (cfg.get("tz_api_url") or "").strip()
    token = (cfg.get("tz_api_token") or "").strip()
    if not url:
        return None, None, "not configured"
    headers = {"User-Agent": "d2r-advisor",
               "D2R-Contact": "github.com/psolvy/d2r_advisor",
               "D2R-Platform": "GitHub", "D2R-Repo": "psolvy/d2r_advisor"}
    if token:
        if "d2emu" in url:
            # d2emu authenticates username+token; a hardcoded username
            # guaranteed a 401 for every user
            user = (cfg.get("tz_api_user") or "").strip()
            if not user:
                return None, None, ("d2emu needs your account name — set "
                                    "tz_api_user in Settings")
            headers["x-emu-username"] = user
            headers["x-emu-token"] = token
        else:
            url += ("&" if "?" in url else "?") + "token=" + token
    try:
        req = urllib.request.Request(url, headers=headers)
        data = json.load(urllib.request.urlopen(req, timeout=timeout))
    except urllib.error.HTTPError as e:
        hint = " — check your token in Settings" if e.code in (401, 403)             else " — provider rate limit, try later" if e.code == 429 else ""
        return None, None, f"HTTP {e.code}{hint}"
    except Exception as e:
        return None, None, f"{type(e).__name__}: {e}"

    def zone_of(node):
        if isinstance(node, str):
            return node
        if isinstance(node, dict):
            for k in ("zone", "name", "displayName", "highestProbabilityZone"):
                v = node.get(k)
                if isinstance(v, (str, dict)):
                    return zone_of(v)
            for v in node.values():
                got = zone_of(v)
                if got:
                    return got
        if isinstance(node, list) and node:
            return ", ".join(z for z in (zone_of(v) for v in node) if z)
        return None

    cur = nxt = None
    if isinstance(data, dict):
        for key, target in (("currentTerrorZone", "cur"), ("current", "cur"),
                            ("nextTerrorZone", "nxt"), ("next", "nxt")):
            if key in data:
                z = zone_of(data[key])
                if target == "cur":
                    cur = cur or z
                else:
                    nxt = nxt or z
    if not cur and not nxt:
        # deliberately NOT walking the whole payload as a fallback: it
        # confidently returned the first string it met ("providedBy", a
        # timestamp) as the current zone
        return None, None, "unexpected response format (no current/next "                            "zone keys) — check tz_api_url"
    return cur, nxt, None


def open_tz_window(root, cfg, scale=1.0):
    # singleton: every tray click used to stack one more always-on-top window
    global _open_window
    if _open_window is not None:
        try:
            if _open_window.winfo_exists():
                _open_window.deiconify()
                _open_window.lift()
                return _open_window
        except Exception:
            pass
        _open_window = None
    from advisor.seedfinder_ui import BG, DIM, FG, GOLD, GOLD_HI, LINE, PANEL
    s = max(1.0, float(scale))
    win = tk.Toplevel(root)
    _open_window = win
    win.title("D2R Item Advisor — Terror Zone")
    win.configure(bg=BG)
    win.resizable(False, False)
    f_base = ("Segoe UI", int(11 * s))
    pad = int(12 * s)
    tk.Label(win, text="TERROR ZONE", bg=BG, fg=GOLD_HI,
             font=("Segoe UI", int(13 * s), "bold")
             ).pack(anchor="w", padx=pad, pady=(pad, 2))
    body = tk.Label(win, text="fetching…", bg=PANEL, fg=FG, font=f_base,
                    justify="left", anchor="w", wraplength=int(420 * s),
                    padx=10, pady=8, highlightthickness=1,
                    highlightbackground=LINE)
    body.pack(fill="x", padx=pad)
    # TZ flips on the hour — the countdown is the number a player wants
    timer = tk.Label(win, text="", bg=BG, fg=GOLD_HI, font=f_base)
    timer.pack(anchor="w", padx=pad, pady=(int(4 * s), 0))

    def tick():
        if not win.winfo_exists():
            return
        import time as _t
        now = _t.localtime()
        left = 60 - now.tm_min - (1 if now.tm_sec else 0)
        timer.configure(text=f"next rotation in ~{max(0, left)} min")
        # refresh shortly after the flip, once per hour
        if now.tm_min == 0 and now.tm_sec < 45:
            _load(win, body, cfg)
        win.after(30000, tick)

    tick()

    # clickable provider links: left click opens, right click copies
    links = tk.Frame(win, bg=BG)
    links.pack(fill="x", padx=pad, pady=(int(6 * s), 0))
    for label, url in (("d2runewizard.com/integration",
                        "https://d2runewizard.com/integration"),
                       ("d2emu.com/terms", "https://www.d2emu.com/terms")):
        lbl = tk.Label(links, text=label, bg=BG, fg=GOLD_HI,
                       font=(f_base[0], f_base[1], "underline"),
                       cursor="hand2")
        lbl.pack(anchor="w")

        def _open(_e, u=url):
            import webbrowser
            webbrowser.open(u)

        def _copy(_e, u=url):
            win.clipboard_clear()
            win.clipboard_append(u)
            body.configure(text=f"copied: {u}")

        lbl.bind("<Button-1>", _open)
        lbl.bind("<Button-3>", _copy)
    tk.Button(win, text="Refresh", bg=GOLD, fg="#191307", relief="flat",
              font=f_base, padx=int(12 * s),
              command=lambda: _load(win, body, cfg)
              ).pack(pady=(int(8 * s), pad))
    _load(win, body, cfg)
    win.lift()
    win.attributes("-topmost", True)  # stays above the game
    return win


def _load(win, body, cfg):
    import threading

    def work():
        cur, nxt, err = fetch(cfg)
        if err == "not configured":
            text = ("Not configured. Get a FREE token:\n"
                    "• d2runewizard.com/integration — set tz_api_url to\n"
                    "  https://d2runewizard.com/api/terror-zone\n"
                    "• or d2emu.com/terms\n"
                    "and paste the token in Settings (tz_api_token).")
        elif err:
            text = f"fetch failed: {err}"
        else:
            text = f"NOW:   {cur or '?'}"
            if nxt:
                text += f"\nNEXT: {nxt}"
        try:
            win.after(0, lambda: body.configure(text=text))
        except Exception:
            pass

    threading.Thread(target=work, daemon=True).start()
