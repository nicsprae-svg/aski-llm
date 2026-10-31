"""Weighted library of good practices, evolved by user feedback.

Practices are tagged by domain. The idea generator samples from applicable
practices; user feedback (keep / reject) re-weights them so that practices
judged useful for a given case rise for next time.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


@dataclass
class Practice:
    id: str
    text: str
    tags: List[str]
    weight: float = 1.0

    def to_dict(self) -> Dict[str, object]:
        return {"id": self.id, "text": self.text, "tags": list(self.tags), "weight": self.weight}


class PracticeLibrary:
    def __init__(self, seed: Optional[int] = None) -> None:
        self._practices: Dict[str, Practice] = {}
        self._rng = random.Random(seed)
        self._load_defaults()

    def _load_defaults(self) -> None:
        defaults = [
            ("p-cite", "Cite sources or label claims that are unverified.", ["rigor", "analysis", "writing"]),
            ("p-structure", "Structure the answer: summary first, then details.", ["writing", "analysis"]),
            ("p-examples", "Illustrate each point with one concrete example.", ["teaching", "writing", "creative"]),
            ("p-steelman", "State the strongest version of the opposing view before countering it.", ["debate", "analysis"]),
            ("p-steps", "Break the task into explicit numbered steps.", ["code", "analysis", "planning"]),
            ("p-tests", "Propose how to verify the result before finalizing.", ["code", "rigor"]),
            ("p-tone", "Match the requested tone and stay consistent with it.", ["writing", "creative"]),
            ("p-questions", "End with one clarifying question if the request is ambiguous.", ["coaching", "teaching"]),
            ("p-alternatives", "Offer two alternative approaches with trade-offs.", ["creative", "planning", "code"]),
            ("p-concise", "Prefer the shortest answer that fully covers the request.", ["writing", "code"]),
        ]
        for pid, text, tags in defaults:
            self._practices[pid] = Practice(id=pid, text=text, tags=tags)

    def add(self, pid: str, text: str, tags: List[str], weight: float = 1.0) -> Practice:
        p = Practice(id=pid, text=text, tags=list(tags), weight=weight)
        self._practices[pid] = p
        return p

    def applicable(self, domain_tags: List[str]) -> List[Practice]:
        tags = set(domain_tags)
        return [p for p in self._practices.values() if tags & set(p.tags)]

    def sample(self, domain_tags: List[str], k: int = 3, rng: Optional[random.Random] = None) -> List[Practice]:
        pool = self.applicable(domain_tags)
        if not pool:
            pool = list(self._practices.values())
        rng = rng or self._rng
        weights = [max(p.weight, 0.01) for p in pool]
        chosen: List[Practice] = []
        pool_copy = list(pool)
        weights_copy = list(weights)
        for _ in range(min(k, len(pool_copy))):
            total = sum(weights_copy)
            r = rng.random() * total
            acc = 0.0
            idx = 0
            for i, w in enumerate(weights_copy):
                acc += w
                if r <= acc:
                    idx = i
                    break
            chosen.append(pool_copy.pop(idx))
            weights_copy.pop(idx)
        return chosen

    def feedback(self, practice_id: str, accepted: bool, learning_rate: float = 0.25) -> float:
        p = self._practices[practice_id]
        target = 2.0 if accepted else 0.25
        p.weight = max(0.05, p.weight + learning_rate * (target - p.weight))
        return p.weight

    def all(self) -> List[Practice]:
        return list(self._practices.values())
