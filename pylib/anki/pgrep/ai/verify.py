# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Verification for generated items and tutor hints (L4.0f).

Three checks the generation and tutor paths lean on, none of which need a model:

  - Dedup: a normalized-front hash so a generated card cannot duplicate an
    existing one.
  - Giveaway verifier: a hint or ladder rung must not reveal the final answer
    before the reveal rung. Conservative by design (it prefers to flag).
  - CAS: SymPy checks a computational item's answer, symbolic or numeric,
    independent of any model, per ``feature-forced-generation.md``.

SymPy is imported lazily so importing this module stays cheap and AI-off never
loads it.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any

_WORD = re.compile(r"[a-z0-9]+")
_NUM = re.compile(r"-?\d+(?:\.\d+)?")


def normalize(text: str) -> str:
    return " ".join(_WORD.findall(text.lower()))


# --- dedup -----------------------------------------------------------------


def normalized_front_hash(front: str) -> str:
    return hashlib.blake2b(normalize(front).encode("utf-8"), digest_size=12).hexdigest()


def is_duplicate(front: str, existing_hashes: set[str]) -> bool:
    return normalized_front_hash(front) in existing_hashes


# --- giveaway verifier -----------------------------------------------------

_REVEAL_PHRASES = (
    "the answer is",
    "answer is",
    "correct answer",
    "the correct choice",
    "the solution is",
    "equals",
    "the result is",
)


def _numbers(text: str) -> set[str]:
    # Normalize numeric tokens so 45 and 45.0 compare equal.
    out = set()
    for m in _NUM.findall(text):
        try:
            out.add(str(float(m)))
        except ValueError:
            continue
    return out


def find_giveaway(
    hint: str, answer: str, *, choice_label: str | None = None
) -> str | None:
    """Return a reason string if the hint reveals the answer, else None.

    Flags three ways a hint can leak: the answer text appears verbatim, a
    decisive number from the answer appears, or a reveal phrase names the answer
    or the key letter. Short, generic answers (a single common word) are not
    flagged on text alone, since they carry no information.
    """
    h = normalize(hint)
    a = normalize(answer)
    if a and len(a) >= 8 and a in h:
        return "hint contains the answer text verbatim"
    ans_nums = _numbers(answer)
    hint_nums = _numbers(hint)
    shared = ans_nums & hint_nums
    if shared:
        return f"hint states the answer value(s): {sorted(shared)}"
    if choice_label:
        label = choice_label.strip().lower()
        for phrase in _REVEAL_PHRASES:
            if phrase in h and re.search(rf"\b{re.escape(label)}\b", h):
                return f"hint names the key choice '{choice_label}'"
    for phrase in ("the answer is", "correct answer is", "the solution is"):
        if phrase in h:
            return f"hint uses a reveal phrase: '{phrase}'"
    return None


def giveaway_safe(hint: str, answer: str, *, choice_label: str | None = None) -> bool:
    """True when the hint does not reveal the answer."""
    return find_giveaway(hint, answer, choice_label=choice_label) is None


# --- CAS (SymPy) -----------------------------------------------------------


def _parse(expr: str) -> Any:
    from sympy.parsing.sympy_parser import (  # type: ignore[import-not-found]
        implicit_multiplication_application,
        parse_expr,
        standard_transformations,
    )

    transformations = standard_transformations + (implicit_multiplication_application,)
    return parse_expr(expr, transformations=transformations, evaluate=True)


def cas_equivalent(expr_a: str, expr_b: str) -> bool:
    """True when two expressions are symbolically equal (a - b simplifies to 0)."""
    import sympy  # type: ignore[import-not-found]

    try:
        diff = sympy.simplify(_parse(expr_a) - _parse(expr_b))
        return bool(diff == 0)
    except (SyntaxError, TypeError, ValueError, AttributeError):
        return False


def cas_check_value(
    expr: str, expected: float, *, tolerance: float = 1e-3, subs: dict | None = None
) -> bool:
    """True when ``expr`` evaluates to ``expected`` within ``tolerance``."""
    import sympy  # type: ignore[import-not-found]

    try:
        e = _parse(expr)
        if subs:
            e = e.subs({sympy.Symbol(k): v for k, v in subs.items()})
        value = float(e.evalf())
    except (SyntaxError, TypeError, ValueError, AttributeError):
        return False
    denom = max(1.0, abs(expected))
    return (
        abs(value - expected) <= tolerance * denom or abs(value - expected) <= tolerance
    )
