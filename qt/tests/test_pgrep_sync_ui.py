# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

from __future__ import annotations

from concurrent.futures import Future
from types import SimpleNamespace
from typing import Any

import pytest

import aqt.sync as sync
from anki.errors import Interrupted, SyncError, SyncErrorKind
from anki.sync import SyncOutput


class _FakeUi:
    def __init__(self) -> None:
        self.updates: list[tuple[str, float | None]] = []
        self.decisions: list[dict[str, Any]] = []
        self.errors: list[Exception] = []
        self.completions: list[str] = []
        self.cancellations: list[str] = []
        self.server_messages: list[str] = []

    def run_task(
        self, task, on_done, *, message: str, cancellable: bool = True
    ) -> None:
        self.updates.append((message, None))
        future: Future = Future()
        try:
            future.set_result(task())
        except Exception as err:  # noqa: BLE001 - fake worker captures task failure
            future.set_exception(err)
        on_done(future)

    def update(self, message: str, *, progress: float | None = None) -> None:
        self.updates.append((message, progress))

    def request_decision(self, *, title: str, body: str, choices, callback) -> None:
        self.decisions.append(
            {
                "title": title,
                "body": body,
                "choices": choices,
                "callback": callback,
            }
        )

    def error(self, err: Exception) -> None:
        self.errors.append(err)

    def complete(self, message: str) -> None:
        self.completions.append(message)

    def cancelled(self, message: str) -> None:
        self.cancellations.append(message)

    def server_message(self, message: str) -> None:
        self.server_messages.append(message)


class _FakeTimer:
    def __init__(self, _parent: object) -> None:
        self.timeout = object()
        self.stopped = False

    def start(self, _period: int) -> None:
        pass

    def stop(self) -> None:
        self.stopped = True


class _FakePm:
    def __init__(self) -> None:
        self.auth = object()
        self.auth_cleared = False
        self.host_number: int | None = None

    def sync_auth(self) -> object:
        return self.auth

    def media_syncing_enabled(self) -> bool:
        return True

    def clear_sync_auth(self) -> None:
        self.auth_cleared = True

    def set_host_number(self, host_number: int) -> None:
        self.host_number = host_number

    def set_current_sync_url(self, _url: str) -> None:
        pass


class _FakeCol:
    def __init__(
        self, *, output: SyncOutput | None = None, error: Exception | None = None
    ) -> None:
        self.output = output
        self.error = error
        self.scheduler_loaded = False

    def sync_collection(self, _auth: object, _sync_media: bool) -> SyncOutput:
        if self.error:
            raise self.error
        assert self.output is not None
        return self.output

    def _load_scheduler(self) -> None:
        self.scheduler_loaded = True


def _mw(col: _FakeCol) -> SimpleNamespace:
    return SimpleNamespace(
        col=col,
        pm=_FakePm(),
        media_syncer=SimpleNamespace(start_monitoring=lambda *args, **kwargs: None),
    )


@pytest.fixture(autouse=True)
def _fake_qt_timer(monkeypatch):
    monkeypatch.setattr(sync, "QTimer", _FakeTimer)
    monkeypatch.setattr(sync, "qconnect", lambda *_args: None)


@pytest.mark.parametrize(
    ("required", "choice_ids"),
    [
        (SyncOutput.FULL_DOWNLOAD, ["download", "cancel"]),
        (SyncOutput.FULL_UPLOAD, ["upload", "cancel"]),
        (SyncOutput.FULL_SYNC, ["upload", "download", "cancel"]),
    ],
)
def test_product_ui_owns_full_sync_decisions(
    required: int, choice_ids: list[str]
) -> None:
    ui = _FakeUi()
    mw = _mw(_FakeCol(output=SyncOutput(required=required)))

    sync.sync_collection(mw, lambda: None, ui=ui)

    assert len(ui.decisions) == 1
    assert [choice.id for choice in ui.decisions[0]["choices"]] == choice_ids
    assert ui.decisions[0]["title"] in {
        "Download your collection?",
        "Upload this collection?",
        "Which copy should we keep?",
    }
    assert "AnkiWeb" not in ui.decisions[0]["body"]
    assert "server" not in ui.decisions[0]["body"].lower()
    assert [choice.label for choice in ui.decisions[0]["choices"]] == [
        {"download": "Download", "upload": "Upload", "cancel": "Cancel"}[choice_id]
        for choice_id in choice_ids
    ]


def test_product_ui_reports_completion_without_qt_progress() -> None:
    ui = _FakeUi()
    mw = _mw(
        _FakeCol(
            output=SyncOutput(
                required=SyncOutput.NO_CHANGES,
                host_number=7,
                server_message="Maintenance tonight",
            )
        )
    )
    done: list[bool] = []

    sync.sync_collection(mw, lambda: done.append(True), ui=ui)

    assert ui.updates[0][0]
    assert len(ui.completions) == 1
    assert ui.completions[0]
    assert ui.server_messages == ["Maintenance tonight"]
    assert done == [True]
    assert mw.pm.host_number == 7


def test_product_ui_reports_auth_error_and_finishes_once() -> None:
    err = SyncError.__new__(SyncError)
    err.kind = SyncErrorKind.AUTH
    ui = _FakeUi()
    mw = _mw(_FakeCol(error=err))
    done: list[bool] = []

    sync.sync_collection(mw, lambda: done.append(True), ui=ui)

    assert ui.errors == [err]
    assert mw.pm.auth_cleared is True
    assert done == [True]


def test_product_ui_reports_interrupted_sync_as_cancelled() -> None:
    ui = _FakeUi()
    interrupted = Interrupted.__new__(Interrupted)
    mw = _mw(_FakeCol(error=interrupted))
    done: list[bool] = []

    sync.sync_collection(mw, lambda: done.append(True), ui=ui)

    assert ui.errors == []
    assert ui.cancellations == ["Sync cancelled"]
    assert done == [True]


def test_decision_cancel_finishes_operation() -> None:
    ui = _FakeUi()
    mw = _mw(_FakeCol(output=SyncOutput(required=SyncOutput.FULL_SYNC)))
    done: list[bool] = []
    sync.sync_collection(mw, lambda: done.append(True), ui=ui)

    ui.decisions[0]["callback"]("cancel")

    assert ui.cancellations == ["Sync cancelled"]
    assert done == [True]


def test_native_fallback_uses_qt_progress() -> None:
    calls: list[str] = []
    mw = _mw(_FakeCol(output=SyncOutput(required=SyncOutput.NO_CHANGES)))
    mw.taskman = SimpleNamespace(
        with_progress=lambda *_args, **_kwargs: calls.append("with_progress")
    )

    sync.sync_collection(mw, lambda: None)

    assert calls == ["with_progress"]
