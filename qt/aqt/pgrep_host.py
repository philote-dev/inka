# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""pgrep desktop host takeover (L2.5).

Make the pgrep web surface the app's primary screen so ``just run`` and the
installed build open into pgrep instead of Anki's deck browser, while keeping
Anki's own screens reachable (Option A). This is the thin-host stance from
``technical-architecture.md`` (c), implemented reversibly.

Surface mode is stored in the local, un-synced profile meta under
``pgrep_surface_mode``:

- ``hosted`` (default): pgrep leads; Anki's screens reachable via the Tools
  fallback + toolbar. This is Option A.
- ``exclusive``: pgrep leads and Anki's screens are hidden (Option C). The A->C
  change is defaulting the mode here plus hiding the toolbar and dropping the
  "Open Anki screens" action.
- ``off``: stock Anki (deck browser leads); the pgrep surface is not built.

The surface reuses the exact PGREP-kind ``AnkiWebView`` + ``/pgrep`` SvelteKit
SPA that the Tools > pgrep window already uses, so the JSON bridge behaves
identically.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from aqt.qt import Qt
from aqt.webview import AnkiWebView, AnkiWebViewKind

if TYPE_CHECKING:
    import aqt.main

_META_KEY = "pgrep_surface_mode"
_ENV_KEY = "PGREP_SURFACE_MODE"
_DEFAULT_MODE = "exclusive"
_VALID_MODES = ("hosted", "exclusive", "off")


def surface_mode(mw: aqt.main.AnkiQt) -> str:
    """Return the current surface mode.

    Resolution order: the ``PGREP_SURFACE_MODE`` env override, then the profile
    meta, then the default (``exclusive``, the clean standalone surface).

    ``exclusive`` is the product: pgrep's own chrome only, Anki's screens and
    admin menus hidden. The dev hatch back to Anki (its deck browser, the dev
    lab, the full menus) is ``PGREP_SURFACE_MODE=hosted`` (or ``off`` for stock
    Anki), so a normal ``just run`` still opens what learners will see.
    """
    env = os.environ.get(_ENV_KEY)
    if env in _VALID_MODES:
        return env
    mode = mw.pm.meta.get(_META_KEY)
    if mode in _VALID_MODES:
        return mode
    return _DEFAULT_MODE


def set_surface_mode(mw: aqt.main.AnkiQt, mode: str) -> None:
    """Persist the surface mode (takes effect on next launch)."""
    if mode not in _VALID_MODES:
        raise ValueError(f"invalid pgrep surface mode: {mode!r}")
    mw.pm.meta[_META_KEY] = mode
    mw.pm.save()


def leads_with_pgrep(mw: aqt.main.AnkiQt) -> bool:
    """True when pgrep should be the primary surface (hosted or exclusive)."""
    return surface_mode(mw) != "off"


def default_state(mw: aqt.main.AnkiQt) -> aqt.main.MainWindowState:
    """The main-window state to enter after the collection loads."""
    if leads_with_pgrep(mw):
        return "pgrep"
    return "deckBrowser"


def anki_fallback_enabled(mode: str) -> bool:
    """True when Anki's own screens stay reachable (the Option A fallback).

    In ``exclusive`` mode (Option C) Anki's screens are hidden, so the
    "Open Anki screens" Tools action is not offered. ``off`` is stock Anki,
    where the fallback is redundant but harmless, so it stays available.
    """
    return mode != "exclusive"


def redirect_state(
    mode: str, requested: aqt.main.MainWindowState
) -> aqt.main.MainWindowState:
    """Remap a requested main-window state for the current surface mode.

    In ``exclusive`` mode Anki's deck browser is unreachable, so a request for
    it returns to the pgrep surface instead. Every other mode and state is
    returned unchanged, so ``hosted`` and ``off`` behave exactly as before.
    """
    if mode == "exclusive" and requested == "deckBrowser":
        return "pgrep"
    return requested


def make_surface_web(mw: aqt.main.AnkiQt) -> AnkiWebView | None:
    """Create the central pgrep webview, or ``None`` in ``off`` mode.

    The page is loaded lazily on first entry to the pgrep state (see
    ``enter_pgrep``), so this is safe to call before the collection is open.
    """
    if not leads_with_pgrep(mw):
        return None
    web = AnkiWebView(kind=AnkiWebViewKind.PGREP)
    web.setFocusPolicy(Qt.FocusPolicy.WheelFocus)
    web.setVisible(False)
    return web


def enter_pgrep(mw: aqt.main.AnkiQt) -> None:
    """Load the pgrep SPA into the central webview on first entry."""
    web = mw.pgrep_web
    if web is None:
        # 'off' at startup; nothing to host, fall back to Anki.
        mw.moveToState("deckBrowser")
        return
    if not getattr(web, "_pgrep_loaded", False):
        web.load_sveltekit_page("pgrep")
        setattr(web, "_pgrep_loaded", True)


def sync_central_surface(mw: aqt.main.AnkiQt, state: str) -> None:
    """Show the pgrep webview for the pgrep state, Anki's webview otherwise."""
    web = mw.pgrep_web
    if web is None:
        return
    pgrep_active = state == "pgrep"
    web.setVisible(pgrep_active)
    mw.web.setVisible(not pgrep_active)
    # pgrep brings its own left-rail chrome, so hide Anki's top toolbar and
    # bottom bar while it leads. Both return when Anki's screens do (Option A,
    # reachable via Tools > Open Anki screens).
    mw.toolbarWeb.setVisible(not pgrep_active)
    mw.bottomWeb.setVisible(not pgrep_active)


def apply_menu_chrome(mw: aqt.main.AnkiQt) -> None:
    """Hide Anki's collection-admin menus in the shipped standalone surface.

    In ``exclusive`` mode pgrep is the whole app, so the native File, View,
    Tools, and Help menus (import/export, note types, add-ons, database checks,
    Anki's own docs) are hidden and only Edit stays for text fields. Anki's
    Preferences is dropped from the macOS app menu too, since pgrep carries its
    own Settings. ``hosted`` and ``off`` keep every menu, the dev hatch.

    Reversible: it only toggles action visibility. About and Quit keep their
    macOS app-menu slots because Qt relocates their role actions when the
    menubar is built, before this runs.
    """
    if surface_mode(mw) != "exclusive":
        return
    form = mw.form
    for menu in (
        form.menuCol,
        form.menuqt_accel_view,
        form.menuTools,
        form.menuHelp,
    ):
        menu.menuAction().setVisible(False)
    form.actionPreferences.setVisible(False)
