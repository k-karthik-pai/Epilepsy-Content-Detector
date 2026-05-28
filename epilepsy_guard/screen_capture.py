from __future__ import annotations

import time

from .models import Monitor, ScreenFrame
from .win32_screen import capture_bgra, enable_dpi_awareness, enumerate_monitors


class ScreenCapture:
    def __init__(self) -> None:
        enable_dpi_awareness()
        self._monitors = enumerate_monitors()

    @property
    def monitors(self) -> list[Monitor]:
        return list(self._monitors)

    def refresh_monitors(self) -> list[Monitor]:
        self._monitors = enumerate_monitors()
        return self.monitors

    def capture_all(self) -> list[ScreenFrame]:
        frames: list[ScreenFrame] = []
        now = time.monotonic()
        for monitor in self._monitors:
            frames.append(
                ScreenFrame(
                    monitor=monitor,
                    timestamp=now,
                    width=monitor.width,
                    height=monitor.height,
                    bgra=capture_bgra(monitor),
                )
            )
        return frames

