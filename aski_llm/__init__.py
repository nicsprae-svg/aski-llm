"""aski-llm: interlinked, self-modifying skill system with bounded autonomy.

Components:
  - graph:    skill graph with dependencies, contracts and semantic versioning
  - engine:   bounded self-modification loop (dry-run, regression tests, rollback)
  - guidance: scoped guidance channel (hint / recommendation / constraint)
  - composer: starting instruction, creative persona, semi-random idea generator
  - practices: weighted library of good practices fed by user feedback
"""

from .models import (
    AuditEntry,
    ChangeClass,
    ChangeProposal,
    Contract,
    Guidance,
    GuidanceLevel,
    GuidanceScope,
    Persona,
    Skill,
    SkillVersion,
    Version,
)
from .invariants import INVARIANTS, MutableField, classify_change, is_mutable_field
from .audit import AuditLog
from .graph import SkillGraph
from .engine import SelfModificationEngine
from .guidance import GuidanceEngine
from .practices import Practice, PracticeLibrary
from .composer import Composer, ComposerDocument

__all__ = [
    "AuditEntry",
    "AuditLog",
    "ChangeClass",
    "ChangeProposal",
    "Composer",
    "ComposerDocument",
    "Contract",
    "Guidance",
    "GuidanceEngine",
    "GuidanceLevel",
    "GuidanceScope",
    "INVARIANTS",
    "MutableField",
    "Persona",
    "Practice",
    "PracticeLibrary",
    "SelfModificationEngine",
    "Skill",
    "SkillGraph",
    "SkillVersion",
    "Version",
    "classify_change",
    "is_mutable_field",
]

__version__ = "0.1.0"
