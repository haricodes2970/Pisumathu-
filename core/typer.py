"""
core/typer.py — Types transcribed text into the previously active window.

Strategy:
  1. On hotkey PRESS  → capture the foreground window handle (Win32 API)
  2. On transcription DONE → restore focus to that window, then type text
     via pynput keyboard controller (simulates real keystrokes)

This works with any application: browsers, IDEs, chat apps, terminals.

Why Win32 + pynput instead of pyautogui?
  - pyautogui.typewrite() breaks on Unicode / Kannada script
  - pynput.keyboard.Controller.type() handles full Unicode correctly
  - Win32 SetForegroundWindow gives us precise focus restoration
"""

import time
import threading
from typing import Optional


# ---------------------------------------------------------------------------
# Win32 focus capture (Windows only)
# ---------------------------------------------------------------------------

def _get_foreground_hwnd() -> Optional[int]:
    """Return the HWND of the currently active window, or None."""
    try:
        import ctypes
        return ctypes.windll.user32.GetForegroundWindow()
    except Exception:
        return None


def _restore_focus(hwnd: int) -> bool:
    """Bring hwnd back to the foreground without disturbing window state.

    Uses AttachThreadInput so SetForegroundWindow succeeds from a background
    thread, and never calls ShowWindow — which would minimize/restore
    fullscreen or maximized windows.
    """
    if not hwnd:
        return False
    try:
        import ctypes
        u32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32

        current_tid = kernel32.GetCurrentThreadId()
        target_tid = u32.GetWindowThreadProcessId(hwnd, None)

        # Allow our process to set foreground
        u32.AllowSetForegroundWindow(hwnd)

        # Attach our thread input to the target thread so focus APIs work
        attached = False
        if target_tid and target_tid != current_tid:
            attached = bool(u32.AttachThreadInput(current_tid, target_tid, True))

        u32.BringWindowToTop(hwnd)
        result = u32.SetForegroundWindow(hwnd)

        if attached:
            u32.AttachThreadInput(current_tid, target_tid, False)

        return bool(result)
    except Exception as e:
        print(f"[Typer] Focus restore failed: {e}")
        return False


def _is_own_window(hwnd: int, own_hwnd: int) -> bool:
    """True if hwnd belongs to our own process (avoid typing into ourselves)."""
    if not hwnd or not own_hwnd:
        return False
    try:
        import ctypes
        pid1 = ctypes.c_ulong(0)
        pid2 = ctypes.c_ulong(0)
        ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid1))
        ctypes.windll.user32.GetWindowThreadProcessId(own_hwnd, ctypes.byref(pid2))
        return pid1.value == pid2.value
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Typer class
# ---------------------------------------------------------------------------

class Typer:
    """
    Captures focus on hotkey press, types text into that window after
    transcription completes.

    Thread-safe. All heavy work runs on the calling thread (transcription
    worker) — no additional threads created here.
    """

    def __init__(self):
        self._captured_hwnd: Optional[int] = None
        self._own_hwnd: Optional[int] = None
        self._enabled: bool = True          # toggled by UI
        self._lock = threading.Lock()

        # pynput keyboard controller (lazy-loaded)
        self._kb = None

        # Small delay between focus restore and typing (ms)
        # Gives the target window time to actually receive focus
        self.focus_settle_ms: int = 150

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_enabled(self, enabled: bool) -> None:
        """Toggle auto-type on/off."""
        with self._lock:
            self._enabled = enabled

    @property
    def enabled(self) -> bool:
        with self._lock:
            return self._enabled

    def capture_focus(self) -> None:
        """
        Call this the instant the hotkey is pressed (BEFORE recording starts).
        Snapshots whichever window the user was typing in.
        """
        hwnd = _get_foreground_hwnd()
        with self._lock:
            self._captured_hwnd = hwnd
        print(f"[Typer] Captured focus HWND: {hwnd}")

    def set_own_hwnd(self, hwnd: int) -> None:
        """Register our own window handle so we never type into ourselves."""
        self._own_hwnd = hwnd

    def type_text(self, text: str) -> bool:
        """
        Restore focus to the captured window and type `text` into it.

        Returns True if text was typed, False if skipped (disabled,
        no capture, or own window).
        """
        with self._lock:
            enabled = self._enabled
            hwnd = self._captured_hwnd
            own = self._own_hwnd

        if not enabled:
            return False

        if not hwnd:
            print("[Typer] No captured window — skipping auto-type.")
            return False

        if _is_own_window(hwnd, own):
            print("[Typer] Captured window is our own — skipping auto-type.")
            return False

        # Restore focus
        restored = _restore_focus(hwnd)
        if not restored:
            print("[Typer] Could not restore focus — skipping auto-type.")
            return False

        # Small settle delay so the window is ready to receive input
        time.sleep(self.focus_settle_ms / 1000.0)

        # Type text
        try:
            kb = self._get_keyboard()
            kb.type(text)
            print(f"[Typer] Typed {len(text)} chars into HWND {hwnd}")
            return True
        except Exception as e:
            print(f"[Typer] Typing failed: {e}")
            return False

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _get_keyboard(self):
        """Lazy-load pynput keyboard controller."""
        if self._kb is None:
            from pynput.keyboard import Controller
            self._kb = Controller()
        return self._kb
