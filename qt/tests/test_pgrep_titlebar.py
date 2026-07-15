# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Tests for the pgrep macOS title-bar runtime.

Only the pure helpers are covered here; the drag strip needs a live window, so it
is verified manually. The negative install path (not mac, or not exclusive) is
still exercised because it returns before touching Qt.
"""

import types

import pytest

from aqt import pgrep_titlebar


def test_native_titlebar_enabled_only_for_mac_exclusive() -> None:
    assert pgrep_titlebar.native_titlebar_enabled("exclusive", True) is True
    assert pgrep_titlebar.native_titlebar_enabled("exclusive", False) is False
    assert pgrep_titlebar.native_titlebar_enabled("hosted", True) is False
    assert pgrep_titlebar.native_titlebar_enabled("off", True) is False


def test_inset_script_sets_the_custom_property() -> None:
    script = pgrep_titlebar.titlebar_inset_script(28)
    assert "--pgrep-titlebar-inset" in script
    assert "'28px'" in script
    # Value is coerced to an int so a float never leaks into the CSS.
    assert "'34px'" in pgrep_titlebar.titlebar_inset_script(34.7)  # type: ignore[arg-type]


def test_clamp_inset_never_below_the_floor() -> None:
    floor = pgrep_titlebar._DEFAULT_INSET
    # Zero or too-small reported margins are lifted to the floor, so content can
    # never under-inset and collide with the traffic lights.
    assert pgrep_titlebar.clamp_inset(0) == floor
    assert pgrep_titlebar.clamp_inset(-5) == floor
    assert pgrep_titlebar.clamp_inset(floor - 1) == floor
    # A larger real safe area is honored as-is.
    assert pgrep_titlebar.clamp_inset(floor + 24) == floor + 24


def test_install_is_a_noop_when_not_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # not exclusive -> install returns before touching Qt, so a bare stub is fine
    calls = {"surface": "hosted"}
    mw = types.SimpleNamespace(pgrep_web=None, form=types.SimpleNamespace())
    monkeypatch.setattr(pgrep_titlebar, "_current_mode", lambda _mw: calls["surface"])
    monkeypatch.setattr(pgrep_titlebar, "_running_on_mac", lambda: True)
    pgrep_titlebar.install(mw)
    assert not hasattr(mw, "_pgrep_titlebar_drag")


def test_push_inset_is_a_noop_without_a_webview() -> None:
    mw = types.SimpleNamespace(pgrep_web=None)
    # No pgrep webview means nothing to eval into; must not raise.
    pgrep_titlebar.push_inset(mw)


def test_install_is_idempotent_when_already_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A window can be shown more than once (headless dev-window re-show), so a
    # second install must not build a second strip; it refreshes the existing one.
    relaid = {"count": 0}
    existing = types.SimpleNamespace(relayout=lambda: relaid.__setitem__("count", 1))
    mw = types.SimpleNamespace(pgrep_web=None, _pgrep_titlebar_drag=existing)
    monkeypatch.setattr(pgrep_titlebar, "_current_mode", lambda _mw: "exclusive")
    monkeypatch.setattr(pgrep_titlebar, "_running_on_mac", lambda: True)
    pgrep_titlebar.install(mw)
    assert mw._pgrep_titlebar_drag is existing
    assert relaid["count"] == 1
