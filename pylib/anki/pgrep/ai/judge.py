# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""One independent judge behind an injectable LLM seam (L4.0f).

The offline content tools each carried a near-identical judge: the figure
verifier asked whether an SVG faithfully depicts a problem stem, and the
technique-giveaway auditor asked whether a stem hands the solver the relation it
is meant to test. Both talked to a pinned ``llm.LLMClient``, parsed a JSON
verdict with the same tolerant brace fallback, and returned a safe default on any
failure. This module is that pattern in one place.

Each check is four small pieces: a system prompt, a payload builder, a typed
verdict dataclass, and a ``Judge`` method. Adding an audit judge later means
adding one of each. A verdict's ``to_dict()`` reproduces the exact dict the tools
emit (same field names, same defaults, the parsed reply passed through verbatim),
so the tools' JSON output is unchanged.

The judge is a pinned ``llm.LLMClient`` by default; tests inject a fake through
the ``client`` seam, so nothing here touches the network. ``llm`` imports
``openai`` lazily, so importing this module stays cheap.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol

from . import llm


class _Client(Protocol):
    """The one method a judge needs from a client (the injectable seam)."""

    def complete_text(
        self, system: str, user: str, *, json_object: bool = False
    ) -> str: ...


# --- figure fidelity -------------------------------------------------------

FIGURE_SYSTEM = (
    "You verify that an SVG line-art diagram faithfully depicts a Physics GRE "
    "problem. You are given the problem stem (the words the student reads) and "
    "the SVG source. Decide whether the figure correctly and sufficiently shows "
    "the setup the stem describes.\n"
    "Check: every physical object, component, or body named in the stem appears "
    "in the figure; the geometry, arrangement, or circuit topology matches the "
    "text; symbolic labels in the figure correspond to variables in the stem; "
    "nothing in the figure contradicts the text; the figure carries NO numeric "
    "values or units (those belong in the stem); and a student could use the "
    "figure to reason about the problem.\n"
    'Return STRICT JSON only: {"matches": true|false, "missing": [str], '
    '"contradictions": [str], "has_numbers": true|false, "notes": str}. '
    "List concrete gaps in missing/contradictions. Set matches=false if any "
    "named element is missing, anything contradicts the text, or numbers appear."
)


@dataclass
class FigureVerdict:
    """Whether an SVG matches its stem; mirrors the figure verifier's shape."""

    matches: bool = False
    missing: list[str] = field(default_factory=list)
    contradictions: list[str] = field(default_factory=list)
    has_numbers: bool = False
    notes: str = ""
    raw: dict | None = field(default=None, repr=False, compare=False)

    @classmethod
    def from_reply(cls, reply: dict) -> FigureVerdict:
        data = reply if isinstance(reply, dict) else {}
        return cls(
            matches=bool(data.get("matches", False)),
            missing=list(data.get("missing") or []),
            contradictions=list(data.get("contradictions") or []),
            has_numbers=bool(data.get("has_numbers", False)),
            notes=str(data.get("notes", "")),
            raw=reply,
        )

    def to_dict(self) -> dict:
        # A parsed reply is passed through verbatim so downstream JSON stays
        # byte-for-byte; a directly built verdict serializes its typed fields.
        if self.raw is not None:
            return self.raw
        return {
            "matches": self.matches,
            "missing": self.missing,
            "contradictions": self.contradictions,
            "has_numbers": self.has_numbers,
            "notes": self.notes,
        }


def _figure_payload(stem: str, svg: str) -> str:
    return f"PROBLEM STEM:\n{stem}\n\nSVG SOURCE:\n{svg}"


# --- technique giveaway ----------------------------------------------------

GIVEAWAY_SYSTEM = (
    "You audit Physics GRE multiple-choice problems for a subtle flaw: a stem that "
    "HANDS THE SOLVER the governing relation, formula, or solution technique the "
    "problem is meant to test. That trivializes a physics problem into plugging in "
    "numbers.\n\n"
    "Draw this line carefully:\n"
    "- NOT a giveaway (allowed): stating given numeric values or standard constants "
    "(for example g = 9.8 m/s^2, the speed of light c, a mass, a length, a moment "
    "of inertia value), defining notation, or describing the physical setup. A "
    "solver is supposed to be given the data.\n"
    "- IS a giveaway (flag it): stating the KEY physical relation, formula, or "
    "method whose recall or derivation is the actual point, for example 'using "
    "f = c/lambda', 'recall that E = hf', 'apply the Rydberg formula "
    "1/lambda = R(1/n1^2 - 1/n2^2)', 'use the fact that the period is "
    "T = 2*pi*sqrt(L/g)', or a stem that walks through the solution steps.\n\n"
    "Judge whether removing the stated relation would still leave the problem "
    "solvable by someone who knows the physics. If the stem states the very "
    "relation that IS the knowledge being tested, flag it.\n\n"
    'Return STRICT JSON: {"gives_away": true|false, "severity": '
    '"high"|"low", "what": "the exact relation/technique handed over, or '
    'empty", "fix": "how to reword so the relation is not given"}. Use '
    "severity high when the handed-over relation is essentially the answer method; "
    "low when it is a borderline nudge."
)

_FIGURE_DIV = re.compile(r'<div class="pg-figure">[\s\S]*?</div>')


@dataclass
class GiveawayVerdict:
    """Whether a stem hands over the tested relation; mirrors the auditor's shape."""

    gives_away: bool = False
    severity: str = ""
    what: str = ""
    fix: str = ""
    raw: dict | None = field(default=None, repr=False, compare=False)

    @classmethod
    def from_reply(cls, reply: dict) -> GiveawayVerdict:
        data = reply if isinstance(reply, dict) else {}
        return cls(
            gives_away=bool(data.get("gives_away", False)),
            severity=str(data.get("severity", "")),
            what=str(data.get("what", "")),
            fix=str(data.get("fix", "")),
            raw=reply,
        )

    def to_dict(self) -> dict:
        if self.raw is not None:
            return self.raw
        return {
            "gives_away": self.gives_away,
            "severity": self.severity,
            "what": self.what,
            "fix": self.fix,
        }


def _giveaway_stem(problem: dict) -> str:
    return _FIGURE_DIV.sub(" ", problem.get("stem", "")).strip()


def _giveaway_payload(problem: dict) -> str:
    choices = "\n".join(f"  {c}" for c in problem.get("choices", []))
    return (
        f"TOPIC: {problem.get('topic', '')}\n\nSTEM:\n{_giveaway_stem(problem)}\n\n"
        f"CHOICES:\n{choices}\n\nCORRECT: {problem.get('correct', '')}"
    )


# --- the judge -------------------------------------------------------------


class Judge:
    """One independent judge over a pinned (or injected) LLM client.

    ``model`` pins a dated snapshot for the default ``llm.LLMClient``; pass
    ``client`` to inject a fake (tests) or a pre-built client. The offline tools
    inject ``llm.judge_client(model)`` so a floating model resolves to a distinct
    dated snapshot. Each method returns a typed verdict.
    """

    def __init__(self, model: str = "", *, client: _Client | None = None) -> None:
        self.client: _Client = client if client is not None else llm.LLMClient(model)
        self.model = getattr(self.client, "model", model)

    def figure_fidelity(self, stem: str, svg: str) -> FigureVerdict:
        """Judge whether ``svg`` faithfully depicts the problem ``stem``."""
        reply = self._verdict(
            FIGURE_SYSTEM,
            _figure_payload(stem, svg),
            on_error=lambda e: {"matches": False, "notes": f"judge call failed: {e}"},
            on_unparseable={"matches": False, "notes": "unparseable judge reply"},
        )
        return FigureVerdict.from_reply(reply)

    def technique_giveaway(self, problem: dict) -> GiveawayVerdict:
        """Judge whether ``problem``'s stem hands over the tested relation."""
        reply = self._verdict(
            GIVEAWAY_SYSTEM,
            _giveaway_payload(problem),
            on_error=lambda e: {
                "gives_away": False,
                "what": "",
                "note": "judge call failed",
            },
            on_unparseable={"gives_away": False},
        )
        return GiveawayVerdict.from_reply(reply)

    def _verdict(
        self,
        system: str,
        user: str,
        *,
        on_error: Callable[[Exception], dict],
        on_unparseable: dict,
    ) -> dict:
        """Call the client and parse a JSON verdict, defaulting on any failure.

        Mirrors the tools exactly: a failed call returns ``on_error(exc)``; a
        reply that is not JSON is retried once with a single-brace regex, and a
        reply with no object at all returns ``on_unparseable``.
        """
        try:
            raw = (
                self.client.complete_text(system, user, json_object=True) or "{}"
            ).strip()
        except Exception as e:  # noqa: BLE001
            return on_error(e)
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            m = re.search(r"\{[\s\S]*\}", raw)
            return json.loads(m.group(0)) if m else dict(on_unparseable)
