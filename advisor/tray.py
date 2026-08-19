"""System-tray icon (pystray): quick actions, health, exit.

The tray thread never touches tkinter directly — every UI action is
marshalled onto the tk main thread with root.after(0, ...)."""
import ctypes
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _console_hwnd():
    return ctypes.windll.kernel32.GetConsoleWindow()


def toggle_console():
    h = _console_hwnd()
    if not h:
        return
    u = ctypes.windll.user32
    u.ShowWindow(h, 0 if u.IsWindowVisible(h) else 5)  # SW_HIDE / SW_SHOW


def hide_console():
    h = _console_hwnd()
    if h:
        ctypes.windll.user32.ShowWindow(h, 0)


def start_tray(app):
    """Returns the pystray Icon (already running detached) or None."""
    try:
        import pystray
        from PIL import Image
    except ImportError as e:
        print(f"tray disabled ({e}) — pip install pystray")
        return None
    ico = ROOT / "assets" / "icon.ico"
    if not ico.exists():
        return None
    image = Image.open(ico)

    def on_finder(icon, item):
        app.open_finder()

    def on_settings(icon, item):
        app.root.after(0, app.open_settings)

    def on_health(icon, item):
        # a real window — Windows swallows tray notifications silently
        app.root.after(0, app.show_health)

    def on_console(icon, item):
        if _console_hwnd():
            toggle_console()
        else:
            # windowed exe: no console exists — show the log file instead
            import os
            log = Path(sys.executable).parent / "advisor.log"
            if log.exists():
                os.startfile(log)

    def on_exit(icon, item):
        icon.stop()
        app.root.after(0, app.root.quit)

    console_label = ("Show / hide console" if _console_hwnd()
                     else "Open log")
    def on_update(icon, item):
        app.check_updates(interactive=True)

    def on_goals(icon, item):
        app.root.after(0, app.open_goals)

    menu = pystray.Menu(
        pystray.MenuItem("Settings", on_settings, default=True),
        pystray.MenuItem("Season goals", on_goals),
        pystray.MenuItem("Seed Finder", on_finder),
        pystray.MenuItem("Health check", on_health),
        pystray.MenuItem("Check for updates", on_update),
        pystray.MenuItem(console_label, on_console),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Exit", on_exit),
    )
    icon = pystray.Icon("d2r-advisor", image, "D2R Item Advisor", menu)
    threading.Thread(target=icon.run, daemon=True).start()
    return icon


def ensure_start_menu_shortcut():
    """Frozen exe only: put a Start Menu shortcut next to real apps."""
    if not getattr(sys, "frozen", False):
        return
    import os
    import subprocess
    lnk = (Path(os.environ["APPDATA"]) / "Microsoft" / "Windows"
           / "Start Menu" / "Programs" / "D2R Item Advisor.lnk")
    if lnk.exists():
        return
    exe = sys.executable
    ps = (f"$s=(New-Object -ComObject WScript.Shell).CreateShortcut("
          f"'{lnk}');$s.TargetPath='{exe}';"
          f"$s.WorkingDirectory='{Path(exe).parent}';"
          f"$s.IconLocation='{exe}';$s.Save()")
    try:
        subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                       capture_output=True, timeout=30,
                       creationflags=0x08000000)  # CREATE_NO_WINDOW
        print(f"Start Menu shortcut created: {lnk.name}")
    except Exception as e:
        print(f"shortcut skipped: {e}")
