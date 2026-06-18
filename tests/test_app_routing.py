from __future__ import annotations

import unittest
import queue
import threading
import time
from dataclasses import dataclass

from epilepsy_guard.app import EpilepsyGuardApp, _scenario_latency
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
        self.refresh_calls: list[list[Monitor]] = []

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

    def refresh_monitors(self, monitors: list[Monitor]) -> None:
        self.refresh_calls.append(list(monitors))


class FakeLogger:
    def __init__(self) -> None:
        self.decisions: list[RiskDecision] = []
        self.messages: list[str] = []

    def write(self, decision: RiskDecision) -> None:
        self.decisions.append(decision)

    def info(self, message: str, **_detail: object) -> None:
        self.messages.append(message)


class FakeCapture:
    def __init__(
        self,
        frames: list[ScreenFrame] | None = None,
        error: Exception | None = None,
        monitors: list[Monitor] | None = None,
    ) -> None:
        self.frames = frames or []
        self.error = error
        self.monitors = monitors or [Monitor("test", 0, 0, 100, 50, True)]
        self.detected_monitors = list(self.monitors)
        self.refresh_calls = 0
        self.capture_calls = 0

    def capture_all(self) -> list[ScreenFrame]:
        self.capture_calls += 1
        if self.error:
            raise self.error
        return self.frames

    def enumerate_monitors(self) -> list[Monitor]:
        return list(self.detected_monitors)

    def refresh_monitors(self) -> list[Monitor]:
        self.refresh_calls += 1
        self.monitors = list(self.detected_monitors)
        return list(self.monitors)


class FakeDetector:
    def __init__(self, decision: RiskDecision = RiskDecision.safe()) -> None:
        self.decision = decision
        self.reset_calls = 0
        self.analyze_calls = 0

    def analyze(self, _frame: ScreenFrame) -> RiskDecision:
        self.analyze_calls += 1
        return self.decision

    def reset_all(self) -> None:
        self.reset_calls += 1


def app_with_fakes(monitor_only: bool = False) -> tuple[EpilepsyGuardApp, FakeShield, FakeLogger]:
    app = object.__new__(EpilepsyGuardApp)
    app.config = AppConfig(monitor_only=monitor_only)
    app.config.capture_error_backoff_seconds = 0.0
    app.print_events = False
    app.capture = FakeCapture()
    app.detector = FakeDetector()
    app.shield = FakeShield()
    app.logger = FakeLogger()
    app._events = queue.Queue()
    app._stop = threading.Event()
    app._capture_lock = threading.Lock()
    app._safe_since = None
    app._last_frame_at = time.monotonic()
    app._last_monitor_refresh_at = app._last_frame_at
    app._detector_resume_at = 0.0
    app._capture_error_count = 0
    app._decision_drop_count = 0
    app._known_monitor_signature = app._monitor_signature(app.capture.monitors)
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

    def test_repeated_capture_errors_rebuild_sessions(self) -> None:
        app, _shield, logger = app_with_fakes()
        app.config.capture_recovery_error_threshold = 2
        app.capture = FakeCapture(error=PermissionError("capture denied"))
        detector = FakeDetector()
        app.detector = detector

        app._capture_once()
        app._capture_once()

        self.assertEqual(app.capture.refresh_calls, 1)
        self.assertEqual(app._capture_error_count, 0)
        self.assertEqual(detector.reset_calls, 3)
        self.assertEqual(logger.messages, ["capture_error", "capture_error", "capture_sessions_rebuilt"])

    def test_successful_capture_resets_error_counter(self) -> None:
        app, _shield, _logger = app_with_fakes()
        app._capture_error_count = 2

        app._capture_once()

        self.assertEqual(app._capture_error_count, 0)

    def test_capture_once_enqueues_detector_decision(self) -> None:
        app, _shield, _logger = app_with_fakes()
        monitor = Monitor("test", 0, 0, 1, 1, True)
        frame = ScreenFrame(monitor, time.monotonic(), 1, 1, bytes((0, 0, 0, 255)))
        decision = RiskDecision(RiskLevel.BLOCK, ("GeneralFlash",))
        app.capture = FakeCapture(frames=[frame])
        app.detector = FakeDetector(decision)
        app._capture_once()
        self.assertEqual(app._events.get_nowait(), decision)

    def test_capture_skips_shield_frames_without_capture_exclusion(self) -> None:
        app, shield, _logger = app_with_fakes()
        monitor = Monitor("test", 0, 0, 1, 1, True)
        frame = ScreenFrame(monitor, time.monotonic(), 1, 1, bytes((0, 0, 0, 255)))
        app.capture = FakeCapture(frames=[frame])
        detector = FakeDetector(RiskDecision(RiskLevel.BLOCK, ("GeneralFlash",)))
        app.detector = detector
        shield.state.active = True
        shield.state.capture_exclusion_enabled = False

        app._capture_once()

        self.assertEqual(app.capture.capture_calls, 0)
        self.assertEqual(detector.analyze_calls, 0)
        self.assertEqual(app._events.get_nowait(), RiskDecision.safe())

    def test_first_block_resets_detector_when_shield_is_captured(self) -> None:
        app, shield, logger = app_with_fakes()
        shield.state.capture_exclusion_enabled = False
        decision = RiskDecision(RiskLevel.BLOCK, ("GeneralFlash",))

        app._handle_decision(decision)

        self.assertEqual(shield.show_calls, ["GeneralFlash"])
        self.assertEqual(app.detector.reset_calls, 1)
        self.assertEqual(logger.decisions, [decision])

    def test_duplicate_block_while_shield_active_is_ignored(self) -> None:
        app, shield, logger = app_with_fakes()
        shield.state.active = True
        shield.state.reason = "GeneralFlash"
        decision = RiskDecision(RiskLevel.BLOCK, ("GeneralFlash",))

        app._handle_decision(decision)

        self.assertEqual(shield.show_calls, [])
        self.assertEqual(logger.decisions, [])

    def test_ui_tick_prioritizes_block_decisions(self) -> None:
        app, _shield, _logger = app_with_fakes()
        handled: list[RiskLevel] = []

        def record_decision(decision: RiskDecision) -> None:
            handled.append(decision.level)

        app._handle_decision = record_decision  # type: ignore[method-assign]
        for _ in range(25):
            app._events.put(RiskDecision.safe())
        app._events.put(RiskDecision(RiskLevel.BLOCK, ("GeneralFlash",)))
        app._events.put(RiskDecision(RiskLevel.CAUTION, ("RegularPattern",)))
        app._ui_tick()
        self.assertEqual(handled[0], RiskLevel.BLOCK)
        self.assertEqual(len(handled), 27)

    def test_full_queue_drops_new_safe_decision(self) -> None:
        app, _shield, logger = app_with_fakes()
        app.config.decision_queue_size = 1
        app._events = queue.Queue(maxsize=1)
        original = RiskDecision.safe()
        app._events.put_nowait(original)

        enqueued = app._enqueue_decision(RiskDecision.safe())

        self.assertFalse(enqueued)
        self.assertEqual(app._events.get_nowait(), original)
        self.assertEqual(app._decision_drop_count, 1)
        self.assertIn("decision_queue_overflow", logger.messages)

    def test_full_queue_preserves_new_block_decision(self) -> None:
        app, _shield, _logger = app_with_fakes()
        app.config.decision_queue_size = 2
        app._events = queue.Queue(maxsize=2)
        app._events.put_nowait(RiskDecision.safe())
        app._events.put_nowait(RiskDecision(RiskLevel.CAUTION, ("RegularPattern",)))
        block = RiskDecision(RiskLevel.BLOCK, ("GeneralFlash",))

        enqueued = app._enqueue_decision(block)
        queued = [app._events.get_nowait(), app._events.get_nowait()]

        self.assertTrue(enqueued)
        self.assertIn(block, queued)
        self.assertEqual(app._decision_drop_count, 1)

    def test_scenario_latency_estimates_windowed_block(self) -> None:
        result = _scenario_latency(AppConfig(), "small-windowed-flash", measured_fps=20.0)
        self.assertTrue(result["blocks"])
        self.assertEqual(result["reasons"], ["LocalizedFlash"])
        self.assertLessEqual(result["estimated_live_ms_at_measured_capture_fps"], 250.0)

    def test_monitor_topology_refresh_rebuilds_capture_and_shield(self) -> None:
        app, shield, logger = app_with_fakes()
        new_monitors = [
            Monitor("primary", 0, 0, 1920, 1080, True),
            Monitor("secondary", 1920, 0, 1280, 1024, False),
        ]
        app.capture.detected_monitors = new_monitors

        changed = app._refresh_monitor_topology()

        self.assertTrue(changed)
        self.assertEqual(app.capture.refresh_calls, 1)
        self.assertEqual(shield.refresh_calls, [new_monitors])
        self.assertEqual(app.detector.reset_calls, 1)
        self.assertIn("monitor_topology_changed", logger.messages)

    def test_monitor_topology_refresh_is_noop_when_unchanged(self) -> None:
        app, shield, logger = app_with_fakes()

        changed = app._refresh_monitor_topology()

        self.assertFalse(changed)
        self.assertEqual(app.capture.refresh_calls, 0)
        self.assertEqual(shield.refresh_calls, [])
        self.assertEqual(app.detector.reset_calls, 0)
        self.assertNotIn("monitor_topology_changed", logger.messages)

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
        self.assertGreater(app._detector_resume_at, now)
        self.assertEqual(app.detector.reset_calls, 1)

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
