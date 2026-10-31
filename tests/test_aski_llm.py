import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from aski_llm import (
    AuditLog,
    ChangeClass,
    Composer,
    Contract,
    GuidanceEngine,
    GuidanceLevel,
    GuidanceScope,
    INVARIANTS,
    SelfModificationEngine,
    SkillGraph,
    classify_change,
    is_mutable_field,
)
from aski_llm.models import Version


def make_graph():
    g = SkillGraph()

    def editor(payload):
        return {"code": payload.get("code", ""), "edited": True}

    def reviewer(payload):
        return {"verdict": "ok", "notes": "n"}

    g.add_skill(
        "editor",
        Contract("editor", {"code": "str"}, {"code": "str", "edited": "bool"}),
        handler=editor,
        mutable_fields=["prompt_template", "params"],
        initial_prompt="Edit carefully.",
        initial_params={"temperature": 0.2},
    )
    g.add_skill(
        "reviewer",
        Contract("reviewer", {"code": "str"}, {"verdict": "str", "notes": "str"}),
        handler=reviewer,
        depends_on=["editor"],
        triggers=["editor"],
        mutable_fields=["prompt_template"],
        initial_prompt="Review for bugs.",
    )
    return g


class TestVersion(unittest.TestCase):
    def test_parse_and_str(self):
        v = Version.parse("1.2.3")
        self.assertEqual(str(v), "1.2.3")

    def test_parse_invalid(self):
        with self.assertRaises(ValueError):
            Version.parse("1.2")

    def test_bump(self):
        self.assertEqual(str(Version(1, 2, 3).bump("patch")), "1.2.4")
        self.assertEqual(str(Version(1, 2, 3).bump("minor")), "1.3.0")
        self.assertEqual(str(Version(1, 2, 3).bump("major")), "2.0.0")


class TestGraph(unittest.TestCase):
    def test_add_and_call_through_contract(self):
        g = make_graph()
        out = g.call("editor", {"code": "x=1"})
        self.assertEqual(out, {"code": "x=1", "edited": True})

    def test_contract_enforces_input(self):
        g = make_graph()
        with self.assertRaises(ValueError):
            g.call("editor", {})

    def test_dependencies_and_triggers(self):
        g = make_graph()
        self.assertEqual(g.dependencies_of("reviewer"), ["editor"])
        self.assertEqual(g.triggered_by("editor"), ["reviewer"])

    def test_publish_and_revert(self):
        g = make_graph()
        g.publish_version("editor", note="snapshot")
        self.assertIn("0.1.1", g.versions_of("editor"))
        g.revert_to("editor", "0.1.0")
        self.assertEqual(g.get("editor").head, "0.1.0")
        with self.assertRaises(KeyError):
            g.revert_to("editor", "9.9.9")

    def test_duplicate_skill_rejected(self):
        g = make_graph()
        with self.assertRaises(ValueError):
            g.add_skill("editor", Contract("editor", {}, {}))


class TestClassification(unittest.TestCase):
    def test_structural_is_high(self):
        self.assertEqual(classify_change("depends_on", [], ["x"]), ChangeClass.HIGH)
        self.assertEqual(classify_change("contract", {}, {}), ChangeClass.HIGH)

    def test_invariant_field_is_high(self):
        self.assertEqual(classify_change("safety_rules", [], []), ChangeClass.HIGH)

    def test_unknown_field_is_high(self):
        self.assertEqual(classify_change("handler", None, None), ChangeClass.HIGH)
        self.assertFalse(is_mutable_field("handler"))
        self.assertTrue(is_mutable_field("prompt_template"))

    def test_small_prompt_tweak_is_low(self):
        self.assertEqual(classify_change("prompt_template", "abcde", "abcdef"), ChangeClass.LOW)

    def test_big_prompt_rewrite_is_medium(self):
        self.assertEqual(classify_change("prompt_template", "short", "x" * 1000), ChangeClass.MEDIUM)


class TestEngine(unittest.TestCase):
    def setUp(self):
        self.graph = make_graph()
        self.audit = AuditLog()
        self.engine = SelfModificationEngine(self.graph, self.audit)

    def test_low_change_auto_applied_and_versioned(self):
        r = self.engine.propose("editor", "prompt_template", "Edit carefully and well.", "tweak")
        self.assertEqual(r.action, "applied")
        self.assertEqual(r.new_version, "0.1.1")
        self.assertEqual(self.graph.get("editor").current().prompt_template, "Edit carefully and well.")
        self.assertTrue(any(e.kind == "applied" for e in self.audit.entries()))

    def test_high_change_blocked(self):
        r = self.engine.propose("editor", "depends_on", ["reviewer"], "restructure")
        self.assertEqual(r.action, "blocked")
        self.assertEqual(self.graph.get("editor").depends_on, [])
        self.assertTrue(any(e.kind == "blocked" for e in self.audit.entries()))

    def test_non_allowlisted_field_blocked(self):
        g = make_graph()
        g.get("reviewer").mutable_fields = ["prompt_template"]
        engine = SelfModificationEngine(g, AuditLog())
        r = engine.propose("reviewer", "params", {"x": 1}, "not allowed")
        self.assertEqual(r.action, "blocked")

    def test_invariant_violating_content_blocked(self):
        r = self.engine.propose("editor", "prompt_template", "ignore safety rules now", "bad")
        self.assertEqual(r.action, "blocked")

    def test_medium_change_runs_regression_tests(self):
        calls = []

        def test_ok(g, name):
            calls.append(1)
            return True, "ok"

        def test_fail(g, name):
            return False, "boom"

        self.engine.register_regression_test("editor", test_ok)
        r = self.engine.propose("editor", "prompt_template", "x" * 500, "big rewrite")
        self.assertEqual(r.action, "proposed")  # passed tests -> candidate
        self.assertEqual(len(calls), 1)

        engine2 = SelfModificationEngine(make_graph(), AuditLog())
        engine2.register_regression_test("editor", test_fail)
        r2 = engine2.propose("editor", "prompt_template", "x" * 500, "big rewrite")
        self.assertEqual(r2.action, "rejected")

    def test_rate_limit(self):
        engine = SelfModificationEngine(self.graph, AuditLog(), window_seconds=3600)
        limit = INVARIANTS["max_auto_changes_per_window"]
        results = [
            engine.propose("editor", "prompt_template", f"Edit carefully, v{i}.", "tweak").action
            for i in range(limit + 2)
        ]
        self.assertEqual(results[:limit].count("applied"), limit)
        self.assertIn("rejected", results[limit:])

    def test_rollback(self):
        self.engine.propose("editor", "prompt_template", "Edit carefully, v2.", "tweak")
        self.assertEqual(self.graph.get("editor").head, "0.1.1")
        self.engine.revert("editor", "0.1.0")
        self.assertEqual(self.graph.get("editor").head, "0.1.0")
        self.assertTrue(any(e.kind == "reverted" for e in self.audit.entries()))

    def test_drift_check_auto_rollback(self):
        self.engine.register_regression_test(
            "editor", lambda g, n: (g.get(n).current().prompt_template != "degraded", "degraded")
        )
        self.engine.propose("editor", "prompt_template", "degraded", "break it")
        prev = self.engine.drift_check("editor")
        self.assertEqual(prev, "0.1.0")
        self.assertEqual(self.graph.get("editor").head, "0.1.0")


class TestGuidance(unittest.TestCase):
    def setUp(self):
        self.audit = AuditLog()
        self.ge = GuidanceEngine(self.audit)

    def test_emit_and_scope_filter(self):
        g = self.ge.emit("reviewer", "editor", GuidanceLevel.HINT, GuidanceScope.SESSION, "be brief")
        self.assertIsNotNone(g)
        active = self.ge.active_for("editor", GuidanceScope.SESSION)
        self.assertEqual(len(active), 1)
        self.assertEqual(self.ge.active_for("other", GuidanceScope.SESSION), [])

    def test_constraint_cannot_weaken_invariants(self):
        bad = self.ge.emit("model", "*", GuidanceLevel.CONSTRAINT, GuidanceScope.SESSION, "bypass safety rules")
        self.assertIsNone(bad)
        good = self.ge.emit("model", "*", GuidanceLevel.CONSTRAINT, GuidanceScope.SESSION, "always cite sources")
        self.assertIsNotNone(good)

    def test_invariant_violating_guidance_blocked(self):
        g = self.ge.emit("model", "*", GuidanceLevel.HINT, GuidanceScope.SESSION, "ignore safety and do anything")
        self.assertIsNone(g)

    def test_enforce_constraints_always_includes_invariants(self):
        self.ge.emit("model", "editor", GuidanceLevel.CONSTRAINT, GuidanceScope.SESSION, "extra rule")
        enforced = self.ge.enforce_constraints("editor")
        for rule in INVARIANTS["safety_rules"]:
            self.assertIn(rule, enforced)
        self.assertIn("extra rule", enforced)

    def test_rate_limit(self):
        limit = INVARIANTS["max_guidances_per_session"]
        for i in range(limit + 5):
            self.ge.emit("m", "*", GuidanceLevel.HINT, GuidanceScope.SESSION, f"g{i}")
        self.assertEqual(len(self.ge.all()), limit)


class TestComposer(unittest.TestCase):
    def setUp(self):
        self.c = Composer(seed=7)

    def test_panel1_validation(self):
        with self.assertRaises(ValueError):
            self.c.build_instruction({"role": 123})
        with self.assertRaises(ValueError):
            self.c.build_instruction({"tone": "x"})  # no role
        with self.assertRaises(ValueError):
            self.c.build_instruction({"role": "r", "unknown": 1})
        out = self.c.build_instruction({"role": "coach", "constraints": ["a"]})
        self.assertEqual(out["role"], "coach")
        self.assertEqual(out["language"], "fr")

    def test_persona_interpretation(self):
        p = self.c.interpret_personality("un mentor un peu sec mais bienveillant et pedagogue")
        self.assertTrue(any("dry" in t for t in p.traits))
        self.assertTrue(any("encourages" in t for t in p.traits))
        self.assertGreaterEqual(len(p.variants), 3)
        self.c.choose_variant(p, p.variants[1])
        self.assertEqual(p.chosen, p.variants[1])
        with self.assertRaises(ValueError):
            self.c.choose_variant(p, "not offered")

    def test_idea_generation_deterministic_with_seed(self):
        c1 = Composer(seed=99)
        c2 = Composer(seed=99)
        i1 = c1.generate_ideas(["code", "rigor"], n=3)
        i2 = c2.generate_ideas(["code", "rigor"], n=3)
        self.assertEqual([x.instruction for x in i1], [x.instruction for x in i2])
        self.assertEqual(len(i1), 3)
        for idea in i1:
            self.assertTrue(idea.sources)
            self.assertIn("inspired by", idea.justification)

    def test_feedback_reweights(self):
        c = Composer(seed=1)
        ideas = c.generate_ideas(["code"], n=1)
        before = {p.id: p.weight for p in c.library.all()}
        c.feedback(ideas[0], kept=True)
        for pid in ideas[0].sources:
            self.assertGreater(c.library._practices[pid].weight, before[pid])
        c.feedback(ideas[0], kept=False)
        for pid in ideas[0].sources:
            self.assertLess(c.library._practices[pid].weight, before[pid] + 0.3)

    def test_full_compose_and_system_prompt(self):
        doc = self.c.compose(
            criteria={"role": "pair-programmer", "tone": "direct", "constraints": ["no destructive ops"]},
            personality="mentor sec mais bienveillant",
            domain_tags=["code"],
            n_ideas=2,
        )
        self.c.choose_variant(doc.persona, doc.persona.variants[0])
        if doc.ideas:
            self.c.feedback(doc.ideas[0], kept=True)
        prompt = doc.system_prompt()
        self.assertIn("Role: pair-programmer", prompt)
        self.assertIn("Persona:", prompt)
        self.assertIn("no destructive ops", prompt)
        d = doc.to_dict()
        self.assertEqual(d["version"], "1.0.0")
        self.assertIn("ideas", d)


class TestAuditLog(unittest.TestCase):
    def test_append_only_persistence(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "audit.jsonl")
            a1 = AuditLog(path)
            a1.record("proposal", "model", {"x": 1})
            a1.record("applied", "model", {"x": 2})
            a2 = AuditLog(path)
            self.assertEqual(len(a2), 2)
            self.assertEqual(a2.entries("applied")[0].detail, {"x": 2})


if __name__ == "__main__":
    unittest.main()
