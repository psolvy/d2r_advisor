"""First-run wizard.

The exe used to start silently into the tray-overflow area with the
maintainer's 4K defaults. On a genuinely fresh install (no marker, no
calibrations, no season state) this window comes up once: suggests a
popup scale derived from the actual monitor, shows the hotkeys (with a
duplicate check), and installs Tesseract in one click.
"""
import shutil
import subprocess
import threading
import tkinter as tk

from advisor.paths import STATE_DIR

_MARKER = STATE_DIR / ".onboarded"


def should_show(cfg):
    if _MARKER.exists():
        return False
    # an install that already has calibrations or season state belongs to
    # an existing user — don't nag, just drop the marker
    if (STATE_DIR / "gamble_clicks.json").exists() \
            or (STATE_DIR / "season_goals.json").exists():
        mark_done()
        return False
    return True


def mark_done():
    try:
        _MARKER.write_text("", encoding="utf-8")
    except OSError:
        pass


def suggest_scale(screen_h):
    """Popup scale matched to the monitor (1080p -> 1.0, 4K -> 2.0)."""
    return max(1.0, min(3.0, round(screen_h / 1080.0 * 4) / 4))


def hotkey_rows(cfg):
    """[(label, key, clash_bool)] — duplicates flagged."""
    keys = [("Item verdict", str(cfg.get("hotkey", "f9"))),
            ("Gear compare", str(cfg.get("compare_hotkey", "shift+f9"))),
            ("Gamble offer", str(cfg.get("gamble_hotkey", "f10"))),
            ("Seed Finder", str(cfg.get("seed_hotkey", "shift+f10")))]
    seen = {}
    for _lbl, k in keys:
        seen[k.lower()] = seen.get(k.lower(), 0) + 1
    return [(lbl, k, seen[k.lower()] > 1) for lbl, k in keys]


def open_wizard(root, cfg, scale=1.0):
    from advisor.seedfinder_ui import BG, DIM, FG, FIELD, GOLD, GOLD_HI, \
        GREEN, LINE, PANEL, RED
    from advisor.app import resolve_tesseract

    s = max(1.0, float(scale))
    win = tk.Toplevel(root)
    win.title("D2R Item Advisor — Welcome")
    win.configure(bg=BG)
    win.resizable(False, False)
    f_head = ("Segoe UI", int(13 * s), "bold")
    f_base = ("Segoe UI", int(11 * s))
    f_sub = ("Segoe UI", int(10 * s))
    pad = int(14 * s)

    tk.Label(win, text="WELCOME — 30-SECOND SETUP", bg=BG, fg=GOLD_HI,
             font=f_head).pack(anchor="w", padx=pad, pady=(pad, 2))
    tk.Label(win, text="The app lives in the system tray (check the ^ "
             "overflow area). Everything below is editable later in "
             "Settings.", bg=BG, fg=DIM, font=f_sub,
             wraplength=int(460 * s), justify="left"
             ).pack(anchor="w", padx=pad)

    body = tk.Frame(win, bg=PANEL, highlightthickness=1,
                    highlightbackground=LINE)
    body.pack(fill="x", padx=pad, pady=(int(8 * s), 0))

    # 1) scale from the real monitor
    sh = win.winfo_screenheight()
    suggested = suggest_scale(sh)
    current = float(cfg.get("ui_scale", 1.5))
    row = tk.Frame(body, bg=PANEL)
    row.pack(fill="x", padx=8, pady=(6, 2))
    tk.Label(row, text=f"Popup scale: your monitor is {sh}px tall → "
             f"suggested {suggested} (config has {current})",
             bg=PANEL, fg=FG, font=f_base).pack(side="left")
    status = tk.Label(win, text="", bg=BG, fg=GREEN, font=f_sub)

    def apply_scale():
        try:
            from advisor.settings_ui import write_config
            write_config({"ui_scale": suggested}, {})
            status.configure(text=f"✓ ui_scale = {suggested} saved — "
                             "applies after restart", fg=GREEN)
        except Exception as e:
            status.configure(text=f"✕ {e}", fg=RED)

    if abs(suggested - current) >= 0.25:
        tk.Button(row, text=f"Use {suggested}", command=apply_scale,
                  bg=GOLD, fg="#191307", relief="flat", font=f_sub,
                  padx=8).pack(side="right")

    # 2) hotkeys + duplicate check
    for lbl, key, clash in hotkey_rows(cfg):
        color = RED if clash else FG
        suffix = "  ← duplicate!" if clash else ""
        tk.Label(body, text=f"{lbl}: {key.upper()}{suffix}", bg=PANEL,
                 fg=color, font=f_sub).pack(anchor="w", padx=8)

    # 3) tesseract
    tess = resolve_tesseract(cfg)
    trow = tk.Frame(body, bg=PANEL)
    trow.pack(fill="x", padx=8, pady=(4, 6))
    if tess:
        tk.Label(trow, text="✓ Tesseract OCR found — verdicts ready",
                 bg=PANEL, fg=GREEN, font=f_base).pack(side="left")
    else:
        tlbl = tk.Label(trow, text="✕ Tesseract OCR missing — tooltip "
                        "verdicts are disabled", bg=PANEL, fg=RED,
                        font=f_base)
        tlbl.pack(side="left")

        def install_tess():
            btn.configure(state="disabled", text="installing…")

            def work():
                winget = shutil.which("winget")
                if not winget:
                    root.after(0, lambda: tlbl.configure(
                        text="✕ winget not found — install Tesseract from "
                             "github.com/UB-Mannheim/tesseract/wiki"))
                    return
                r = subprocess.run(
                    [winget, "install", "-e", "--id",
                     "UB-Mannheim.TesseractOCR", "--silent",
                     "--accept-package-agreements",
                     "--accept-source-agreements"],
                    capture_output=True, text=True, timeout=600)
                ok = r.returncode == 0
                root.after(0, lambda: tlbl.configure(
                    text="✓ Tesseract installed — restart the app"
                    if ok else f"✕ winget exit {r.returncode} — install "
                              "manually (see README)",
                    fg=GREEN if ok else RED))
            threading.Thread(target=work, daemon=True).start()

        btn = tk.Button(trow, text="Install via winget",
                        command=install_tess, bg=GOLD, fg="#191307",
                        relief="flat", font=f_sub, padx=8)
        btn.pack(side="right")

    status.pack(anchor="w", padx=pad, pady=(4, 0))

    btns = tk.Frame(win, bg=BG)
    btns.pack(fill="x", padx=pad, pady=(int(8 * s), pad))

    def open_settings():
        try:
            from advisor.settings_ui import open_settings
            open_settings(root, cfg, scale=s)
        except Exception:
            pass

    def close():
        mark_done()
        win.destroy()

    tk.Button(btns, text="Open Settings", command=open_settings, bg=FIELD,
              fg=FG, relief="flat", font=f_base, padx=10
              ).pack(side="left")
    tk.Button(btns, text="Let's go", command=close, bg=GOLD, fg="#191307",
              relief="flat", font=f_base, padx=14).pack(side="right")
    win.protocol("WM_DELETE_WINDOW", close)
    win.lift()
    win.attributes("-topmost", True)
    return win
