# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""macOS native title-bar runtime for the pgrep product surface.

The exclusive product on macOS extends the web surface under a transparent title
bar (see ``pgrep_host.apply_native_titlebar``). That leaves two gaps this module
fills. The window can no longer be dragged by its top edge, because the
``QWebEngineView`` covers the whole window and consumes the mouse events a native
drag needs, so a thin transparent strip restores dragging. And the real
traffic-light inset must reach the web as a variable rather than a guessed
constant, so it is read from Qt's safe-area margins and pushed to the page.

Everything here is scoped to macOS plus surface mode ``exclusive``; it is inert
elsewhere.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from aqt.qt import QEvent, Qt, QWidget

if TYPE_CHECKING:
    import aqt.main
    from aqt.qt import QMouseEvent, QObject, QPoint

# Width reserved at the top-left for the macOS traffic lights, so the drag strip
# never sits over them and swallows their clicks. The three controls span roughly
# 13..77px; 80 leaves a small margin.
_TRAFFIC_LIGHTS_WIDTH = 80

# Fallback title-bar inset used before Qt reports a real safe area, and as the CSS
# fallback. Matches the historic hardcoded value.
_DEFAULT_INSET = 28


def native_titlebar_enabled(mode: str, is_mac: bool) -> bool:
    """True only for the shipped product on macOS (exclusive plus mac)."""
    return is_mac and mode == "exclusive"


def titlebar_inset_script(top_px: int) -> str:
    """JS that sets the ``--pgrep-titlebar-inset`` custom property on the page."""
    return (
        "document.documentElement.style.setProperty("
        f"'--pgrep-titlebar-inset', '{int(top_px)}px');"
    )


def _running_on_mac() -> bool:
    from anki.utils import is_mac

    return is_mac


def _current_mode(mw: aqt.main.AnkiQt) -> str:
    from aqt import pgrep_host

    return pgrep_host.surface_mode(mw)


def _safe_area_top(mw: aqt.main.AnkiQt) -> int:
    """The true traffic-light inset in px, or the fallback before Qt reports it."""
    handle = mw.windowHandle()
    top = handle.safeAreaMargins().top() if handle is not None else 0
    return top if top > 0 else _DEFAULT_INSET


class PgrepTitleBarDrag(QWidget):
    """Transparent strip over the top edge that moves the window on drag.

    Parented to the central widget and kept above the pgrep webview. It grabs only
    press (start a native window move, with a manual-move fallback) and
    double-click (toggle zoom); every other event passes through untouched. It is
    its own event filter on the central widget, so it re-lays-out on resize.
    """

    def __init__(self, mw: aqt.main.AnkiQt) -> None:
        self._mw = mw
        central = mw.form.centralwidget
        super().__init__(central)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setCursor(Qt.CursorShape.ArrowCursor)
        # Fallback drag offset, set only when startSystemMove is unavailable.
        self._manual_origin: QPoint | None = None
        central.installEventFilter(self)
        self.relayout()

    def relayout(self) -> None:
        parent = self.parentWidget()
        if parent is None:
            return
        top = _safe_area_top(self._mw)
        width = max(0, parent.width() - _TRAFFIC_LIGHTS_WIDTH)
        self.setGeometry(_TRAFFIC_LIGHTS_WIDTH, 0, width, top)
        self.raise_()

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        if event.type() == QEvent.Type.Resize:
            self.relayout()
        return False

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            event.ignore()
            return
        handle = self._mw.windowHandle()
        if handle is not None and handle.startSystemMove():
            event.accept()
            return
        # Fallback: track the offset and move the window manually.
        self._manual_origin = (
            event.globalPosition().toPoint() - self._mw.frameGeometry().topLeft()
        )
        event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._manual_origin is not None and (
            event.buttons() & Qt.MouseButton.LeftButton
        ):
            self._mw.move(event.globalPosition().toPoint() - self._manual_origin)
            event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._manual_origin = None
        event.accept()

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        win = self._mw
        win.setWindowState(win.windowState() ^ Qt.WindowState.WindowMaximized)
        event.accept()


def push_inset(mw: aqt.main.AnkiQt) -> None:
    """Send the current traffic-light inset to the pgrep page as a CSS variable."""
    web = getattr(mw, "pgrep_web", None)
    if web is None:
        return
    web.eval(titlebar_inset_script(_safe_area_top(mw)))


def install(mw: aqt.main.AnkiQt) -> None:
    """Create the drag strip and start tracking the safe-area inset.

    Call after the main window is shown, on every show path (the normal run and
    the headless dev-window/review re-show). Idempotent: a second call refreshes
    the existing strip rather than building another. Inert unless mac plus
    exclusive.
    """
    if not native_titlebar_enabled(_current_mode(mw), _running_on_mac()):
        return
    existing = getattr(mw, "_pgrep_titlebar_drag", None)
    if existing is not None:
        existing.relayout()
        push_inset(mw)
        return
    strip = PgrepTitleBarDrag(mw)
    strip.show()
    # Keep a reference so the widget and its event filter outlive this call.
    mw._pgrep_titlebar_drag = strip  # type: ignore[attr-defined]
    handle = mw.windowHandle()
    if handle is not None:

        def _on_safe_area_changed() -> None:
            strip.relayout()
            push_inset(mw)

        handle.safeAreaMarginsChanged.connect(_on_safe_area_changed)
    push_inset(mw)
