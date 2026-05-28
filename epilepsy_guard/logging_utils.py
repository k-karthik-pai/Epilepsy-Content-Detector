from __future__ import annotations

import json
import time
from pathlib import Path

from .models import RiskDecision, RiskEvidence


class RiskLogger:
    def __init__(self, path: str | None) -> None:
        self.path = Path(path) if path else None
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
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, separators=(",", ":")) + "\n")

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
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, separators=(",", ":")) + "\n")

    def _evidence_to_dict(self, evidence: RiskEvidence) -> dict[str, object]:
        return {
            "reason": evidence.reason,
            "monitor_id": evidence.monitor_id,
            "value": evidence.value,
            "threshold": evidence.threshold,
            "detail": evidence.detail,
        }

