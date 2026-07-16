# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

from __future__ import annotations

from types import SimpleNamespace

from aqt.pgrep_operation import OperationController, ProductSyncUi
from aqt.sync import SyncChoice


def test_stale_update_cannot_overwrite_new_operation() -> None:
    controller = OperationController()
    first = controller.begin("sync", "Checking")
    second = controller.begin("export", "Exporting")

    assert controller.update(first, message="stale") is False
    assert controller.snapshot()["operation_id"] == second
    assert controller.snapshot()["message"] == "Exporting"


def test_try_begin_rejects_an_active_operation() -> None:
    controller = OperationController()
    first = controller.try_begin("sync", "Checking")

    assert first is not None
    assert controller.try_begin("export", "Exporting") is None
    assert controller.snapshot()["operation_id"] == first
    assert controller.snapshot()["kind"] == "sync"


def test_decision_resolves_once_and_clears_prompt() -> None:
    choices: list[str] = []
    controller = OperationController()
    operation_id = controller.begin("sync", "Checking")
    controller.request_decision(
        operation_id,
        title="Which copy should we keep?",
        body="The copies cannot be merged.",
        choices=[{"id": "cancel", "label": "Cancel", "destructive": False}],
        resolver=choices.append,
    )

    assert controller.resolve(operation_id, "cancel") is True
    assert controller.resolve(operation_id, "cancel") is False
    assert choices == ["cancel"]
    assert controller.snapshot()["decision"] is None


def test_cancel_and_dismiss_are_operation_scoped() -> None:
    cancelled: list[int] = []
    controller = OperationController()
    operation_id = controller.begin(
        "sync", "Syncing", cancellable=True, cancel=lambda: cancelled.append(1)
    )

    assert controller.cancel(operation_id + 1) is False
    assert controller.cancel(operation_id) is True
    assert controller.cancel(operation_id) is False
    assert cancelled == [1]

    assert controller.dismiss(operation_id) is False
    assert controller.fail(operation_id, "Sync failed", detail="Network down") is True
    assert controller.dismiss(operation_id) is True
    assert controller.snapshot()["phase"] == "idle"


def test_cancel_callback_can_move_to_media_phase() -> None:
    cancelled: list[str] = []
    controller = OperationController()
    operation_id = controller.begin("sync", "Checking")

    assert (
        controller.set_cancel(operation_id, lambda: cancelled.append("media")) is True
    )
    assert controller.cancel(operation_id) is True
    assert cancelled == ["media"]


def test_cancelled_operation_is_terminal_and_dismissible() -> None:
    controller = OperationController()
    operation_id = controller.begin("sync", "Checking")

    assert controller.cancelled(operation_id, "Sync cancelled") is True
    assert controller.snapshot()["phase"] == "cancelled"
    assert controller.update(operation_id, message="late") is False
    assert controller.dismiss(operation_id) is True


def test_progress_is_clamped_and_terminal_state_is_immutable() -> None:
    controller = OperationController()
    operation_id = controller.begin("sync", "Downloading")

    assert controller.update(operation_id, progress=1.5) is True
    assert controller.snapshot()["progress"] == 1.0
    assert controller.update(operation_id, progress=None) is True
    assert controller.snapshot()["progress"] is None
    assert controller.succeed(operation_id, "Sync complete") is True
    assert controller.update(operation_id, message="late progress") is False
    assert controller.snapshot()["message"] == "Sync complete"


def test_product_sync_ui_uses_background_task_and_controller() -> None:
    controller = OperationController()
    background_calls: list[tuple[object, object]] = []
    progress_calls: list[object] = []
    mw = SimpleNamespace(
        col=SimpleNamespace(abort_sync=lambda: None),
        taskman=SimpleNamespace(
            run_in_background=lambda task, done: background_calls.append((task, done)),
            run_on_main=lambda fn: fn(),
            with_progress=lambda *args: progress_calls.append(args),
        ),
    )
    ui = ProductSyncUi(mw, controller=controller)

    ui.run_task(lambda: 1, lambda _future: None, message="Checking")

    assert len(background_calls) == 1
    assert progress_calls == []
    assert controller.snapshot()["message"] == "Checking"
    assert controller.snapshot()["cancellable"] is True


def test_product_sync_ui_reuses_active_operation_without_starting() -> None:
    controller = OperationController()
    first = controller.begin("export", "Exporting")
    mw = SimpleNamespace(
        col=SimpleNamespace(abort_sync=lambda: None),
        taskman=SimpleNamespace(
            run_in_background=lambda *_args: None,
            run_on_main=lambda fn: fn(),
        ),
    )

    ui = ProductSyncUi(mw, controller=controller)

    assert ui.started is False
    assert ui.operation_id == first
    assert controller.snapshot()["kind"] == "export"


def test_product_sync_ui_decision_round_trips_through_controller() -> None:
    controller = OperationController()
    selected: list[str] = []
    mw = SimpleNamespace(
        col=SimpleNamespace(abort_sync=lambda: None),
        taskman=SimpleNamespace(
            run_in_background=lambda *_args: None,
            run_on_main=lambda fn: fn(),
        ),
    )
    ui = ProductSyncUi(mw, controller=controller)
    ui.request_decision(
        title="Choose",
        body="Keep one copy",
        choices=[
            SyncChoice("upload", "Upload", destructive=True),
            SyncChoice("cancel", "Cancel"),
        ],
        callback=selected.append,
    )

    assert controller.resolve(ui.operation_id, "upload") is True
    assert selected == ["upload"]


def test_product_sync_ui_rearms_cancellation_after_decision() -> None:
    controller = OperationController()
    mw = SimpleNamespace(
        col=SimpleNamespace(abort_sync=lambda: None),
        taskman=SimpleNamespace(
            run_in_background=lambda *_args: None,
            run_on_main=lambda fn: fn(),
        ),
    )
    ui = ProductSyncUi(mw, controller=controller)
    ui.request_decision(
        title="Choose",
        body="Keep one",
        choices=[
            SyncChoice("upload", "Upload", destructive=True),
            SyncChoice("cancel", "Cancel"),
        ],
        callback=lambda _choice: ui.run_task(
            lambda: None, lambda _future: None, message="Uploading"
        ),
    )

    assert controller.resolve(ui.operation_id, "upload") is True
    assert controller.snapshot()["cancellable"] is True
