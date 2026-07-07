# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""pgrep About dialog content (Qt-free so it is unit testable).

The dialog leads with the pgrep identity. The Anki attribution stays here, in the
licenses and credits block, to satisfy the AGPL credit requirement in one place.
"""

from __future__ import annotations


def about_html(
    *,
    license_line: str,
    version_line: str,
    seam_line: str | None,
    env_line: str,
    contributors_html: str,
) -> str:
    """Return the About dialog body as HTML.

    All dynamic values are passed in so this function needs no Qt or collection.
    """
    parts: list[str] = []
    parts.append("<center><h1 style='letter-spacing:0.05em'>pgrep</h1></center>")
    parts.append(
        "<p>pgrep is a focused study app for the Physics GRE. "
        "It runs on your own devices and syncs to a server you control."
    )
    parts.append(f"<p>{version_line}<br>")
    if seam_line:
        parts.append(f"{seam_line}<br>")
    parts.append(f"{env_line}")
    parts.append("<hr>")
    parts.append("<p><b>Built on Anki</b>")
    parts.append(
        "<p>pgrep is built on Anki, created by Ankitects Pty Ltd "
        "(Damien Elmes) and the Anki community. "
        f"{license_line} Source is available under that license."
    )
    parts.append(f"<p style='color:gray;font-size:small'>{contributors_html}")
    return "".join(parts)
