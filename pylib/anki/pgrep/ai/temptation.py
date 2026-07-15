# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Distractor structural wrongness and temptation (WS3).

Temptation is the fraction of weaker or proficiency-simulated solvers that
select an option other than the stored key. With solver evidence, zero
temptation is a free elimination. ``is_wrong`` means only that a label differs
from the stored key; the consensus panel owns whether that key is correct.
"""

from __future__ import annotations

import json
import random
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol


class _Client(Protocol):
    def complete_text(
        self, system: str, user: str, *, json_object: bool = False
    ) -> str: ...


SOLVE_SYSTEM = (
    "Solve the multiple-choice physics problem. Reply JSON only: "
    '{"answer":"A"|"B"|"C"|"D"|"E","reasoning":"...","confidence":0..1}.'
)


@dataclass
class DistractorScore:
    """A candidate's temptation and structural relation to the stored key.

    ``is_wrong`` means ``label != stored key``. It is not an independent
    solver-based judgment of option correctness.
    """

    label: str
    is_wrong: bool
    temptation: float
    selected_by: int
    n_solvers: int


@dataclass
class TemptationReport:
    """Temptation evidence; free eliminations require at least one valid solve."""

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
    for client in weak_clients:
        order = list(range(len(choices)))
        rng.shuffle(order)
        display = [choices[j] for j in order]
        user = json.dumps({"stem": problem.get("stem", ""), "choices": display})
        try:
            picked_display = _letter(
                client.complete_text(SOLVE_SYSTEM, user, json_object=True)
            )
        except Exception:  # noqa: BLE001
            continue
        if not picked_display or picked_display not in letters:
            continue
        di = letters.index(picked_display)
        if di >= len(order):
            continue
        orig = letters[order[di]]
        n += 1
        if orig in counts:
            counts[orig] += 1
    scores = []
    free = []
    for label, c in counts.items():
        tempt = (c / n) if n else 0.0
        scores.append(DistractorScore(label, label != correct, tempt, c, n))
        if n > 0 and tempt == 0.0:
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
    """Keep the k most tempting candidates known not to be the stored key."""
    if not candidates:
        return []
    base = dict(problem or {})
    # Score the caller's problem, then rank candidates by label temptation.
    report = score_distractors(base, weak_clients, seed=seed)
    rank = {s.label: s.temptation for s in report.scores}
    ordered = sorted(
        candidates,
        key=lambda d: rank.get(str(d.get("label", "")), 0.0),
        reverse=True,
    )
    return ordered[: max(0, k)]
