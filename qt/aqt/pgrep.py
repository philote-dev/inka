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

The L2 core handlers were scaffolded from the L2 API contract
(``docs_pgrep/reference/api-contract.md`` §3), whose four surfaces call the
``anki.pgrep.*`` bodies mapped here. Later L5.9 features append their own
handlers to this file as they land, including Exam mode, Settings (with export
and reset), the dev-only demo profile, and the Diagnostic completion gate. Each
new handler follows the same register-once pattern and is added to
``pgrep_post_handlers`` below.
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


# Dev harness -> anki.pgrep.seed.restart_sample_cards. Refill the sample Cards
# door so a demo always has cards: seed if needed, lift the sample deck's daily
# caps, and forget the seeded cards back to new. Also (re)seeds the sample
# Problems, mirroring pgrep_seed, so one call refills both doors. A normal
# collection write, safe on the mediasrv thread like the study handlers.
def pgrep_restart_cards() -> bytes:
    from anki.pgrep import seed

    result = seed.restart_sample_cards(aqt.mw.col)
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


# L5.9 Home / knowledge manifold -> anki.pgrep.manifold.manifold_surface
def pgrep_manifold() -> bytes:
    from anki.pgrep import manifold

    return _json(manifold.manifold_surface(aqt.mw.col, deck_id=_args().get("deck_id")))


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
            # M5 seam: the client-measured time from item shown to commit.
            response_ms=args.get("response_ms"),
        )
    )


# L5.9 Exam mode (timed mock over Problems) -> anki.pgrep.exam
def pgrep_exam_start() -> bytes:
    from anki.pgrep import exam

    args = _args()
    return _json(
        exam.start_exam(
            aqt.mw.col,
            question_count=args.get("question_count"),
            section=bool(args.get("section", False)),
        )
    )


def pgrep_exam_next() -> bytes:
    from anki.pgrep import exam

    args = _args()
    return _json(
        exam.next_exam_item(aqt.mw.col, args.get("session_id"), args.get("index"))
    )


# Records a selection, its response_ms, and the flag. Blind: nothing is graded or
# revealed here, and nothing hits the attempt log until pgrep_exam_result finishes.
def pgrep_exam_answer() -> bytes:
    from anki.pgrep import exam

    args = _args()
    return _json(
        exam.answer_exam_item(
            aqt.mw.col,
            args.get("session_id"),
            int(args.get("index", 0)),
            args.get("selected", ""),
            response_ms=args.get("response_ms"),
            flagged=args.get("flagged"),
        )
    )


# Finishes the exam: appends one clean, committed, timed Attempt per answered item
# (idempotent), then returns the projected scaled Readiness score + range + pace.
def pgrep_exam_result() -> bytes:
    from anki.pgrep import exam

    return _json(exam.finish_exam(aqt.mw.col, _args().get("session_id")))


# L4 AI (upgrade; desktop first-run default is on via ensure_first_run_defaults).
# Handlers lazily import the AI modules, so an AI-off app never loads the heavy deps.


def pgrep_ai_status() -> bytes:
    from anki.pgrep import ai_config

    # First AI-status read applies the collection's first-run defaults (AI on),
    # so onboarding lands on the calibration-paramount path. Idempotent.
    ai_config.ensure_first_run_defaults(aqt.mw.col)
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


# Dev harness -> anki.pgrep.tutor.session_synthesis_preview. The consolidation
# screen on a small fixed sample, so the dev lab can tune it without a session.
def pgrep_tutor_synthesis_preview() -> bytes:
    from anki.pgrep import tutor

    return _json(tutor.session_synthesis_preview(aqt.mw.col))


# Decomposition tutor (Problems miss) -> anki.pgrep.decomposition.check_mcq.
# Grades one subproblem's MCQ pick; withholds the key on a wrong pick (unlimited
# retries), reveals the model rationale on a correct one. No API call.
def pgrep_tutor_mcq() -> bytes:
    from anki.pgrep import decomposition

    a = _args()
    return _json(
        decomposition.check_mcq(
            aqt.mw.col,
            a.get("note_id"),
            int(a.get("subgoal_index", 0)),
            int(a.get("variant_index", 0)),
            a.get("selected", ""),
        )
    )


# Decomposition tutor (Problems miss) -> anki.pgrep.decomposition.grade_explanation.
# AI-on only: lenient "good enough" pass/fail on the free-text "explain why", with
# a giveaway guard so feedback never leaks the parent answer. AI off never calls it.
def pgrep_tutor_explain() -> bytes:
    from anki.pgrep import decomposition

    a = _args()
    return _json(
        decomposition.grade_explanation(
            aqt.mw.col,
            a.get("note_id"),
            int(a.get("subgoal_index", 0)),
            int(a.get("variant_index", 0)),
            a.get("learner_text", ""),
        )
    )


# Decomposition tutor dev harness -> anki.pgrep.decomposition.refresh_tutor_data.
# Seeds the bundled Problems if absent and refreshes their tutor data from the
# current bundle, so a stale collection can run the tutor. Dev-only; writes notes.
def pgrep_tutor_seed() -> bytes:
    from anki.pgrep import decomposition

    return _json(decomposition.refresh_tutor_data(aqt.mw.col))


# Decomposition tutor dev harness -> anki.pgrep.decomposition.list_tutor_problems.
# Read-only list of problems that have a usable decomposition, for the dev lab.
def pgrep_tutor_list() -> bytes:
    from anki.pgrep import decomposition

    return _json({"problems": decomposition.list_tutor_problems(aqt.mw.col)})


# Decomposition tutor dev harness -> anki.pgrep.decomposition.load_tutor.
# Loads a chosen problem's subproblems (answers withheld) plus the parent stem for
# context, so the dev lab can run the tutor without a real miss.
def pgrep_tutor_load() -> bytes:
    from anki.notes import NoteId
    from anki.pgrep import decomposition, problem

    a = _args()
    note_id = a.get("note_id")
    data = decomposition.load_tutor(aqt.mw.col, note_id, int(a.get("round_index", 0)))
    try:
        note = aqt.mw.col.get_note(NoteId(int(note_id)))
        data["parent_stem_html"] = (
            str(note[problem.FIELD_STEM]) if problem.FIELD_STEM in note else ""
        )
    except Exception:  # noqa: BLE001 - harness context only, never blocks
        data["parent_stem_html"] = ""
    return _json(data)


# Desktop sync. Reuses Anki's own main-thread sync flow (aqt.sync) against the
# self-hosted server, while the product SyncUi reports progress and full-sync
# decisions inside the shell. Nothing on the mediasrv thread touches the open
# collection unsafely.
# Points the profile at the given custom URL, logs in if there is no stored key,
# then runs the standard sync. Returns immediately with the operation ID.
def pgrep_sync() -> bytes:
    import aqt.sync
    from aqt.pgrep_operation import ProductSyncUi

    mw = aqt.mw
    a = _args()
    # 8090, not 8080: `just run` holds 8080 for the Qt remote-debug/hot-reload
    # server, so the self-hosted sync server uses its own port (see just sync-server).
    url = (a.get("url") or "http://127.0.0.1:8090/").strip()
    username = a.get("username") or "pgrep"
    password = a.get("password") or "pgrep"
    ui = ProductSyncUi(mw)
    if not ui.started:
        return _json({"status": "busy", "operation_id": ui.operation_id})

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
                    ui.error(err)
                    return
                mw.pm.set_sync_key(auth.hkey)
                mw.pm.set_sync_username(username)
                aqt.sync.sync_collection(mw, lambda: None, ui=ui)

            ui.run_task(do_login, logged_in, message="Signing in")
        else:
            aqt.sync.sync_collection(mw, lambda: None, ui=ui)

    mw.taskman.run_on_main(start)
    return _json({"status": "started", "url": url, "operation_id": ui.operation_id})


def _operation_controller():
    # Import the module, rather than binding the singleton at import time, so
    # tests and future profile reloads can replace it safely.
    from aqt import pgrep_operation

    return pgrep_operation.operation_controller


def _wake_operation() -> None:
    from aqt import pgrep_host

    pgrep_host.notify_operation_changed(aqt.mw)


def pgrep_operation_status() -> bytes:
    return _json(_operation_controller().snapshot())


def pgrep_operation_resolve() -> bytes:
    controller = _operation_controller()
    a = _args()
    try:
        operation_id = int(a.get("operation_id"))
    except (TypeError, ValueError):
        return _json({"ok": False})
    choice = str(a.get("choice") or "")
    snapshot = controller.snapshot()
    decision = snapshot.get("decision")
    valid = (
        snapshot["operation_id"] == operation_id
        and snapshot["phase"] == "decision"
        and decision is not None
        and choice in {candidate["id"] for candidate in decision["choices"]}
    )
    if not valid:
        return _json({"ok": False})

    def resolve() -> None:
        controller.resolve(operation_id, choice)
        _wake_operation()

    aqt.mw.taskman.run_on_main(resolve)
    return _json({"ok": True})


def pgrep_operation_cancel() -> bytes:
    controller = _operation_controller()
    a = _args()
    try:
        operation_id = int(a.get("operation_id"))
    except (TypeError, ValueError):
        return _json({"ok": False})
    snapshot = controller.snapshot()
    valid = (
        snapshot["operation_id"] == operation_id
        and snapshot["phase"] == "active"
        and snapshot["cancellable"]
    )
    if not valid:
        return _json({"ok": False})

    def cancel() -> None:
        controller.cancel(operation_id)
        _wake_operation()

    aqt.mw.taskman.run_on_main(cancel)
    return _json({"ok": True})


def pgrep_operation_dismiss() -> bytes:
    controller = _operation_controller()
    a = _args()
    try:
        operation_id = int(a.get("operation_id"))
    except (TypeError, ValueError):
        return _json({"ok": False})
    ok = controller.dismiss(operation_id)
    if ok:
        aqt.mw.taskman.run_on_main(_wake_operation)
    return _json({"ok": ok})


# --- pgrep first-run login gate (beta) --------------------------------------
# The gate greets a new or signed-out user before Home (migration plan in
# docs_pgrep/plan/login-gate-beta-handoff.md). It reuses the existing Anki sync
# account model, inventing no new auth stack. "Continue offline" is remembered
# per-device in the profile manager's global meta (never synced); signing in
# resolves the gate everywhere via the stored sync key. Offline-first is
# untouched: study and AI-off scoring never call any of these.

# Set when the user chooses "Continue offline", so the gate does not nag on every
# cold start. Lives in the global (per-device) meta, not the synced collection.
_LOGIN_GATE_SKIPPED_META_KEY = "pgrep_login_gate_skipped"


def pgrep_auth_status() -> bytes:
    mw = aqt.mw
    signed_in = mw.pm.sync_auth() is not None
    skipped = bool(mw.pm.meta.get(_LOGIN_GATE_SKIPPED_META_KEY, False))
    return _json(
        {
            "signed_in": signed_in,
            "skipped": skipped,
            "gate_dismissed": signed_in or skipped,
        }
    )


def _sign_in_error_message(err: Exception) -> str:
    """Map a sync-login failure to one calm, learner-facing line."""
    from anki.errors import NetworkError, SyncError, SyncErrorKind

    if isinstance(err, SyncError) and err.kind == SyncErrorKind.AUTH:
        return "That username or password did not match. Try again."
    if isinstance(err, NetworkError):
        return "Could not reach the server. Check the URL and your connection."
    return f"Sign-in failed. {err}"


def pgrep_sign_in() -> bytes:
    """Authenticate against the sync server and report the real result.

    Runs the login on the mediasrv thread (as Anki itself runs ``sync_login`` off
    the main thread) so the page gets a definitive ok/error rather than a
    fire-and-forget kickoff. On success it stores the key and URL, clears any
    prior offline-skip, and starts a normal sync on the main thread.
    """
    mw = aqt.mw
    a = _args()
    url = (a.get("url") or "http://127.0.0.1:8090/").strip()
    username = (a.get("username") or "").strip()
    password = a.get("password") or ""
    if not username or not password:
        return _json(
            {"ok": False, "error": "Enter the username and password we sent you."}
        )

    try:
        auth = mw.col.sync_login(username=username, password=password, endpoint=url)
    except Exception as err:  # noqa: BLE001 - reported calmly to the page
        return _json({"ok": False, "error": _sign_in_error_message(err)})

    from aqt.pgrep_operation import ProductSyncUi

    ui = ProductSyncUi(mw)
    if not ui.started:
        return _json(
            {
                "ok": False,
                "error": "Another sync or export is already running.",
                "operation_id": ui.operation_id,
            }
        )

    def finish() -> None:
        import aqt.sync

        mw.pm.set_custom_sync_url(url)
        mw.pm.set_sync_key(auth.hkey)
        mw.pm.set_sync_username(username)
        mw.pm.meta.pop(_LOGIN_GATE_SKIPPED_META_KEY, None)
        mw.pm.save()
        aqt.sync.sync_collection(mw, lambda: None, ui=ui)

    mw.taskman.run_on_main(finish)
    return _json({"ok": True, "operation_id": ui.operation_id})


def pgrep_gate_skip() -> bytes:
    """Remember the user's "Continue offline" choice (per-device, not synced)."""
    mw = aqt.mw

    def finish() -> None:
        mw.pm.meta[_LOGIN_GATE_SKIPPED_META_KEY] = True
        mw.pm.save()

    mw.taskman.run_on_main(finish)
    return _json({"ok": True, "skipped": True})


# Dev-only (pgrep-lab, L5.9 P5). Injects or clears a clearly-marked hypothetical
# demo profile so the three scores light up on demand for hands-on testing and
# the desktop-to-mobile sync demo. This is NOT wired into any shipped user
# surface (Home, Study, Progress, Diagnostic, Library, Settings); it is reachable
# only from the pgrep-lab dev gallery. Real accounts never call it, so they still
# abstain by construction. Returns a status snapshot (with the three scores) so
# the lab shows the result immediately; the "preview" action returns a stage's
# scores without committing, so a stage lights up on selection before inject.
def pgrep_demo_profile() -> bytes:
    from anki.pgrep import demo_profile

    args = _args()
    action = args.get("action", "status")
    profile = args.get("profile", demo_profile.DEFAULT_PROFILE)
    if action == "inject":
        demo_profile.inject_demo_profile(aqt.mw.col, profile=profile)
    elif action == "clear":
        demo_profile.clear_demo_profile(aqt.mw.col)
    elif action == "preview":
        # Preview computes a stage's scores without committing, so it returns its
        # own snapshot (carrying the preview flags) rather than the live status.
        return _json(demo_profile.preview_demo_profile(aqt.mw.col, profile=profile))
    return _json(demo_profile.demo_status(aqt.mw.col))


# L5.9 Settings. The get/set handlers read and write only the open collection's
# config and the sample deck's config, so they are safe on the mediasrv thread.
# Export must close and reopen the collection, so it runs on the main thread via
# QueryOp, exactly like Anki's own colpkg export.


def pgrep_settings_get() -> bytes:
    from anki.pgrep import settings

    data = settings.get_settings(aqt.mw.col)
    # Per-device: when this machine last finished a successful sync. Not stored
    # in the collection blob, so one device does not overwrite another's clock.
    last = aqt.mw.pm.meta.get("pgrep_last_synced_at")
    data["last_synced_at"] = int(last) if isinstance(last, int) else None
    return _json(data)


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

    mw = aqt.mw
    out_path = settings.default_export_path()
    controller = _operation_controller()
    operation_id = controller.try_begin("export", "Exporting…")
    if operation_id is None:
        return _json(
            {
                "status": "busy",
                "operation_id": controller.snapshot()["operation_id"],
            }
        )
    mw.taskman.run_on_main(_wake_operation)

    def start() -> None:
        def on_success(_: None) -> None:
            mw.reopen()
            controller.succeed(
                operation_id,
                "Export complete",
                detail=f"Saved to {out_path}",
            )
            _wake_operation()

        def on_failure(exc: Exception) -> None:
            mw.reopen()
            controller.fail(operation_id, "Export failed", detail=str(exc))
            _wake_operation()

        gui_hooks.collection_will_temporarily_close(mw.col)
        QueryOp(
            parent=mw,
            op=lambda col: col.export_collection_package(
                out_path, include_media=True, legacy=False
            ),
            success=on_success,
        ).failure(on_failure).run_in_background()

    mw.taskman.run_on_main(start)
    return _json(
        {
            "status": "started",
            "path": out_path,
            "operation_id": operation_id,
        }
    )


# Data / Reset. Conservative and scoped: deletes the pgrep attempt notes and
# forgets the seeded sample cards back to new. Settings, notetypes, decks, and
# all other content (including AI-generated Library cards and Problems) are left
# intact; the collection is never wiped. This is a normal collection write, like
# the study handlers, so it runs on the mediasrv thread. The destructive intent
# is gated by the two-step confirmation on the Settings surface.
def pgrep_reset() -> bytes:
    from anki.pgrep import settings

    return _json(settings.reset_progress(aqt.mw.col))


# L2.3 Diagnostic completion gate. Reads the rolled-up placement snapshot the
# Diagnostic writes (anki.pgrep.diagnostic.place stores it in the collection
# config), so Home and Progress can show the first-run "Run the diagnostic"
# prompt only until it has been completed once. A completed run persists a
# non-empty snapshot; a never-run collection has none.
def pgrep_diagnostic_status() -> bytes:
    from anki.pgrep.diagnostic import DIAGNOSTIC_CONFIG_KEY

    stored = aqt.mw.col.get_config(DIAGNOSTIC_CONFIG_KEY, {})
    completed = isinstance(stored, dict) and bool(stored)
    return _json({"completed": completed})


# L4 Library / Card Sets browser -> anki.pgrep.card_sets.list_card_sets. A
# read-only view model for the "wheel": the learner's Basic topic-tagged cards
# grouped into one set per blueprint category, with real counts and real face
# previews. No AI, no scheduler.
def pgrep_card_sets() -> bytes:
    from anki.pgrep import card_sets

    return _json(card_sets.list_card_sets(aqt.mw.col))


# L4 Library / Card Sets "Add a card" -> anki.pgrep.card_sets.add_card. Authors
# the learner's own front/back as-is into the category's set (generation.author_
# seed), no AI. Separate from calibration.
def pgrep_add_card() -> bytes:
    from anki.pgrep import card_sets

    a = _args()
    return _json(
        card_sets.add_card(
            aqt.mw.col, a.get("category", ""), a.get("front", ""), a.get("back", "")
        )
    )


# L4 Calibration gate -> anki.pgrep.calibration.calibration_status. Reports how
# many blueprint categories the learner has authored a card in and whether that
# calibrates the collection, so Study and Library can gate on aiEnabled &&
# !calibrated. Sets a sticky flag on completion.
def pgrep_calibration_status() -> bytes:
    from anki.pgrep import calibration

    return _json(calibration.calibration_status(aqt.mw.col))


# Registered once into mediasrv's post_handler_list (see qt/aqt/mediasrv.py).
pgrep_post_handlers = [
    pgrep_seed,
    pgrep_restart_cards,
    pgrep_memory_score,
    pgrep_coverage,
    pgrep_performance_score,
    pgrep_readiness_score,
    pgrep_calibration,
    pgrep_manifold,
    pgrep_diagnostic_topics,
    pgrep_diagnostic_place,
    pgrep_study_start,
    pgrep_study_next,
    pgrep_study_answer_card,
    pgrep_study_commit,
    pgrep_exam_start,
    pgrep_exam_next,
    pgrep_exam_answer,
    pgrep_exam_result,
    pgrep_ai_status,
    pgrep_ai_set_enabled,
    pgrep_library_generate,
    pgrep_problem_generate,
    pgrep_tutor_grade,
    pgrep_tutor_synthesis,
    pgrep_tutor_synthesis_preview,
    pgrep_tutor_mcq,
    pgrep_tutor_explain,
    pgrep_tutor_seed,
    pgrep_tutor_list,
    pgrep_tutor_load,
    pgrep_sync,
    pgrep_operation_status,
    pgrep_operation_resolve,
    pgrep_operation_cancel,
    pgrep_operation_dismiss,
    pgrep_auth_status,
    pgrep_sign_in,
    pgrep_gate_skip,
    pgrep_demo_profile,
    pgrep_settings_get,
    pgrep_settings_set,
    pgrep_export,
    pgrep_reset,
    pgrep_diagnostic_status,
    pgrep_card_sets,
    pgrep_add_card,
    pgrep_calibration_status,
]
