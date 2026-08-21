"""Always-on-top verdict popup (tkinter)."""
import tkinter as tk
import webbrowser

COLORS = {
    "keep": ("#0d3311", "#4dff64"),    # bg, accent
    "check": ("#332b0d", "#ffd94d"),
    "trash": ("#330d0d", "#ff6a4d"),
    "error": ("#222222", "#cccccc"),
    "scan": ("#101c2b", "#6db3f2"),    # in-progress notice
    "compare": ("#101c2b", "#6db3f2"),  # gear diff vs equipped
}
TITLES = {
    "keep": "KEEP",
    "check": "CHECK",
    "trash": "TRASH",
    "error": "ERROR",
    "scan": "SCANNING…",
    "compare": "COMPARE",
}
# D2 item-name colors, for the recognized item line.
QUALITY_COLORS = {
    "Unique": "#c7b377",
    "Set": "#00fc00",
    "Runeword": "#c7b377",
    "Rare": "#ffff6e",
    "Crafted": "#ffa800",
    "Magic": "#7e7eff",
    "Base": "#e8e8e8",
}
MAX_STAT_LINES = 14


from advisor.render import render_affix as _render_affix


class Overlay:
    def __init__(self, root, scale=1.5):
        self.root = root
        self.scale = scale
        self.win = None
        self._close_job = None
        self._clip = ""

    def _fs(self, size):
        return max(8, int(size * self.scale))

    def _clip_text(self, verdict, item, ranges):
        """Trade-ready text for the shown item: a header line and one stat
        per line (a single semicolon-joined blob was unreadable once an
        item had more than three affixes)."""
        name = item.get("name") or item.get("base") or "?"
        quality, base = item.get("quality") or "", item.get("base") or ""
        sub = [b for b in (quality, base if base != name else "",
                           item.get("tier") or "") if b and b != "Normal"]
        lines = [f"[{verdict.upper()}] {name}"]
        if sub:
            lines.append(" · ".join(sub))
        if ranges:
            for p in ranges:
                text = p["label"]
                if "roll" in p:
                    text += f" -> {p['roll']}"
                    if p.get("perfect"):
                        text += " (MAX)"
                    elif p.get("offrange"):
                        text += " (?)"
                lines.append(f"  {text}")
        else:
            for tmpl, params in item.get("affixes") or []:
                lines.append(f"  {_render_affix(tmpl, params)}")
        return "\n".join(lines)

    def _copy_clip(self, event=None):
        if not self._clip:
            return "break"
        try:
            self.root.clipboard_clear()
            self.root.clipboard_append(self._clip)
            print("copied:\n" + self._clip)
            self._flash_hint("✓ copied to clipboard", "#4dff64")
        except Exception:
            self._flash_hint("could not reach the clipboard", "#ff9a6a")
        return "break"

    def _flash_hint(self, text, color):
        """The copy/tuning affordances used to act with NO visible sign —
        say what happened on the hint line, then restore it."""
        lbl = getattr(self, "_hint_lbl", None)
        if lbl is None:
            return
        try:
            was = (lbl.cget("text"), lbl.cget("fg"))
            lbl.configure(text=text, fg=color)
            self.root.after(1800, lambda: self._restore_hint(lbl, was))
        except tk.TclError:
            pass

    def _restore_hint(self, lbl, was):
        try:
            lbl.configure(text=was[0], fg=was[1])
        except tk.TclError:
            pass

    def _label(self, win, bg, text, size=10, fg="#cccccc", bold=False, italic=False,
               pady=(0, 0), link=None):
        style = []
        if bold:
            style.append("bold")
        if italic:
            style.append("italic")
        if link:
            style.append("underline")
        lbl = tk.Label(
            win, text=text, font=("Segoe UI", self._fs(size), *style), fg=fg, bg=bg,
            wraplength=self._fs(400), justify="left",
        )
        lbl.pack(padx=self._fs(14), pady=(self._fs(pady[0]), self._fs(pady[1])), anchor="w")
        lbl.bind("<Button-3>", self._copy_clip)
        if link:
            lbl.configure(cursor="hand2")

            def _open(event, u=link, lbl=lbl, size=size):
                try:
                    if callable(u):  # in-app action, not a web link
                        said = u()
                        # clicking used to do its work in total silence
                        if isinstance(said, str) and said:
                            lbl.configure(text=said, fg="#4dff64",
                                          cursor="",
                                          font=("Segoe UI", self._fs(size)))
                            lbl.unbind("<Button-1>")
                    else:
                        webbrowser.open(u)
                except Exception:
                    pass
                return "break"  # keep the popup open (window click closes it)

            lbl.bind("<Button-1>", _open)

    def _stat_lines(self, item, ranges):
        """Yield (text, color) stat lines: ranges for uniques/sets, parsed affixes otherwise."""
        lines = []
        if ranges:
            for p in ranges:
                text, color = p["label"], "#9a9a9a"
                if p.get("var"):
                    color = "#e8e8e8"
                    if "roll" in p:
                        if p.get("offrange"):
                            text += f"  → roll: {p['roll']} (out of range — check by eye)"
                            color = "#ff9a6a"
                        elif p.get("perfect"):
                            text += f"  → roll: {p['roll']} ★ MAX"
                            color = "#4dff64"
                        else:
                            text += f"  → roll: {p['roll']}"
                            color = "#ffd94d"
                lines.append((text, color))
        else:
            uncertain = item.get("uncertain") or {}
            for entry in item.get("affixes") or []:
                text = _render_affix(entry[0], entry[1])
                if entry[0] in uncertain:
                    alts = "/".join(str(v) for v in uncertain[entry[0]])
                    lines.append((f"{text}  ⚠ {alts}? — check by eye",
                                  "#ff9a6a"))
                else:
                    lines.append((text, "#e8e8e8"))
        return lines

    TIER_STYLE = {
        "S": ("#ffd700", "S-tier — chase item!"),
        "A": ("#4dff64", "A-tier — solid value"),
        "B": ("#9ecfff", "B-tier — useful / situational"),
        "C": ("#9a9a9a", "C-tier — low value"),
    }

    def _extra_block(self, win, bg, extra):
        """Render the advice lines. Sections (separated by a blank entry —
        compare emits one per equipped item) go SIDE BY SIDE: stacked, two
        20-line diffs ran the popup off the bottom of the screen."""
        sections, cur = [], []
        for entry in extra:
            if not str(entry[0]).strip():
                if cur:
                    sections.append(cur)
                cur = []
                continue
            cur.append(entry)
        if cur:
            sections.append(cur)
        if not sections:
            return
        holder = tk.Frame(win, bg=bg)
        holder.pack(fill="x")
        for col, section in enumerate(sections):
            frame = tk.Frame(holder, bg=bg)
            frame.grid(row=0, column=col, sticky="nw",
                       padx=(0, self._fs(10) if col < len(sections) - 1 else 0))
            for entry in section:
                text, color = entry[0], entry[1]
                link = entry[2] if len(entry) > 2 else None
                self._label(frame, bg, text, size=10, fg=color, link=link)

    def show(self, verdict, item=None, rule="", note="", pos=None, seconds=8, ranges=None,
             screen_rect=None, extra=None, tier=None):
        self.hide()
        self._hint_lbl = None   # belongs to the window we just destroyed
        bg, accent = COLORS.get(verdict, COLORS["error"])
        title = TITLES.get(verdict, verdict.upper())

        win = tk.Toplevel(self.root)
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        try:
            win.attributes("-alpha", 0.94)
        except tk.TclError:
            pass
        win.configure(bg=bg, highlightthickness=3, highlightbackground=accent)

        tk.Label(win, text=title, font=("Segoe UI", self._fs(18), "bold"), fg=accent, bg=bg).pack(
            padx=self._fs(14), pady=(self._fs(8), self._fs(2))
        )

        if item:
            quality = item.get("quality") or ""
            name = item.get("name") or item.get("base") or "?"
            base = item.get("base") or ""
            # Magic names matched by suffix alone read awkwardly ("of the
            # Apprentice") — prepend the base for display.
            if base and name.lower().startswith("of "):
                name = f"{base} {name}"
            q_color = QUALITY_COLORS.get(quality, "#e8e8e8")
            # Recognized uniques/sets/runewords: clickable name -> web lookup.
            name_link = None
            if quality in ("Unique", "Set", "Runeword") and item.get("name"):
                from advisor.links import item_url
                name_link = item_url(item["name"])
            self._label(win, bg, f"{name}", size=13, fg=q_color, bold=True, link=name_link)
            sub = quality
            if base and base != name:
                sub += f" · {base}"
            if item.get("tier") and item.get("tier") != "Normal":
                sub += f" · {item['tier']}"
            if sub:
                self._label(win, bg, sub, size=10, fg="#bbbbbb")

            if tier:
                grade, tier_note = tier
                color, default_label = self.TIER_STYLE.get(grade, ("#bbbbbb", grade))
                text = f"★ {default_label}"
                if tier_note:
                    text += f" · {tier_note}"
                self._label(win, bg, text, size=10, fg=color, bold=True)

            stat_lines = self._stat_lines(item, ranges)
            if stat_lines:
                tk.Frame(win, bg=accent, height=1).pack(fill="x", padx=self._fs(14), pady=self._fs(4))
                for text, color in stat_lines[:MAX_STAT_LINES]:
                    self._label(win, bg, text, size=10, fg=color)
                hidden = len(stat_lines) - MAX_STAT_LINES
                if hidden > 0:
                    self._label(win, bg, f"… {hidden} more", size=9, fg="#888888")

        # Extra advice block (e.g. runewords that fit this base). Entries are
        # (text, color) or (text, color, url) — the latter renders as a link.
        if item and extra:
            tk.Frame(win, bg=accent, height=1).pack(fill="x", padx=self._fs(14), pady=self._fs(4))
            self._extra_block(win, bg, extra)

        if rule:
            self._label(win, bg, f"Rule: {rule}", size=9, fg="#999999", pady=(4, 0))
        if note:
            self._label(win, bg, note, size=10, fg="#cccccc", italic=True, pady=(2, 8))
        else:
            tk.Label(win, text="", bg=bg).pack(pady=(0, self._fs(6)))
        copyable = bool(item) and verdict not in ("compare", "scan", "error")
        if item:
            # the copy affordance was invisible — nothing hinted at it
            hint = ("right-click: copy for trade chat · click: close"
                    if copyable else "click: close")
            self._hint_lbl = tk.Label(
                win, text=hint, font=("Segoe UI", self._fs(8)),
                fg="#777777", bg=bg)
            self._hint_lbl.pack(pady=(0, self._fs(4)))

        win.update_idletasks()
        w, h = win.winfo_reqwidth(), win.winfo_reqheight()
        # Clamp to the monitor the scan happened on (multi-monitor safe);
        # fall back to the primary screen when unknown.
        if screen_rect:
            sx, sy, sw, sh = screen_rect
        else:
            sx, sy = 0, 0
            sw, sh = win.winfo_screenwidth(), win.winfo_screenheight()
        if pos:
            x = min(max(pos[0] + 28, sx), sx + sw - w - 8)
            y = min(max(pos[1] - h - 28, sy), sy + sh - h - 8)
        else:
            x, y = sx + (sw - w) // 2, sy + 80
        win.geometry(f"+{x}+{y}")
        win.bind("<Button-1>", lambda e: self.hide())
        win.bind("<Escape>", lambda e: self.hide())
        # Right-click anywhere on the popup: copy trade-ready item text.
        # Compare diffs are not a tradeable item — no clip, no hint.
        self._clip = (self._clip_text(verdict, item, ranges)
                      if copyable else "")
        if copyable:
            win.bind("<Button-3>", self._copy_clip)

        self.win = win
        self._close_job = self.root.after(int(seconds * 1000), self.hide)

    def hide(self):
        if self._close_job:
            try:
                self.root.after_cancel(self._close_job)
            except Exception:
                pass
            self._close_job = None
        if self.win:
            try:
                self.win.destroy()
            except Exception:
                pass
            self.win = None
