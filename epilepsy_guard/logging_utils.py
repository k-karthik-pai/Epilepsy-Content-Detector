from __future__ import annotations

import json
import threading
import time
from pathlib import Path

from .models import RiskDecision, RiskEvidence


class RiskLogger:
    def __init__(self, path: str | None, max_bytes: int = 1_000_000, backup_count: int = 5) -> None:
        self.path = Path(path) if path else None
        self.max_bytes = max_bytes
        self.backup_count = backup_count
        self.last_error: str | None = None
        self._lock = threading.Lock()
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, decision: RiskDecision, source: str = "detector") -> None:
        if not self.path:
            return
        record = {
            "timestamp": time.time(),
            "source": source,
            "level": decision.level.value,
            "reasons": list(decision.reasons),
            "evidence": [self._evidence_to_dict(item) for item in decision.evidence],
        }
        self._write_record(record)

    def info(self, message: str, **detail: object) -> None:
        if not self.path:
            return
        record = {
            "timestamp": time.time(),
            "source": "app",
            "level": "info",
            "message": message,
            "detail": detail,
        }
        self._write_record(record)

    def _evidence_to_dict(self, evidence: RiskEvidence) -> dict[str, object]:
        return {
            "reason": evidence.reason,
            "monitor_id": evidence.monitor_id,
            "value": evidence.value,
            "threshold": evidence.threshold,
            "detail": evidence.detail,
        }

    def _write_record(self, record: dict[str, object]) -> None:
        if not self.path:
            return
        line = json.dumps(record, separators=(",", ":")) + "\n"
        try:
            with self._lock:
                self._rotate_if_needed(len(line.encode("utf-8")))
                with self.path.open("a", encoding="utf-8") as handle:
                    handle.write(line)
                self.last_error = None
        except OSError as exc:
            self.last_error = repr(exc)

    def _rotate_if_needed(self, incoming_bytes: int) -> None:
        if not self.path or not self.path.exists():
            return
        if self.path.stat().st_size + incoming_bytes <= self.max_bytes:
            return
        if self.backup_count <= 0:
            self.path.unlink()
            return

        oldest = self._backup_path(self.backup_count)
        if oldest.exists():
            oldest.unlink()
        for index in range(self.backup_count - 1, 0, -1):
            source = self._backup_path(index)
            if source.exists():
                source.replace(self._backup_path(index + 1))
        self.path.replace(self._backup_path(1))

    def _backup_path(self, index: int) -> Path:
        return self.path.with_name(f"{self.path.name}.{index}")
