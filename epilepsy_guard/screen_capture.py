from __future__ import annotations

import time

from .capture_backends import CaptureBackend, CaptureSession, create_capture_backend
from .models import Monitor, ScreenFrame


class ScreenCapture:
    def __init__(
        self,
        analysis_width: int = 40,
        analysis_height: int = 24,
        backend: CaptureBackend | None = None,
    ) -> None:
        self._analysis_width = analysis_width
        self._analysis_height = analysis_height
        self._backend = backend or create_capture_backend()
        self._monitors: list[Monitor] = []
        self._sessions: list[CaptureSession] = []
        self._monitors = self._backend.enumerate_monitors()
        self._sessions = self._build_sessions(self._monitors)

    @property
    def monitors(self) -> list[Monitor]:
        return list(self._monitors)

    @property
    def backend_name(self) -> str:
        return self._backend.name

    @property
    def backend_description(self) -> str:
        return self._backend.description

    def enumerate_monitors(self) -> list[Monitor]:
        return self._backend.enumerate_monitors()

    def refresh_monitors(self) -> list[Monitor]:
        self.close()
        self._monitors = self.enumerate_monitors()
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

    def _build_sessions(self, monitors: list[Monitor]) -> list[CaptureSession]:
        return [
            self._backend.create_session(monitor, self._analysis_width, self._analysis_height)
            for monitor in monitors
        ]

    def __del__(self) -> None:
        self.close()
