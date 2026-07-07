# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]


def _read(rel: str) -> str:
    return (_ROOT / rel).read_text(encoding="utf-8")


def test_sync_conflict_uses_server_wording():
    ftl = _read("ftl/core/sync.ftl")
    assert "sync-download-from-ankiweb = Download from server" in ftl
    assert "sync-upload-to-ankiweb = Upload to server" in ftl
    assert "conflict between this device and your sync server" in ftl
    # the user-facing service name is gone from the conflict copy
    assert "and AnkiWeb" not in ftl
    assert "from AnkiWeb" not in ftl


def test_sync_app_name_is_pgrep():
    ftl = _read("ftl/core/sync.ftl")
    assert "Only one copy of pgrep can sync" in ftl
    assert "pgrep is currently syncing" in ftl


def test_errors_app_name_is_pgrep():
    ftl = _read("ftl/qt/errors.ftl")
    assert "pgrep encountered a problem" in ftl
    assert "pgrep was unable to open your collection" in ftl


def test_profiles_app_name_is_pgrep():
    ftl = _read("ftl/core/profiles.ftl")
    assert "pgrep could not read your profile" in ftl
    assert "pgrep could not rename your profile" in ftl
    assert "display pgrep's interface" in ftl
    assert "pgrep could not create its data folder" in ftl
    assert "pgrep's prefs21.db file was corrupt" in ftl
    # the old app name is gone from these values
    assert "Anki could not read" not in ftl
    assert "Anki could not rename" not in ftl
    assert "Anki could not create" not in ftl
    assert "display Anki's interface" not in ftl
    assert "Anki's prefs21.db" not in ftl
    # keys are unchanged and the on-disk data path is left intact
    assert "profiles-anki-could-not-read-your-profile =" in ftl
    assert "profiles-anki-could-not-rename-your-profile =" in ftl
    assert "Documents/Anki" in ftl


def test_qt_misc_app_name_is_pgrep():
    ftl = _read("ftl/qt/qt-misc.ftl")
    assert "<h1>pgrep Updated</h1>pgrep" in ftl
    assert "pgrep requires your computer's internal clock" in ftl
    assert "while pgrep is open" in ftl
    assert "Unable to access pgrep media folder" in ftl
    assert (
        "preventing pgrep from creating a connection to itself. "
        "Please add an exception for pgrep." in ftl
    )
    assert "Please start pgrep again, and pgrep will switch" in ftl
    assert "Please start pgrep again to try the next driver" in ftl
    assert "pgrep Already Running" in ftl
    assert "existing instance of pgrep is not responding" in ftl
    assert "pgrep is not busy" in ftl
    assert "restart pgrep." in ftl


def test_qt_misc_keys_unchanged():
    ftl = _read("ftl/qt/qt-misc.ftl")
    # keys that literally contain "anki" are left alone. Only values changed.
    assert "qt-misc-anki-updatedanki-has-been-released =" in ftl
    assert "qt-misc-unable-to-access-anki-media-folder =" in ftl
    assert "qt-misc-anki-is-running =" in ftl
    # the old app name no longer appears in the rebranded values
    assert "Anki Already Running" not in ftl
    assert "instance of Anki" not in ftl
    assert "restart Anki." not in ftl
