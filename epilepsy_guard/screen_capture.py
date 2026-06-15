from __future__ import annotations

import time

from .models import Monitor, ScreenFrame
from .win32_screen import capture_bgra_scaled, enable_dpi_awareness, enumerate_monitors


class ScreenCapture:
    def __init__(self, analysis_width: int = 96, analysis_height: int = 54) -> None:
        enable_dpi_awareness()
        self._monitors = enumerate_monitors()
        self._analysis_width = analysis_width
        self._analysis_height = analysis_height

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
                    width=self._analysis_width,
                    height=self._analysis_height,
                    bgra=capture_bgra_scaled(monitor, self._analysis_width, self._analysis_height),
                )
            )
        return frames
