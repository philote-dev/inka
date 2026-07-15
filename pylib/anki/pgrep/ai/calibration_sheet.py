# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Blind Markdown rendering and figure assets for the calibration ruler.

Pass A sheets expose only the review ID, protected stem, five protected choices,
a relative figure link when needed, and unfilled rubric fields. Sanitized SVG
bytes are returned separately by :func:`figure_assets`. Hidden metadata stays
in the private manifest. This module is pure, with no filesystem or network
access.
"""

from __future__ import annotations

import html
import re
from collections.abc import Sequence
from pathlib import PurePosixPath

from .calibration_ruler import RulerItem, RulerManifest

PASS_A_FIELDS = (
    "your_answer",
    "stem_clear",
    "distractor_A",
    "distractor_B",
    "distractor_C",
    "distractor_D",
    "distractor_E",
    "figure",
    "difficulty",
    "overall",
    "notes",
)

PASS_A_INSTRUCTIONS = (
    "Work independently. Do not use another AI system.",
    "In Pass A, solve the problem before consulting any outside reference.",
    "A calculator and scratch work are allowed.",
    "Use `UNSURE` instead of guessing.",
    "Judge the presented problem, not how easily it could be repaired.",
    (
        "Mark a distractor valid only if it is wrong, distinct, and plausibly "
        "caused by a learner misconception."
    ),
    "Judge a figure against the prose, not against the hidden intended answer.",
    "Do not infer model identity from writing style.",
    "Do not edit item IDs or machine-parseable field names.",
    "Complete Pass A and import it before opening Pass B.",
)

PASS_A_VALUE_LEGEND = (
    "`your_answer` = `A`, `B`, `C`, `D`, `E`, or `UNSURE`",
    "`stem_clear` = `PASS`, `FAIL`, or `UNSURE`",
    (
        "`distractor_A` through `distractor_E` = `VALID`, `INVALID`, "
        "`CORRECT_ANSWER`, or `UNSURE`"
    ),
    (
        "`figure` = `MATCHES`, `CONTRADICTS`, `UNNECESSARY`, `MISSING`, "
        "`N_A`, or `UNSURE`"
    ),
    "`difficulty` = `1`, `2`, `3`, `4`, `5`, or `UNSURE`",
    "`overall` = `KEEP`, `DROP`, or `UNSURE`",
    "`notes` = free text",
)

BLOCK_CAPACITY = 20
_CHOICE_LABELS = ("A", "B", "C", "D", "E")
_SAFE_REVIEW_ID = re.compile(r"(?:cal|rep)-[0-9]{4}\Z", re.ASCII)
_MARKDOWN_PROTECTION = str.maketrans(
    {
        "#": "&#35;",
        "`": "&#96;",
        "-": "&#45;",
        "*": "&#42;",
        "_": "&#95;",
        ":": "&#58;",
    }
)


def _items_from(value: object) -> tuple[RulerItem, ...]:
    if isinstance(value, RulerManifest):
        items = value.items
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        items = tuple(value)
        if not all(isinstance(item, RulerItem) for item in items):
            raise TypeError("expected a RulerManifest or a sequence of RulerItem")
    else:
        raise TypeError("expected a RulerManifest or a sequence of RulerItem")

    seen: set[str] = set()
    for item in items:
        review_id = _require_review_id(item)
        if review_id in seen:
            raise ValueError(f"duplicate review ID: {review_id}")
        seen.add(review_id)
    return items


def _require_review_id(item: RulerItem) -> str:
    review_id = item.review_id
    if type(review_id) is not str or _SAFE_REVIEW_ID.fullmatch(review_id) is None:
        raise ValueError("safe review ID must match 'cal-0000' or 'rep-0000' shape")
    return review_id


def protect_markdown_text(text: str) -> str:
    """Reversibly neutralize structural Markdown and HTML tokens.

    HTML-sensitive characters and Markdown punctuation used by headings, code
    fences, separators, and rubric fields become character references. Markdown
    renders those references as the original human-readable text but does not
    reinterpret them as structure. Existing entities and zero-width characters
    survive an exact protect/unprotect round trip.
    """
    if type(text) is not str:
        raise TypeError("Markdown text must be a string")
    return html.escape(text, quote=False).translate(_MARKDOWN_PROTECTION)


def unprotect_markdown_text(text: str) -> str:
    """Restore text emitted by :func:`protect_markdown_text` exactly.

    A future parser must call this function on visible stem and choice text. It
    must not strip zero-width or other characters.
    """
    if type(text) is not str:
        raise TypeError("protected Markdown text must be a string")
    return html.unescape(text)


def _figure_asset_path(review_id: str) -> str:
    path = PurePosixPath("figures", f"{review_id}.svg")
    if (
        path.is_absolute()
        or path.parts != ("figures", f"{review_id}.svg")
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise ValueError(f"unsafe figure asset path for review ID: {review_id}")
    return path.as_posix()


def _render_figure(review_id: str, figure: str) -> str:
    if not figure:
        return ""
    return f"![Figure](../{_figure_asset_path(review_id)})"


def _render_rubric() -> str:
    return "\n".join(f"{field}:" for field in PASS_A_FIELDS)


def _render_header() -> str:
    lines = ["# Pass A", ""]
    for index, instruction in enumerate(PASS_A_INSTRUCTIONS, start=1):
        lines.append(f"{index}. {instruction}")
    lines.extend(["", "## Allowed rubric values", ""])
    lines.extend(f"- {legend}" for legend in PASS_A_VALUE_LEGEND)
    lines.extend(["", "---", ""])
    return "\n".join(lines)


def render_pass_a_block(item: RulerItem) -> str:
    """Render one blind Pass A judgment block for a ruler item."""
    if not isinstance(item, RulerItem):
        raise TypeError("render_pass_a_block expects a RulerItem")
    review_id = _require_review_id(item)
    content = item.pass_a_content()
    stem = protect_markdown_text(str(content["stem"]))
    choices = _as_choices(content["choices"])
    figure = str(content["figure"])

    lines = [f"### {review_id}", "", "**Stem.**", "", stem, ""]
    for label, choice in zip(_CHOICE_LABELS, choices, strict=True):
        lines.append(f"**{label})** {protect_markdown_text(choice)}")
    lines.append("")
    if figure_markup := _render_figure(review_id, figure):
        lines.extend([figure_markup, ""])
    lines.extend([_render_rubric(), "", "---", ""])
    return "\n".join(lines)


def _as_choices(value: object) -> list[str]:
    if type(value) is not list or len(value) != 5:
        raise ValueError("Pass A choices must contain exactly five strings")
    return [str(choice) for choice in value]


def figure_assets(
    items: RulerManifest | Sequence[RulerItem],
) -> dict[str, bytes]:
    """Map safe run-root-relative asset paths to exact validated SVG bytes.

    Each review ID gets its own path, including hidden repeats. A publisher
    writes these bytes below the review workspace without modification. A
    future parser receives the bytes separately, decodes UTF-8 strictly, and
    includes that exact figure string when recomputing ``pass_a_hash``.
    """
    assets: dict[str, bytes] = {}
    for item in _items_from(items):
        review_id = _require_review_id(item)
        figure = str(item.pass_a_content()["figure"])
        if not figure:
            continue
        path = _figure_asset_path(review_id)
        if path in assets:
            raise ValueError(f"figure asset path collision: {path}")
        assets[path] = figure.encode("utf-8")
    return assets


def render_blocks(
    items: RulerManifest | Sequence[RulerItem],
    *,
    pass_name: str,
) -> list[str]:
    """Render Pass A Markdown documents with at most 20 judgments each."""
    if pass_name != "a":
        raise ValueError("pass_name must be 'a' for Pass A rendering")
    ordered = _items_from(items)
    if not ordered:
        return []
    header = _render_header()
    blocks: list[str] = []
    for start in range(0, len(ordered), BLOCK_CAPACITY):
        chunk = ordered[start : start + BLOCK_CAPACITY]
        body = "".join(render_pass_a_block(item) for item in chunk)
        blocks.append(header + body)
    return blocks


def render_index(items: RulerManifest | Sequence[RulerItem]) -> str:
    """Render a blind index of review IDs and completion placeholders only."""
    ordered = _items_from(items)
    lines = [
        "# Review index",
        "",
        "Mark `[x]` when a pass is complete. Review IDs only.",
        "",
    ]
    for item in ordered:
        review_id = _require_review_id(item)
        lines.append(f"- {review_id}: pass_a=[ ] pass_b=[ ]")
    lines.append("")
    return "\n".join(lines)
