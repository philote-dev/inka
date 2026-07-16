# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Tests for the pgrep surface-mode host logic.

The shipped default is ``exclusive`` (the clean standalone surface); dev runs
default to ``hosted`` so Anki stays reachable (the dev hatch). The pure decision
helpers are covered directly so no Qt main window is needed.
"""

import types

import pytest

import aqt.main
import aqt.mediasync
from aqt import pgrep_host, pgrep_operation
from aqt.pgrep_operation import OperationController, ProductSyncUi


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


def test_chooser_suppressed_only_in_exclusive() -> None:
    # the product never shows Anki's profile chooser; the dev hatch keeps it
    assert pgrep_host.suppress_profile_chooser("exclusive") is True
    assert pgrep_host.suppress_profile_chooser("hosted") is False
    assert pgrep_host.suppress_profile_chooser("off") is False


def test_headless_reads_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PGREP_HEADLESS", raising=False)
    assert pgrep_host.headless() is False
    monkeypatch.setenv("PGREP_HEADLESS", "1")
    assert pgrep_host.headless() is True
    monkeypatch.setenv("PGREP_HEADLESS", "0")
    assert pgrep_host.headless() is False


def test_main_sync_uses_product_ui_when_pgrep_leads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controller = OperationController()
    monkeypatch.setattr(pgrep_operation, "operation_controller", controller)
    monkeypatch.setattr(pgrep_host, "leads_with_pgrep", lambda _mw: True)
    monkeypatch.setattr(aqt.main.gui_hooks, "sync_will_start", lambda: None)
    captured: dict = {}
    monkeypatch.setattr(
        aqt.main,
        "sync_collection",
        lambda mw, on_done, *, ui=None: captured.update(ui=ui),
    )
    mw = types.SimpleNamespace(
        col=types.SimpleNamespace(abort_sync=lambda: None),
        taskman=types.SimpleNamespace(run_on_main=lambda fn: fn()),
    )

    aqt.main.AnkiQt._sync_collection_and_media(mw, lambda: None)

    assert isinstance(captured["ui"], ProductSyncUi)


def test_product_sync_shortcut_routes_to_in_app_login(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(pgrep_host, "leads_with_pgrep", lambda _mw: True)
    native_login: list[bool] = []
    monkeypatch.setattr(
        aqt.main, "sync_login", lambda *_args, **_kwargs: native_login.append(True)
    )
    routes: list[str] = []
    mw = types.SimpleNamespace(
        media_syncer=types.SimpleNamespace(
            is_syncing=lambda: False,
            show_sync_log=lambda: routes.append("native-log"),
        ),
        pm=types.SimpleNamespace(sync_auth=lambda: None),
        pgrep_navigate=routes.append,
    )

    aqt.main.AnkiQt.on_sync_button_clicked(mw)

    assert routes == ["pgrep/login"]
    assert native_login == []


def test_product_media_failure_is_in_app(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controller = OperationController()
    monkeypatch.setattr(pgrep_operation, "operation_controller", controller)
    operation_id = controller.begin("sync", "Syncing")
    monkeypatch.setattr(pgrep_host, "leads_with_pgrep", lambda _mw: True)
    native_info: list[str] = []
    monkeypatch.setattr(
        aqt.mediasync,
        "show_info",
        lambda message, **_kwargs: native_info.append(message),
    )
    syncer = aqt.mediasync.MediaSyncer.__new__(aqt.mediasync.MediaSyncer)
    syncer.mw = types.SimpleNamespace(
        taskman=types.SimpleNamespace(run_on_main=lambda fn: fn()),
        pgrep_web=None,
    )
    syncer.last_progress = ""
    syncer._operation_id = operation_id

    syncer._handle_sync_error(Exception("network down"))

    assert controller.snapshot()["operation_id"] == operation_id
    assert controller.snapshot()["phase"] == "error"
    assert native_info == []


def test_product_media_failure_without_active_sync_stays_in_app(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controller = OperationController()
    monkeypatch.setattr(pgrep_operation, "operation_controller", controller)
    monkeypatch.setattr(pgrep_host, "leads_with_pgrep", lambda _mw: True)
    native_info: list[str] = []
    monkeypatch.setattr(
        aqt.mediasync,
        "show_info",
        lambda message, **_kwargs: native_info.append(message),
    )
    syncer = aqt.mediasync.MediaSyncer.__new__(aqt.mediasync.MediaSyncer)
    syncer.mw = types.SimpleNamespace(
        taskman=types.SimpleNamespace(run_on_main=lambda fn: fn()),
        pgrep_web=None,
    )
    syncer.last_progress = ""
    syncer._operation_id = None

    syncer._handle_sync_error(Exception("network down"))

    assert controller.snapshot()["phase"] == "error"
    assert controller.snapshot()["message"] == "Sync failed"
    assert native_info == []


def test_media_monitor_does_not_bind_to_a_newer_operation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controller = OperationController()
    monkeypatch.setattr(pgrep_operation, "operation_controller", controller)
    monkeypatch.setattr(pgrep_host, "leads_with_pgrep", lambda _mw: True)
    first = controller.begin("sync", "First")
    syncer = aqt.mediasync.MediaSyncer.__new__(aqt.mediasync.MediaSyncer)
    syncer.mw = types.SimpleNamespace()
    syncer._operation_id = first
    second = controller.begin("sync", "Second")

    assert syncer._product_operation() is None
    assert controller.snapshot()["operation_id"] == second


def test_product_sync_keeps_window_enabled_for_decisions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(pgrep_host, "leads_with_pgrep", lambda _mw: True)
    assert pgrep_host.disable_window_during_sync(object()) is False
    monkeypatch.setattr(pgrep_host, "leads_with_pgrep", lambda _mw: False)
    assert pgrep_host.disable_window_during_sync(object()) is True


def test_successful_product_sync_records_last_synced_at() -> None:
    saved: list[bool] = []
    meta: dict = {}
    syncer = aqt.mediasync.MediaSyncer.__new__(aqt.mediasync.MediaSyncer)
    syncer.mw = types.SimpleNamespace(
        pm=types.SimpleNamespace(meta=meta, save=lambda: saved.append(True))
    )

    syncer._record_last_synced()

    assert isinstance(meta["pgrep_last_synced_at"], int)
    assert meta["pgrep_last_synced_at"] > 0
    assert saved == [True]


def test_product_shutdown_wait_does_not_open_media_log(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(pgrep_host, "leads_with_pgrep", lambda _mw: True)
    opened: list[str] = []
    fake_dialog = types.SimpleNamespace(show=lambda: None)
    monkeypatch.setattr(
        aqt.dialogs,
        "open",
        lambda name, *_args, **_kwargs: (opened.append(name), fake_dialog)[1],
    )
    syncer = aqt.mediasync.MediaSyncer.__new__(aqt.mediasync.MediaSyncer)
    syncer.mw = types.SimpleNamespace(
        progress=types.SimpleNamespace(timer=lambda *_args, **_kwargs: object())
    )
    syncer._syncing = True

    syncer.show_diag_until_finished(lambda: None)

    assert opened == []
