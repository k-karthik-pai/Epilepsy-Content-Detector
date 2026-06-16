from __future__ import annotations

import unittest

from epilepsy_guard.detector import PhotosensitiveRiskDetector
from epilepsy_guard.models import DetectorConfig, Monitor, RiskLevel, ScreenFrame
from epilepsy_guard.synthetic import scenario_frames, windowed_flash_frame


MONITOR = Monitor("test", 0, 0, 160, 90, True)


def solid_frame(timestamp: float, rgb: tuple[int, int, int], width: int = 160, height: int = 90) -> ScreenFrame:
    r, g, b = rgb
    pixel = bytes((b, g, r, 255))
    return ScreenFrame(MONITOR, timestamp, width, height, pixel * width * height)


def small_flash_frame(timestamp: float, flashing: bool, width: int = 160, height: int = 90) -> ScreenFrame:
    bg = bytes((0, 0, 0, 255))
    fg = bytes((255, 255, 255, 255)) if flashing else bg
    data = bytearray(bg * width * height)
    for y in range(0, height // 8):
        for x in range(0, width // 8):
            offset = (y * width + x) * 4
            data[offset : offset + 4] = fg
    return ScreenFrame(MONITOR, timestamp, width, height, bytes(data))


def stripes_frame(timestamp: float, width: int = 160, height: int = 90) -> ScreenFrame:
    data = bytearray()
    for _y in range(height):
        for x in range(width):
            value = 255 if (x // 8) % 2 == 0 else 0
            data.extend((value, value, value, 255))
    return ScreenFrame(MONITOR, timestamp, width, height, bytes(data))


def partial_stripes_frame(
    timestamp: float,
    inverted: bool = False,
    width: int = 160,
    height: int = 90,
) -> ScreenFrame:
    data = bytearray()
    patterned_height = height // 4
    for y in range(height):
        for x in range(width):
            if y < patterned_height:
                stripe_on = (x // 8) % 2 == 0
                if inverted:
                    stripe_on = not stripe_on
                value = 255 if stripe_on else 0
            else:
                value = 245
            data.extend((value, value, value, 255))
    return ScreenFrame(MONITOR, timestamp, width, height, bytes(data))


def mostly_stripes_frame(
    timestamp: float,
    inverted: bool = False,
    width: int = 160,
    height: int = 90,
) -> ScreenFrame:
    data = bytearray()
    patterned_height = int(height * 0.70)
    for y in range(height):
        for x in range(width):
            if y < patterned_height:
                stripe_on = (x // 8) % 2 == 0
                if inverted:
                    stripe_on = not stripe_on
                value = 255 if stripe_on else 0
            else:
                value = 245
            data.extend((value, value, value, 255))
    return ScreenFrame(MONITOR, timestamp, width, height, bytes(data))


def browser_like_frame(timestamp: float, width: int = 160, height: int = 90) -> ScreenFrame:
    data = bytearray(bytes((255, 255, 255, 255)) * width * height)
    toolbar = bytes((225, 225, 225, 255))
    text = bytes((45, 45, 45, 255))
    link = bytes((190, 95, 30, 255))

    for y in range(0, 12):
        for x in range(width):
            offset = (y * width + x) * 4
            data[offset : offset + 4] = toolbar

    for y in range(20, 76, 10):
        for x in range(12, 118):
            if (x // 7) % 3 == 0:
                offset = (y * width + x) * 4
                data[offset : offset + 4] = text

    for y in range(30, 76, 20):
        for x in range(14, 82):
            if (x // 9) % 2 == 0:
                offset = (y * width + x) * 4
                data[offset : offset + 4] = link

    return ScreenFrame(MONITOR, timestamp, width, height, bytes(data))


def partial_area_frame(
    timestamp: float,
    lit: bool,
    area_ratio: float,
    width: int = 160,
    height: int = 90,
) -> ScreenFrame:
    dark = bytes((0, 0, 0, 255))
    light = bytes((255, 255, 255, 255))
    data = bytearray(dark * width * height)
    active_width = int(width * area_ratio)
    active_pixel = light if lit else dark
    for y in range(height):
        for x in range(active_width):
            offset = (y * width + x) * 4
            data[offset : offset + 4] = active_pixel
    return ScreenFrame(MONITOR, timestamp, width, height, bytes(data))


class DetectorTests(unittest.TestCase):
    def config(self) -> DetectorConfig:
        return DetectorConfig(grid_width=40, grid_height=24, sample_fps=40.0)

    def test_static_content_is_safe(self) -> None:
        detector = PhotosensitiveRiskDetector(self.config())
        decisions = [detector.analyze(solid_frame(i / 12, (32, 80, 128))) for i in range(6)]
        self.assertTrue(all(decision.level is RiskLevel.SAFE for decision in decisions))

    def test_large_alternating_flash_blocks(self) -> None:
        detector = PhotosensitiveRiskDetector(self.config())
        colors = [(0, 0, 0), (255, 255, 255)] * 6
        decisions = [
            detector.analyze(solid_frame(index / 12, color))
            for index, color in enumerate(colors)
        ]
        self.assertEqual(decisions[-1].level, RiskLevel.BLOCK)
        self.assertIn("GeneralFlash", decisions[-1].reasons)

    def test_large_alternating_flash_blocks_quickly(self) -> None:
        detector = PhotosensitiveRiskDetector(self.config())
        colors = [(0, 0, 0), (255, 255, 255)] * 6
        decisions = [
            detector.analyze(solid_frame(index / 40, color))
            for index, color in enumerate(colors)
        ]
        first_block = next(
            index for index, decision in enumerate(decisions) if decision.level is RiskLevel.BLOCK
        )
        self.assertLessEqual(first_block / 40, 0.10)

    def test_saturated_red_flash_blocks(self) -> None:
        detector = PhotosensitiveRiskDetector(self.config())
        colors = [(0, 0, 0), (255, 0, 0)] * 6
        decisions = [
            detector.analyze(solid_frame(index / 12, color))
            for index, color in enumerate(colors)
        ]
        self.assertEqual(decisions[-1].level, RiskLevel.BLOCK)
        self.assertIn("RedFlash", decisions[-1].reasons)

    def test_small_area_flash_does_not_block(self) -> None:
        detector = PhotosensitiveRiskDetector(self.config())
        decisions = [
            detector.analyze(small_flash_frame(index / 12, bool(index % 2)))
            for index in range(12)
        ]
        self.assertNotEqual(decisions[-1].level, RiskLevel.BLOCK)

    def test_high_contrast_stripes_block(self) -> None:
        detector = PhotosensitiveRiskDetector(self.config())
        decision = detector.analyze(stripes_frame(0.0))
        self.assertEqual(decision.level, RiskLevel.BLOCK)
        self.assertIn("RegularPattern", decision.reasons)

    def test_partial_moving_pattern_does_not_block_like_browser_chrome(self) -> None:
        detector = PhotosensitiveRiskDetector(self.config())
        decisions = [
            detector.analyze(solid_frame(0.0, (34, 34, 34))),
            detector.analyze(partial_stripes_frame(1 / 12)),
            detector.analyze(partial_stripes_frame(2 / 12, inverted=True)),
        ]
        self.assertTrue(all(decision.level is not RiskLevel.BLOCK for decision in decisions))

    def test_moving_pattern_caution_includes_pattern_evidence(self) -> None:
        detector = PhotosensitiveRiskDetector(self.config())
        detector.analyze(mostly_stripes_frame(0.0))
        decision = detector.analyze(mostly_stripes_frame(1 / 40, inverted=True))
        self.assertEqual(decision.level, RiskLevel.CAUTION)
        self.assertIn("RegularPattern", decision.reasons)
        self.assertTrue(any(item.reason == "RegularPattern" for item in decision.evidence))

    def test_normal_browser_opening_sequence_does_not_block(self) -> None:
        detector = PhotosensitiveRiskDetector(self.config())
        frames = [
            solid_frame(0.0, (32, 80, 128)),
            solid_frame(1 / 12, (245, 245, 245)),
            browser_like_frame(2 / 12),
            browser_like_frame(3 / 12),
            solid_frame(4 / 12, (250, 250, 250)),
        ]
        decisions = [detector.analyze(frame) for frame in frames]
        self.assertTrue(all(decision.level is not RiskLevel.BLOCK for decision in decisions))

    def test_medium_area_screen_transitions_do_not_block(self) -> None:
        detector = PhotosensitiveRiskDetector(self.config())
        frames = [
            partial_area_frame(0 / 40, False, 0.25),
            partial_area_frame(1 / 40, True, 0.35),
            partial_area_frame(2 / 40, False, 0.45),
            partial_area_frame(3 / 40, True, 0.55),
        ]
        decisions = [detector.analyze(frame) for frame in frames]
        self.assertTrue(all(decision.level is not RiskLevel.BLOCK for decision in decisions))

    def test_windowed_flash_blocks_without_fullscreen_area(self) -> None:
        detector = PhotosensitiveRiskDetector(self.config())
        decisions = [
            detector.analyze(windowed_flash_frame(index / 40, bool(index % 2)))
            for index in range(12)
        ]
        self.assertEqual(decisions[-1].level, RiskLevel.BLOCK)
        self.assertIn("LocalizedFlash", decisions[-1].reasons)

    def test_windowed_flash_blocks_quickly(self) -> None:
        detector = PhotosensitiveRiskDetector(self.config())
        decisions = [
            detector.analyze(windowed_flash_frame(index / 40, bool(index % 2)))
            for index in range(12)
        ]
        first_block = next(
            index for index, decision in enumerate(decisions) if decision.level is RiskLevel.BLOCK
        )
        self.assertLessEqual(first_block / 40, 0.125)

    def test_small_off_center_windowed_flash_blocks(self) -> None:
        detector = PhotosensitiveRiskDetector(self.config())
        decisions = [
            detector.analyze(
                windowed_flash_frame(
                    index / 40,
                    bool(index % 2),
                    window_width_ratio=0.35,
                    window_height_ratio=0.35,
                    left_ratio=0.82,
                    top_ratio=0.68,
                )
            )
            for index in range(12)
        ]
        self.assertEqual(decisions[-1].level, RiskLevel.BLOCK)
        self.assertIn("LocalizedFlash", decisions[-1].reasons)

    def test_synthetic_safe_scenarios_do_not_block(self) -> None:
        for scenario in ("safe-browser", "partial-pattern"):
            with self.subTest(scenario=scenario):
                detector = PhotosensitiveRiskDetector(self.config())
                decisions = [detector.analyze(frame) for frame in scenario_frames(scenario, 12.0)]
                self.assertTrue(all(decision.level is not RiskLevel.BLOCK for decision in decisions))

    def test_synthetic_risk_scenarios_block(self) -> None:
        for scenario in ("general-flash", "windowed-flash", "small-windowed-flash", "red-flash", "regular-pattern"):
            with self.subTest(scenario=scenario):
                detector = PhotosensitiveRiskDetector(self.config())
                decisions = [detector.analyze(frame) for frame in scenario_frames(scenario, 12.0)]
                self.assertTrue(any(decision.level is RiskLevel.BLOCK for decision in decisions))


if __name__ == "__main__":
    unittest.main()
