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
import re
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
    "You are a Physics GRE tutor writing the end-of-session consolidation for a "
    "learner from the problems they missed today. Group the misses into 1 to 3 "
    "named reasoning patterns, each a transferable habit the learner can fix (an "
    "error about a concept or method, never 'question 7'). For each pattern give a "
    "short title and ONE evidence sentence saying what actually went wrong, "
    "grounded only in the misses provided. Put real physics in LaTeX with \\( \\) "
    "so it reads like a textbook, never ASCII math. Never state or imply any "
    "problem's final answer or its key choice. Use plain sentences, with no em "
    "dashes and no colon-heavy phrasing. Only name patterns the evidence "
    "supports and invent nothing. Return STRICT JSON: "
    '{"patterns": [{"title": str, "count": int, "evidence": str}]}.'
)

_SAFE_PROBE = (
    "Look again at the step you were least sure about. What principle decides it?"
)


def _load_problem(col: Collection, note_id: int) -> dict:
    from anki.notes import NoteId

    note = col.get_note(NoteId(note_id))
    choices = json.loads(note[problem.FIELD_CHOICES] or "[]")
    decomposition = json.loads(note[problem.FIELD_SOLUTION_DECOMPOSITION] or "[]")
    rationales = {}
    if problem.FIELD_DISTRACTOR_RATIONALES in note:
        try:
            rationales = json.loads(note[problem.FIELD_DISTRACTOR_RATIONALES] or "{}")
        except (ValueError, TypeError):
            rationales = {}
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
        "distractor_rationales": rationales if isinstance(rationales, dict) else {},
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


def _reframe(total: int, correct: int) -> str:
    """One honest reframe line under the score. Warmth from a truer reading of the
    same number, never praise (desirable-difficulty study is meant to feel worse
    than it went)."""
    if total == 0:
        return "No problems landed this session."
    if correct >= total:
        return (
            "A clean run today. The value now is keeping the mix hard enough to miss."
        )
    return (
        "In-session accuracy understates your learning. The misses are where "
        "today's work happened; here is what they share."
    )


def _strip(text: str, limit: int = 220) -> str:
    """Plain text from a stem or step, markup and figures removed, length capped."""
    text = re.sub(r"<[^>]+>", " ", text or "")
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


def _topic_list(by_topic: dict[str, list[int]]) -> list[dict[str, Any]]:
    return [{"topic": t, "correct": c, "total": n} for t, (c, n) in by_topic.items()]


def _miss_detail(col: Collection, event: Any) -> dict[str, Any] | None:
    """Ground one missed attempt from its stored problem: the stem, the wrong
    choice the learner picked, and the verified method (no final answer)."""
    note_id = event.payload.get("item_note_id")
    if not note_id:
        return None
    try:
        prob = _load_problem(col, int(note_id))
    except Exception:  # noqa: BLE001 - a missing/edited note just drops from grounding
        return None
    picked = ""
    why = ""
    letter = str(event.payload.get("selected_option", "")).strip().upper()
    if letter in problem.CHOICE_LETTERS:
        idx = problem.CHOICE_LETTERS.index(letter)
        if idx < len(prob["choices"]):
            picked = _strip(str(prob["choices"][idx]), 120)
        why = _strip(str(prob["distractor_rationales"].get(letter, "")), 200)
    method = "; ".join(
        _strip(str(s.get("subgoal", "")), 120)
        for s in prob["decomposition"]
        if isinstance(s, dict) and s.get("subgoal")
    )
    return {
        "category": event.category,
        "stem": _strip(str(prob["stem"]), 220),
        "picked": picked,
        "why": why,
        "method": method,
    }


def _ai_patterns(
    col: Collection, correct: int, total: int, misses: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Group the session's misses into 1 to 3 named patterns with grounded, real-
    math evidence. Titles/evidence come from the model; count and kind are set here
    so the shape is trusted."""
    from anki.pgrep.ai import llm

    lines = [
        f"- [{m['category']}] STEM: {m['stem']}\n"
        f"  PICKED (wrong): {m['picked'] or 'unknown'}. "
        f"WHY THAT IS WRONG: {m['why'] or 'n/a'}. "
        f"METHOD (never state the final answer): {m['method'] or 'n/a'}"
        for m in misses[:8]
    ]
    user = f"SESSION: {correct}/{total} first-try correct.\nMISSES:\n" + "\n".join(
        lines
    )
    raw = llm.LLMClient(ai_config.resolve_model(col)).complete_json(SYNTH_SYSTEM, user)
    out: list[dict[str, Any]] = []
    for p in raw.get("patterns", []) or []:
        if not isinstance(p, dict):
            continue
        title = str(p.get("title", "")).strip()
        if not title:
            continue
        try:
            count = int(p.get("count", 1) or 1)
        except (TypeError, ValueError):
            count = 1
        out.append(
            {
                "title": title,
                "count": max(1, count),
                "kind": "miss",
                "evidence": str(p.get("evidence", "")),
            }
        )
    return out[:3]


def _synthesize(
    col: Collection,
    *,
    total: int,
    correct: int,
    duration_min: int,
    by_topic: dict[str, list[int]],
    misses: list[dict[str, Any]],
) -> dict[str, Any]:
    """Shared synthesis core: assemble the consolidation payload. Score, duration,
    and per-topic bars are computed; the pattern cards come from the AI (grounded
    in the misses) or a plain template with AI off. Saves are only produced when
    grounded, which needs captured method, so real sessions emit misses today."""
    base = {
        "score": {"correct": correct, "total": total},
        "duration_min": int(duration_min),
        "reframe": _reframe(total, correct),
        "by_topic": _topic_list(by_topic),
    }

    if total == 0:
        return {"ai": "off", **base, "patterns": []}

    if not ai_config.ai_enabled(col):
        weak = sorted(
            ((t, c, n) for t, (c, n) in by_topic.items() if n - c > 0),
            key=lambda x: x[1] / max(1, x[2]),
        )
        patterns = [
            {
                "title": f"{t.replace('_', ' ').capitalize()} needs another pass",
                "count": n - c,
                "kind": "miss",
                "evidence": "",
            }
            for t, c, n in weak[:3]
        ]
        return {"ai": "off", **base, "patterns": patterns}

    try:
        patterns = _ai_patterns(col, correct, total, misses)
    except Exception:  # noqa: BLE001 - never crash the session end; degrade to no cards
        return {"ai": "error", **base, "patterns": []}
    return {"ai": "on", **base, "patterns": patterns}


def session_synthesis(col: Collection, session_id: str) -> dict[str, Any]:
    """End-of-session consolidation from the attempt log. First-try (clean)
    attempts drive the score, the topic bars, and the miss grouping; retries are
    excluded. Duration is the wall clock across the whole session."""
    events = _session_attempts(col, session_id)
    times = [e.answered_at for e in events if e.answered_at]
    duration_min = round((max(times) - min(times)) / 60) if len(times) >= 2 else 0

    clean = [e for e in events if int(e.payload.get("ladder_depth", 0) or 0) == 0]
    by_topic: dict[str, list[int]] = {}
    for e in clean:
        bucket = by_topic.setdefault(e.category, [0, 0])
        bucket[0] += 1 if e.correct else 0
        bucket[1] += 1
    total = len(clean)
    correct = sum(1 for e in clean if e.correct)
    misses = [d for d in (_miss_detail(col, e) for e in clean if not e.correct) if d]
    return _synthesize(
        col,
        total=total,
        correct=correct,
        duration_min=int(duration_min),
        by_topic=by_topic,
        misses=misses,
    )


def session_synthesis_preview(col: Collection) -> dict[str, Any]:
    """Dev harness: the finished consolidation screen on the design's fixed sample,
    so the dev lab can review the whole layout (including a grounded save card)
    without playing a session. Reads nothing from the collection."""
    return {
        "ai": "preview",
        "score": {"correct": 14, "total": 20},
        "duration_min": 48,
        "reframe": (
            "In-session accuracy understates your learning. The misses are where "
            "today's work happened; here is what they share."
        ),
        "by_topic": [
            {"topic": "mechanics", "correct": 4, "total": 6},
            {"topic": "electromagnetism", "correct": 4, "total": 6},
            {"topic": "quantum", "correct": 4, "total": 5},
            {"topic": "thermodynamics", "correct": 2, "total": 3},
        ],
        "patterns": [
            {
                "title": "Moment of inertia taken about the wrong axis",
                "count": 2,
                "kind": "miss",
                "evidence": (
                    "Both used the center value \\( \\tfrac{1}{12}ML^{2} \\) at an "
                    "end pivot. Parallel axis gives \\( \\tfrac{1}{3}ML^{2} \\)."
                ),
            },
            {
                "title": "Induced EMF sign dropped at the final step",
                "count": 2,
                "kind": "miss",
                "evidence": (
                    "The flux setup was right both times; the direction flipped "
                    "while solving. Lenz's law is the free check."
                ),
            },
            {
                "title": "Limiting cases are doing real work",
                "count": 2,
                "kind": "save",
                "evidence": (
                    "Sending \\( L \\to \\infty \\) and \\( T \\to 0 \\) rejected "
                    "trap options in Quantum and Thermo."
                ),
            },
        ],
    }
