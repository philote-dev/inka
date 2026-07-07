# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
from aqt.pgrep_about import about_html


def _html() -> str:
    return about_html(
        license_line="Anki is licensed under the AGPL3 license.",
        version_line="Version 26.05",
        seam_line="pgrep: ok",
        env_line="Python 3.13 Qt 6 Chromium 130",
        contributors_html="Damien Elmes, and others",
    )


def test_about_leads_with_pgrep():
    html = _html()
    assert "pgrep" in html
    # pgrep leads, the Anki marketing logo and lede are gone
    assert "anki-logo-thin.png" not in html
    assert "friendly, intelligent" not in html


def test_about_keeps_the_anki_credit():
    html = _html()
    # the AGPL credit that names Anki stays, this is the licenses part
    assert "AGPL" in html
    assert "Anki" in html
    assert "Ankitects" in html
