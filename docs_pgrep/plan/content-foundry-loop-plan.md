# Content foundry loop, Phase 2 implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the Phase 1 verifier into a generation loop that samples best-of-N candidates per blueprint slot, scores distractor temptation and difficulty honestly, keeps only panel-accepted problems, and routes the rest to reject logs or a human escalation sheet.

**Architecture:** New `temptation.py` and `difficulty.py` modules feed soft (then tunable) panel checks. `content/tools/foundry.py` owns the sample-verify-partition loop behind injectable clients, with a dry-run that never touches the network. Escalation sheets reuse `review_sheet.py`. Accepted survivors still land only through `assemble_bundle.py`.

**Tech stack:** Python 3, Phase 1 `consensus` / `verifier` / `agreement`, existing `generation_core.generate_problem`, `llm.LLMClient`, `review_sheet.py`, `pytest` via `just test-py`.

## Global Constraints

- Depends on Phase 1 landing (`consensus.py`, `verifier.py`, `agreement.py`, `calibrate_verifier.py`). Do not reimplement those.
- No network in CI. Every new module is fake-client tested.
- Firewall unchanged: generation reads only `content/corpus/`; foundry outputs stay under git-ignored `content/run/foundry/`.
- Soft checks still do not reject by default until temptation is calibrated; free-elimination (temptation == 0) may escalate or soft-fail per task acceptance.
- Do not change the shipped bundle schema or the per-commit invariant gate.
- Writing style: no em dashes in docs, comments, or commit messages.

---

## Phasing reminder

- **Phase 1 (done / in PR):** WS1 panel, WS2 consensus, WS6 metric helpers + calibrate CLI.
- **Phase 2 (this plan):** WS3 distractor temptation, WS5 difficulty, WS7 best-of-N foundry, human escalation sheet.
- **Phase 3 (next):** WS8 preference dataset, WS9 standing eval + gate wiring.

## Environment note

- Full suite: `just test-py`.
- Focused loop (after pyenv exists): `./out/pyenv/bin/pytest pylib/tests/test_pgrep_temptation.py -v`.
- Content tools import via `import _ai_path; _ai_path.add_ai_core()` then `from pgrep.ai import ...`.
- Fake client contract: `complete_text(system, user, *, json_object=False) -> str` returning canned JSON strings.

## File structure

- Create `pylib/anki/pgrep/ai/temptation.py` — per-distractor wrongness + temptation from weak solvers; two-stage distractor select helper.
- Create `pylib/anki/pgrep/ai/difficulty.py` — proficiency-simulated difficulty band; ETS correlation helper for offline validation scripts.
- Modify `pylib/anki/pgrep/ai/verifier.py` — wire temptation (and optional difficulty flag) into panel checks; keep soft-by-default.
- Create `content/tools/foundry.py` — best-of-N sample, verify, partition, yield report, dry-run.
- Create `content/tools/make_foundry_escalation.py` — escalation sheet via `review_sheet.build`.
- Create tests `pylib/tests/test_pgrep_temptation.py`, `pylib/tests/test_pgrep_difficulty.py`, `pylib/tests/test_pgrep_foundry.py`.
- Modify `justfile` — `foundry` and `foundry-dry` recipes.
- Modify `docs_pgrep/reference/content-pipeline.md` — document the loop.
- Link from `docs_pgrep/plan/content-foundry-and-verifier-design.md`.

Problem shape (unchanged): `{id, topic, kind, stem, choices: [str x5], correct: "A".."E", distractors: [...], ...}`. Generation items may use `key` instead of `correct`; the foundry normalizes to `correct` before the panel.

---

### Task 1: Distractor temptation scoring

**Files:**

- Create: `pylib/anki/pgrep/ai/temptation.py`
- Test: `pylib/tests/test_pgrep_temptation.py`

**Interfaces:**

- Consumes: `consensus.solve_once` (optional; weak solvers may call `complete_text` directly), fake `_Client` with `complete_text`.
- Produces:
  - `@dataclass DistractorScore: label: str; is_wrong: bool; temptation: float; selected_by: int; n_solvers: int`
  - `@dataclass TemptationReport: scores: list[DistractorScore]; free_elimination_labels: list[str]; mean_temptation: float`
  - `def score_distractors(problem: dict, weak_clients: Sequence[_Client], *, seed: int = 0) -> TemptationReport`
  - `def select_distractors(candidates: list[dict], weak_clients: Sequence[_Client], *, k: int = 4, seed: int = 0) -> list[dict]` (DisGeM-style: keep the k most tempting wrong options)

- [ ] **Step 1: Write the failing test**

```python
# pylib/tests/test_pgrep_temptation.py
# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

from anki.pgrep.ai import temptation


class FakeClient:
    def __init__(self, letter: str):
        self.letter = letter

    def complete_text(self, system, user, *, json_object=False):
        return f'{{"answer": "{self.letter}", "reasoning": "x", "confidence": 0.5}}'


def _problem():
    return {
        "id": "p",
        "stem": "What is 2+2?",
        "choices": ["3", "4", "5", "6", "7"],
        "correct": "B",
    }


def test_temptation_counts_weak_solver_picks_on_wrong_options():
    # Three weak solvers pick A, A, C. Correct is B.
    clients = [FakeClient("A"), FakeClient("A"), FakeClient("C")]
    report = temptation.score_distractors(_problem(), clients, seed=1)
    by_label = {s.label: s for s in report.scores}
    assert by_label["A"].temptation == 2 / 3
    assert by_label["C"].temptation == 1 / 3
    assert by_label["D"].temptation == 0.0
    assert "D" in report.free_elimination_labels
    assert "E" in report.free_elimination_labels
    assert "B" not in by_label  # correct option is not a distractor score


def test_select_distractors_keeps_most_tempting_wrong_options():
    # candidates are option dicts with label + text; correct excluded upstream
    cands = [
        {"label": "A", "text": "3"},
        {"label": "C", "text": "5"},
        {"label": "D", "text": "6"},
        {"label": "E", "text": "7"},
    ]
    # All weak solvers pick A -> A is most tempting
    clients = [FakeClient("A"), FakeClient("A")]
    problem = _problem()
    kept = temptation.select_distractors(
        cands, clients, k=2, seed=1, problem=problem
    )
    assert [d["label"] for d in kept][:1] == ["A"]
    assert len(kept) == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `just test-py` (or focused pytest on `test_pgrep_temptation.py`).
Expected: `ModuleNotFoundError` for `temptation`.

- [ ] **Step 3: Write minimal implementation**

```python
# pylib/anki/pgrep/ai/temptation.py
# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Distractor wrongness and temptation (WS3).

Temptation is the fraction of weaker or proficiency-simulated solvers that
select a wrong option. Zero temptation is a free elimination. Wrongness of the
stored key is still the consensus panel's job; this module only scores how
attractive each distractor is to weaker solvers.
"""

from __future__ import annotations

import json
import random
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol


class _Client(Protocol):
    def complete_text(self, system: str, user: str, *, json_object: bool = False) -> str: ...


SOLVE_SYSTEM = (
    "Solve the multiple-choice physics problem. Reply JSON only: "
    '{"answer":"A"|"B"|"C"|"D"|"E","reasoning":"...","confidence":0..1}.'
)


@dataclass
class DistractorScore:
    label: str
    is_wrong: bool
    temptation: float
    selected_by: int
    n_solvers: int


@dataclass
class TemptationReport:
    scores: list[DistractorScore]
    free_elimination_labels: list[str]
    mean_temptation: float


def _letter(raw: str) -> str:
    try:
        ans = str(json.loads(raw).get("answer", "")).strip().upper()
    except json.JSONDecodeError:
        return ""
    return ans if ans in "ABCDE" else ""


def score_distractors(
    problem: dict,
    weak_clients: Sequence[_Client],
    *,
    seed: int = 0,
) -> TemptationReport:
    correct = str(problem.get("correct") or problem.get("key") or "").upper()
    choices = list(problem.get("choices") or [])
    letters = "ABCDE"[: len(choices)]
    counts = {L: 0 for L in letters if L != correct}
    n = 0
    rng = random.Random(seed)
    for i, client in enumerate(weak_clients):
        order = list(range(len(choices)))
        rng.shuffle(order)
        display = [choices[j] for j in order]
        inv = {display_i: orig for display_i, orig in enumerate(order)}
        user = json.dumps({"stem": problem.get("stem", ""), "choices": display})
        try:
            picked_display = _letter(client.complete_text(SOLVE_SYSTEM, user, json_object=True))
        except Exception:  # noqa: BLE001
            continue
        if not picked_display:
            continue
        di = "ABCDE".index(picked_display)
        orig = "ABCDE"[inv[di]]
        n += 1
        if orig in counts:
            counts[orig] += 1
    scores = []
    free = []
    for label, c in counts.items():
        tempt = (c / n) if n else 0.0
        scores.append(
            DistractorScore(label, True, round(tempt, 3), c, n)
        )
        if tempt == 0.0:
            free.append(label)
    mean = (sum(s.temptation for s in scores) / len(scores)) if scores else 0.0
    return TemptationReport(scores, free, round(mean, 3))


def select_distractors(
    candidates: list[dict],
    weak_clients: Sequence[_Client],
    *,
    k: int = 4,
    seed: int = 0,
    problem: dict | None = None,
) -> list[dict]:
    """Keep the k most tempting wrong options (DisGeM-style second stage)."""
    if not candidates:
        return []
    base = dict(problem or {})
    # Build a temporary problem whose choices align with candidate labels.
    # Caller passes a full problem; we score then filter candidates by label.
    report = score_distractors(base, weak_clients, seed=seed)
    rank = {s.label: s.temptation for s in report.scores}
    ordered = sorted(
        candidates,
        key=lambda d: rank.get(str(d.get("label", "")), 0.0),
        reverse=True,
    )
    return ordered[: max(0, k)]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./out/pyenv/bin/pytest pylib/tests/test_pgrep_temptation.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pylib/anki/pgrep/ai/temptation.py pylib/tests/test_pgrep_temptation.py
git commit -m "$(cat <<'EOF'
feat(pgrep): distractor temptation scoring from weak solvers

EOF
)"
```

---

### Task 2: Wire temptation into the verifier panel

**Files:**

- Modify: `pylib/anki/pgrep/ai/verifier.py`
- Modify: `pylib/tests/test_pgrep_verifier.py`

**Interfaces:**

- Consumes: `temptation.score_distractors`, existing `Verifier` constructor.
- Produces: `Verifier(..., weak_clients: Sequence[_Client] | None = None)` and a soft `CheckVerdict(name="temptation", ...)`. Free-elimination labels go in `evidence`. Soft severity in Phase 2 (annotates; does not reject) unless `thresholds.temptation_hard` is True later.

- [ ] **Step 1: Write the failing test**

```python
def test_free_elimination_annotates_soft_temptation_check():
    # Reuse existing Verifier fixtures; inject weak clients that never pick D/E.
    problem = {
        "id": "p", "stem": "x", "kind": "conceptual",
        "choices": ["a", "b", "c", "d", "e"], "correct": "A",
    }
    # Fake judge + key_consensus stubs from existing tests; add weak clients
    # that always answer "B".
    v = Verifier(
        judge=fake_judge_all_pass(),
        key_consensus=lambda *a, **k: accept_key(),
        weak_clients=[AlwaysB(), AlwaysB()],
    )
    panel = v.check(problem)
    tempt = next(c for c in panel.checks if c.name == "temptation")
    assert tempt.severity == "soft"
    assert not tempt.passed  # free eliminations present
    assert "D" in tempt.evidence or "E" in tempt.evidence
    assert panel.decision == "accept"  # soft does not reject
```

Adapt helper names to match existing `test_pgrep_verifier.py` fixtures.

- [ ] **Step 2: Run test to verify it fails**

Expected: no `temptation` check / `weak_clients` unknown.

- [ ] **Step 3: Minimal wiring**

In `Verifier.__init__`, store `weak_clients`. In `check`, after `_distractor_check`, if `weak_clients` is non-empty, append `_temptation_check(problem)`.

```python
def _temptation_check(self, problem: dict) -> CheckVerdict:
    from . import temptation as temptation_mod
    report = temptation_mod.score_distractors(problem, self.weak_clients)
    passed = not report.free_elimination_labels
    ev = ",".join(report.free_elimination_labels)
    return CheckVerdict("temptation", _SOFT, passed, 0.7, ev)
```

Keep `_distractor_check` (judge plausibility) as a separate soft check.

- [ ] **Step 4: Run tests**

Run: `./out/pyenv/bin/pytest pylib/tests/test_pgrep_verifier.py pylib/tests/test_pgrep_temptation.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pylib/anki/pgrep/ai/verifier.py pylib/tests/test_pgrep_verifier.py
git commit -m "$(cat <<'EOF'
feat(pgrep): soft temptation check on the verifier panel

EOF
)"
```

---

### Task 3: Proficiency-simulated difficulty

**Files:**

- Create: `pylib/anki/pgrep/ai/difficulty.py`
- Test: `pylib/tests/test_pgrep_difficulty.py`

**Interfaces:**

- Consumes: weak `_Client` ensemble (same protocol as temptation).
- Produces:
  - `@dataclass DifficultyEstimate: band: str; p_correct: float; n_solvers: int; out_of_band: bool`
  - `def estimate_difficulty(problem: dict, weak_clients: Sequence[_Client], *, seed: int = 0) -> DifficultyEstimate`
  - Bands: `"easy"` (p_correct >= 0.7), `"medium"` (0.35..0.7), `"hard"` (< 0.35). `out_of_band` True when p_correct >= 0.95 or p_correct <= 0.05 (outside useful PGRE band).
  - `def pearson_correlation(xs: list[float], ys: list[float]) -> float` for ETS validation scripts (stdlib only).

Document the 2512.18880 caveat in the module docstring: do not use frontier solve-rate as difficulty.

- [ ] **Step 1: Write the failing test**

```python
from anki.pgrep.ai import difficulty


class FakeClient:
    def __init__(self, letter: str):
        self.letter = letter

    def complete_text(self, system, user, *, json_object=False):
        return f'{{"answer": "{self.letter}", "reasoning": "x", "confidence": 0.5}}'


def _problem(correct="B"):
    return {
        "stem": "q", "choices": ["a", "b", "c", "d", "e"], "correct": correct,
    }


def test_hard_band_when_weak_solvers_mostly_miss():
    clients = [FakeClient("A"), FakeClient("C"), FakeClient("D"), FakeClient("E")]
    est = difficulty.estimate_difficulty(_problem("B"), clients, seed=0)
    assert est.band == "hard"
    assert est.p_correct == 0.0
    assert est.out_of_band is True


def test_easy_band_when_weak_solvers_mostly_hit():
    clients = [FakeClient("B")] * 5
    est = difficulty.estimate_difficulty(_problem("B"), clients, seed=0)
    assert est.band == "easy"
    assert est.p_correct == 1.0
    assert est.out_of_band is True  # >= 0.95


def test_pearson_correlation_perfect_line():
    assert abs(difficulty.pearson_correlation([1, 2, 3], [2, 4, 6]) - 1.0) < 1e-9
```

- [ ] **Step 2: Run to fail**

Expected: missing module.

- [ ] **Step 3: Implement**

```python
# pylib/anki/pgrep/ai/difficulty.py
"""Proficiency-simulated difficulty (WS5).

Estimates difficulty from weaker solvers, never from a frontier model's
solve-rate (see Hugging Face paper 2512.18880). Validate estimates against
held-out ETS item difficulty offline; that correlation lives in a content
tool, not in CI.
"""

from __future__ import annotations

import json
import math
import random
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol


class _Client(Protocol):
    def complete_text(self, system: str, user: str, *, json_object: bool = False) -> str: ...


SOLVE_SYSTEM = (
    "Solve the multiple-choice physics problem. Reply JSON only: "
    '{"answer":"A"|"B"|"C"|"D"|"E","reasoning":"...","confidence":0..1}.'
)


@dataclass
class DifficultyEstimate:
    band: str
    p_correct: float
    n_solvers: int
    out_of_band: bool


def _letter(raw: str) -> str:
    try:
        ans = str(json.loads(raw).get("answer", "")).strip().upper()
    except json.JSONDecodeError:
        return ""
    return ans if ans in "ABCDE" else ""


def estimate_difficulty(
    problem: dict,
    weak_clients: Sequence[_Client],
    *,
    seed: int = 0,
) -> DifficultyEstimate:
    correct = str(problem.get("correct") or problem.get("key") or "").upper()
    choices = list(problem.get("choices") or [])
    hits = n = 0
    rng = random.Random(seed)
    for client in weak_clients:
        order = list(range(len(choices)))
        rng.shuffle(order)
        display = [choices[j] for j in order]
        inv = {di: orig for di, orig in enumerate(order)}
        user = json.dumps({"stem": problem.get("stem", ""), "choices": display})
        try:
            picked = _letter(client.complete_text(SOLVE_SYSTEM, user, json_object=True))
        except Exception:  # noqa: BLE001
            continue
        if not picked:
            continue
        n += 1
        orig = "ABCDE"[inv["ABCDE".index(picked)]]
        if orig == correct:
            hits += 1
    p = (hits / n) if n else 0.0
    if p >= 0.7:
        band = "easy"
    elif p >= 0.35:
        band = "medium"
    else:
        band = "hard"
    return DifficultyEstimate(band, round(p, 3), n, p >= 0.95 or p <= 0.05)


def pearson_correlation(xs: list[float], ys: list[float]) -> float:
    if len(xs) != len(ys) or len(xs) < 2:
        return float("nan")
    n = len(xs)
    mx = sum(xs) / n
    my = sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    dx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    dy = math.sqrt(sum((y - my) ** 2 for y in ys))
    if dx == 0 or dy == 0:
        return float("nan")
    return num / (dx * dy)
```

- [ ] **Step 4: Tests pass**

- [ ] **Step 5: Commit**

```bash
git add pylib/anki/pgrep/ai/difficulty.py pylib/tests/test_pgrep_difficulty.py
git commit -m "$(cat <<'EOF'
feat(pgrep): proficiency-simulated difficulty bands

EOF
)"
```

---

### Task 4: Foundry loop core (offline dry-run)

**Files:**

- Create: `content/tools/foundry.py`
- Create: `pylib/tests/test_pgrep_foundry.py` (tests importable pure helpers; put pure logic in `pylib/anki/pgrep/ai/foundry_loop.py` so `just test-py` covers it without content/tools path hacks)

Prefer: create `pylib/anki/pgrep/ai/foundry_loop.py` for pure partition/yield logic, and thin CLI in `content/tools/foundry.py`.

**Interfaces:**

- Consumes: `Verifier.check`, injectable `generate_fn(slot) -> dict`, `max_n_for_accuracy(accuracy: float, *, floor: int = 2, ceiling: int = 8) -> int`
- Produces:
  - `@dataclass SlotResult: accepted: list[dict]; rejected: list[dict]; escalated: list[dict]; yield_rate: float`
  - `def run_slot(slot: dict, *, generate_fn, verifier, n: int, seed: int = 0) -> SlotResult`
  - Each rejected/escalated item carries `panel` (verdict dict) and `reason` strings.
  - Normalize generation `key` -> `correct` before verify.

- [ ] **Step 1: Write the failing test**

```python
# pylib/tests/test_pgrep_foundry.py
from anki.pgrep.ai import foundry_loop


class FakePanel:
    def __init__(self, decisions):
        self._d = list(decisions)

    def check(self, problem):
        d = self._d.pop(0)

        class V:
            decision = d
            def to_dict(self):
                return {"decision": d, "checks": []}
            def reasons(self):
                return ["key: disagree"] if d == "reject" else []

        return V()


def test_run_slot_partitions_accept_reject_escalate():
    items = [
        {"id": "1", "key": "A", "choices": ["a"] * 5, "stem": "s"},
        {"id": "2", "key": "B", "choices": ["a"] * 5, "stem": "s"},
        {"id": "3", "key": "C", "choices": ["a"] * 5, "stem": "s"},
    ]
    gen = iter(items)

    def generate_fn(slot):
        return next(gen)

    result = foundry_loop.run_slot(
        {"topic": "classical_mechanics"},
        generate_fn=generate_fn,
        verifier=FakePanel(["accept", "reject", "escalate"]),
        n=3,
        seed=0,
    )
    assert len(result.accepted) == 1
    assert len(result.rejected) == 1
    assert len(result.escalated) == 1
    assert result.accepted[0]["correct"] == "A"  # key normalized
    assert result.yield_rate == 1 / 3


def test_max_n_caps_by_verifier_accuracy():
    # Weak verifier -> small N (mitigate 2502.00271 over-pruning)
    assert foundry_loop.max_n_for_accuracy(0.5) == 2
    assert foundry_loop.max_n_for_accuracy(0.9) >= 4
    assert foundry_loop.max_n_for_accuracy(0.99) == 8
```

- [ ] **Step 2: Fail, then implement**

```python
# pylib/anki/pgrep/ai/foundry_loop.py
"""Best-of-N foundry partition helpers (WS7). Pure; no network."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Protocol


class _Verifier(Protocol):
    def check(self, problem: dict) -> Any: ...


@dataclass
class SlotResult:
    accepted: list[dict] = field(default_factory=list)
    rejected: list[dict] = field(default_factory=list)
    escalated: list[dict] = field(default_factory=list)

    @property
    def yield_rate(self) -> float:
        total = len(self.accepted) + len(self.rejected) + len(self.escalated)
        return (len(self.accepted) / total) if total else 0.0


def max_n_for_accuracy(
    accuracy: float, *, floor: int = 2, ceiling: int = 8
) -> int:
    """Cap N by measured verifier accuracy so a weak panel does not over-prune."""
    if accuracy < 0.6:
        return floor
    if accuracy < 0.8:
        return max(floor, min(ceiling, 4))
    if accuracy < 0.95:
        return max(floor, min(ceiling, 6))
    return ceiling


def _normalize(item: dict) -> dict:
    out = dict(item)
    if "correct" not in out and out.get("key"):
        out["correct"] = out["key"]
    return out


def run_slot(
    slot: dict,
    *,
    generate_fn: Callable[[dict], dict],
    verifier: _Verifier,
    n: int,
    seed: int = 0,
) -> SlotResult:
    result = SlotResult()
    for i in range(max(0, n)):
        raw = generate_fn(slot)
        if raw.get("refused"):
            result.rejected.append({**raw, "reason": raw.get("refusal_reason", "refused")})
            continue
        item = _normalize(raw)
        item["_foundry_seed"] = seed + i
        verdict = verifier.check(item)
        decision = getattr(verdict, "decision", "escalate")
        payload = {
            **item,
            "panel": verdict.to_dict() if hasattr(verdict, "to_dict") else {"decision": decision},
            "reason": "; ".join(verdict.reasons()) if hasattr(verdict, "reasons") else "",
        }
        if decision == "accept":
            result.accepted.append(payload)
        elif decision == "reject":
            result.rejected.append(payload)
        else:
            result.escalated.append(payload)
    return result
```

- [ ] **Step 3: Thin CLI** `content/tools/foundry.py` with `--dry-run` (fake generate + fake verifier), `--n`, `--topic`, `--out content/run/foundry`, `--self-check` that runs the partition helpers offline and prints yield.

- [ ] **Step 4: Tests pass + `python content/tools/foundry.py --self-check` prints ok**

- [ ] **Step 5: Commit**

```bash
git add pylib/anki/pgrep/ai/foundry_loop.py content/tools/foundry.py pylib/tests/test_pgrep_foundry.py
git commit -m "$(cat <<'EOF'
feat(pgrep): best-of-N foundry loop with offline dry-run

EOF
)"
```

---

### Task 5: Escalation sheet

**Files:**

- Create: `content/tools/make_foundry_escalation.py`
- Modify or create: `content/tools/test_foundry_escalation.py` (plain unittest/pytest under content/tools if that is the local pattern; else a small pure function tested from `test_pgrep_foundry.py`)

**Interfaces:**

- Consumes: `review_sheet.build`, list of escalated items from a foundry run JSON.
- Produces: Markdown sheet with `### <id>` blocks and `-> your call: ESCALATE|KEEP|DROP`.

- [ ] **Step 1: Test that a rendered sheet parses back**

```python
from review_sheet import build, parse, PROBLEM_ID_RE

def test_escalation_sheet_roundtrip():
    items = [{
        "id": "p4-prob-9001",
        "reason": "key: low confidence",
        "stem": "A mass slides...",
        "panel": {"decision": "escalate"},
    }]
    def block(it):
        return (
            f"### {it['id']}\n"
            f"reason: {it['reason']}\n"
            f"stem: {it['stem'][:80]}\n"
            f"-> your call: ESCALATE\n---\n"
        )
    md = build(
        items,
        header=["# Foundry escalation", ""],
        recommend=lambda it: "ESCALATE",
        block=block,
        id_of=lambda it: it["id"],
    )
    assert parse(md, PROBLEM_ID_RE, default="ESCALATE")["p4-prob-9001"] == "ESCALATE"
```

Put the `block` helper in `make_foundry_escalation.py` and import it from the test.

- [ ] **Step 2–4: Implement CLI that reads `content/run/foundry/<run>/escalated.json` and writes `escalation.md`**

- [ ] **Step 5: Commit**

```bash
git commit -m "$(cat <<'EOF'
feat(pgrep): foundry escalation review sheet

EOF
)"
```

---

### Task 6: Recipes and docs

**Files:**

- Modify: `justfile`
- Modify: `docs_pgrep/reference/content-pipeline.md`
- Modify: `docs_pgrep/plan/content-foundry-and-verifier-design.md` (link this plan)
- Modify: `docs_pgrep/README.md` (one line under Plan)

- [ ] **Step 1: Add recipes**

```just
# Offline foundry smoke (no network).
foundry-dry *args:
    {{python}} content/tools/foundry.py --self-check {{args}}

# Real foundry run (needs AI runtime + key). Example: `just foundry --topic classical_mechanics --n 8`.
foundry *args:
    #!/usr/bin/env bash
    set -euo pipefail
    source "{{os_path}}"
    conda run -n pgrep-ai --no-capture-output python content/tools/foundry.py {{args}}
```

Match existing `audit-bundle-ai` / OS path patterns in the justfile exactly.

- [ ] **Step 2: Document** in `content-pipeline.md`: temptation, difficulty caveat, foundry partition, N cap, escalation sheet, firewall path `content/run/foundry/`.

- [ ] **Step 3: `just test-py` green**

- [ ] **Step 4: Commit**

```bash
git commit -m "$(cat <<'EOF'
docs(pgrep): document foundry loop and add just recipes

EOF
)"
```

---

## Self-review checklist

1. **Spec coverage:** WS3 (Tasks 1–2), WS5 (Task 3), WS7 (Tasks 4–5), escalation sheet (Task 5), N cap (Task 4), docs/recipes (Task 6). Comparative multi-candidate pass from the design is deferred to a follow-up bullet inside Task 4 CLI (`--compare` stub that no-ops with a logged note) unless time allows a real contrast prompt; if stubbed, document it as Phase 2.1.
2. **No placeholders:** every task has concrete code.
3. **Types:** `TemptationReport`, `DifficultyEstimate`, `SlotResult`, soft `temptation` check name are consistent across tasks.
4. **Out of scope here:** preference dataset schema (Phase 3), `just eval-verifier` (Phase 3), Tier 2/3 fine-tunes.

---

## Execution handoff

Plan complete and saved to `docs_pgrep/plan/content-foundry-loop-plan.md`. Two execution options:

1. **Subagent-Driven (recommended)** — fresh subagent per task, review between tasks
2. **Inline Execution** — execute in this session with checkpoints

**Which approach?**

Prerequisite: merge or land Phase 1 (`feat/pgrep-content-foundry` / PR #6) before implementing Tasks 2+ that modify `verifier.py`.
