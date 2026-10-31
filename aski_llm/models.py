"""Core data models for the aski-llm skill system."""

from __future__ import annotations

import copy
import enum
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional


class ChangeClass(enum.Enum):
    """How dangerous a proposed change is. Determines the workflow it goes through."""

    LOW = "low"        # auto-apply + log
    MEDIUM = "medium"  # dry-run + regression tests, then propose for approval
    HIGH = "high"      # blocked, mandatory human escalation


class GuidanceLevel(enum.Enum):
    HINT = "hint"                    # suggestion only
    RECOMMENDATION = "recommendation"  # strong suggestion
    CONSTRAINT = "constraint"        # must be enforced, still filtered by invariants


class GuidanceScope(enum.Enum):
    SESSION = "session"        # current session only
    SKILL = "skill"            # one skill
    GRAPH = "graph"            # the whole graph for this session


@dataclass(frozen=True, order=True)
class Version:
    """Immutable semantic version."""

    major: int
    minor: int
    patch: int

    @classmethod
    def parse(cls, text: str) -> "Version":
        parts = text.split(".")
        if len(parts) != 3 or not all(p.isdigit() for p in parts):
            raise ValueError(f"invalid semantic version: {text!r}")
        return cls(int(parts[0]), int(parts[1]), int(parts[2]))

    def bump(self, part: str) -> "Version":
        if part == "major":
            return Version(self.major + 1, 0, 0)
        if part == "minor":
            return Version(self.major, self.minor + 1, 0)
        if part == "patch":
            return Version(self.major, self.minor, self.patch + 1)
        raise ValueError(f"unknown bump part: {part!r}")

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"


@dataclass(frozen=True)
class Contract:
    """Typed interface of a skill. Other skills may only call through this contract."""

    name: str
    input_schema: Dict[str, str]
    output_schema: Dict[str, str]
    description: str = ""


@dataclass
class SkillVersion:
    """One immutable version of a skill."""

    version: Version
    prompt_template: str
    params: Dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    note: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": str(self.version),
            "prompt_template": self.prompt_template,
            "params": copy.deepcopy(self.params),
            "created_at": self.created_at,
            "note": self.note,
        }


@dataclass
class Skill:
    """A node in the skill graph."""

    name: str
    contract: Contract
    depends_on: List[str] = field(default_factory=list)
    triggers: List[str] = field(default_factory=list)
    handler: Optional[Callable[[Dict[str, Any]], Dict[str, Any]]] = None
    versions: Dict[str, SkillVersion] = field(default_factory=dict)
    head: str = "0.1.0"
    mutable_fields: List[str] = field(default_factory=list)

    def current(self) -> SkillVersion:
        return self.versions[self.head]

    def call(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        if self.handler is None:
            raise RuntimeError(f"skill {self.name!r} has no handler")
        self._validate_input(payload)
        out = self.handler(copy.deepcopy(payload))
        self._validate_output(out)
        return out

    def _validate_input(self, payload: Dict[str, Any]) -> None:
        missing = [k for k in self.contract.input_schema if k not in payload]
        if missing:
            raise ValueError(f"skill {self.name!r} missing inputs: {missing}")

    def _validate_output(self, out: Dict[str, Any]) -> None:
        if not isinstance(out, dict):
            raise ValueError(f"skill {self.name!r} handler must return a dict")
        missing = [k for k in self.contract.output_schema if k not in out]
        if missing:
            raise ValueError(f"skill {self.name!r} output missing keys: {missing}")


@dataclass
class Guidance:
    """A contextual directive emitted by a skill (or the model) towards others."""

    emitter: str
    target: str  # skill name, "session", or "*" for graph-wide
    level: GuidanceLevel
    scope: GuidanceScope
    content: str
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    created_at: float = field(default_factory=time.time)


@dataclass
class ChangeProposal:
    """A modification a skill (or the model) wants to apply to a skill."""

    target_skill: str
    field: str
    new_value: Any
    reason: str
    requested_by: str
    change_class: ChangeClass
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    created_at: float = field(default_factory=time.time)
    applied: bool = False
    new_version: Optional[str] = None


@dataclass
class Persona:
    """A creative interpretation of a personality description."""

    raw_description: str
    traits: List[str]
    variants: List[str]
    chosen: Optional[str] = None
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])


@dataclass
class AuditEntry:
    """One append-only audit record."""

    kind: str  # proposal | applied | rejected | blocked | reverted | guidance | feedback
    actor: str
    detail: Dict[str, Any]
    ts: float = field(default_factory=time.time)
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
