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
    for client in weak_clients:
        user = json.dumps({"stem": problem.get("stem", ""), "choices": choices})
        try:
            picked = _letter(client.complete_text(SOLVE_SYSTEM, user, json_object=True))
        except Exception:  # noqa: BLE001
            continue
        if not picked:
            continue
        n += 1
        if picked in counts:
            counts[picked] += 1
    scores = []
    free = []
    for label, c in counts.items():
        tempt = (c / n) if n else 0.0
        scores.append(
            DistractorScore(label, True, tempt, c, n)
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
