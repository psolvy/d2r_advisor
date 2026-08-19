"""Season Goals window: runeword targets with live rune checklists.

Runes arrive automatically from scans; the +/- buttons fix miscounts.
Click a goal to see its runes; "I made it" spends the runes.
"""
import tkinter as tk
from tkinter import ttk

from advisor import goals
from advisor.seedfinder_ui import (BG, DIM, FG, FIELD, GOLD, GOLD_HI, GREEN,
                                   LINE, PANEL, RED)

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
        self.s = s = max(1.0, float(scale))
        self.title("D2R Item Advisor — Season Goals")
        self.configure(bg=BG)
        self.resizable(False, False)
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
        self.add_cb = ttk.Combobox(row, values=goals.all_runeword_names(),
                                   width=22, font=self.f_sub)
        self.add_cb.pack(side="left")
        self._btn(row, "Add goal", self._add).pack(side="left", padx=4)
        self._btn(row, "Remove", self._remove).pack(side="left", padx=4)
        self._btn(row, "🏁 I made it", self._made,
                  hot=True).pack(side="right")

        # one-shot stash scan: open the RUNES tab in game, hit the button
        scan = tk.Frame(self, bg=BG)
        scan.grid(row=5, column=0, columnspan=3, sticky="ew", padx=pad,
                  pady=(int(6 * s), pad))
        self._btn(scan, "📷 Scan runes tab", self._scan_tab,
                  hot=True).pack(side="left")
        self._btn(scan, "Set rune grid (3 points)",
                  self._calibrate).pack(side="left", padx=6)
        self.status = tk.Label(scan, text="", bg=BG, fg=DIM,
                               font=self.f_sub)
        self.status.pack(side="left", padx=6)
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
            head = "🏁 " if complete else ""
            self.tv.insert("", "end", iid=goal,
                           text=f" {head}{goal}   ·  {'  '.join(bits)}",
                           tags=("done" if complete else "todo",))
        if keep and self.tv.exists(keep):
            self.tv.selection_set(keep)
        self._pick()

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

    def _add(self):
        name = self.add_cb.get().strip()
        if not name:
            return
        st = goals.load_state()
        if name not in st["goals"] and name in goals.all_runeword_names():
            st["goals"].append(name)
            goals.save_state(st)
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
            goals.mark_made(sel[0])
            self.refresh()

    # -------------------------------------------------- stash-tab scanning

    def _calibrate(self):
        """3 hovered points pin the whole rune lattice: El cell, the LAST
        cell of the FIRST row, then the LAST rune cell (Zod)."""
        from advisor.autoclicker import get_cursor_pos, load_calib, save_calib
        prompts = ["hover the EL cell (first rune)…",
                   "hover the LAST cell of the FIRST row…",
                   "hover the LAST rune cell (Zod)…"]
        points = []

        def capture(step, countdown):
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
                calib["runetab"] = points
                save_calib(calib)
                self.status.configure(text="✓ rune grid saved", fg=GREEN)

        capture(0, 4)

    def _scan_tab(self):
        from advisor.autoclicker import load_calib
        calib = load_calib()
        pts = calib.get("runetab")
        if not pts or len(pts) != 6:
            self.status.configure(
                text="set the rune grid first (3 points)", fg=RED)
            return

        def go(countdown):
            if countdown > 0:
                self.status.configure(
                    text=f"open the stash RUNES tab — scanning in "
                         f"{countdown}", fg=GOLD_HI)
                self.after(1000, lambda: go(countdown - 1))
                return
            self.status.configure(text="scanning…", fg=GOLD_HI)
            self.update_idletasks()
            try:
                import mss
                import numpy as np
                from advisor.app import load_config, resolve_tesseract
                from advisor.rune_tab import scan_rune_tab
                with mss.MSS() as s:
                    mon = next((m for m in s.monitors[1:]
                                if m["left"] <= pts[0] < m["left"] + m["width"]
                                and m["top"] <= pts[1] < m["top"] + m["height"]),
                               s.monitors[0])
                    img = np.array(s.grab(mon))[:, :, :3]
                    rect = (mon["left"], mon["top"],
                            mon["width"], mon["height"])
                tess = resolve_tesseract(self.cfg or load_config())
                counts = scan_rune_tab(img, pts, screen_rect=rect,
                                       tesseract_cmd=tess)
            except Exception as e:
                self.status.configure(text=f"scan failed: {e}", fg=RED)
                return
            if not counts:
                self.status.configure(text="scan failed: bad grid points",
                                      fg=RED)
                return
            goals.set_counts(counts)
            total = sum(counts.values())
            kinds = sum(1 for n in counts.values() if n > 0)
            self.status.configure(
                text=f"✓ {total} runes ({kinds} kinds) — counters set",
                fg=GREEN)
            self.refresh()

        go(4)
