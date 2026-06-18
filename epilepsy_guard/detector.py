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


@dataclass(frozen=True)
class _FlashRegion:
    area_ratio: float
    largest_area_ratio: float
    largest_bbox: tuple[int, int, int, int] | None
    largest_fill_ratio: float
    largest_width_ratio: float
    largest_height_ratio: float
    overall_polarity_ratio: float
    largest_polarity_ratio: float


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
        self._localized_flash_events_by_monitor: dict[str, deque[float]] = {}
        self._localized_red_events_by_monitor: dict[str, deque[float]] = {}
        self._localized_bbox_by_monitor: dict[str, tuple[int, int, int, int]] = {}
        self._localized_red_bbox_by_monitor: dict[str, tuple[int, int, int, int]] = {}
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

        general_region = self._detect_general_flash_region(monitor_id, previous, sampled)
        if (
            general_region.area_ratio >= self.config.flash_area_ratio
            and general_region.overall_polarity_ratio >= self.config.flash_polarity_coherence_ratio
        ):
            events = self._events_for(self._flash_events_by_monitor, monitor_id)
            events.append(sampled.timestamp)
            count = self._count_recent(events, sampled.timestamp)
            evidence.append(
                RiskEvidence(
                    "GeneralFlash",
                    monitor_id,
                    count,
                    self.config.block_flash_count,
                    {
                        "affected_area_ratio": round(general_region.area_ratio, 4),
                        "polarity_coherence_ratio": round(general_region.overall_polarity_ratio, 4),
                    },
                )
            )
            if (
                count >= self.config.block_flash_count
                or (
                    general_region.area_ratio >= self.config.severe_flash_area_ratio
                    and count >= self.config.severe_block_flash_count
                )
            ):
                reasons.append("GeneralFlash")
        elif self._is_localized_region(general_region, self.config.localized_flash_area_ratio):
            count = self._append_localized_event(
                self._localized_flash_events_by_monitor,
                self._localized_bbox_by_monitor,
                monitor_id,
                sampled.timestamp,
                general_region.largest_bbox,
            )
            evidence.append(
                RiskEvidence(
                    "LocalizedFlash",
                    monitor_id,
                    count,
                    self.config.localized_block_flash_count,
                    {
                        "affected_area_ratio": round(general_region.area_ratio, 4),
                        "localized_area_ratio": round(general_region.largest_area_ratio, 4),
                        "polarity_coherence_ratio": round(general_region.largest_polarity_ratio, 4),
                        "bbox": general_region.largest_bbox,
                    },
                )
            )
            if count >= self.config.localized_block_flash_count:
                reasons.append("LocalizedFlash")

        red_region = self._detect_red_flash_region(monitor_id, previous, sampled)
        if (
            red_region.area_ratio >= self.config.red_flash_area_ratio
            and red_region.overall_polarity_ratio >= self.config.flash_polarity_coherence_ratio
        ):
            events = self._events_for(self._red_events_by_monitor, monitor_id)
            events.append(sampled.timestamp)
            count = self._count_recent(events, sampled.timestamp)
            evidence.append(
                RiskEvidence(
                    "RedFlash",
                    monitor_id,
                    count,
                    self.config.block_flash_count,
                    {
                        "affected_area_ratio": round(red_region.area_ratio, 4),
                        "polarity_coherence_ratio": round(red_region.overall_polarity_ratio, 4),
                    },
                )
            )
            if count >= self.config.block_flash_count:
                reasons.append("RedFlash")
        elif self._is_localized_region(red_region, self.config.localized_red_flash_area_ratio):
            count = self._append_localized_event(
                self._localized_red_events_by_monitor,
                self._localized_red_bbox_by_monitor,
                monitor_id,
                sampled.timestamp,
                red_region.largest_bbox,
            )
            evidence.append(
                RiskEvidence(
                    "LocalizedRedFlash",
                    monitor_id,
                    count,
                    self.config.localized_red_block_flash_count,
                    {
                        "affected_area_ratio": round(red_region.area_ratio, 4),
                        "localized_area_ratio": round(red_region.largest_area_ratio, 4),
                        "polarity_coherence_ratio": round(red_region.largest_polarity_ratio, 4),
                        "bbox": red_region.largest_bbox,
                    },
                )
            )
            if count >= self.config.localized_red_block_flash_count:
                reasons.append("LocalizedRedFlash")

        rapid_cut = self._detect_rapid_cut(monitor_id, previous, sampled)
        if rapid_cut:
            events = self._events_for(self._rapid_events_by_monitor, monitor_id)
            events.append(sampled.timestamp)
            count = self._count_recent(events, sampled.timestamp)
            evidence.append(RiskEvidence("RapidCut", monitor_id, count, self.config.block_flash_count))
            if count >= self.config.block_flash_count:
                reasons.append("RapidCut")

        if reasons:
            return RiskDecision(RiskLevel.BLOCK, tuple(sorted(set(reasons))), tuple(evidence))

        recent_counts = [
            self._count_recent(self._events_for(self._flash_events_by_monitor, monitor_id), sampled.timestamp),
            self._count_recent(self._events_for(self._red_events_by_monitor, monitor_id), sampled.timestamp),
            self._count_recent(self._events_for(self._rapid_events_by_monitor, monitor_id), sampled.timestamp),
            self._count_recent(self._events_for(self._localized_flash_events_by_monitor, monitor_id), sampled.timestamp),
            self._count_recent(self._events_for(self._localized_red_events_by_monitor, monitor_id), sampled.timestamp),
        ]
        sequence_building = bool(evidence) and max(recent_counts) >= self.config.caution_flash_count
        if pattern_decision.level is RiskLevel.CAUTION or sequence_building:
            caution_reasons = list(pattern_decision.reasons)
            caution_evidence = [*pattern_decision.evidence, *evidence]
            if sequence_building:
                caution_reasons.append("FlashSequenceBuilding")
            return RiskDecision(RiskLevel.CAUTION, tuple(sorted(set(caution_reasons))), tuple(caution_evidence))

        return RiskDecision.safe()

    def reset_monitor(self, monitor_id: str) -> None:
        self._previous_by_monitor.pop(monitor_id, None)
        self._cell_signs_by_monitor.pop(monitor_id, None)
        self._red_signs_by_monitor.pop(monitor_id, None)
        self._global_sign_by_monitor.pop(monitor_id, None)
        self._flash_events_by_monitor.pop(monitor_id, None)
        self._red_events_by_monitor.pop(monitor_id, None)
        self._rapid_events_by_monitor.pop(monitor_id, None)
        self._localized_flash_events_by_monitor.pop(monitor_id, None)
        self._localized_red_events_by_monitor.pop(monitor_id, None)
        self._localized_bbox_by_monitor.pop(monitor_id, None)
        self._localized_red_bbox_by_monitor.pop(monitor_id, None)
        self._pattern_streak_by_monitor.pop(monitor_id, None)

    def reset_all(self) -> None:
        self._previous_by_monitor.clear()
        self._cell_signs_by_monitor.clear()
        self._red_signs_by_monitor.clear()
        self._global_sign_by_monitor.clear()
        self._flash_events_by_monitor.clear()
        self._red_events_by_monitor.clear()
        self._rapid_events_by_monitor.clear()
        self._localized_flash_events_by_monitor.clear()
        self._localized_red_events_by_monitor.clear()
        self._localized_bbox_by_monitor.clear()
        self._localized_red_bbox_by_monitor.clear()
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

    def _detect_general_flash_region(
        self,
        monitor_id: str,
        previous: _SampledFrame,
        current: _SampledFrame,
    ) -> _FlashRegion:
        signs = self._cell_signs_by_monitor.setdefault(monitor_id, [0] * len(current.luma))
        pair_count = 0
        transition_signs = [0] * len(current.luma)
        for index, (before, after) in enumerate(zip(previous.luma, current.luma)):
            delta = after - before
            if abs(delta) < self.config.general_luminance_delta:
                continue
            if min(before, after) >= self.config.darker_luminance_ceiling:
                continue
            sign = 1 if delta > 0 else -1
            if signs[index] and signs[index] != sign:
                pair_count += 1
                transition_signs[index] = sign
            signs[index] = sign
        return self._flash_region(pair_count, transition_signs, current.width, current.height)

    def _detect_red_flash_region(
        self,
        monitor_id: str,
        previous: _SampledFrame,
        current: _SampledFrame,
    ) -> _FlashRegion:
        signs = self._red_signs_by_monitor.setdefault(monitor_id, [0] * len(current.luma))
        pair_count = 0
        transition_signs = [0] * len(current.luma)
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
                transition_signs[index] = sign
            signs[index] = sign
        return self._flash_region(pair_count, transition_signs, current.width, current.height)

    def _flash_region(self, pair_count: int, transition_signs: list[int], width: int, height: int) -> _FlashRegion:
        largest_count = 0
        largest_bbox: tuple[int, int, int, int] | None = None
        largest_polarity_ratio = 0.0
        visited = [False] * len(transition_signs)

        for start, transition_sign in enumerate(transition_signs):
            if not transition_sign or visited[start]:
                continue
            stack = [start]
            visited[start] = True
            count = 0
            positive_count = 0
            negative_count = 0
            min_x = max_x = start % width
            min_y = max_y = start // width

            while stack:
                index = stack.pop()
                count += 1
                if transition_signs[index] > 0:
                    positive_count += 1
                else:
                    negative_count += 1
                x = index % width
                y = index // width
                min_x = min(min_x, x)
                max_x = max(max_x, x)
                min_y = min(min_y, y)
                max_y = max(max_y, y)
                for neighbor in self._neighbors(index, x, y, width, height):
                    if transition_signs[neighbor] and not visited[neighbor]:
                        visited[neighbor] = True
                        stack.append(neighbor)

            if count > largest_count:
                largest_count = count
                largest_bbox = (min_x, min_y, max_x, max_y)
                largest_polarity_ratio = max(positive_count, negative_count) / count

        total = max(1, len(transition_signs))
        positive_total = sum(1 for sign in transition_signs if sign > 0)
        negative_total = sum(1 for sign in transition_signs if sign < 0)
        overall_polarity_ratio = max(positive_total, negative_total) / pair_count if pair_count else 0.0
        if not largest_bbox:
            return _FlashRegion(pair_count / total, 0.0, None, 0.0, 0.0, 0.0, 0.0, 0.0)
        bbox_width = largest_bbox[2] - largest_bbox[0] + 1
        bbox_height = largest_bbox[3] - largest_bbox[1] + 1
        bbox_area = bbox_width * bbox_height
        return _FlashRegion(
            pair_count / total,
            largest_count / total,
            largest_bbox,
            largest_count / max(1, bbox_area),
            bbox_width / max(1, width),
            bbox_height / max(1, height),
            overall_polarity_ratio,
            largest_polarity_ratio,
        )

    def _neighbors(self, index: int, x: int, y: int, width: int, height: int) -> tuple[int, ...]:
        neighbors: list[int] = []
        if x > 0:
            neighbors.append(index - 1)
        if x + 1 < width:
            neighbors.append(index + 1)
        if y > 0:
            neighbors.append(index - width)
        if y + 1 < height:
            neighbors.append(index + width)
        return tuple(neighbors)

    def _is_localized_region(self, region: _FlashRegion, area_threshold: float) -> bool:
        return (
            region.largest_bbox is not None
            and region.largest_area_ratio >= area_threshold
            and region.largest_fill_ratio >= self.config.localized_region_fill_ratio
            and region.largest_polarity_ratio >= self.config.localized_polarity_coherence_ratio
            and max(region.largest_width_ratio, region.largest_height_ratio) <= self.config.localized_max_span_ratio
        )

    def _append_localized_event(
        self,
        event_map: dict[str, deque[float]],
        bbox_map: dict[str, tuple[int, int, int, int]],
        monitor_id: str,
        timestamp: float,
        bbox: tuple[int, int, int, int] | None,
    ) -> int:
        events = self._events_for(event_map, monitor_id)
        if bbox is None:
            return self._count_recent(events, timestamp)

        previous_bbox = bbox_map.get(monitor_id)
        if previous_bbox is not None:
            stable_overlap = self._bbox_iou(previous_bbox, bbox) >= self.config.localized_bbox_overlap_ratio
            stable_area = self._bbox_area_similarity(previous_bbox, bbox) >= self.config.localized_bbox_min_area_similarity
            if not stable_overlap or not stable_area:
                events.clear()
        bbox_map[monitor_id] = bbox
        events.append(timestamp)
        return self._count_recent(events, timestamp)

    def _bbox_iou(self, left: tuple[int, int, int, int], right: tuple[int, int, int, int]) -> float:
        x1 = max(left[0], right[0])
        y1 = max(left[1], right[1])
        x2 = min(left[2], right[2])
        y2 = min(left[3], right[3])
        if x2 < x1 or y2 < y1:
            return 0.0
        intersection = (x2 - x1 + 1) * (y2 - y1 + 1)
        left_area = (left[2] - left[0] + 1) * (left[3] - left[1] + 1)
        right_area = (right[2] - right[0] + 1) * (right[3] - right[1] + 1)
        return intersection / max(1, left_area + right_area - intersection)

    def _bbox_area_similarity(self, left: tuple[int, int, int, int], right: tuple[int, int, int, int]) -> float:
        left_area = (left[2] - left[0] + 1) * (left[3] - left[1] + 1)
        right_area = (right[2] - right[0] + 1) * (right[3] - right[1] + 1)
        return min(left_area, right_area) / max(1, left_area, right_area)

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

        positive_count = sum(1 for delta in deltas if delta > 0)
        negative_count = len(deltas) - positive_count
        polarity_ratio = max(positive_count, negative_count) / len(deltas)
        if polarity_ratio < self.config.rapid_cut_polarity_coherence_ratio:
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
