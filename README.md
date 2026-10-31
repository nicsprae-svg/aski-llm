# aski-llm

A way to simulate rapid auto-skill evolution: an **interlinked, self-modifying skill system with hard limits**, plus a **Composer interface** that builds the model's starting instructions, creative persona, and semi-random inspiration on demand.

Pure Python 3.12 standard library — no dependencies.

## Concepts

### 1. Interlinked skill graph (`aski_llm/graph.py`)
- Each skill is a node with explicit `depends_on` / `triggers`.
- Skills call each other **only through a typed `Contract`** (input/output schemas).
- Every version is **immutable and semantically versioned**; `head` points to the active one; `revert_to()` gives instant rollback.

### 2. Bounded self-modification (`aski_llm/engine.py`, `invariants.py`)
The model can *propose* changes, classified by risk:

| Class | Examples | Behaviour |
|---|---|---|
| `low` | small prompt tweak, numeric param change | auto-apply + audit log (rate-limited) |
| `medium` | larger prompt rewrite, structural param change | dry-run + regression tests, applied as candidate pending approval |
| `high` | contract, dependencies, invariants, unknown fields | **blocked**, human escalation mandatory |

- Only fields in a skill's `mutable_fields` allow-list can change.
- System **invariants** (`INVARIANTS` in `invariants.py`) are immutable — even the model cannot touch them.
- Drift detection auto-rolls back if regression tests degrade after a change.

### 3. Scoped guidance channel (`aski_llm/guidance.py`)
Skills/model emit guidance with a **level** (`hint` / `recommendation` / `constraint`) and a **bounded scope** (`session` / `skill` / `graph`). Constraints are always intersected with the immutable invariants — a guidance can never weaken them. Everything is audited and rate-limited per session.

### 4. Composer interface (`aski_llm/composer.py`) — 3 panels
1. **Structured starting instruction**: schema-validated criteria (role, tone, language, format, constraints, resources) compiled into a versioned system prompt.
2. **Creative personality**: a free-text personality description interpreted into concrete observable traits, with variants to choose from.
3. **Semi-random idea generator**: samples 2–3 good practices from a domain-tagged, **weighted library** (`practices.py`) and composes varied instructions with a justification. Keep/reject feedback re-weights the practices so useful ones rise next time.

The Composer output is a versioned `ComposerDocument` whose `system_prompt()` can be injected as session-scope guidance into the skill graph.

## Usage

```bash
python -m aski_llm.cli        # end-to-end demo
python -m unittest discover -s tests -v   # test suite
```

```python
from aski_llm import SkillGraph, Contract, SelfModificationEngine, Composer

g = SkillGraph()
g.add_skill("editor", Contract("editor", {"code": "str"}, {"code": "str"}),
            handler=lambda p: {"code": p["code"]},
            mutable_fields=["prompt_template"], initial_prompt="Edit carefully.")

engine = SelfModificationEngine(g)
engine.propose("editor", "prompt_template", "Edit carefully and well.", "tweak")   # -> applied
engine.propose("editor", "depends_on", ["x"], "restructure")                        # -> blocked

composer = Composer(seed=42)
doc = composer.compose(criteria={"role": "pair-programmer", "tone": "direct"},
                       personality="un mentor sec mais bienveillant",
                       domain_tags=["code"], n_ideas=3)
print(doc.system_prompt())
```

## Layout

```
aski_llm/
  models.py      data models (Skill, Contract, Version, Guidance, ChangeProposal, Persona, AuditEntry)
  invariants.py  immutable invariants + mutable allow-list + change classification
  audit.py       append-only audit log (JSONL persistence supported)
  graph.py       skill graph: dependencies, contracts, versioning, rollback
  engine.py      bounded self-modification loop (dry-run, tests, rate-limit, drift rollback)
  guidance.py    scoped guidance channel
  practices.py   weighted good-practice library with feedback
  composer.py    the 3-panel Composer interface
  cli.py         demo
tests/test_aski_llm.py
```
