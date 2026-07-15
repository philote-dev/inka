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

import hashlib
import html
import json
import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import cast

from .calibration_ruler import (
    RulerItem,
    RulerManifest,
    pass_a_hash,
    validate_manifest,
)

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
_ITEM_HEADING = re.compile(r"^### ([^\r\n]+)$", re.MULTILINE)
_FIELD_LINE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*):(?: |$)", re.ASCII)
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

ANSWERS = frozenset({"A", "B", "C", "D", "E", "UNSURE"})
PASS_FAIL = frozenset({"PASS", "FAIL", "UNSURE"})
DISTRACTOR = frozenset({"VALID", "INVALID", "CORRECT_ANSWER", "UNSURE"})
FIGURE = frozenset(
    {"MATCHES", "CONTRADICTS", "UNNECESSARY", "MISSING", "N_A", "UNSURE"}
)
DIFFICULTY = frozenset({"1", "2", "3", "4", "5", "UNSURE"})
OVERALL = frozenset({"KEEP", "DROP", "UNSURE"})

MAX_NOTES_LENGTH = 2_000
ANSWER_REPEAT_MIN_MATCHES = 11
CATEGORICAL_REPEAT_MIN_AGREEMENT = 0.90
PASS_A_CATEGORICAL_FIELDS = (
    "stem_clear",
    "distractor_A",
    "distractor_B",
    "distractor_C",
    "distractor_D",
    "distractor_E",
    "figure",
    "difficulty",
    "overall",
)

_FIELD_VALUES = {
    "your_answer": ANSWERS,
    "stem_clear": PASS_FAIL,
    "distractor_A": DISTRACTOR,
    "distractor_B": DISTRACTOR,
    "distractor_C": DISTRACTOR,
    "distractor_D": DISTRACTOR,
    "distractor_E": DISTRACTOR,
    "figure": FIGURE,
    "difficulty": DIFFICULTY,
    "overall": OVERALL,
}
_HIDDEN_METADATA_FIELDS = frozenset(
    {
        "correct",
        "key",
        "source_ref",
        "source_excerpt",
        "solution_decomposition",
        "decomposition",
        "model",
        "model_family",
        "model_output",
        "origin",
        "provenance",
        "trace",
        "verifier",
        "recommendation",
        "stratum",
        "split",
        "repeat_of",
        "content_hash",
        "pass_a_hash",
        "pass_b_hash",
        "confidence",
    }
)


class PassAParseError(ValueError):
    """Base class for actionable Pass A import errors."""


class ReviewerEditError(PassAParseError):
    """A rubric value or note needs correction by the reviewer."""


class RendererSchemaError(PassAParseError):
    """The sheet, manifest, or asset contract no longer matches the renderer."""


def _reviewer_error(message: str) -> ReviewerEditError:
    return ReviewerEditError(f"reviewer edit required: {message}")


def _schema_error(message: str) -> RendererSchemaError:
    return RendererSchemaError(f"renderer/schema mismatch: {message}")


def _validate_note(note: str) -> None:
    """Allow bounded ordinary Unicode without structural or invisible controls."""
    if type(note) is not str:
        raise _reviewer_error("notes must be text")
    if len(note) > MAX_NOTES_LENGTH:
        raise _reviewer_error(
            f"notes must contain at most {MAX_NOTES_LENGTH} characters"
        )
    if len(note.splitlines()) > 1 or any(
        unicodedata.category(character) in {"Zl", "Zp"}
        or unicodedata.category(character).startswith("C")
        for character in note
    ):
        raise _reviewer_error(
            "notes must be one line of ordinary Unicode; controls, format "
            "characters (including zero-width spaces), surrogates, private-use "
            "or unassigned characters, and line or paragraph separators are "
            "not allowed"
        )
    try:
        json.dumps(note, ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (UnicodeEncodeError, ValueError) as error:
        raise _reviewer_error("notes must be valid JSON-safe Unicode text") from error


def _validate_label_value(field: str, value: str) -> None:
    if type(value) is not str:
        raise _reviewer_error(f"{field} must be text")
    allowed = _FIELD_VALUES[field]
    if value not in allowed:
        options = ", ".join(sorted(allowed))
        if not value:
            raise _reviewer_error(f"incomplete field {field}; choose one of: {options}")
        raise _reviewer_error(
            f"unknown value {value!r} for {field}; choose one of: {options}"
        )


@dataclass(frozen=True, slots=True)
class PassALabel:
    """One immutable, fixed-shape, JSON-safe Pass A judgment.

    Notes are bounded to one line of ordinary Unicode. Unicode category C
    characters and line or paragraph separators are rejected.
    """

    your_answer: str
    stem_clear: str
    distractor_A: str
    distractor_B: str
    distractor_C: str
    distractor_D: str
    distractor_E: str
    figure: str
    difficulty: str
    overall: str
    notes: str

    def __post_init__(self) -> None:
        for field in _FIELD_VALUES:
            _validate_label_value(field, cast(str, getattr(self, field)))
        _validate_note(self.notes)

    def to_dict(self) -> dict[str, str]:
        """Return only the fixed Pass A fields as a JSON object."""
        return {
            "your_answer": self.your_answer,
            "stem_clear": self.stem_clear,
            "distractor_A": self.distractor_A,
            "distractor_B": self.distractor_B,
            "distractor_C": self.distractor_C,
            "distractor_D": self.distractor_D,
            "distractor_E": self.distractor_E,
            "figure": self.figure,
            "difficulty": self.difficulty,
            "overall": self.overall,
            "notes": self.notes,
        }


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


def _validated_manifest_items(manifest: RulerManifest) -> tuple[RulerItem, ...]:
    if not isinstance(manifest, RulerManifest):
        raise _schema_error("Pass A import requires a private RulerManifest")
    try:
        validate_manifest(manifest)
    except (TypeError, ValueError) as error:
        raise _schema_error(f"private ruler manifest is invalid: {error}") from error
    return manifest.items


def _as_documents(value: str | Sequence[str]) -> tuple[str, ...]:
    if type(value) is str:
        return (value,)
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise _schema_error("Pass A documents must be text or a sequence of text")
    documents = tuple(value)
    if any(type(document) is not str for document in documents):
        raise _schema_error("every Pass A document must be plain text")
    return documents


def _expected_document_count(items: Sequence[RulerItem]) -> int:
    return (len(items) + BLOCK_CAPACITY - 1) // BLOCK_CAPACITY


def _document_review_ids(documents: Sequence[str]) -> list[str]:
    return [
        match.group(1)
        for document in documents
        for match in _ITEM_HEADING.finditer(document)
    ]


def _validate_document_ids(
    documents: Sequence[str],
    items: Sequence[RulerItem],
) -> None:
    expected = [_require_review_id(item) for item in items]
    actual = _document_review_ids(documents)
    counts: dict[str, int] = {}
    for review_id in actual:
        counts[review_id] = counts.get(review_id, 0) + 1
    if duplicates := sorted(
        review_id for review_id, count in counts.items() if count > 1
    ):
        raise _schema_error("duplicate review ID(s): " + ", ".join(duplicates))
    expected_set = set(expected)
    if extras := sorted(set(actual) - expected_set):
        raise _schema_error("unexpected review ID(s): " + ", ".join(extras))
    if missing := [review_id for review_id in expected if review_id not in counts]:
        raise _schema_error("missing review ID(s): " + ", ".join(missing))


def _field_names(documents: Sequence[str]) -> list[str]:
    names: list[str] = []
    for document in documents:
        for line in document.split("\n"):
            if match := _FIELD_LINE.match(line):
                names.append(match.group(1))
    return names


def _validate_document_fields(
    documents: Sequence[str],
    item_count: int,
) -> None:
    names = _field_names(documents)
    for name in names:
        if name in _HIDDEN_METADATA_FIELDS:
            raise _schema_error(f"hidden metadata field injected into Pass A: {name}")
        if name not in PASS_A_FIELDS:
            raise _schema_error(f"unexpected field injection in Pass A: {name}")
    for field in PASS_A_FIELDS:
        count = names.count(field)
        if count < item_count:
            raise _schema_error(
                f"incomplete Pass A: field {field} appears {count} times; "
                f"expected {item_count}"
            )
        if count > item_count:
            raise _schema_error(
                f"duplicate field {field}: appears {count} times; expected {item_count}"
            )


def _validate_document_separators(
    documents: Sequence[str],
    item_count: int,
) -> None:
    actual = sum(
        1 for document in documents for line in document.split("\n") if line == "---"
    )
    expected = item_count + len(documents)
    if actual != expected:
        raise _schema_error(
            f"separator count changed: found {actual}; expected {expected}"
        )


def _validate_document_headers(documents: Sequence[str]) -> None:
    header = _render_header()
    for index, document in enumerate(documents, start=1):
        if not document.startswith(header):
            raise _schema_error(
                f"document {index} header or allowed-value legend changed"
            )


def _preflight_documents(
    documents: Sequence[str],
    items: Sequence[RulerItem],
) -> None:
    expected_count = _expected_document_count(items)
    if len(documents) != expected_count:
        raise _schema_error(
            f"Pass A document count changed: found {len(documents)}; "
            f"expected {expected_count}"
        )
    _validate_document_ids(documents, items)
    _validate_document_fields(documents, len(items))
    _validate_document_separators(documents, len(items))
    _validate_document_headers(documents)


def _expected_asset_items(
    items: Sequence[RulerItem],
) -> dict[str, RulerItem]:
    expected: dict[str, RulerItem] = {}
    for item in items:
        if not item.figure:
            continue
        path = _figure_asset_path(_require_review_id(item))
        if path in expected:
            raise _schema_error(f"figure asset path collision: {path}")
        expected[path] = item
    return expected


def _copy_asset_mapping(assets: Mapping[str, bytes]) -> dict[str, bytes]:
    if not isinstance(assets, Mapping):
        raise _schema_error("figure assets must be a pure mapping of paths to bytes")
    copied: dict[str, bytes] = {}
    for path, raw in assets.items():
        if type(path) is not str:
            raise _schema_error("asset mapping keys must be exact relative strings")
        if path in copied:
            raise _schema_error(f"figure asset path collision: {path}")
        if type(raw) is not bytes:
            raise _schema_error(f"asset {path} must contain exact raw bytes")
        copied[path] = raw
    return copied


def _validate_asset_sets(
    expected: Mapping[str, RulerItem],
    actual: Mapping[str, bytes],
) -> None:
    if missing := sorted(set(expected) - set(actual)):
        raise _schema_error("missing asset(s): " + ", ".join(missing))
    if extras := sorted(set(actual) - set(expected)):
        raise _schema_error("extra asset(s): " + ", ".join(extras))


def _decode_asset(path: str, raw: bytes, item: RulerItem) -> str:
    try:
        decoded = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as error:
        raise _schema_error(f"asset {path} is not strict UTF-8") from error
    expected = item.figure.encode("utf-8")
    if raw != expected:
        actual_digest = hashlib.sha256(raw).hexdigest()
        expected_digest = hashlib.sha256(expected).hexdigest()
        raise _schema_error(
            f"asset bytes/hash mismatch for {path}: "
            f"found {actual_digest}; expected {expected_digest}"
        )
    return decoded


def _validated_figure_text(
    items: Sequence[RulerItem],
    assets: Mapping[str, bytes],
) -> dict[str, str]:
    expected = _expected_asset_items(items)
    actual = _copy_asset_mapping(assets)
    _validate_asset_sets(expected, actual)
    figures: dict[str, str] = {}
    for path, item in expected.items():
        review_id = _require_review_id(item)
        figures[review_id] = _decode_asset(path, actual[path], item)
    return figures


@dataclass
class _LineCursor:
    lines: list[str]
    document_number: int
    index: int = 0

    def peek(self, *, context: str) -> str:
        if self.index >= len(self.lines):
            raise _schema_error(
                f"document {self.document_number} is truncated while reading {context}"
            )
        return self.lines[self.index]

    def take(self, *, context: str) -> str:
        line = self.peek(context=context)
        self.index += 1
        return line

    def expect(self, expected: str, *, context: str) -> None:
        actual = self.take(context=context)
        if actual != expected:
            raise _schema_error(
                f"{context} changed: found {actual!r}; expected {expected!r}"
            )


def _visible_text(
    protected: str,
    expected: str,
    *,
    review_id: str,
    field: str,
) -> str:
    visible = unprotect_markdown_text(protected)
    if protect_markdown_text(visible) != protected:
        raise _schema_error(f"protection tampering in {review_id} {field}")
    if visible != expected:
        raise _schema_error(f"immutable content changed for {review_id} {field}")
    return visible


def _parse_stem(
    cursor: _LineCursor,
    item: RulerItem,
    review_id: str,
) -> str:
    cursor.expect("**Stem.**", context=f"{review_id} stem label")
    cursor.expect("", context=f"{review_id} blank line before stem")
    protected = cursor.take(context=f"{review_id} stem")
    stem = _visible_text(
        protected,
        item.stem,
        review_id=review_id,
        field="stem",
    )
    cursor.expect("", context=f"{review_id} blank line after stem")
    return stem


def _parse_choice(
    cursor: _LineCursor,
    item: RulerItem,
    review_id: str,
    index: int,
) -> str:
    label = _CHOICE_LABELS[index]
    line = cursor.take(context=f"{review_id} choice {label}")
    prefix = f"**{label})** "
    if not line.startswith(prefix):
        raise _schema_error(
            f"{review_id} choice {label} renderer grammar changed: {line!r}"
        )
    return _visible_text(
        line[len(prefix) :],
        item.choices[index],
        review_id=review_id,
        field=f"choice {label}",
    )


def _parse_figure_reference(
    cursor: _LineCursor,
    item: RulerItem,
    review_id: str,
    figure_text: Mapping[str, str],
) -> str:
    if not item.figure:
        next_line = cursor.peek(context=f"{review_id} figure or rubric")
        if next_line.startswith("![Figure]("):
            raise _schema_error(f"changed figure reference for {review_id}")
        return ""
    expected = _render_figure(review_id, item.figure)
    actual = cursor.take(context=f"{review_id} figure reference")
    if actual != expected:
        raise _schema_error(
            f"changed figure reference for {review_id}: "
            f"found {actual!r}; expected {expected!r}"
        )
    cursor.expect("", context=f"{review_id} blank line after figure")
    return figure_text[review_id]


def _parse_field_line(
    cursor: _LineCursor,
    review_id: str,
    field: str,
) -> str:
    line = cursor.take(context=f"{review_id} field {field}")
    prefix = f"{field}:"
    if line == prefix:
        value = ""
    elif line.startswith(prefix + " "):
        value = line[len(prefix) + 1 :]
    else:
        raise _schema_error(f"{review_id} expected exact field {field}, found {line!r}")
    if field == "notes":
        _validate_note(value)
    else:
        _validate_label_value(field, value)
    return value


def _label_from_values(values: Mapping[str, str]) -> PassALabel:
    return PassALabel(
        your_answer=values["your_answer"],
        stem_clear=values["stem_clear"],
        distractor_A=values["distractor_A"],
        distractor_B=values["distractor_B"],
        distractor_C=values["distractor_C"],
        distractor_D=values["distractor_D"],
        distractor_E=values["distractor_E"],
        figure=values["figure"],
        difficulty=values["difficulty"],
        overall=values["overall"],
        notes=values["notes"],
    )


def _parse_item(
    cursor: _LineCursor,
    item: RulerItem,
    figure_text: Mapping[str, str],
) -> tuple[str, PassALabel]:
    review_id = _require_review_id(item)
    cursor.expect(f"### {review_id}", context=f"{review_id} heading")
    cursor.expect("", context=f"{review_id} blank line after heading")
    stem = _parse_stem(cursor, item, review_id)
    choices = [
        _parse_choice(cursor, item, review_id, index)
        for index in range(len(_CHOICE_LABELS))
    ]
    cursor.expect("", context=f"{review_id} blank line after choices")
    figure = _parse_figure_reference(cursor, item, review_id, figure_text)
    visible = {"stem": stem, "choices": choices, "figure": figure}
    if pass_a_hash(visible) != item.pass_a_hash:
        raise _schema_error(
            f"immutable content hash mismatch for review ID {review_id}"
        )
    values = {
        field: _parse_field_line(cursor, review_id, field) for field in PASS_A_FIELDS
    }
    cursor.expect("", context=f"{review_id} blank line after rubric")
    cursor.expect("---", context=f"{review_id} separator")
    return review_id, _label_from_values(values)


def _parse_document(
    document: str,
    items: Sequence[RulerItem],
    figure_text: Mapping[str, str],
    document_number: int,
) -> dict[str, PassALabel]:
    body = document[len(_render_header()) :]
    cursor = _LineCursor(body.split("\n"), document_number)
    labels: dict[str, PassALabel] = {}
    for item in items:
        review_id, label = _parse_item(cursor, item, figure_text)
        labels[review_id] = label
    if cursor.lines[cursor.index :] != [""]:
        raise _schema_error(
            f"document {document_number} contains extra or truncated block content"
        )
    return labels


def _validate_complete_items(
    labels: Mapping[str, PassALabel],
    items: Sequence[RulerItem],
) -> None:
    if not isinstance(labels, Mapping):
        raise _reviewer_error("Pass A labels must be a review-ID mapping")
    expected = [_require_review_id(item) for item in items]
    actual = list(labels)
    if any(type(review_id) is not str for review_id in actual):
        raise _schema_error("Pass A label mapping keys must be review ID strings")
    if missing := [review_id for review_id in expected if review_id not in labels]:
        raise _reviewer_error(
            "incomplete Pass A labels; missing review ID(s): " + ", ".join(missing)
        )
    if extras := sorted(set(actual) - set(expected)):
        raise _schema_error("unexpected labeled review ID(s): " + ", ".join(extras))
    for review_id in expected:
        if not isinstance(labels[review_id], PassALabel):
            raise _reviewer_error(
                f"review ID {review_id} does not contain a PassALabel"
            )


def parse_pass_a(
    documents: str | Sequence[str],
    *,
    manifest: RulerManifest,
    assets: Mapping[str, bytes],
) -> dict[str, PassALabel]:
    """Parse only exact Pass A renderer output with injected private inputs."""
    items = _validated_manifest_items(manifest)
    parsed_documents = _as_documents(documents)
    _preflight_documents(parsed_documents, items)
    figure_text = _validated_figure_text(items, assets)
    labels: dict[str, PassALabel] = {}
    for document_number, start in enumerate(
        range(0, len(items), BLOCK_CAPACITY),
        start=1,
    ):
        chunk = items[start : start + BLOCK_CAPACITY]
        labels.update(
            _parse_document(
                parsed_documents[document_number - 1],
                chunk,
                figure_text,
                document_number,
            )
        )
    _validate_complete_items(labels, items)
    return labels


def validate_pass_a_complete(
    labels: Mapping[str, PassALabel],
    *,
    manifest: RulerManifest,
) -> None:
    """Require one immutable Pass A label for every private-manifest item."""
    items = _validated_manifest_items(manifest)
    _validate_complete_items(labels, items)


def _repeat_pairs(
    items: Sequence[RulerItem],
) -> list[tuple[RulerItem, RulerItem]]:
    originals = {
        _require_review_id(item): item for item in items if item.repeat_of is None
    }
    pairs: list[tuple[RulerItem, RulerItem]] = []
    for repeat in items:
        if repeat.repeat_of is None:
            continue
        origin = originals.get(repeat.repeat_of)
        if origin is None:
            raise _schema_error(
                f"repeat {repeat.review_id} references unknown original "
                f"{repeat.repeat_of}"
            )
        if (
            repeat.content_hash != origin.content_hash
            or repeat.pass_a_content() != origin.pass_a_content()
        ):
            raise _schema_error(
                f"repeat {repeat.review_id} content does not match its original"
            )
        pairs.append((origin, repeat))
    return pairs


def _agreement_metric(
    pairs: Sequence[tuple[PassALabel, PassALabel]],
    field: str,
) -> dict[str, object]:
    total = len(pairs)
    matches = sum(
        1
        for original, repeat in pairs
        if getattr(original, field) == getattr(repeat, field)
    )
    return {
        "matches": matches,
        "total": total,
        "raw_agreement": matches / total if total else 0.0,
    }


def _split_support(items: Sequence[RulerItem]) -> dict[str, int]:
    support = {"calibration": 0, "validation": 0, "total": 0}
    for item in items:
        if item.repeat_of is not None:
            continue
        if item.split not in {"calibration", "validation"}:
            raise _schema_error(
                f"primary review ID {item.review_id} has invalid split {item.split!r}"
            )
        support[item.split] += 1
        support["total"] += 1
    return support


def repeat_consistency(
    labels: Mapping[str, PassALabel],
    manifest: RulerManifest,
) -> dict[str, object]:
    """Report private-pair answer and per-property raw repeat agreement."""
    items = _validated_manifest_items(manifest)
    _validate_complete_items(labels, items)
    item_pairs = _repeat_pairs(items)
    label_pairs = [
        (
            labels[_require_review_id(original)],
            labels[_require_review_id(repeat)],
        )
        for original, repeat in item_pairs
    ]
    return {
        "repeat_count": len(item_pairs),
        "split_support": _split_support(items),
        "exact_answer": _agreement_metric(label_pairs, "your_answer"),
        "categorical_fields": {
            field: _agreement_metric(label_pairs, field)
            for field in PASS_A_CATEGORICAL_FIELDS
        },
    }


def _gate_metric(value: object, *, name: str) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"consistency report {name} must be an object")
    matches = value.get("matches")
    total = value.get("total")
    raw_agreement = value.get("raw_agreement")
    if (
        type(matches) is not int
        or type(total) is not int
        or type(raw_agreement) is not float
        or total <= 0
        or not 0 <= matches <= total
        or raw_agreement != matches / total
    ):
        raise ValueError(f"consistency report {name} has an invalid agreement metric")
    return {
        "matches": matches,
        "total": total,
        "raw_agreement": raw_agreement,
    }


def consistency_gate(consistency: Mapping[str, object]) -> dict[str, object]:
    """Apply fixed repeat floors without changing or adjudicating any label."""
    if not isinstance(consistency, Mapping):
        raise ValueError("consistency gate requires a repeat-consistency report")
    exact = _gate_metric(consistency.get("exact_answer"), name="exact_answer")
    categorical = consistency.get("categorical_fields")
    if not isinstance(categorical, Mapping) or set(categorical) != set(
        PASS_A_CATEGORICAL_FIELDS
    ):
        raise ValueError("consistency report categorical field set is invalid")

    answer_passed = (
        exact["total"] == 12
        and cast(int, exact["matches"]) >= ANSWER_REPEAT_MIN_MATCHES
    )
    exact_result = {
        **exact,
        "required_matches": ANSWER_REPEAT_MIN_MATCHES,
        "passed": answer_passed,
    }
    failed = [] if answer_passed else ["your_answer"]
    field_results: dict[str, dict[str, object]] = {}
    for field in PASS_A_CATEGORICAL_FIELDS:
        metric = _gate_metric(categorical[field], name=field)
        passed = (
            metric["total"] == 12
            and cast(float, metric["raw_agreement"]) >= CATEGORICAL_REPEAT_MIN_AGREEMENT
        )
        field_results[field] = {
            **metric,
            "required_raw_agreement": CATEGORICAL_REPEAT_MIN_AGREEMENT,
            "passed": passed,
        }
        if not passed:
            failed.append(field)
    passed = not failed
    return {
        "status": "PASS" if passed else "ADJUDICATION_REQUIRED",
        "passed": passed,
        "exact_answer": exact_result,
        "categorical_fields": field_results,
        "failed_checks": failed,
    }
