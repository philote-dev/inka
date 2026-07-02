# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""The ``pgrep::Problem`` notetype and sample problems (L2.1 Study).

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

:func:`seed_sample_problems` idempotently seeds a handful of real problems spread
across categories into a ``PGRE::Problems`` deck; a marker tag makes repeat calls
a no-op. The scaffolding ``pgrep_seed`` handler calls it opportunistically.
"""

from __future__ import annotations

import json
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
PROBLEM_FIELDS: tuple[str, ...] = (
    FIELD_STEM,
    FIELD_CHOICES,
    FIELD_CORRECT,
    FIELD_DISTRACTOR_RATIONALES,
    FIELD_SOLUTION_DECOMPOSITION,
    FIELD_DIFFICULTY,
    FIELD_SOURCE_REF,
)

# The option letters a Problem may use, in order.
CHOICE_LETTERS: tuple[str, ...] = ("A", "B", "C", "D", "E")


# Notetype bootstrap
##########################################################################


def get_problem_notetype(col: Collection) -> NotetypeDict | None:
    """The ``pgrep::Problem`` notetype, or ``None`` if it doesn't exist yet."""
    return col.models.by_name(PROBLEM_NOTETYPE_NAME)


def ensure_problem_notetype(col: Collection) -> NotetypeDict:
    """Return the ``pgrep::Problem`` notetype, creating it if missing.

    Mirrors ``attempt_log.ensure_attempt_notetype``: seven fields in the
    contract order, ``stem`` as the sort field, and a single trivial card
    template (Problems are rendered by the Study surface from their fields, not
    by Anki's card templates, but Anki requires at least one template).
    """
    existing = get_problem_notetype(col)
    if existing:
        return existing

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


# Sample problems (the AI-off ladder data)
##########################################################################

# (category, stem, choices A..E, correct letter, {distractor letter: why it is
# wrong}, [(subgoal, rubric), ...]). The distractor rationales never name the
# correct option, and no sub-goal/rubric states the final answer, so the final
# answer only ever appears in the reveal rung that ``study.commit_problem``
# builds. Real physics, text only (unicode, no media, no MathJax required).
_SAMPLE_PROBLEMS: tuple[
    tuple[
        str,
        str,
        tuple[str, str, str, str, str],
        str,
        dict[str, str],
        tuple[tuple[str, str], ...],
    ],
    ...,
] = (
    (
        "mechanics",
        "A ball is dropped from rest and falls freely for 3.0 s near Earth's "
        "surface. Ignoring air resistance and taking g \u2248 10 m/s\u00b2, "
        "how far does it fall?",
        ("5 m", "15 m", "30 m", "45 m", "90 m"),
        "D",
        {
            "A": "Dropped g and used only \u00bd t\u00b2. The acceleration has "
            "to appear in the displacement.",
            "B": "Used \u00bd g t, so the time was not squared. Free-fall "
            "distance grows with t\u00b2.",
            "C": "That is the speed g t reached after 3.0 s, not the distance "
            "travelled.",
            "E": "Used g t\u00b2 but dropped the factor of \u00bd.",
        },
        (
            (
                "Pick the right kinematics relation",
                "Chooses d = \u00bd g t\u00b2 for motion from rest (initial "
                "speed zero).",
            ),
            (
                "Substitute the given values",
                "Uses g \u2248 10 m/s\u00b2 and t = 3.0 s, and squares the time.",
            ),
        ),
    ),
    (
        "electromagnetism",
        "Two point charges of +2 \u03bcC each are held 1.0 m apart in vacuum. "
        "With k \u2248 9\u00d710\u2079 N\u00b7m\u00b2/C\u00b2, the magnitude of "
        "the force between them is closest to",
        ("0.018 N", "0.036 N", "0.072 N", "3.6 N", "36 N"),
        "B",
        {
            "A": "Halved the result, as if only one charge entered the "
            "numerator. Both charge magnitudes multiply.",
            "C": "Doubled the force, as if the charges added instead of "
            "multiplying in Coulomb's law.",
            "D": "Mishandled the micro prefix, since (10\u207b\u2076)\u00b2 is "
            "10\u207b\u00b9\u00b2, not 10\u207b\u2076.",
            "E": "Kept only one factor of 10\u207b\u2076 instead of squaring it.",
        },
        (
            (
                "Choose the force law",
                "Writes Coulomb's law F = k q\u2081 q\u2082 / r\u00b2.",
            ),
            (
                "Convert the charges",
                "Uses q = 2\u00d710\u207b\u2076 C for each charge and r = 1.0 m.",
            ),
            (
                "Handle the powers of ten",
                "Combines 9\u00d710\u2079 with (2\u00d710\u207b\u2076)\u00b2 = "
                "4\u00d710\u207b\u00b9\u00b2.",
            ),
        ),
    ),
    (
        "quantum",
        "An electron is confined to a one-dimensional infinite square well. Its "
        "ground-state energy is E\u2081. What is the energy of the n = 3 level?",
        ("3 E\u2081", "4 E\u2081", "6 E\u2081", "9 E\u2081", "27 E\u2081"),
        "D",
        {
            "A": "Took energy proportional to n. The infinite-well levels grow "
            "with n\u00b2, not n.",
            "B": "Squared the wrong level (n = 2 gives 4 E\u2081).",
            "C": "Used 2n or added levels instead of squaring n.",
            "E": "Used n\u00b3; the infinite-well spectrum goes as n\u00b2.",
        },
        (
            (
                "Recall the spectrum",
                "States E_n = n\u00b2 E\u2081 for the infinite square well.",
            ),
            (
                "Insert the level",
                "Sets n = 3 and squares it before multiplying by E\u2081.",
            ),
        ),
    ),
    (
        "thermodynamics",
        "A Carnot engine runs between reservoirs at 400 K and 300 K. Its maximum "
        "theoretical efficiency is closest to",
        ("25%", "33%", "57%", "75%", "133%"),
        "A",
        {
            "B": "Divided the temperature difference by the cold reservoir "
            "(\u0394T/T_c) instead of the hot one.",
            "C": "Mixed Celsius and Kelvin in the ratio.",
            "D": "This is T_c/T_h; the efficiency is one minus that ratio.",
            "E": "Inverted the ratio to T_h/T_c, which cannot be an efficiency.",
        },
        (
            (
                "Recall Carnot efficiency",
                "Writes \u03b7 = 1 \u2212 T_c/T_h with absolute temperatures.",
            ),
            (
                "Substitute in Kelvin",
                "Uses T_c = 300 K and T_h = 400 K (no Celsius).",
            ),
        ),
    ),
    (
        "optics_waves",
        "In a double-slit experiment with slit separation d, light of "
        "wavelength \u03bb gives first-order maxima at angle \u03b8. If the "
        "wavelength is doubled at fixed d, sin \u03b8 for the first order",
        (
            "is halved",
            "is unchanged",
            "doubles",
            "quadruples",
            "falls to zero",
        ),
        "C",
        {
            "A": "Treated sin \u03b8 as proportional to 1/\u03bb, which is "
            "backwards for the maxima condition.",
            "B": "Assumed the angle does not depend on wavelength, but it does.",
            "D": "Used a \u03bb\u00b2 dependence; the relation is linear in "
            "\u03bb.",
            "E": "Confused the bright-fringe condition with a dark-fringe one.",
        },
        (
            (
                "Write the maxima condition",
                "States d sin \u03b8 = m \u03bb for bright fringes.",
            ),
            (
                "Isolate the wavelength",
                "Rearranges to sin \u03b8 = m \u03bb / d, so sin \u03b8 \u221d "
                "\u03bb at fixed d and m.",
            ),
        ),
    ),
    (
        "atomic",
        "A photon has wavelength 500 nm. Using h c \u2248 1240 eV\u00b7nm, its "
        "energy is closest to",
        ("0.40 eV", "1.24 eV", "2.48 eV", "4.96 eV", "620 eV"),
        "C",
        {
            "A": "Computed \u03bb / (h c), inverting the ratio.",
            "B": "Divided by the wrong wavelength (used ~1000 nm).",
            "D": "Halved the wavelength (used 250 nm).",
            "E": "Multiplied h c by \u03bb instead of dividing.",
        },
        (
            (
                "Choose the photon relation",
                "Writes E = h c / \u03bb.",
            ),
            (
                "Use the handy constant",
                "Uses h c \u2248 1240 eV\u00b7nm with \u03bb in nm.",
            ),
        ),
    ),
)


def seed_sample_problems(col: Collection) -> int:
    """Idempotently seed the sample Problems; return how many were created.

    Creates the ``pgrep::Problem`` notetype (if missing) and one Problem per
    entry in :data:`_SAMPLE_PROBLEMS`, each tagged ``pgrep::problem-seed`` plus
    its ``topic::<category>`` tag, with its cards in the ``PGRE::Problems`` deck.
    A marker tag makes repeat calls a no-op (returns ``0``). The whole seed is
    one undoable action.
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
    for category, stem, choices, correct, rationales, decomposition in _SAMPLE_PROBLEMS:
        note = col.new_note(notetype)
        note[FIELD_STEM] = stem
        note[FIELD_CHOICES] = json.dumps(list(choices), ensure_ascii=False)
        note[FIELD_CORRECT] = correct
        note[FIELD_DISTRACTOR_RATIONALES] = json.dumps(
            rationales, ensure_ascii=False, sort_keys=True
        )
        note[FIELD_SOLUTION_DECOMPOSITION] = json.dumps(
            [{"subgoal": subgoal, "rubric": rubric} for subgoal, rubric in decomposition],
            ensure_ascii=False,
        )
        note[FIELD_DIFFICULTY] = "medium"
        note[FIELD_SOURCE_REF] = "pgrep-sample"
        # Marker tag first (idempotency); the topic tag is the only topic:: tag.
        note.tags = [PROBLEM_SEED_TAG, f"{TOPIC_PREFIX}{category}"]
        requests.append(AddNoteRequest(note=note, deck_id=deck_id))

    col.add_notes(requests)
    col.merge_undo_entries(undo_id)

    return len(requests)
