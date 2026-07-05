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
(``docs_pgrep/contracts/L2-api-contract.md`` §3): the four surfaces implement the
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


# L5.2 Progress / Performance -> anki.pgrep.performance.performance_score
def pgrep_performance_score() -> bytes:
    from anki.pgrep import performance

    return _json(
        performance.performance_score(aqt.mw.col, deck_id=_args().get("deck_id"))
    )


# L5.3 Progress / Readiness -> anki.pgrep.readiness.readiness_score
def pgrep_readiness_score() -> bytes:
    from anki.pgrep import readiness

    # deck_id scopes only the mastery (FSRS) component, mirroring memory and
    # performance. The attempt log Readiness leans on is always collection-wide.
    return _json(readiness.readiness_score(aqt.mw.col, deck_id=_args().get("deck_id")))


# L5.5 Progress / Calibration -> anki.pgrep.calibration_evidence (embedded, no col)
def pgrep_calibration() -> bytes:
    from anki.pgrep import calibration_evidence

    return _json(calibration_evidence.calibration_evidence())


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
            aqt.mw.col,
            topic=a.get("topic", ""),
            n=int(a.get("n", problem_gen.DEFAULT_N)),
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


# Desktop sync. Reuses Anki's own main-thread sync flow (aqt.sync) against the
# self-hosted server, so progress and the full-sync direction dialog are handled
# for us and nothing on the mediasrv thread touches the open collection unsafely.
# Points the profile at the given custom URL, logs in if there is no stored key,
# then runs the standard sync. Returns immediately; the visible completion is
# Anki's own progress dialog and "sync complete" tooltip.
def pgrep_sync() -> bytes:
    import aqt.sync

    mw = aqt.mw
    a = _args()
    url = (a.get("url") or "http://127.0.0.1:8090/").strip()
    username = a.get("username") or "pgrep"
    password = a.get("password") or "pgrep"

    def start() -> None:
        mw.pm.set_custom_sync_url(url)
        if mw.pm.sync_auth() is None:

            def do_login() -> Any:
                return mw.col.sync_login(
                    username=username, password=password, endpoint=url
                )

            def logged_in(fut: Any) -> None:
                try:
                    auth = fut.result()
                except Exception as err:  # noqa: BLE001
                    aqt.sync.handle_sync_error(mw, err)
                    return
                mw.pm.set_sync_key(auth.hkey)
                mw.pm.set_sync_username(username)
                aqt.sync.sync_collection(mw, lambda: None)

            mw.taskman.with_progress(
                do_login, logged_in, parent=mw, label="Logging in to sync server"
            )
        else:
            aqt.sync.sync_collection(mw, lambda: None)

    mw.taskman.run_on_main(start)
    return _json({"status": "started", "url": url})


# Dev-only (pgrep-lab, L5.9 P5). Injects or clears a clearly-marked hypothetical
# demo profile so the three scores light up on demand for hands-on testing and
# the desktop-to-mobile sync demo. This is NOT wired into any shipped user
# surface (Home, Study, Progress, Diagnostic, Library, Settings); it is reachable
# only from the pgrep-lab dev gallery. Real accounts never call it, so they still
# abstain by construction. Always returns the current status (with a scores
# snapshot) so the lab can show the result of the action immediately.
def pgrep_demo_profile() -> bytes:
    from anki.pgrep import demo_profile

    args = _args()
    action = args.get("action", "status")
    if action == "inject":
        demo_profile.inject_demo_profile(
            aqt.mw.col, profile=args.get("profile", demo_profile.DEFAULT_PROFILE)
        )
    elif action == "clear":
        demo_profile.clear_demo_profile(aqt.mw.col)
    return _json(demo_profile.demo_status(aqt.mw.col))


# L5.9 Settings. The get/set handlers read and write only the open collection's
# config and the sample deck's config, so they are safe on the mediasrv thread.
# Export must close and reopen the collection, so it runs on the main thread via
# QueryOp, exactly like Anki's own colpkg export.


def pgrep_settings_get() -> bytes:
    from anki.pgrep import settings

    return _json(settings.get_settings(aqt.mw.col))


def pgrep_settings_set() -> bytes:
    from anki.pgrep import settings

    return _json(settings.apply_settings(aqt.mw.col, _args()))


# Data / Export. Writes a timestamped .colpkg (cards, media, and the attempt
# notes) to a user-visible folder and reports the path. Reuses Anki's own
# collection-package export, run on the main thread with the same close/reopen
# dance the desktop exporter uses, so nothing on the mediasrv thread touches the
# collection while it is temporarily closed.
def pgrep_export() -> bytes:
    from anki.pgrep import settings
    from aqt import gui_hooks
    from aqt.operations import QueryOp
    from aqt.utils import showWarning, tooltip

    mw = aqt.mw
    out_path = settings.default_export_path()

    def start() -> None:
        def on_success(_: None) -> None:
            mw.reopen()
            tooltip(f"Exported to {out_path}", parent=mw)

        def on_failure(exc: Exception) -> None:
            mw.reopen()
            showWarning(str(exc), parent=mw)

        gui_hooks.collection_will_temporarily_close(mw.col)
        QueryOp(
            parent=mw,
            op=lambda col: col.export_collection_package(
                out_path, include_media=True, legacy=False
            ),
            success=on_success,
        ).with_progress("Exporting your collection").failure(
            on_failure
        ).run_in_background()

    mw.taskman.run_on_main(start)
    return _json({"status": "started", "path": out_path})


# Data / Reset. Conservative and scoped: deletes the pgrep attempt notes and
# forgets the seeded sample cards back to new. Settings, notetypes, decks, and
# all other content (including AI-generated Library cards and Problems) are left
# intact; the collection is never wiped. This is a normal collection write, like
# the study handlers, so it runs on the mediasrv thread. The destructive intent
# is gated by the two-step confirmation on the Settings surface.
def pgrep_reset() -> bytes:
    from anki.pgrep import settings

    return _json(settings.reset_progress(aqt.mw.col))


# Registered once into mediasrv's post_handler_list (see qt/aqt/mediasrv.py).
pgrep_post_handlers = [
    pgrep_seed,
    pgrep_memory_score,
    pgrep_coverage,
    pgrep_performance_score,
    pgrep_readiness_score,
    pgrep_calibration,
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
    pgrep_sync,
    pgrep_demo_profile,
    pgrep_settings_get,
    pgrep_settings_set,
    pgrep_export,
    pgrep_reset,
]
