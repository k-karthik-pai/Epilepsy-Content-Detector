from __future__ import annotations

from typing import Protocol

from .models import Monitor


class CaptureSession(Protocol):
    @property
    def monitor(self) -> Monitor:
        ...

    def capture(self) -> bytes:
        ...

    def close(self) -> None:
        ...


class CaptureBackend:
    name = "unknown"
    description = ""

    def enumerate_monitors(self) -> list[Monitor]:
        raise NotImplementedError

    def create_session(self, monitor: Monitor, width: int, height: int) -> CaptureSession:
        raise NotImplementedError


class GdiCaptureBackend(CaptureBackend):
    name = "gdi"
    description = "Win32 GDI StretchBlt capture backend"

    def __init__(self) -> None:
        from . import win32_screen

        self._win32_screen = win32_screen
        self._win32_screen.enable_dpi_awareness()

    def enumerate_monitors(self) -> list[Monitor]:
        return self._win32_screen.enumerate_monitors()

    def create_session(self, monitor: Monitor, width: int, height: int) -> CaptureSession:
        return self._win32_screen.ScaledCaptureSession(monitor, width, height)


def create_capture_backend(name: str = "gdi") -> CaptureBackend:
    normalized = name.strip().lower()
    if normalized == "gdi":
        return GdiCaptureBackend()
    raise ValueError(f"Unknown capture backend: {name}")


def available_capture_backends() -> tuple[str, ...]:
    return ("gdi",)
