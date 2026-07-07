# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Tests for the pgrep surface-mode host logic.

The shipped default is ``exclusive`` (the clean standalone surface); dev runs
default to ``hosted`` so Anki stays reachable (the dev hatch). The pure decision
helpers are covered directly so no Qt main window is needed.
"""

import types
from unittest import mock

import pytest

from aqt import pgrep_host


def _fake_mw(meta: dict | None = None) -> tuple[types.SimpleNamespace, dict]:
    """A minimal stand-in for AnkiQt with just the profile meta the host reads."""
    saved = {"count": 0}

    def save() -> None:
        saved["count"] += 1

    pm = types.SimpleNamespace(meta=dict(meta or {}), save=save)
    return types.SimpleNamespace(pm=pm), saved


def test_exclusive_is_the_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PGREP_SURFACE_MODE", raising=False)
    mw, _ = _fake_mw()
    assert pgrep_host.surface_mode(mw) == "exclusive"
    assert pgrep_host.leads_with_pgrep(mw) is True
    assert pgrep_host.default_state(mw) == "pgrep"


def test_unknown_mode_falls_back_to_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PGREP_SURFACE_MODE", raising=False)
    mw, _ = _fake_mw({"pgrep_surface_mode": "bogus"})
    assert pgrep_host.surface_mode(mw) == "exclusive"


def test_hosted_is_the_dev_hatch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PGREP_SURFACE_MODE", raising=False)
    # The stored meta opts back into Anki's reachable, full-menu surface.
    mw, _ = _fake_mw({"pgrep_surface_mode": "hosted"})
    assert pgrep_host.surface_mode(mw) == "hosted"


def test_env_override_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    mw, _ = _fake_mw({"pgrep_surface_mode": "off"})
    monkeypatch.setenv("PGREP_SURFACE_MODE", "hosted")
    assert pgrep_host.surface_mode(mw) == "hosted"
    # An invalid env value is ignored, so the stored meta wins.
    monkeypatch.setenv("PGREP_SURFACE_MODE", "bogus")
    assert pgrep_host.surface_mode(mw) == "off"


def test_apply_menu_chrome_hides_admin_menus_only_in_exclusive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PGREP_SURFACE_MODE", raising=False)

    # The dev hatch (hosted) keeps every menu: nothing is hidden.
    hosted, _ = _fake_mw({"pgrep_surface_mode": "hosted"})
    hosted.form = mock.MagicMock()
    pgrep_host.apply_menu_chrome(hosted)
    hosted.form.menuTools.menuAction().setVisible.assert_not_called()

    # Exclusive (the default product surface) hides the admin menus and
    # Anki's Preferences.
    exclusive, _ = _fake_mw()
    exclusive.form = mock.MagicMock()
    pgrep_host.apply_menu_chrome(exclusive)
    exclusive.form.menuTools.menuAction().setVisible.assert_called_with(False)
    exclusive.form.menuCol.menuAction().setVisible.assert_called_with(False)
    exclusive.form.actionPreferences.setVisible.assert_called_with(False)


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


def test_profile_autoload_exclusive_prefers_last_loaded() -> None:
    # the product is single-user: exclusive auto-opens, never shows the chooser
    assert (
        pgrep_host.profile_to_autoload("exclusive", ["User 1", "Frank"], "Frank")
        == "Frank"
    )


def test_profile_autoload_exclusive_falls_back_to_first() -> None:
    # last-loaded missing or unset, take the first profile
    assert (
        pgrep_host.profile_to_autoload("exclusive", ["User 1", "Frank"], "Gone")
        == "User 1"
    )
    assert pgrep_host.profile_to_autoload("exclusive", ["User 1"], None) == "User 1"


def test_profile_autoload_dev_hatch_returns_none() -> None:
    # hosted and off keep Anki's chooser (the dev hatch), so no auto-open
    assert pgrep_host.profile_to_autoload("hosted", ["User 1"], "User 1") is None
    assert pgrep_host.profile_to_autoload("off", ["User 1"], "User 1") is None


def test_profile_autoload_none_when_no_profiles() -> None:
    assert pgrep_host.profile_to_autoload("exclusive", [], "User 1") is None
