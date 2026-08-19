"""D2R Item Advisor application (the launcher is main.py — kept thin so
Windows multiprocessing workers that re-import __main__ never load cv2/
tkinter/the whole app).

Works from screenshots only — the game's memory is never read.
"""
import ctypes
import json
import queue
import shutil
import sys
import threading
import time
import tkinter as tk
from datetime import datetime
from pathlib import Path

import cv2
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from advisor.ocr import scan_tooltip
from advisor.overlay import Overlay
from advisor.parse import parse_best
from advisor import links
from advisor.breakpoints import bp_lines
from advisor.knowledge import (consumable_advice, craft_advice, gamble_advice,
                               gamble_offer_summary, gem_advice, get_value_tier,
                               match_gamble_offer, quest_advice, rune_advice, set_advice,
                               special_advice, upgrade_advice)
from advisor.ranges import get_item_ranges, magic_affix_ranges
from advisor.rules import evaluate, load_rules
from advisor.runewords import base_advice
from advisor.tooltip import fallback_region, find_tooltip
from d2rlootreader.screen import capture_monitor_at

IS_WINDOWS = sys.platform == "win32"


def load_config():
    cfg_path = ROOT / "config.yaml"
    try:
        with open(cfg_path, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except FileNotFoundError:
        print("WARNING: config.yaml not found — using defaults")
        return {}
    except yaml.YAMLError as e:
        print(f"WARNING: config.yaml is broken ({e}) — using defaults")
        return {}


def get_cursor_pos():
    if IS_WINDOWS:
        class POINT(ctypes.Structure):
            _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]
        p = POINT()
        ctypes.windll.user32.GetCursorPos(ctypes.byref(p))
        return (p.x, p.y)
    return None


def resolve_tesseract(cfg):
    explicit = (cfg.get("tesseract_cmd") or "").strip()
    if explicit:
        return explicit
    found = shutil.which("tesseract")
    if found:
        return found
    default_win = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
    if IS_WINDOWS and Path(default_win).exists():
        return default_win
    return None


def resolve_rules_file(cfg):
    """Pick the rules file: presets/rules-<preset>.yaml, or rules.yaml (custom)."""
    preset = (cfg.get("preset") or "custom").strip().lower()
    if preset == "auto":
        # Pick by season age: leveling < 14 days, midgame < 45, then lategame.
        try:
            start = datetime.strptime(str(cfg.get("season_start", "")).strip(), "%Y-%m-%d")
            days = max(0, (datetime.now() - start).days)
            preset = "leveling" if days < 14 else "midgame" if days < 45 else "lategame"
            print(f"Auto preset: {preset} (season day {days})")
        except ValueError:
            print("WARNING: preset 'auto' needs season_start: YYYY-MM-DD — using leveling")
            preset = "leveling"
    if preset != "custom":
        candidate = ROOT / "presets" / f"rules-{preset}.yaml"
        if candidate.exists():
            return candidate
        print(f"WARNING: preset '{preset}' not found ({candidate}), falling back to rules.yaml")
    return ROOT / "rules.yaml"


APP_NAME = "D2R Item Advisor"


def set_app_identity(root):
    """Window title, taskbar identity and icon for console + tk windows."""
    if IS_WINDOWS:
        try:
            ctypes.windll.kernel32.SetConsoleTitleW(APP_NAME)
        except Exception:
            pass
        try:
            # Own taskbar identity (icon grouping) instead of python.exe's.
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("d2r.item.advisor")
        except Exception:
            pass
    icon = ROOT / "assets" / "icon.ico"
    if icon.exists():
        try:
            root.iconbitmap(default=str(icon))
        except Exception:
            pass


class App:
    def __init__(self):
        self.cfg = load_config()
        rules_path = resolve_rules_file(self.cfg)
        try:
            self.rules, self.default = load_rules(rules_path)
            print(f"Rules: {rules_path.name}")
        except Exception as e:
            print(f"ERROR: cannot load {rules_path.name} ({type(e).__name__}: {e})")
            print("Fix the YAML — running with a single 'check everything' rule until then.")
            self.rules, self.default = [], {"verdict": "check", "note": "rules file is broken — fix it"}
        links.configure(self.cfg.get("link_template"))
        self.tesseract = resolve_tesseract(self.cfg)
        self.last_gamble = []  # last F10-scanned offer, auto-fills the seed finder
        self.last_gamble_entries = None  # icon-scan entries [(idx, x, y)]
        self.results = queue.Queue()
        self.busy = threading.Lock()

        self.root = tk.Tk()
        self.root.withdraw()
        set_app_identity(self.root)
        self.overlay = Overlay(self.root, scale=float(self.cfg.get("ui_scale", 1.5)))

        if IS_WINDOWS:
            try:
                ctypes.windll.user32.SetProcessDPIAware()
            except Exception:
                pass

    def scan(self):
        """Runs in a worker thread: capture -> detect -> OCR -> parse -> verdict."""
        if not self.busy.acquire(blocking=False):
            return
        try:
            # Give the just-hidden verdict popup time to leave the screen so
            # it isn't captured and OCR'd as part of the tooltip.
            time.sleep(0.15)
            cursor = get_cursor_pos()
            # Capture only the monitor under the cursor: multi-monitor virtual
            # desktops have a different origin than cursor coordinates, and
            # OCR-scanning other monitors' windows is slow noise.
            img, local_cursor, screen_rect = capture_monitor_at(cursor)
            crop, box = find_tooltip(img, local_cursor)
            used_fallback = False
            if crop is None:
                crop, box = fallback_region(img, local_cursor)
                used_fallback = True

            stamp = datetime.now().strftime("%H%M%S")
            if self.cfg.get("debug"):
                dbg = ROOT / "debug"
                dbg.mkdir(exist_ok=True)
                cv2.imwrite(str(dbg / f"{stamp}_full.png"), img)
                cv2.imwrite(str(dbg / f"{stamp}_crop.png"), crop)

            # OCR + title-color hint: the color of the item-name line
            # (green/gold/yellow/blue...) pins the quality even when the name
            # is unknown to the fuzzy matcher.
            variants, quality_hint, flags = scan_tooltip(crop, tesseract_cmd=self.tesseract)
            if used_fallback:
                quality_hint = None

            item = parse_best(variants, quality_hint=quality_hint)
            if not item.get("tooltip"):
                self.results.put({"verdict": "error",
                                  "note": "No text recognized — hover an item tooltip",
                                  "cursor": cursor, "screen_rect": screen_rect})
                return

            verdict, rule_name, note = evaluate(item, self.rules, self.default)
            # Quest items override every preset: always keep, with what-to-do.
            quest = quest_advice(item)
            override = None
            if quest:
                verdict, rule_name, note = "keep", "Quest item", ""
                if not item.get("name"):
                    tooltip = item.get("tooltip") or []
                    item["name"] = tooltip[0].strip() if tooltip else "Quest item"
            else:
                # Endgame specials (essences/uber keys/organs/tokens/ears),
                # then consumables (potions/scrolls/tomes/keys/ammo): clear
                # name + sensible verdict instead of "?" and the default rule.
                special = special_advice(item)
                override = special or consumable_advice(item)
                if override:
                    kind = "Special item" if special else "Consumable"
                    verdict, rule_name, note = override["verdict"], kind, override["note"]
                    # Own the display: the fuzzy matcher may have "matched" a
                    # base (grimoire "Tome" vs "Tome of Identify") — a
                    # consumable has no base, slot or gear advice.
                    item["name"] = override["name"]
                    item["base"] = item["slot"] = item["tier"] = None
                    item["quality"] = ""

            ranges = tier = None
            if quest:
                extra = quest
            elif override:
                extra = None  # no runeword/craft/gamble advice for consumables
            else:
                # Contextual advice: runeword list for bases, cube-up info for
                # runes/gems, craft recipes for magic bases, tier upgrades for
                # uniques/rares, set context, value tier for known uniques/sets.
                ranges = get_item_ranges(item) if self.cfg.get("show_ranges", True) else None
                if ranges is None and self.cfg.get("show_ranges", True):
                    # Blue/yellow/superior gear: annotate each affix with its
                    # prefix/suffix tier and the stat's cap.
                    ranges = magic_affix_ranges(item)
                extra = (base_advice(item) or rune_advice(item)
                         or gem_advice(item) or craft_advice(item) or [])
                extra += upgrade_advice(item) or []
                extra += set_advice(item) or []
                extra += bp_lines(item, self.cfg.get("my_class")) or []
                # Gamble screen: unidentified gear + a Cost/Buy line.
                if flags.get("shop") and not item.get("affixes"):
                    extra = (gamble_advice(item, char_level=int(self.cfg.get("char_level") or 0))
                             or []) + extra
                # Price check: clickable line for tradeable qualities.
                price_tmpl = (self.cfg.get("price_link_template") or "").strip()
                if price_tmpl and item.get("quality") in (
                        "Unique", "Set", "Runeword", "Rare", "Crafted"):
                    from urllib.parse import quote
                    q = item.get("name") or item.get("base") or ""
                    if q:
                        extra += [("💰 Price check", "#ffd94d",
                                   price_tmpl.replace("{query}", quote(q)))]
                extra = extra or None
                tier = get_value_tier(item)
            if quest:
                ranges = get_item_ranges(item) if self.cfg.get("show_ranges", True) else None
            if used_fallback:
                note = (note + " · tooltip detection was fuzzy").strip(" ·")
            if any("#" in t and p and p[0] == 0 for t, p in item.get("affixes") or []):
                note = (note + " · ⚠ a value read as 0 — check the real number by eye").strip(" ·")

            if self.cfg.get("debug"):
                dump = {k: v for k, v in item.items() if k != "tooltip"}
                with open(ROOT / "debug" / f"{stamp}_parse.txt", "w", encoding="utf-8") as f:
                    f.write(f"hint: {quality_hint}\nverdict: {verdict} ({rule_name})\n\n")
                    f.write("OCR lines:\n" + "\n".join(item.get("tooltip") or []) + "\n\n")
                    f.write("item:\n" + json.dumps(dump, ensure_ascii=False, indent=1, default=str))

            self.log_history(verdict, item, rule_name)
            self.results.put({"verdict": verdict, "item": item, "rule": rule_name,
                              "note": note, "cursor": cursor, "ranges": ranges,
                              "screen_rect": screen_rect, "extra": extra, "tier": tier})
        except Exception as e:
            self.results.put({"verdict": "error", "note": f"{type(e).__name__}: {e}"})
        finally:
            self.busy.release()

    def log_history(self, verdict, item, rule_name):
        """Append the scan to history.log (one JSON object per line)."""
        if not self.cfg.get("history", True):
            return
        try:
            tooltip = item.get("tooltip") or []
            entry = {
                "time": datetime.now().isoformat(timespec="seconds"),
                "verdict": verdict,
                "quality": item.get("quality"),
                "name": item.get("name") or (tooltip[0].strip() if tooltip else None),
                "base": item.get("base"),
                "rule": rule_name,
            }
            with open(ROOT / "history.log", "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except OSError:
            pass

    def play_sound(self, verdict):
        """Distinct beep per verdict, so trash needs no reading."""
        if not (IS_WINDOWS and self.cfg.get("sounds", True)):
            return

        def _beep():
            import winsound
            try:
                if verdict == "keep":
                    winsound.Beep(880, 90)
                    winsound.Beep(1318, 140)
                elif verdict == "check":
                    winsound.Beep(660, 160)
                elif verdict == "trash":
                    winsound.Beep(233, 140)
                else:
                    winsound.Beep(160, 220)
            except RuntimeError:
                pass

        threading.Thread(target=_beep, daemon=True).start()

    def scan_gamble(self):
        """Read the whole gamble offer around the cursor: mark which slots are
        worth buying and copy the list for the DBM seed simulator."""
        if not self.busy.acquire(blocking=False):
            return
        try:
            time.sleep(0.15)
            cursor = get_cursor_pos()
            img, local_cursor, screen_rect = capture_monitor_at(cursor)
            # instant feedback AFTER the capture (so it isn't in the shot) —
            # icon recognition takes a few seconds and looked like a dead key
            self.results.put({"verdict": "scan",
                              "note": "Reading the gamble offer from the icons "
                                      "(a few seconds)…",
                              "cursor": cursor, "screen_rect": screen_rect})

            # 1) Icon recognition (resurrected graphics shows icons, no text).
            #    Needs the 3-point grid calibration (Shift+F10 -> Calibrate).
            entries, vision_err = None, None
            diag = []
            try:
                from advisor.gamble_vision import scan_gamble_icons
                # always keep the recognition overlay — it is the ground
                # truth for fixing any misread remotely
                dbg = ROOT / "debug"
                dbg.mkdir(exist_ok=True)
                debug_out = dbg / f"{datetime.now():%H%M%S}_gamble_grid.png"
                entries = scan_gamble_icons(img, screen_rect,
                                            debug_out=debug_out, diag=diag)
            except ValueError as e:
                vision_err = str(e)
            except Exception as e:
                vision_err = f"{type(e).__name__}: {e}"
            if entries is None:
                # always dump a failure bundle — this is what fixes it remotely
                try:
                    dbg = ROOT / "debug"
                    dbg.mkdir(exist_ok=True)
                    stamp = f"{datetime.now():%H%M%S}"
                    cv2.imwrite(str(dbg / f"{stamp}_gamble_fail_frame.png"), img)
                    with open(dbg / f"{stamp}_gamble_fail.txt", "w",
                              encoding="utf-8") as f:
                        f.write(f"error: {vision_err}\n"
                                f"screen_rect: {screen_rect}\n"
                                "pair score per cell size (cell_px, score):\n")
                        for cell, score in diag:
                            f.write(f"  {cell}: {score}\n")
                except Exception:
                    pass
            if entries:
                from advisor.gamble_seed import items as engine_items
                it = engine_items()
                names = [it[i]["name"] for i, _x, _y in entries]
                self.last_gamble = names
                self.last_gamble_entries = list(entries)
                self.results.put({
                    "verdict": "check",
                    "item": {"name": "Gamble offer", "quality": "",
                             "tooltip": names, "affixes": []},
                    "rule": "Gamble helper (icons)",
                    "cursor": cursor,
                    "screen_rect": screen_rect,
                    "extra": self._offer_summary(names),
                    "clip": ", ".join(names),
                })
                return

            # 2) Legacy-graphics fallback: OCR the text list.
            crop, _ = fallback_region(img, local_cursor, width=1100, height=900)
            variants, _hint, _flags = scan_tooltip(crop, tesseract_cmd=self.tesseract)
            lines = next(iter(variants), [])
            offer = match_gamble_offer(lines)
            if not offer:
                note = ((vision_err or "No gamble items recognized.")
                        + " Diagnostics saved to debug\\*_gamble_fail* — "
                        "send them. You can also enter the offer by clicking "
                        "the grid in the Seed Finder (Shift+F10).")
                self.results.put({"verdict": "error", "note": note,
                                  "cursor": cursor, "screen_rect": screen_rect})
                return
            self.last_gamble = list(offer)  # feeds the seed finder's auto-fill
            self.last_gamble_entries = None
            self.results.put({
                "verdict": "check",
                "item": {"name": "Gamble offer", "quality": "", "tooltip": lines, "affixes": []},
                "rule": "Gamble helper",
                "cursor": cursor,
                "screen_rect": screen_rect,
                "extra": self._offer_summary(offer),
                "clip": ", ".join(offer),
            })
        except Exception as e:
            self.results.put({"verdict": "error", "note": f"{type(e).__name__}: {e}"})
        finally:
            self.busy.release()

    _last_finder_open = 0.0

    def _offer_summary(self, names):
        """gamble_offer_summary with the Seed Finder line CLICKABLE."""
        out = []
        for entry in gamble_offer_summary(names):
            if "Shift+F10" in entry[0]:
                out.append(("Open the Seed Finder — click here (or "
                            "Shift+F10); it comes pre-filled with this offer",
                            entry[1], self.open_finder))
            else:
                out.append(entry)
        return out

    def open_finder(self):
        """Open the Seed Finder pre-filled with the last scan (hotkey AND
        the clickable popup line use this). Debounced against key repeat."""
        now = time.time()
        if now - self._last_finder_open < 1.0:
            return
        self._last_finder_open = now
        from advisor.seedfinder_ui import open_seed_finder
        self.root.after(0, lambda: open_seed_finder(
            self.root, int(self.cfg.get("char_level") or 85),
            get_last_offer=lambda: getattr(self, "last_gamble", []),
            get_last_entries=lambda: getattr(self, "last_gamble_entries", None),
            ui_scale=float(self.cfg.get("seedfinder_scale")
                           or self.cfg.get("ui_scale") or 1.0),
            cfg=self.cfg))

    def on_gamble_hotkey(self):
        # shift+f10 is the seed finder; the bare-f10 hotkey fires anyway
        try:
            import keyboard
            if keyboard.is_pressed("shift"):
                return
        except Exception:
            pass
        self.root.after(0, self.overlay.hide)
        threading.Thread(target=self.scan_gamble, daemon=True).start()

    def scan_compare(self):
        """Both Shift-compare tooltips -> what the hovered item gains and
        loses vs the equipped one."""
        if not self.busy.acquire(blocking=False):
            return
        try:
            time.sleep(0.15)
            cursor = get_cursor_pos()
            img, local_cursor, screen_rect = capture_monitor_at(cursor)
            from advisor.tooltip import find_compare_tooltips
            hov, others = find_compare_tooltips(img, local_cursor)

            def dump(reason):
                dbg = ROOT / "debug"
                dbg.mkdir(exist_ok=True)
                stamp = datetime.now().strftime("%H%M%S")
                cv2.imwrite(str(dbg / f"{stamp}_cmp_full.png"), img)
                if hov is not None:
                    cv2.imwrite(str(dbg / f"{stamp}_cmp_hovered.png"), hov)
                for i, o in enumerate(others or [], 1):
                    cv2.imwrite(str(dbg / f"{stamp}_cmp_equipped{i}.png"), o)
                print(f"compare debug saved ({reason}) -> debug/{stamp}_cmp_*")

            if hov is None or not others:
                dump("missing tooltip")
                self.results.put({
                    "verdict": "error",
                    "note": "Need BOTH tooltips: hold Shift so the game "
                            "shows the equipped item, keep hovering, then "
                            "press the compare hotkey",
                    "cursor": cursor, "screen_rect": screen_rect})
                return

            def read(crop):
                variants, hint, _fl = scan_tooltip(
                    crop, tesseract_cmd=self.tesseract)
                return parse_best(variants, quality_hint=hint)

            new_item = read(hov)
            old_items = [it for it in (read(o) for o in others)
                         if it.get("tooltip")]
            if not new_item.get("tooltip") or not old_items:
                dump("unreadable "
                     + ("hovered" if not new_item.get("tooltip")
                        else "equipped"))
                self.results.put({
                    "verdict": "error",
                    "note": "Could not read one of the tooltips — try "
                            "again (debug images saved)",
                    "cursor": cursor, "screen_rect": screen_rect})
                return
            if self.cfg.get("debug"):
                dump("ok")
            from advisor.compare import diff_items
            extra = []
            for k, old in enumerate(old_items):
                if k:
                    extra.append((" ", "#9a9a9a"))  # section spacer
                extra += diff_items(new_item, old)
            self.results.put({
                "verdict": "compare",
                "item": new_item,
                "extra": extra,
                "cursor": cursor, "screen_rect": screen_rect})
        except Exception as e:
            self.results.put({"verdict": "error",
                              "note": f"{type(e).__name__}: {e}",
                              "cursor": get_cursor_pos()})
        finally:
            self.busy.release()

    def on_compare_hotkey(self):
        threading.Thread(target=self.scan_compare, daemon=True).start()

    def on_hotkey(self):
        # Hide our own popup first — otherwise it gets captured and OCR'd.
        self.root.after(0, self.overlay.hide)
        threading.Thread(target=self.scan, daemon=True).start()

    def poll(self):
        try:
            while True:
                r = self.results.get_nowait()
                try:
                    if r.get("clip"):
                        try:
                            self.root.clipboard_clear()
                            self.root.clipboard_append(r["clip"])
                        except Exception:
                            pass
                    if r.get("verdict") != "scan":  # progress notice is silent
                        self.play_sound(r.get("verdict", "error"))
                    self.overlay.show(
                        r.get("verdict", "error"),
                        item=r.get("item"),
                        rule=r.get("rule", ""),
                        note=r.get("note", ""),
                        pos=r.get("cursor"),
                        seconds=float(self.cfg.get("display_seconds", 10)),
                        ranges=r.get("ranges"),
                        screen_rect=r.get("screen_rect"),
                        extra=r.get("extra"),
                        tier=r.get("tier"),
                    )
                except Exception as e:
                    # A display failure must never kill the poll loop.
                    print(f"overlay error: {type(e).__name__}: {e}")
        except queue.Empty:
            pass
        self.root.after(100, self.poll)

    def _fetch_missing_assets(self):
        """First-run helper (mainly for the exe build): gamble icons and the
        fast-search workers are not shipped — download them quietly in the
        background when absent. Everything works without them meanwhile."""
        try:
            from advisor.gamble_vision import ICON_DIR
            worker = ROOT / "tools" / "dbm_validation" / "brute.worker.js"
            if (ICON_DIR / "rin.png").exists() and worker.exists():
                return
            sys.path.insert(0, str(ROOT / "tools"))
            import setup_assets
            print("first run: downloading gamble icons + fast-search workers…")
            setup_assets.main()
        except Exception as e:
            print(f"asset download skipped ({e}) — F10 icon scan and the "
                  "fast seed search need them; rerun to retry")

    def _ui_scale(self):
        return float(self.cfg.get("seedfinder_scale")
                     or self.cfg.get("ui_scale") or 1.5)

    def open_settings(self):
        from advisor.settings_ui import open_settings
        open_settings(self.root, self.cfg, restart_cb=self.restart,
                      scale=self._ui_scale())

    def show_health(self):
        from advisor.settings_ui import open_health_report
        open_health_report(self.root, self.cfg, scale=self._ui_scale())

    def open_goals(self):
        from advisor.goals_ui import open_goals
        open_goals(self.root, scale=self._ui_scale(), cfg=self.cfg)

    def show_tz(self):
        from advisor.tz import open_tz_window
        open_tz_window(self.root, self.cfg, scale=self._ui_scale())

    def check_updates(self, interactive=False):
        """Compare against the newest GitHub release in the background;
        offer the update dialog when there is one."""
        from advisor import updater

        def work():
            newer, tag, asset = updater.check()
            if newer:
                self.root.after(0, lambda: self._update_dialog(tag, asset))
            elif interactive:
                self.root.after(0, lambda: self._update_dialog(None, None,
                                                               True))
        threading.Thread(target=work, daemon=True).start()

    def _update_dialog(self, tag, asset, up_to_date=False):
        from advisor.settings_ui import open_update_dialog
        open_update_dialog(self.root, tag, asset, scale=self._ui_scale(),
                           up_to_date=up_to_date)

    def restart(self):
        """Relaunch (exe or source) so new hotkeys/scales apply."""
        import subprocess
        if getattr(sys, "frozen", False):
            subprocess.Popen([sys.executable], cwd=str(ROOT))
        else:
            subprocess.Popen([sys.executable, str(ROOT / "main.py")],
                             cwd=str(ROOT),
                             creationflags=0x00000010)  # CREATE_NEW_CONSOLE
        self.root.after(200, self.root.quit)

    def _report_health(self, tray_icon):
        from advisor.health import health_report, summary_line
        issues = health_report(self.cfg)
        for lv, title, detail in issues:
            mark = {"error": "ERROR", "warn": "warning", "ok": "note"}[lv]
            print(f"[{mark}] {title} — {detail}")
        hot = [i for i in issues if i[0] in ("error", "warn")]
        if hot and tray_icon is not None:
            try:
                tray_icon.notify(
                    "\n".join(t for _lv, t, _d in hot[:3]),
                    f"D2R Item Advisor: {summary_line(issues)}")
            except Exception:
                pass

    def run(self):
        threading.Thread(target=self._fetch_missing_assets,
                         daemon=True).start()
        if not self.tesseract:
            # No hard exit: gamble/seed features work without OCR.
            print("WARNING: Tesseract not found — tooltip scans (hotkey "
                  "verdicts) are disabled. See Settings / README.")

        import keyboard  # imported late: on some systems needs admin

        hotkey = self.cfg.get("hotkey", "f8")
        keyboard.add_hotkey(hotkey, self.on_hotkey)
        gamble_key = (self.cfg.get("gamble_hotkey") or "").strip()
        if gamble_key:
            keyboard.add_hotkey(gamble_key, self.on_gamble_hotkey)
        seed_key = (self.cfg.get("seed_hotkey") or "").strip()
        if seed_key:
            keyboard.add_hotkey(seed_key, self.open_finder)
        compare_key = (self.cfg.get("compare_hotkey") or "").strip()
        if compare_key:
            keyboard.add_hotkey(compare_key, self.on_compare_hotkey)
        bits = [f"[{hotkey.upper()}] item verdict"]
        if compare_key:
            bits.append(f"[{compare_key.upper()}] compare vs equipped "
                        "(hold Shift in game)")
        if gamble_key:
            bits.append(f"[{gamble_key.upper()}] gamble offer")
        if seed_key:
            bits.append(f"[{seed_key.upper()}] Seed Finder")
        print(f"=== {APP_NAME} === " + " · ".join(bits))
        print("tray: Settings / Season goals / Terror Zone / Health / "
              "updates · Ctrl+C to quit")

        from advisor import tray
        tray_icon = tray.start_tray(self)
        if getattr(sys, "frozen", False):
            # exe UX: windowed build lives in the tray only; keep the
            # Start Menu discoverable
            tray.ensure_start_menu_shortcut()
        self.root.after(1500, lambda: self._report_health(tray_icon))
        if self.cfg.get("auto_update", True):
            self.root.after(5000, self.check_updates)
        self.root.after(100, self.poll)
        try:
            self.root.mainloop()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    App().run()
