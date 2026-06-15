from __future__ import annotations

import argparse
import json
import queue
import sys
import threading
import time
from dataclasses import asdict

from .config import example_config, load_config
from .detector import PhotosensitiveRiskDetector
from .logging_utils import RiskLogger
from .models import AppConfig, RiskDecision, RiskLevel
from .screen_capture import ScreenCapture
from .shield import BlackoutShield
from .synthetic import scenario_frames, scenario_names


class EpilepsyGuardApp:
    def __init__(
        self,
        config: AppConfig,
        duration_seconds: float | None = None,
        print_events: bool = False,
    ):
        self.config = config
        self.duration_seconds = duration_seconds
        self.print_events = print_events
        self.capture = ScreenCapture(config.detector.grid_width, config.detector.grid_height)
        self.detector = PhotosensitiveRiskDetector(config.detector)
        self.logger = RiskLogger(config.log_path)
        self.shield = BlackoutShield(
            self.capture.monitors,
            config.detector.manual_unlock_hold_seconds,
            config.detector.manual_unlock_snooze_seconds,
        )
        self._events: queue.Queue[RiskDecision] = queue.Queue()
        self._stop = threading.Event()
        self._safe_since: float | None = None
        self._last_frame_at = time.monotonic()

    def run(self) -> int:
        self.logger.info(
            "started",
            monitors=[asdict(monitor) for monitor in self.capture.monitors],
            capture_exclusion_enabled=self.shield.state.capture_exclusion_enabled,
        )
        thread = threading.Thread(target=self._capture_loop, name="capture-loop", daemon=True)
        thread.start()
        if self.duration_seconds is not None:
            self.shield.root.after(max(1, int(self.duration_seconds * 1000)), self.shield.root.quit)
        self.shield.root.after(self.config.detector.ui_tick_ms, self._ui_tick)
        try:
            self.shield.root.mainloop()
        finally:
            self._stop.set()
            thread.join(timeout=2.0)
        return 0

    def _capture_loop(self) -> None:
        interval = 1.0 / max(1.0, self.config.detector.sample_fps)
        while not self._stop.is_set():
            started = time.monotonic()
            self._capture_once()
            elapsed = time.monotonic() - started
            time.sleep(max(0.0, interval - elapsed))

    def _capture_once(self) -> None:
        try:
            for frame in self.capture.capture_all():
                decision = self.detector.analyze(frame)
                self._events.put(decision)
            self._last_frame_at = time.monotonic()
        except Exception as exc:
            self.detector.reset_all()
            self.logger.info("capture_error", error=repr(exc))
            time.sleep(0.25)

    def _ui_tick(self) -> None:
        now = time.monotonic()
        self.shield.poll_emergency_unlock()
        self._release_expired_shield(now)

        while True:
            try:
                decision = self._events.get_nowait()
            except queue.Empty:
                break
            self._handle_decision(decision)

        self.shield.root.after(self.config.detector.ui_tick_ms, self._ui_tick)

    def _handle_decision(self, decision: RiskDecision) -> None:
        now = time.monotonic()
        if self.print_events and decision.level is not RiskLevel.SAFE:
            print(json.dumps(_decision_to_dict(decision), separators=(",", ":")), flush=True)
        self._release_expired_shield(now)
        if decision.level is RiskLevel.BLOCK:
            self._safe_since = None
            self.logger.write(decision)
            if not self.config.monitor_only:
                reason = ",".join(decision.reasons) or "RiskDetected"
                self.shield.show(reason)
            return

        if decision.level is RiskLevel.CAUTION:
            self._safe_since = None
            self.logger.write(decision)
            return

        if not self.shield.state.active:
            return
        if (
            self.config.detector.auto_release_requires_capture_exclusion
            and not self.shield.state.capture_exclusion_enabled
        ):
            return
        if now - self.shield.state.shown_at < self.config.detector.blackout_hold_seconds:
            return
        if self._safe_since is None:
            self._safe_since = now
            return
        if now - self._safe_since >= self.config.detector.safe_release_seconds:
            self.logger.info("shield_auto_release")
            self.shield.hide()

    def _release_expired_shield(self, now: float) -> bool:
        if not self.shield.state.active or self.shield.state.shown_at <= 0.0:
            return False
        active_seconds = now - self.shield.state.shown_at
        if active_seconds < self.config.detector.max_blackout_seconds:
            return False
        snoozed_until = now + self.config.detector.manual_unlock_snooze_seconds
        self.shield.state.snoozed_until = max(self.shield.state.snoozed_until, snoozed_until)
        self.logger.info(
            "shield_max_duration_release",
            reason=self.shield.state.reason,
            active_seconds=round(active_seconds, 3),
        )
        self.shield.hide()
        self._safe_since = None
        return True


def run_once(config: AppConfig) -> int:
    capture = ScreenCapture(config.detector.grid_width, config.detector.grid_height)
    detector = PhotosensitiveRiskDetector(config.detector)
    decisions: list[RiskDecision] = []
    for frame in capture.capture_all():
        decisions.append(detector.analyze(frame))
    print(json.dumps([_decision_to_dict(item) for item in decisions], indent=2))
    return 0 if all(item.level is RiskLevel.SAFE for item in decisions) else 2


def run_simulation(
    config: AppConfig,
    scenario: str,
    simulate_shield: bool = False,
    shield_seconds: float = 2.0,
) -> int:
    detector = PhotosensitiveRiskDetector(config.detector)
    decisions = [detector.analyze(frame) for frame in scenario_frames(scenario, config.detector.sample_fps)]
    print(json.dumps([_decision_to_dict(item) for item in decisions], indent=2))
    blocked = any(item.level is RiskLevel.BLOCK for item in decisions)
    if blocked and simulate_shield and not config.monitor_only:
        capture = ScreenCapture(config.detector.grid_width, config.detector.grid_height)
        shield = BlackoutShield(
            capture.monitors,
            config.detector.manual_unlock_hold_seconds,
            config.detector.manual_unlock_snooze_seconds,
        )
        reason = ",".join(
            sorted({reason for decision in decisions for reason in decision.reasons})
        ) or "SyntheticRisk"
        shield.show(reason)
        display_seconds = min(shield_seconds, config.detector.max_blackout_seconds)

        def release_simulated_shield() -> None:
            shield.hide()
            shield.root.quit()

        shield.root.after(max(1, int(display_seconds * 1000)), release_simulated_shield)
        shield.root.mainloop()
        shield.hide()
    return 2 if blocked else 0


def _decision_to_dict(decision: RiskDecision) -> dict[str, object]:
    return {
        "level": decision.level.value,
        "reasons": list(decision.reasons),
        "evidence": [
            {
                "reason": item.reason,
                "monitor_id": item.monitor_id,
                "value": item.value,
                "threshold": item.threshold,
                "detail": item.detail,
            }
            for item in decision.evidence
        ],
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Windows photosensitive-epilepsy screen guard.")
    parser.add_argument("--config", help="Path to JSON config file.")
    parser.add_argument("--once", action="store_true", help="Analyze one screenshot per monitor and exit.")
    parser.add_argument(
        "--monitor-only",
        action="store_true",
        help="Log/print detections without showing the blackout shield. Not recommended for patient use.",
    )
    parser.add_argument("--duration", type=float, help="Run the live loop for this many seconds, then exit.")
    parser.add_argument("--print-events", action="store_true", help="Print non-safe live decisions to the console.")
    parser.add_argument(
        "--simulate",
        choices=scenario_names(),
        help="Run a synthetic frame scenario without displaying flashing content.",
    )
    parser.add_argument(
        "--simulate-shield",
        action="store_true",
        help="During --simulate, show the black shield briefly only if the detector emits block.",
    )
    parser.add_argument("--print-example-config", action="store_true", help="Print an example JSON config.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.print_example_config:
        print(json.dumps(example_config(), indent=2))
        return 0

    config = load_config(args.config)
    if args.monitor_only:
        config.monitor_only = True
    if args.simulate:
        shield_seconds = args.duration if args.duration is not None else 2.0
        return run_simulation(config, args.simulate, args.simulate_shield, shield_seconds)
    if args.once:
        return run_once(config)

    if sys.platform != "win32":
        print("Epilepsy Guard currently requires Windows for screen capture and blackout shielding.", file=sys.stderr)
        return 1
    return EpilepsyGuardApp(config, args.duration, args.print_events).run()


if __name__ == "__main__":
    raise SystemExit(main())
