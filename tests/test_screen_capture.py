from __future__ import annotations

import unittest

from epilepsy_guard.capture_backends import CaptureBackend
from epilepsy_guard.models import Monitor
from epilepsy_guard.screen_capture import ScreenCapture


class FakeSession:
    def __init__(self, monitor: Monitor, width: int, height: int) -> None:
        self._monitor = monitor
        self._width = width
        self._height = height
        self.closed = False

    @property
    def monitor(self) -> Monitor:
        return self._monitor

    def capture(self) -> bytes:
        return bytes((0, 0, 0, 255)) * self._width * self._height

    def close(self) -> None:
        self.closed = True


class FakeBackend(CaptureBackend):
    name = "fake"
    description = "Fake capture backend"

    def __init__(self) -> None:
        self.monitors = [Monitor("fake-1", 0, 0, 100, 50, True)]
        self.sessions: list[FakeSession] = []

    def enumerate_monitors(self) -> list[Monitor]:
        return list(self.monitors)

    def create_session(self, monitor: Monitor, width: int, height: int) -> FakeSession:
        session = FakeSession(monitor, width, height)
        self.sessions.append(session)
        return session


class ScreenCaptureTests(unittest.TestCase):
    def test_capture_uses_backend_metadata_and_sessions(self) -> None:
        backend = FakeBackend()
        capture = ScreenCapture(10, 6, backend=backend)
        try:
            frames = capture.capture_all()
            self.assertEqual(capture.backend_name, "fake")
            self.assertEqual(capture.backend_description, "Fake capture backend")
            self.assertEqual(len(frames), 1)
            self.assertEqual(frames[0].monitor.id, "fake-1")
            self.assertEqual(frames[0].width, 10)
            self.assertEqual(frames[0].height, 6)
            self.assertEqual(len(frames[0].bgra), 10 * 6 * 4)
        finally:
            capture.close()
        self.assertTrue(all(session.closed for session in backend.sessions))


if __name__ == "__main__":
    unittest.main()
