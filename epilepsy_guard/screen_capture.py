from __future__ import annotations

import time

from .models import Monitor, ScreenFrame
from .win32_screen import ScaledCaptureSession, enable_dpi_awareness, enumerate_monitors


class ScreenCapture:
    def __init__(self, analysis_width: int = 96, analysis_height: int = 54) -> None:
        enable_dpi_awareness()
        self._analysis_width = analysis_width
        self._analysis_height = analysis_height
        self._monitors: list[Monitor] = []
        self._sessions: list[ScaledCaptureSession] = []
        self._monitors = enumerate_monitors()
        self._sessions = self._build_sessions(self._monitors)

    @property
    def monitors(self) -> list[Monitor]:
        return list(self._monitors)

    def refresh_monitors(self) -> list[Monitor]:
        self.close()
        self._monitors = enumerate_monitors()
        self._sessions = self._build_sessions(self._monitors)
        return self.monitors

    def capture_all(self) -> list[ScreenFrame]:
        frames: list[ScreenFrame] = []
        now = time.monotonic()
        for session in self._sessions:
            monitor = session.monitor
            frames.append(
                ScreenFrame(
                    monitor=monitor,
                    timestamp=now,
                    width=self._analysis_width,
                    height=self._analysis_height,
                    bgra=session.capture(),
                )
            )
        return frames

    def close(self) -> None:
        for session in self._sessions:
            session.close()
        self._sessions = []

    def _build_sessions(self, monitors: list[Monitor]) -> list[ScaledCaptureSession]:
        return [
            ScaledCaptureSession(monitor, self._analysis_width, self._analysis_height)
            for monitor in monitors
        ]

    def __del__(self) -> None:
        self.close()
