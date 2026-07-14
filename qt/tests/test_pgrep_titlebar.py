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
