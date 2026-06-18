from __future__ import annotations

import argparse
import json
import queue
import sys
import threading
import time
from dataclasses import asdict

from .config import example_config, load_config
from .capture_backends import available_capture_backends, create_capture_backend
from .detector import PhotosensitiveRiskDetector
from .logging_utils import RiskLogger
from .models import AppConfig, Monitor, RiskDecision, RiskLevel
from .screen_capture import ScreenCapture
from .shield import BlackoutShield
from .single_instance import SingleInstanceLock
from .synthetic import scenario_frames, scenario_names


LIVE_INSTANCE_MUTEX = "Local\\EpilepsyGuard.Live"


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
        self.capture = _create_capture(config)
        self.detector = PhotosensitiveRiskDetector(config.detector)
        self.logger = RiskLogger(config.log_path, config.log_max_bytes, config.log_backup_count)
        self.shield = BlackoutShield(
            self.capture.monitors,
            config.detector.manual_unlock_hold_seconds,
            config.detector.manual_unlock_snooze_seconds,
        )
        self._events: queue.Queue[RiskDecision] = queue.Queue(maxsize=config.decision_queue_size)
        self._stop = threading.Event()
        self._capture_lock = threading.Lock()
        self._safe_since: float | None = None
        self._last_frame_at = time.monotonic()
        self._last_monitor_refresh_at = self._last_frame_at
        self._detector_resume_at = 0.0
        self._capture_error_count = 0
        self._decision_drop_count = 0
        self._known_monitor_signature = self._monitor_signature(self.capture.monitors)

    def run(self) -> int:
        self.logger.info(
            "started",
            monitors=[asdict(monitor) for monitor in self.capture.monitors],
            capture_backend=self.capture.backend_name,
            capture_exclusion_enabled=self.shield.state.capture_exclusion_enabled,
            monitor_refresh_seconds=self.config.monitor_refresh_seconds,
            detector_rearm_seconds=self.config.detector_rearm_seconds,
            capture_recovery_error_threshold=self.config.capture_recovery_error_threshold,
            decision_queue_size=self.config.decision_queue_size,
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
            self.capture.close()
            self.shield.close()
        return 0

    def _capture_loop(self) -> None:
        interval = 1.0 / max(1.0, self.config.detector.sample_fps)
        while not self._stop.is_set():
            started = time.monotonic()
            self._capture_once()
            elapsed = time.monotonic() - started
            self._stop.wait(max(0.0, interval - elapsed))

    def _capture_once(self) -> None:
        now = time.monotonic()
        if now < self._detector_resume_at or (
            self.shield.state.active and not self.shield.state.capture_exclusion_enabled
        ):
            self._enqueue_decision(RiskDecision.safe())
            self._last_frame_at = now
            return
        try:
            with self._capture_lock:
                for frame in self.capture.capture_all():
                    decision = self.detector.analyze(frame)
                    self._enqueue_decision(decision)
            self._capture_error_count = 0
            self._last_frame_at = time.monotonic()
        except Exception as exc:
            self._capture_error_count += 1
            with self._capture_lock:
                self.detector.reset_all()
            self.logger.info(
                "capture_error",
                error=repr(exc),
                consecutive_errors=self._capture_error_count,
            )
            if self._capture_error_count >= self.config.capture_recovery_error_threshold:
                self._recover_capture_sessions()
            self._stop.wait(self.config.capture_error_backoff_seconds)

    def _enqueue_decision(self, decision: RiskDecision) -> bool:
        try:
            self._events.put_nowait(decision)
            return True
        except queue.Full:
            self._record_decision_drop()
            if decision.level is not RiskLevel.BLOCK:
                return False

        while True:
            try:
                self._events.get_nowait()
            except queue.Empty:
                pass
            try:
                self._events.put_nowait(decision)
                return True
            except queue.Full:
                continue

    def _record_decision_drop(self) -> None:
        self._decision_drop_count += 1
        if self._decision_drop_count == 1 or self._decision_drop_count % 100 == 0:
            self.logger.info(
                "decision_queue_overflow",
                dropped_decisions=self._decision_drop_count,
                queue_size=self.config.decision_queue_size,
            )

    def _recover_capture_sessions(self) -> bool:
        try:
            with self._capture_lock:
                monitors = self.capture.refresh_monitors()
                self.detector.reset_all()
            self._capture_error_count = 0
            self.logger.info(
                "capture_sessions_rebuilt",
                monitors=[asdict(monitor) for monitor in monitors],
            )
            return True
        except Exception as exc:
            self.logger.info(
                "capture_recovery_error",
                error=repr(exc),
                consecutive_errors=self._capture_error_count,
            )
            return False

    def _ui_tick(self) -> None:
        now = time.monotonic()
        if self.shield.poll_emergency_unlock():
            self._rearm_detector(now, "manual_unlock")
        self._refresh_monitor_topology_if_due(now)
        self._release_expired_shield(now)

        pending: list[RiskDecision] = []
        while True:
            try:
                pending.append(self._events.get_nowait())
            except queue.Empty:
                break
        pending.sort(key=lambda decision: decision.level is not RiskLevel.BLOCK)
        for decision in pending:
            self._handle_decision(decision)

        self.shield.root.after(self.config.detector.ui_tick_ms, self._ui_tick)

    def _refresh_monitor_topology_if_due(self, now: float) -> bool:
        if now - self._last_monitor_refresh_at < self.config.monitor_refresh_seconds:
            return False
        self._last_monitor_refresh_at = now
        return self._refresh_monitor_topology()

    def _refresh_monitor_topology(self) -> bool:
        try:
            detected_monitors = self.capture.enumerate_monitors()
        except Exception as exc:
            self.logger.info("monitor_refresh_error", error=repr(exc))
            return False

        detected_signature = self._monitor_signature(detected_monitors)
        if detected_signature == self._known_monitor_signature:
            return False

        try:
            with self._capture_lock:
                refreshed_monitors = self.capture.refresh_monitors()
                self.detector.reset_all()
            self.shield.refresh_monitors(refreshed_monitors)
            self._known_monitor_signature = self._monitor_signature(refreshed_monitors)
            self.logger.info(
                "monitor_topology_changed",
                monitors=[asdict(monitor) for monitor in refreshed_monitors],
            )
            return True
        except Exception as exc:
            self.logger.info("monitor_refresh_error", error=repr(exc))
            return False

    def _handle_decision(self, decision: RiskDecision) -> None:
        now = time.monotonic()
        if self.print_events and decision.level is not RiskLevel.SAFE:
            print(json.dumps(_decision_to_dict(decision), separators=(",", ":")), flush=True)
        self._release_expired_shield(now)
        if decision.level is RiskLevel.BLOCK:
            self._safe_since = None
            if self.config.monitor_only:
                self.logger.write(decision)
                return
            if self.shield.state.active:
                return
            reason = ",".join(decision.reasons) or "RiskDetected"
            self.shield.show(reason)
            if self.shield.state.active and not self.shield.state.capture_exclusion_enabled:
                self._reset_detector_state()
            self.logger.write(decision)
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
            self._rearm_detector(now, "auto_release")

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
        self._rearm_detector(now, "max_duration_release")
        return True

    def _reset_detector_state(self) -> None:
        with self._capture_lock:
            self.detector.reset_all()

    def _rearm_detector(self, now: float, reason: str) -> None:
        self._reset_detector_state()
        self._detector_resume_at = max(
            self._detector_resume_at,
            now + self.config.detector_rearm_seconds,
        )
        self._safe_since = None
        self.logger.info(
            "detector_rearmed",
            reason=reason,
            rearm_seconds=self.config.detector_rearm_seconds,
        )

    def _monitor_signature(self, monitors: list[Monitor]) -> tuple[tuple[object, ...], ...]:
        signatures = [
            (
                monitor.id,
                monitor.left,
                monitor.top,
                monitor.width,
                monitor.height,
                monitor.primary,
            )
            for monitor in monitors
        ]
        return tuple(sorted(signatures, key=lambda item: str(item[0])))


def run_once(config: AppConfig) -> int:
    capture = _create_capture(config)
    decisions: list[RiskDecision] = []
    try:
        detector = PhotosensitiveRiskDetector(config.detector)
        for frame in capture.capture_all():
            decisions.append(detector.analyze(frame))
    finally:
        capture.close()
    print(json.dumps([_decision_to_dict(item) for item in decisions], indent=2))
    return 0 if all(item.level is RiskLevel.SAFE for item in decisions) else 2


def benchmark_capture(config: AppConfig, frame_count: int = 60) -> int:
    result = _measure_capture(config, frame_count)
    print(json.dumps(result, indent=2))
    return 0


def benchmark_latency(config: AppConfig, frame_count: int = 60) -> int:
    capture_result = _measure_capture(config, frame_count)
    measured_fps = float(capture_result["measured_fps"])
    scenarios = [
        _scenario_latency(config, scenario, measured_fps)
        for scenario in ("general-flash", "windowed-flash", "small-windowed-flash", "red-flash")
    ]
    print(
        json.dumps(
            {
                "capture": capture_result,
                "scenarios": scenarios,
                "note": "Estimates use synthetic frames; they do not display flashing content.",
            },
            indent=2,
        )
    )
    return 0


def health_check(config: AppConfig, frame_count: int = 20) -> int:
    checks: list[dict[str, object]] = []
    result: dict[str, object] = {
        "status": "pass",
        "platform": sys.platform,
        "python": sys.version.split()[0],
        "log_path": config.log_path,
        "log_max_bytes": config.log_max_bytes,
        "log_backup_count": config.log_backup_count,
        "monitor_refresh_seconds": config.monitor_refresh_seconds,
        "detector_rearm_seconds": config.detector_rearm_seconds,
        "capture_recovery_error_threshold": config.capture_recovery_error_threshold,
        "capture_error_backoff_seconds": config.capture_error_backoff_seconds,
        "decision_queue_size": config.decision_queue_size,
        "monitor_only": config.monitor_only,
        "capture_backend": config.capture_backend,
        "available_capture_backends": list(available_capture_backends()),
        "detector": {
            "sample_fps": config.detector.sample_fps,
            "grid_width": config.detector.grid_width,
            "grid_height": config.detector.grid_height,
            "ui_tick_ms": config.detector.ui_tick_ms,
        },
        "checks": checks,
    }

    def add_check(name: str, status: str, **detail: object) -> None:
        checks.append({"name": name, "status": status, "detail": detail})
        if status == "fail":
            result["status"] = "fail"
        elif status == "warn" and result["status"] != "fail":
            result["status"] = "warn"

    if sys.platform != "win32":
        add_check("platform", "fail", message="Windows is required for capture and shielding.")
        print(json.dumps(result, indent=2))
        return 1
    add_check("platform", "pass")

    try:
        capture_result = _measure_capture(config, frame_count)
        result["capture"] = capture_result
        measured_fps = float(capture_result["measured_fps"])
        add_check(
            "capture",
            "pass" if measured_fps > 0 else "fail",
            measured_fps=measured_fps,
            analysis_size=capture_result["analysis_size"],
        )
    except Exception as exc:
        add_check("capture", "fail", error=repr(exc))

    try:
        capture = _create_capture(config)
        try:
            monitors = capture.monitors
            result["monitors"] = [asdict(monitor) for monitor in monitors]
            add_check("monitors", "pass" if monitors else "fail", count=len(monitors))
            shield = BlackoutShield(
                monitors,
                config.detector.manual_unlock_hold_seconds,
                config.detector.manual_unlock_snooze_seconds,
            )
            try:
                status = "pass" if shield.state.capture_exclusion_enabled else "warn"
                add_check(
                    "shield",
                    status,
                    capture_exclusion_enabled=shield.state.capture_exclusion_enabled,
                    message=(
                        "Shield windows can be excluded from capture."
                        if shield.state.capture_exclusion_enabled
                        else "Shield works, but Windows capture exclusion is unavailable on this PC."
                    ),
                )
            finally:
                shield.close()
        finally:
            capture.close()
    except Exception as exc:
        add_check("shield", "fail", error=repr(exc))

    measured_fps = float(result.get("capture", {}).get("measured_fps", 0.0)) if isinstance(result.get("capture"), dict) else 0.0
    result["latency_estimates"] = [
        _scenario_latency(config, scenario, measured_fps)
        for scenario in ("general-flash", "windowed-flash", "small-windowed-flash", "red-flash")
    ]
    print(json.dumps(result, indent=2))
    return 0 if result["status"] in {"pass", "warn"} else 1


def _measure_capture(config: AppConfig, frame_count: int = 60) -> dict[str, object]:
    capture = _create_capture(config)
    durations: list[float] = []
    try:
        for _ in range(max(1, frame_count)):
            started = time.perf_counter()
            capture.capture_all()
            durations.append(time.perf_counter() - started)
    finally:
        capture.close()

    total_frames = len(durations) * max(1, len(capture.monitors))
    total_seconds = sum(durations)
    mean_seconds = total_seconds / max(1, len(durations))
    result = {
        "monitors": len(capture.monitors),
        "backend": capture.backend_name,
        "backend_description": capture.backend_description,
        "captures": len(durations),
        "analysis_size": {
            "width": config.detector.grid_width,
            "height": config.detector.grid_height,
        },
        "target_fps": config.detector.sample_fps,
        "measured_fps": round(total_frames / total_seconds, 2) if total_seconds else 0.0,
        "mean_capture_ms": round(mean_seconds * 1000, 2),
        "min_capture_ms": round(min(durations) * 1000, 2),
        "max_capture_ms": round(max(durations) * 1000, 2),
    }
    return result


def _scenario_latency(config: AppConfig, scenario: str, measured_fps: float) -> dict[str, object]:
    detector = PhotosensitiveRiskDetector(config.detector)
    first_block_index: int | None = None
    first_block_timestamp: float | None = None
    first_block_reasons: tuple[str, ...] = ()
    for index, frame in enumerate(scenario_frames(scenario, config.detector.sample_fps)):
        decision = detector.analyze(frame)
        if decision.level is RiskLevel.BLOCK:
            first_block_index = index
            first_block_timestamp = frame.timestamp
            first_block_reasons = decision.reasons
            break

    if first_block_index is None:
        return {
            "scenario": scenario,
            "blocks": False,
        }

    estimated_live_ms = None
    if measured_fps > 0:
        estimated_live_ms = round((first_block_index / measured_fps) * 1000 + config.detector.ui_tick_ms, 2)

    return {
        "scenario": scenario,
        "blocks": True,
        "first_block_frame_index": first_block_index,
        "synthetic_time_ms": round((first_block_timestamp or 0.0) * 1000, 2),
        "estimated_live_ms_at_measured_capture_fps": estimated_live_ms,
        "reasons": list(first_block_reasons),
    }


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
        capture = _create_capture(config)
        try:
            shield = BlackoutShield(
                capture.monitors,
                config.detector.manual_unlock_hold_seconds,
                config.detector.manual_unlock_snooze_seconds,
            )
            try:
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
            finally:
                shield.close()
        finally:
            capture.close()
    return 2 if blocked else 0


def _create_capture(config: AppConfig) -> ScreenCapture:
    return ScreenCapture(
        config.detector.grid_width,
        config.detector.grid_height,
        backend=create_capture_backend(config.capture_backend),
    )


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
        "--benchmark-capture",
        action="store_true",
        help="Measure real screen capture speed without showing the shield.",
    )
    parser.add_argument(
        "--benchmark-latency",
        action="store_true",
        help="Estimate live block latency from measured capture FPS and synthetic risky scenarios.",
    )
    parser.add_argument(
        "--health-check",
        action="store_true",
        help="Run local diagnostics for capture, monitors, shield, config, and latency estimates.",
    )
    parser.add_argument(
        "--benchmark-frames",
        type=int,
        default=60,
        help="Number of capture iterations for benchmark and health-check commands.",
    )
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

    try:
        config = load_config(args.config)
    except (OSError, ValueError) as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2

    try:
        if args.monitor_only:
            config.monitor_only = True
        if args.benchmark_capture:
            return benchmark_capture(config, args.benchmark_frames)
        if args.benchmark_latency:
            return benchmark_latency(config, args.benchmark_frames)
        if args.health_check:
            return health_check(config, args.benchmark_frames)
        if args.simulate:
            shield_seconds = args.duration if args.duration is not None else 2.0
            return run_simulation(config, args.simulate, args.simulate_shield, shield_seconds)
        if args.once:
            return run_once(config)

        if sys.platform != "win32":
            print("Epilepsy Guard currently requires Windows for screen capture and blackout shielding.", file=sys.stderr)
            return 1
        with SingleInstanceLock(LIVE_INSTANCE_MUTEX) as instance_lock:
            if not instance_lock.acquired:
                print("Epilepsy Guard is already running.", file=sys.stderr)
                return 3
            return EpilepsyGuardApp(config, args.duration, args.print_events).run()
    except KeyboardInterrupt:
        print("Epilepsy Guard stopped.", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"Epilepsy Guard error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
