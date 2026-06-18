from __future__ import annotations

import time
import tkinter as tk
from dataclasses import dataclass

from .models import Monitor
from .win32_screen import exclude_window_from_capture, is_hotkey_pressed


VK_CONTROL = 0x11
VK_MENU = 0x12
VK_U = 0x55


@dataclass
class ShieldState:
    active: bool = False
    reason: str = ""
    shown_at: float = 0.0
    capture_exclusion_enabled: bool = False
    snoozed_until: float = 0.0


class BlackoutShield:
    def __init__(self, monitors: list[Monitor], unlock_hold_seconds: float, snooze_seconds: float):
        self.root = tk.Tk()
        self.root.withdraw()
        self.root.configure(bg="black")
        self._monitors = monitors
        self._windows: list[tk.Toplevel] = []
        self._unlock_hold_seconds = unlock_hold_seconds
        self._snooze_seconds = snooze_seconds
        self._hotkey_started_at: float | None = None
        self._closed = False
        self.state = ShieldState()
        self._build_windows()

    def show(self, reason: str) -> None:
        now = time.monotonic()
        if now < self.state.snoozed_until:
            return
        self.state.active = True
        self.state.reason = reason
        if self.state.shown_at == 0.0:
            self.state.shown_at = now
        exclusion_results: list[bool] = []
        for window in self._windows:
            window.deiconify()
            window.lift()
            window.attributes("-topmost", True)
            window.update_idletasks()
            exclusion_results.append(exclude_window_from_capture(window.winfo_id()))
        self.state.capture_exclusion_enabled = bool(exclusion_results) and all(exclusion_results)

    def hide(self) -> None:
        self.state.active = False
        self.state.reason = ""
        self.state.shown_at = 0.0
        for window in self._windows:
            window.withdraw()

    def refresh_monitors(self, monitors: list[Monitor]) -> None:
        self._monitors = monitors
        for window in self._windows:
            window.destroy()
        self._windows.clear()
        self._build_windows()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        for window in self._windows:
            window.destroy()
        self._windows.clear()
        self.root.destroy()

    def poll_emergency_unlock(self) -> bool:
        pressed = (
            is_hotkey_pressed(VK_CONTROL)
            and is_hotkey_pressed(VK_MENU)
            and is_hotkey_pressed(VK_U)
        )
        now = time.monotonic()
        if not pressed:
            self._hotkey_started_at = None
            return False
        if self._hotkey_started_at is None:
            self._hotkey_started_at = now
            return False
        if now - self._hotkey_started_at < self._unlock_hold_seconds:
            return False
        self.state.snoozed_until = now + self._snooze_seconds
        self.hide()
        self._hotkey_started_at = None
        return True

    def _build_windows(self) -> None:
        exclusion_results: list[bool] = []
        for monitor in self._monitors:
            window = tk.Toplevel(self.root)
            window.withdraw()
            window.overrideredirect(True)
            window.configure(bg="black", cursor="none")
            geometry = f"{monitor.width}x{monitor.height}{monitor.left:+d}{monitor.top:+d}"
            window.geometry(geometry)
            window.attributes("-topmost", True)
            window.update_idletasks()
            exclusion_results.append(exclude_window_from_capture(window.winfo_id()))
            self._windows.append(window)
        self.state.capture_exclusion_enabled = bool(exclusion_results) and all(exclusion_results)
