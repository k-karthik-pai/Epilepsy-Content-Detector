from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from epilepsy_guard.config import load_config


class ConfigTests(unittest.TestCase):
    def load_from_dict(self, data: dict[str, object]):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "config.json"
            path.write_text(json.dumps(data), encoding="utf-8")
            return load_config(str(path))

    def test_string_false_is_false(self) -> None:
        config = self.load_from_dict({"monitor_only": "false"})
        self.assertFalse(config.monitor_only)

    def test_string_true_is_true(self) -> None:
        config = self.load_from_dict({"monitor_only": "true"})
        self.assertTrue(config.monitor_only)

    def test_invalid_boolean_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self.load_from_dict({"monitor_only": "sometimes"})

    def test_invalid_detector_ratio_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self.load_from_dict({"detector": {"flash_area_ratio": 1.5}})

    def test_invalid_detector_grid_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self.load_from_dict({"detector": {"grid_width": 4}})

    def test_invalid_capture_backend_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self.load_from_dict({"capture_backend": "desktop-duplication"})

    def test_log_rotation_fields_are_loaded(self) -> None:
        config = self.load_from_dict({"log_max_bytes": 2048, "log_backup_count": 2})
        self.assertEqual(config.log_max_bytes, 2048)
        self.assertEqual(config.log_backup_count, 2)

    def test_tiny_log_size_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self.load_from_dict({"log_max_bytes": 10})

    def test_negative_log_backup_count_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self.load_from_dict({"log_backup_count": -1})

    def test_monitor_refresh_interval_is_loaded(self) -> None:
        config = self.load_from_dict({"monitor_refresh_seconds": 5.0})
        self.assertEqual(config.monitor_refresh_seconds, 5.0)

    def test_invalid_monitor_refresh_interval_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self.load_from_dict({"monitor_refresh_seconds": 0})

    def test_detector_rearm_interval_is_loaded(self) -> None:
        config = self.load_from_dict({"detector_rearm_seconds": 0.25})
        self.assertEqual(config.detector_rearm_seconds, 0.25)

    def test_negative_detector_rearm_interval_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self.load_from_dict({"detector_rearm_seconds": -0.1})

    def test_capture_recovery_settings_are_loaded(self) -> None:
        config = self.load_from_dict(
            {
                "capture_recovery_error_threshold": 5,
                "capture_error_backoff_seconds": 0.5,
            }
        )
        self.assertEqual(config.capture_recovery_error_threshold, 5)
        self.assertEqual(config.capture_error_backoff_seconds, 0.5)

    def test_invalid_capture_recovery_threshold_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self.load_from_dict({"capture_recovery_error_threshold": 0})

    def test_negative_capture_error_backoff_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self.load_from_dict({"capture_error_backoff_seconds": -0.1})

    def test_decision_queue_size_is_loaded(self) -> None:
        config = self.load_from_dict({"decision_queue_size": 512})
        self.assertEqual(config.decision_queue_size, 512)

    def test_tiny_decision_queue_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self.load_from_dict({"decision_queue_size": 2})


if __name__ == "__main__":
    unittest.main()
