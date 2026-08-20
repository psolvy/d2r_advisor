"""Gamble Seed Finder + buy planner — the full DBM toolchain, native.

Modern dark UI with the site-style visual store grid: the offer shows as
item icons on a 10x10 grid; click any cell to pick/replace/remove an item
manually (searchable picker), or let F10 fill everything automatically
(icon recognition, no calibration needed — the grid auto-locates).

Find seed -> quality-colored refresh predictions (which slots become
UNIQUE / SET / rare) -> Plan buys -> Execute the plan in game with the
auto-clicker. Engine, planner and vendor fill are validated bit-exact
against the DBM site's workers. Window size scales with `seedfinder_scale`
(falls back to `ui_scale`) in config.yaml and is freely resizable.
"""
import base64
import queue
import threading
import tkinter as tk
import tkinter.font as tkfont
from pathlib import Path
from tkinter import ttk

from advisor.autoclicker import (calib_ok, execute_plan, get_cursor_pos,
                                 load_calib, save_calib)
from advisor.gamble_plan import plan_buys
from advisor.gamble_seed import (Ctx, Q_RARE, Q_SET, Q_UNIQUE, QUALITY_NAMES,
                                 find_offsets, game_seed_to_store, item_index,
                                 items, refresh_chain_full,
                                 search_full)

ROOT = Path(__file__).resolve().parents[1]

# ------------------------------------------------------------------ palette
BG = "#141009"
PANEL = "#1e1710"
FIELD = "#2b2114"
LINE = "#3a2d1c"
FG = "#eee6d4"
DIM = "#94886f"
GOLD = "#c7b377"
GOLD_HI = "#ffd94d"
GREEN = "#3ddc6a"
SETC = "#00e050"
RARE = "#ffff64"
RED = "#e05545"
BLUE = "#6db3f2"

# Human platform names -> pool order (the site's own mapping: PC and Xbox
# use msvc, PlayStation the freebsd pool, Switch musl; the rest are expert
# variants for unusual builds)
PLATFORM_CHOICES = [
    ("PC", "msvc"),
    ("PlayStation", "freebsd"),
    ("Xbox", "msvc"),
    ("Switch", "musl"),
    ("other: gcc", "gcc"),
    ("other: stable", "stable"),
    ("other: msvc-std", "msvc-std"),
    ("other: reverse", "reverse"),
]
# newest first, latest is the default
VERSION_CHOICES = [
    ("RoW (latest)", "row"),
    ("D2R", "d2r"),
    ("D2 Classic", "d2"),
]
NPC_CHOICES = [
    ("Gheed (Act 1)", "gheed"),
    ("Elzix (Act 2)", "elzix"),
    ("Alkor (Act 3)", "alkor"),
    ("Jamella (Act 4)", "jamella"),
    ("Anya (Act 5)", "anya"),
]
DIFFICULTIES = ["Normal", "Nightmare", "Hell"]
RARITY_CHOICES = [("set/unique/rare (default)", None),
                  ("Unique only", Q_UNIQUE), ("Set only", Q_SET),
                  ("Rare only", Q_RARE), ("Any quality", -1)]
TIER_CHOICES = [("any tier", -1), ("normal", 0),
                ("exceptional", 1), ("elite", 2)]

_open_window = None  # singleton — the hotkey re-focuses an existing window


def _equiv_safe():
    """Identical-icon equivalence for the search; empty when icons absent."""
    try:
        from advisor.gamble_vision import icon_equiv
        return icon_equiv() or None
    except Exception:
        return None


def map_ocr_name(name):
    """Map an OCR/gamble-db base name to an engine item index (fuzzy) —
    only against items that can actually appear in a gamble offer."""
    from advisor.gamble_seed import poolable_codes
    pool = poolable_codes()
    idx = item_index(name)
    if idx >= 0 and items()[idx]["code"] in pool:
        return idx
    try:
        from rapidfuzz import fuzz, process
    except ImportError:
        return -1
    engine_names = [it["name"] for it in items() if it["code"] in pool]
    m = process.extractOne(name, engine_names, scorer=fuzz.ratio,
                           processor=str.lower, score_cutoff=80)
    return item_index(m[0]) if m else -1


_GDB = None


def _gamble_db():
    """Repository lookups for predicting WHICH unique/set a gamble rolls:
    base family -> candidates with alvl, item name -> real base, base ->
    tier. Loaded once."""
    global _GDB
    if _GDB is None:
        import json
        rep = ROOT / "d2rlootreader" / "repository"

        def load(name):
            with open(rep / name, encoding="utf-8") as f:
                return json.load(f)
        _GDB = {"gamble": load("gamble.json"), "u2b": load("uniques.json"),
                "s2b": load("set.json"), "bases": load("bases.json")}
        for src, key in (("u2b", "rev_u"), ("s2b", "rev_s")):
            rev = {}
            for name, base in _GDB[src].items():
                rev.setdefault(base, []).append(name)
            _GDB[key] = rev
    return _GDB


class SearchDropdown:
    """Reusable type-to-search dropdown: entry + overlay Treeview with item
    icons. The Treeview is parented to the WINDOW and shown with place()
    under the entry (a child of a short frame gets clipped; pack would
    shift the layout). get_rows(needle) -> [(name, PhotoImage|None)];
    on_pick(name) fires on click/Enter. Hover selects, Esc clears+hides."""

    def __init__(self, win, entry, var, get_rows, on_pick, min_width=0):
        self.win, self.entry, self.var = win, entry, var
        self.get_rows, self.on_pick = get_rows, on_pick
        self.min_width = min_width
        self.tv = ttk.Treeview(win, show="tree", style="SF.Treeview",
                               selectmode="browse", height=5)
        self.rows = {}
        self.visible = False
        self._picking = False
        var.trace_add("write", self.refill)
        self.tv.bind("<Motion>", self._hover)
        self.tv.bind("<ButtonRelease-1>", self.pick)
        self.tv.bind("<Return>", self.pick)
        entry.bind("<Return>", self.pick)
        entry.bind("<Down>", lambda _e: self.tv.focus_set())
        entry.bind("<FocusIn>", lambda _e: self.show(True))
        entry.bind("<Button-1>", lambda _e: self.show(True), add=True)
        for wdg in (entry, self.tv):
            wdg.bind("<FocusOut>",
                     lambda _e: win.after(150, self._maybe_hide))
        entry.bind("<Escape>", lambda _e: (var.set(""), self.show(False)))
        # click ANYWHERE else in the window closes the list (a Toplevel
        # binding fires for every descendant widget)
        win.bind("<Button-1>", self._click_away, add=True)
        self.refill()

    def show(self, show):
        if show and not self.visible:
            kw = {"x": 0, "rely": 1.0, "y": 3}
            w = max(self.entry.winfo_width(), self.min_width)
            if w > 1:
                kw["width"] = w
            else:
                kw["relwidth"] = 1.0
            self.tv.place(in_=self.entry, **kw)
            self.tv.lift()
            self.visible = True
        elif not show and self.visible:
            self.tv.place_forget()
            self.visible = False

    def _maybe_hide(self):
        try:
            focus = self.win.focus_get()
        except (KeyError, tk.TclError):
            focus = None
        if focus not in (self.entry, self.tv):
            self.show(False)

    def _click_away(self, ev):
        if self.visible and ev.widget not in (self.entry, self.tv):
            self.show(False)

    def refill(self, *_):
        needle = self.var.get().strip().lower()
        rows = self.get_rows(needle)
        # the field holds an already-picked value -> reopening should offer
        # the FULL list again (combobox behavior), not a single stale row
        if len(rows) == 1 and rows[0][0].lower() == needle:
            rows = self.get_rows("")
        tv = self.tv
        tv.delete(*tv.get_children())
        self.rows.clear()
        for name, img in rows:
            kw = {"image": img} if img is not None else {}
            iid = tv.insert("", "end", text=" " + name, **kw)
            self.rows[iid] = name
        # shrink to content — a 5-row box around 1 row is dead space
        tv.configure(height=max(1, min(5, len(rows))))
        kids = tv.get_children()
        if kids:
            tv.selection_set(kids[0])
        # typing must (re)open the list — but a programmatic set from a
        # pick handler must not undo the hide it just did
        if not self._picking:
            try:
                if self.win.focus_get() is self.entry:
                    self.show(True)
            except (KeyError, tk.TclError):
                pass

    def _hover(self, ev):
        iid = self.tv.identify_row(ev.y)
        if iid:
            self.tv.selection_set(iid)

    def pick(self, *_):
        sel = self.tv.selection()
        if not sel or sel[0] not in self.rows:
            return
        self._picking = True
        try:
            self.on_pick(self.rows[sel[0]])
        finally:
            self._picking = False


class SeedFinder(tk.Toplevel):

    @staticmethod
    def _label_of(choices, value, default_label):
        """Accept a config value as either the code or the label."""
        v = str(value).strip().lower()
        for lbl, code in choices:
            if v in (lbl.lower(), str(code).lower()):
                return lbl
        return default_label

    def __init__(self, root, char_level=85, get_last_offer=None,
                 get_last_entries=None, ui_scale=1.0, cfg=None):
        super().__init__(root)
        self.s = max(0.8, min(2.5, float(ui_scale or 1.0)))
        s = self.s
        self.title("Gamble Seed Finder — D2R Item Advisor")
        self.configure(bg=BG)
        # a provisional size — replaced after _build by the real required
        # size of the content (clamped to the screen)
        self.geometry(f"{int(1020 * s)}x{int(860 * s)}")
        self.attributes("-topmost", True)
        self.stop_event = threading.Event()
        # closing mid-search must stop the node/pool burn — without this
        # the workers kept every core busy until the app exited
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.msgs = queue.Queue()
        self.items = items()
        from advisor.gamble_seed import poolable_codes
        pool = poolable_codes()
        self.names = sorted(it["name"] for it in self.items
                            if it["code"] in pool)
        self.get_last_offer = get_last_offer
        self.get_last_entries = get_last_entries
        self.searching = False
        self._last_fill_key = None
        self.plans = []
        self.calib = load_calib()
        self.slots = []          # placed items: {"idx", "x", "y"}
        self.unplaced = []       # item idxs without a grid position
        self._photos = {}
        self._picker = None
        self._char_level = char_level
        # defaults for every control come from config.yaml `seedfinder:`
        sf = dict((cfg or {}).get("seedfinder") or {})
        self.sf = {
            "level": sf.get("level") or char_level or 85,
            "platform": self._label_of(PLATFORM_CHOICES,
                                       sf.get("platform", "PC"), "PC"),
            "version": self._label_of(VERSION_CHOICES,
                                      sf.get("version", "row"),
                                      VERSION_CHOICES[0][0]),
            "npc": self._label_of(NPC_CHOICES, sf.get("npc", "gheed"),
                                  NPC_CHOICES[0][0]),
            "difficulty": next((d for d in DIFFICULTIES
                                if d.lower() == str(sf.get("difficulty",
                                                           "Hell")).lower()),
                               "Hell"),
            "depth": sf.get("depth", 5000),
            "shift_buys": sf.get("shift_buys", 10),
            "refreshes": sf.get("refreshes", 30),
            "max_offset": sf.get("max_offset", 2000000),
            "click_delay": sf.get("click_delay", 0.8),
            "execute_delay": sf.get("execute_delay", 5),
            "target": str(sf.get("target") or "").strip().replace("(any)", ""),
            "target_rarity": self._label_of(
                RARITY_CHOICES + [("set/unique/rare (default)", "default"),
                                  ("Unique only", "unique"),
                                  ("Set only", "set"), ("Rare only", "rare"),
                                  ("Any quality", "any")],
                sf.get("target_rarity", "default"), RARITY_CHOICES[0][0]),
            "target_tier": self._label_of(
                TIER_CHOICES + [("any tier", "any")],
                sf.get("target_tier", "any"), TIER_CHOICES[0][0]),
        }

        self._fonts()
        self._styles()
        self._build()
        self._place_defaults()
        if get_last_offer or get_last_entries:
            self.fill_from_scan(quiet=True)
        self.redraw()
        # size the window to what the content actually needs (clamped to
        # the screen) — fixed guesses clipped it at larger scales
        self.update_idletasks()
        req_w = self.winfo_reqwidth() + 8
        req_h = self.winfo_reqheight() + 8
        max_w = int(self.winfo_screenwidth() * 0.94)
        max_h = int(self.winfo_screenheight() * 0.90)
        # how much the WHOLE window must shrink to fit this screen —
        # open_seed_finder reopens at a smaller scale when < 1 (clamping
        # alone just clipped the bottom on short/wide monitors)
        self.fit_factor = min(1.0, max_w / req_w, max_h / req_h)
        w, h = min(req_w, max_w), min(req_h, max_h)
        self.geometry(f"{w}x{h}")
        self.minsize(min(w, 900), min(h, 640))
        threading.Thread(target=self._prewarm, daemon=True).start()
        self.after(150, self._poll)

    def _prewarm(self):
        try:
            from advisor.gamble_seed import prewarm_pool
            n = prewarm_pool()
            self.msgs.put(("step", f"  {n} search workers warmed up — "
                                   "Find seed starts instantly"))
        except Exception:
            pass

    # ------------------------------------------------------------- theming

    def _fonts(self):
        s = self.s
        self.f_base = tkfont.Font(family="Segoe UI", size=max(9, int(10 * s)))
        self.f_bold = tkfont.Font(family="Segoe UI Semibold", size=max(9, int(10 * s)))
        self.f_head = tkfont.Font(family="Segoe UI Semibold", size=int(16 * s))
        self.f_sub = tkfont.Font(family="Segoe UI", size=max(8, int(9 * s)))
        self.f_mono = tkfont.Font(family="Consolas", size=max(9, int(10 * s)))

    def _styles(self):
        st = ttk.Style(self)
        try:
            st.theme_use("clam")
        except tk.TclError:
            pass
        st.configure("SF.TCombobox", fieldbackground=FIELD, background=PANEL,
                     foreground=FG, arrowcolor=GOLD, bordercolor=LINE,
                     lightcolor=PANEL, darkcolor=PANEL, selectbackground=FIELD,
                     selectforeground=FG, padding=(6, 4, 2, 4),
                     arrowsize=int(16 * self.s))
        st.map("SF.TCombobox", fieldbackground=[("readonly", FIELD)],
               foreground=[("readonly", FG)])
        st.configure("SF.Horizontal.TProgressbar", troughcolor=FIELD,
                     background=GOLD, bordercolor=LINE, lightcolor=GOLD,
                     darkcolor=GOLD)
        st.configure("SF.Treeview", background=FIELD, fieldbackground=FIELD,
                     foreground=FG, borderwidth=0,
                     font=self.f_base,  # default system font ignores scale
                     rowheight=int(30 * self.s))
        st.map("SF.Treeview", background=[("selected", GOLD)],
               foreground=[("selected", BG)])
        self.option_add("*TCombobox*Listbox.background", FIELD)
        self.option_add("*TCombobox*Listbox.foreground", FG)
        self.option_add("*TCombobox*Listbox.selectBackground", GOLD)
        self.option_add("*TCombobox*Listbox.selectForeground", BG)
        self.option_add("*TCombobox*Listbox.font", self.f_base)

    def _btn(self, parent, text, cmd, kind="normal", **kw):
        colors = {"primary": (GOLD, "#191307", GOLD_HI),
                  "normal": ("#332817", FG, "#463620"),
                  "danger": ("#5a2b22", FG, "#7c382b")}
        bg, fg, hover = colors.get(kind, colors["normal"])
        b = tk.Button(parent, text=text, command=cmd, bg=bg, fg=fg,
                      activebackground=hover, activeforeground=fg,
                      relief="flat", bd=0, font=self.f_bold,
                      padx=int(10 * self.s), pady=int(4 * self.s),
                      cursor="hand2", **kw)
        b.bind("<Enter>", lambda e: b.configure(bg=hover))
        b.bind("<Leave>", lambda e: b.configure(bg=bg))
        return b

    def _entry(self, parent, width, textvariable=None):
        return tk.Entry(parent, width=width, textvariable=textvariable,
                        bg=FIELD, fg=FG, insertbackground=GOLD,
                        relief="flat", font=self.f_base,
                        highlightthickness=1, highlightbackground=LINE,
                        highlightcolor=GOLD)

    def _spin(self, parent, lo, hi, val, width, increment=None):
        kw = {"increment": increment} if increment else {}
        # +1 char of air so digits never hide behind the arrow buttons
        sp = tk.Spinbox(parent, from_=lo, to=hi, width=width + 1,
                        bg=FIELD, fg=FG,
                        buttonbackground=PANEL, insertbackground=GOLD,
                        relief="flat", font=self.f_base,
                        highlightthickness=1, highlightbackground=LINE,
                        highlightcolor=GOLD, **kw)
        sp.delete(0, "end")
        sp.insert(0, val)
        return sp

    def _combo(self, parent, values, default, width):
        cb = ttk.Combobox(parent, values=values, width=width,
                          state="readonly", style="SF.TCombobox",
                          font=self.f_base)
        cb.set(default)
        cb.bind("<<ComboboxSelected>>",
                lambda _e: cb.selection_clear(), add=True)
        cb.bind("<FocusOut>", lambda _e: cb.selection_clear(), add=True)
        return cb

    def _lbl(self, parent, text, fg=DIM, font=None):
        return tk.Label(parent, text=text, bg=parent["bg"], fg=fg,
                        font=font or self.f_base)

    # ------------------------------------------------------------- layout

    def _build(self):
        s = self.s
        pad = int(10 * s)
        self.columnconfigure(0, weight=0)
        self.columnconfigure(1, weight=1)
        self.rowconfigure(2, weight=1)

        # header
        head = tk.Frame(self, bg=BG)
        head.grid(row=0, column=0, columnspan=2, sticky="ew",
                  padx=pad, pady=(pad, 0))
        tk.Label(head, text="GAMBLE SEED FINDER", bg=BG, fg=GOLD,
                 font=self.f_head).pack(side="left")
        tk.Label(head, text="  DBM simulator, native · bit-exact · F10 reads the icons",
                 bg=BG, fg=DIM, font=self.f_sub).pack(side="left", pady=(int(6 * s), 0))

        # store setup
        setup = tk.Frame(self, bg=BG)
        setup.grid(row=1, column=0, columnspan=2, sticky="ew",
                   padx=pad, pady=(int(6 * s), 0))
        self._lbl(setup, "Level").pack(side="left")
        self.level = self._spin(setup, 1, 99, str(self.sf["level"]), 4)
        self.level.pack(side="left", padx=(3, int(8 * s)))
        self._lbl(setup, "Platform").pack(side="left")
        self.platform = self._combo(setup, [p[0] for p in PLATFORM_CHOICES],
                                    self.sf["platform"], 11)
        self.platform.pack(side="left", padx=(3, int(8 * s)))
        self._lbl(setup, "Version").pack(side="left")
        self.version = self._combo(setup, [v[0] for v in VERSION_CHOICES],
                                   self.sf["version"], 12)
        self.version.pack(side="left", padx=(3, int(8 * s)))
        self._lbl(setup, "NPC").pack(side="left")
        self.npc = self._combo(setup, [n[0] for n in NPC_CHOICES],
                               self.sf["npc"], 13)
        self.npc.pack(side="left", padx=(3, int(8 * s)))
        self._lbl(setup, "Difficulty").pack(side="left")
        self.difficulty = self._combo(setup, DIFFICULTIES, self.sf["difficulty"], 9)
        self.difficulty.pack(side="left", padx=(3, 0))
        # any RNG-context change kills everything computed with the old one
        self.level.configure(command=self._settings_changed)
        self.level.bind("<KeyRelease>", self._settings_changed)
        for cb in (self.platform, self.version, self.npc, self.difficulty):
            cb.bind("<<ComboboxSelected>>", self._settings_changed, add=True)
        self._btn(setup, "Clear", self.clear_offer).pack(side="right")
        self._btn(setup, "⟳ Fill from F10 scan", self.fill_from_scan).pack(
            side="right", padx=(0, int(6 * s)))
        self.scan_btn = self._btn(setup, "📷 Scan screen", self.scan_screen,
                                  "primary")
        self.scan_btn.configure(width=14)
        self.scan_btn.pack(side="right", padx=(0, int(6 * s)))

        # left: the store grid
        left = tk.Frame(self, bg=BG)
        left.grid(row=2, column=0, sticky="nsew", padx=(pad, int(6 * s)),
                  pady=(int(8 * s), pad))
        self.cell = int(44 * s)
        cv_sz = self.cell * 10 + 1
        cap = tk.Frame(left, bg=BG)
        cap.pack(fill="x")
        tk.Label(cap, text="THE OFFER — click a cell to pick, right-click "
                           "removes", bg=BG, fg=DIM,
                 font=self.f_sub).pack(side="left")
        self.count_lbl = tk.Label(cap, text="", bg=BG, fg=GOLD,
                                  font=self.f_bold, width=34, anchor="e")
        self.count_lbl.pack(side="right")
        self._grid_preview = None
        # always packed (disabled when idle) so appearing never shifts layout
        self.back_btn = self._btn(cap, "↩ Back to my offer",
                                  self._preview_off)
        self.back_btn.configure(state="disabled", disabledforeground="#5a4d38")
        self.back_btn.pack(side="right", padx=(0, int(6 * s)))
        self.canvas = tk.Canvas(left, width=cv_sz, height=cv_sz, bg="#0d0a06",
                                highlightthickness=1, highlightbackground=LINE)
        self.canvas.pack(pady=(int(4 * s), 0))
        self.canvas.bind("<ButtonPress-1>", self._grid_press)
        self.canvas.bind("<B1-Motion>", self._grid_drag)
        self.canvas.bind("<ButtonRelease-1>", self._grid_drop)
        self.canvas.bind("<Button-3>", self._grid_rclick)
        self.canvas.bind("<Motion>", self._grid_hover)
        self.canvas.bind("<Leave>", lambda _e: self._set_hover(None))
        self._hover_rect = None
        self._hover_slot = None
        self._hover_x_box = None
        self._target_cell = None
        self._drag = None  # {"slot": i, "dx": cells, "dy": cells}

        # permanent add-item search: type -> pick -> the item lands where
        # the game itself would pack it (flat right-to-left, tall
        # left-to-right); drag items on the grid to correct
        addf = tk.Frame(left, bg=BG)
        addf.pack(fill="x", pady=(int(6 * s), 0))
        tk.Label(addf, text="ADD ITEM — Enter places it by D2 packing; "
                            "drag to move, right-click removes",
                 bg=BG, fg=DIM, font=self.f_sub).pack(anchor="w")
        srow = tk.Frame(addf, bg=BG)
        srow.pack(fill="x")
        self.search_var = tk.StringVar()
        self.search_entry = self._entry(srow, 24, self.search_var)
        self.search_entry.pack(side="left", fill="x", expand=True)
        self.place_mode = self._combo(srow, ["auto-place", "no position"],
                                      "auto-place", 10)
        self.place_mode.pack(side="left", padx=(int(4 * s), 0))
        # results appear ONLY while searching (focus/typing) — a permanent
        # 125-row list was wasted space
        self._search_dd = SearchDropdown(self, self.search_entry,
                                         self.search_var, self._item_rows,
                                         self._add_item_pick)
        self.search_tv = self._search_dd.tv

        unp = tk.Frame(left, bg=BG)
        unp.pack(fill="x", pady=(int(6 * s), 0))
        self._lbl(unp, "Items without a position (name-only search):",
                  fg=DIM, font=self.f_sub).pack(anchor="w")
        row = tk.Frame(unp, bg=BG)
        row.pack(fill="x")
        self.unplaced_list = tk.Listbox(row, height=4, bg=FIELD, fg=FG,
                                        selectbackground=GOLD,
                                        selectforeground=BG, relief="flat",
                                        font=self.f_base,
                                        highlightthickness=1,
                                        highlightbackground=LINE)
        self.unplaced_list.pack(side="left", fill="x", expand=True)
        col = tk.Frame(row, bg=BG)
        col.pack(side="left", padx=(int(4 * s), 0))
        self._btn(col, "+", self._focus_unplaced_add).pack(fill="x")
        self._btn(col, "−", self._remove_unplaced).pack(fill="x", pady=(3, 0))

        # right: controls
        right = tk.Frame(self, bg=BG)
        right.grid(row=2, column=1, sticky="nsew", padx=(0, pad),
                   pady=(int(8 * s), 0))
        right.columnconfigure(0, weight=1)

        sec1 = self._section(right, "SEED", 0)
        r1 = tk.Frame(sec1, bg=PANEL)
        r1.pack(fill="x", padx=int(8 * s), pady=(0, int(6 * s)))
        self.btn = self._btn(r1, "🔍 Find seed", self.toggle, "primary")
        self.btn.configure(width=12)
        self.btn.pack(side="left")
        self.progress = ttk.Progressbar(r1, length=int(150 * s), maximum=1.0,
                                        style="SF.Horizontal.TProgressbar")
        self.progress.pack(side="left", padx=int(8 * s), fill="x", expand=True)
        self.status = self._lbl(r1, "idle", fg=FG)
        self.status.pack(side="left")
        r2 = tk.Frame(sec1, bg=PANEL)
        r2.pack(fill="x", padx=int(8 * s), pady=(0, int(8 * s)))
        self._lbl(r2, "Seed").pack(side="left")
        self.seed_var = tk.StringVar()
        self._entry(r2, 12, self.seed_var).pack(side="left", padx=(3, 4))
        self._btn(r2, "🎲", self.random_seed).pack(side="left", padx=(0, 4))
        self.game_seed = tk.BooleanVar(value=False)
        tk.Checkbutton(r2, text="in-game seed", variable=self.game_seed,
                       bg=PANEL, fg=DIM, selectcolor=FIELD, relief="flat",
                       activebackground=PANEL, font=self.f_sub).pack(side="left")
        self._lbl(r2, "  Offset").pack(side="left")
        self.offset_var = tk.StringVar(value="0")
        self._entry(r2, 9, self.offset_var).pack(side="left", padx=(3, 0))
        self.state_lbl = tk.Label(r2, text="", bg=PANEL, fg=GOLD_HI,
                                  font=self.f_bold)
        self.state_lbl.pack(side="left", padx=(int(8 * self.s), 0))
        rc = tk.Frame(sec1, bg=PANEL)
        rc.pack(fill="x", padx=int(8 * s), pady=(0, int(8 * s)))
        tk.Label(rc, text="CANDIDATES — appear live; double-click to use "
                          "(the search keeps running)",
                 bg=PANEL, fg=DIM, font=self.f_sub).pack(anchor="w")
        self.cand_list = tk.Listbox(rc, height=3, bg=FIELD, fg=GOLD_HI,
                                    selectbackground=GOLD, selectforeground=BG,
                                    relief="flat", font=self.f_mono,
                                    highlightthickness=1,
                                    highlightbackground=LINE)
        self.cand_list.pack(fill="x")
        self.cand_list.bind("<Double-Button-1>", self._use_candidate)

        sec2 = self._section(right, "PREDICT — future refreshes", 1)
        r3 = tk.Frame(sec2, bg=PANEL)
        r3.pack(fill="x", padx=int(8 * s), pady=(0, int(4 * s)))
        self._btn(r3, "Preview refreshes", self.preview).pack(side="left")
        self._lbl(r3, " n").pack(side="left")
        self.n_refresh = self._spin(r3, 1, 500, str(self.sf["refreshes"]), 4)
        self.n_refresh.pack(side="left", padx=(2, int(8 * s)))
        self.off_btn = self._btn(r3, "Find offset (after buys)", self.offsets)
        self.off_btn.configure(width=22)
        self.off_btn.pack(side="left")
        self._lbl(r3, " max").pack(side="left")
        self.max_off = self._spin(r3, 1000, 100000000, str(self.sf["max_offset"]), 9,
                                  increment=100000)
        self.max_off.pack(side="left", padx=(2, 0))
        rp = tk.Frame(sec2, bg=PANEL)
        rp.pack(fill="x", padx=int(8 * s), pady=(0, int(8 * s)))
        rp_cap = tk.Frame(rp, bg=PANEL)
        rp_cap.pack(fill="x")
        tk.Label(rp_cap, text="click a refresh to SEE it on the grid "
                              "(UNIQUE/SET rows glow):",
                 bg=PANEL, fg=DIM, font=self.f_sub).pack(side="left")
        self._btn(rp_cap, "⤓ I refreshed to here — apply",
                  self._apply_preview_state).pack(side="right")
        self.buy_btn = self._btn(rp_cap, "🛒 I bought — click it",
                                 self._buy_mode_toggle)
        self.buy_btn.pack(side="right", padx=(0, int(6 * s)))
        self._buy_mode = False
        self._session = None  # {'lo','hi','abs_pos','win','buys'} after buys
        self.prev_tv = ttk.Treeview(rp, show="tree", style="SF.Treeview",
                                    selectmode="browse", height=5)
        self.prev_tv.pack(fill="x")
        self.prev_tv.tag_configure("uni", foreground=GOLD)
        self.prev_tv.tag_configure("set", foreground=SETC)
        self.prev_tv.tag_configure("dim", foreground=DIM)
        self.prev_tv.bind("<<TreeviewSelect>>", self._preview_pick)
        self._preview_chain = None

        sec3 = self._section(right, "BUY PLANNER — routes to your target", 2)
        r4 = tk.Frame(sec3, bg=PANEL)
        r4.pack(fill="x", padx=int(8 * s), pady=(0, int(6 * s)))
        self.plan_btn = self._btn(r4, "🧭 Plan buys", self.plan, "primary")
        self.plan_btn.configure(width=22)
        self.plan_btn.pack(side="left")
        self._lbl(r4, " target").pack(side="left")
        # same searchable icon dropdown as ADD ITEM (a plain Combobox
        # doesn't filter while typing)
        self.target_var = tk.StringVar(value=self.sf["target"])
        self.target_name = self._entry(r4, 16, self.target_var)
        self.target_name.pack(side="left", padx=2)
        # typing replaces the old value instead of appending to "(any)"
        self.target_name.bind(
            "<FocusIn>",
            lambda _e: self.target_name.select_range(0, "end"), add=True)
        self._target_dd = SearchDropdown(
            self, self.target_name, self.target_var,
            lambda needle: ([("(any)", None)] if needle in "(any)" else [])
            + self._item_rows(needle),
            self._target_pick, min_width=int(260 * s))
        self.target_rarity = self._combo(r4, [r[0] for r in RARITY_CHOICES],
                                         self.sf["target_rarity"], 20)
        self.target_rarity.pack(side="left", padx=2)
        self.target_tier = self._combo(r4, [t[0] for t in TIER_CHOICES],
                                       self.sf["target_tier"], 11)
        self.target_tier.pack(side="left", padx=2)
        r5 = tk.Frame(sec3, bg=PANEL)
        r5.pack(fill="x", padx=int(8 * s), pady=(0, int(4 * s)))
        self._lbl(r5, "depth").pack(side="left")
        self.max_depth = self._spin(r5, 1, 100000, str(self.sf["depth"]), 6)
        self.max_depth.pack(side="left", padx=(2, int(8 * s)))
        self._lbl(r5, "shift-buys").pack(side="left")
        self.max_buys = self._spin(r5, 0, 100, str(self.sf["shift_buys"]), 3)
        self.max_buys.pack(side="left", padx=(2, 0))
        rq = tk.Frame(sec3, bg=PANEL)
        rq.pack(fill="x", padx=int(8 * s), pady=(0, int(4 * s)))
        tk.Label(rq, text="click a plan: its steps show below, the plan # "
                          "is set for Execute, and the final window previews "
                          "on the grid:",
                 bg=PANEL, fg=DIM, font=self.f_sub).pack(anchor="w")
        self.plans_tv = ttk.Treeview(rq, show="tree", style="SF.Treeview",
                                     selectmode="browse", height=5)
        self.plans_tv.pack(fill="x")
        self.plans_tv.tag_configure("uni", foreground=GOLD)
        self.plans_tv.tag_configure("set", foreground=SETC)
        self.plans_tv.tag_configure("rare", foreground=RARE)
        self.plans_tv.bind("<<TreeviewSelect>>", self._plan_pick)
        self.plan_steps_lbl = tk.Label(sec3, text="", bg=PANEL, fg=FG,
                                       font=self.f_sub, anchor="nw",
                                       height=3,
                                       justify="left", wraplength=int(560 * s))
        self.plan_steps_lbl.pack(fill="x", padx=int(8 * s),
                                 pady=(0, int(8 * s)))

        sec4 = self._section(right, "AUTO-CLICKER", 3)
        r6 = tk.Frame(sec4, bg=PANEL)
        r6.pack(fill="x", padx=int(8 * s), pady=(0, int(8 * s)))
        self.exec_btn = self._btn(r6, "▶ Execute plan #", self.execute,
                                  "danger")
        self.exec_btn.configure(width=18)
        self.exec_btn.pack(side="left")
        self.plan_no = self._spin(r6, 1, 30, "1", 3)
        self.plan_no.pack(side="left", padx=(2, int(8 * s)))
        self._lbl(r6, "delay s").pack(side="left")
        self.click_delay = self._spin(r6, 0, 5, str(self.sf["click_delay"]), 4, increment=0.1)
        self.click_delay.pack(side="left", padx=(2, int(8 * s)))
        self._btn(r6, "Set Refresh button", self.calibrate).pack(side="left")
        self._btn(r6, "Set sell zone",
                  self.calibrate_sell).pack(side="left", padx=(int(4 * s), 0))
        self.calib_lbl = self._lbl(r6, "", fg=DIM, font=self.f_sub)
        self.calib_lbl.pack(side="left", padx=int(6 * s))
        self._update_calib_lbl()

        # log
        logf = tk.Frame(left, bg=BG)
        logf.pack(fill="both", expand=True, pady=(int(8 * s), 0))
        logf.rowconfigure(0, weight=1)
        logf.columnconfigure(0, weight=1)
        self.out = tk.Text(logf, bg="#0d0a06", fg=FG, insertbackground=GOLD,
                           relief="flat", font=self.f_mono, wrap="word",
                           height=8,
                           highlightthickness=1, highlightbackground=LINE)
        self.out.grid(row=0, column=0, sticky="nsew")
        sb = ttk.Scrollbar(logf, command=self.out.yview)
        sb.grid(row=0, column=1, sticky="ns")
        self.out.configure(yscrollcommand=sb.set)
        self.out.configure(state="disabled")
        self.out.tag_configure("uni", foreground=GOLD)
        self.out.tag_configure("set", foreground=SETC)
        self.out.tag_configure("rare", foreground=RARE)
        self.out.tag_configure("dim", foreground=DIM)
        self.out.tag_configure("hot", foreground=GOLD_HI)
        self.log("F10 on the gamble screen fills the grid automatically "
                 "(icons, no setup). Click cells to fix anything by hand.")
        self.log("Find seed → preview shows which refreshes become "
                 "UNIQUE/SET → Plan buys → Execute clicks it in game.")

    def _section(self, parent, title, row):
        s = self.s
        f = tk.Frame(parent, bg=PANEL, highlightthickness=1,
                     highlightbackground=LINE)
        f.grid(row=row, column=0, sticky="ew", pady=(0, int(6 * s)))
        tk.Label(f, text=title, bg=PANEL, fg=GOLD, font=self.f_sub,
                 anchor="w").pack(fill="x", padx=int(8 * s), pady=(int(4 * s), 2))
        return f

    def _update_calib_lbl(self):
        have_r = isinstance(self.calib.get("refresh"), (list, tuple))
        have_c = calib_ok({**self.calib, "refresh": self.calib.get("refresh") or [0, 0]})
        have_s = isinstance(self.calib.get("sellzone"), (list, tuple)) \
            or isinstance(self.calib.get("sellslot"), (list, tuple))
        txt, col = [], GREEN
        txt.append("refresh ✓" if have_r else "refresh: not set")
        txt.append("cells ✓" if have_c else "cells: auto after F10 scan")
        txt.append("auto sell-back ✓" if have_s else "sell zone: not set")
        if not have_r:
            col = RED
        elif not (have_c and have_s):
            col = DIM
        self.calib_lbl.configure(text=" · ".join(txt) + " · ESC aborts", fg=col)

    # ------------------------------------------------------------- grid UI

    def _photo(self, code, wcells, hcells):
        key = (code, wcells, hcells, self.cell)
        got = self._photos.get(key)
        if got is not None:
            return got
        import cv2
        from advisor.gamble_vision import ICON_DIR
        p = ICON_DIR / f"{code}.png"
        if not p.exists():
            return None
        icon = cv2.imread(str(p), cv2.IMREAD_UNCHANGED)
        if icon is None:
            return None
        icon = cv2.resize(icon, (wcells * self.cell - 2, hcells * self.cell - 2),
                          interpolation=cv2.INTER_AREA)
        ok, png = cv2.imencode(".png", icon)
        if not ok:
            return None
        img = tk.PhotoImage(data=base64.b64encode(png.tobytes()))
        self._photos[key] = img
        return img

    _Q_OUTLINE = {Q_UNIQUE: (GOLD_HI, 3), Q_SET: (SETC, 3), Q_RARE: (RARE, 2)}

    def redraw(self):
        c, cell = self.canvas, self.cell
        c.delete("all")
        preview = self._grid_preview
        for i in range(11):
            c.create_line(i * cell, 0, i * cell, 10 * cell, fill=LINE)
            c.create_line(0, i * cell, 10 * cell, i * cell, fill=LINE)
        show = self._display_slots()
        if not preview:
            # ghost anchors (edit mode only)
            placed = {(sl["x"], sl["y"]) for sl in show}
            if (9, 0) not in placed:
                c.create_text(9 * cell + cell // 2, cell // 2, text="R",
                              fill=LINE, font=self.f_head)
            if (9, 1) not in placed:
                c.create_text(9 * cell + cell // 2, cell + cell // 2, text="A",
                              fill=LINE, font=self.f_head)
        for sl in show:
            it = self.items[sl["idx"]]
            w, h = it["invw"], it["invh"]
            x0, y0 = sl["x"] * cell, sl["y"] * cell
            outline, width = GOLD, 1
            if preview:
                outline, width = self._Q_OUTLINE.get(sl.get("quality"),
                                                     (LINE, 1))
            c.create_rectangle(x0 + 1, y0 + 1, x0 + w * cell - 1,
                               y0 + h * cell - 1, fill="#241b10",
                               outline=outline, width=width)
            img = self._photo(it["code"], w, h)
            if img is not None:
                c.create_image(x0 + 1, y0 + 1, image=img, anchor="nw")
            else:
                c.create_text(x0 + w * cell // 2, y0 + h * cell // 2,
                              text=it["code"], fill=FG, font=self.f_sub)
            if preview and sl.get("quality") in (Q_UNIQUE, Q_SET):
                tagname = QUALITY_NAMES[sl["quality"]]
                c.create_text(x0 + 3, y0 + 2, text=tagname, anchor="nw",
                              fill=self._Q_OUTLINE[sl["quality"]][0],
                              font=self.f_sub)
        self._draw_marker("target",
                          None if self._target_cell is None
                          else (self._target_cell[0], self._target_cell[1], 1, 1),
                          GOLD_HI, dash=(4, 3))
        # full redraw wipes ALL hover state — markers, ✕ box, tooltip
        self._hover_rect = None
        self._hover_slot = None
        self._hover_x_box = None
        self._tip_hide()
        self.unplaced_list.delete(0, "end")
        for idx in self.unplaced:
            self.unplaced_list.insert("end", self.items[idx]["name"])
        if preview:
            self.count_lbl.configure(text=preview["title"][:34], fg=GOLD_HI)
            return
        n = len(self.slots) + len(self.unplaced)
        over = " — TOO MANY, remove extras!" if n > 14 else ""
        self.title(f"Gamble Seed Finder — {n}/14 items{over} — D2R Item Advisor")
        if hasattr(self, "count_lbl"):
            if n > 14:
                self.count_lbl.configure(text=f"{n}/14 — remove extras!", fg=RED)
            elif n == 14:
                self.count_lbl.configure(text="14/14 ✓", fg=GREEN)
            else:
                self.count_lbl.configure(
                    text=f"{n}/14 (fewer is OK if (0,0) is placed)", fg=GOLD)

    # ---------------------------------------------------- grid preview mode

    def _display_slots(self):
        """What the grid currently shows: a preview window or the offer."""
        if self._grid_preview:
            return self._grid_preview["slots"]
        return self.slots

    def _set_grid_preview(self, title, slots, source=None):
        """Render a predicted window on the grid with quality colors;
        ↩ Back returns to the editable offer. source ("refresh", k) lets an
        edit attempt APPLY the previewed state first, then edit."""
        self._grid_preview = {"title": title, "slots": slots,
                              "source": source}
        self.back_btn.configure(state="normal", bg=GOLD, fg="#191307")
        self.redraw()

    def _preview_edit_through(self):
        """Editing while previewing: a refresh preview becomes the current
        state (offset + items) and editing continues; plan previews are
        read-only. Returns True when the caller may proceed editing."""
        gp = self._grid_preview
        if not gp:
            return True
        src = gp.get("source")
        if src and src[0] == "refresh":
            self.prev_tv.selection_set(str(src[1]))
            self._apply_preview_state()
            self.log("preview applied as the current state — edit away",
                     "dim")
            return True
        self.log("plan previews are read-only — press ↩ Back to edit your "
                 "offer", "dim")
        return False

    def _preview_off(self, *_):
        self._grid_preview = None
        self.back_btn.configure(state="disabled", bg="#332817")
        for tv in (self.prev_tv, self.plans_tv):
            for sel in tv.selection():
                tv.selection_remove(sel)
        self.redraw()

    def _draw_marker(self, tag, rect, color, dash=None):
        """rect: (x, y, w, h) in CELLS, or None to clear."""
        self.canvas.delete(tag)
        if rect is None:
            return
        x, y, w, h = rect
        kw = {"dash": dash} if dash else {}
        self.canvas.create_rectangle(
            x * self.cell + 2, y * self.cell + 2,
            (x + w) * self.cell - 2, (y + h) * self.cell - 2,
            outline=color, width=2, tags=tag, **kw)

    def _tip_show(self, text):
        """Floating site-style tooltip (cream box, dark text) at the mouse."""
        if getattr(self, "_tip", None) is None or not self._tip.winfo_exists():
            self._tip = tk.Toplevel(self)
            self._tip.overrideredirect(True)
            self._tip.attributes("-topmost", True)
            self._tip_lbl = tk.Label(self._tip, text="", bg="#f2ead8",
                                     fg="#1d1509", font=self.f_bold,
                                     padx=8, pady=3, relief="solid", bd=1)
            self._tip_lbl.pack()
        self._tip_lbl.configure(text=text)
        self._tip.geometry(f"+{self.winfo_pointerx() + 14}"
                           f"+{self.winfo_pointery() + 12}")
        self._tip.deiconify()

    def _tip_hide(self):
        if getattr(self, "_tip", None) is not None and self._tip.winfo_exists():
            self._tip.withdraw()

    def _set_hover(self, rect, label=None, slot=None):
        # ALWAYS recompute — caching by (rect,label) went stale whenever a
        # redraw happened between motions and hover pointed at ghosts
        self._hover_slot = slot
        self._hover_rect = (rect, label)
        self._hover_x_box = None
        self._draw_marker("hover", rect, "#8a7a52")
        self.canvas.delete("hoverx")
        if (rect is not None and slot is not None
                and not self._grid_preview):
            # site-style ✕ remove button — EDIT mode only (previews are
            # read-only; a stale ✕ once deleted the wrong offer slot)
            x, y, w, h = rect
            bx1 = (x + w) * self.cell - 4
            bx0 = bx1 - int(16 * self.s)
            by0 = y * self.cell + 4
            by1 = by0 + int(16 * self.s)
            self.canvas.create_rectangle(bx0, by0, bx1, by1,
                                         fill="#402018", outline=RED,
                                         tags="hoverx")
            self.canvas.create_text((bx0 + bx1) // 2, (by0 + by1) // 2,
                                    text="✕", fill="#ff9a8a",
                                    font=self.f_sub, tags="hoverx")
            self._hover_x_box = (bx0, by0, bx1, by1)
        if rect is None or not label:
            self._tip_hide()
        else:
            self._tip_show(label)

    def _set_target(self, cell):
        self._target_cell = cell
        self._draw_marker("target",
                          None if cell is None else (cell[0], cell[1], 1, 1),
                          GOLD_HI, dash=(4, 3))

    def _grid_hover(self, ev):
        gx, gy = ev.x // self.cell, ev.y // self.cell
        if not (0 <= gx < 10 and 0 <= gy < 10):
            self._set_hover(None)
            return
        hit = self._slot_at(gx, gy)
        if hit is not None:  # highlight the whole ITEM and name it
            sl = self._display_slots()[hit]  # NOT self.slots — previews too
            it = self.items[sl["idx"]]
            self._set_hover((sl["x"], sl["y"], it["invw"], it["invh"]),
                            it["name"], slot=hit)
            # keep the tooltip tracking the mouse
            self._tip_show(it["name"])
        else:
            self._set_hover((gx, gy, 1, 1))

    # -------------------------------------------------------- drag & drop

    def _grid_press(self, ev):
        if self._grid_preview and not self._preview_edit_through():
            return
        gx, gy = ev.x // self.cell, ev.y // self.cell
        if not (0 <= gx < 10 and 0 <= gy < 10):
            return
        if self._buy_mode:
            hit = self._slot_at(gx, gy)
            self._buy_mode = False
            self.buy_btn.configure(bg="#332817", fg=FG)
            if hit is None:
                self.log("! buy cancelled — that cell is empty")
            else:
                self._apply_buy(hit)
            return
        # click on the hover ✕ removes the item (site behavior)
        box = getattr(self, "_hover_x_box", None)
        if (box and self._hover_slot is not None
                and box[0] <= ev.x <= box[2] and box[1] <= ev.y <= box[3]):
            del self.slots[self._hover_slot]
            self._set_hover(None)
            self.redraw()
            return
        hit = self._slot_at(gx, gy)
        if hit is None:
            self.search_entry.focus_set()  # empty cell -> go type a name
            return
        sl = self.slots[hit]
        self._tip_hide()
        self._drag = {"slot": hit, "dx": gx - sl["x"], "dy": gy - sl["y"]}

    def _grid_drag(self, ev):
        if not self._drag:
            return
        sl = self.slots[self._drag["slot"]]
        it = self.items[sl["idx"]]
        gx = ev.x // self.cell - self._drag["dx"]
        gy = ev.y // self.cell - self._drag["dy"]
        gx = max(0, min(10 - it["invw"], gx))
        gy = max(0, min(10 - it["invh"], gy))
        ok = self._fits(sl["idx"], gx, gy, skip=self._drag["slot"])
        self._draw_marker("dragtgt", (gx, gy, it["invw"], it["invh"]),
                          GREEN if ok else RED, dash=(3, 2))

    def _grid_drop(self, ev):
        self.canvas.delete("dragtgt")
        if not self._drag:
            return
        d, self._drag = self._drag, None
        sl = self.slots[d["slot"]]
        it = self.items[sl["idx"]]
        gx = ev.x // self.cell - d["dx"]
        gy = ev.y // self.cell - d["dy"]
        gx = max(0, min(10 - it["invw"], gx))
        gy = max(0, min(10 - it["invh"], gy))
        if (gx, gy) != (sl["x"], sl["y"]) and self._fits(sl["idx"], gx, gy,
                                                         skip=d["slot"]):
            sl["x"], sl["y"] = gx, gy
        self.redraw()

    # -------------------------------------------------------- add via search

    def place_by_d2(self, idx):
        """First free spot by the game's own packing: flat items scan
        columns right-to-left, taller items left-to-right."""
        it = self.items[idx]
        w, h = it["invw"], it["invh"]
        xs = range(10 - w, -1, -1) if h <= 1 else range(0, 10 - w + 1)
        for x in xs:
            for y in range(0, 10 - h + 1):
                if self._fits(idx, x, y):
                    return (x, y)
        return None

    def _item_rows(self, needle):
        """(name, icon) rows for a SearchDropdown, filtered by needle."""
        code_of = {it["name"]: it["code"] for it in self.items}
        return [(n, self._thumb(code_of.get(n, "")))
                for n in self.names if needle in n.lower()]

    def _target_pick(self, name):
        # empty field = any target ("(any)" is just the discoverable row)
        self.target_var.set("" if name == "(any)" else name)
        self._target_dd.show(False)
        self.focus_set()  # drop entry focus so the list stays closed

    def _add_item_pick(self, name):
        if self._grid_preview and not self._preview_edit_through():
            self._preview_off()  # plan preview: fall back to the offer
        idx = item_index(name)
        if idx < 0:
            return
        if self.place_mode.get() == "no position":
            self.unplaced.append(idx)
            self.redraw()
        else:
            pos = self.place_by_d2(idx)
            if pos is None:
                self.log(f"! no room for {name} — remove something first")
                return
            self.slots.append({"idx": idx, "x": pos[0], "y": pos[1]})
            self.redraw()
            self.log(f"placed {name} at ({pos[0]},{pos[1]}) — drag it if the "
                     "game shows it elsewhere", "dim")
        self.search_var.set("")
        self.search_entry.focus_set()

    def _next_empty_cell(self):
        occupied = [[False] * 10 for _ in range(10)]
        for sl in self.slots:
            it = self.items[sl["idx"]]
            for yy in range(sl["y"], min(10, sl["y"] + it["invh"])):
                for xx in range(sl["x"], min(10, sl["x"] + it["invw"])):
                    occupied[yy][xx] = True
        for y in range(10):
            for x in range(10):
                if not occupied[y][x]:
                    return (x, y)
        return None

    def _slot_at(self, gx, gy):
        for i, sl in enumerate(self._display_slots()):
            it = self.items[sl["idx"]]
            if (sl["x"] <= gx < sl["x"] + it["invw"]
                    and sl["y"] <= gy < sl["y"] + it["invh"]):
                return i
        return None

    def _fits(self, idx, x, y, skip=None):
        it = self.items[idx]
        w, h = it["invw"], it["invh"]
        if x + w > 10 or y + h > 10:
            return False
        for i, sl in enumerate(self.slots):
            if i == skip:
                continue
            o = self.items[sl["idx"]]
            if (x < sl["x"] + o["invw"] and sl["x"] < x + w
                    and y < sl["y"] + o["invh"] and sl["y"] < y + h):
                return False
        return True

    def _focus_unplaced_add(self):
        self.place_mode.set("no position")
        self.search_entry.focus_set()

    def _grid_rclick(self, ev):
        if self._grid_preview and not self._preview_edit_through():
            return
        gx, gy = ev.x // self.cell, ev.y // self.cell
        hit = self._slot_at(gx, gy)
        if hit is not None:
            del self.slots[hit]
            self.redraw()

    def _remove_unplaced(self):
        sel = self.unplaced_list.curselection()
        if sel:
            del self.unplaced[sel[0]]
            self.redraw()

    def _thumb(self, code):
        """Small item icon for the picker rows (aspect kept, cached)."""
        key = ("thumb", code)
        got = self._photos.get(key)
        if got is not None:
            return got
        import cv2
        from advisor.gamble_vision import ICON_DIR
        p = ICON_DIR / f"{code}.png"
        if not p.exists():
            return None
        icon = cv2.imread(str(p), cv2.IMREAD_UNCHANGED)
        if icon is None:
            return None
        th = max(18, int(26 * self.s))
        h, w = icon.shape[:2]
        sc = th / max(h, w)
        icon = cv2.resize(icon, (max(1, int(w * sc)), max(1, int(h * sc))),
                          interpolation=cv2.INTER_AREA)
        ok, png = cv2.imencode(".png", icon)
        if not ok:
            return None
        img = tk.PhotoImage(data=base64.b64encode(png.tobytes()))
        self._photos[key] = img
        return img

    def _place_defaults(self):
        self.slots = [{"idx": item_index("rin"), "x": 9, "y": 0},
                      {"idx": item_index("amu"), "x": 9, "y": 1}]
        self.unplaced = []

    def clear_offer(self):
        self._place_defaults()
        self._clear_session("offer cleared")
        self.redraw()

    # ------------------------------------------------------------- data in

    def _scan_done(self):
        self._screen_scanning = False
        self.scan_btn.configure(text="📷 Scan screen", state="normal")

    def _on_close(self):
        self.stop_event.set()
        self.destroy()

    def scan_screen(self):
        """Capture every monitor and read the gamble grid right from here —
        no hotkey needed. Fills the visual grid; fix mistakes by clicking.
        Has its OWN feedback (the button) — the SEED progress bar belongs
        to the seed search and stays out of this."""
        if getattr(self, "_screen_scanning", False):
            return
        from advisor import capture_guard
        if capture_guard.busy_with():
            self.log(f"busy: {capture_guard.busy_with()} is running", "dim")
            return
        self._screen_scanning = True
        self.scan_btn.configure(text="⏳ Scanning…", state="disabled")
        self.log("scanning all monitors for the gamble grid…", "dim")

        def work():
            try:
                import mss
                import numpy as np
                from advisor import gamble_vision as gv
                fails = []
                with mss.mss() as sct:
                    monitors = sct.monitors[1:] or sct.monitors
                    for mi, mon in enumerate(monitors, 1):
                        img = np.array(sct.grab(mon))[:, :, :3]
                        rect = (mon["left"], mon["top"],
                                mon["width"], mon["height"])
                        diag = []
                        try:
                            entries = gv.scan_gamble_icons(img, rect, diag=diag)
                            self.msgs.put(("scan_ok", entries, mi))
                            return
                        except ValueError as e:
                            best = max((sc for _c, sc in diag), default=0.0)
                            fails.append(f"monitor {mi}: {e} "
                                         f"(best anchor score {best:.2f})")
                self.msgs.put(("scan_fail", fails))
            except Exception as e:
                self.msgs.put(("err", f"{type(e).__name__}: {e}"))

        threading.Thread(target=work, daemon=True).start()

    def fill_from_scan(self, quiet=False):
        entries = list(self.get_last_entries() or []) if self.get_last_entries else []
        if entries:
            key = tuple(sorted(entries))
            if quiet and key == self._last_fill_key:
                return  # same scan as before — keep the user's hand edits
            self._last_fill_key = key
            self._invalidate(plans=True, preview=True, candidates=True)
            self._clear_session("new scan")
            self.slots = [{"idx": i, "x": x, "y": y} for i, x, y in entries]
            self.unplaced = []
            self.redraw()
            self.log(f"filled {len(entries)}/14 from the icon scan "
                     "(with grid positions)")
            return
        offer = list(self.get_last_offer() or []) if self.get_last_offer else []
        if not offer:
            if not quiet:
                self.log("! no F10 scan yet — open the gamble screen and press F10")
            return
        self._place_defaults()
        skipped = []
        seen_forced = {"Ring": 1, "Amulet": 1}
        for name in offer:
            if seen_forced.get(name):
                seen_forced[name] -= 1
                continue
            idx = map_ocr_name(name)
            if idx < 0:
                skipped.append(name)
                continue
            self.unplaced.append(idx)
        self.redraw()
        n = len(self.slots) + len(self.unplaced)
        self.log(f"filled {n}/14 from the OCR scan (no positions)"
                 + (f" — could not map: {', '.join(skipped)}" if skipped else ""))

    def _entries(self):
        entries = [(sl["idx"], sl["x"], sl["y"]) for sl in self.slots]
        entries += [(idx, None, None) for idx in self.unplaced]
        return entries

    # ------------------------------------------------------------- helpers

    def log(self, text, tag=None):
        self.out.configure(state="normal")
        self.out.insert("end", text + "\n", tag or ())
        self.out.configure(state="disabled")
        self.out.see("end")

    def log_segments(self, segments):
        self.out.configure(state="normal")
        for text, tag in segments:
            self.out.insert("end", text, tag or ())
        self.out.insert("end", "\n")
        self.out.configure(state="disabled")
        self.out.see("end")

    def _ctx(self):
        return Ctx(int(self.level.get()), self._platform(),
                   version=self._version())

    def _platform(self):
        return dict(PLATFORM_CHOICES).get(self.platform.get(), "msvc")

    def _version(self):
        return dict(VERSION_CHOICES).get(self.version.get(), "d2r")

    def _npc(self):
        return dict(NPC_CHOICES).get(self.npc.get(), "gheed")

    def random_seed(self):
        """🎲 — explore without scanning anything: roll a random store
        seed, show its offer on the grid and preview the refreshes."""
        import random
        sd = random.getrandbits(32)
        self._clear_session("random seed")
        self._invalidate(plans=True, preview=True, candidates=True)
        self.seed_var.set(str(sd))
        self.game_seed.set(False)
        self.offset_var.set("0")
        from advisor.gamble_seed import offer_with_positions
        offer = offer_with_positions(sd, self._ctx())
        self.slots = [{"idx": i, "x": p[0], "y": p[1]}
                      for i, p in offer if p is not None]
        self.unplaced = []
        self._preview_off()
        self.redraw()
        self.log(f"🎲 random seed {sd} — its offer is on the grid; "
                 "Preview refreshes / Plan buys away", "hot")
        try:
            self.show_future(sd, int(self.n_refresh.get() or 30))
        except Exception:
            pass

    def _use_candidate(self, _ev=None):
        sel = self.cand_list.curselection()
        if not sel:
            return
        sd = self.cand_list.get(sel[0])
        self._clear_session("candidate selected")
        self._invalidate(plans=True, preview=True)
        self.seed_var.set(sd)
        self.game_seed.set(False)
        self.offset_var.set("0")
        self.log(f"using candidate {sd} — Preview refreshes / Plan buys are "
                 "ready (search continues in the background)", "hot")

    def _seed(self):
        try:
            seed = int(self.seed_var.get().strip()) & 0xFFFFFFFF
        except ValueError:
            raise ValueError("enter the seed first (Find seed fills it in)")
        if self.game_seed.get():
            seed = game_seed_to_store(seed, self._version())
        return seed

    def _offset(self):
        try:
            return max(0, int(self.offset_var.get().strip() or "0"))
        except ValueError:
            return 0

    def _difficulty(self):
        return DIFFICULTIES.index(self.difficulty.get())

    def _busy(self, label):
        if self.searching:
            return False
        self.searching = True
        self.stop_event.clear()
        self.btn.configure(text="■ Stop")
        self.status.configure(text=label)
        return True

    def _reset(self):
        self.searching = False
        self.btn.configure(text="🔍 Find seed")
        self.status.configure(text="idle")
        self._indet = False
        self.progress["value"] = 0

    def _qtag(self, quality):
        return {Q_UNIQUE: "uni", Q_SET: "set", Q_RARE: "rare"}.get(quality)

    # ------------------------------------------------------------- find seed

    def toggle(self):
        if self.searching:
            self.stop_event.set()
            self.status.configure(text="stopping…")
            return
        entries = self._entries()
        try:
            level = int(self.level.get())
        except ValueError:
            self.log("! bad level")
            return
        if len(entries) > 14:
            self.log("! more than 14 items entered — an offer has exactly 14, "
                     "remove the extras (right-click) or Clear and rescan")
            return
        has_00 = any(x == 0 and y == 0 for _, x, y in entries)
        if len(entries) < 14 and not has_00:
            self.log("! need either all 14 items (positions optional) or the "
                     "item whose top-left corner is at grid (0,0)")
            return
        if len(entries) < 14:
            self.log(f"searching with {len(entries)}/14 items — works, but "
                     "expect more candidate seeds; add items to narrow down",
                     "dim")
        if not self._busy("starting…"):
            return
        # a new search invalidates everything the old seed produced
        self._invalidate(plans=True, preview=True, candidates=True)
        self._clear_session("new search")
        self._match_count = 0
        self._engine_tag = ""
        self._n_entries = len(entries)
        # until the first real slice lands, the bar CREEPS smoothly (no
        # bouncing/blinking) — replaced by true progress on arrival
        self._indet = True
        self.progress["value"] = 0.0

        def _creep():
            if getattr(self, "_indet", False) and self.searching:
                self.progress["value"] = min(0.04, self.progress["value"] + 0.0015)
                self.after(120, _creep)

        self.after(120, _creep)
        plat = self._platform()
        from advisor.gamble_seed import versions as _versions
        row = bool(_versions()[self._version()].get("row_pool"))
        import time as _time
        t0 = _time.time()

        def work():
            try:
                found = search_full(
                    level, plat, entries,
                    on_progress=lambda d, t: self.msgs.put(
                        ("prog2", d / t, d, d / max(0.001, _time.time() - t0))),
                    on_match=lambda sd: self.msgs.put(("cand", sd)),
                    on_engine=lambda eng, info: self.msgs.put(
                        ("engine", eng, info)),
                    stop=self.stop_event, equiv=_equiv_safe(), row_pool=row)
                self.msgs.put(("done", found))
            except Exception as e:
                self.msgs.put(("err", f"{type(e).__name__}: {e}"))

        threading.Thread(target=work, daemon=True).start()

    # ------------------------------------------------------------- seed tools

    def preview(self):
        try:
            seed = self._seed()
            n = int(self.n_refresh.get())
        except ValueError as e:
            self.log(f"! {e}")
            return
        # sync but not instant for big n — show a busy cursor as the loader
        self.configure(cursor="watch")
        self.update_idletasks()
        try:
            self.show_future(seed, n, offset=self._offset())
        finally:
            self.configure(cursor="")

    def _off_done(self):
        self._offsetting = False
        self._off_stop = None
        self.off_btn.configure(text="Find offset (after buys)")

    def offsets(self):
        # own feedback + cancel; the SEED bar stays with the seed search
        if getattr(self, "_offsetting", False):
            if self._off_stop is not None:
                self._off_stop.set()
                self.off_btn.configure(text="⏳ cancelling…")
            return
        try:
            seed = self._seed()
            max_off = int(self.max_off.get())
        except ValueError as e:
            self.log(f"! {e}")
            return
        entries = self._entries()
        has_00 = any(x == 0 and y == 0 for _, x, y in entries)
        if len(entries) < 14 and not has_00:
            self.log("! enter the CURRENT offer (all 14, or the (0,0) item)")
            return
        ctx = self._ctx()
        stop = self._off_stop = threading.Event()
        self._offsetting = True
        self.off_btn.configure(text="■ Cancel (0%)")

        def work():
            try:
                offs = find_offsets(seed, ctx, entries, max_offset=max_off,
                                    progress=lambda d, t: (
                                        self.msgs.put(("off_prog", d / t)),
                                        not stop.is_set())[1],
                                    equiv=_equiv_safe())
                self.msgs.put(("offs", offs, seed))
            except Exception as e:
                self.msgs.put(("err", f"{type(e).__name__}: {e}"))

        threading.Thread(target=work, daemon=True).start()

    # ------------------------------------------------------------- planner

    def _specs(self):
        name = self.target_name.get().strip()
        name_idx = -1
        if name and name != "(any)":
            name_idx = map_ocr_name(name)
            if name_idx < 0:
                raise ValueError(f"unknown target item: {name}")
        rarity = dict(RARITY_CHOICES)[self.target_rarity.get()]
        tier = dict(TIER_CHOICES).get(self.target_tier.get(), -1)
        if rarity is None:
            if name_idx < 0 and tier == -1:
                return None
            return [{"name": name_idx, "tier": tier, "rarity": q}
                    for q in (Q_RARE, Q_SET, Q_UNIQUE)]
        return [{"name": name_idx, "tier": tier, "rarity": rarity}]

    def _exec_done(self):
        self._executing = False
        self._exec_stop = None
        self.exec_btn.configure(text="▶ Execute plan #")

    def _plan_done(self):
        self._planning = False
        self._plan_stop = None
        self.plan_btn.configure(text="🧭 Plan buys")

    def plan(self):
        # the planner has its OWN feedback and cancel — the SEED bar
        # belongs to the seed search
        if getattr(self, "_planning", False):
            if self._plan_stop is not None:
                self._plan_stop.set()
                self.plan_btn.configure(text="⏳ cancelling…")
            return
        try:
            seed = self._seed()
            specs = self._specs()
            depth = int(self.max_depth.get())
            buys = int(self.max_buys.get())
        except ValueError as e:
            self.log(f"! {e}")
            return
        self._planning = True
        self._plan_stop = threading.Event()
        stop = self._plan_stop
        self.plan_btn.configure(text="■ Cancel planning (0%)")
        ctx = self._ctx()
        offset, npc, diff = self._offset(), self._npc(), self._difficulty()

        try:
            state = self._current_state()  # tracked buys included
        except ValueError as e:
            self.log(f"! {e}")
            self._plan_done()
            return

        def work():
            try:
                lo, hi, abs_pos, slots = state
                self._plan_input_win = slots
                result = plan_buys(
                    lo, hi, abs_pos, slots, ctx, specs=specs,
                    max_depth=depth, max_buys=buys, node_cap=400_000,
                    progress=lambda e, n: self.msgs.put(
                        ("plan_prog", min(1.0, n / 400_000))),
                    stop=stop)
                self.msgs.put(("plans", result, ctx))
            except Exception as e:
                self.msgs.put(("err", f"{type(e).__name__}: {e}"))

        threading.Thread(target=work, daemon=True).start()

    _TIER_NAMES = {0: "", 1: " (exceptional)", 2: " (elite)"}

    def _predict_names(self, display_idx, tier, quality):
        """The unique/set items this (already tier-specific) base can
        actually roll. One name = the purchase IS that item; several
        (rings, amulets…) = the game picks among them with extra server
        rolls. `tier` is unused — the display name already carries it."""
        if quality not in (Q_UNIQUE, Q_SET):
            return []
        db = _gamble_db()
        base = self.items[display_idx]["name"]
        cands = list(db["rev_u" if quality == Q_UNIQUE
                        else "rev_s"].get(base) or [])
        if len(cands) > 1:
            # jewelry: gate the option list by the reachable gamble ilvl
            fam = db["gamble"].get(base) or {}
            lst = fam.get("uniques" if quality == Q_UNIQUE else "sets") or []
            try:
                clvl = int(self.level.get())
            except (ValueError, tk.TclError):
                clvl = 85
            ok = {c["name"] for c in lst if c["alvl"] <= clvl + 4}
            gated = [n for n in cands if n in ok]
            if gated:
                cands = gated
        return cands

    def _predict_suffix(self, display_idx, tier, quality):
        """' = Shako' when determined, ' (1 of N)' when the game decides."""
        names = self._predict_names(display_idx, tier, quality)
        if len(names) == 1:
            return f" = {names[0]}"
        if len(names) > 1:
            return f" (1 of {len(names)})"
        return ""

    def _show_plans(self, result, ctx):
        it = self.items
        self.plans = result["plans"]
        self._plan_ctx = ctx
        tv = self.plans_tv
        tv.delete(*tv.get_children())
        note = " (node cap hit — deepen carefully)" if result["capped"] else ""
        if not self.plans:
            self.log(f"— planner: no route within depth/buys "
                     f"({result['explored']} states explored{note}) — raise "
                     "depth, or refresh manually and re-plan", "dim")
            self.plan_steps_lbl.configure(text="")
            return
        for i, p in enumerate(self.plans, 1):
            q = p["quality"]
            name = (it[p["recv_idx"]]["name"]
                    + self._TIER_NAMES.get(p["tier"], "")
                    + self._predict_suffix(p["recv_idx"], p["tier"], q))
            refreshes = sum(1 for st in p["steps"] if st["type"] == "R")
            tv.insert("", "end", iid=str(i - 1),
                      text=f" #{i:>2}  {QUALITY_NAMES.get(q, q)} {name}   ·  "
                           f"{refreshes} refresh, {p['buys']} buys"
                           f", {p['routes']} routes",
                      tags=(self._qtag(q) or "dim",))
        self.log(f"— planner: {len(self.plans)} route(s), best first "
                 f"({result['explored']} states{note}). Click a plan to see "
                 "its steps and the final window.", "hot")
        first = tv.get_children()[0]
        tv.selection_set(first)

    def _plan_pick(self, _ev=None):
        sel = self.plans_tv.selection()
        if not sel or not self.plans:
            return
        for s2 in self.prev_tv.selection():
            self.prev_tv.selection_remove(s2)
        i = int(sel[0])
        p = self.plans[i]
        it = self.items
        self.plan_no.delete(0, "end")
        self.plan_no.insert(0, str(i + 1))
        steps_txt = []
        run = 0
        for st in p["steps"]:
            if st["type"] == "R":
                run += 1
                continue
            if run:
                steps_txt.append(f"Refresh ×{run}" if run > 1 else "Refresh")
                run = 0
            verb = "Buy" if st["type"] == "B" else "COLLECT"
            steps_txt.append(f"{verb} {it[st['idx']]['name']}"
                             f"@({st['x']},{st['y']})")
        if run:
            steps_txt.append(f"Refresh ×{run}" if run > 1 else "Refresh")
        # what the target purchase actually BECOMES (options for rin/amu)
        cand = self._predict_names(p["recv_idx"], p["tier"], p["quality"])
        outcome = ""
        if len(cand) == 1:
            outcome = f"   ⇒ {cand[0]}"
        elif cand:
            shown = ", ".join(cand[:5]) + ("…" if len(cand) > 5 else "")
            outcome = f"   ⇒ one of {len(cand)}: {shown}"
        self.plan_steps_lbl.configure(
            text="  →  ".join(steps_txt) + outcome
                 + "   (Execute clicks this in game)")
        # preview the window WHERE YOU BUY the target (pre-collect state)
        last = p["steps"][-1]
        if len(p["steps"]) >= 2:
            win = p["steps"][-2]["win"]
        else:
            win = getattr(self, "_plan_input_win", None)
        if not win:
            return
        ctx = getattr(self, "_plan_ctx", None) or self._ctx()
        from advisor.gamble_seed import pack_grid
        pos = pack_grid([w["idx"] if w else 0 for w in win], ctx)
        slots = [{"idx": w["idx"], "x": pp[0], "y": pp[1],
                  "tier": w["tier"], "quality": w["quality"]}
                 for w, pp in zip(win, pos) if w and pp is not None]
        q = p["quality"]
        self._set_grid_preview(
            f"PLAN #{i + 1} — buy the {QUALITY_NAMES.get(q, q)} "
            f"{it[p['recv_idx']]['name']}"
            f"{self._predict_suffix(p['recv_idx'], p['tier'], q)}"
            f" at ({last['x']},{last['y']})",
            slots, source=("plan", i))

    # ------------------------------------------------------------- clicker

    def _capture_point(self, key, what, then=None, _guarded=False):
        """Countdown, then save the hovered cursor position as calib[key]."""
        from advisor import capture_guard
        if not _guarded:
            if not capture_guard.acquire(f"{what} calibration"):
                self.log(f"! busy: {capture_guard.busy_with()} is running")
                return

        def capture(countdown):
            if countdown > 0:
                self.status.configure(text=f"{what} — {countdown}…")
                self.log(f"  capturing in {countdown}…", "dim")
                self.after(1000, lambda: capture(countdown - 1))
            else:
                pos = get_cursor_pos()
                self.calib = load_calib()
                self.calib[key] = list(pos)
                save_calib(self.calib)
                self.status.configure(text="idle")
                self.log(f"  {key} = {pos} — saved")
                self._update_calib_lbl()
                if then:
                    then()
                else:
                    capture_guard.release()

        capture(4)

    def calibrate(self):
        """Capture the Refresh button position (cells auto-calibrate on F10)."""
        self.log("Hover the REFRESH button in game…", "hot")
        self._capture_point("refresh", "Refresh button")

    def calibrate_sell(self):
        """Two-corner SELL ZONE: the empty inventory area where purchases
        land (small items pack bottom-right, bigger ones higher — one slot
        is not enough). Filler buys are Ctrl+click-swept across it."""
        self.log("SELL ZONE — the empty inventory columns where bought "
                 "items land. Keep it EMPTY during runs: everything inside "
                 "gets sold! Hover its TOP-LEFT cell…", "hot")

        def second():
            self.log("…now hover the BOTTOM-RIGHT cell of the zone", "hot")

            def finish():
                c = load_calib()
                p1, p2 = c.pop("_sz1", None), c.pop("_sz2", None)
                if p1 and p2:
                    c["sellzone"] = [min(p1[0], p2[0]), min(p1[1], p2[1]),
                                     max(p1[0], p2[0]), max(p1[1], p2[1])]
                    c.pop("sellslot", None)  # zone supersedes the old slot
                    save_calib(c)
                    self.calib = c
                    from advisor.autoclicker import sell_points
                    n = len(sell_points(c))
                    self.log(f"  sell zone saved ({n} cells swept per "
                             "filler buy)", "hot")
                    self._update_calib_lbl()
                from advisor import capture_guard
                capture_guard.release()

            self._capture_point("_sz2", "Sell zone BOTTOM-RIGHT", then=finish, _guarded=True)

        self._capture_point("_sz1", "Sell zone TOP-LEFT", then=second)

    def execute(self):
        if not self.plans:
            self.log("! no plans — run Plan buys first")
            return
        try:
            no = int(self.plan_no.get())
            delay = float(self.click_delay.get())
        except ValueError:
            self.log("! bad plan number / delay")
            return
        if not (1 <= no <= len(self.plans)):
            self.log(f"! plan number must be 1..{len(self.plans)}")
            return
        self.calib = load_calib()
        if not calib_ok(self.calib):
            self.log("! clicker needs: (1) an F10 icon scan (auto-calibrates "
                     "the grid cells) and (2) Set Refresh button")
            return
        if getattr(self, "_executing", False):
            if self._exec_stop is not None:
                self._exec_stop.set()
                self.exec_btn.configure(text="⏳ stopping…")
            return
        self._executing = True
        self._exec_stop = threading.Event()
        exec_stop = self._exec_stop
        plan = self.plans[no - 1]
        self._exec_total = len(plan["steps"])
        self.exec_btn.configure(text=f"■ Stop (0/{self._exec_total})")
        wait_s = float(self.sf.get("execute_delay", 5))
        self.log(f"executing plan #{no} in {wait_s:.0f}s — focus the game "
                 "window! (ESC aborts)", "hot")
        from advisor.autoclicker import sell_points
        if sell_points(self.calib):
            self.log("  filler buys auto-sell back (Ctrl+click sweep over "
                     "the sell zone)", "dim")
        elif any(st["type"] == "B" for st in plan["steps"]):
            self.log("⚠ auto sell-back is OFF — click 'Set sell zone' first "
                     "(hover the two corners of the empty inventory area "
                     "where purchases land)", "hot")

        fillers = [(i, self.items[st["idx"]]["name"])
                   for i, st in enumerate(plan["steps"])
                   if st["type"] == "B"]

        def work():
            import time
            # visible focus countdown — Stop/ESC still work during it
            left = wait_s
            while left > 0:
                if exec_stop.is_set():
                    self.msgs.put(("clicked", 0, len(plan["steps"]),
                                   "cancelled before start", fillers,
                                   plan["steps"]))
                    return
                self.msgs.put(("exec_countdown", int(left + 0.999)))
                time.sleep(min(1.0, left))
                left -= 1.0
            done, err = execute_plan(
                plan["steps"], self.items, self.calib, delay=delay,
                on_step=lambda i, txt: self.msgs.put(
                    ("exec_step", i + 1, len(plan["steps"]), txt)),
                stop=exec_stop)
            self.msgs.put(("clicked", done, len(plan["steps"]), err, fillers,
                           plan["steps"]))

        threading.Thread(target=work, daemon=True).start()

    # ------------------------------------------------------------- polling

    def _poll(self):
        # one bad handler must never kill the polling loop (that made a
        # finished search look like "nothing happened")
        try:
            while True:
                m = self.msgs.get_nowait()
                try:
                    self._handle_msg(m)
                except Exception as e:
                    try:
                        self.log(f"! UI error on '{m[0]}': "
                                 f"{type(e).__name__}: {e}")
                        self._reset()
                    except Exception:
                        pass
        except queue.Empty:
            pass
        finally:
            self.after(150, self._poll)

    def _handle_msg(self, m):
        if True:
                if m[0] == "prog":
                    self.progress["value"] = m[1]
                    self.status.configure(text=f"{m[1] * 100:.1f}%")
                elif m[0] == "engine":
                    eng, info = m[1], m[2]
                    if eng == "node":
                        import re as _re
                        thr = (_re.search(r"(\d+) threads", info) or [None, "?"])[1]
                        self._engine_tag = f"{thr} threads"
                        self.log(f"Sweeping all 4,294,967,296 store seeds "
                                 f"against your {self._n_entries} items on "
                                 f"{thr} threads (site kernel).", "dim")
                    else:
                        self._engine_tag = "slow engine!"
                        self.log(f"! FALLBACK TO SLOW ENGINE: {info}", "hot")
                elif m[0] == "prog2":
                    self._indet = False
                    frac, done, rate = m[1], m[2], m[3]
                    # never move backwards: the warm-up creep may sit ahead
                    # of the first real slices — hold until reality catches up
                    self.progress["value"] = max(float(self.progress["value"]),
                                                 frac)
                    left = (1 - frac) * done / max(1.0, rate * frac)
                    eta = (f"ETA {left:.0f}s" if left < 90
                           else f"ETA {left / 60:.0f}m")
                    nmatch = getattr(self, "_match_count", 0)
                    mtxt = f"{nmatch} match(es)" if nmatch else "no matches yet"
                    tag = getattr(self, "_engine_tag", "")
                    self.status.configure(
                        text=f"{frac * 100:.1f}% · {rate / 1e6:.1f}M seeds/s · "
                             f"{eta} · {mtxt}"
                             + (f" · {tag}" if tag else ""))
                elif m[0] == "cand":
                    self._match_count = getattr(self, "_match_count", 0) + 1
                    self.log(f"CANDIDATE SEED: {m[1]} — search continues "
                             "(double-click it in CANDIDATES to use now)", "hot")
                    self.cand_list.insert("end", str(m[1]))
                    if not self.seed_var.get().strip():
                        self.seed_var.set(str(m[1]))
                        self.game_seed.set(False)
                        self.offset_var.set("0")
                elif m[0] == "plan_prog":
                    self.plan_btn.configure(
                        text=f"■ Cancel planning ({m[1] * 100:.0f}%)")
                elif m[0] == "off_prog":
                    self.off_btn.configure(
                        text=f"■ Cancel ({m[1] * 100:.0f}%)")
                elif m[0] == "err":
                    self.log("! " + m[1])
                    self._reset()
                    self._scan_done()
                    self._plan_done()
                    self._off_done()
                    self._exec_done()
                elif m[0] == "step":
                    self.log(m[1], "dim")
                elif m[0] == "exec_countdown":
                    self.exec_btn.configure(text=f"⏳ focus game! {m[1]}s")
                    self.log(f"  starting in {m[1]}s — focus the game "
                             "window!", "dim")
                elif m[0] == "exec_step":
                    k, total, txt = m[1], m[2], m[3]
                    self.exec_btn.configure(text=f"■ Stop ({k}/{total})")
                    self.log(f"  step {k}/{total}: {txt}", "dim")
                elif m[0] == "clicked":
                    done, total, err = m[1], m[2], m[3]
                    fillers = m[4] if len(m) > 4 else []
                    steps = m[5] if len(m) > 5 else []
                    self._exec_done()
                    if err:
                        self.log(f"clicker stopped after {done}/{total}: {err}",
                                 "hot")
                    else:
                        self.log(f"plan executed — {done}/{total} clicks done.",
                                 "hot")
                    self._apply_run_state(steps, done)
                    from advisor.autoclicker import sell_points
                    bought = [name for i, name in fillers if i < done]
                    if bought and sell_points(self.calib):
                        self.log("💰 fillers auto-sold back (zone sweep): "
                                 + ", ".join(bought)
                                 + " (selling consumes no RNG)", "hot")
                    elif bought:
                        self.log("💰 sell back MANUALLY (no sell zone set — "
                                 "use 'Set sell zone' to automate): Ctrl+click "
                                 "each in your inventory at Gheed (no RNG "
                                 "cost): " + ", ".join(bought), "hot")
                    if not err:
                        self.log("mark further buys with 🛒, or F10 + Find "
                                 "offset to resync.", "dim")
                elif m[0] == "done":
                    found = m[1]
                    self._reset()
                    self.log(f"— search finished: {len(found)} candidate(s)",
                             "hot" if found else "dim")
                    # Stop kills the pool — re-warm it for the next search
                    threading.Thread(target=self._prewarm, daemon=True).start()
                    if not found:
                        self.log("no seed matched — recheck items / level / "
                                 "platform (or the offer got refreshed mid-scan)")
                    if len(found) > 1:
                        self.log(f"{len(found)} seeds match — refresh once in "
                                 "game, F10, search again to disambiguate")
                    if found:
                        self._clear_session("new seed")
                    for sd in found:
                        if str(sd) not in self.cand_list.get(0, "end"):
                            self.cand_list.insert("end", str(sd))
                        self.log(f"SEED FOUND: {sd}", "hot")
                        self.seed_var.set(str(sd))
                        self.game_seed.set(False)
                        self.offset_var.set("0")
                    if found:
                        # the loop left found[-1] in the field while the
                        # preview showed found[0]
                        self.seed_var.set(str(found[0]))
                        try:
                            n_prev = int(self.n_refresh.get() or 30)
                        except ValueError:
                            n_prev = 30
                        self.show_future(found[0], n_prev)
                elif m[0] == "offs":
                    offs, seed = m[1], m[2]
                    self._off_done()
                    if not offs:
                        self.log("no offset matched — raise max, or recheck "
                                 "the current offer")
                    if offs:
                        self._clear_session("offset resync")
                        self._invalidate(plans=True)
                    for k in offs:
                        self.log(f"OFFSET FOUND: {k} (0 = original offer)", "hot")
                        self.offset_var.set(str(k))
                        self.show_future(seed, int(self.n_refresh.get() or 30),
                                         offset=k)
                elif m[0] == "scan_ok":
                    self._scan_done()
                    self._invalidate(plans=True, preview=True,
                                     candidates=True)
                    self._clear_session("new scan")
                    entries, mi = m[1], m[2]
                    self.slots = [{"idx": i, "x": x, "y": y}
                                  for i, x, y in entries]
                    self.unplaced = []
                    self.redraw()
                    self._update_calib_lbl()
                    self.log(f"monitor {mi}: {len(entries)}/14 items read from "
                             "the screen — click any cell to correct", "hot")
                elif m[0] == "scan_fail":
                    self._scan_done()
                    for d in m[1]:
                        self.log("! " + d)
                    self.log("if this window covers the store grid, move it "
                             "aside and scan again", "dim")
                elif m[0] == "plans":
                    self._plan_done()
                    self._show_plans(m[1], m[2])

    # ------------------------------------------------------------- preview

    def show_future(self, seed, n=30, offset=0):
        ctx = self._ctx()
        it = self.items
        npc, diff = self._npc(), self._difficulty()
        if self._session is not None:
            from advisor.gamble_seed import chain_from_state
            st = self._session
            chain, post = chain_from_state(st["lo"], st["hi"], ctx, n)
            self._preview_chain = {"session": True, "chain": chain,
                                   "post": post}
        else:
            chain = refresh_chain_full(seed, ctx, n, offset=offset, npc=npc,
                                       difficulty=diff)
            self._preview_chain = {"seed": seed, "offset": offset,
                                   "chain": chain}
        tv = self.prev_tv
        tv.delete(*tv.get_children())
        total_hot = 0
        for k, offer in enumerate(chain, 1):
            hots = [sl for sl in offer
                    if sl["quality"] in (Q_UNIQUE, Q_SET)
                    and sl["pos"] is not None]
            total_hot += len(hots)
            if hots:
                txt = " + ".join(
                    f"{QUALITY_NAMES[sl['quality']]} "
                    f"{it[ctx.display_idx(sl['idx'], sl['tier'])]['name']}"
                    f"{self._predict_suffix(ctx.display_idx(sl['idx'], sl['tier']), sl['tier'], sl['quality'])}"
                    f"@({sl['pos'][0]},{sl['pos'][1]})" for sl in hots)
                tag = ("uni" if any(sl["quality"] == Q_UNIQUE for sl in hots)
                       else "set")
            else:
                names = ", ".join(it[sl["idx"]]["name"] for sl in offer[2:6]
                                  if sl["pos"] is not None)
                txt = names + ", …"
                tag = "dim"
            tv.insert("", "end", iid=str(k - 1), text=f" R{k:>3}   {txt}",
                      tags=(tag,))
        if self._session is not None:
            n_buys = self._session.get("buys", 0)
            src = f"the TRACKED state ({n_buys} buys applied)"
        else:
            src = f"seed {seed}" + (f" from offset {offset}" if offset else "")
        self.log(f"— preview ready: {n} refreshes for {src} at "
                 f"{npc}/{DIFFICULTIES[diff]} — {total_hot} UNIQUE/SET. "
                 "Click a row above the planner to SEE that window.",
                 "hot" if total_hot else "dim")

    def _buy_mode_toggle(self):
        """Arm buy mode: the next click on a grid item applies that PURCHASE
        to the tracked state — the RNG advances by the exact rolls the buy
        consumes and the slot rerolls, all without rescanning."""
        if self._buy_mode:
            self._buy_mode = False
            self.buy_btn.configure(bg="#332817", fg=FG)
            return
        try:
            self._seed()
        except ValueError as e:
            self.log(f"! {e}")
            return
        self._buy_mode = True
        self.buy_btn.configure(bg=GOLD, fg="#191307")
        self.log("buy mode: click the item you just bought on the grid "
                 "(button again cancels)", "hot")

    def _current_state(self):
        """(lo, hi, abs_pos, win) — from tracked buys or from seed+offset."""
        if self._session is not None:
            st = self._session
            return st["lo"], st["hi"], st["abs_pos"], st["win"]
        from advisor.gamble_seed import state_after_offer as sao
        return sao(self._seed(), self._ctx(), self._offset(),
                   self._npc(), self._difficulty())

    def _apply_buy(self, hit):
        from advisor.gamble_seed import buy_roll, pack_grid
        ctx = self._ctx()
        it = self.items
        try:
            lo, hi, abs_pos, win = self._current_state()
        except ValueError as e:
            self.log(f"! {e}")
            return
        gx, gy = self.slots[hit]["x"], self.slots[hit]["y"]
        pos = pack_grid([w["idx"] for w in win], ctx)
        m = next((i for i, p in enumerate(pos) if p == (gx, gy)), None)
        if m is None:  # grid was hand-edited; fall back to item identity
            m = next((i for i, w in enumerate(win)
                      if w["idx"] == self.slots[hit]["idx"]), None)
        if m is None:
            self.log("! that item doesn't match the tracked window — use "
                     "Find offset to resync instead")
            return
        bought = it[win[m]["idx"]]["name"]
        new_slot, steps, lo2, hi2 = buy_roll(lo, hi, win[m]["idx"], ctx)
        win = list(win)
        win[m] = new_slot
        buys = (self._session or {}).get("buys", 0) + 1
        self._session = {"lo": lo2, "hi": hi2, "abs_pos": abs_pos + steps,
                         "win": win, "buys": buys}
        self._update_state_lbl()
        self._invalidate(plans=True, why="state advanced by the buy")
        # the game keeps the slot's position; the item just rerolls
        self.slots[hit]["idx"] = new_slot["idx"]
        self.redraw()
        q = new_slot["quality"]
        self.log(f"bought {bought} (+{steps} rolls) — the slot rerolled to "
                 f"{QUALITY_NAMES.get(q, '')} {it[new_slot['idx']]['name']}. "
                 f"State tracked ({buys} buys); previews and the planner "
                 "continue from it.", "hot")
        self.show_future(None, int(self.n_refresh.get() or 30))

    def _apply_run_state(self, steps, done):
        """After an auto-clicker run (finished OR stopped), the RNG state
        after the executed steps becomes the tracked CURRENT state — the
        grid, previews and the planner continue from it automatically."""
        if done <= 0 or not steps or "lo" not in steps[0]:
            return
        run = steps[:done]
        last = run[-1]
        win = last["win"]
        if any(w is None for w in win):
            self.log("(state not auto-applied: classic removes bought slots "
                     "— F10 + Find offset to resync)", "dim")
            return
        from advisor.gamble_seed import pack_grid
        buys_ct = sum(1 for st in run if st["type"] in ("B", "C"))
        prev = (self._session or {}).get("buys", 0)
        self._session = {"lo": last["lo"], "hi": last["hi"],
                         "abs_pos": last["abs"], "win": list(win),
                         "buys": prev + buys_ct}
        self._update_state_lbl()
        self._invalidate(plans=True, why="plans consumed by the run")
        # positions come from the LAST refresh's packing; buys after it
        # reroll IN PLACE (the game keeps the slot position)
        base = max((i for i, st in enumerate(run) if st["type"] == "R"),
                   default=-1)
        base_win = run[base]["win"] if base >= 0 else win
        pos = pack_grid([w["idx"] for w in base_win], self._ctx())
        idx_map, slots = {}, []
        for wi, (w, p) in enumerate(zip(base_win, pos)):
            if p is not None:
                idx_map[wi] = len(slots)
                slots.append({"idx": w["idx"], "x": p[0], "y": p[1]})
        for st in run[base + 1:] if base >= 0 else []:
            k = st["slot"]
            if k in idx_map and st["win"][k] is not None:
                slots[idx_map[k]]["idx"] = st["win"][k]["idx"]
        self.slots = slots
        self.unplaced = []
        self.redraw()
        self.log(f"✔ state auto-applied after the run ({len(run)} steps, "
                 f"{buys_ct} buys) — grid shows the store as it is NOW; "
                 "previews/planner continue from it.", "hot")
        try:
            self.show_future(None, int(self.n_refresh.get() or 30))
        except Exception:
            pass

    def _update_state_lbl(self):
        st = self._session
        n_buys = st.get("buys", 0) if st else 0
        self.state_lbl.configure(
            text=f"● tracked state · {n_buys} buy(s)" if st else "")

    def _invalidate(self, plans=False, preview=False, candidates=False,
                    why=""):
        """Stale-state hygiene: whatever changed the underlying RNG state
        or its inputs must clear every result computed from the OLD one."""
        cleared = False
        if plans and (self.plans or self.plans_tv.get_children()):
            self.plans = []
            self.plans_tv.delete(*self.plans_tv.get_children())
            self.plan_steps_lbl.configure(text="")
            cleared = True
        if preview and (self._preview_chain is not None
                        or self.prev_tv.get_children()):
            self.prev_tv.delete(*self.prev_tv.get_children())
            self._preview_chain = None
            self._preview_off()
            cleared = True
        if candidates and self.cand_list.size():
            self.cand_list.delete(0, "end")
            cleared = True
        if candidates and self.seed_var.get().strip():
            # the old seed silently fed Preview/Plan during a new search
            self.seed_var.set("")
            self.offset_var.set("0")
            cleared = True
        if why and cleared:
            self.log(f"({why} — stale results cleared)", "dim")

    def _settings_changed(self, *_):
        """Level/platform/version/NPC/difficulty define the RNG context —
        every computed result and the tracked session die with the old one."""
        self._clear_session("settings changed")
        self._invalidate(plans=True, preview=True, candidates=True,
                         why="settings changed")

    def _clear_session(self, why=""):
        if self._session is not None:
            self._session = None
            if why:
                self.log(f"tracked buy-state cleared ({why})", "dim")
        self._update_state_lbl()

    def _apply_preview_state(self, *_):
        """You refreshed in game up to the selected row — make that window
        the CURRENT state: offset moves there, the grid takes its items,
        and planner/preview/offset-resync all continue from it."""
        pc = self._preview_chain
        sel = self.prev_tv.selection()
        if not pc or not sel:
            if self._session is not None:
                self.log("your buy is ALREADY the current state — use "
                         "apply only if you also refreshed in game "
                         "(pick the row you are at first)", "dim")
            else:
                self.log("! pick the refresh row you are now AT, then apply")
            return
        k = int(sel[0])
        offer = pc["chain"][k]
        self.slots = [{"idx": sl["idx"], "x": sl["pos"][0], "y": sl["pos"][1]}
                      for sl in offer if sl["pos"] is not None]
        self.unplaced = []
        self._invalidate(plans=True, why="state moved to the applied refresh")
        if pc.get("session"):
            # advance the tracked (post-buy) state to that window
            from advisor.gamble_seed import count_steps
            st = self._session
            nlo, nhi = pc["post"][k]
            steps = count_steps(st["lo"], st["hi"], nlo, nhi,
                                limit=(k + 1) * 200)
            self._session = {"lo": nlo, "hi": nhi,
                             "abs_pos": st["abs_pos"] + steps,
                             "win": [{"idx": sl["idx"], "tier": sl["tier"],
                                      "quality": sl["quality"]}
                                     for sl in offer],
                             "buys": st.get("buys", 0)}
            self._update_state_lbl()
            self._preview_off()
            self.log(f"applied refresh R{k + 1} on the tracked state — "
                     "everything continues from it.", "hot")
            self.show_future(None, len(pc["chain"]))
            return
        from advisor.gamble_seed import chain_offsets
        ctx = self._ctx()
        offs = chain_offsets(pc["seed"], ctx, k + 1, offset=pc["offset"],
                             npc=self._npc(), difficulty=self._difficulty())
        new_off = offs[k]
        self.offset_var.set(str(new_off))
        self._preview_off()
        self.log(f"applied refresh R{k + 1} as the current state — offset "
                 f"{new_off}. Planner, previews and Find offset now continue "
                 "from here.", "hot")
        self.show_future(pc["seed"], len(pc["chain"]), offset=new_off)

    def _preview_pick(self, _ev=None):
        pc = self._preview_chain
        sel = self.prev_tv.selection()
        if not pc or not sel:
            return
        for s2 in self.plans_tv.selection():
            self.plans_tv.selection_remove(s2)
        k = int(sel[0])
        offer = pc["chain"][k]
        slots = [{"idx": sl["idx"], "x": sl["pos"][0], "y": sl["pos"][1],
                  "tier": sl["tier"], "quality": sl["quality"]}
                 for sl in offer if sl["pos"] is not None]
        self._set_grid_preview(f"PREVIEW — refresh R{k + 1}", slots,
                               source=("refresh", k))


def open_seed_finder(root, char_level=85, get_last_offer=None,
                     get_last_entries=None, ui_scale=1.0, cfg=None):
    global _open_window
    try:
        if _open_window is not None and _open_window.winfo_exists():
            if get_last_offer:
                _open_window.get_last_offer = get_last_offer
            if get_last_entries:
                _open_window.get_last_entries = get_last_entries
            if get_last_offer or get_last_entries:
                _open_window.fill_from_scan(quiet=True)
            _open_window.deiconify()
            _open_window.lift()
            return _open_window
    except tk.TclError:
        pass
    _open_window = None
    w = SeedFinder(root, char_level, get_last_offer, get_last_entries,
                   ui_scale=ui_scale, cfg=cfg)
    # content taller/wider than the screen: reopen at a scale that FITS
    # (a widescreen 1080p monitor clipped the auto-clicker row entirely)
    if w.fit_factor < 0.97:
        smaller = max(0.8, float(ui_scale or 1.0) * w.fit_factor)
        w.destroy()
        w = SeedFinder(root, char_level, get_last_offer, get_last_entries,
                       ui_scale=smaller, cfg=cfg)
    _open_window = w
    return w
