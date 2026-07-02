# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""The two-door study loop (Cards and Problems) for pgrep.

**Stub — implemented by the L2.1 Study surface.**

The scaffolding bridge handlers ``pgrep_study_start``, ``pgrep_study_next``,
``pgrep_study_answer_card`` and ``pgrep_study_commit`` in ``qt/aqt/pgrep.py``
already call the functions below; L2.1 fills in the bodies. Do not change the
signatures — the four surfaces coordinate through the fixed handler contract.

See ``docs/pgrep/planning/l2-api-contract.md`` §3 (L2.1) for the request and
response shapes, ``feature-interleaving.md`` for the two-door session, and
``feature-productive-failure.md`` for the commit gate and ladder. No AI, no
confidence capture, no predict-before-answer; ordering is reused via the L1
points-at-stake selector and the schedule state is never mutated by hand.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from anki.collection import Collection


def start_session(col: Collection, door: str, topic: str | None = None) -> dict:
    """Begin or scope a study session for one door.

    ``door`` is ``"cards"`` or ``"problems"``; ``topic`` scopes a focus drill
    (cross-topic interleaving off) when given. The result matches the
    ``pgrepStudyStart`` response in the L2 API contract (§3, L2.1).

    Raises:
        NotImplementedError: until the L2.1 Study surface implements it.
    """
    raise NotImplementedError("implemented by L2.1 Study")


def next_item(col: Collection, session_id: str | None = None) -> dict:
    """Return the next item for the session, with no help revealed.

    The result matches the ``pgrepStudyNext`` response in the L2 API contract
    (§3, L2.1): a ``card``, a ``problem`` (answer withheld behind the commit
    gate), or ``empty`` when the door is exhausted.

    Raises:
        NotImplementedError: until the L2.1 Study surface implements it.
    """
    raise NotImplementedError("implemented by L2.1 Study")


def answer_card(col: Collection, card_id: int, rating: int) -> dict:
    """Grade a Cards-door card after its answer was revealed.

    ``rating`` is 1..4 (Again/Hard/Good/Easy) and is applied via
    ``col.sched.answer_card``. The result matches the ``pgrepStudyAnswerCard``
    response in the L2 API contract (§3, L2.1).

    Raises:
        NotImplementedError: until the L2.1 Study surface implements it.
    """
    raise NotImplementedError("implemented by L2.1 Study")


def commit_problem(
    col: Collection, note_id: int, session_id: str, selected: str
) -> dict:
    """Commit a Problems-door answer before any help is shown.

    ``selected`` is the chosen option letter. The commit appends one immutable
    Attempt note via ``anki.pgrep.attempt_log`` and returns the correctness,
    rationale, and the static solution ladder. The result matches the
    ``pgrepStudyCommit`` response in the L2 API contract (§3, L2.1).

    Raises:
        NotImplementedError: until the L2.1 Study surface implements it.
    """
    raise NotImplementedError("implemented by L2.1 Study")
