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


def _render_affix(tmpl, params):
    """Substitute parsed params back into an affix template for display."""
    out = tmpl
    for p in params or []:
        token = "#" if isinstance(p, (int, float)) else "["
        i = out.find(token)
        if i < 0:
            continue
        if token == "#":
            out = out[:i] + str(p) + out[i + 1:]
        else:
            j = out.find("]", i)
            out = out[:i] + str(p) + out[j + 1:] if j >= 0 else out
    return out


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
        """Trade-chat-ready text for the shown item."""
        name = item.get("name") or item.get("base") or "?"
        head = name
        quality, base = item.get("quality") or "", item.get("base") or ""
        if quality or (base and base != name):
            bits = [b for b in (quality, base if base != name else "") if b]
            head += f" ({' '.join(bits)})"
        stats = []
        if ranges:
            for p in ranges:
                s = p["label"]
                if "roll" in p:
                    s += f" = {p['roll']}" + (" (perfect)" if p.get("perfect") else "")
                stats.append(s)
        else:
            for tmpl, params in item.get("affixes") or []:
                stats.append(_render_affix(tmpl, params))
        return head + (" | " + "; ".join(stats) if stats else "")

    def _copy_clip(self, event=None):
        if self._clip:
            try:
                self.root.clipboard_clear()
                self.root.clipboard_append(self._clip)
                print(f"copied: {self._clip}")
            except Exception:
                pass
        return "break"

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

            def _open(event, u=link):
                try:
                    if callable(u):  # in-app action, not a web link
                        u()
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

    def show(self, verdict, item=None, rule="", note="", pos=None, seconds=8, ranges=None,
             screen_rect=None, extra=None, tier=None):
        self.hide()
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
            for entry in extra:
                text, color = entry[0], entry[1]
                link = entry[2] if len(entry) > 2 else None
                self._label(win, bg, text, size=10, fg=color, link=link)

        if rule:
            self._label(win, bg, f"Rule: {rule}", size=9, fg="#999999", pady=(4, 0))
        if note:
            self._label(win, bg, note, size=10, fg="#cccccc", italic=True, pady=(2, 8))
        else:
            tk.Label(win, text="", bg=bg).pack(pady=(0, self._fs(6)))

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
        # Right-click anywhere on the popup: copy trade-ready item text.
        self._clip = f"[{title}] " + self._clip_text(verdict, item, ranges) if item else ""
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
