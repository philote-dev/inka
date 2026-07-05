# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""The scaffold-fade tutor: rubric grading and session synthesis (L4.3).

The wrong-answer ladder walks the problem's stored, verified solution
decomposition (``feature-productive-failure.md`` L2). Two evaluation modes share
that stored structure, switched by the AI toggle:

  - AI off (the spec baseline): reveal-and-self-compare. The learner produces a
    sub-goal plus a one-line why, then the stored correct sub-goal is shown for
    self-rating. Pure retrieval and self-explanation, zero AI. This is the L2
    behavior and it stays intact.
  - AI on (the upgrade): rubric grading. The learner's sub-goal is scored against
    the stored rubric (covered / partial / missing) and the weakest gap is
    probed, with the giveaway verifier on every probe so the final answer never
    leaks before the reveal rung. A probe that would leak is refused and replaced
    with a safe generic nudge.

Session-end synthesis reads the attempt log (the single K4 seam) and produces the
pattern recap. Never mutates scheduling state; the tutor only reads the stored
decomposition and the attempt log.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from anki.pgrep import ai_config, attempt_log, problem

if TYPE_CHECKING:
    from anki.collection import Collection

GRADE_SYSTEM = (
    "You are a Physics GRE tutor grading one sub-goal of a solution, in the "
    "Willow checkpoint style. Score the learner's sub-goal against the rubric as "
    "covered, partial, or missing, then ask ONE short probing question about the "
    "weakest gap. NEVER state or imply the final answer or the key choice. Return "
    'STRICT JSON: {"coverage": "covered"|"partial"|"missing", "probe": str}.'
)

SYNTH_SYSTEM = (
    "You write a brief end-of-session synthesis for a Physics GRE learner from "
    "their attempt log: the recurring confusions, the discriminating principles "
    "to remember, and a one-line calibration note. Ground it in the topics and "
    'sources given. Return STRICT JSON: {"patterns": [str], "principles": '
    '[str], "calibration": str}.'
)

_SAFE_PROBE = (
    "Look again at the step you were least sure about. What principle decides it?"
)


def _load_problem(col: Collection, note_id: int) -> dict:
    from anki.notes import NoteId

    note = col.get_note(NoteId(note_id))
    choices = json.loads(note[problem.FIELD_CHOICES] or "[]")
    decomposition = json.loads(note[problem.FIELD_SOLUTION_DECOMPOSITION] or "[]")
    key = note[problem.FIELD_CORRECT]
    key_text = ""
    if key in problem.CHOICE_LETTERS:
        idx = problem.CHOICE_LETTERS.index(key)
        if idx < len(choices):
            key_text = choices[idx]
    return {
        "stem": note[problem.FIELD_STEM],
        "choices": choices,
        "key": key,
        "key_text": key_text,
        "decomposition": decomposition,
        "source_ref": note[problem.FIELD_SOURCE_REF],
    }


def grade_subgoal(
    col: Collection,
    note_id: int,
    subgoal_index: int,
    learner_text: str,
    learner_why: str = "",
) -> dict[str, Any]:
    """Evaluate one produced sub-goal. AI off reveals for self-compare; AI on grades."""
    prob = _load_problem(col, note_id)
    decomposition = prob["decomposition"]
    if subgoal_index < 0 or subgoal_index >= len(decomposition):
        return {"error": "no such sub-goal"}
    step = decomposition[subgoal_index]
    subgoal = step.get("subgoal", "") if isinstance(step, dict) else str(step)
    rubric = step.get("rubric", "") if isinstance(step, dict) else ""

    if not ai_config.ai_enabled(col):
        # Reveal-and-self-compare: show the stored correct sub-goal (L2 baseline).
        return {
            "ai": "off",
            "mode": "reveal",
            "subgoal": subgoal,
            "rubric": rubric,
            "is_last": subgoal_index == len(decomposition) - 1,
        }

    from anki.pgrep.ai import llm, verify

    user = (
        f"RUBRIC for this sub-goal: {rubric}\n"
        f"(The correct sub-goal, for your judgement only, do not reveal it: {subgoal})\n\n"
        f"LEARNER SUB-GOAL: {learner_text}\nLEARNER WHY: {learner_why}"
    )
    try:
        raw = llm.LLMClient(ai_config.resolve_model(col)).complete_json(
            GRADE_SYSTEM, user
        )
    except Exception as exc:  # noqa: BLE001 - never crash study; fall back to the safe path
        return {
            "ai": "error",
            "mode": "reveal",
            "subgoal": subgoal,
            "rubric": rubric,
            "message": f"grading failed: {exc}",
        }

    coverage = raw.get("coverage", "partial")
    probe = raw.get("probe", "") or _SAFE_PROBE
    # Giveaway verifier: a probe that reveals the answer is refused and replaced.
    reason = verify.find_giveaway(probe, prob["key_text"], choice_label=prob["key"])
    giveaway_blocked = reason is not None
    if giveaway_blocked:
        probe = _SAFE_PROBE
    return {
        "ai": "on",
        "mode": "grade",
        "coverage": coverage,
        "probe": probe,
        "giveaway_blocked": giveaway_blocked,
        "is_last": subgoal_index == len(decomposition) - 1,
    }


def _session_attempts(col: Collection, session_id: str) -> list:
    return [
        e
        for e in attempt_log.attempts(col)
        if e.payload.get("session_id") == session_id
    ]


def session_synthesis(col: Collection, session_id: str) -> dict[str, Any]:
    """End-of-session synthesis from the attempt log. AI on summarizes; off templates."""
    events = _session_attempts(col, session_id)
    total = len(events)
    correct = sum(1 for e in events if e.correct)
    by_topic: dict[str, list[int]] = {}
    for e in events:
        bucket = by_topic.setdefault(e.category, [0, 0])
        bucket[0] += 1 if e.correct else 0
        bucket[1] += 1
    recap = {
        "attempted": total,
        "correct": correct,
        "accuracy": (correct / total) if total else 0.0,
        "by_topic": {t: {"correct": c, "total": n} for t, (c, n) in by_topic.items()},
    }

    if total == 0:
        return {
            "ai": "off",
            "recap": recap,
            "patterns": [],
            "principles": [],
            "calibration": "No attempts this session yet.",
        }

    if not ai_config.ai_enabled(col):
        weak = sorted(by_topic.items(), key=lambda kv: kv[1][0] / max(1, kv[1][1]))
        patterns = [f"{t}: {c}/{n} correct" for t, (c, n) in weak[:3]]
        return {
            "ai": "off",
            "recap": recap,
            "patterns": patterns,
            "principles": [f"Review {weak[0][0]}"] if weak else [],
            "calibration": f"You answered {correct} of {total} first-try.",
        }

    from anki.pgrep.ai import llm

    topics = ", ".join(f"{t} ({c}/{n})" for t, (c, n) in by_topic.items())
    user = (
        f"SESSION: {correct}/{total} first-try correct.\nTOPICS: {topics}\n"
        "Summarize the recurring confusions and the discriminating principles."
    )
    try:
        raw = llm.LLMClient(ai_config.resolve_model(col)).complete_json(
            SYNTH_SYSTEM, user
        )
    except Exception as exc:  # noqa: BLE001
        return {
            "ai": "error",
            "recap": recap,
            "patterns": [],
            "principles": [],
            "calibration": f"synthesis failed: {exc}",
        }
    return {
        "ai": "on",
        "recap": recap,
        "patterns": raw.get("patterns", []),
        "principles": raw.get("principles", []),
        "calibration": raw.get("calibration", ""),
    }
