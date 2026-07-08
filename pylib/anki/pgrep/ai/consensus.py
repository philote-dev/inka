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
from collections.abc import Sequence
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


def solve_once(
    client: _Client, problem: dict, *, order: list[int] | None = None
) -> Solve:
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
    return Solve(
        letter, str(reply.get("reasoning", "")), _as_float(reply.get("confidence"))
    )


def _majority(letters: list[str]) -> str:
    counts: dict[str, int] = {}
    for x in letters:
        if x:
            counts[x] = counts.get(x, 0) + 1
    return max(counts, key=counts.get) if counts else ""  # type: ignore[arg-type]


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


def backward_check(
    client: _Client | None, problem: dict, proposed_key: str
) -> bool | None:
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
    user = (
        f"STEM (one value masked as <X>):\n{masked}\n\n"
        f"STATED ANSWER: {choices[ki]}\n\nRecover <X>."
    )
    reply = _parse(client, BACKWARD_SYSTEM, user)
    try:
        got = float(reply.get("value"))
        tgt = float(target)
    except (TypeError, ValueError):
        return None
    return abs(got - tgt) <= 1e-6 * max(1.0, abs(tgt))


def _decide(
    stored: str, predicted: str, agree_count: int, n: int, stable: bool,
    sympy_ok: bool | None, backward_ok: bool | None,
) -> tuple[bool, float]:
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


def key_consensus(
    problem: dict, clients: Sequence[_Client], *, use_sympy: bool = True,
    backward_client: _Client | None = None, seed: int = 0,
) -> KeyConsensus:
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
