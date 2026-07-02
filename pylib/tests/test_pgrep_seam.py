# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

from tests.shared import getEmptyCol


def test_pgrep_seam_check():
    col = getEmptyCol()
    assert col.pgrep_seam_check() == "pgrep seam OK (Rust)"
