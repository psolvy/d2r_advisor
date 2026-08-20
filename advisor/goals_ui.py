"""Season Goals window: runeword targets with live rune checklists.

Runes arrive automatically from scans; the +/- buttons fix miscounts.
Click a goal to see its runes; "I made it" spends the runes.
"""
import tkinter as tk
from tkinter import ttk

from advisor import goals
from advisor.seedfinder_ui import (BG, DIM, FG, FIELD, GOLD, GOLD_HI, GREEN,
                                   LINE, PANEL, RED, SearchDropdown)

_open_window = None


def open_goals(root, scale=1.0, cfg=None):
    global _open_window
    if _open_window is not None:
        try:
            if _open_window.winfo_exists():
                _open_window.refresh()
                _open_window.deiconify()
                _open_window.lift()
                return _open_window
        except tk.TclError:
            pass
        _open_window = None
    _open_window = GoalsWindow(root, scale, cfg)
    return _open_window


class GoalsWindow(tk.Toplevel):
    def __init__(self, root, scale=1.0, cfg=None):
        super().__init__(root)
        self.cfg = cfg or {}
        self._guard_hold = None
        # closing the window mid-countdown must free the capture guard,
        # or every later scan reports "busy" until an app restart
        self.bind("<Destroy>", self._drop_guard, add="+")
        self.s = s = max(1.0, float(scale))
        self.title("D2R Item Advisor — Season Goals")
        self.configure(bg=BG)
        self.resizable(False, False)
        self.attributes("-topmost", True)  # stay above the game
        self.f_base = ("Segoe UI", int(11 * s))
        self.f_sub = ("Segoe UI", int(10 * s))
        pad = int(12 * s)

        tk.Label(self, text="SEASON GOALS", bg=BG, fg=GOLD_HI,
                 font=("Segoe UI", int(13 * s), "bold")
                 ).grid(row=0, column=0, columnspan=3, sticky="w",
                        padx=pad, pady=(pad, int(4 * s)))
        tk.Label(self, text="runes are collected from your scans "
                            "automatically; use +/− to correct counts",
                 bg=BG, fg=DIM, font=self.f_sub
                 ).grid(row=1, column=0, columnspan=3, sticky="w", padx=pad)

        st = ttk.Style(self)
        st.theme_use("clam")
        st.configure("SG.Treeview", background=FIELD, fieldbackground=FIELD,
                     foreground=FG, borderwidth=0, font=self.f_base,
                     rowheight=int(30 * s))
        st.map("SG.Treeview", background=[("selected", GOLD)],
               foreground=[("selected", BG)])
        # themed combobox — the raw white system one looked alien here
        st.configure("SG.TCombobox", fieldbackground=FIELD, background=PANEL,
                     foreground=FG, arrowcolor=GOLD, bordercolor=LINE,
                     lightcolor=FIELD, darkcolor=FIELD)
        st.map("SG.TCombobox",
               fieldbackground=[("readonly", FIELD)],
               selectbackground=[("!disabled", FIELD)],
               selectforeground=[("!disabled", FG)],
               foreground=[("readonly", FG)])
        self.option_add("*TCombobox*Listbox.background", FIELD)
        self.option_add("*TCombobox*Listbox.foreground", FG)
        self.option_add("*TCombobox*Listbox.selectBackground", GOLD)
        self.option_add("*TCombobox*Listbox.selectForeground", BG)
        self.tv = ttk.Treeview(self, show="tree", style="SG.Treeview",
                               selectmode="browse", height=8)
        self.tv.grid(row=2, column=0, columnspan=3, sticky="ew",
                     padx=pad, pady=(int(6 * s), 0))
        self.tv.tag_configure("done", foreground=GREEN)
        self.tv.tag_configure("todo", foreground=FG)
        self.tv.bind("<<TreeviewSelect>>", self._pick)

        # rune adjust row for the selected goal
        self.rune_row = tk.Frame(self, bg=BG)
        self.rune_row.grid(row=3, column=0, columnspan=3, sticky="w",
                           padx=pad, pady=(int(6 * s), 0))

        row = tk.Frame(self, bg=BG)
        row.grid(row=4, column=0, columnspan=3, sticky="ew", padx=pad,
                 pady=(int(8 * s), 0))
        # type-to-search picker (same component as the Seed Finder)
        self.add_var = tk.StringVar()
        self.add_entry = tk.Entry(row, textvariable=self.add_var, width=24,
                                  bg=FIELD, fg=FG, insertbackground=GOLD,
                                  relief="flat", font=self.f_sub,
                                  highlightthickness=1,
                                  highlightbackground=LINE,
                                  highlightcolor=GOLD)
        self.add_entry.pack(side="left", ipady=int(3 * s))
        self._add_dd = SearchDropdown(
            self, self.add_entry, self.add_var,
            lambda needle: [(n, None) for n in goals.all_runeword_names()
                            if needle in n.lower()],
            self._add_pick, min_width=int(260 * s))
        self._btn(row, "Add goal", self._add).pack(side="left", padx=4)
        self._btn(row, "Remove", self._remove).pack(side="left", padx=4)
        self._btn(row, "✔ I made it", self._made,
                  hot=True).pack(side="right")

        # one-shot stash scans: open the tab in game, hit the button
        scan = tk.Frame(self, bg=BG)
        scan.grid(row=5, column=0, columnspan=3, sticky="ew", padx=pad,
                  pady=(int(6 * s), 0))
        self._btn(scan, "📷 Scan runes tab", self._scan_runes,
                  hot=True).pack(side="left")
        self._btn(scan, "Set rune grid",
                  lambda: self._calibrate("runetab", "rune")
                  ).pack(side="left", padx=(4, 12))
        self._btn(scan, "📷 Scan gems tab", self._scan_gems,
                  hot=True).pack(side="left")
        self._btn(scan, "Set gems grid",
                  lambda: self._calibrate("gemstab", "gem")
                  ).pack(side="left", padx=4)
        self.status = tk.Label(self, text="", bg=BG, fg=DIM,
                               font=self.f_sub, anchor="w")
        self.status.grid(row=6, column=0, columnspan=3, sticky="ew",
                         padx=pad)

        # craft stock from the scanned gems
        self.craft_box = tk.Frame(self, bg=PANEL, highlightthickness=1,
                                  highlightbackground=LINE)
        self.craft_box.grid(row=7, column=0, columnspan=3, sticky="ew",
                            padx=pad, pady=(int(6 * s), 0))

        # everything makeable RIGHT NOW from the pools
        self.make_tv = ttk.Treeview(self, show="tree", style="SG.Treeview",
                                    selectmode="browse", height=6)
        self.make_tv.grid(row=8, column=0, columnspan=3, sticky="ew",
                          padx=pad, pady=(int(6 * s), pad))
        self.make_tv.tag_configure("hot", foreground=GREEN)
        self.make_tv.tag_configure("dim", foreground=DIM)
        self.refresh()

    def _btn(self, parent, text, cmd, hot=False):
        return tk.Button(parent, text=text, command=cmd,
                         bg=GOLD if hot else FIELD,
                         fg="#191307" if hot else FG,
                         activebackground=GOLD_HI, relief="flat",
                         font=self.f_sub, padx=int(10 * self.s))

    def refresh(self):
        sel = self.tv.selection()
        keep = sel[0] if sel else None
        self.tv.delete(*self.tv.get_children())
        for goal, rows, complete in goals.goal_progress():
            bits = []
            for r, n, h in rows:
                mark = "✓" if h >= n else "✗"
                bits.append(f"{r}{'×%d' % n if n > 1 else ''}{mark}")
            head = "★ " if complete else ""
            self.tv.insert("", "end", iid=goal,
                           text=f" {head}{goal}   ·  {'  '.join(bits)}",
                           tags=("done" if complete else "todo",))
        if keep and self.tv.exists(keep):
            self.tv.selection_set(keep)
        self._pick()
        allow_up = bool(self.cfg.get("count_upcube"))
        if hasattr(self, "craft_box"):
            for w in self.craft_box.winfo_children():
                w.destroy()
            tk.Label(self.craft_box, text="CRAFT STOCK (from the gems tab)"
                     + (" — counting cube-ups" if allow_up else ""),
                     bg=PANEL, fg=GOLD, font=self.f_sub
                     ).pack(anchor="w", padx=8, pady=(4, 0))
            for text, ok in goals.craft_lines(allow_up):
                tk.Label(self.craft_box, text=("✓ " if ok else "· ") + text,
                         bg=PANEL, fg=GREEN if ok else DIM,
                         font=self.f_sub, anchor="w"
                         ).pack(fill="x", padx=8, pady=1)
        if hasattr(self, "make_tv"):
            tv = self.make_tv
            tv.delete(*tv.get_children())
            rows = goals.craftable_runewords(allow_up)
            head = ("RUNEWORDS YOU CAN MAKE NOW"
                    + (" (incl. cube-upgrading)" if allow_up else "")
                    + " — enable cube-ups in Settings" * (not allow_up))
            tv.insert("", "end", iid="_head", text=f" {head}", tags=("dim",))
            if not rows:
                tv.insert("", "end", text="   nothing yet — scan the "
                          "runes/gems tabs or farm on!", tags=("dim",))
            for name, n, runes in rows:
                tv.insert("", "end",
                          text=f"   {name} ×{n}   ·  {runes}",
                          tags=("hot",))

    def _pick(self, _ev=None):
        for w in self.rune_row.winfo_children():
            w.destroy()
        sel = self.tv.selection()
        if not sel:
            return
        goal = sel[0]
        rows = next((r for g, r, _c in goals.goal_progress() if g == goal),
                    [])
        for rune, need, have in rows:
            cell = tk.Frame(self.rune_row, bg=PANEL, highlightthickness=1,
                            highlightbackground=LINE)
            cell.pack(side="left", padx=3)
            color = GREEN if have >= need else RED
            tk.Label(cell, text=f"{rune} {have}/{need}", bg=PANEL, fg=color,
                     font=self.f_base).pack(side="left", padx=(6, 2))
            for txt, d in (("−", -1), ("+", +1)):
                tk.Button(cell, text=txt, bg=FIELD, fg=FG, relief="flat",
                          font=self.f_sub, padx=4,
                          command=lambda r=rune, dd=d: (
                              goals.adjust_rune(r, dd), self.refresh())
                          ).pack(side="left", padx=1, pady=2)

    def _add_pick(self, name):
        self.add_var.set(name)
        self._add_dd.show(False)
        self._add()

    def _add(self):
        name = self.add_var.get().strip()
        if not name:
            return
        st = goals.load_state()
        if name not in st["goals"] and name in goals.all_runeword_names():
            st["goals"].append(name)
            goals.save_state(st)
            self.add_var.set("")
        self.refresh()

    def _remove(self):
        sel = self.tv.selection()
        if not sel:
            return
        st = goals.load_state()
        if sel[0] in st["goals"]:
            st["goals"].remove(sel[0])
            goals.save_state(st)
        self.refresh()

    def _made(self):
        sel = self.tv.selection()
        if sel:
            _st, ok, msg = goals.mark_made(sel[0])
            if not ok:
                self.status.configure(text=f"✕ {sel[0]}: {msg}", fg=RED)
                return
            self.status.configure(text=f"✓ {sel[0]} made — runes spent",
                                  fg=GREEN)
            self.refresh()

    # -------------------------------------------------- stash-tab scanning

    def _guard_acquire(self, what):
        from advisor import capture_guard
        if not capture_guard.acquire(what):
            self.status.configure(
                text=f"busy: {capture_guard.busy_with()} is running", fg=RED)
            return False
        self._guard_hold = what
        return True

    def _guard_release(self):
        from advisor import capture_guard
        if self._guard_hold:
            capture_guard.release(self._guard_hold)
            self._guard_hold = None

    def _drop_guard(self, event=None):
        if event is None or event.widget is self:
            self._guard_release()

    def _calibrate(self, key, what):
        """4 hovered points pin a whole tab lattice: first cell, END of the
        top row, the cell BELOW the first, then the LAST cell overall."""
        if not self._guard_acquire(f"{what} grid calibration"):
            return
        from advisor.autoclicker import get_cursor_pos, load_calib, save_calib
        if what == "rune":
            prompts = ["hover EL (first rune, top-left)…",
                       "hover the LAST rune of the TOP row…",
                       "hover the rune DIRECTLY BELOW El (row 2 start)…",
                       "hover ZOD (the very last rune)…"]
        else:
            prompts = ["hover Chipped DIAMOND (top-left gem)…",
                       "hover Chipped SKULL (top-right gem)…",
                       "hover Flawed DIAMOND (directly below the first)…",
                       "hover Perfect SKULL (bottom-right gem)…"]
        points = []

        def capture(step, countdown):
            if not self.winfo_exists():
                self._guard_release()
                return
            if countdown > 0:
                self.status.configure(
                    text=f"{prompts[step]}  {countdown}", fg=GOLD_HI)
                self.after(1000, lambda: capture(step, countdown - 1))
                return
            points.extend(get_cursor_pos())
            if step + 1 < len(prompts):
                capture(step + 1, 4)
            else:
                calib = load_calib()
                calib[key] = points
                save_calib(calib)
                self.status.configure(text=f"✓ {what} grid saved", fg=GREEN)
                self._guard_release()

        capture(0, 4)

    def _scan_counted(self, key, names, apply_fn, what, band=False,
                      pool_key="runes"):
        if not self._guard_acquire(f"{what} tab scan"):
            return
        from advisor.autoclicker import load_calib
        calib = load_calib()
        pts = calib.get(key)
        if not pts or len(pts) != 8:
            self._guard_release()
            self.status.configure(
                text=f"set the {what} grid first (4 points)", fg=RED)
            return

        def go(countdown):
            if not self.winfo_exists():
                self._guard_release()
                return
            if countdown > 0:
                self.status.configure(
                    text=f"open the stash {what.upper()} tab — scanning in "
                         f"{countdown}", fg=GOLD_HI)
                self.after(1000, lambda: go(countdown - 1))
                return
            self.status.configure(text="scanning…", fg=GOLD_HI)
            self.update_idletasks()
            try:
                import mss
                import numpy as np
                from advisor.app import load_config, resolve_tesseract
                from advisor.rune_tab import scan_counted_tab
                with mss.MSS() as s:
                    mon = next((m for m in s.monitors[1:]
                                if m["left"] <= pts[0] < m["left"] + m["width"]
                                and m["top"] <= pts[1] < m["top"] + m["height"]),
                               s.monitors[0])
                    img = np.array(s.grab(mon))[:, :, :3]
                    rect = (mon["left"], mon["top"],
                            mon["width"], mon["height"])
                tess = resolve_tesseract(self.cfg or load_config())
                from datetime import datetime
                from pathlib import Path
                dbg_dir = Path(__file__).resolve().parents[1] / "debug"
                dbg_dir.mkdir(exist_ok=True)
                dbg = dbg_dir / (datetime.now().strftime("%H%M%S")
                                 + f"_tabscan_{what}.png")
                counts = scan_counted_tab(img, pts, names,
                                          screen_rect=rect,
                                          tesseract_cmd=tess,
                                          debug_out=dbg, band=band)
            except Exception as e:
                self._guard_release()
                self.status.configure(text=f"scan failed: {e}", fg=RED)
                return
            if not counts:
                self._guard_release()
                self.status.configure(text="scan failed: bad grid points",
                                      fg=RED)
                return
            self._guard_release()
            total = sum(counts.values())
            kinds = sum(1 for n in counts.values() if n > 0)
            # a scan REPLACES the whole pool — show the diff and confirm
            # before overwriting hand-curated counts
            cur = goals.load_state().get(pool_key) or {}
            changes = []
            for name in sorted(set(cur) | set(counts)):
                old, new = cur.get(name, 0), counts.get(name, 0)
                if old != new:
                    changes.append(f"{name} {old}→{new}")
            if cur and changes:
                from tkinter import messagebox
                shown = ", ".join(changes[:8]) + \
                    (f" … +{len(changes) - 8} more" if len(changes) > 8
                     else "")
                if not messagebox.askyesno(
                        "Apply scan?",
                        f"{total} {what}s ({kinds} kinds) scanned.\n\n"
                        f"Changes: {shown}\n\nReplace the current "
                        f"{what} counters?", parent=self):
                    self.status.configure(text="scan discarded", fg=GOLD_HI)
                    return
            apply_fn(counts)
            self.status.configure(
                text=f"✓ {total} {what}s ({kinds} kinds) — counters set",
                fg=GREEN)
            self.refresh()

        go(4)

    def _scan_runes(self):
        from advisor.knowledge import RUNE_ORDER
        self._scan_counted("runetab", RUNE_ORDER, goals.set_counts, "rune")

    def _scan_gems(self):
        from advisor.rune_tab import GEM_ORDER
        self._scan_counted("gemstab", GEM_ORDER, goals.set_gem_counts,
                           "gem", band=True, pool_key="gems")
