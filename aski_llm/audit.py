"""Append-only audit log. Every proposal, application, rejection, revert,
guidance and feedback event is recorded here."""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

from .models import AuditEntry


class AuditLog:
    def __init__(self, path: Optional[str] = None) -> None:
        self._entries: List[AuditEntry] = []
        self._path = path
        if path and os.path.exists(path):
            with open(path, "r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    raw = json.loads(line)
                    self._entries.append(
                        AuditEntry(kind=raw["kind"], actor=raw["actor"], detail=raw["detail"], ts=raw["ts"], id=raw["id"])
                    )

    def record(self, kind: str, actor: str, detail: Dict[str, Any]) -> AuditEntry:
        entry = AuditEntry(kind=kind, actor=actor, detail=detail)
        self._entries.append(entry)
        if self._path:
            with open(self._path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps({"kind": entry.kind, "actor": entry.actor, "detail": entry.detail, "ts": entry.ts, "id": entry.id}) + "\n")
        return entry

    def entries(self, kind: Optional[str] = None) -> List[AuditEntry]:
        if kind is None:
            return list(self._entries)
        return [e for e in self._entries if e.kind == kind]

    def __len__(self) -> int:
        return len(self._entries)
