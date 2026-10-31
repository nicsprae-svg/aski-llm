"""Bounded self-modification engine.

The model (or a skill) may *propose* changes. Depending on the class:
  LOW    -> validated, applied, logged (rate-limited)
  MEDIUM -> dry-run against regression tests; applied only if all pass, then logged as needing approval
  HIGH   -> blocked outright, human escalation required

Invariants and non-allow-listed fields can never be touched.
Every applied change creates a new immutable version; rollback is instant.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from .audit import AuditLog
from .graph import SkillGraph
from .invariants import INVARIANTS, classify_change, is_mutable_field, violates_invariant
from .models import ChangeClass, ChangeProposal, Skill


RegressionTest = Callable[[SkillGraph, str], Tuple[bool, str]]


@dataclass
class EngineResult:
    proposal: ChangeProposal
    action: str  # "applied" | "proposed" | "blocked" | "rejected"
    detail: str
    new_version: Optional[str] = None


class SelfModificationEngine:
    def __init__(
        self,
        graph: SkillGraph,
        audit: Optional[AuditLog] = None,
        window_seconds: int = 3600,
    ) -> None:
        self.graph = graph
        self.audit = audit if audit is not None else AuditLog()
        self.window_seconds = window_seconds
        self._applied_times: List[float] = []
        self._regression_tests: Dict[str, List[RegressionTest]] = {}

    def register_regression_test(self, skill_name: str, test: RegressionTest) -> None:
        self._regression_tests.setdefault(skill_name, []).append(test)

    def _rate_limit_ok(self) -> bool:
        now = time.time()
        self._applied_times = [t for t in self._applied_times if now - t < self.window_seconds]
        return len(self._applied_times) < INVARIANTS["max_auto_changes_per_window"]

    def propose(self, target_skill: str, field: str, new_value: Any, reason: str, requested_by: str = "model") -> EngineResult:
        skill = self.graph.get(target_skill)
        old_value = self._current_value(skill, field)

        if violates_invariant(reason) or violates_invariant(str(new_value)):
            proposal = ChangeProposal(target_skill, field, new_value, reason, requested_by, ChangeClass.HIGH)
            self.audit.record("blocked", requested_by, {"proposal_id": proposal.id, "reason": "content violates invariants"})
            return EngineResult(proposal, "blocked", "content collides with system invariants")

        change_class = classify_change(field, old_value, new_value)
        proposal = ChangeProposal(target_skill, field, new_value, reason, requested_by, change_class)
        self.audit.record("proposal", requested_by, {"proposal_id": proposal.id, "skill": target_skill, "field": field, "class": change_class.value})

        if change_class == ChangeClass.HIGH:
            self.audit.record("blocked", requested_by, {"proposal_id": proposal.id, "reason": "HIGH class requires human approval"})
            return EngineResult(proposal, "blocked", "structural/invariant change: human approval required")

        if field not in skill.mutable_fields or not is_mutable_field(field):
            self.audit.record("blocked", requested_by, {"proposal_id": proposal.id, "reason": "field not in allow-list"})
            return EngineResult(proposal, "blocked", f"field {field!r} is not in the skill's mutable allow-list")

        if change_class == ChangeClass.LOW:
            if not self._rate_limit_ok():
                self.audit.record("rejected", requested_by, {"proposal_id": proposal.id, "reason": "rate limit reached"})
                return EngineResult(proposal, "rejected", "auto-change rate limit reached for this window")
            new_version = self._apply(proposal)
            return EngineResult(proposal, "applied", "LOW change auto-applied", new_version)

        # MEDIUM: dry-run + regression tests
        ok, detail = self._dry_run(target_skill, proposal)
        if not ok:
            self.audit.record("rejected", requested_by, {"proposal_id": proposal.id, "reason": detail})
            return EngineResult(proposal, "rejected", f"dry-run failed: {detail}")
        new_version = self._apply(proposal)
        return EngineResult(proposal, "proposed", "MEDIUM change passed regression tests; applied as candidate, pending approval", new_version)

    def _current_value(self, skill: Skill, field: str) -> Any:
        head = skill.current()
        if field == "prompt_template":
            return head.prompt_template
        if field == "params":
            return dict(head.params)
        return None

    def _apply(self, proposal: ChangeProposal) -> str:
        new_version = self.graph.apply_proposal(proposal)
        proposal.applied = True
        proposal.new_version = str(new_version.version)
        self._applied_times.append(time.time())
        self.audit.record("applied", proposal.requested_by, {"proposal_id": proposal.id, "skill": proposal.target_skill, "version": proposal.new_version})
        return proposal.new_version

    def _dry_run(self, skill_name: str, proposal: ChangeProposal) -> Tuple[bool, str]:
        tests = self._regression_tests.get(skill_name, [])
        if not tests:
            return True, "no regression tests registered (accepted)"
        for i, test in enumerate(tests):
            ok, detail = test(self.graph, skill_name)
            if not ok:
                return False, f"regression test #{i} failed: {detail}"
        return True, "all regression tests passed"

    def revert(self, skill_name: str, version: str, actor: str = "model") -> str:
        current = self.graph.get(skill_name).head
        self.graph.revert_to(skill_name, version)
        self.audit.record("reverted", actor, {"skill": skill_name, "from": current, "to": version})
        return version

    def drift_check(self, skill_name: str) -> Optional[str]:
        """If the latest regression run degraded, auto-rollback to previous version."""
        tests = self._regression_tests.get(skill_name, [])
        versions = self.graph.versions_of(skill_name)
        if len(versions) < 2 or not tests:
            return None
        head = self.graph.get(skill_name).head
        for test in tests:
            ok, _ = test(self.graph, skill_name)
            if not ok:
                previous = versions[-2]
                self.revert(skill_name, previous, actor="drift-check")
                return previous
        return None
