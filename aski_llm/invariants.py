"""Immutable system invariants and the mutation allow-list.

The model may never modify anything in INVARIANTS or in a skill's
immutable fields. Only fields listed in the skill's `mutable_fields`
(and restricted to LOW-class value tweaks) may change autonomously.
"""

from __future__ import annotations

import enum
from typing import Any, Dict

from .models import ChangeClass


class MutableField(str, enum.Enum):
    """Fields a skill is allowed to auto-modify (LOW class only)."""

    PROMPT_TEMPLATE = "prompt_template"
    PARAMS = "params"


# System-level invariants: not modifiable by the model itself, ever.
INVARIANTS: Dict[str, Any] = {
    "forbidden_tools": ["exec_shell", "network_write", "delete_all"],
    "safety_rules": [
        "never output secrets",
        "never run destructive commands",
        "always confirm before irreversible actions",
    ],
    "max_auto_changes_per_window": 5,
    "max_guidances_per_session": 50,
    "require_human_for": ["contract", "depends_on", "triggers", "mutable_fields", "handler"],
}

# Fields that structurally change a skill: always HIGH class.
STRUCTURAL_FIELDS = {"contract", "depends_on", "triggers", "mutable_fields", "handler"}


def is_mutable_field(field: str) -> bool:
    try:
        MutableField(field)
        return True
    except ValueError:
        return False


def is_structural_field(field: str) -> bool:
    return field in STRUCTURAL_FIELDS


def classify_change(field: str, old_value: Any, new_value: Any) -> ChangeClass:
    """Classify a proposed change.

    - structural / invariant / unknown field  -> HIGH (blocked, human required)
    - prompt_template or params with a small, safe delta -> LOW
    - anything else on a mutable field -> MEDIUM (dry-run + tests)
    """
    if field in INVARIANTS or field in STRUCTURAL_FIELDS or not is_mutable_field(field):
        return ChangeClass.HIGH

    if field == MutableField.PROMPT_TEMPLATE.value:
        if isinstance(old_value, str) and isinstance(new_value, str):
            # Heuristic: prompt edits are LOW only if they stay a tweak
            # (similar length, no wholesale rewrite).
            ratio = len(new_value) / max(len(old_value), 1)
            if 0.5 <= ratio <= 2.0:
                return ChangeClass.LOW
            return ChangeClass.MEDIUM
        return ChangeClass.MEDIUM

    if field == MutableField.PARAMS.value:
        if isinstance(old_value, dict) and isinstance(new_value, dict):
            changed = set(old_value) ^ set(new_value)
            if not changed and all(old_value.get(k) == new_value.get(k) for k in old_value):
                return ChangeClass.LOW  # no-op tweak
            # Numeric threshold-style tweaks are LOW, structural param changes MEDIUM
            for k in set(old_value) & set(new_value):
                o, n = old_value[k], new_value[k]
                if isinstance(o, (int, float)) and isinstance(n, (int, float)):
                    continue
            if changed:
                return ChangeClass.MEDIUM
            return ChangeClass.LOW
        return ChangeClass.MEDIUM

    return ChangeClass.HIGH


def violates_invariant(content: str) -> bool:
    """Check whether a guidance/change content collides with safety invariants."""
    lowered = content.lower()
    banned = ["ignore safety", "bypass invariant", "disable safety", "exfiltrate", "remove invariant"]
    return any(b in lowered for b in banned)
