from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class RiskLevel(str, Enum):
    SAFE = "safe"
    CAUTION = "caution"
    BLOCK = "block"


@dataclass(frozen=True)
class Monitor:
    id: str
    left: int
    top: int
    width: int
    height: int
    primary: bool = False


@dataclass(frozen=True)
class ScreenFrame:
    monitor: Monitor
    timestamp: float
    width: int
    height: int
    bgra: bytes


@dataclass
class DetectorConfig:
    sample_fps: float = 15.0
    grid_width: int = 80
    grid_height: int = 45
    flash_window_seconds: float = 1.0
    safe_release_seconds: float = 2.0
    blackout_hold_seconds: float = 2.5
    general_luminance_delta: float = 0.10
    darker_luminance_ceiling: float = 0.80
    red_ratio_threshold: float = 0.80
    red_ratio_delta: float = 0.20
    block_flash_count: int = 3
    caution_flash_count: int = 2
    flash_area_ratio: float = 0.25
    red_flash_area_ratio: float = 0.20
    rapid_cut_area_ratio: float = 0.45
    rapid_cut_delta: float = 0.20
    pattern_stationary_area_ratio: float = 0.40
    pattern_motion_area_ratio: float = 0.25
    pattern_min_pairs: int = 5
    pattern_contrast_delta: float = 0.25
    fail_closed: bool = True
    capture_timeout_seconds: float = 1.5
    auto_release_requires_capture_exclusion: bool = True
    manual_unlock_hold_seconds: float = 2.0
    manual_unlock_snooze_seconds: float = 10.0


@dataclass
class AppConfig:
    detector: DetectorConfig = field(default_factory=DetectorConfig)
    log_path: str | None = None
    monitor_only: bool = False


@dataclass(frozen=True)
class RiskEvidence:
    reason: str
    monitor_id: str
    value: float | int | str
    threshold: float | int | str
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RiskDecision:
    level: RiskLevel
    reasons: tuple[str, ...] = ()
    evidence: tuple[RiskEvidence, ...] = ()

    @classmethod
    def safe(cls) -> "RiskDecision":
        return cls(RiskLevel.SAFE)

