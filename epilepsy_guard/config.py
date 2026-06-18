from __future__ import annotations

import json
import os
from dataclasses import fields, is_dataclass
from pathlib import Path
from typing import Any, TypeVar

from .capture_backends import available_capture_backends
from .models import AppConfig, DetectorConfig

T = TypeVar("T")


def default_log_path() -> str:
    root = os.environ.get("LOCALAPPDATA") or str(Path.home())
    return str(Path(root) / "EpilepsyGuard" / "events.jsonl")


def load_config(path: str | None) -> AppConfig:
    config = AppConfig()
    config.log_path = default_log_path()
    if not path:
        return validate_config(config)

    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Config root must be a JSON object.")

    if "detector" in data:
        config.detector = _merge_dataclass(config.detector, data["detector"])
    if "log_path" in data:
        config.log_path = data["log_path"]
    if "monitor_only" in data:
        config.monitor_only = _coerce_value(config.monitor_only, data["monitor_only"])
    if "capture_backend" in data:
        config.capture_backend = str(data["capture_backend"])
    if "log_max_bytes" in data:
        config.log_max_bytes = _coerce_value(config.log_max_bytes, data["log_max_bytes"])
    if "log_backup_count" in data:
        config.log_backup_count = _coerce_value(config.log_backup_count, data["log_backup_count"])
    if "monitor_refresh_seconds" in data:
        config.monitor_refresh_seconds = _coerce_value(
            config.monitor_refresh_seconds,
            data["monitor_refresh_seconds"],
        )
    if "detector_rearm_seconds" in data:
        config.detector_rearm_seconds = _coerce_value(
            config.detector_rearm_seconds,
            data["detector_rearm_seconds"],
        )
    if "capture_recovery_error_threshold" in data:
        config.capture_recovery_error_threshold = _coerce_value(
            config.capture_recovery_error_threshold,
            data["capture_recovery_error_threshold"],
        )
    if "capture_error_backoff_seconds" in data:
        config.capture_error_backoff_seconds = _coerce_value(
            config.capture_error_backoff_seconds,
            data["capture_error_backoff_seconds"],
        )
    if "decision_queue_size" in data:
        config.decision_queue_size = _coerce_value(
            config.decision_queue_size,
            data["decision_queue_size"],
        )
    return validate_config(config)


def _merge_dataclass(instance: T, values: dict[str, Any]) -> T:
    if not is_dataclass(instance):
        raise TypeError("Expected a dataclass instance.")
    if not isinstance(values, dict):
        raise ValueError("Dataclass override must be a JSON object.")

    allowed = {field.name for field in fields(instance)}
    unknown = set(values) - allowed
    if unknown:
        names = ", ".join(sorted(unknown))
        raise ValueError(f"Unknown config field(s): {names}")

    merged = {field.name: getattr(instance, field.name) for field in fields(instance)}
    for key, value in values.items():
        merged[key] = _coerce_value(getattr(instance, key), value)
    return type(instance)(**merged)


def _coerce_value(current: Any, value: Any) -> Any:
    if isinstance(current, bool):
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"true", "1", "yes", "on"}:
                return True
            if normalized in {"false", "0", "no", "off"}:
                return False
        if isinstance(value, int) and value in (0, 1):
            return bool(value)
        raise ValueError(f"Expected boolean value, got {value!r}.")
    if isinstance(current, int) and not isinstance(current, bool):
        if isinstance(value, bool):
            raise ValueError(f"Expected integer value, got {value!r}.")
        return int(value)
    if isinstance(current, float):
        if isinstance(value, bool):
            raise ValueError(f"Expected numeric value, got {value!r}.")
        return float(value)
    return value


def validate_config(config: AppConfig) -> AppConfig:
    if config.log_path is not None and not isinstance(config.log_path, str):
        raise ValueError("log_path must be a string or null.")
    if config.capture_backend not in available_capture_backends():
        names = ", ".join(available_capture_backends())
        raise ValueError(f"capture_backend must be one of: {names}.")
    if config.log_max_bytes < 1024:
        raise ValueError("log_max_bytes must be at least 1024.")
    if config.log_backup_count < 0:
        raise ValueError("log_backup_count must be at least 0.")
    if config.monitor_refresh_seconds <= 0:
        raise ValueError("monitor_refresh_seconds must be greater than 0.")
    if config.detector_rearm_seconds < 0:
        raise ValueError("detector_rearm_seconds must be at least 0.")
    if config.capture_recovery_error_threshold < 1:
        raise ValueError("capture_recovery_error_threshold must be at least 1.")
    if config.capture_error_backoff_seconds < 0:
        raise ValueError("capture_error_backoff_seconds must be at least 0.")
    if config.decision_queue_size < 8:
        raise ValueError("decision_queue_size must be at least 8.")
    _validate_detector_config(config.detector)
    return config


def _validate_detector_config(config: DetectorConfig) -> None:
    positive_numbers = (
        "sample_fps",
        "flash_window_seconds",
        "safe_release_seconds",
        "blackout_hold_seconds",
        "max_blackout_seconds",
        "manual_unlock_hold_seconds",
        "manual_unlock_snooze_seconds",
    )
    for name in positive_numbers:
        if getattr(config, name) <= 0:
            raise ValueError(f"detector.{name} must be greater than 0.")

    positive_ints = (
        "grid_width",
        "grid_height",
        "block_flash_count",
        "caution_flash_count",
        "severe_block_flash_count",
        "localized_block_flash_count",
        "localized_red_block_flash_count",
        "pattern_min_pairs",
        "pattern_confirm_frames",
        "ui_tick_ms",
    )
    for name in positive_ints:
        if getattr(config, name) < 1:
            raise ValueError(f"detector.{name} must be at least 1.")

    if config.grid_width < 8 or config.grid_height < 8:
        raise ValueError("detector grid dimensions must be at least 8x8.")

    ratios = (
        "general_luminance_delta",
        "darker_luminance_ceiling",
        "red_ratio_threshold",
        "red_ratio_delta",
        "flash_area_ratio",
        "red_flash_area_ratio",
        "severe_flash_area_ratio",
        "flash_polarity_coherence_ratio",
        "localized_flash_area_ratio",
        "localized_red_flash_area_ratio",
        "localized_region_fill_ratio",
        "localized_polarity_coherence_ratio",
        "localized_bbox_overlap_ratio",
        "localized_bbox_min_area_similarity",
        "localized_max_span_ratio",
        "rapid_cut_area_ratio",
        "rapid_cut_delta",
        "rapid_cut_polarity_coherence_ratio",
        "pattern_stationary_area_ratio",
        "pattern_motion_area_ratio",
        "pattern_contrast_delta",
    )
    for name in ratios:
        value = getattr(config, name)
        if not 0.0 <= value <= 1.0:
            raise ValueError(f"detector.{name} must be between 0 and 1.")


def example_config() -> dict[str, Any]:
    detector = DetectorConfig()
    return {
        "log_path": default_log_path(),
        "monitor_only": False,
        "capture_backend": "gdi",
        "log_max_bytes": 1_000_000,
        "log_backup_count": 5,
        "monitor_refresh_seconds": 2.0,
        "detector_rearm_seconds": 0.15,
        "capture_recovery_error_threshold": 3,
        "capture_error_backoff_seconds": 0.25,
        "decision_queue_size": 256,
        "detector": {field.name: getattr(detector, field.name) for field in fields(detector)},
    }
