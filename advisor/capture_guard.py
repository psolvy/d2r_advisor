"""One capture flow at a time, app-wide.

Calibrations and tab scans run multi-second countdowns on the tk timer;
starting a second one mid-flight interleaved the prompts and wrote
garbage points. Every flow acquires before starting and releases on its
LAST step (or failure)."""

_busy = None  # description of the running flow, or None


def acquire(what):
    """True if the flow may start; False when another one is running."""
    global _busy
    if _busy is not None:
        return False
    _busy = what
    return True


def release():
    global _busy
    _busy = None


def busy_with():
    return _busy
