# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Misconception-first problem generation (L4.2).

Generates exam-style MCQs whose value and risk both sit in the distractors, per
``feature-problem-generation.md``. Each distractor names the likely error and the
trap it produces, and every problem carries a stored solution decomposition
verified once at creation, so it is ladder-ready and no rung leaks the answer
(the core rejects any decomposition that does).

Accepted problems are written as ``pgrep::Problem`` notes (the L1 notetype), so
they join the Problems door pool and feed the wrong-answer ladder and the
Performance score. Generation is AI-on only and heavy deps are lazy, so an AI-off
app is untouched. New notes cold-start FSRS; scheduling state is never mutated.

The batch gold gate (key correctness, distractor quality, beats retrieval and
naive-distractor generation) is the offline harness in ``content/tools``. At
runtime this applies the core-minimum per-item checks: grounding, the giveaway
verifier on the decomposition, CAS for computational keys, and the confidence
route.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from anki.pgrep import ai_config, problem

if TYPE_CHECKING:
    from anki.collection import Collection

GENERATED_TAG = "pgrep::problem-generated"
TOPIC_PREFIX = "topic::"
RETRIEVE_K = 6
DEFAULT_N = 1


def _topic_tag(topic: str) -> str:
    return topic if topic.startswith(TOPIC_PREFIX) else f"{TOPIC_PREFIX}{topic}"


def _category(topic: str) -> str:
    return topic.split("::")[1] if topic.startswith(TOPIC_PREFIX) else topic


def _existing_stem_hashes(col: Collection) -> set[str]:
    from anki.pgrep.ai import verify

    nt = problem.get_problem_notetype(col)
    if nt is None:
        return set()
    hashes: set[str] = set()
    for nid in col.find_notes(f'note:"{problem.PROBLEM_NOTETYPE_NAME}"'):
        note = col.get_note(nid)
        if problem.FIELD_STEM in note:
            hashes.add(verify.normalized_front_hash(note[problem.FIELD_STEM]))
    return hashes


def _add_problem(col: Collection, item: dict, topic: str) -> int:
    """Write one generated MCQ as a pgrep::Problem note. Returns the note id."""
    notetype = problem.ensure_problem_notetype(col)
    note = col.new_note(notetype)
    note[problem.FIELD_STEM] = item["stem"]
    note[problem.FIELD_CHOICES] = json.dumps(list(item["choices"]), ensure_ascii=False)
    note[problem.FIELD_CORRECT] = item["key"]
    note[problem.FIELD_DISTRACTOR_RATIONALES] = json.dumps(
        item.get("distractor_rationales", {}), ensure_ascii=False, sort_keys=True
    )
    note[problem.FIELD_SOLUTION_DECOMPOSITION] = json.dumps(
        item.get("solution_decomposition", []), ensure_ascii=False
    )
    # Store on the Performance model's 1..5 authored scale, exactly like the
    # bundle seed path. A raw 0..1 generated fraction clamps to the 1.0 floor in
    # the model, pinning every generated problem to "easiest".
    note[problem.FIELD_DIFFICULTY] = problem.difficulty_field(item.get("difficulty"))
    note[problem.FIELD_SOURCE_REF] = item.get("source_ref") or ""
    # Carry any pre-generated decomposition tutor data the same way the seed path
    # does (an empty blob when the generated item has none).
    note[problem.FIELD_DECOMPOSITION_TUTOR] = problem.tutor_field(item)
    note.tags = [GENERATED_TAG, _topic_tag(topic)]
    deck_id = col.decks.id(problem.PROBLEM_DECK_NAME)
    col.add_note(note, deck_id)
    return note.id


def _retrieve(col: Collection, query: str) -> Any:
    from anki.pgrep.ai import retrieval

    return retrieval.search(query, k=RETRIEVE_K)


def generate(col: Collection, *, topic: str, n: int = DEFAULT_N) -> dict[str, Any]:
    """Generate ``n`` misconception-first MCQs for a topic (AI on only)."""
    if not ai_config.ai_enabled(col):
        return {
            "ai": "off",
            "added": [],
            "review": [],
            "refused": [],
            "message": "AI is off; the Problems door uses the curated and bundled problems.",
        }
    from anki.pgrep.ai import generation_core as gc
    from anki.pgrep.ai import llm, verify

    retrieved = _retrieve(col, f"{_category(topic)} physics problem")
    client = llm.LLMClient(ai_config.resolve_model(col))
    existing = _existing_stem_hashes(col)

    added, review, refused = [], [], []
    for _ in range(max(1, n)):
        try:
            item = gc.generate_problem(
                topic=_topic_tag(topic), retrieved=retrieved, llm=client
            )
        except Exception as exc:  # noqa: BLE001 - surface a clean status, never crash the app
            return {
                "ai": "error",
                "added": [],
                "review": [],
                "refused": [],
                "message": f"generation failed: {exc}",
            }
        if item.get("refused"):
            refused.append(
                {"reason": item.get("refusal_reason"), "stem": item.get("stem")}
            )
            continue
        h = verify.normalized_front_hash(item.get("stem", ""))
        if h in existing:
            continue
        existing.add(h)
        record = {
            "stem": item["stem"],
            "key": item["key"],
            "source_ref": item.get("source_ref"),
            "confidence": item.get("confidence"),
            "n_distractors": len(item.get("distractors", [])),
            "cas_verified": item.get("cas_verified"),
        }
        if item.get("needs_review"):
            record["review_reason"] = item.get("review_reason")
            review.append(record)
            continue
        record["note_id"] = _add_problem(col, item, topic)
        added.append(record)
    return {
        "ai": "on",
        "added": added,
        "review": review,
        "refused": refused,
        "n_requested": n,
    }
