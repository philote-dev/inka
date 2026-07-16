# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

from __future__ import annotations

import functools
import os
from collections.abc import Callable
from concurrent.futures import Future
from dataclasses import dataclass
from typing import Any, Protocol

import aqt
import aqt.main
from anki.errors import Interrupted, SyncError, SyncErrorKind
from anki.lang import without_unicode_isolation
from anki.sync import SyncOutput, SyncStatus
from anki.sync_pb2 import SyncAuth
from anki.utils import plat_desc
from aqt import gui_hooks
from aqt.qt import (
    QDialog,
    QDialogButtonBox,
    QGridLayout,
    QLabel,
    QLineEdit,
    Qt,
    QTimer,
    QVBoxLayout,
    qconnect,
)
from aqt.utils import (
    ask_user_dialog,
    disable_help_button,
    show_warning,
    showText,
    showWarning,
    tooltip,
    tr,
)


def get_sync_status(
    mw: aqt.main.AnkiQt, callback: Callable[[SyncStatus], None]
) -> None:
    auth = mw.pm.sync_auth()
    if not auth:
        callback(SyncStatus(required=SyncStatus.NO_CHANGES))
        return

    def on_future_done(fut: Future[SyncStatus]) -> None:
        try:
            out = fut.result()
        except Exception as e:
            # swallow errors
            print("sync status check failed:", str(e))
            return
        if out.new_endpoint:
            mw.pm.set_current_sync_url(out.new_endpoint)
        callback(out)

    mw.taskman.run_in_background(
        lambda: mw.col.sync_status(auth),
        on_future_done,
        # The check quickly releases the collection, and we don't need to block other callers
        uses_collection=False,
    )


@dataclass(frozen=True)
class SyncChoice:
    id: str
    label: str
    destructive: bool = False


class SyncUi(Protocol):
    """Presentation seam for collection sync.

    The native implementation keeps upstream dialogs for the explicit off-mode
    hatch. The pgrep implementation reports the same state inside the SPA.
    """

    def run_task(
        self,
        task: Callable[[], Any],
        on_done: Callable[[Future], None],
        *,
        message: str,
        cancellable: bool = True,
    ) -> None: ...

    def update(self, message: str, *, progress: float | None = None) -> None: ...

    def request_decision(
        self,
        *,
        title: str,
        body: str,
        choices: list[SyncChoice],
        callback: Callable[[str], None],
    ) -> None: ...

    def error(self, err: Exception) -> None: ...

    def complete(self, message: str) -> None: ...

    def cancelled(self, message: str) -> None: ...

    def server_message(self, message: str) -> None: ...


class NativeSyncUi:
    """Upstream Qt presentation, retained only when pgrep is switched off."""

    def __init__(self, mw: aqt.main.AnkiQt) -> None:
        self.mw = mw

    def run_task(
        self,
        task: Callable[[], Any],
        on_done: Callable[[Future], None],
        *,
        message: str,
        cancellable: bool = True,
    ) -> None:
        self.mw.taskman.with_progress(
            task,
            on_done,
            label=message,
            immediate=True,
            title=message,
        )

    def update(self, message: str, *, progress: float | None = None) -> None:
        kwargs: dict[str, Any] = {"label": message, "process": False}
        if progress is not None:
            kwargs.update(value=round(progress * 1000), max=1000)
        self.mw.progress.update(**kwargs)
        if self.mw.progress.want_cancel():
            self.mw.col.abort_sync()

    def request_decision(
        self,
        *,
        title: str,
        body: str,
        choices: list[SyncChoice],
        callback: Callable[[str], None],
    ) -> None:
        def on_choice(index: int) -> None:
            callback(choices[index].id)

        ask_user_dialog(
            body,
            callback=on_choice,
            buttons=[choice.label for choice in choices],
            default_button=len(choices) - 1,
            parent=self.mw,
            textFormat=Qt.TextFormat.MarkdownText,
            title=title,
        )

    def error(self, err: Exception) -> None:
        show_warning(str(err), parent=self.mw)

    def complete(self, message: str) -> None:
        tooltip(parent=self.mw, msg=message)

    def cancelled(self, _message: str) -> None:
        # Upstream treats interruption as silent.
        pass

    def server_message(self, message: str) -> None:
        showText(message, parent=self.mw, type="rich")


def _prepare_sync_error(mw: aqt.main.AnkiQt, err: Exception) -> bool:
    if isinstance(err, SyncError):
        if err.kind is SyncErrorKind.AUTH:
            mw.pm.clear_sync_auth()
    elif isinstance(err, Interrupted):
        return False
    return True


def handle_sync_error(mw: aqt.main.AnkiQt, err: Exception) -> None:
    """Compatibility entry point for native-only callers such as sync_login."""
    if _prepare_sync_error(mw, err):
        show_warning(str(err), parent=mw)


def _report_sync_exception(mw: aqt.main.AnkiQt, ui: SyncUi, err: Exception) -> None:
    if isinstance(err, Interrupted):
        ui.cancelled("Sync cancelled")
    elif _prepare_sync_error(mw, err):
        ui.error(err)


def _media_operation_id(ui: SyncUi) -> int | None:
    operation_id = getattr(ui, "operation_id", None)
    return operation_id if isinstance(operation_id, int) else None


def on_normal_sync_timer(mw: aqt.main.AnkiQt, ui: SyncUi) -> None:
    progress = mw.col.latest_progress()
    if not progress.HasField("normal_sync"):
        return
    sync_progress = progress.normal_sync

    ui.update(
        f"{sync_progress.stage}\n{sync_progress.added}\n{sync_progress.removed}",
        progress=None,
    )


def sync_collection(
    mw: aqt.main.AnkiQt,
    on_done: Callable[[], None],
    *,
    ui: SyncUi | None = None,
) -> None:
    auth = mw.pm.sync_auth()
    if not auth:
        raise Exception("expected auth")
    sync_ui = ui or NativeSyncUi(mw)

    def on_timer() -> None:
        on_normal_sync_timer(mw, sync_ui)

    timer = QTimer(mw)
    qconnect(timer.timeout, on_timer)
    timer.start(150)

    def on_future_done(fut: Future[SyncOutput]) -> None:
        # scheduler version may have changed
        mw.col._load_scheduler()
        timer.stop()
        try:
            out = fut.result()
        except Exception as err:
            _report_sync_exception(mw, sync_ui, err)
            return on_done()

        mw.pm.set_host_number(out.host_number)
        if out.new_endpoint:
            mw.pm.set_current_sync_url(out.new_endpoint)
        if out.server_message:
            sync_ui.server_message(out.server_message)
        if out.required == out.NO_CHANGES:
            sync_ui.complete(tr.sync_collection_complete())
            # all done; track media progress
            mw.media_syncer.start_monitoring(operation_id=_media_operation_id(sync_ui))
            return on_done()
        else:
            full_sync(mw, out, on_done, ui=sync_ui)

    sync_ui.run_task(
        lambda: mw.col.sync_collection(auth, mw.pm.media_syncing_enabled()),
        on_future_done,
        message=tr.sync_checking(),
    )


def full_sync(
    mw: aqt.main.AnkiQt,
    out: SyncOutput,
    on_done: Callable[[], None],
    *,
    ui: SyncUi | None = None,
) -> None:
    sync_ui = ui or NativeSyncUi(mw)
    server_usn = out.server_media_usn if mw.pm.media_syncing_enabled() else None
    title, body, choices = _full_sync_decision(
        out, product=not isinstance(sync_ui, NativeSyncUi)
    )

    def start_download() -> None:
        full_download(mw, server_usn, on_done, ui=sync_ui)

    def start_upload() -> None:
        full_upload(mw, server_usn, on_done, ui=sync_ui)

    def callback(choice: str) -> None:
        if choice == "cancel":
            sync_ui.cancelled("Sync cancelled")
            on_done()
        elif choice == "download":
            if out.required == out.FULL_DOWNLOAD:
                mw.closeAllWindows(start_download)
            else:
                start_download()
        elif choice == "upload":
            if out.required == out.FULL_UPLOAD:
                mw.closeAllWindows(start_upload)
            else:
                start_upload()

    sync_ui.request_decision(
        title=title,
        body=body,
        choices=choices,
        callback=callback,
    )


def _full_sync_decision(
    out: SyncOutput, *, product: bool
) -> tuple[str, str, list[SyncChoice]]:
    """Title, body, and choices for a one-way or conflict full sync.

    Product copy is short and plain. Native/off mode keeps upstream Fluent
    strings (including AnkiWeb wording) for the stock dialogs.
    """
    if product:
        cancel = SyncChoice("cancel", "Cancel")
        if out.required == out.FULL_DOWNLOAD:
            return (
                "Download your collection?",
                "This device has no cards yet.",
                [
                    SyncChoice("download", "Download", destructive=True),
                    cancel,
                ],
            )
        if out.required == out.FULL_UPLOAD:
            return (
                "Upload this collection?",
                "Your account has no cards yet.",
                [
                    SyncChoice("upload", "Upload", destructive=True),
                    cancel,
                ],
            )
        return (
            "Which copy should we keep?",
            "Upload keeps this device. Download keeps your account.",
            [
                SyncChoice("upload", "Upload", destructive=True),
                SyncChoice("download", "Download", destructive=True),
                cancel,
            ],
        )

    if out.required == out.FULL_DOWNLOAD:
        return (
            tr.qt_misc_sync(),
            tr.sync_confirm_empty_download(),
            [
                SyncChoice(
                    "download", tr.sync_download_from_ankiweb(), destructive=True
                ),
                SyncChoice("cancel", tr.sync_cancel_button()),
            ],
        )
    if out.required == out.FULL_UPLOAD:
        return (
            tr.qt_misc_sync(),
            tr.sync_confirm_empty_upload(),
            [
                SyncChoice("upload", tr.sync_upload_to_ankiweb(), destructive=True),
                SyncChoice("cancel", tr.sync_cancel_button()),
            ],
        )
    return (
        tr.qt_misc_sync(),
        tr.sync_conflict_explanation2(),
        [
            SyncChoice("upload", tr.sync_upload_to_ankiweb(), destructive=True),
            SyncChoice("download", tr.sync_download_from_ankiweb(), destructive=True),
            SyncChoice("cancel", tr.sync_cancel_button()),
        ],
    )


def on_full_sync_timer(mw: aqt.main.AnkiQt, label: str, ui: SyncUi) -> None:
    progress = mw.col.latest_progress()
    if not progress.HasField("full_sync"):
        return
    sync_progress = progress.full_sync

    # If we've reached total, show the "checking" label
    if sync_progress.transferred == sync_progress.total:
        label = tr.sync_checking()

    total = sync_progress.total
    transferred = sync_progress.transferred

    fraction = transferred / total if total else None
    ui.update(label, progress=fraction)


def full_download(
    mw: aqt.main.AnkiQt,
    server_usn: int | None,
    on_done: Callable[[], None],
    *,
    ui: SyncUi | None = None,
) -> None:
    sync_ui = ui or NativeSyncUi(mw)
    label = tr.sync_downloading_from_ankiweb()

    def on_timer() -> None:
        on_full_sync_timer(mw, label, sync_ui)

    timer = QTimer(mw)
    qconnect(timer.timeout, on_timer)
    timer.start(150)

    # hook needs to be called early, on the main thread
    gui_hooks.collection_will_temporarily_close(mw.col)

    def download() -> None:
        mw.create_backup_now()
        mw.col.close_for_full_sync()
        mw.col.full_upload_or_download(
            auth=mw.pm.sync_auth(), server_usn=server_usn, upload=False
        )

    def on_future_done(fut: Future) -> None:
        timer.stop()
        mw.reopen(after_full_sync=True)
        mw.reset()
        try:
            fut.result()
        except Exception as err:
            _report_sync_exception(mw, sync_ui, err)
            return on_done()
        sync_ui.complete(tr.sync_collection_complete())
        mw.media_syncer.start_monitoring(operation_id=_media_operation_id(sync_ui))
        return on_done()

    sync_ui.run_task(
        download,
        on_future_done,
        message=label,
    )


def full_upload(
    mw: aqt.main.AnkiQt,
    server_usn: int | None,
    on_done: Callable[[], None],
    *,
    ui: SyncUi | None = None,
) -> None:
    sync_ui = ui or NativeSyncUi(mw)
    gui_hooks.collection_will_temporarily_close(mw.col)
    mw.col.close_for_full_sync()

    label = tr.sync_uploading_to_ankiweb()

    def on_timer() -> None:
        on_full_sync_timer(mw, label, sync_ui)

    timer = QTimer(mw)
    qconnect(timer.timeout, on_timer)
    timer.start(150)

    def on_future_done(fut: Future) -> None:
        timer.stop()
        mw.reopen(after_full_sync=True)
        mw.reset()
        try:
            fut.result()
        except Exception as err:
            _report_sync_exception(mw, sync_ui, err)
            return on_done()
        sync_ui.complete(tr.sync_collection_complete())
        mw.media_syncer.start_monitoring(operation_id=_media_operation_id(sync_ui))
        return on_done()

    sync_ui.run_task(
        lambda: mw.col.full_upload_or_download(
            auth=mw.pm.sync_auth(), server_usn=server_usn, upload=True
        ),
        on_future_done,
        message=label,
    )


def sync_login(
    mw: aqt.main.AnkiQt,
    on_success: Callable[[], None],
    username: str = "",
    password: str = "",
) -> None:
    def on_future_done(fut: Future[SyncAuth], username: str, password: str) -> None:
        try:
            auth = fut.result()
        except SyncError as e:
            if e.kind is SyncErrorKind.AUTH:
                showWarning(str(e))
                sync_login(mw, on_success, username, password)
            else:
                handle_sync_error(mw, e)
            return
        except Exception as err:
            handle_sync_error(mw, err)
            return

        mw.pm.set_sync_key(auth.hkey)
        mw.pm.set_sync_username(username)

        on_success()

    def callback(username: str, password: str) -> None:
        if not username and not password:
            return
        if username and password:
            mw.taskman.with_progress(
                lambda: mw.col.sync_login(
                    username=username, password=password, endpoint=mw.pm.sync_endpoint()
                ),
                functools.partial(on_future_done, username=username, password=password),
                parent=mw,
            )
        else:
            sync_login(mw, on_success, username, password)

    get_id_and_pass_from_user(mw, callback, username, password)


def get_id_and_pass_from_user(
    mw: aqt.main.AnkiQt,
    callback: Callable[[str, str], None],
    username: str = "",
    password: str = "",
) -> None:
    diag = QDialog(mw)
    diag.setWindowTitle(tr.qt_misc_sync())
    disable_help_button(diag)
    diag.setWindowModality(Qt.WindowModality.WindowModal)
    vbox = QVBoxLayout()
    info_label = QLabel(
        without_unicode_isolation(
            tr.sync_account_required(link="https://ankiweb.net/account/register")
        )
    )
    info_label.setOpenExternalLinks(True)
    info_label.setWordWrap(True)
    vbox.addWidget(info_label)
    vbox.addSpacing(20)
    g = QGridLayout()
    l1 = QLabel(tr.sync_ankiweb_id_label())
    g.addWidget(l1, 0, 0)
    user = QLineEdit()
    user.setText(username)
    g.addWidget(user, 0, 1)
    l1.setBuddy(user)
    l2 = QLabel(tr.sync_password_label())
    g.addWidget(l2, 1, 0)
    passwd = QLineEdit()
    passwd.setText(password)
    passwd.setEchoMode(QLineEdit.EchoMode.Password)
    g.addWidget(passwd, 1, 1)
    l2.setBuddy(passwd)
    vbox.addLayout(g)
    bb = QDialogButtonBox(
        QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
    )  # type: ignore
    ok_button = bb.button(QDialogButtonBox.StandardButton.Ok)
    assert ok_button is not None
    ok_button.setAutoDefault(True)
    qconnect(bb.accepted, diag.accept)
    qconnect(bb.rejected, diag.reject)
    vbox.addWidget(bb)
    diag.setLayout(vbox)
    diag.adjustSize()
    diag.show()
    user.setFocus()

    def on_finished(result: int) -> None:
        if result == QDialog.DialogCode.Rejected:
            callback("", "")
        else:
            callback(user.text().strip(), passwd.text())

    qconnect(diag.finished, on_finished)
    diag.open()


# export platform version to syncing code
os.environ["PLATFORM"] = plat_desc()
