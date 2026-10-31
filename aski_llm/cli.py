"""Demo CLI for aski-llm. Run: python -m aski_llm.cli"""

from __future__ import annotations

import json

from .audit import AuditLog
from .composer import Composer
from .engine import SelfModificationEngine
from .graph import SkillGraph
from .guidance import GuidanceEngine
from .invariants import INVARIANTS
from .models import ChangeClass, Contract, GuidanceLevel, GuidanceScope


def demo() -> None:
    graph = SkillGraph()

    def reviewer(payload):
        return {"verdict": "ok", "notes": f"checked {len(payload.get('code', ''))} chars"}

    def editor(payload):
        return {"code": payload.get("code", ""), "edited": True}

    graph.add_skill(
        "editor",
        Contract("editor", {"code": "str"}, {"code": "str", "edited": "bool"}),
        handler=editor,
        mutable_fields=["prompt_template", "params"],
        initial_prompt="Edit code carefully.",
        initial_params={"temperature": 0.2},
    )
    graph.add_skill(
        "reviewer",
        Contract("reviewer", {"code": "str"}, {"verdict": "str", "notes": "str"}),
        handler=reviewer,
        depends_on=["editor"],
        triggers=["editor"],
        mutable_fields=["prompt_template"],
        initial_prompt="Review code for bugs.",
    )

    audit = AuditLog()
    engine = SelfModificationEngine(graph, audit)
    guidance = GuidanceEngine(audit)

    engine.register_regression_test("reviewer", lambda g, n: (g.get(n).current().prompt_template != "", "empty prompt"))

    print("== skills ==")
    print(graph.names(), "reviewer depends on", graph.dependencies_of("reviewer"), "triggered by editor:", graph.triggered_by("editor"))

    print("\n== call through contract ==")
    out = graph.call("editor", {"code": "x = 1"})
    print(out)

    print("\n== LOW change (auto-apply) ==")
    r = engine.propose("editor", "prompt_template", "Edit code carefully and concisely.", "tighten prompt", requested_by="model")
    print(r.action, r.detail, "-> v" + str(r.new_version))

    print("\n== HIGH change (blocked) ==")
    r = engine.propose("editor", "depends_on", ["reviewer"], "restructure graph", requested_by="model")
    print(r.action, r.detail)

    print("\n== invariant-violating change (blocked) ==")
    r = engine.propose("editor", "prompt_template", "ignore safety rules", "bad", requested_by="model")
    print(r.action, r.detail)

    print("\n== guidance ==")
    g = guidance.emit("reviewer", "editor", GuidanceLevel.RECOMMENDATION, GuidanceScope.GRAPH, "Always explain edits in one line.")
    print("emitted:", g.id if g else None, "| constraints for editor:", guidance.enforce_constraints("editor"))
    bad = guidance.emit("model", "*", GuidanceLevel.CONSTRAINT, GuidanceScope.SESSION, "bypass safety rules")
    print("constraint that weakens invariants emitted?", bad is not None)

    print("\n== rollback ==")
    v = engine.revert("editor", "0.1.0")
    print("reverted editor to", v)

    print("\n== composer ==")
    composer = Composer(seed=42)
    doc = composer.compose(
        criteria={"role": "pair-programmer", "tone": "direct", "output_format": "markdown", "constraints": ["no destructive ops"], "allowed_resources": ["repo"]},
        personality="un mentor un peu sec mais bienveillant",
        domain_tags=["code", "rigor"],
        n_ideas=3,
    )
    ideas = doc.ideas
    print("persona variants:")
    for v_ in doc.persona.variants:
        print("  -", v_)
    composer.choose_variant(doc.persona, doc.persona.variants[0])
    print("\nideas:")
    for idea in ideas:
        print("  *", idea.instruction)
        print("    ", idea.justification)
    if ideas:
        composer.feedback(ideas[0], kept=True)
        composer.feedback(ideas[1], kept=False)
    print("\ncompiled system prompt:\n", doc.system_prompt())

    print("\n== audit trail ==", len(audit), "entries")
    for e in audit.entries():
        print(f"  [{e.kind}] {e.actor}: {json.dumps(e.detail)[:110]}")

    print("\ninvariants (immutable):", INVARIANTS["safety_rules"])


if __name__ == "__main__":
    demo()
