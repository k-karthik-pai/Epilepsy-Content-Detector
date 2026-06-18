from __future__ import annotations

import json
import tempfile
import threading
import unittest
from pathlib import Path

from epilepsy_guard.logging_utils import RiskLogger


class RiskLoggerTests(unittest.TestCase):
    def test_logs_rotate_when_size_limit_is_reached(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "events.jsonl"
            logger = RiskLogger(str(path), max_bytes=220, backup_count=2)

            for index in range(12):
                logger.info("capture_error", index=index, detail="x" * 80)

            self.assertTrue(path.exists())
            self.assertTrue(path.with_name("events.jsonl.1").exists())
            self.assertTrue(path.with_name("events.jsonl.2").exists())
            self.assertFalse(path.with_name("events.jsonl.3").exists())
            self.assertLessEqual(path.stat().st_size, 220)

    def test_zero_backups_truncates_rotated_log(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "events.jsonl"
            logger = RiskLogger(str(path), max_bytes=220, backup_count=0)

            for index in range(6):
                logger.info("capture_error", index=index, detail="x" * 80)

            self.assertTrue(path.exists())
            self.assertFalse(path.with_name("events.jsonl.1").exists())
            self.assertLessEqual(path.stat().st_size, 220)

    def test_concurrent_writes_remain_valid_json_lines(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "events.jsonl"
            logger = RiskLogger(str(path), max_bytes=1_000_000, backup_count=1)

            def write_batch(worker: int) -> None:
                for index in range(50):
                    logger.info("worker_event", worker=worker, index=index)

            threads = [threading.Thread(target=write_batch, args=(worker,)) for worker in range(4)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()

            lines = path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 200)
            self.assertTrue(all(json.loads(line)["message"] == "worker_event" for line in lines))
            self.assertIsNone(logger.last_error)

    def test_log_io_failure_does_not_raise(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = RiskLogger(tmpdir, max_bytes=1_000_000_000, backup_count=1)

            logger.info("unwritable_target")

            self.assertIsNotNone(logger.last_error)


if __name__ == "__main__":
    unittest.main()
