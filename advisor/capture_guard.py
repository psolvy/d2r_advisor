"""One capture flow at a time, app-wide.

Calibrations and tab scans run multi-second countdowns on the tk timer;
starting a second one mid-flight interleaved the prompts and wrote
garbage points. Every flow acquires before starting and releases on its
LAST step (or failure).

Thread-safe (F9/F10 scans check it from worker threads), and stale
holds auto-expire: a flow that died without releasing (window closed
mid-countdown) used to lock every scan out until an app restart.
"""
import threading
import time

_LOCK = threading.Lock()
_busy = None   # description of the running flow, or None
_since = 0.0
_TIMEOUT_S = 120  # no capture flow legitimately runs longer


def acquire(what):
    """True if the flow may start; False when another one is running."""
    global _busy, _since
    with _LOCK:
        if _busy is not None and time.time() - _since < _TIMEOUT_S:
            return False
        _busy = what
        _since = time.time()
        return True


def release(owner=None):
    """Release the guard. With owner given, releases only if that flow
    still holds it (so a late failure path can't drop someone else's
    hold)."""
    global _busy
    with _LOCK:
        if owner is None or _busy == owner:
            _busy = None


def busy_with():
    with _LOCK:
        if _busy is not None and time.time() - _since >= _TIMEOUT_S:
            return None
        return _busy
