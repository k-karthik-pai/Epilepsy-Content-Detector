from __future__ import annotations

import json
import os
from dataclasses import fields, is_dataclass
from pathlib import Path
from typing import Any, TypeVar

from .models import AppConfig, DetectorConfig

T = TypeVar("T")


def default_log_path() -> str:
    root = os.environ.get("LOCALAPPDATA") or str(Path.home())
    return str(Path(root) / "EpilepsyGuard" / "events.jsonl")


def load_config(path: str | None) -> AppConfig:
    config = AppConfig()
    config.log_path = default_log_path()
    if not path:
        return config

    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Config root must be a JSON object.")

    if "detector" in data:
        config.detector = _merge_dataclass(config.detector, data["detector"])
    if "log_path" in data:
        config.log_path = data["log_path"]
    if "monitor_only" in data:
        config.monitor_only = bool(data["monitor_only"])
    return config


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
        return bool(value)
    if isinstance(current, int) and not isinstance(current, bool):
        return int(value)
    if isinstance(current, float):
        return float(value)
    return value


def example_config() -> dict[str, Any]:
    detector = DetectorConfig()
    return {
        "log_path": default_log_path(),
        "monitor_only": False,
        "detector": {field.name: getattr(detector, field.name) for field in fields(detector)},
    }
