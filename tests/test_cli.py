from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path

from epilepsy_guard.app import main


class CliTests(unittest.TestCase):
    def test_invalid_config_returns_clean_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "config.json"
            path.write_text(json.dumps({"detector": {"flash_area_ratio": 2.0}}), encoding="utf-8")
            stderr = io.StringIO()
            with redirect_stderr(stderr):
                exit_code = main(["--config", str(path), "--once"])

        self.assertEqual(exit_code, 2)
        self.assertIn("Configuration error:", stderr.getvalue())
        self.assertNotIn("Traceback", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
