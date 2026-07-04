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
(``docs_pgrep/plan/l2-api-contract.md`` §3): the four surfaces implement the
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


# L4 AI (upgrade only; AI off by default). Handlers lazily import the AI modules,
# so an AI-off app never loads the heavy deps.


def pgrep_ai_status() -> bytes:
    from anki.pgrep import ai_config

    return _json(ai_config.ai_status(aqt.mw.col))


def pgrep_ai_set_enabled() -> bytes:
    from anki.pgrep import ai_config

    enabled = bool(_args().get("enabled", False))
    ai_config.set_ai_enabled(aqt.mw.col, enabled)
    return _json(ai_config.ai_status(aqt.mw.col))


# L4.1 Library -> anki.pgrep.generation.generate (author seed, then stylize/gap-fill)
def pgrep_library_generate() -> bytes:
    from anki.pgrep import generation

    a = _args()
    return _json(
        generation.generate(
            aqt.mw.col,
            mode=a.get("mode", "gap_fill"),
            topic=a.get("topic", ""),
            seed_front=a.get("seed_front", ""),
            seed_back=a.get("seed_back", ""),
            n=int(a.get("n", generation.DEFAULT_GAPFILL_N)),
        )
    )


# L4.2 Problem generation -> anki.pgrep.problem_gen.generate (misconception-first)
def pgrep_problem_generate() -> bytes:
    from anki.pgrep import problem_gen

    a = _args()
    return _json(
        problem_gen.generate(
            aqt.mw.col, topic=a.get("topic", ""), n=int(a.get("n", problem_gen.DEFAULT_N))
        )
    )


# L4.3 Tutor -> anki.pgrep.tutor.grade_subgoal (AI-on rubric grading, giveaway-safe)
def pgrep_tutor_grade() -> bytes:
    from anki.pgrep import tutor

    a = _args()
    return _json(
        tutor.grade_subgoal(
            aqt.mw.col,
            a.get("note_id"),
            int(a.get("subgoal_index", 0)),
            a.get("learner_text", ""),
            a.get("learner_why", ""),
        )
    )


# L4.3 Tutor -> anki.pgrep.tutor.session_synthesis (end-of-session recap)
def pgrep_tutor_synthesis() -> bytes:
    from anki.pgrep import tutor

    return _json(tutor.session_synthesis(aqt.mw.col, _args().get("session_id", "")))


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
    pgrep_ai_status,
    pgrep_ai_set_enabled,
    pgrep_library_generate,
    pgrep_problem_generate,
    pgrep_tutor_grade,
    pgrep_tutor_synthesis,
]
