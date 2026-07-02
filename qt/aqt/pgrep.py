# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""The pgrep JSON bridge (Channel B) between the web surfaces and the engine.

Each handler is a plain ``mediasrv`` POST handler registered once (in
``qt/aqt/mediasrv.py``). ``mediasrv`` camelCases the function name, so
``pgrep_memory_score`` is reachable at ``POST /_anki/pgrepMemoryScore``. A
handler reads the JSON request body, lazily imports the relevant
``anki.pgrep.*`` module (so a not-yet-implemented surface never breaks app
startup), calls the mapped pure-Python function on ``aqt.mw.col``, and returns
JSON bytes (``mediasrv`` wraps the bytes into an ``application/binary``
response).

The handler names and the function each calls are fixed by the L2 API contract
(``docs/pgrep/planning/l2-api-contract.md`` §3): the four surfaces implement the
``anki.pgrep.*`` bodies these handlers already call, so no surface edits this
file after scaffolding.
"""

from __future__ import annotations

import json
from typing import Any

from flask import request

import aqt


def _args() -> dict[str, Any]:
    """Parse the JSON request body into a dict (empty body -> ``{}``)."""
    return json.loads(request.data or b"{}")


def _json(result: Any) -> bytes:
    return json.dumps(result).encode("utf-8")


# Scaffolding-owned. seed_sample_content is fully implemented; sample Problems
# are seeded opportunistically once L2.1 provides them.
def pgrep_seed() -> bytes:
    from anki.pgrep import seed

    result = seed.seed_sample_content(aqt.mw.col)
    try:
        from anki.pgrep import problem

        result["problems_created"] = problem.seed_sample_problems(aqt.mw.col)
    except (NotImplementedError, ImportError):
        pass
    return _json(result)


# L2.2 Home / Readiness -> anki.pgrep.memory.memory_score
def pgrep_memory_score() -> bytes:
    from anki.pgrep import memory

    return _json(memory.memory_score(aqt.mw.col, deck_id=_args().get("deck_id")))


# L2.4 Progress / Coverage -> anki.pgrep.coverage.coverage
def pgrep_coverage() -> bytes:
    from anki.pgrep import coverage

    return _json(coverage.coverage(aqt.mw.col))


# L2.3 Diagnostic -> anki.pgrep.diagnostic.topics
def pgrep_diagnostic_topics() -> bytes:
    from anki.pgrep import diagnostic

    return _json(diagnostic.topics(aqt.mw.col))


# L2.3 Diagnostic -> anki.pgrep.diagnostic.place
def pgrep_diagnostic_place() -> bytes:
    from anki.pgrep import diagnostic

    return _json(diagnostic.place(aqt.mw.col, _args().get("results", [])))


# L2.1 Study -> anki.pgrep.study.start_session
def pgrep_study_start() -> bytes:
    from anki.pgrep import study

    args = _args()
    return _json(
        study.start_session(aqt.mw.col, args.get("door", "cards"), args.get("topic"))
    )


# L2.1 Study -> anki.pgrep.study.next_item
def pgrep_study_next() -> bytes:
    from anki.pgrep import study

    return _json(study.next_item(aqt.mw.col, _args().get("session_id")))


# L2.1 Study (Cards door) -> anki.pgrep.study.answer_card
def pgrep_study_answer_card() -> bytes:
    from anki.pgrep import study

    args = _args()
    return _json(study.answer_card(aqt.mw.col, args.get("card_id"), args.get("rating")))


# L2.1 Study (Problems door) -> anki.pgrep.study.commit_problem
def pgrep_study_commit() -> bytes:
    from anki.pgrep import study

    args = _args()
    return _json(
        study.commit_problem(
            aqt.mw.col,
            args.get("note_id"),
            args.get("session_id"),
            args.get("selected"),
        )
    )


# Registered once into mediasrv's post_handler_list (see qt/aqt/mediasrv.py).
pgrep_post_handlers = [
    pgrep_seed,
    pgrep_memory_score,
    pgrep_coverage,
    pgrep_diagnostic_topics,
    pgrep_diagnostic_place,
    pgrep_study_start,
    pgrep_study_next,
    pgrep_study_answer_card,
    pgrep_study_commit,
]
