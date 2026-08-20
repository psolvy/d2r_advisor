"""Debug-artifact housekeeping shared by every dump site.

Frames are multi-MB 4K screenshots; without retention the debug dir grew
without bound (hundreds of files). Stamps carry the date — bare %H%M%S
silently overwrote files across days.
"""
from datetime import datetime


def stamp():
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def prune(dbg_dir, keep=60):
    """Keep the newest `keep` files, delete the rest. Never raises."""
    try:
        files = sorted((p for p in dbg_dir.iterdir() if p.is_file()),
                       key=lambda p: p.stat().st_mtime, reverse=True)
        for p in files[keep:]:
            try:
                p.unlink()
            except OSError:
                pass
    except OSError:
        pass


def rotate(path, max_mb=5):
    """history.log-style rotation: file > max_mb moves to <name>.1."""
    try:
        if path.exists() and path.stat().st_size > max_mb * 1024 * 1024:
            bak = path.with_suffix(path.suffix + ".1")
            if bak.exists():
                bak.unlink()
            path.rename(bak)
    except OSError:
        pass
