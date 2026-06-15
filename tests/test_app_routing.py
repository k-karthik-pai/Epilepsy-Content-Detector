from __future__ import annotations

import unittest
import queue
import time
from dataclasses import dataclass

from epilepsy_guard.app import EpilepsyGuardApp
from epilepsy_guard.models import AppConfig, Monitor, RiskDecision, RiskLevel, ScreenFrame


@dataclass
class FakeShieldState:
    active: bool = False
    reason: str = ""
    shown_at: float = 0.0
    capture_exclusion_enabled: bool = True
    snoozed_until: float = 0.0


class FakeRoot:
    def __init__(self) -> None:
        self.after_calls: list[tuple[int, object]] = []

    def after(self, delay_ms: int, callback: object) -> None:
        self.after_calls.append((delay_ms, callback))


class FakeShield:
    def __init__(self) -> None:
        self.root = FakeRoot()
        self.state = FakeShieldState()
        self.show_calls: list[str] = []
        self.hide_calls = 0

    def show(self, reason: str) -> None:
        if time.monotonic() < self.state.snoozed_until:
            return
        self.show_calls.append(reason)
        self.state.active = True
        self.state.reason = reason
        if self.state.shown_at == 0.0:
            self.state.shown_at = time.monotonic()

    def hide(self) -> None:
        self.hide_calls += 1
        self.state.active = False
        self.state.reason = ""
        self.state.shown_at = 0.0

    def poll_emergency_unlock(self) -> bool:
        return False


class FakeLogger:
    def __init__(self) -> None:
        self.decisions: list[RiskDecision] = []
        self.messages: list[str] = []

    def write(self, decision: RiskDecision) -> None:
        self.decisions.append(decision)

    def info(self, message: str, **_detail: object) -> None:
        self.messages.append(message)


class FakeCapture:
    def __init__(self, frames: list[ScreenFrame] | None = None, error: Exception | None = None) -> None:
        self.frames = frames or []
        self.error = error

    def capture_all(self) -> list[ScreenFrame]:
        if self.error:
            raise self.error
        return self.frames


class FakeDetector:
    def __init__(self, decision: RiskDecision = RiskDecision.safe()) -> None:
        self.decision = decision
        self.reset_calls = 0

    def analyze(self, _frame: ScreenFrame) -> RiskDecision:
        return self.decision

    def reset_all(self) -> None:
        self.reset_calls += 1


def app_with_fakes(monitor_only: bool = False) -> tuple[EpilepsyGuardApp, FakeShield, FakeLogger]:
    app = object.__new__(EpilepsyGuardApp)
    app.config = AppConfig(monitor_only=monitor_only)
    app.print_events = False
    app.capture = FakeCapture()
    app.detector = FakeDetector()
    app.shield = FakeShield()
    app.logger = FakeLogger()
    app._events = queue.Queue()
    app._safe_since = None
    app._last_frame_at = time.monotonic()
    return app, app.shield, app.logger


class AppRoutingTests(unittest.TestCase):
    def test_safe_decision_does_not_show_shield(self) -> None:
        app, shield, logger = app_with_fakes()
        app._handle_decision(RiskDecision.safe())
        self.assertEqual(shield.show_calls, [])
        self.assertEqual(logger.decisions, [])

    def test_caution_decision_logs_but_does_not_show_shield(self) -> None:
        app, shield, logger = app_with_fakes()
        decision = RiskDecision(RiskLevel.CAUTION, ("FlashSequenceBuilding",))
        app._handle_decision(decision)
        self.assertEqual(shield.show_calls, [])
        self.assertEqual(logger.decisions, [decision])

    def test_block_decision_shows_shield(self) -> None:
        app, shield, logger = app_with_fakes()
        decision = RiskDecision(RiskLevel.BLOCK, ("GeneralFlash",))
        app._handle_decision(decision)
        self.assertEqual(shield.show_calls, ["GeneralFlash"])
        self.assertEqual(logger.decisions, [decision])

    def test_monitor_only_block_does_not_show_shield(self) -> None:
        app, shield, logger = app_with_fakes(monitor_only=True)
        decision = RiskDecision(RiskLevel.BLOCK, ("GeneralFlash",))
        app._handle_decision(decision)
        self.assertEqual(shield.show_calls, [])
        self.assertEqual(logger.decisions, [decision])

    def test_capture_error_logs_and_does_not_enqueue_block(self) -> None:
        app, shield, logger = app_with_fakes()
        app.capture = FakeCapture(error=PermissionError("capture denied"))
        detector = FakeDetector()
        app.detector = detector
        app._capture_once()
        self.assertTrue(app._events.empty())
        self.assertEqual(shield.show_calls, [])
        self.assertEqual(logger.messages, ["capture_error"])
        self.assertEqual(detector.reset_calls, 1)

    def test_capture_once_enqueues_detector_decision(self) -> None:
        app, _shield, _logger = app_with_fakes()
        monitor = Monitor("test", 0, 0, 1, 1, True)
        frame = ScreenFrame(monitor, time.monotonic(), 1, 1, bytes((0, 0, 0, 255)))
        decision = RiskDecision(RiskLevel.BLOCK, ("GeneralFlash",))
        app.capture = FakeCapture(frames=[frame])
        app.detector = FakeDetector(decision)
        app._capture_once()
        self.assertEqual(app._events.get_nowait(), decision)

    def test_expired_shield_releases_even_without_capture_exclusion(self) -> None:
        app, shield, logger = app_with_fakes()
        now = time.monotonic()
        shield.state.active = True
        shield.state.reason = "GeneralFlash"
        shield.state.shown_at = now - app.config.detector.max_blackout_seconds - 0.1
        shield.state.capture_exclusion_enabled = False
        app._handle_decision(RiskDecision.safe())
        self.assertFalse(shield.state.active)
        self.assertEqual(shield.hide_calls, 1)
        self.assertIn("shield_max_duration_release", logger.messages)
        self.assertGreater(shield.state.snoozed_until, now)

    def test_expired_shield_snoozes_immediate_reblock(self) -> None:
        app, shield, logger = app_with_fakes()
        now = time.monotonic()
        shield.state.active = True
        shield.state.reason = "GeneralFlash"
        shield.state.shown_at = now - app.config.detector.max_blackout_seconds - 0.1
        shield.state.capture_exclusion_enabled = False
        decision = RiskDecision(RiskLevel.BLOCK, ("GeneralFlash",))
        app._handle_decision(decision)
        self.assertEqual(shield.hide_calls, 1)
        self.assertEqual(shield.show_calls, [])
        self.assertFalse(shield.state.active)
        self.assertIn("shield_max_duration_release", logger.messages)

    def test_ui_tick_releases_expired_shield_without_new_events(self) -> None:
        app, shield, logger = app_with_fakes()
        now = time.monotonic()
        shield.state.active = True
        shield.state.reason = "GeneralFlash"
        shield.state.shown_at = now - app.config.detector.max_blackout_seconds - 0.1
        shield.state.capture_exclusion_enabled = False
        app._ui_tick()
        self.assertFalse(shield.state.active)
        self.assertEqual(shield.hide_calls, 1)
        self.assertIn("shield_max_duration_release", logger.messages)
        self.assertEqual(shield.root.after_calls[0][0], app.config.detector.ui_tick_ms)


if __name__ == "__main__":
    unittest.main()
