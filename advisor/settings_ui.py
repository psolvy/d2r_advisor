"""Settings window: every config.yaml value editable from the UI, plus a
live health panel ("what is not configured"). Saving rewrites only the
VALUE part of each line, so all comments in config.yaml survive.

Hotkeys and scales are read once at startup — Save & Restart relaunches
the app so everything applies immediately.
"""
import json
import os
import re
import sys
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, ttk

from advisor.seedfinder_ui import (BG, DIM, FG, FIELD, GOLD, GOLD_HI, GREEN,
                                   LINE, PANEL, RED)

ROOT = Path(__file__).resolve().parents[1]

CLASSES = ["", "amazon", "assassin", "barbarian", "druid", "necromancer",
           "paladin", "sorceress"]
PRESETS = ["leveling", "midgame", "lategame", "custom", "auto"]
PLATFORMS = ["PC", "PlayStation", "Xbox", "Switch"]
VERSIONS = ["row", "d2r", "d2"]
NPCS = ["gheed", "elzix", "alkor", "jamella", "anya"]
DIFFICULTIES = ["Normal", "Nightmare", "Hell"]
RARITIES = ["default", "unique", "set", "rare", "any"]
TIERS = ["any", "normal", "exceptional", "elite"]

# (key, label, kind, choices) — kind: str/int/float/bool/choice
GENERAL = [
    ("hotkey", "Scan hotkey (tooltip verdict)", "str", None),
    ("gamble_hotkey", "Gamble-screen hotkey", "str", None),
    ("seed_hotkey", "Seed Finder hotkey", "str", None),
    ("preset", "Rules preset", "choice", PRESETS),
    ("season_start", "Season start (YYYY-MM-DD, for auto)", "str", None),
    ("my_class", "Your class (breakpoint ladders)", "choice", CLASSES),
    ("char_level", "Character level (0 = off)", "int", None),
    ("display_seconds", "Verdict display seconds", "int", None),
    ("auto_update", "Check for updates on start", "bool", None),
    ("count_upcube", "Goals: count cube-upgrading runes/gems", "bool", None),
    ("show_ranges", "Show roll ranges", "bool", None),
    ("sounds", "Verdict sounds", "bool", None),
    ("history", "Write history.log", "bool", None),
    ("debug", "Debug screenshots", "bool", None),
    ("ui_scale", "Popup scale", "float", None),
    ("seedfinder_scale", "Seed Finder scale (empty = popup scale)", "str", None),
    ("link_template", "Link template ({query})", "str", None),
    ("price_link_template", "Price-check link ({query})", "str", None),
    ("compare_hotkey", "Gear-compare hotkey", "str", None),
    ("scan_settle", "Capture settle delay (s)", "float", None),
    ("tz_api_url", "Terror Zone API url", "str", None),
    ("tz_api_token", "Terror Zone API token", "str", None),
    ("tz_api_user", "Terror Zone API username (d2emu)", "str", None),
    ("tesseract_cmd", "Tesseract path (empty = auto)", "str", None),
]
SEEDFINDER = [
    ("level", "Level", "int", None),
    ("platform", "Platform", "choice", PLATFORMS),
    ("version", "Version", "choice", VERSIONS),
    ("npc", "NPC", "choice", NPCS),
    ("difficulty", "Difficulty", "choice", DIFFICULTIES),
    ("depth", "Planner depth", "int", None),
    ("shift_buys", "Planner shift-buys", "int", None),
    ("refreshes", "Preview refreshes", "int", None),
    ("max_offset", "Find-offset max", "int", None),
    ("click_delay", "Clicker delay (s)", "float", None),
    ("execute_delay", "Execute focus delay (s)", "float", None),
    ("target", "Planner target (empty = any)", "str", None),
    ("target_rarity", "Target rarity", "choice", RARITIES),
    ("target_tier", "Target tier", "choice", TIERS),
]


def _fmt(v):
    """YAML scalar for a value, quoting only when necessary."""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        s = str(v)
        return s[:-2] if s.endswith(".0") else s
    s = str(v)
    if s == "" or re.search(r'[:#{}\[\],&*?|>%@`"\']', s) or s != s.strip():
        return json.dumps(s)
    return s


def write_config(updates, sf_updates, path=None):
    """Rewrite values in place; comments and layout survive. Keys the file
    does not have yet are APPENDED — configs frozen by the updater's
    keep-list used to silently drop every new setting saved from the UI."""
    from advisor.paths import STATE_DIR
    path = path or STATE_DIR / "config.yaml"
    lines = path.read_text(encoding="utf-8").splitlines()
    seen, sf_seen = set(), set()
    out, in_sf = [], False
    for line in lines:
        body = line
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            indented = line[0].isspace()
            key = stripped.split(":", 1)[0].strip()
            # a comment is "  # like this" — '#' glued to a value (URL
            # fragment) is part of the value
            m = re.search(r"\s+#(?:\s.*)?$", line)
            comment = m.group(0) if m else ""
            if not indented:
                in_sf = key == "seedfinder"
                if key in updates:
                    body = f"{key}: {_fmt(updates[key])}{comment}"
                    seen.add(key)
            elif in_sf and key in sf_updates:
                body = f"  {key}: {_fmt(sf_updates[key])}{comment}"
                sf_seen.add(key)
        out.append(body)
    missing = [k for k in updates if k not in seen]
    if missing:
        out.append("")
        out.append("# added by Settings (key was not in the file yet)")
        for k in missing:
            out.append(f"{k}: {_fmt(updates[k])}")
    sf_missing = [k for k in sf_updates if k not in sf_seen]
    if sf_missing:
        add = [f"  {k}: {_fmt(sf_updates[k])}" for k in sf_missing]
        block = next((i for i, ln in enumerate(out)
                      if ln.split(":", 1)[0].strip() == "seedfinder"
                      and not ln[:1].isspace()), None)
        if block is None:
            out += ["", "seedfinder:"] + add
        else:
            end = block + 1
            while end < len(out) and (not out[end].strip()
                                      or out[end][:1].isspace()
                                      or out[end].lstrip().startswith("#")):
                end += 1
            out[end:end] = add
    # atomic: a crash mid-write must not truncate the user's config
    tmp = path.with_suffix(".yaml.tmp")
    tmp.write_text("\n".join(out) + "\n", encoding="utf-8")
    os.replace(tmp, path)


class Settings(tk.Toplevel):
    def __init__(self, root, cfg, restart_cb=None, scale=1.0):
        super().__init__(root)
        self.cfg = cfg
        self.restart_cb = restart_cb
        self.s = max(1.0, float(scale))
        s = self.s
        self.title("D2R Item Advisor — Settings")
        self.configure(bg=BG)
        self.f_base = ("Segoe UI", int(11 * s))
        self.f_sub = ("Segoe UI", int(10 * s))
        self.f_h = ("Segoe UI", int(13 * s), "bold")
        self.vars = {}
        self.sf_vars = {}

        self.resizable(False, False)  # fixed layout — no dead space
        self.attributes("-topmost", True)  # stay above the game
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("ST.TCombobox", fieldbackground=FIELD,
                        background=PANEL, foreground=FG,
                        arrowcolor=GOLD, bordercolor=LINE,
                        lightcolor=FIELD, darkcolor=FIELD)
        # readonly comboboxes render their value as a SELECTION — without
        # this map the gold highlight swallows the text completely
        style.map("ST.TCombobox",
                  fieldbackground=[("readonly", FIELD)],
                  selectbackground=[("readonly", FIELD)],
                  selectforeground=[("readonly", FG)],
                  foreground=[("readonly", FG)])

        pad = int(10 * s)
        tk.Label(self, text="SETTINGS", bg=BG, fg=GOLD_HI,
                 font=self.f_h).grid(row=0, column=0, columnspan=2,
                                     sticky="w", padx=pad,
                                     pady=(pad, int(4 * s)))
        # health panel — the "what is not configured" answer
        hp = tk.Frame(self, bg=PANEL, highlightthickness=1,
                      highlightbackground=LINE)
        hp.grid(row=1, column=0, columnspan=2, sticky="ew", padx=pad)
        self._health(hp)

        left = self._panel("GENERAL", 2, 0, GENERAL, self.vars,
                           self.cfg.get)
        sf = dict(self.cfg.get("seedfinder") or {})
        right = self._panel("SEED FINDER DEFAULTS", 2, 1, SEEDFINDER,
                            self.sf_vars, sf.get)
        # tesseract browse button — fields start at grid row 1, so the
        # LAST field (tesseract_cmd) sits at row len(GENERAL)
        tk.Button(left, text="…", command=self._browse_tesseract,
                  bg=FIELD, fg=FG, relief="flat",
                  font=self.f_sub).grid(row=len(GENERAL), column=2,
                                        sticky="w")

        btns = tk.Frame(self, bg=BG)
        btns.grid(row=3, column=0, columnspan=2, sticky="ew",
                  padx=pad, pady=pad)
        self.status = tk.Label(btns, text="", bg=BG, fg=DIM,
                               font=self.f_sub)
        self.status.pack(side="left")
        for text, cmd, hot in (("Save & Restart", self._save_restart, True),
                               ("Save", self._save, False),
                               ("Close", self.destroy, False)):
            b = tk.Button(btns, text=text, command=cmd,
                          bg=GOLD if hot else FIELD,
                          fg="#191307" if hot else FG,
                          activebackground=GOLD_HI, relief="flat",
                          font=self.f_base, padx=int(12 * s))
            b.pack(side="right", padx=(int(6 * s), 0))

    # ------------------------------------------------------------- layout

    def _health(self, parent):
        from advisor.health import health_report
        issues = health_report(self.cfg)
        colors = {"error": RED, "warn": GOLD_HI, "ok": DIM}
        if not issues:
            tk.Label(parent, text="✓ everything is configured", bg=PANEL,
                     fg=GREEN, font=self.f_base, anchor="w"
                     ).pack(fill="x", padx=8, pady=4)
        for lv, title, detail in issues:
            mark = {"error": "✕", "warn": "⚠", "ok": "·"}[lv]
            tk.Label(parent, text=f"{mark} {title} — {detail}", bg=PANEL,
                     fg=colors[lv], font=self.f_sub, anchor="w",
                     wraplength=int(760 * self.s), justify="left"
                     ).pack(fill="x", padx=8, pady=2)

    def _panel(self, title, row, col, fields, store, getter):
        s = self.s
        f = tk.Frame(self, bg=PANEL, highlightthickness=1,
                     highlightbackground=LINE)
        f.grid(row=row, column=col, sticky="nsew", padx=int(10 * s),
               pady=int(8 * s))
        tk.Label(f, text=title, bg=PANEL, fg=GOLD, font=self.f_base
                 ).grid(row=0, column=0, columnspan=2, sticky="w",
                        padx=8, pady=(6, 4))
        for i, (key, label, kind, choices) in enumerate(fields, 1):
            tk.Label(f, text=label, bg=PANEL, fg=DIM, font=self.f_sub
                     ).grid(row=i, column=0, sticky="w", padx=8, pady=2)
            val = getter(key)
            if kind == "bool":
                var = tk.BooleanVar(value=bool(val))
                # the check mark draws in fg — default black is invisible
                # on the dark indicator box
                w = tk.Checkbutton(f, variable=var, bg=PANEL,
                                   activebackground=PANEL,
                                   selectcolor=FIELD, fg=GOLD_HI,
                                   activeforeground=GOLD_HI,
                                   highlightthickness=0, bd=0)
            elif kind == "choice":
                var = tk.StringVar(value="" if val is None else str(val))
                w = ttk.Combobox(f, values=choices, textvariable=var,
                                 state="readonly", style="ST.TCombobox",
                                 width=18, font=self.f_sub)
                w.bind("<<ComboboxSelected>>",
                       lambda _e=None, cb=w: cb.selection_clear(), add=True)
            else:
                var = tk.StringVar(value="" if val is None else str(val))
                w = tk.Entry(f, textvariable=var, width=26, bg=FIELD,
                             fg=FG, insertbackground=GOLD, relief="flat",
                             font=self.f_sub, highlightthickness=1,
                             highlightbackground=LINE,
                             highlightcolor=GOLD)
            w.grid(row=i, column=1, sticky="w", padx=(4, 8), pady=2)
            store[key] = (var, kind)
        return f

    def _browse_tesseract(self):
        p = filedialog.askopenfilename(
            title="tesseract.exe", filetypes=[("tesseract", "*.exe")])
        if p:
            self.vars["tesseract_cmd"][0].set(p)

    # ------------------------------------------------------------- saving

    def _collect(self, store):
        out = {}
        for key, (var, kind) in store.items():
            v = var.get()
            if kind == "bool":
                out[key] = bool(v)
            elif kind == "int":
                try:
                    out[key] = int(float(str(v).strip() or 0))
                except ValueError:
                    raise ValueError(f"{key}: '{v}' is not a number")
            elif kind == "float":
                try:
                    out[key] = float(str(v).strip() or 0)
                except ValueError:
                    raise ValueError(f"{key}: '{v}' is not a number")
            else:
                out[key] = str(v).strip()
        return out

    def _save(self):
        try:
            updates = self._collect(self.vars)
            sf_updates = self._collect(self.sf_vars)
        except ValueError as e:
            self.status.configure(text=f"✕ {e}", fg=RED)
            return False
        try:
            write_config(updates, sf_updates)
        except Exception as e:
            # PermissionError/FileNotFoundError used to vanish into the log
            # while the button looked like it worked
            self.status.configure(
                text=f"✕ save failed: {type(e).__name__}: {e}", fg=RED)
            return False
        self.status.configure(
            text="✓ saved — hotkeys/scales apply after restart", fg=GREEN)
        return True

    def _save_restart(self):
        if self._save() and self.restart_cb:
            self.restart_cb()


def open_update_dialog(root, tag, asset_url, scale=1.0, up_to_date=False,
                       check_failed=False):
    """'New version available — Update now?' (or a you're-up-to-date /
    couldn't-check note). Applying runs in a thread; when the updater
    takes over, the app quits."""
    import threading
    from advisor.version import __version__
    s = max(1.0, float(scale))
    win = tk.Toplevel(root)
    win.title("D2R Item Advisor — Update")
    win.configure(bg=BG)
    win.resizable(False, False)
    f_base = ("Segoe UI", int(11 * s))
    pad = int(14 * s)
    if check_failed:
        # offline / rate-limited used to render as "you are up to date"
        tk.Label(win, text="✕ Couldn't check for updates (offline or "
                           "GitHub unreachable)", bg=BG, fg=RED,
                 font=f_base, wraplength=int(420 * s)
                 ).pack(padx=pad, pady=(pad, int(6 * s)))
        tk.Button(win, text="OK", command=win.destroy, bg=GOLD,
                  fg="#191307", relief="flat", font=f_base,
                  padx=int(16 * s)).pack(pady=(0, pad))
    elif up_to_date:
        tk.Label(win, text=f"✓ You are up to date (v{__version__})",
                 bg=BG, fg=GREEN, font=f_base
                 ).pack(padx=pad, pady=(pad, int(6 * s)))
        tk.Button(win, text="OK", command=win.destroy, bg=GOLD,
                  fg="#191307", relief="flat", font=f_base,
                  padx=int(16 * s)).pack(pady=(0, pad))
    else:
        tk.Label(win, text=f"Update available: {tag}  (you have "
                           f"v{__version__})", bg=BG, fg=GOLD_HI,
                 font=("Segoe UI", int(12 * s), "bold")
                 ).pack(padx=pad, pady=(pad, int(4 * s)))
        status = tk.Label(win, text="Downloads from GitHub releases; your "
                                    "config and calibration are kept.",
                          bg=BG, fg=DIM, font=("Segoe UI", int(10 * s)),
                          wraplength=int(420 * s), justify="left")
        status.pack(padx=pad)
        btns = tk.Frame(win, bg=BG)
        btns.pack(pady=(int(10 * s), pad))

        def do_update():
            upd.configure(state="disabled", text="updating…")

            def set_status(m, color=DIM):
                root.after(0, lambda: status.configure(
                    text=str(m)[:200], fg=color))

            def fail(msg):
                # a failed download/unpack used to freeze the dialog with
                # the button dead and no message anywhere
                set_status(msg, RED)
                root.after(0, lambda: upd.configure(
                    state="normal", text="Retry update"))

            def work():
                from advisor import updater
                try:
                    ok = updater.apply_update(asset_url, on_step=set_status)
                except Exception as e:
                    fail(f"update failed: {type(e).__name__}: {e} — "
                         f"get it manually: {updater.RELEASES_URL}")
                    return
                if ok:
                    root.after(500, root.quit)  # the updater takes over
                else:
                    fail("update did not start — see the log, or get it "
                         f"manually: {updater.RELEASES_URL}")
            threading.Thread(target=work, daemon=True).start()

        upd = tk.Button(btns, text="Update now", command=do_update,
                        bg=GOLD, fg="#191307", activebackground=GOLD_HI,
                        relief="flat", font=f_base, padx=int(14 * s))
        upd.pack(side="left", padx=(0, int(8 * s)))
        tk.Button(btns, text="Later", command=win.destroy, bg=FIELD,
                  fg=FG, relief="flat", font=f_base,
                  padx=int(14 * s)).pack(side="left")
    win.lift()
    win.attributes("-topmost", True)  # stays above the game
    return win


def open_health_report(root, cfg, scale=1.0):
    """Small themed report window — tray notifications are unreliable
    (Windows can swallow them silently), a window always shows."""
    from advisor.health import health_report, summary_line
    issues = health_report(cfg)
    s = max(1.0, float(scale))
    win = tk.Toplevel(root)
    win.title("D2R Item Advisor — Health")
    win.configure(bg=BG)
    win.resizable(False, False)
    f_base = ("Segoe UI", int(10 * s))
    f_sub = ("Segoe UI", int(9 * s))
    pad = int(12 * s)
    tk.Label(win, text=f"HEALTH — {summary_line(issues)}", bg=BG,
             fg=GOLD_HI, font=("Segoe UI", int(12 * s), "bold")
             ).pack(anchor="w", padx=pad, pady=(pad, int(4 * s)))
    body = tk.Frame(win, bg=PANEL, highlightthickness=1,
                    highlightbackground=LINE)
    body.pack(fill="both", expand=True, padx=pad)
    colors = {"error": RED, "warn": GOLD_HI, "ok": DIM}
    if not issues:
        tk.Label(body, text="✓ everything is configured", bg=PANEL,
                 fg=GREEN, font=f_base, anchor="w"
                 ).pack(fill="x", padx=8, pady=6)
    for lv, title, detail in issues:
        mark = {"error": "✕", "warn": "⚠", "ok": "·"}[lv]
        tk.Label(body, text=f"{mark} {title}\n   {detail}", bg=PANEL,
                 fg=colors[lv], font=f_sub, anchor="w", justify="left",
                 wraplength=int(560 * s)).pack(fill="x", padx=8, pady=3)
    tk.Button(win, text="OK", command=win.destroy, bg=GOLD, fg="#191307",
              activebackground=GOLD_HI, relief="flat", font=f_base,
              padx=int(16 * s)).pack(pady=(int(8 * s), pad))
    win.lift()
    win.attributes("-topmost", True)  # stays above the game
    return win


_open_window = None  # singleton — repeat opens re-focus the existing one


def open_settings(root, cfg, restart_cb=None, scale=1.0):
    global _open_window
    if _open_window is not None:
        try:
            if _open_window.winfo_exists():
                _open_window.deiconify()
                _open_window.lift()
                _open_window.focus_force()
                return _open_window
        except tk.TclError:
            pass
        _open_window = None
    win = Settings(root, cfg, restart_cb=restart_cb, scale=scale)
    win.lift()
    win.attributes("-topmost", True)
    win.after(200, lambda: win.attributes("-topmost", False))
    _open_window = win
    return win
