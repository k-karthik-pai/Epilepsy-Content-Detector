from __future__ import annotations

import unittest

from epilepsy_guard.detector import PhotosensitiveRiskDetector
from epilepsy_guard.models import DetectorConfig, Monitor, RiskLevel, ScreenFrame


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


class DetectorTests(unittest.TestCase):
    def config(self) -> DetectorConfig:
        return DetectorConfig(grid_width=40, grid_height=24, sample_fps=12.0)

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


if __name__ == "__main__":
    unittest.main()

