"""Append-only audit trail at output/audit_trail.json.

The file is one JSON array. Each write loads the existing records, adds the
new one, and swaps the file in atomically, so earlier runs are never lost and
a crash mid-write can't leave half a file behind.
"""

from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from config import AUDIT_PATH, AUDIT_TEXT_LIMIT


def clip(value: Any, limit: int = AUDIT_TEXT_LIMIT) -> Any:
    """Shorten long strings (recursively) so the audit stays readable."""
    if isinstance(value, str):
        return value if len(value) <= limit else value[:limit] + f"... [+{len(value) - limit} chars]"
    if isinstance(value, dict):
        return {k: clip(v, limit) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clip(v, limit) for v in value]
    return value


class AuditLog:
    def __init__(self, path: Path = AUDIT_PATH) -> None:
        self.path = path
        self._lock = asyncio.Lock()
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _load(self) -> list[dict]:
        if not self.path.exists() or self.path.stat().st_size == 0:
            return []
        try:
            records = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            # Never silently drop history: keep the unreadable file aside and start fresh.
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            self.path.rename(self.path.with_name(f"{self.path.stem}.corrupt-{stamp}.json"))
            return []
        return records if isinstance(records, list) else [records]

    async def append(self, event: str, **fields: Any) -> None:
        record = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "event": event,
            **clip(fields),
        }
        async with self._lock:
            records = self._load()
            record["seq"] = len(records) + 1
            records.append(record)
            tmp = self.path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(records, indent=2, default=str), encoding="utf-8")
            os.replace(tmp, self.path)
