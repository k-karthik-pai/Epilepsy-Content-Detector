from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from statistics import fmean

from .models import DetectorConfig, RiskDecision, RiskEvidence, RiskLevel, ScreenFrame


_SRGB_TO_LINEAR = tuple(
    value / 255.0 / 12.92
    if value / 255.0 <= 0.04045
    else ((value / 255.0 + 0.055) / 1.055) ** 2.4
    for value in range(256)
)


@dataclass
class _SampledFrame:
    timestamp: float
    width: int
    height: int
    luma: list[float]
    red_ratio: list[float]
    red_saturated: list[bool]


class PhotosensitiveRiskDetector:
    """Guideline-inspired detector for flashes, red flashes, rapid cuts, and patterns.

    The detector intentionally favors reproducible conservative rules over ML. It
    downsamples frames to a stable analysis grid, tracks opposing transitions in a
    rolling one-second window, and emits BLOCK decisions when medical/broadcast
    guidance thresholds are crossed.
    """

    def __init__(self, config: DetectorConfig | None = None):
        self.config = config or DetectorConfig()
        self._previous_by_monitor: dict[str, _SampledFrame] = {}
        self._cell_signs_by_monitor: dict[str, list[int]] = {}
        self._red_signs_by_monitor: dict[str, list[int]] = {}
        self._global_sign_by_monitor: dict[str, int] = {}
        self._flash_events_by_monitor: dict[str, deque[float]] = {}
        self._red_events_by_monitor: dict[str, deque[float]] = {}
        self._rapid_events_by_monitor: dict[str, deque[float]] = {}
        self._pattern_streak_by_monitor: dict[str, int] = {}

    def analyze(self, frame: ScreenFrame) -> RiskDecision:
        sampled = self._sample(frame)
        monitor_id = frame.monitor.id
        previous = self._previous_by_monitor.get(monitor_id)
        self._previous_by_monitor[monitor_id] = sampled

        pattern_decision = self._detect_pattern(frame, sampled, previous)
        if pattern_decision.level is RiskLevel.BLOCK:
            return pattern_decision

        if previous is None:
            return pattern_decision

        evidence: list[RiskEvidence] = []
        reasons: list[str] = []

        general_area = self._detect_general_flash_area(monitor_id, previous, sampled)
        if general_area >= self.config.flash_area_ratio:
            events = self._events_for(self._flash_events_by_monitor, monitor_id)
            events.append(sampled.timestamp)
            count = self._count_recent(events, sampled.timestamp)
            evidence.append(
                RiskEvidence(
                    "GeneralFlash",
                    monitor_id,
                    count,
                    self.config.block_flash_count,
                    {"affected_area_ratio": round(general_area, 4)},
                )
            )
            if count > self.config.block_flash_count:
                reasons.append("GeneralFlash")

        red_area = self._detect_red_flash_area(monitor_id, previous, sampled)
        if red_area >= self.config.red_flash_area_ratio:
            events = self._events_for(self._red_events_by_monitor, monitor_id)
            events.append(sampled.timestamp)
            count = self._count_recent(events, sampled.timestamp)
            evidence.append(
                RiskEvidence(
                    "RedFlash",
                    monitor_id,
                    count,
                    self.config.block_flash_count,
                    {"affected_area_ratio": round(red_area, 4)},
                )
            )
            if count > self.config.block_flash_count:
                reasons.append("RedFlash")

        rapid_cut = self._detect_rapid_cut(monitor_id, previous, sampled)
        if rapid_cut:
            events = self._events_for(self._rapid_events_by_monitor, monitor_id)
            events.append(sampled.timestamp)
            count = self._count_recent(events, sampled.timestamp)
            evidence.append(RiskEvidence("RapidCut", monitor_id, count, self.config.block_flash_count))
            if count > self.config.block_flash_count:
                reasons.append("RapidCut")

        if reasons:
            return RiskDecision(RiskLevel.BLOCK, tuple(sorted(set(reasons))), tuple(evidence))

        recent_counts = [
            self._count_recent(self._events_for(self._flash_events_by_monitor, monitor_id), sampled.timestamp),
            self._count_recent(self._events_for(self._red_events_by_monitor, monitor_id), sampled.timestamp),
            self._count_recent(self._events_for(self._rapid_events_by_monitor, monitor_id), sampled.timestamp),
        ]
        if pattern_decision.level is RiskLevel.CAUTION or max(recent_counts) >= self.config.caution_flash_count:
            caution_reasons = list(pattern_decision.reasons)
            if max(recent_counts) >= self.config.caution_flash_count:
                caution_reasons.append("FlashSequenceBuilding")
            return RiskDecision(RiskLevel.CAUTION, tuple(sorted(set(caution_reasons))), tuple(evidence))

        return RiskDecision.safe()

    def reset_monitor(self, monitor_id: str) -> None:
        self._previous_by_monitor.pop(monitor_id, None)
        self._cell_signs_by_monitor.pop(monitor_id, None)
        self._red_signs_by_monitor.pop(monitor_id, None)
        self._global_sign_by_monitor.pop(monitor_id, None)
        self._flash_events_by_monitor.pop(monitor_id, None)
        self._red_events_by_monitor.pop(monitor_id, None)
        self._rapid_events_by_monitor.pop(monitor_id, None)
        self._pattern_streak_by_monitor.pop(monitor_id, None)

    def reset_all(self) -> None:
        self._previous_by_monitor.clear()
        self._cell_signs_by_monitor.clear()
        self._red_signs_by_monitor.clear()
        self._global_sign_by_monitor.clear()
        self._flash_events_by_monitor.clear()
        self._red_events_by_monitor.clear()
        self._rapid_events_by_monitor.clear()
        self._pattern_streak_by_monitor.clear()

    def _sample(self, frame: ScreenFrame) -> _SampledFrame:
        gw = max(8, self.config.grid_width)
        gh = max(8, self.config.grid_height)
        luma: list[float] = []
        red_ratio: list[float] = []
        red_saturated: list[bool] = []
        data = frame.bgra
        stride = frame.width * 4

        for gy in range(gh):
            y = min(frame.height - 1, int((gy + 0.5) * frame.height / gh))
            row = y * stride
            for gx in range(gw):
                x = min(frame.width - 1, int((gx + 0.5) * frame.width / gw))
                offset = row + x * 4
                b = data[offset]
                g = data[offset + 1]
                r = data[offset + 2]
                linear_r = _SRGB_TO_LINEAR[r]
                linear_g = _SRGB_TO_LINEAR[g]
                linear_b = _SRGB_TO_LINEAR[b]
                y_rel = 0.2126 * linear_r + 0.7152 * linear_g + 0.0722 * linear_b
                total = r + g + b
                ratio = r / total if total else 0.0
                luma.append(y_rel)
                red_ratio.append(ratio)
                red_saturated.append(ratio >= self.config.red_ratio_threshold and r >= 80)

        return _SampledFrame(frame.timestamp, gw, gh, luma, red_ratio, red_saturated)

    def _detect_general_flash_area(self, monitor_id: str, previous: _SampledFrame, current: _SampledFrame) -> float:
        signs = self._cell_signs_by_monitor.setdefault(monitor_id, [0] * len(current.luma))
        pair_count = 0
        for index, (before, after) in enumerate(zip(previous.luma, current.luma)):
            delta = after - before
            if abs(delta) < self.config.general_luminance_delta:
                continue
            if min(before, after) >= self.config.darker_luminance_ceiling:
                continue
            sign = 1 if delta > 0 else -1
            if signs[index] and signs[index] != sign:
                pair_count += 1
            signs[index] = sign
        return pair_count / len(current.luma)

    def _detect_red_flash_area(self, monitor_id: str, previous: _SampledFrame, current: _SampledFrame) -> float:
        signs = self._red_signs_by_monitor.setdefault(monitor_id, [0] * len(current.luma))
        pair_count = 0
        for index, (prev_ratio, curr_ratio) in enumerate(zip(previous.red_ratio, current.red_ratio)):
            red_transition = previous.red_saturated[index] or current.red_saturated[index]
            if not red_transition:
                continue
            delta = curr_ratio - prev_ratio
            if abs(delta) < self.config.red_ratio_delta:
                continue
            sign = 1 if delta > 0 else -1
            if signs[index] and signs[index] != sign:
                pair_count += 1
            signs[index] = sign
        return pair_count / len(current.luma)

    def _detect_rapid_cut(self, monitor_id: str, previous: _SampledFrame, current: _SampledFrame) -> bool:
        changed = 0
        deltas: list[float] = []
        for before, after in zip(previous.luma, current.luma):
            delta = after - before
            if abs(delta) >= self.config.rapid_cut_delta:
                changed += 1
                deltas.append(delta)
        area = changed / len(current.luma)
        if area < self.config.rapid_cut_area_ratio or not deltas:
            return False

        mean_delta = fmean(deltas)
        sign = 1 if mean_delta > 0 else -1
        previous_sign = self._global_sign_by_monitor.get(monitor_id, 0)
        self._global_sign_by_monitor[monitor_id] = sign
        return bool(previous_sign and previous_sign != sign)

    def _detect_pattern(
        self,
        frame: ScreenFrame,
        current: _SampledFrame,
        previous: _SampledFrame | None,
    ) -> RiskDecision:
        horizontal_area = self._stripe_area(current, axis="horizontal")
        vertical_area = self._stripe_area(current, axis="vertical")
        area = max(horizontal_area, vertical_area)
        monitor_id = frame.monitor.id
        if area < min(self.config.pattern_motion_area_ratio, self.config.pattern_stationary_area_ratio):
            self._pattern_streak_by_monitor.pop(monitor_id, None)
            return RiskDecision.safe()

        moving = False
        if previous is not None:
            changed_cells = sum(
                1
                for before, after in zip(previous.luma, current.luma)
                if abs(after - before) >= self.config.pattern_contrast_delta
            )
            moving = changed_cells / len(current.luma) >= self.config.pattern_motion_area_ratio

        threshold = (
            self.config.pattern_motion_area_ratio
            if moving
            else self.config.pattern_stationary_area_ratio
        )
        if area < threshold:
            self._pattern_streak_by_monitor.pop(monitor_id, None)
            return RiskDecision.safe()

        streak = self._pattern_streak_by_monitor.get(monitor_id, 0) + 1
        self._pattern_streak_by_monitor[monitor_id] = streak
        evidence = (
            RiskEvidence(
                "RegularPattern",
                monitor_id,
                round(area, 4),
                threshold,
                {
                    "moving_or_reversing": moving,
                    "confirm_frames": streak,
                    "required_confirm_frames": self.config.pattern_confirm_frames,
                },
            ),
        )
        if not moving or streak >= self.config.pattern_confirm_frames:
            return RiskDecision(RiskLevel.BLOCK, ("RegularPattern",), evidence)
        return RiskDecision(RiskLevel.CAUTION, ("RegularPattern",), evidence)

    def _stripe_area(self, frame: _SampledFrame, axis: str) -> float:
        stripe_lines = 0
        line_count = frame.height if axis == "horizontal" else frame.width
        for line in range(line_count):
            values = self._line_values(frame, axis, line)
            if self._has_stripes(values):
                stripe_lines += 1
        return stripe_lines / line_count

    def _line_values(self, frame: _SampledFrame, axis: str, line: int) -> list[float]:
        if axis == "horizontal":
            start = line * frame.width
            return frame.luma[start : start + frame.width]
        return [frame.luma[y * frame.width + line] for y in range(frame.height)]

    def _has_stripes(self, values: list[float]) -> bool:
        if len(values) < self.config.pattern_min_pairs * 2:
            return False
        low = min(values)
        high = max(values)
        if high - low < self.config.pattern_contrast_delta:
            return False
        threshold = (low + high) / 2.0
        bands: list[int] = []
        last = 1 if values[0] >= threshold else -1
        bands.append(last)
        for value in values[1:]:
            band = 1 if value >= threshold else -1
            if band != last:
                bands.append(band)
                last = band
        pairs = max(0, (len(bands) - 1) // 2)
        return pairs >= self.config.pattern_min_pairs

    def _events_for(self, event_map: dict[str, deque[float]], monitor_id: str) -> deque[float]:
        return event_map.setdefault(monitor_id, deque())

    def _count_recent(self, events: deque[float], now: float) -> int:
        cutoff = now - self.config.flash_window_seconds
        while events and events[0] < cutoff:
            events.popleft()
        return len(events)
