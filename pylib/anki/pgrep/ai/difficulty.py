# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

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
    letters = "ABCDE"[: len(choices)]
    hits = n = 0
    rng = random.Random(seed)
    for client in weak_clients:
        order = list(range(len(choices)))
        rng.shuffle(order)
        display = [choices[j] for j in order]
        user = json.dumps({"stem": problem.get("stem", ""), "choices": display})
        try:
            picked = _letter(client.complete_text(SOLVE_SYSTEM, user, json_object=True))
        except Exception:  # noqa: BLE001
            continue
        if not picked or picked not in letters:
            continue
        di = letters.index(picked)
        if di >= len(order):
            continue
        orig = letters[order[di]]
        n += 1
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
