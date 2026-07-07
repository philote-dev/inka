# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""The gated decomposition tutor for the Problems door (replaces the ladder).

A miss in the Problems door no longer opens a static nudge/decompose/sibling/
reveal ladder. Instead the learner is walked through 2 to 3 pre-generated
subproblems, one at a time, and can only advance when each is satisfied. There is
no skip, and the parent problem's own answer is never revealed on a miss.

Each subproblem is a self-contained mini multiple-choice question (five choices,
one correct key, misconception-tagged distractor rationales) plus a model
``explain_why`` rationale and a named source. It carries several numeric variants
so a missed problem that recurs in the same session shows different numbers.

Two gates per subproblem:

- **The MCQ** must be answered correctly to advance (unlimited retries). A wrong
  pick returns that distractor's rationale and never names the correct key.
- **The explanation** ("explain why") is graded only with AI on, with a lenient
  "good enough" bar plus one line of feedback, and must pass to advance. With AI
  off the explanation step is skipped, so the MCQ alone gates.

Everything the runtime needs is stored with the item (pre-generated in a batch),
so study time never calls the API to *fetch* a decomposition; the only network
call here is the optional AI grade of a free-text explanation, gated on AI being
on. Reads only; no scheduling state is ever touched.
"""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Any

from anki.pgrep import ai_config, problem

if TYPE_CHECKING:
    from anki.collection import Collection

# The lenient "good enough" grader. Willow-checkpoint style: pass anything that
# shows the core idea, fail only blank / off-topic / clearly wrong, never leak the
# parent answer. No em-dashes, light on colons, per the copy rule.
GRADE_EXPLAIN_SYSTEM = (
    "You are a Physics GRE tutor judging whether a learner's short explanation "
    "of one solution step is good enough to move on. Be lenient. The learner is "
    "typing on a keyboard, so judge the idea, not the format: a brief plain "
    "language sentence passes, and you must NOT require numbers, formulas, "
    "equations, or any worked math. Pass any explanation that names the core "
    "idea, even when it is informal, qualitative, partial, or slightly "
    "imprecise. Fail only a blank, off-topic, or clearly wrong explanation. Give "
    "one short line of feedback either way, warm and specific, in plain "
    "sentences with no em dashes and no colons. NEVER state the final answer to "
    'the parent problem or name its key choice. Return STRICT JSON: {"pass": '
    'bool, "feedback": str}.'
)

_SAFE_FEEDBACK = "Good enough. Hold onto that reasoning for the next step."
_EMPTY_FEEDBACK = "Write a line on why before moving on."


# --- reading the stored tutor blob ------------------------------------------


def _load_tutor_data(col: Collection, note_id: int) -> dict[str, Any]:
    """The parsed ``decomposition_tutor`` blob for a Problem, always well-formed.

    Returns ``{"subproblems": [...], "parent_variants": [...]}``. A problem whose
    notetype predates the field, or whose blob is empty or malformed, reads as
    empty lists rather than raising, so the caller degrades gracefully.
    """
    from anki.notes import NoteId

    note = col.get_note(NoteId(int(note_id)))
    if problem.FIELD_DECOMPOSITION_TUTOR not in note:
        return {"subproblems": [], "parent_variants": []}
    try:
        data = json.loads(note[problem.FIELD_DECOMPOSITION_TUTOR] or "{}")
    except (ValueError, TypeError):
        return {"subproblems": [], "parent_variants": []}
    if not isinstance(data, dict):
        return {"subproblems": [], "parent_variants": []}
    subs = data.get("subproblems")
    parents = data.get("parent_variants")
    return {
        "subproblems": subs if isinstance(subs, list) else [],
        "parent_variants": parents if isinstance(parents, list) else [],
    }


def _valid_variant(variant: Any) -> bool:
    if not isinstance(variant, dict):
        return False
    choices = variant.get("choices")
    key = str(variant.get("key", "")).strip().upper()
    return (
        isinstance(choices, list)
        and len(choices) == 5
        and key in problem.CHOICE_LETTERS
    )


def _usable_subproblems(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Subproblems that carry at least one well-formed variant, in order."""
    out: list[dict[str, Any]] = []
    for sub in data["subproblems"]:
        if not isinstance(sub, dict):
            continue
        variants = sub.get("variants")
        if isinstance(variants, list) and any(_valid_variant(v) for v in variants):
            out.append(sub)
    return out


def has_tutor(col: Collection, note_id: int) -> bool:
    """Whether a problem has any usable decomposition to run on a miss."""
    return bool(_usable_subproblems(_load_tutor_data(col, note_id)))


def refresh_tutor_data(col: Collection) -> dict[str, Any]:
    """Dev harness: make sure the collection's Problems carry current tutor data.

    Seeds the bundled Problems if none exist yet, then refreshes every seeded
    note's ``decomposition_tutor`` from the current bundle (matched by stem), so
    a collection seeded before the tutor data was generated picks it up without a
    full reseed. Returns a small report. Writes notes; dev-only.
    """
    from anki.notes import Note, NoteId

    created = problem.seed_sample_problems(col)
    by_stem = {
        str(item.get("stem", "")): problem.tutor_field(item)
        for item in problem.BUNDLE_PROBLEMS
    }
    nids = list(col.find_notes(f'note:"{problem.PROBLEM_NOTETYPE_NAME}"'))
    updated: list[Note] = []
    for nid in nids:
        note = col.get_note(NoteId(int(nid)))
        if problem.FIELD_DECOMPOSITION_TUTOR not in note:
            continue
        field = by_stem.get(str(note[problem.FIELD_STEM]))
        if field is not None and note[problem.FIELD_DECOMPOSITION_TUTOR] != field:
            note[problem.FIELD_DECOMPOSITION_TUTOR] = field
            updated.append(note)
    if updated:
        col.update_notes(updated)
    with_tutor = sum(1 for nid in nids if has_tutor(col, int(nid)))
    return {
        "created": int(created),
        "refreshed": len(updated),
        "with_tutor": with_tutor,
        "total": len(nids),
    }


def list_tutor_problems(col: Collection, limit: int = 300) -> list[dict[str, Any]]:
    """Dev harness: every problem that has a usable decomposition, with a label.

    Reads only. Returns ``[{note_id, label, subgoals}]`` so a dev page can pick a
    problem to run the tutor against without a real session. The label is the
    parent stem stripped of markup and truncated (the parent answer is never
    included), so the picker stays honest and readable.
    """
    from anki.notes import NoteId

    out: list[dict[str, Any]] = []
    for nid in col.find_notes(f'note:"{problem.PROBLEM_NOTETYPE_NAME}"'):
        subs = _usable_subproblems(_load_tutor_data(col, int(nid)))
        if not subs:
            continue
        note = col.get_note(NoteId(int(nid)))
        stem = str(note[problem.FIELD_STEM]) if problem.FIELD_STEM in note else ""
        text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", stem)).strip()
        label = f"{text[:90]}\u2026" if len(text) > 90 else (text or f"Problem {nid}")
        out.append({"note_id": int(nid), "label": label, "subgoals": len(subs)})
        if len(out) >= limit:
            break
    return out


def _rationale_map(raw: Any) -> dict[str, str]:
    if not isinstance(raw, dict):
        return {}
    return {str(key).upper(): str(value) for key, value in raw.items()}


def _variant(
    col: Collection, note_id: int, subgoal_index: int, variant_index: int
) -> dict[str, Any] | None:
    """The specific subproblem variant to grade, or ``None`` if out of range."""
    subs = _usable_subproblems(_load_tutor_data(col, note_id))
    if not (0 <= subgoal_index < len(subs)):
        return None
    variants = [v for v in subs[subgoal_index]["variants"] if _valid_variant(v)]
    if not variants:
        return None
    return variants[variant_index % len(variants)]


# --- load the next tutor state (answer / rationale / explanation withheld) ----


def load_tutor(col: Collection, note_id: int, round_index: int = 0) -> dict[str, Any]:
    """The subproblems to work, with the correct answer and help withheld.

    ``round_index`` selects the numeric variant of every subproblem (0 on the
    first miss; it increments each time the parent recurs), so a repeat never
    reuses the same numbers. Each returned subproblem carries only what the
    learner needs to attempt it (``stem_html`` and ``choices``); the key,
    distractor rationales, and model ``explain_why`` stay server-side until the
    MCQ is answered.
    """
    data = _load_tutor_data(col, note_id)
    subs = _usable_subproblems(data)
    out: list[dict[str, Any]] = []
    for index, sub in enumerate(subs):
        variants = [v for v in sub["variants"] if _valid_variant(v)]
        vi = round_index % len(variants)
        variant = variants[vi]
        out.append(
            {
                "index": index,
                "variant_index": vi,
                "prompt": str(sub.get("prompt", "")),
                "stem_html": str(variant.get("stem", "")),
                "choices": [str(choice) for choice in variant["choices"]],
            }
        )
    return {
        "note_id": int(note_id),
        "variant_round": int(round_index),
        "count": len(out),
        "subproblems": out,
    }


def parent_variant(
    col: Collection, note_id: int, round_index: int
) -> dict[str, Any] | None:
    """A renumbered parent stem for a re-served problem, or ``None`` to reuse it.

    ``round_index`` is 0 for the first serving (the base note) and increments on
    each re-queue. Variant N (0-based) backs round N+1; when the item has no
    parent variants the caller keeps the original stem, which is still honest
    because the parent answer was never revealed.
    """
    if round_index <= 0:
        return None
    variants = [
        v
        for v in _load_tutor_data(col, note_id)["parent_variants"]
        if _valid_variant(v)
    ]
    if not variants:
        return None
    variant = variants[(round_index - 1) % len(variants)]
    return {
        "stem": str(variant.get("stem", "")),
        "choices": [str(choice) for choice in variant["choices"]],
        "key": str(variant.get("key", "")).strip().upper(),
    }


# --- grading the two gates ---------------------------------------------------


def check_mcq(
    col: Collection,
    note_id: int,
    subgoal_index: int,
    variant_index: int,
    selected: str,
) -> dict[str, Any]:
    """Grade one subproblem's MCQ pick (unlimited retries).

    A wrong pick returns that distractor's rationale and withholds the correct
    key (so retries stay honest). A correct pick reveals the model ``explain_why``
    and reports whether the free-text explanation gate applies (AI on only).
    """
    variant = _variant(col, note_id, subgoal_index, variant_index)
    if variant is None:
        return {"error": "no such subproblem"}
    key = str(variant.get("key", "")).strip().upper()
    picked = str(selected or "").strip().upper()
    if not picked or picked != key:
        return {
            "correct": False,
            "rationale_html": _rationale_map(variant.get("distractor_rationales")).get(
                picked, ""
            ),
        }
    return {
        "correct": True,
        "correct_choice": key,
        "explain_why_html": str(variant.get("explain_why", "")),
        "needs_explanation": ai_config.ai_enabled(col),
    }


def _parent_answer(col: Collection, note_id: int) -> tuple[str, str]:
    """The parent problem's correct ``(letter, text)`` for the giveaway guard."""
    from anki.notes import NoteId

    note = col.get_note(NoteId(int(note_id)))
    key = str(note[problem.FIELD_CORRECT] or "").strip().upper()
    try:
        choices = json.loads(note[problem.FIELD_CHOICES] or "[]")
    except (ValueError, TypeError):
        choices = []
    text = ""
    if key in problem.CHOICE_LETTERS and isinstance(choices, list):
        idx = problem.CHOICE_LETTERS.index(key)
        if idx < len(choices):
            text = str(choices[idx])
    return key, text


def grade_explanation(
    col: Collection,
    note_id: int,
    subgoal_index: int,
    variant_index: int,
    learner_text: str,
) -> dict[str, Any]:
    """Grade a subproblem's free-text explanation leniently (AI on only).

    Returns ``{"ai", "pass", "feedback"}`` and, on a pass, ``explain_why_html``
    (the model rationale, shown as reinforcement). AI off never calls this (the
    explanation step is skipped); if it is called anyway it passes by construction
    so it can never block forced learning. The feedback is run through the
    giveaway verifier against the parent problem's answer, so a stray leak is
    replaced with a safe line.
    """
    variant = _variant(col, note_id, subgoal_index, variant_index)
    if variant is None:
        return {"error": "no such subproblem"}
    explain_why = str(variant.get("explain_why", ""))

    if not ai_config.ai_enabled(col):
        return {
            "ai": "off",
            "pass": True,
            "feedback": "",
            "explain_why_html": explain_why,
        }

    text = str(learner_text or "").strip()
    if not text:
        return {"ai": "on", "pass": False, "feedback": _EMPTY_FEEDBACK}

    from anki.pgrep.ai import llm, verify

    user = (
        f"STEP: {variant.get('stem', '')}\n"
        f"MODEL EXPLANATION (reference only, never quote the final answer): "
        f"{explain_why}\n\n"
        f"LEARNER EXPLANATION: {text}"
    )
    try:
        raw = llm.LLMClient(ai_config.resolve_model(col)).complete_json(
            GRADE_EXPLAIN_SYSTEM, user
        )
    except Exception as exc:  # noqa: BLE001 - never crash study; accept and move on
        return {
            "ai": "error",
            "pass": True,
            "feedback": f"Grading is unavailable right now ({exc}); accepted.",
            "explain_why_html": explain_why,
        }

    passed = bool(raw.get("pass"))
    feedback = str(raw.get("feedback", "") or "")
    parent_key, parent_text = _parent_answer(col, note_id)
    if parent_text and verify.find_giveaway(
        feedback, parent_text, choice_label=parent_key
    ):
        feedback = _SAFE_FEEDBACK
    result: dict[str, Any] = {"ai": "on", "pass": passed, "feedback": feedback}
    if passed:
        result["explain_why_html"] = explain_why
    return result
