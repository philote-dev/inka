# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""The ``pgrep::Problem`` notetype and bundled problems (L2.1 Study).

A Problem is a five-choice practice question with everything the wrong-answer
ladder needs stored *with the item* (``feature-productive-failure.md`` §L2): the
correct letter, a short rationale per distractor, and an ordered
``solution_decomposition`` (sub-goals + a rubric each). Because the decomposition
is stored, the ladder is **AI-off by construction** — hint-time just walks the
stored steps (reveal-and-self-compare). There is deliberately **no confidence
field**: the commit gate captures the answer before any help, nothing else.

Field order (fixed by the L2 API contract §3):

    stem, choices, correct, distractor_rationales, solution_decomposition,
    difficulty, source_ref

``choices``, ``distractor_rationales`` and ``solution_decomposition`` hold JSON
(an array, a letter->text map, and an ordered list of ``{subgoal, rubric}``).
The topic lives on the note's tags (``topic::<category>``), mirroring the rest of
pgrep, so the selector / Memory / Coverage see Problems the same way as cards.

``decomposition_tutor`` (field 7, added for the gated decomposition tutor that
replaces the static wrong-answer ladder) holds JSON with a ``subproblems`` list,
each carrying several pre-generated numeric variants so a repeat never reuses the
same numbers. Each variant is a full mini multiple-choice question (``stem``,
``choices`` of five, ``key``, per-distractor ``distractor_rationales``, a model
``explain_why`` rationale, and a named ``source_ref``). An optional
``parent_variants`` list holds renumbered forms of the parent stem, so a missed
problem can recur in the same session with different numbers. It is deliberately
pre-generated in a batch, so study time never calls the API to fetch it.

:func:`seed_sample_problems` idempotently seeds the curated, corpus-grounded
problems from the committed content bundle (:data:`BUNDLE_PROBLEMS`, built from
the P4 triage-approved set) into a ``PGRE::Problems`` deck; a marker tag makes
repeat calls a no-op. New notes cold-start FSRS; scheduling state is never
touched. The scaffolding ``pgrep_seed`` handler calls it opportunistically.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from anki.collection import Collection
    from anki.models import NotetypeDict

# Schema, per the L2 API contract §3.
PROBLEM_NOTETYPE_NAME = "pgrep::Problem"
# Marker tag on every seeded Problem; drives idempotency (never duplicate cards).
PROBLEM_SEED_TAG = "pgrep::problem-seed"
# Seeded Problems' cards live here (a separate deck from the Cards door sample).
PROBLEM_DECK_NAME = "PGRE::Problems"

TOPIC_PREFIX = "topic::"

# Field names, in order. ``stem`` (field 0) is the sort field.
FIELD_STEM = "stem"
FIELD_CHOICES = "choices"
FIELD_CORRECT = "correct"
FIELD_DISTRACTOR_RATIONALES = "distractor_rationales"
FIELD_SOLUTION_DECOMPOSITION = "solution_decomposition"
FIELD_DIFFICULTY = "difficulty"
FIELD_SOURCE_REF = "source_ref"
# Field 7: the pre-generated, gated decomposition tutor data (JSON). Appended
# after the original contract fields so their ordinals never move.
FIELD_DECOMPOSITION_TUTOR = "decomposition_tutor"
PROBLEM_FIELDS: tuple[str, ...] = (
    FIELD_STEM,
    FIELD_CHOICES,
    FIELD_CORRECT,
    FIELD_DISTRACTOR_RATIONALES,
    FIELD_SOLUTION_DECOMPOSITION,
    FIELD_DIFFICULTY,
    FIELD_SOURCE_REF,
    FIELD_DECOMPOSITION_TUTOR,
)

# The option letters a Problem may use, in order.
CHOICE_LETTERS: tuple[str, ...] = ("A", "B", "C", "D", "E")

# The committed content bundle lives next to this module.
_BUNDLE_PATH = Path(__file__).with_name("content_bundle.json")

# Middle of the 1..5 authored scale, used when a bundle item lacks a difficulty.
_NEUTRAL_DIFFICULTY = "3.0"


def _load_bundle_problems() -> list[dict[str, Any]]:
    with _BUNDLE_PATH.open(encoding="utf-8") as handle:
        return json.load(handle)["problems"]


# The curated default problems (P4 triage-approved, corpus-grounded). Each record
# is ``{"id", "topic", "kind", "stem", "choices", "correct", "distractors",
# "solution_decomposition", "difficulty", "source_ref"}``.
BUNDLE_PROBLEMS: tuple[dict[str, Any], ...] = tuple(_load_bundle_problems())


# Notetype bootstrap
##########################################################################


def get_problem_notetype(col: Collection) -> NotetypeDict | None:
    """The ``pgrep::Problem`` notetype, or ``None`` if it doesn't exist yet."""
    return col.models.by_name(PROBLEM_NOTETYPE_NAME)


def ensure_problem_notetype(col: Collection) -> NotetypeDict:
    """Return the ``pgrep::Problem`` notetype, creating it if missing.

    Mirrors ``attempt_log.ensure_attempt_notetype``: the contract fields in
    order, ``stem`` as the sort field, and a single trivial card template
    (Problems are rendered by the Study surface from their fields, not by Anki's
    card templates, but Anki requires at least one template). An already-created
    notetype from before ``decomposition_tutor`` was added is migrated forward by
    appending the missing field.
    """
    existing = get_problem_notetype(col)
    if existing:
        return _migrate_fields(col, existing)

    mm = col.models
    notetype = mm.new(PROBLEM_NOTETYPE_NAME)
    for field_name in PROBLEM_FIELDS:
        mm.add_field(notetype, mm.new_field(field_name))
    # stem is the sort field.
    mm.set_sort_index(notetype, 0)
    template = mm.new_template("Problem")
    template["qfmt"] = "{{" + FIELD_STEM + "}}"
    template["afmt"] = "{{FrontSide}}\n\n<hr id=answer>\n\n{{" + FIELD_CORRECT + "}}"
    mm.add_template(notetype, template)
    mm.add(notetype)
    created = get_problem_notetype(col)
    assert created is not None
    return created


def _migrate_fields(col: Collection, notetype: NotetypeDict) -> NotetypeDict:
    """Append any contract field a pre-existing notetype is missing.

    Only ever adds fields (never reorders or drops), so existing Problem notes
    and their cards are untouched; a collection made before the tutor field
    existed simply gains an empty ``decomposition_tutor`` to fill.
    """
    mm = col.models
    have = {field["name"] for field in notetype["flds"]}
    missing = [name for name in PROBLEM_FIELDS if name not in have]
    if not missing:
        return notetype
    for field_name in missing:
        mm.add_field(notetype, mm.new_field(field_name))
    mm.update_dict(notetype)
    refreshed = get_problem_notetype(col)
    assert refreshed is not None
    return refreshed


# Bundled problems (the AI-off ladder data)
##########################################################################


def difficulty_field(fraction: Any) -> str:
    """Authored 0..1 difficulty fraction (higher is harder) -> the 1..5 scale.

    Both the bundle seed path and the AI generation path store difficulty through
    this, so a curated problem and a generated one feed the score on one scale.
    The Performance model reads the stored value via
    ``performance._attempt_difficulty`` on the 1..5 authored scale (normalized
    internally by ``(d-1)/4``). A raw 0..1 fraction would clamp to the 1.0 floor
    there, so map it with ``1 + 4*f`` first. The fraction is clamped to [0, 1] so
    an out-of-range generated value can never overshoot the scale; a missing or
    non-numeric value falls back to the neutral middle.
    """
    if isinstance(fraction, bool) or not isinstance(fraction, (int, float)):
        return _NEUTRAL_DIFFICULTY
    clamped = min(1.0, max(0.0, float(fraction)))
    return f"{1.0 + 4.0 * clamped:.2f}"


def _rationale_map(distractors: list[dict[str, Any]]) -> dict[str, str]:
    """The ``{letter: rationale}`` map the Study surface consumes.

    The bundle keeps each distractor's misconception tag alongside its rationale;
    the note field only needs the letter->text map (the misconception tags stay
    in the bundle as review provenance). Never includes the correct letter.
    """
    return {d["label"]: d["rationale"] for d in distractors}


def tutor_field(item: dict[str, Any]) -> str:
    """The JSON string stored in ``decomposition_tutor`` for a bundle item.

    Normalizes a bundle record's ``decomposition_tutor`` (or its absence) to the
    ``{"subproblems": [...], "parent_variants": [...]}`` shape the runtime reads,
    so a problem without generated decompositions stores a well-formed empty blob
    rather than nothing. Both the seed path and the generation path go through
    here, so a curated and a generated problem carry the tutor data the same way.
    """
    tutor = item.get("decomposition_tutor")
    if not isinstance(tutor, dict):
        tutor = {}
    subproblems = tutor.get("subproblems")
    parent_variants = tutor.get("parent_variants")
    normalized: dict[str, Any] = {
        "subproblems": subproblems if isinstance(subproblems, list) else [],
    }
    if isinstance(parent_variants, list) and parent_variants:
        normalized["parent_variants"] = parent_variants
    return json.dumps(normalized, ensure_ascii=False)


def seed_sample_problems(col: Collection) -> int:
    """Idempotently seed the bundled Problems; return how many were created.

    Creates the ``pgrep::Problem`` notetype (if missing) and one Problem per
    entry in :data:`BUNDLE_PROBLEMS`, each tagged ``pgrep::problem-seed`` plus
    its ``topic::<category>`` tag, with its cards in the ``PGRE::Problems`` deck.
    A marker tag makes repeat calls a no-op (returns ``0``). The whole seed is
    one undoable action; new notes cold-start FSRS.
    """
    from anki.collection import AddNoteRequest

    notetype = ensure_problem_notetype(col)
    deck_id = col.decks.id(PROBLEM_DECK_NAME)
    assert deck_id is not None

    # Idempotency guard: if any seeded Problem exists, do nothing further.
    if col.find_notes(f"tag:{PROBLEM_SEED_TAG}"):
        return 0

    undo_id = col.add_custom_undo_entry("Seed pgrep sample problems")

    requests: list[AddNoteRequest] = []
    for item in BUNDLE_PROBLEMS:
        note = col.new_note(notetype)
        note[FIELD_STEM] = item["stem"]
        note[FIELD_CHOICES] = json.dumps(list(item["choices"]), ensure_ascii=False)
        note[FIELD_CORRECT] = item["correct"]
        note[FIELD_DISTRACTOR_RATIONALES] = json.dumps(
            _rationale_map(item["distractors"]), ensure_ascii=False, sort_keys=True
        )
        note[FIELD_SOLUTION_DECOMPOSITION] = json.dumps(
            item["solution_decomposition"], ensure_ascii=False
        )
        note[FIELD_DIFFICULTY] = difficulty_field(item.get("difficulty"))
        # Real provenance where the corpus supplied it; empty for the handful of
        # triage-KEEP items the generator left uncited (physics re-derived in P4).
        note[FIELD_SOURCE_REF] = item.get("source_ref") or ""
        # Pre-generated gated tutor data (empty blob when the item has none yet).
        note[FIELD_DECOMPOSITION_TUTOR] = tutor_field(item)
        # Marker tag first (idempotency); the topic tag is the only topic:: tag.
        note.tags = [PROBLEM_SEED_TAG, item["topic"]]
        requests.append(AddNoteRequest(note=note, deck_id=deck_id))

    col.add_notes(requests)
    col.merge_undo_entries(undo_id)

    return len(requests)
