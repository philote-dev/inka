# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Blind Markdown rendering for the human calibration ruler.

Pass A sheets expose only the review ID, stem, five choices, and a sanitized
inline figure, plus unfilled rubric fields. Hidden metadata stays in the private
manifest. This module is pure: no filesystem or network access.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

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

BLOCK_CAPACITY = 20
_CHOICE_LABELS = ("A", "B", "C", "D", "E")
_THEMATIC_BREAK = re.compile(r"^(?:-{3,}|\*{3,}|_{3,})$")
_ZWSP = "\u200b"


def _items_from(value: object) -> tuple[RulerItem, ...]:
    if isinstance(value, RulerManifest):
        return value.items
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        items = tuple(value)
        if all(isinstance(item, RulerItem) for item in items):
            return items
    raise TypeError("expected a RulerManifest or a sequence of RulerItem")


def _require_review_id(item: RulerItem) -> str:
    if item.review_id is None:
        raise ValueError("review_id is required for Pass A rendering")
    return item.review_id


def _protect_prose(text: str) -> str:
    """Neutralize Markdown constructs that could inject headings or fields.

    Pass A stems are whitespace-collapsed by the ruler schema, so attacks may
    sit mid-line. Break heading markers, fences, comments, separators, and
    rubric field names wherever they appear, while leaving math prose readable.
    """
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    normalized = normalized.replace("<!--", f"<!{_ZWSP}--")
    normalized = normalized.replace("-->", f"--{_ZWSP}>")
    normalized = normalized.replace("```", f"`{_ZWSP}``")
    # Insert ZWSP so "###" is never a contiguous token reviewers or parsers see.
    normalized = normalized.replace("###", f"##{_ZWSP}#")
    normalized = normalized.replace("##", f"#{_ZWSP}#")
    lines: list[str] = []
    for line in normalized.split("\n"):
        stripped = line.lstrip()
        if stripped.startswith("#"):
            hash_at = line.index("#")
            line = f"{line[:hash_at]}#{_ZWSP}{line[hash_at + 1 :]}"
            stripped = line.lstrip()
        if _THEMATIC_BREAK.fullmatch(stripped):
            line = stripped[0] + _ZWSP + stripped[1:]
        lines.append(line)
    protected = "\n".join(lines)
    protected = re.sub(r"(?<!\S)---(?!\S)", f"-{_ZWSP}--", protected)
    for field in PASS_A_FIELDS:
        protected = protected.replace(f"{field}:", f"{field}{_ZWSP}:")
    return protected


def _render_figure(figure: str) -> str:
    if not figure:
        return ""
    return f'<div class="pg-figure">{figure}</div>'


def _render_rubric() -> str:
    return "\n".join(f"{field}:" for field in PASS_A_FIELDS)


def _render_header() -> str:
    lines = ["# Pass A", ""]
    for index, instruction in enumerate(PASS_A_INSTRUCTIONS, start=1):
        lines.append(f"{index}. {instruction}")
    lines.extend(["", "---", ""])
    return "\n".join(lines)


def render_pass_a_block(item: RulerItem) -> str:
    """Render one blind Pass A judgment block for a ruler item."""
    if not isinstance(item, RulerItem):
        raise TypeError("render_pass_a_block expects a RulerItem")
    review_id = _require_review_id(item)
    content = item.pass_a_content()
    stem = _protect_prose(str(content["stem"]))
    choices = _as_choices(content["choices"])
    figure = str(content["figure"])

    lines = [f"### {review_id}", "", "**Stem.**", "", stem, ""]
    for label, choice in zip(_CHOICE_LABELS, choices, strict=True):
        lines.append(f"**{label})** {_protect_prose(choice)}")
    lines.append("")
    if figure_markup := _render_figure(figure):
        lines.extend([figure_markup, ""])
    lines.extend([_render_rubric(), "", "---", ""])
    return "\n".join(lines)


def _as_choices(value: object) -> list[str]:
    if type(value) is not list or len(value) != 5:
        raise ValueError("Pass A choices must contain exactly five strings")
    return [str(choice) for choice in value]


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
