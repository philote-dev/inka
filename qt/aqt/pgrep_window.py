# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""The pgrep host window.

A light, non-modal window that embeds an :class:`AnkiWebView` loading the pgrep
SvelteKit SPA at ``/pgrep``. The client-side router then handles the pgrep
surfaces (Home, Study, Progress, Diagnostic). Opened from the Tools menu; a
single instance is reused if the window is already open.
"""

from __future__ import annotations

import aqt
import aqt.main
from aqt.qt import *
from aqt.utils import disable_help_button, restoreGeom, saveGeom
from aqt.webview import AnkiWebView, AnkiWebViewKind


class PgrepWindow(QDialog):
    """Host window embedding the pgrep web surfaces."""

    TITLE = "pgrep"
    silentlyClose = True

    def __init__(self, mw: aqt.main.AnkiQt) -> None:
        QDialog.__init__(self, mw, Qt.WindowType.Window)
        self.mw = mw
        self.mw.garbage_collect_on_dialog_finish(self)
        disable_help_button(self)
        restoreGeom(self, self.TITLE, default_size=(1000, 760))

        self.web: AnkiWebView | None = AnkiWebView(kind=AnkiWebViewKind.PGREP)
        self.web.load_sveltekit_page("pgrep")
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.web)
        self.setLayout(layout)
        self.setWindowTitle("pgrep")
        self.show()

    def reject(self) -> None:
        if self.web:
            self.web.cleanup()
            self.web = None
        saveGeom(self, self.TITLE)
        QDialog.reject(self)


_pgrep_window: PgrepWindow | None = None


def open_pgrep_window() -> None:
    """Open the pgrep window, or focus it if it is already open."""
    global _pgrep_window
    if _pgrep_window is not None:
        try:
            _pgrep_window.activateWindow()
            _pgrep_window.raise_()
            return
        except RuntimeError:
            # Underlying C++ object was already deleted; recreate below.
            _pgrep_window = None

    _pgrep_window = PgrepWindow(aqt.mw)
    qconnect(_pgrep_window.finished, _on_pgrep_window_finished)


def _on_pgrep_window_finished(*_args: object) -> None:
    global _pgrep_window
    _pgrep_window = None
