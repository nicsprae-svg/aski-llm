"""The Composer interface: three panels that produce a versioned config doc.

Panel 1 - structured starting instruction from well-defined criteria
          (schema-validated, compiled into a reusable system prompt).
Panel 2 - creative interpretation of a personality description into
          concrete observable traits, with variants to pick from.
Panel 3 - semi-random instruction generator on demand, sampling from the
          weighted library of good practices for the current case, with
          keep/reject feedback feeding back into the weights.
"""

from __future__ import annotations

import random
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from .models import Persona, Version
from .practices import Practice, PracticeLibrary


PANEL1_FIELDS = {
    "role": str,
    "tone": str,
    "language": str,
    "output_format": str,
    "max_length": str,
    "constraints": list,
    "allowed_resources": list,
}


@dataclass
class IdeaProposal:
    instruction: str
    sources: List[str]  # practice ids it was sampled from
    justification: str
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:10])
    verdict: Optional[bool] = None  # True=kept, False=rejected


@dataclass
class ComposerDocument:
    """Versioned configuration produced by the Composer."""

    panel1: Dict[str, Any]
    persona: Optional[Persona]
    ideas: List[IdeaProposal]
    version: Version = field(default_factory=lambda: Version(1, 0, 0))
    created_at: float = field(default_factory=time.time)
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])

    def system_prompt(self) -> str:
        p = self.panel1
        lines = [
            f"Role: {p.get('role', '')}",
            f"Tone: {p.get('tone', '')}",
            f"Language: {p.get('language', '')}",
            f"Output format: {p.get('output_format', '')}",
            f"Max length: {p.get('max_length', '')}",
        ]
        if self.persona and self.persona.chosen:
            lines.append(f"Persona: {self.persona.chosen}")
        constraints = p.get("constraints") or []
        if constraints:
            lines.append("Constraints: " + "; ".join(constraints))
        kept = [i.instruction for i in self.ideas if i.verdict is True]
        if kept:
            lines.append("Adopted instructions: " + " | ".join(kept))
        return "\n".join(lines)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "version": str(self.version),
            "created_at": self.created_at,
            "panel1": dict(self.panel1),
            "persona": None if self.persona is None else {
                "raw": self.persona.raw_description,
                "traits": self.persona.traits,
                "variants": self.persona.variants,
                "chosen": self.persona.chosen,
                "id": self.persona.id,
            },
            "ideas": [
                {"id": i.id, "instruction": i.instruction, "sources": i.sources, "justification": i.justification, "verdict": i.verdict}
                for i in self.ideas
            ],
        }


class Composer:
    def __init__(self, library: Optional[PracticeLibrary] = None, seed: Optional[int] = None) -> None:
        self.library = library or PracticeLibrary(seed=seed)
        self._rng = random.Random(seed)

    # ---- Panel 1: structured starting instruction -------------------------

    def build_instruction(self, criteria: Dict[str, Any]) -> Dict[str, Any]:
        unknown = set(criteria) - set(PANEL1_FIELDS)
        if unknown:
            raise ValueError(f"unknown criteria fields: {sorted(unknown)}")
        cleaned: Dict[str, Any] = {}
        for key, expected in PANEL1_FIELDS.items():
            value = criteria.get(key)
            if value is None:
                continue
            if expected is list and not isinstance(value, list):
                raise ValueError(f"field {key!r} must be a list")
            if expected is str and not isinstance(value, str):
                raise ValueError(f"field {key!r} must be a string")
            cleaned[key] = value
        if "role" not in cleaned:
            raise ValueError("panel1 requires at least a 'role'")
        cleaned.setdefault("language", "fr")
        return cleaned

    # ---- Panel 2: creative personality interpretation ----------------------

    def interpret_personality(self, description: str, n_variants: int = 3) -> Persona:
        if not description or not description.strip():
            raise ValueError("personality description must not be empty")
        traits = self._extract_traits(description)
        variants = self._make_variants(description, traits, n_variants)
        return Persona(raw_description=description, traits=traits, variants=variants)

    def _extract_traits(self, description: str) -> List[str]:
        text = description.lower()
        trait_map = {
            "sec": "answers briefly, dry humour tolerated",
            "bienveillant": "encourages and reassures before correcting",
            "pédagogue": "explains the why behind every step",
            "direct": "goes straight to the point, no filler",
            "créatif": "proposes unexpected angles and metaphors",
            "rigoureux": "checks facts, flags uncertainty explicitly",
            "chaleureux": "warm, conversational tone",
            "technique": "precise vocabulary, assumes expertise",
        }
        traits = [v for k, v in trait_map.items() if k in text]
        if not traits:
            traits = ["neutral, adaptive tone: mirrors the user's register"]
        return traits

    def _make_variants(self, description: str, traits: List[str], n: int) -> List[str]:
        base = f"Persona '{description.strip()}': " + "; ".join(traits)
        variants = [base]
        flavors = ["slightly more formal", "slightly more playful", "more concise"]
        for i in range(1, min(n, len(flavors) + 1)):
            variants.append(f"{base} — {flavors[i - 1]}")
        return variants

    def choose_variant(self, persona: Persona, variant: str) -> Persona:
        if variant not in persona.variants:
            raise ValueError("variant not offered by this persona")
        persona.chosen = variant
        return persona

    # ---- Panel 3: semi-random idea generator --------------------------------

    def generate_ideas(self, domain_tags: List[str], n: int = 3, k_sources: int = 2) -> List[IdeaProposal]:
        practices = self.library.sample(domain_tags, k=k_sources)
        if not practices:
            return []
        ideas: List[IdeaProposal] = []
        tones = ["directly instructive", "as a checklist", "as a guiding question"]
        for i in range(n):
            srcs = self.library.sample(domain_tags, k=k_sources, rng=self._rng)
            if not srcs:
                break
            tone = tones[i % len(tones)]
            instruction = self._compose_instruction(srcs, tone)
            justification = "inspired by: " + ", ".join(f"[{p.id}] {p.text}" for p in srcs) + f" (case tags: {', '.join(domain_tags)})"
            ideas.append(IdeaProposal(instruction=instruction, sources=[p.id for p in srcs], justification=justification))
        return ideas

    def _compose_instruction(self, sources: List[Practice], tone: str) -> str:
        texts = [p.text.rstrip(".") for p in sources]
        if tone == "directly instructive":
            return "When answering: " + "; and ".join(texts) + "."
        if tone == "as a checklist":
            return "Follow this checklist: " + " | ".join(f"- {t}" for t in texts)
        return "Ask yourself before answering: " + " and ".join(f'"{t}?"' for t in texts)

    def feedback(self, idea: IdeaProposal, kept: bool) -> List[float]:
        idea.verdict = kept
        return [self.library.feedback(pid, kept) for pid in idea.sources]

    # ---- Assemble ------------------------------------------------------------

    def compose(self, criteria: Dict[str, Any], personality: Optional[str] = None, domain_tags: Optional[List[str]] = None, n_ideas: int = 3) -> ComposerDocument:
        panel1 = self.build_instruction(criteria)
        persona = self.interpret_personality(personality) if personality else None
        ideas = self.generate_ideas(domain_tags or ["writing"], n=n_ideas) if domain_tags is not None else []
        return ComposerDocument(panel1=panel1, persona=persona, ideas=ideas)
