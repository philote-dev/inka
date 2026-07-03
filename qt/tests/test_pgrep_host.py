# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Tests for the pgrep surface-mode host logic.

These prove the exclusive takeover (Option C) works without shipping it. The
default stays ``hosted`` (Option A), and the pure decision helpers are covered
directly so no Qt main window is needed.
"""

import types

import pytest

from aqt import pgrep_host


def _fake_mw(meta: dict | None = None) -> tuple[types.SimpleNamespace, dict]:
    """A minimal stand-in for AnkiQt with just the profile meta the host reads."""
    saved = {"count": 0}

    def save() -> None:
        saved["count"] += 1

    pm = types.SimpleNamespace(meta=dict(meta or {}), save=save)
    return types.SimpleNamespace(pm=pm), saved


def test_hosted_is_the_default() -> None:
    mw, _ = _fake_mw()
    assert pgrep_host.surface_mode(mw) == "hosted"
    assert pgrep_host.leads_with_pgrep(mw) is True
    assert pgrep_host.default_state(mw) == "pgrep"


def test_unknown_mode_falls_back_to_hosted() -> None:
    mw, _ = _fake_mw({"pgrep_surface_mode": "bogus"})
    assert pgrep_host.surface_mode(mw) == "hosted"


def test_hosted_keeps_anki_reachable() -> None:
    assert pgrep_host.anki_fallback_enabled("hosted") is True
    # hosted does not redirect, so Anki's deck browser stays reachable.
    assert pgrep_host.redirect_state("hosted", "deckBrowser") == "deckBrowser"


def test_exclusive_hides_anki_and_redirects() -> None:
    assert pgrep_host.anki_fallback_enabled("exclusive") is False
    assert pgrep_host.redirect_state("exclusive", "deckBrowser") == "pgrep"
    # Other states are untouched even in exclusive mode.
    assert pgrep_host.redirect_state("exclusive", "overview") == "overview"
    assert pgrep_host.redirect_state("exclusive", "pgrep") == "pgrep"


def test_exclusive_still_leads_with_pgrep() -> None:
    mw, _ = _fake_mw({"pgrep_surface_mode": "exclusive"})
    assert pgrep_host.leads_with_pgrep(mw) is True
    assert pgrep_host.default_state(mw) == "pgrep"


def test_off_mode_leads_with_anki() -> None:
    mw, _ = _fake_mw({"pgrep_surface_mode": "off"})
    assert pgrep_host.leads_with_pgrep(mw) is False
    assert pgrep_host.default_state(mw) == "deckBrowser"
    # off is stock Anki, so the fallback action is redundant but stays offered.
    assert pgrep_host.anki_fallback_enabled("off") is True


def test_set_surface_mode_round_trips_and_validates() -> None:
    mw, saved = _fake_mw()
    pgrep_host.set_surface_mode(mw, "exclusive")
    assert mw.pm.meta["pgrep_surface_mode"] == "exclusive"
    assert pgrep_host.surface_mode(mw) == "exclusive"
    assert saved["count"] == 1
    with pytest.raises(ValueError):
        pgrep_host.set_surface_mode(mw, "nonsense")
