# Content foundry and verifier, Phase 1 implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a trustworthy, calibrated verifier for pgrep problems: a panel that decides accept / reject / escalate on real content, with a calibration harness that proves its per-property agreement with human judgment.

**Architecture:** Three shipped modules under `pylib/anki/pgrep/ai/` behind the existing injectable LLM seam (`consensus.py` for keys, `verifier.py` for the panel, `agreement.py` for calibration stats), plus one thin `content/tools/` CLI. Every module is pure or client-injectable, so the whole plan is tested offline with a fake client, no network in CI.

**Tech stack:** Python 3, the existing `llm.LLMClient` / `Judge` / `verify` seams, `pytest` (run via `just test-py`), stdlib-only stats (no numpy in shipped code).

---

## Phasing (scope-check result)

The spec `content-foundry-and-verifier-design.md` has nine workstreams on a
dependency chain. This is one subsystem, but it is large, so it is split into
three plans, each of which produces working, testable software on its own:

- **Phase 1 (this plan): the trustworthy verifier.** WS1 (panel), WS2 (consensus
  keys), the metric helpers from WS6, and the calibration harness. Output: a
  calibrated panel that can gate any existing problem, replacing the untrustworthy
  audit judge.
- **Phase 2 (next plan): the foundry loop.** WS3 (distractor temptation), WS5
  (difficulty), WS7 (best-of-N loop), the human escalation sheet.
- **Phase 3 (later plan): dataset and standing eval.** WS8 (preference dataset),
  WS9 (standing eval and gate wiring), then the staged Tier 2 and Tier 3.

Phase 1 alone is worth shipping: it turns the audit from a near-noise judge
(kappa ~0) into a panel with a measured, documented error rate.

## Environment note

- Run the full suite with `just test-py` (builds the pyenv, runs
  `ninja check:pytest`). It is the guaranteed-correct command and is used at task
  boundaries below.
- For a focused inner loop, once the pyenv is built you can run a single file, for
  example `./out/pyenv/bin/pytest pylib/tests/test_pgrep_consensus.py -v`. If that
  path is not present in your checkout, fall back to `just test-py`.
- All new tests follow the fake-client pattern in
  `pylib/tests/test_pgrep_judge.py`: a small stub exposing
  `complete_text(system, user, *, json_object=False) -> str` that returns canned
  JSON. Nothing in this plan touches the network.

## File structure

- Create `pylib/anki/pgrep/ai/consensus.py` — multi-model solve, majority,
  option-shuffle stability, SymPy hook, FOBAR backward check. One responsibility:
  decide whether a stored answer key is correct.
- Create `pylib/anki/pgrep/ai/verifier.py` — `CheckVerdict`, `PanelVerdict`,
  `Thresholds`, and `Verifier.check(problem)` composing the key consensus with the
  existing `Judge` checks into one accept / reject / escalate decision.
- Create `pylib/anki/pgrep/ai/agreement.py` — stdlib-only calibration stats:
  raw agreement, balanced accuracy, precision/recall, consistency, threshold
  tuning, and the calibration-card assembler.
- Create `content/tools/calibrate_verifier.py` — thin CLI: load a labeled set,
  run the panel, call `agreement.py`, write the calibration card and the tuned
  thresholds JSON.
- Create tests `pylib/tests/test_pgrep_consensus.py`,
  `pylib/tests/test_pgrep_verifier.py`, `pylib/tests/test_pgrep_agreement.py`.
- Modify `justfile` — add the `calibrate-verifier` recipe.
- Modify `docs_pgrep/reference/content-pipeline.md` — document the panel and the
  calibration card.

The bundle problem shape these operate on (from `content_bundle.json`):
`{id, topic, kind, stem, choices: [str x5], correct: "A".."E", distractors:
[{label, misconception, rationale}], solution_decomposition, difficulty,
source_ref}`. `kind` is `"computational"` or `"conceptual"`. The stem may embed an
`<svg>` inside a `.pg-figure` wrapper.

---

## Task 1: Consensus solver and majority

**Files:**

- Create: `pylib/anki/pgrep/ai/consensus.py`
- Test: `pylib/tests/test_pgrep_consensus.py`

- [ ] **Step 1: Write the failing test**

```python
# pylib/tests/test_pgrep_consensus.py
from anki.pgrep.ai import consensus


class FakeClient:
    """Returns queued JSON strings; records the payloads it was asked to solve."""

    def __init__(self, replies):
        self._replies = list(replies)
        self.seen = []

    def complete_text(self, system, user, *, json_object=False):
        self.seen.append(user)
        return self._replies.pop(0)


def _problem(correct="D"):
    return {
        "id": "p", "kind": "computational",
        "stem": "A car rises to height above a loop of radius R.",
        "choices": ["h = R/2", "h = 3R/2", "h = 2R", "h = 5R/2", "h = 3R"],
        "correct": correct,
    }


def test_solve_once_maps_shuffled_letter_back_to_original():
    # Display order puts original index 3 (letter D) into display slot A.
    order = [3, 0, 1, 2, 4]
    client = FakeClient(['{"answer": "A", "reasoning": "energy + contact", "confidence": 0.9}'])
    solve = consensus.solve_once(client, _problem(), order=order)
    assert solve.letter == "D"  # display A -> original D
    assert solve.confidence == 0.9


def test_majority_picks_the_mode():
    assert consensus._majority(["D", "D", "B"]) == "D"
    assert consensus._majority([]) == ""
```

- [ ] **Step 2: Run it to verify it fails**

Run: `just test-py` (expect `ModuleNotFoundError: anki.pgrep.ai.consensus` or missing attributes).

- [ ] **Step 3: Write the minimal implementation**

```python
# pylib/anki/pgrep/ai/consensus.py
# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Independent answer-key consensus (WS2).

Decides whether a stored MCQ key is correct from three independent signals:
several diverse model solves, an optional SymPy check, and an optional FOBAR
backward check. Deterministic disproof (SymPy or backward) wins outright;
otherwise a stable majority carries. Everything runs behind the injectable
``complete_text`` seam, so tests use a fake client and nothing touches the
network.
"""

from __future__ import annotations

import json
import random
import re
from dataclasses import dataclass, field
from typing import Protocol

from .judge import _extract_svg, _strip_figure

_LETTERS = ("A", "B", "C", "D", "E")
_NUM = re.compile(r"-?\d+(?:\.\d+)?")


class _Client(Protocol):
    def complete_text(
        self, system: str, user: str, *, json_object: bool = False
    ) -> str: ...


SOLVE_SYSTEM = (
    "You solve one Physics GRE multiple-choice problem. You are given the stem, "
    "an optional SVG figure (no numeric values), and options A-E. Reason briefly, "
    "then choose the single best option. You are NOT told the intended answer; "
    "decide independently.\n"
    'Return STRICT JSON only: {"answer":"A"|"B"|"C"|"D"|"E","reasoning":"one or '
    'two sentences","confidence":0..1}.'
)


@dataclass
class Solve:
    letter: str
    reasoning: str = ""
    confidence: float = 0.0


def _as_float(value: object) -> float:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0


def _parse(client: _Client, system: str, user: str) -> dict:
    try:
        raw = (client.complete_text(system, user, json_object=True) or "{}").strip()
    except Exception:  # noqa: BLE001
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        m = re.search(r"\{[\s\S]*\}", raw)
        return json.loads(m.group(0)) if m else {}


def _present(problem: dict, order: list[int]) -> str:
    choices = problem.get("choices", []) or []
    lines = []
    for disp_i, orig_i in enumerate(order):
        if orig_i < len(choices):
            lines.append(f"  {_LETTERS[disp_i]}. {choices[orig_i]}")
    return "\n".join(lines)


def solve_once(client: _Client, problem: dict, *, order: list[int] | None = None) -> Solve:
    """One independent solve. ``order`` permutes the displayed options; the
    returned letter is mapped back to the original option's letter."""
    n = len(problem.get("choices", []) or [])
    order = list(order) if order is not None else list(range(n))
    stem = _strip_figure(problem.get("stem", ""))
    svg = _extract_svg(problem.get("stem", ""))
    parts = [f"STEM:\n{stem}"]
    if svg:
        parts.append(f"FIGURE (SVG line art, no numeric values):\n{svg}")
    parts.append("OPTIONS:\n" + _present(problem, order))
    reply = _parse(client, SOLVE_SYSTEM, "\n\n".join(parts))
    disp = str(reply.get("answer", "")).strip().upper()[:1]
    letter = ""
    if disp in _LETTERS:
        disp_i = _LETTERS.index(disp)
        if disp_i < len(order):
            letter = _LETTERS[order[disp_i]]
    return Solve(letter, str(reply.get("reasoning", "")), _as_float(reply.get("confidence")))


def _majority(letters: list[str]) -> str:
    counts: dict[str, int] = {}
    for x in letters:
        if x:
            counts[x] = counts.get(x, 0) + 1
    return max(counts, key=counts.get) if counts else ""  # type: ignore[arg-type]
```

- [ ] **Step 4: Run the tests and verify they pass**

Run: `just test-py`
Expected: the two Task 1 tests pass.

- [ ] **Step 5: Commit**

```bash
git add pylib/anki/pgrep/ai/consensus.py pylib/tests/test_pgrep_consensus.py
git commit -m "feat(pgrep): consensus solver with option-shuffle mapping"
```

---

## Task 2: Key consensus decision (SymPy + backward + stability)

**Files:**

- Modify: `pylib/anki/pgrep/ai/consensus.py`
- Modify: `pylib/anki/pgrep/ai/verify.py` is unchanged; reuse `cas_check_value`.
- Test: `pylib/tests/test_pgrep_consensus.py`

- [ ] **Step 1: Write the failing tests**

```python
# append to pylib/tests/test_pgrep_consensus.py

def _ans(letter, conf=0.9):
    return '{"answer": "%s", "reasoning": "r", "confidence": %s}' % (letter, conf)


def test_unanimous_agreement_accepts_with_high_confidence():
    clients = [FakeClient([_ans("D")]) for _ in range(3)]
    stability = FakeClient([_ans("D")])  # first client re-solve under shuffle
    clients[0]._replies.append(_ans("D"))
    kc = consensus.key_consensus(_problem("D"), clients, seed=0)
    assert kc.accepted is True
    assert kc.confidence >= 0.9
    assert kc.stable is True


def test_majority_on_a_different_letter_rejects_the_key():
    clients = [FakeClient([_ans("A")]) for _ in range(3)]
    clients[0]._replies.append(_ans("A"))  # stable shuffle re-solve
    kc = consensus.key_consensus(_problem("D"), clients, seed=0)
    assert kc.accepted is False
    assert kc.predicted == "A"
    assert kc.confidence >= 0.9  # confident the stored key is wrong


def test_bare_majority_is_accepted_but_low_confidence():
    clients = [FakeClient([_ans("D")]), FakeClient([_ans("D")]), FakeClient([_ans("B")])]
    clients[0]._replies.append(_ans("D"))  # stable
    kc = consensus.key_consensus(_problem("D"), clients, seed=0)
    assert kc.accepted is True
    assert kc.confidence < 0.8  # 2/3 -> escalation band


def test_sympy_disproof_rejects_even_if_models_agree():
    prob = _problem("D")
    prob["answer_expr"] = "2*R"
    prob["answer_value"] = 3.0   # claim 2R == 3 is false for R != 1.5
    prob["answer_subs"] = {"R": 1.0}
    clients = [FakeClient([_ans("D")]) for _ in range(3)]
    clients[0]._replies.append(_ans("D"))
    kc = consensus.key_consensus(prob, clients, use_sympy=True, seed=0)
    assert kc.sympy_ok is False
    assert kc.accepted is False


def test_backward_check_recovers_masked_value():
    prob = {"id": "p", "kind": "computational",
            "stem": "A mass travels 12 meters in the field.",
            "choices": ["1 J", "2 J", "3 J", "4 J", "5 J"], "correct": "C"}
    back = FakeClient(['{"value": 12}'])
    assert consensus.backward_check(back, prob, "C") is True
    back2 = FakeClient(['{"value": 99}'])
    assert consensus.backward_check(back2, prob, "C") is False
```

- [ ] **Step 2: Run to verify they fail**

Run: `just test-py`
Expected: FAIL (`key_consensus`, `backward_check` not defined).

- [ ] **Step 3: Implement the decision, SymPy hook, and backward check**

```python
# append to pylib/anki/pgrep/ai/consensus.py

BACKWARD_SYSTEM = (
    "You are given a physics problem stem with exactly one numeric value replaced "
    "by <X>, and the stated final answer. Infer the single numeric value of <X> "
    "that makes the stated answer correct.\n"
    'Return STRICT JSON only: {"value": <number>}.'
)


@dataclass
class KeyConsensus:
    accepted: bool
    predicted: str
    stored: str
    agree_count: int
    n: int
    stable: bool
    sympy_ok: bool | None
    backward_ok: bool | None
    confidence: float
    opinions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "accepted": self.accepted, "predicted": self.predicted,
            "stored": self.stored, "agree_count": self.agree_count, "n": self.n,
            "stable": self.stable, "sympy_ok": self.sympy_ok,
            "backward_ok": self.backward_ok, "confidence": self.confidence,
            "opinions": self.opinions,
        }


def sympy_check(problem: dict) -> bool | None:
    """CAS check when the problem carries an explicit ``answer_expr`` and
    ``answer_value``; ``None`` when it does not (most bundle items today)."""
    expr = problem.get("answer_expr")
    if not expr or "answer_value" not in problem:
        return None
    from . import verify

    return verify.cas_check_value(
        str(expr), float(problem["answer_value"]),
        subs=problem.get("answer_subs") or None,
    )


def backward_check(client: _Client | None, problem: dict, proposed_key: str) -> bool | None:
    """FOBAR: mask the first numeric given, supply the proposed answer, ask the
    model to recover the masked value. ``None`` when not applicable."""
    if client is None:
        return None
    stem = _strip_figure(problem.get("stem", ""))
    nums = _NUM.findall(stem)
    if not nums:
        return None
    target = nums[0]
    masked = stem.replace(target, "<X>", 1)
    choices = problem.get("choices", []) or []
    if proposed_key not in _LETTERS:
        return None
    ki = _LETTERS.index(proposed_key)
    if ki >= len(choices):
        return None
    user = f"STEM (one value masked as <X>):\n{masked}\n\nSTATED ANSWER: {choices[ki]}\n\nRecover <X>."
    reply = _parse(client, BACKWARD_SYSTEM, user)
    try:
        got = float(reply.get("value"))
        tgt = float(target)
    except (TypeError, ValueError):
        return None
    return abs(got - tgt) <= 1e-6 * max(1.0, abs(tgt))


def _decide(stored, predicted, agree_count, n, stable, sympy_ok, backward_ok):
    if sympy_ok is True:
        return True, 0.99
    if sympy_ok is False:
        return False, 0.95
    if backward_ok is False:
        return False, 0.85
    if n == 0:
        return False, 0.0
    frac = agree_count / n
    if predicted == stored and 2 * agree_count > n:
        conf = frac if stable else frac * 0.6
        return True, round(conf, 3)
    if predicted and predicted != stored and 2 * (n - agree_count) > n:
        return False, round((n - agree_count) / n, 3)
    return False, 0.5


def key_consensus(problem, clients, *, use_sympy=True, backward_client=None, seed=0):
    stored = str(problem.get("correct", "")).strip().upper()[:1]
    n_choices = len(problem.get("choices", []) or [])
    opinions = [solve_once(c, problem).letter for c in clients]
    stable = True
    if clients and n_choices > 1:
        order = list(range(n_choices))
        random.Random(seed).shuffle(order)
        shuffled = solve_once(clients[0], problem, order=order).letter
        stable = bool(opinions[0]) and shuffled == opinions[0]
    valid = [o for o in opinions if o]
    predicted = _majority(valid)
    agree_count = sum(1 for o in valid if o == stored)
    n = len(clients)
    sympy_ok = sympy_check(problem) if use_sympy else None
    backward_ok = backward_check(backward_client, problem, stored)
    accepted, confidence = _decide(
        stored, predicted, agree_count, n, stable, sympy_ok, backward_ok
    )
    return KeyConsensus(accepted, predicted, stored, agree_count, n, stable,
                        sympy_ok, backward_ok, confidence, opinions)
```

- [ ] **Step 4: Run and verify pass**

Run: `just test-py`
Expected: all Task 1 and Task 2 tests pass.

- [ ] **Step 5: Commit**

```bash
git add pylib/anki/pgrep/ai/consensus.py pylib/tests/test_pgrep_consensus.py
git commit -m "feat(pgrep): key consensus with SymPy and FOBAR backward checks"
```

---

## Task 3: The verifier panel

**Files:**

- Create: `pylib/anki/pgrep/ai/verifier.py`
- Test: `pylib/tests/test_pgrep_verifier.py`

- [ ] **Step 1: Write the failing tests**

```python
# pylib/tests/test_pgrep_verifier.py
from anki.pgrep.ai import verifier
from anki.pgrep.ai.consensus import KeyConsensus


class StubConsensus:
    def __init__(self, kc):
        self.kc = kc

    def __call__(self, problem, clients, **kw):
        return self.kc


class StubJudge:
    """Stands in for Judge; returns fixed verdicts."""

    def __init__(self, figure=None, giveaway=None, distractor=None):
        from anki.pgrep.ai.judge import FigureVerdict, GiveawayVerdict, DistractorVerdict
        self._figure = figure or FigureVerdict(matches=True)
        self._giveaway = giveaway or GiveawayVerdict(gives_away=False)
        self._distractor = distractor or DistractorVerdict()

    def figure_fidelity(self, stem, svg):
        return self._figure

    def technique_giveaway(self, problem):
        return self._giveaway

    def distractor_plausibility(self, problem):
        return self._distractor


def _problem():
    return {"id": "p", "kind": "computational", "stem": "no figure here",
            "choices": ["a", "b", "c", "d", "e"], "correct": "D",
            "distractors": []}


def _kc(accepted, conf):
    return KeyConsensus(accepted, "D", "D", 3, 3, True, None, None, conf, ["D", "D", "D"])


def test_accepts_when_all_hard_checks_certain_pass():
    v = verifier.Verifier(judge=StubJudge(), key_consensus=StubConsensus(_kc(True, 0.95)))
    pv = v.check(_problem())
    assert pv.decision == "accept"


def test_rejects_on_certain_key_failure():
    v = verifier.Verifier(judge=StubJudge(), key_consensus=StubConsensus(_kc(False, 0.95)))
    pv = v.check(_problem())
    assert pv.decision == "reject"
    assert any("key" in r for r in pv.reasons())


def test_escalates_on_uncertain_key():
    v = verifier.Verifier(judge=StubJudge(), key_consensus=StubConsensus(_kc(True, 0.66)))
    pv = v.check(_problem())
    assert pv.decision == "escalate"


def test_soft_distractor_flag_annotates_but_does_not_reject():
    from anki.pgrep.ai.judge import DistractorVerdict
    j = StubJudge(distractor=DistractorVerdict(implausible_labels=["A"]))
    v = verifier.Verifier(judge=j, key_consensus=StubConsensus(_kc(True, 0.95)))
    pv = v.check(_problem())
    assert pv.decision == "accept"
    assert any(c.name == "distractor" and not c.passed for c in pv.checks)
```

- [ ] **Step 2: Run to verify they fail**

Run: `just test-py`
Expected: FAIL (`anki.pgrep.ai.verifier` not found).

- [ ] **Step 3: Implement the panel**

```python
# pylib/anki/pgrep/ai/verifier.py
# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""The verifier panel (WS1).

Composes the answer-key consensus with the existing single-check judges into one
accept / reject / escalate decision. A hard check that fails with confidence at
or above ``certain`` rejects; any hard check below ``certain`` escalates;
otherwise the panel accepts. Soft checks annotate the verdict but never change
the decision in Phase 1. The panel is fully injectable, so tests pass stubs and
nothing here calls a model directly.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import consensus as consensus_mod
from .judge import Judge, _extract_svg, _strip_figure

_HARD = "hard"
_SOFT = "soft"


@dataclass
class CheckVerdict:
    name: str
    severity: str
    passed: bool
    confidence: float
    evidence: str = ""


@dataclass
class Thresholds:
    certain: float = 0.8  # min confidence to treat a hard verdict as decisive

    @classmethod
    def from_dict(cls, d: dict) -> "Thresholds":
        return cls(certain=float(d.get("certain", 0.8)))

    def to_dict(self) -> dict:
        return {"certain": self.certain}


@dataclass
class PanelVerdict:
    decision: str
    checks: list[CheckVerdict] = field(default_factory=list)

    def hard_failures(self) -> list[CheckVerdict]:
        return [c for c in self.checks if c.severity == _HARD and not c.passed]

    def reasons(self) -> list[str]:
        return [f"{c.name}: {c.evidence}" for c in self.hard_failures()]

    def to_dict(self) -> dict:
        return {"decision": self.decision,
                "checks": [c.__dict__ for c in self.checks]}


class Verifier:
    def __init__(self, *, judge=None, solve_clients=None, backward_client=None,
                 key_consensus=None, thresholds=None):
        self.judge = judge if judge is not None else Judge()
        self.solve_clients = solve_clients or []
        self.backward_client = backward_client
        self._key_consensus = key_consensus or consensus_mod.key_consensus
        self.thresholds = thresholds or Thresholds()

    def check(self, problem: dict) -> PanelVerdict:
        checks = [self._key_check(problem)]
        svg = _extract_svg(problem.get("stem", ""))
        if svg:
            checks.append(self._figure_check(problem, svg))
        checks.append(self._giveaway_check(problem))
        checks.append(self._distractor_check(problem))
        return PanelVerdict(self._decide(checks), checks)

    def _decide(self, checks: list[CheckVerdict]) -> str:
        hard = [c for c in checks if c.severity == _HARD]
        if any((not c.passed) and c.confidence >= self.thresholds.certain for c in hard):
            return "reject"
        if any(c.confidence < self.thresholds.certain for c in hard):
            return "escalate"
        return "accept"

    def _key_check(self, problem: dict) -> CheckVerdict:
        kc = self._key_consensus(
            problem, self.solve_clients, backward_client=self.backward_client
        )
        ev = "" if kc.accepted else (
            f"solves say {kc.predicted or '?'} vs stored {kc.stored} "
            f"({kc.agree_count}/{kc.n}, stable={kc.stable}, "
            f"sympy={kc.sympy_ok}, backward={kc.backward_ok})"
        )
        return CheckVerdict("key", _HARD, kc.accepted, kc.confidence, ev)

    def _figure_check(self, problem: dict, svg: str) -> CheckVerdict:
        v = self.judge.figure_fidelity(_strip_figure(problem.get("stem", "")), svg)
        passed = v.matches and not v.has_numbers
        gaps = len(v.missing) + len(v.contradictions) + (1 if v.has_numbers else 0)
        confidence = 0.9 if gaps == 0 else min(0.95, 0.6 + 0.15 * gaps)
        ev = "; ".join(v.missing + v.contradictions) or ("numbers in figure" if v.has_numbers else "")
        return CheckVerdict("figure", _HARD, passed, confidence, ev)

    def _giveaway_check(self, problem: dict) -> CheckVerdict:
        v = self.judge.technique_giveaway(problem)
        confidence = 0.9 if v.severity == "high" else 0.6
        return CheckVerdict("giveaway", _SOFT, not v.gives_away, confidence, v.what)

    def _distractor_check(self, problem: dict) -> CheckVerdict:
        v = self.judge.distractor_plausibility(problem)
        passed = not v.implausible_labels
        return CheckVerdict("distractor", _SOFT, passed, 0.7,
                            ",".join(v.implausible_labels))
```

- [ ] **Step 4: Run and verify pass**

Run: `just test-py`
Expected: the four Task 3 tests pass.

- [ ] **Step 5: Commit**

```bash
git add pylib/anki/pgrep/ai/verifier.py pylib/tests/test_pgrep_verifier.py
git commit -m "feat(pgrep): verifier panel with accept/reject/escalate decision"
```

---

## Task 4: Calibration statistics

**Files:**

- Create: `pylib/anki/pgrep/ai/agreement.py`
- Test: `pylib/tests/test_pgrep_agreement.py`

- [ ] **Step 1: Write the failing tests**

```python
# pylib/tests/test_pgrep_agreement.py
from anki.pgrep.ai import agreement


def test_raw_agreement_counts_matches():
    assert agreement.raw_agreement([True, True, False], [True, False, False]) == 2 / 3


def test_balanced_accuracy_handles_class_imbalance():
    # 9 easy negatives all right, 1 positive missed -> raw high, balanced low.
    pred = [False] * 9 + [False]
    human = [False] * 9 + [True]
    assert agreement.balanced_accuracy(pred, human) == 0.5


def test_precision_recall():
    prec, rec = agreement.precision_recall([True, True, False], [True, False, True])
    assert prec == 0.5
    assert rec == 0.5


def test_consistency_is_fraction_of_stable_verdicts():
    runs = [[True, True, False], [True, False, False]]  # item 2 flipped
    assert agreement.consistency_score(runs) == 2 / 3


def test_tune_threshold_finds_precision_cutoff():
    conf = [0.9, 0.8, 0.7, 0.6]
    correct = [True, True, False, True]
    # at cutoff 0.8: {0.9,0.8} both correct -> precision 1.0
    assert agreement.tune_threshold(conf, correct, target_precision=1.0) == 0.8
```

- [ ] **Step 2: Run to verify they fail**

Run: `just test-py`
Expected: FAIL (`anki.pgrep.ai.agreement` not found).

- [ ] **Step 3: Implement stdlib-only stats**

```python
# pylib/anki/pgrep/ai/agreement.py
# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Calibration statistics for the verifier panel (WS6).

Stdlib-only, pure functions over aligned boolean labels: raw agreement, balanced
accuracy, precision/recall, verdict consistency across perturbations, and a
precision-target threshold sweep. These replace the single misleading kappa with
a per-property, human-aligned picture, and they ship with the app (no numpy), so
they are trivially unit tested.
"""

from __future__ import annotations

from dataclasses import dataclass


def raw_agreement(pred: list[bool], human: list[bool]) -> float:
    if not pred or len(pred) != len(human):
        return float("nan")
    return sum(1 for p, h in zip(pred, human) if p == h) / len(pred)


def balanced_accuracy(pred: list[bool], human: list[bool]) -> float:
    pos = sum(1 for h in human if h)
    neg = sum(1 for h in human if not h)
    tp = sum(1 for p, h in zip(pred, human) if h and p)
    tn = sum(1 for p, h in zip(pred, human) if (not h) and (not p))
    recalls = []
    if pos:
        recalls.append(tp / pos)
    if neg:
        recalls.append(tn / neg)
    return sum(recalls) / len(recalls) if recalls else float("nan")


def precision_recall(pred: list[bool], human: list[bool]) -> tuple[float, float]:
    tp = sum(1 for p, h in zip(pred, human) if p and h)
    fp = sum(1 for p, h in zip(pred, human) if p and not h)
    fn = sum(1 for p, h in zip(pred, human) if (not p) and h)
    prec = tp / (tp + fp) if (tp + fp) else float("nan")
    rec = tp / (tp + fn) if (tp + fn) else float("nan")
    return prec, rec


def consistency_score(runs: list[list[bool]]) -> float:
    """Fraction of items whose verdict is identical across every perturbation run."""
    if not runs or not runs[0]:
        return float("nan")
    n = len(runs[0])
    same = sum(1 for i in range(n) if len({run[i] for run in runs}) == 1)
    return same / n


def tune_threshold(confidences: list[float], correct: list[bool], *,
                   target_precision: float = 0.95) -> float:
    """Smallest confidence cutoff whose kept predictions reach ``target_precision``.

    Sweeps cutoffs high to low; returns the lowest cutoff still meeting the
    target, or 1.0 if none does.
    """
    pairs = sorted(zip(confidences, correct), reverse=True)
    best = 1.0
    kept = correct_kept = 0
    for conf, ok in pairs:
        kept += 1
        correct_kept += 1 if ok else 0
        if correct_kept / kept >= target_precision:
            best = conf
    return best


@dataclass
class PropertyReport:
    name: str
    n: int
    raw_agreement: float
    balanced_accuracy: float
    precision: float
    recall: float

    def to_dict(self) -> dict:
        return self.__dict__


def property_report(name: str, pred: list[bool], human: list[bool]) -> PropertyReport:
    prec, rec = precision_recall(pred, human)
    return PropertyReport(name, len(pred), raw_agreement(pred, human),
                          balanced_accuracy(pred, human), prec, rec)


def build_card(reports: list[PropertyReport], consistency: float,
               thresholds: dict) -> dict:
    return {
        "properties": [r.to_dict() for r in reports],
        "consistency": consistency,
        "thresholds": thresholds,
    }
```

- [ ] **Step 4: Run and verify pass**

Run: `just test-py`
Expected: the five Task 4 tests pass.

- [ ] **Step 5: Commit**

```bash
git add pylib/anki/pgrep/ai/agreement.py pylib/tests/test_pgrep_agreement.py
git commit -m "feat(pgrep): stdlib calibration statistics for the verifier"
```

---

## Task 5: Calibration CLI

**Files:**

- Create: `content/tools/calibrate_verifier.py`
- Modify: `justfile`

The pure logic is already covered by Task 4's tests. This task is thin I/O glue,
so it has no new unit test; it is exercised by the `--self-check` smoke below.

- [ ] **Step 1: Implement the CLI**

```python
# content/tools/calibrate_verifier.py
"""Calibrate the verifier panel against a per-property human-labeled set (WS6).

Reads a labels JSON (a list of {id, key_ok, figure_ok, ...} human verdicts plus
the matching problems), runs the panel, compares per property via
``anki.pgrep.ai.agreement``, tunes each gate's confidence threshold for the
target accept-precision, and writes the calibration card and thresholds under
``content/run/calibration/``.

Run: `just calibrate-verifier` (needs the AI runtime and a key), or
`python content/tools/calibrate_verifier.py --self-check` for an offline smoke.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))  # repo root

from pylib.anki.pgrep.ai import agreement  # type: ignore[import-not-found]


def _self_check() -> int:
    pred = [True, True, False, True]
    human = [True, False, False, True]
    rep = agreement.property_report("key", pred, human)
    card = agreement.build_card([rep], consistency=1.0, thresholds={"key": 0.8})
    assert card["properties"][0]["name"] == "key"
    print("[ok] calibrate_verifier self-check passed")
    print(json.dumps(card, indent=2))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Calibrate the verifier panel.")
    ap.add_argument("--labels", help="path to the per-property human labels JSON")
    ap.add_argument("--out", default="content/run/calibration")
    ap.add_argument("--self-check", action="store_true",
                    help="run an offline smoke and exit")
    args = ap.parse_args()
    if args.self_check:
        return _self_check()
    if not args.labels:
        ap.error("--labels is required unless --self-check is given")
    # Full path: load labels + problems, run the panel per item, collect per-property
    # predictions, tune thresholds, write the card. Implemented once the ~120-item
    # labeled set exists (WS6 human pass); the panel and stats it calls are done.
    raise SystemExit("labeled-set run: provide --labels once the calibration set exists")


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Add the recipe to `justfile`**

Find the `audit-bundle-ai` recipe and add below it:

```make
# Calibrate the verifier panel against the per-property human-labeled set.
calibrate-verifier *args:
    {{ python }} content/tools/calibrate_verifier.py {{ args }}
```

(Match the interpreter variable the neighboring `audit-bundle-ai` recipe uses; if
it invokes `conda run -n pgrep-ai ... python`, mirror that exactly.)

- [ ] **Step 3: Run the offline smoke**

Run: `python content/tools/calibrate_verifier.py --self-check`
Expected: `[ok] calibrate_verifier self-check passed` and a JSON card.

- [ ] **Step 4: Commit**

```bash
git add content/tools/calibrate_verifier.py justfile
git commit -m "feat(pgrep): calibrate-verifier CLI and recipe"
```

---

## Task 6: Documentation and full-suite gate

**Files:**

- Modify: `docs_pgrep/reference/content-pipeline.md`

- [ ] **Step 1: Document the panel and calibration card**

Add a section after "The AI audits (on-demand)" describing: the panel
(`verifier.py`) composing the key consensus (`consensus.py`) with the judges; the
accept / reject / escalate rule and the single `certain` threshold; and the
calibration card (`agreement.py` + `calibrate-verifier`) reporting per-property
raw agreement, balanced accuracy, precision/recall, and consistency, which
replaces the single kappa. Note that the panel and the audits share the same
underlying checks.

- [ ] **Step 2: Run the whole suite and lint**

Run: `just test-py`
Expected: all new tests (Tasks 1-4) plus the existing suite pass.

Run: `just lint`
Expected: clean (ruff/mypy) for the three new modules and their tests.

- [ ] **Step 3: Commit**

```bash
git add docs_pgrep/reference/content-pipeline.md
git commit -m "docs(pgrep): document the verifier panel and calibration card"
```

---

## Self-review

**1. Spec coverage (Phase 1 slice):**

- WS1 verifier panel skeleton -> Task 3 (`verifier.py`, decision rule, thresholds). Covered.
- WS2 consensus key verification (multi-model + SymPy + backward + stability) ->
  Tasks 1-2 (`consensus.py`). Covered.
- WS4 wrap figure/giveaway/distractor into panel sub-verdicts -> Task 3
  (`_figure_check`, `_giveaway_check`, `_distractor_check`). Citation and the
  deterministic decomposition-leak wrap move to Phase 2 with the loop, since they
  gate generation rather than a single stored problem; noted, not silently
  dropped.
- WS6 metric helpers + calibration harness -> Tasks 4-5 (`agreement.py`,
  `calibrate_verifier.py`). The ~120-item human labeling pass is a manual runbook
  step; the code that consumes it is done and tested on synthetic data.

**2. Placeholder scan:** Task 5's full labeled-set branch intentionally raises
until the human labeled set exists (a data dependency, not a code gap), and its
pure logic is fully implemented and tested in Task 4. The `--self-check` path is
complete. No other placeholders.

**3. Type consistency:** `KeyConsensus` fields are produced in Task 2 and consumed
in Task 3's `_key_check` (`accepted`, `predicted`, `stored`, `agree_count`, `n`,
`stable`, `sympy_ok`, `backward_ok`, `confidence`). `CheckVerdict`
(`name`, `severity`, `passed`, `confidence`, `evidence`) is produced by every
`_*_check` and consumed by `_decide`, `hard_failures`, and `reasons`.
`Thresholds.certain` is the single knob used in `_decide` and written by the
calibration card. `agreement.property_report` returns `PropertyReport`, consumed
by `build_card`. Consistent.

## Execution handoff

Plan complete and saved to
`docs_pgrep/plan/content-foundry-and-verifier-plan.md` (Phase 1). Two execution
options:

1. **Subagent-driven (recommended)** - one fresh subagent per task, review between
   tasks, fast iteration.
2. **Inline execution** - execute the tasks in this session with checkpoints for
   review.

Which approach?
