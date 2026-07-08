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
import re
from dataclasses import dataclass
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
