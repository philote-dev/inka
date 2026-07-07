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
_FIGURE_SVG = re.compile(r'<div class="pg-figure">([\s\S]*?)</div>')


def _strip_figure(stem: str) -> str:
    """The stem with any ``pg-figure`` block removed (the words a solver reads)."""
    return _FIGURE_DIV.sub(" ", stem or "").strip()


def _extract_svg(stem: str) -> str:
    """The SVG source inside a stem's ``pg-figure`` block, or "" when absent."""
    m = _FIGURE_SVG.search(stem or "")
    return m.group(1).strip() if m else ""


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
    return _strip_figure(problem.get("stem", ""))


def _giveaway_payload(problem: dict) -> str:
    choices = "\n".join(f"  {c}" for c in problem.get("choices", []))
    return (
        f"TOPIC: {problem.get('topic', '')}\n\nSTEM:\n{_giveaway_stem(problem)}\n\n"
        f"CHOICES:\n{choices}\n\nCORRECT: {problem.get('correct', '')}"
    )


# --- answer key (independent solve) ----------------------------------------

_LETTERS = ("A", "B", "C", "D", "E")

ANSWER_KEY_SYSTEM = (
    "You solve one Physics GRE multiple-choice problem from physics. You are given "
    "the stem, an optional line-art figure as SVG source (it carries no numeric "
    "values; every given number is in the stem text), and the five options A-E. "
    "Reason it out, then choose the single best option. You are NOT told the "
    "intended answer; decide independently and do not assume any option is "
    "correct.\n"
    'Return STRICT JSON only: {"answer": "A"|"B"|"C"|"D"|"E", "confidence": '
    '0..1, "reasoning": "one or two sentences of physics justification"}.'
)


def _as_float(value: object) -> float:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0


def _labeled_choices(choices: list) -> str:
    return "\n".join(
        f"  {lab}. {choices[i]}" for i, lab in enumerate(_LETTERS) if i < len(choices)
    )


@dataclass
class AnswerKeyVerdict:
    """An independent solve of an MCQ, compared to the stored key.

    ``predicted_letter`` is the judge's own answer, blank when it produced no
    valid letter (a failed or unparseable call), which the auditor treats as
    inconclusive rather than a disagreement. ``agrees`` is that letter against the
    stored ``correct``. Unlike the two legacy verdicts, ``to_dict`` serializes the
    typed fields, since ``agrees`` is derived and has no place in the raw reply.
    """

    predicted_letter: str = ""
    agrees: bool = False
    confidence: float = 0.0
    reasoning: str = ""
    raw: dict | None = field(default=None, repr=False, compare=False)

    @classmethod
    def from_reply(cls, reply: dict, correct: str) -> AnswerKeyVerdict:
        data = reply if isinstance(reply, dict) else {}
        letter = str(data.get("answer", "")).strip().upper()[:1]
        if letter not in _LETTERS:
            letter = ""
        stored = str(correct or "").strip().upper()[:1]
        return cls(
            predicted_letter=letter,
            agrees=bool(letter) and letter == stored,
            confidence=_as_float(data.get("confidence")),
            reasoning=str(data.get("reasoning", "")),
            raw=reply,
        )

    def to_dict(self) -> dict:
        return {
            "predicted_letter": self.predicted_letter,
            "agrees": self.agrees,
            "confidence": self.confidence,
            "reasoning": self.reasoning,
        }


def _answer_key_payload(problem: dict) -> str:
    # Deliberately omits the stored key so the solve stays blind to it.
    stem = _strip_figure(problem.get("stem", ""))
    svg = _extract_svg(problem.get("stem", ""))
    parts = [f"STEM:\n{stem}"]
    if svg:
        parts.append(f"FIGURE (SVG line art, no numeric values):\n{svg}")
    parts.append(f"OPTIONS:\n{_labeled_choices(problem.get('choices', []) or [])}")
    return "\n\n".join(parts)


# --- distractor plausibility -----------------------------------------------

DISTRACTOR_SYSTEM = (
    "You audit the DISTRACTORS (the wrong options) of a Physics GRE "
    "multiple-choice problem. A good distractor is tempting: it is the answer a "
    "student reaches through a specific, plausible misconception or a common "
    "algebra, sign, or factor slip. A bad distractor is obviously wrong (wrong "
    "units, wrong order of magnitude, nonsensical, or a throwaway) so a test-wise "
    "student eliminates it for free.\n"
    "You are given the stem, all options with the correct one marked, and the "
    "author's intended misconception for each wrong option. For each wrong option "
    "decide whether it is genuinely tempting and tied to a real misconception.\n"
    'Return STRICT JSON only: {"implausible_labels": [letters of the wrong '
    'options that are obviously wrong or free to eliminate], "notes": "one or two '
    'sentences"}. Judge only the wrong options; never list the correct option.'
)


@dataclass
class DistractorVerdict:
    """Which wrong options are too weak to tempt anyone (a soft, report-only audit)."""

    implausible_labels: list[str] = field(default_factory=list)
    notes: str = ""
    raw: dict | None = field(default=None, repr=False, compare=False)

    @classmethod
    def from_reply(cls, reply: dict) -> DistractorVerdict:
        data = reply if isinstance(reply, dict) else {}
        labels: list[str] = []
        for item in data.get("implausible_labels") or []:
            lab = str(item).strip().upper()[:1]
            if lab in _LETTERS and lab not in labels:
                labels.append(lab)
        return cls(
            implausible_labels=labels, notes=str(data.get("notes", "")), raw=reply
        )

    def to_dict(self) -> dict:
        return {"implausible_labels": self.implausible_labels, "notes": self.notes}


def _distractor_payload(problem: dict) -> str:
    stem = _strip_figure(problem.get("stem", ""))
    choices = problem.get("choices", []) or []
    correct = str(problem.get("correct", "")).strip().upper()[:1]
    options = []
    for i, lab in enumerate(_LETTERS):
        if i >= len(choices):
            break
        mark = "  (correct)" if lab == correct else ""
        options.append(f"  {lab}. {choices[i]}{mark}")
    parts = [f"STEM:\n{stem}", "OPTIONS:\n" + "\n".join(options)]
    rationales = []
    for d in problem.get("distractors", []) or []:
        if isinstance(d, dict) and d.get("label"):
            tag = d.get("misconception", "") or d.get("misconception_tag", "")
            rationales.append(f"  {d['label']}: {tag} - {d.get('rationale', '')}")
    if rationales:
        joined = "\n".join(rationales)
        parts.append(f"AUTHOR INTENDED MISCONCEPTION PER WRONG OPTION:\n{joined}")
    return "\n\n".join(parts)


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

    def answer_key(self, problem: dict) -> AnswerKeyVerdict:
        """Independently solve ``problem`` (blind to the stored key), then compare.

        The payload never carries ``correct``; the judge returns its own letter and
        this compares it to the stored key. A call that yields no valid letter
        leaves ``predicted_letter`` blank, which the auditor reports as
        inconclusive rather than a disagreement.
        """
        reply = self._verdict(
            ANSWER_KEY_SYSTEM,
            _answer_key_payload(problem),
            on_error=lambda e: {"reasoning": f"judge call failed: {e}"},
            on_unparseable={"reasoning": "unparseable judge reply"},
        )
        return AnswerKeyVerdict.from_reply(reply, problem.get("correct", ""))

    def distractor_plausibility(self, problem: dict) -> DistractorVerdict:
        """Judge whether ``problem``'s wrong options are tempting (a soft audit)."""
        reply = self._verdict(
            DISTRACTOR_SYSTEM,
            _distractor_payload(problem),
            on_error=lambda e: {
                "implausible_labels": [],
                "notes": f"judge call failed: {e}",
            },
            on_unparseable={"implausible_labels": []},
        )
        return DistractorVerdict.from_reply(reply)

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
