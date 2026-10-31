"""The interlinked skill graph.

Skills are nodes with explicit dependencies (`depends_on`) and triggers.
Calls between skills go through typed contracts only. Every published
version is immutable; `head` points at the active one.
"""

from __future__ import annotations

import copy
from typing import Any, Callable, Dict, List, Optional

from .models import ChangeProposal, Contract, Skill, SkillVersion, Version


class SkillGraph:
    def __init__(self) -> None:
        self._skills: Dict[str, Skill] = {}

    def add_skill(
        self,
        name: str,
        contract: Contract,
        handler: Optional[Callable[[Dict[str, Any]], Dict[str, Any]]] = None,
        depends_on: Optional[List[str]] = None,
        triggers: Optional[List[str]] = None,
        mutable_fields: Optional[List[str]] = None,
        initial_prompt: str = "",
        initial_params: Optional[Dict[str, Any]] = None,
    ) -> Skill:
        if name in self._skills:
            raise ValueError(f"skill {name!r} already exists")
        skill = Skill(
            name=name,
            contract=contract,
            depends_on=list(depends_on or []),
            triggers=list(triggers or []),
            handler=handler,
            mutable_fields=list(mutable_fields or []),
            versions={"0.1.0": SkillVersion(version=Version(0, 1, 0), prompt_template=initial_prompt, params=dict(initial_params or {}))},
            head="0.1.0",
        )
        for dep in skill.depends_on:
            if dep not in self._skills and dep != name:
                # forward references allowed; resolved lazily at call time
                pass
        self._skills[name] = skill
        return skill

    def get(self, name: str) -> Skill:
        if name not in self._skills:
            raise KeyError(f"unknown skill: {name!r}")
        return self._skills[name]

    def names(self) -> List[str]:
        return sorted(self._skills)

    def dependencies_of(self, name: str) -> List[str]:
        return list(self.get(name).depends_on)

    def triggered_by(self, skill_name: str) -> List[str]:
        """Skills whose trigger list contains `skill_name`."""
        return [s.name for s in self._skills.values() if skill_name in s.triggers]

    def call(self, name: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Call a skill through its contract. Dependencies must already be satisfied."""
        skill = self.get(name)
        for dep in skill.depends_on:
            if dep not in self._skills:
                raise RuntimeError(f"skill {name!r} depends on missing skill {dep!r}")
        return skill.call(payload)

    def publish_version(self, name: str, note: str = "") -> SkillVersion:
        """Freeze the current head state as a new immutable version."""
        skill = self.get(name)
        head = skill.current()
        new_v = head.version.bump("patch")
        clone = SkillVersion(
            version=new_v,
            prompt_template=head.prompt_template,
            params=copy.deepcopy(head.params),
            note=note or head.note,
        )
        skill.versions[str(new_v)] = clone
        skill.head = str(new_v)
        return clone

    def revert_to(self, name: str, version: str) -> SkillVersion:
        skill = self.get(name)
        if version not in skill.versions:
            raise KeyError(f"skill {name!r} has no version {version}")
        skill.head = version
        return skill.versions[version]

    def versions_of(self, name: str) -> List[str]:
        return sorted(self.get(name).versions, key=lambda v: Version.parse(v))

    def apply_proposal(self, proposal: ChangeProposal) -> SkillVersion:
        """Apply a LOW/MEDIUM change that already passed validation."""
        skill = self.get(proposal.target_skill)
        if proposal.field not in skill.mutable_fields:
            raise PermissionError(f"field {proposal.field!r} is not in mutable_fields of {skill.name!r}")
        head = skill.current()
        if proposal.field == "prompt_template":
            new_prompt = proposal.new_value
        elif proposal.field == "params":
            new_prompt = head.prompt_template
        else:
            raise PermissionError(f"field {proposal.field!r} not mutable")
        new_params = copy.deepcopy(head.params)
        if proposal.field == "params":
            new_params.update(proposal.new_value)
        new_v = head.version.bump("patch")
        clone = SkillVersion(version=new_v, prompt_template=new_prompt, params=new_params, note=proposal.reason)
        skill.versions[str(new_v)] = clone
        skill.head = str(new_v)
        return clone
