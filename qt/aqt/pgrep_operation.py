# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Thread-safe state for long-running pgrep desktop operations.

The mediasrv bridge reads this state from a request thread while sync/export
callbacks update it on Qt's main thread. Operation IDs make late callbacks and
stale browser pages harmless.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from concurrent.futures import Future
from copy import deepcopy
from threading import RLock
from typing import Any, Literal, TypedDict

OperationKind = Literal["idle", "sync", "export", "message"]
OperationPhase = Literal["idle", "active", "decision", "success", "error", "cancelled"]


class _Unset:
    pass


_UNSET = _Unset()


class OperationChoice(TypedDict):
    id: str
    label: str
    destructive: bool


class OperationDecision(TypedDict):
    title: str
    body: str
    choices: list[OperationChoice]


class OperationSnapshot(TypedDict):
    revision: int
    operation_id: int | None
    kind: OperationKind
    phase: OperationPhase
    message: str
    detail: str | None
    progress: float | None
    cancellable: bool
    decision: OperationDecision | None
    dismiss_after_ms: int | None


class OperationController:
    """Own one visible operation and reject stale mutations."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._next_operation_id = 1
        self._revision = 0
        self._snapshot = self._idle_snapshot()
        self._resolver: Callable[[str], None] | None = None
        self._cancel: Callable[[], None] | None = None

    def _idle_snapshot(self) -> OperationSnapshot:
        return {
            "revision": self._revision,
            "operation_id": None,
            "kind": "idle",
            "phase": "idle",
            "message": "",
            "detail": None,
            "progress": None,
            "cancellable": False,
            "decision": None,
            "dismiss_after_ms": None,
        }

    def _bump_revision(self) -> None:
        self._revision += 1
        self._snapshot["revision"] = self._revision

    def begin(
        self,
        kind: Literal["sync", "export", "message"],
        message: str,
        *,
        detail: str | None = None,
        progress: float | None = None,
        cancellable: bool = False,
        cancel: Callable[[], None] | None = None,
    ) -> int:
        with self._lock:
            return self._begin_locked(
                kind,
                message,
                detail=detail,
                progress=progress,
                cancellable=cancellable,
                cancel=cancel,
            )

    def try_begin(
        self,
        kind: Literal["sync", "export", "message"],
        message: str,
        *,
        detail: str | None = None,
        progress: float | None = None,
        cancellable: bool = False,
        cancel: Callable[[], None] | None = None,
    ) -> int | None:
        with self._lock:
            if self._snapshot["phase"] in ("active", "decision"):
                return None
            return self._begin_locked(
                kind,
                message,
                detail=detail,
                progress=progress,
                cancellable=cancellable,
                cancel=cancel,
            )

    def update(
        self,
        operation_id: int,
        *,
        message: str | None = None,
        detail: str | None = None,
        progress: float | None | _Unset = _UNSET,
        cancellable: bool | None = None,
    ) -> bool:
        with self._lock:
            if not self._is_active(operation_id):
                return False
            if message is not None:
                self._snapshot["message"] = message
            if detail is not None:
                self._snapshot["detail"] = detail
            if not isinstance(progress, _Unset):
                self._snapshot["progress"] = self._clamp_progress(progress)
            if cancellable is not None:
                self._snapshot["cancellable"] = cancellable and self._cancel is not None
            self._bump_revision()
            return True

    def request_decision(
        self,
        operation_id: int,
        *,
        title: str,
        body: str,
        choices: Sequence[OperationChoice],
        resolver: Callable[[str], None],
    ) -> bool:
        with self._lock:
            if not self._is_active(operation_id) or not choices:
                return False
            self._snapshot["phase"] = "decision"
            self._snapshot["message"] = title
            self._snapshot["progress"] = None
            self._snapshot["cancellable"] = False
            self._snapshot["decision"] = {
                "title": title,
                "body": body,
                "choices": deepcopy(list(choices)),
            }
            self._resolver = resolver
            self._bump_revision()
            return True

    def resolve(self, operation_id: int, choice: str) -> bool:
        resolver: Callable[[str], None]
        with self._lock:
            decision = self._snapshot["decision"]
            if (
                self._snapshot["operation_id"] != operation_id
                or self._snapshot["phase"] != "decision"
                or decision is None
                or self._resolver is None
                or choice not in {candidate["id"] for candidate in decision["choices"]}
            ):
                return False
            resolver = self._resolver
            self._resolver = None
            self._snapshot["phase"] = "active"
            self._snapshot["decision"] = None
            self._snapshot["message"] = "Continuing…"
            self._bump_revision()
        resolver(choice)
        return True

    def cancel(self, operation_id: int) -> bool:
        cancel: Callable[[], None]
        with self._lock:
            if (
                not self._is_active(operation_id)
                or not self._snapshot["cancellable"]
                or self._cancel is None
            ):
                return False
            cancel = self._cancel
            self._cancel = None
            self._snapshot["cancellable"] = False
            self._snapshot["message"] = "Cancelling"
            self._bump_revision()
        cancel()
        return True

    def set_cancel(self, operation_id: int, cancel: Callable[[], None] | None) -> bool:
        with self._lock:
            if not self._is_active(operation_id):
                return False
            self._cancel = cancel
            self._snapshot["cancellable"] = cancel is not None
            self._bump_revision()
            return True

    def succeed(
        self,
        operation_id: int,
        message: str,
        *,
        detail: str | None = None,
        dismiss_after_ms: int = 3000,
    ) -> bool:
        return self._finish(
            operation_id,
            phase="success",
            message=message,
            detail=detail,
            dismiss_after_ms=dismiss_after_ms,
        )

    def fail(
        self,
        operation_id: int,
        message: str,
        *,
        detail: str | None = None,
    ) -> bool:
        return self._finish(
            operation_id,
            phase="error",
            message=message,
            detail=detail,
            dismiss_after_ms=None,
        )

    def cancelled(
        self,
        operation_id: int,
        message: str,
        *,
        dismiss_after_ms: int = 2000,
    ) -> bool:
        return self._finish(
            operation_id,
            phase="cancelled",
            message=message,
            detail=None,
            dismiss_after_ms=dismiss_after_ms,
        )

    def dismiss(self, operation_id: int) -> bool:
        with self._lock:
            if self._snapshot["operation_id"] != operation_id or self._snapshot[
                "phase"
            ] not in ("success", "error", "cancelled"):
                return False
            self._resolver = None
            self._cancel = None
            self._snapshot = self._idle_snapshot()
            self._bump_revision()
            return True

    def snapshot(self) -> OperationSnapshot:
        with self._lock:
            return deepcopy(self._snapshot)

    def _finish(
        self,
        operation_id: int,
        *,
        phase: Literal["success", "error", "cancelled"],
        message: str,
        detail: str | None,
        dismiss_after_ms: int | None,
    ) -> bool:
        with self._lock:
            if not self._is_active(operation_id):
                return False
            self._resolver = None
            self._cancel = None
            self._snapshot["phase"] = phase
            self._snapshot["message"] = message
            self._snapshot["detail"] = detail
            self._snapshot["progress"] = 1.0 if phase == "success" else None
            self._snapshot["cancellable"] = False
            self._snapshot["decision"] = None
            self._snapshot["dismiss_after_ms"] = dismiss_after_ms
            self._bump_revision()
            return True

    def _begin_locked(
        self,
        kind: Literal["sync", "export", "message"],
        message: str,
        *,
        detail: str | None,
        progress: float | None,
        cancellable: bool,
        cancel: Callable[[], None] | None,
    ) -> int:
        operation_id = self._next_operation_id
        self._next_operation_id += 1
        self._resolver = None
        self._cancel = cancel
        self._snapshot = {
            "revision": self._revision,
            "operation_id": operation_id,
            "kind": kind,
            "phase": "active",
            "message": message,
            "detail": detail,
            "progress": self._clamp_progress(progress),
            "cancellable": cancellable and cancel is not None,
            "decision": None,
            "dismiss_after_ms": None,
        }
        self._bump_revision()
        return operation_id

    def _is_active(self, operation_id: int) -> bool:
        return self._snapshot["operation_id"] == operation_id and self._snapshot[
            "phase"
        ] in ("active", "decision")

    @staticmethod
    def _clamp_progress(progress: float | None) -> float | None:
        if progress is None:
            return None
        return min(1.0, max(0.0, progress))


operation_controller = OperationController()


class ProductSyncUi:
    """`aqt.sync.SyncUi` implementation backed by the pgrep operation state."""

    def __init__(
        self,
        mw: Any,
        *,
        controller: OperationController | None = None,
        operation_id: int | None = None,
    ) -> None:
        self.mw = mw
        self.controller = controller or operation_controller
        if operation_id is not None:
            self.operation_id = operation_id
            self.started = True
        else:
            started_id = self.controller.try_begin("sync", "Preparing…")
            if started_id is None:
                current_id = self.controller.snapshot()["operation_id"]
                assert current_id is not None
                self.operation_id = current_id
                self.started = False
            else:
                self.operation_id = started_id
                self.started = True
                self._wake()

    def run_task(
        self,
        task: Callable[[], Any],
        on_done: Callable[[Future], None],
        *,
        message: str,
        cancellable: bool = True,
    ) -> None:
        if not self.started:
            return
        self.controller.set_cancel(
            self.operation_id,
            self.mw.col.abort_sync if cancellable else None,
        )
        self.update(message)
        self.mw.taskman.run_in_background(task, on_done)

    def update(self, message: str, *, progress: float | None = None) -> None:
        if not self.started:
            return
        changed = self.controller.update(
            self.operation_id,
            message=message,
            progress=progress,
        )
        if changed:
            self._wake()

    def request_decision(
        self,
        *,
        title: str,
        body: str,
        choices: Sequence[Any],
        callback: Callable[[str], None],
    ) -> None:
        if not self.started:
            return
        serialized: list[OperationChoice] = [
            OperationChoice(
                id=choice.id,
                label=choice.label,
                destructive=choice.destructive,
            )
            for choice in choices
        ]
        changed = self.controller.request_decision(
            self.operation_id,
            title=title,
            body=body,
            choices=serialized,
            resolver=callback,
        )
        if changed:
            self._wake()

    def error(self, err: Exception) -> None:
        if not self.started:
            return
        changed = self.controller.fail(
            self.operation_id,
            "Sync failed",
            detail=str(err),
        )
        if changed:
            self._wake()

    def complete(self, _message: str) -> None:
        if not self.started:
            return
        # Collection sync is only the first phase. MediaSyncer owns the final
        # success transition so the learner sees one honest end-to-end result.
        if self.controller.update(
            self.operation_id,
            message="Checking media…",
            progress=None,
            cancellable=False,
        ):
            self._wake()

    def cancelled(self, message: str) -> None:
        if self.started and self.controller.cancelled(self.operation_id, message):
            self._wake()

    def server_message(self, message: str) -> None:
        if not self.started:
            return
        if self.controller.update(self.operation_id, detail=message):
            self._wake()

    def _wake(self) -> None:
        from aqt import pgrep_host

        self.mw.taskman.run_on_main(
            lambda: pgrep_host.notify_operation_changed(self.mw)
        )
