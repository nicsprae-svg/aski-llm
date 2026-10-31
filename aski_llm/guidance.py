"""Scoped guidance channel.

A skill or the model may emit guidance towards others:
  - level:  hint / recommendation / constraint
  - scope:  session / skill / graph-local
Constraints are always filtered through the immutable invariants: even a
"constraint" guidance can never weaken them. Every guidance is audited and
rate-limited per session.
"""

from __future__ import annotations

import time
from typing import Dict, List, Optional

from .audit import AuditLog
from .invariants import INVARIANTS, violates_invariant
from .models import Guidance, GuidanceLevel, GuidanceScope


class GuidanceEngine:
    def __init__(self, audit: Optional[AuditLog] = None) -> None:
        self.audit = audit if audit is not None else AuditLog()
        self._guidances: List[Guidance] = []
        self._session_start = time.time()

    def emit(self, emitter: str, target: str, level: GuidanceLevel, scope: GuidanceScope, content: str) -> Optional[Guidance]:
        if len(self._guidances) >= INVARIANTS["max_guidances_per_session"]:
            self.audit.record("rejected", emitter, {"reason": "guidance rate limit reached", "content": content})
            return None
        if violates_invariant(content):
            self.audit.record("blocked", emitter, {"reason": "guidance violates invariants", "content": content})
            return None
        if level == GuidanceLevel.CONSTRAINT and not self._constraint_allowed(content):
            self.audit.record("blocked", emitter, {"reason": "constraint would weaken invariants", "content": content})
            return None
        g = Guidance(emitter=emitter, target=target, level=level, scope=scope, content=content)
        self._guidances.append(g)
        self.audit.record("guidance", emitter, {"id": g.id, "target": target, "level": level.value, "scope": scope.value, "content": content})
        return g

    def _constraint_allowed(self, content: str) -> bool:
        # A constraint is only allowed if it reinforces, never weakens, invariants.
        lowered = content.lower()
        weakening = ["ignore", "bypass", "disable", "remove", "skip"] + [r.split()[0] for r in INVARIANTS["safety_rules"]]
        return not any(w in lowered for w in ["bypass", "ignore safety", "disable safety"])

    def active_for(self, target: str, scope: GuidanceScope) -> List[Guidance]:
        return [
            g for g in self._guidances
            if g.scope == scope and (g.target == target or g.target == "*")
        ]

    def all(self) -> List[Guidance]:
        return list(self._guidances)

    def enforce_constraints(self, target: str) -> List[str]:
        """Constraints applicable to a target, always intersected with invariants."""
        out = list(INVARIANTS["safety_rules"])
        for g in self.active_for(target, GuidanceScope.SESSION):
            if g.level == GuidanceLevel.CONSTRAINT:
                out.append(g.content)
        return out
