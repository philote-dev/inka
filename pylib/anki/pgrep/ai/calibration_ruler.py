# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Canonical, blind-safe problem records for the human calibration ruler.

Visible prose uses Unicode NFC and collapsed whitespace. Decomposition and
grounding-provenance strings use the same normalization recursively. Figure
markup is validated but otherwise preserved.
"""

from __future__ import annotations

import hashlib
import json
import math
import random
import re
import unicodedata
from collections.abc import Callable, Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass, field, replace
from types import MappingProxyType
from typing import cast
from xml.etree import ElementTree

BLUEPRINT_CATEGORIES = frozenset(
    {
        "mechanics",
        "electromagnetism",
        "quantum",
        "thermodynamics",
        "atomic",
        "optics_waves",
        "special_relativity",
        "lab",
        "specialized",
    }
)

_VALID_KEYS = frozenset("ABCDE")
_AUTHORED_KINDS = frozenset({"conceptual", "computational"})
_VALID_KINDS = _AUTHORED_KINDS | frozenset({"unspecified"})
_VALID_STRATA = frozenset({"trusted", "failure", "shadow"})
_VALID_SPLITS = frozenset({"calibration", "validation"})

# The shadow foundry generates candidates from exactly these frontier families.
# An absent family fails ruler construction before any sampling.
SHADOW_MODEL_FAMILIES = frozenset({"sol", "opus", "grok"})

# Locked ruler geometry: 40 items per stratum, an 80/40 calibration/validation
# split of the 120 primaries, and 12 hidden repeats excluded from split support.
PRIMARY_PER_STRATUM = 40
VALIDATION_SIZE = 40
CALIBRATION_SIZE = 80
REPEAT_COUNT = 12

# Optional provenance disposition used only when fixtures supply it. Human KEEP
# and DROP labels are never required at construction time.
_HUMAN_LABELS = frozenset({"positive", "negative"})
_HUMAN_LABEL_KEY = "human_label"
_MODEL_FAMILY_KEY = "model_family"

# Broad dataset tokens apply only to identifier fields. Boundaries are
# Unicode-aware while underscores remain separators, so "marigold" stays safe.
_PRIVATE_ID_MARKER = re.compile(
    r"(?i)(?<![^\W_])(?:"
    r"gold|ets|gr9677|gr1777"
    r"|held[\s_./\\-]*out"
    r"|tier[\s_./\\-]*3"
    r")(?![^\W_])"
)
# Path-shaped markers apply recursively to all strings. Bare physics prose such
# as "gold foil" does not match any alternative.
_PRIVATE_PATH_MARKER = re.compile(
    r"(?ix)(?<![^\W_])(?:"
    r"content[\\/]+(?:gold|ets|held[\s_.\\/-]*out|tier[\s_.\\/-]*3)"
    r"(?=$|[\\/._:-])"
    r"|gold(?:[\s_.-]*(?:set|items?))?(?=[\\/])"
    r"|gold[\s_.-]+(?:set|items?)(?=$|[\\/._:-])"
    r"|held[\s_.\\/-]*out(?=[\\/])"
    r"|ets(?:[\s_.-]*private)?(?=[\\/])"
    r"|ets[\s_.-]+private(?=$|[\\/._:-])"
    r"|tier[\s_.\\/-]*3(?:[\s_.-]*private)?(?=[\\/])"
    r"|tier[\s_.\\/-]*3[\s_.-]+private(?=$|[\\/._:-])"
    r"|(?:gold|ets|held[\s_.\\/-]*out|tier[\s_.\\/-]*3)"
    r"(?=[._-](?:jsonl?|ya?ml|csv|md|txt|pdf)\b)"
    r"|gr9677|gr1777"
    r")"
)

_FIGURE_BLOCK = re.compile(
    r"""<div\s+class\s*=\s*(?P<quote>["'])pg-figure(?P=quote)\s*>"""
    r"(?P<body>[\s\S]*?)</div>",
    re.IGNORECASE,
)
_FIGURE_OPEN = re.compile(
    r"""<div\s+class\s*=\s*["']pg-figure["']\s*>""",
    re.IGNORECASE,
)
_RAW_SVG = re.compile(r"<svg\b", re.IGNORECASE)
_FORBIDDEN_XML = re.compile(r"<!\s*(?:DOCTYPE|ENTITY)\b|<\?", re.IGNORECASE)
_URL_FUNCTION = re.compile(
    r"""url\(\s*["']?([^)"'\s]+)["']?\s*\)""",
    re.IGNORECASE,
)
_SAFE_CSS_URL = re.compile(r"(?i)url\(#[A-Za-z_][A-Za-z0-9_-]*\)")
_CSS_URL_WORD = re.compile(r"(?i)\burl\b")
_EXTERNAL_URL = re.compile(
    r"(?i)(?:https?|ftp|file|data|javascript|vbscript)\s*:|(?:^|[\s('\"=])//"
)

_SVG_NAMESPACE = "http://www.w3.org/2000/svg"
_XLINK_NAMESPACE = "http://www.w3.org/1999/xlink"
_XML_NAMESPACE = "http://www.w3.org/XML/1998/namespace"
_SVG_TAGS = frozenset(
    {
        "svg",
        "g",
        "defs",
        "symbol",
        "use",
        "marker",
        "path",
        "line",
        "polyline",
        "polygon",
        "rect",
        "circle",
        "ellipse",
        "text",
        "tspan",
        "title",
        "desc",
        "style",
        "clippath",
        "mask",
        "pattern",
        "lineargradient",
        "radialgradient",
        "stop",
        "filter",
        "fegaussianblur",
        "feoffset",
        "femerge",
        "femergenode",
        "fecolormatrix",
        "feblend",
    }
)
_CONTENT_FIELDS = frozenset(
    {
        "id",
        "topic",
        "blueprint_category",
        "kind",
        "problem_kind",
        "difficulty",
        "stem",
        "choices",
        "correct",
        "key",
        "figure",
        "source_ref",
        "source_excerpt",
        "solution_decomposition",
        "decomposition",
        "provenance",
        "computational",
    }
)
_ASSIGNMENT_FIELDS = frozenset({"review_id", "stratum", "split", "repeat_of"})
_HASH_FIELDS = ("content_hash", "pass_a_hash", "pass_b_hash")
_SERIALIZATION_FIELDS = (
    _CONTENT_FIELDS
    | _ASSIGNMENT_FIELDS
    | frozenset(_HASH_FIELDS)
    | frozenset({"metadata"})
)


def _child_path(path: str, key: object) -> str:
    return f"{path}.{key}" if type(key) is str else f"{path}[{key!r}]"


def _private_marker_error(
    value: str,
    path: str,
    *,
    identifier: bool = False,
) -> ValueError | None:
    marker = _PRIVATE_PATH_MARKER.search(value)
    if marker is None and identifier:
        marker = _PRIVATE_ID_MARKER.search(value)
    if marker is None:
        return None
    return ValueError(f"{path}: private marker {marker.group(0)!r} is not allowed")


def _is_identifier_key(key: str) -> bool:
    lowered = key.lower()
    return (
        lowered in {"id", "ids", "repeat_of"}
        or lowered.endswith("_id")
        or lowered.endswith("_ids")
    )


def _is_path_key(key: str) -> bool:
    lowered = key.lower()
    return any(
        token in lowered
        for token in ("path", "file", "dataset", "heldout", "held_out", "tier3")
    )


def _validate_private_markers(
    value: object,
    path: str = "$",
    *,
    identifier: bool = False,
) -> None:
    if type(value) is str:
        if error := _private_marker_error(value, path, identifier=identifier):
            raise error
        return
    if type(value) is list:
        for index, nested in enumerate(cast(list[object], value)):
            _validate_private_markers(
                nested,
                f"{path}[{index}]",
                identifier=identifier,
            )
        return
    if type(value) is not dict:
        return
    for key, nested in cast(dict[str, object], value).items():
        child = _child_path(path, key)
        if _is_path_key(key) and (
            error := _private_marker_error(key, f"{child} (key)", identifier=True)
        ):
            raise error
        _validate_private_markers(
            nested,
            child,
            identifier=identifier or _is_identifier_key(key) or _is_path_key(key),
        )


def _validate_json(
    value: object,
    path: str = "$",
    active: set[int] | None = None,
) -> None:
    if value is None or type(value) in (bool, int):
        return
    if type(value) is float:
        if not math.isfinite(value):
            raise ValueError(f"{path}: non-finite numbers are not allowed")
        return
    if type(value) is str:
        return
    if type(value) is list:
        _validate_json_array(cast(list[object], value), path, active)
        return
    if type(value) is dict:
        _validate_json_object(cast(dict[object, object], value), path, active)
        return
    raise ValueError(
        f"{path}: value of type {type(value).__name__} is not JSON-compatible"
    )


def _enter_container(value: object, path: str, active: set[int] | None) -> set[int]:
    containers = active if active is not None else set()
    identity = id(value)
    if identity in containers:
        raise ValueError(f"{path}: cyclic JSON values are not allowed")
    containers.add(identity)
    return containers


def _validate_json_array(
    value: list[object],
    path: str,
    active: set[int] | None,
) -> None:
    containers = _enter_container(value, path, active)
    try:
        for index, nested in enumerate(value):
            _validate_json(nested, f"{path}[{index}]", containers)
    finally:
        containers.remove(id(value))


def _validate_json_object(
    value: dict[object, object],
    path: str,
    active: set[int] | None,
) -> None:
    containers = _enter_container(value, path, active)
    try:
        for key, nested in value.items():
            child = _child_path(path, key)
            if type(key) is not str:
                raise ValueError(f"{child} (key): JSON object keys must be strings")
            _validate_json(nested, child, containers)
    finally:
        containers.remove(id(value))


def _dict_input(value: object, *, name: str) -> dict[str, object]:
    if isinstance(value, RulerItem):
        return value._source_dict()
    if type(value) is not dict:
        raise ValueError(f"{name} must be a JSON object")
    return cast(dict[str, object], value)


def _raw_non_empty_string(value: object, *, name: str) -> str:
    if type(value) is not str or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _non_empty_string(value: object, *, name: str) -> str:
    return unicodedata.normalize(
        "NFC",
        _raw_non_empty_string(value, name=name),
    )


def _normalized_text(value: object, *, name: str) -> str:
    return " ".join(_non_empty_string(value, name=name).split())


def _canonicalize_json(value: object, *, collapse_text: bool) -> object:
    if type(value) is str:
        normalized_text = unicodedata.normalize("NFC", value)
        return " ".join(normalized_text.split()) if collapse_text else normalized_text
    if type(value) is list:
        return [
            _canonicalize_json(nested, collapse_text=collapse_text)
            for nested in cast(list[object], value)
        ]
    if type(value) is dict:
        normalized_object: dict[str, object] = {}
        for key, nested in cast(dict[str, object], value).items():
            normalized_key = unicodedata.normalize("NFC", key)
            if normalized_key in normalized_object:
                raise ValueError(
                    f"JSON object keys collide after NFC normalization: {key!r}"
                )
            normalized_object[normalized_key] = _canonicalize_json(
                nested,
                collapse_text=collapse_text,
            )
        return normalized_object
    return value


def _freeze_json(value: object) -> object:
    if type(value) is list:
        return tuple(_freeze_json(nested) for nested in cast(list[object], value))
    if type(value) is dict:
        mapping = cast(dict[str, object], value)
        return MappingProxyType(
            {key: _freeze_json(mapping[key]) for key in sorted(mapping)}
        )
    return value


def _thaw_json(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: _thaw_json(nested) for key, nested in value.items()}
    if type(value) is tuple:
        return [_thaw_json(nested) for nested in cast(tuple[object, ...], value)]
    return value


def _optional_string(value: object, *, name: str) -> str | None:
    if value is None:
        return None
    return _non_empty_string(value, name=name)


def _allowed_optional_string(
    value: object,
    *,
    name: str,
    allowed: frozenset[str],
) -> str | None:
    parsed = _optional_string(value, name=name)
    if parsed is not None and parsed not in allowed:
        options = ", ".join(sorted(allowed))
        raise ValueError(f"{name} must be exactly one of: {options}")
    return parsed


def _namespace_and_name(name: str) -> tuple[str, str]:
    if name.startswith("{") and "}" in name:
        namespace, local = name[1:].split("}", maxsplit=1)
        return namespace, local
    return "", name


def _validate_url_value(value: str, *, name: str) -> None:
    if "\\" in value:
        raise ValueError(f"figure {name} CSS escapes are not allowed")
    if _CSS_URL_WORD.search(_SAFE_CSS_URL.sub("", value)):
        raise ValueError(f"figure {name} URLs must be strict local fragment references")
    if _EXTERNAL_URL.search(value):
        raise ValueError(f"figure {name} contains an external URL")
    for match in _URL_FUNCTION.finditer(value):
        if not match.group(1).startswith("#"):
            raise ValueError(f"figure {name} contains an external URL")


def _validate_css(value: str, *, name: str) -> None:
    lowered = value.lower()
    if "@import" in lowered:
        raise ValueError(f"figure {name} imports are not allowed")
    if re.search(r"(?i)\bexpression\s*\(", value):
        raise ValueError(f"figure {name} expressions are not allowed")
    _validate_url_value(value, name=name)


def _validate_svg_attribute(raw_name: str, value: str) -> None:
    namespace, name = _namespace_and_name(raw_name)
    lowered = name.lower()
    if namespace not in ("", _XLINK_NAMESPACE, _XML_NAMESPACE):
        raise ValueError(f"figure attribute {name!r} uses an unsupported namespace")
    if lowered.startswith("on") and len(lowered) > 2:
        raise ValueError(f"figure event handler {name!r} is not allowed")
    if lowered in {"href", "src"} and not value.strip().startswith("#"):
        raise ValueError(f"figure {name!r} contains an external URL")
    _validate_css(
        value,
        name="style attribute" if lowered == "style" else f"attribute {name!r}",
    )


def _validate_svg_element(element: ElementTree.Element) -> None:
    if not isinstance(element.tag, str):
        return
    namespace, name = _namespace_and_name(element.tag)
    lowered = name.lower()
    if namespace not in ("", _SVG_NAMESPACE):
        raise ValueError(f"figure element {name!r} uses a non-SVG namespace")
    if lowered not in _SVG_TAGS:
        raise ValueError(f"figure element {name!r} is not allowed")
    for raw_name, value in element.attrib.items():
        _validate_svg_attribute(raw_name, value)
    if lowered == "style":
        _validate_css(element.text or "", name="style")


def _validated_figure(value: object, *, name: str = "figure") -> str:
    if type(value) is not str:
        raise ValueError(f"{name} must be a string")
    markup = value.strip()
    if not markup:
        return ""
    if match := _FIGURE_BLOCK.fullmatch(markup):
        markup = match.group("body").strip()
    if not markup:
        raise ValueError(f"{name} wrapper must contain SVG markup")
    if _FORBIDDEN_XML.search(markup):
        raise ValueError(f"{name} contains a forbidden XML declaration")
    try:
        root = ElementTree.fromstring(markup)
    except ElementTree.ParseError as error:
        raise ValueError(f"{name} must contain well-formed SVG: {error}") from error
    namespace, root_name = _namespace_and_name(cast(str, root.tag))
    if root_name.lower() != "svg" or namespace not in ("", _SVG_NAMESPACE):
        raise ValueError(f"{name} must contain exactly one SVG root")
    for element in root.iter():
        _validate_svg_element(element)
    return markup


def _stem_and_figure(stem_value: object, figure_value: object) -> tuple[str, str]:
    stem = _raw_non_empty_string(stem_value, name="stem")
    matches = list(_FIGURE_BLOCK.finditer(stem))
    open_count = len(_FIGURE_OPEN.findall(stem))
    if open_count != len(matches):
        raise ValueError("figure block in stem is malformed")
    if len(matches) > 1:
        raise ValueError("stem must contain at most one figure block")

    embedded = (
        _validated_figure(matches[0].group("body"), name="embedded figure")
        if matches
        else ""
    )
    without_figure = _FIGURE_BLOCK.sub(" ", stem)
    if _RAW_SVG.search(without_figure):
        raise ValueError("figure SVG in stem must use a pg-figure wrapper")
    visible_stem = _normalized_text(without_figure, name="stem")

    explicit = _validated_figure(figure_value)
    if embedded and explicit and embedded != explicit:
        raise ValueError("figure field and embedded figure conflict")
    return visible_stem, explicit or embedded


def _canonical_choices(value: object) -> list[str]:
    if type(value) is not list or len(value) != 5:
        raise ValueError("choices must contain exactly five non-empty strings")
    choices = cast(list[object], value)
    return [
        _normalized_text(choice, name=f"choices[{index}]")
        for index, choice in enumerate(choices)
    ]


def _canonical_pass_a(value: object) -> dict[str, object]:
    item = _dict_input(value, name="Pass A content")
    _validate_json(item)
    _validate_private_markers(item)
    figure_value = item["figure"] if "figure" in item else ""
    stem, figure = _stem_and_figure(item.get("stem"), figure_value)
    return {
        "stem": stem,
        "choices": _canonical_choices(item.get("choices")),
        "figure": figure,
    }


def _canonical_decomposition(item: dict[str, object]) -> list[object]:
    has_solution = "solution_decomposition" in item
    has_short = "decomposition" in item
    solution = item.get("solution_decomposition")
    short = item.get("decomposition")
    if has_solution and has_short and solution != short:
        raise ValueError(
            "solution_decomposition and decomposition fields must not conflict"
        )
    value = solution if has_solution else short
    if value is None and not has_solution and not has_short:
        value = []
    if type(value) is not list:
        raise ValueError("solution_decomposition must be a JSON array")
    return cast(
        list[object],
        _canonicalize_json(value, collapse_text=True),
    )


def _canonical_object_field(
    item: dict[str, object],
    name: str,
) -> dict[str, object] | None:
    value = item.get(name)
    if value is None:
        return None
    if type(value) is not dict:
        raise ValueError(f"{name} must be a JSON object or null")
    return cast(
        dict[str, object],
        _canonicalize_json(value, collapse_text=True),
    )


def _excerpt_from_item(
    item: dict[str, object],
    provenance: dict[str, object] | None,
) -> str | None:
    explicit = (
        _normalized_text(item["source_excerpt"], name="source_excerpt")
        if item.get("source_excerpt") is not None
        else None
    )
    quote: str | None = None
    if provenance is not None:
        raw_quote = provenance.get("quote_anchor")
        if type(raw_quote) is str and raw_quote.strip():
            quote = _normalized_text(raw_quote, name="provenance.quote_anchor")
        if raw_quote is not None and type(raw_quote) is not str:
            raise ValueError("provenance.quote_anchor must be a string or null")
    if explicit is not None and quote is not None and explicit != quote:
        raise ValueError(
            "source_excerpt must match provenance.quote_anchor after canonicalization"
        )
    return explicit or quote


def _validate_provenance_source_ref(
    item: dict[str, object],
    provenance: dict[str, object] | None,
) -> None:
    if provenance is None or "source_ref" not in provenance:
        return
    provenance_ref = _normalized_text(
        provenance["source_ref"],
        name="provenance.source_ref",
    )
    if "source_ref" not in item:
        raise ValueError("provenance.source_ref requires top-level source_ref")
    source_ref = _normalized_text(item["source_ref"], name="source_ref")
    if provenance_ref != source_ref:
        raise ValueError("provenance.source_ref must match top-level source_ref")


def _canonical_pass_b(
    value: object,
    *,
    require_excerpt: bool = True,
) -> dict[str, object]:
    item = _dict_input(value, name="Pass B content")
    _validate_json(item)
    _validate_private_markers(item)
    provenance = _canonical_object_field(item, "provenance")
    _validate_provenance_source_ref(item, provenance)
    excerpt = _excerpt_from_item(item, provenance)
    if require_excerpt and excerpt is None:
        raise ValueError("Pass B source excerpt is unavailable")
    return {
        "source_excerpt": excerpt,
        "solution_decomposition": _canonical_decomposition(item),
    }


def _correct_key(item: dict[str, object]) -> str:
    has_correct = "correct" in item
    has_key = "key" in item
    correct = item.get("correct")
    key = item.get("key")
    if has_correct and (type(correct) is not str or correct not in _VALID_KEYS):
        raise ValueError("correct must be exactly one of A, B, C, D, or E")
    if has_key and (type(key) is not str or key not in _VALID_KEYS):
        raise ValueError("key must be exactly one of A, B, C, D, or E")
    if has_correct and has_key and correct != key:
        raise ValueError("correct and key fields must not conflict")
    value = correct if has_correct else key
    if type(value) is not str:
        raise ValueError("correct must be exactly one of A, B, C, D, or E")
    return value


def _category(item: dict[str, object], topic: str) -> str:
    parts = topic.split("::")
    derived = parts[1] if len(parts) >= 2 and parts[0] == "topic" else None
    explicit = item["blueprint_category"] if "blueprint_category" in item else derived
    if type(explicit) is not str or explicit not in BLUEPRINT_CATEGORIES:
        raise ValueError("blueprint_category must be one of the nine locked slugs")
    if derived is not None and derived not in BLUEPRINT_CATEGORIES:
        raise ValueError("topic contains an invalid blueprint category")
    if derived is not None and explicit != derived:
        raise ValueError("blueprint_category must agree with topic")
    return explicit


def _has_computational_evidence(item: dict[str, object]) -> bool:
    value = item.get("computational")
    if type(value) is not dict:
        return False
    computational = cast(dict[str, object], value)
    expression = computational.get("expression")
    expected = computational.get("expected")
    tolerance = computational.get("tolerance")
    return (
        type(expression) is str
        and bool(expression.strip())
        and type(expected) in (int, float)
        and math.isfinite(float(cast(int | float, expected)))
        and type(tolerance) in (int, float)
        and math.isfinite(float(cast(int | float, tolerance)))
        and float(cast(int | float, tolerance)) >= 0
    )


def _kind(item: dict[str, object]) -> str:
    has_kind = "kind" in item
    has_problem_kind = "problem_kind" in item
    kind = item.get("kind")
    problem_kind = item.get("problem_kind")
    if has_problem_kind and (
        type(problem_kind) is not str or problem_kind not in _AUTHORED_KINDS
    ):
        raise ValueError("problem_kind must be exactly conceptual or computational")
    if kind == "problem":
        kind = (
            problem_kind
            if has_problem_kind
            else (
                "computational" if _has_computational_evidence(item) else "unspecified"
            )
        )
    elif not has_kind:
        kind = problem_kind if has_problem_kind else "unspecified"
    elif has_problem_kind and problem_kind != kind:
        raise ValueError("kind and problem_kind fields must not conflict")
    if type(kind) is not str or kind not in _VALID_KINDS:
        raise ValueError(
            "kind must be exactly conceptual, computational, or unspecified"
        )
    return kind


def _difficulty(value: object) -> float:
    if type(value) not in (int, float):
        raise ValueError("difficulty must be a number from 0 through 1")
    difficulty = float(cast(int | float, value))
    if not math.isfinite(difficulty):
        raise ValueError("difficulty must be finite")
    if not 0.0 <= difficulty <= 1.0:
        raise ValueError("difficulty must be between 0 and 1")
    return difficulty


def canonical_problem(value: object) -> dict[str, object]:
    """Return immutable content using NFC and deterministic prose whitespace."""
    item = _dict_input(value, name="source item")
    _validate_json(item)
    _validate_private_markers(item)
    _non_empty_string(item.get("id"), name="id")
    topic = _normalized_text(item.get("topic"), name="topic")
    pass_a = _canonical_pass_a(item)
    pass_b = _canonical_pass_b(item, require_excerpt=False)
    return {
        "topic": topic,
        "blueprint_category": _category(item, topic),
        "kind": _kind(item),
        "difficulty": _difficulty(item.get("difficulty")),
        **pass_a,
        "correct": _correct_key(item),
        "source_ref": _normalized_text(item.get("source_ref"), name="source_ref"),
        **pass_b,
        "provenance": _canonical_object_field(item, "provenance"),
        "computational": _canonical_object_field(item, "computational"),
    }


def validate_source_item(value: object) -> None:
    """Reject a malformed, unsafe, non-JSON, or private ruler source item."""
    canonical_problem(value)


def _hash_payload(value: object) -> str:
    _validate_json(value)
    try:
        raw = json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        encoded = raw.encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError) as error:
        raise ValueError(f"content is not canonical JSON: {error}") from error
    return hashlib.sha256(encoded).hexdigest()


def content_hash(value: object) -> str:
    """Hash all canonical content, excluding origin and review metadata."""
    return _hash_payload(canonical_problem(value))


def pass_a_hash(value: object) -> str:
    """Hash only the stem, choices, and safe figure visible in Pass A."""
    return _hash_payload(_canonical_pass_a(value))


def pass_b_hash(value: object) -> str:
    """Hash only the source excerpt and decomposition visible in Pass B."""
    return _hash_payload(_canonical_pass_b(value))


def _metadata(item: dict[str, object]) -> dict[str, object]:
    nested = item.get("metadata", {})
    if type(nested) is not dict:
        raise ValueError("metadata must be a JSON object")
    metadata = deepcopy(cast(dict[str, object], nested))
    if reserved := set(metadata) & _SERIALIZATION_FIELDS:
        names = ", ".join(sorted(reserved))
        raise ValueError(f"metadata contains reserved field(s): {names}")
    for name, value in item.items():
        if name not in _SERIALIZATION_FIELDS:
            if name in metadata and metadata[name] != value:
                raise ValueError(f"metadata field {name!r} conflicts with source item")
            metadata[name] = deepcopy(value)
    _validate_json(metadata, "$.metadata")
    _validate_private_markers(metadata, "$.metadata")
    return cast(
        dict[str, object],
        _canonicalize_json(metadata, collapse_text=False),
    )


def _provided_assignment(
    explicit: str | None,
    item: dict[str, object],
    name: str,
) -> object:
    return explicit if explicit is not None else item.get(name)


@dataclass(frozen=True)
class RulerItem:
    """A typed private-manifest item with narrow blind rendering projections."""

    id: str
    topic: str
    blueprint_category: str
    kind: str
    difficulty: float
    stem: str
    choices: tuple[str, ...]
    correct: str
    figure: str
    source_ref: str
    source_excerpt: str | None
    solution_decomposition: tuple[object, ...]
    provenance: Mapping[str, object] | None
    computational: Mapping[str, object] | None
    review_id: str | None = None
    stratum: str | None = None
    split: str | None = None
    repeat_of: str | None = None
    metadata: Mapping[str, object] = field(
        default_factory=lambda: MappingProxyType({}),
        repr=False,
    )

    def __post_init__(self) -> None:
        if type(self.choices) is not tuple:
            raise ValueError("choices must be a tuple on RulerItem")
        if type(self.solution_decomposition) is not tuple:
            raise ValueError("solution_decomposition must be a tuple on RulerItem")
        if not isinstance(self.metadata, Mapping):
            raise ValueError("metadata must be a JSON object")
        metadata = cast(dict[str, object], _thaw_json(self.metadata))
        _validate_json(metadata, "$.metadata")
        _validate_private_markers(metadata, "$.metadata")
        if reserved := set(metadata) & _SERIALIZATION_FIELDS:
            names = ", ".join(sorted(reserved))
            raise ValueError(f"metadata contains reserved field(s): {names}")
        canonical = canonical_problem(self._source_dict())
        object.__setattr__(
            self,
            "id",
            _non_empty_string(self.id, name="id"),
        )
        object.__setattr__(self, "topic", cast(str, canonical["topic"]))
        object.__setattr__(
            self,
            "blueprint_category",
            cast(str, canonical["blueprint_category"]),
        )
        object.__setattr__(self, "kind", cast(str, canonical["kind"]))
        object.__setattr__(self, "difficulty", cast(float, canonical["difficulty"]))
        object.__setattr__(self, "stem", cast(str, canonical["stem"]))
        object.__setattr__(
            self,
            "choices",
            tuple(cast(list[str], canonical["choices"])),
        )
        object.__setattr__(self, "correct", cast(str, canonical["correct"]))
        object.__setattr__(self, "figure", cast(str, canonical["figure"]))
        object.__setattr__(self, "source_ref", cast(str, canonical["source_ref"]))
        object.__setattr__(
            self,
            "source_excerpt",
            cast(str | None, canonical["source_excerpt"]),
        )
        object.__setattr__(
            self,
            "solution_decomposition",
            cast(
                tuple[object, ...],
                _freeze_json(canonical["solution_decomposition"]),
            ),
        )
        object.__setattr__(
            self,
            "provenance",
            cast(
                Mapping[str, object] | None,
                _freeze_json(canonical["provenance"]),
            ),
        )
        object.__setattr__(
            self,
            "computational",
            cast(
                Mapping[str, object] | None,
                _freeze_json(canonical["computational"]),
            ),
        )
        object.__setattr__(
            self,
            "metadata",
            cast(
                Mapping[str, object],
                _freeze_json(
                    _canonicalize_json(metadata, collapse_text=False),
                ),
            ),
        )
        self._validate_assignment()

    def _validate_assignment(self) -> None:
        review_id = _optional_string(self.review_id, name="review_id")
        _allowed_optional_string(
            self.stratum,
            name="stratum",
            allowed=_VALID_STRATA,
        )
        _allowed_optional_string(
            self.split,
            name="split",
            allowed=_VALID_SPLITS,
        )
        repeat_of = _optional_string(self.repeat_of, name="repeat_of")
        for name, value in (("review_id", review_id), ("repeat_of", repeat_of)):
            if value is not None:
                _validate_private_markers(
                    value,
                    f"$.{name}",
                    identifier=True,
                )

    @classmethod
    def from_source_item(
        cls,
        value: object,
        *,
        review_id: str | None = None,
        stratum: str | None = None,
        split: str | None = None,
        repeat_of: str | None = None,
    ) -> RulerItem:
        """Validate a bundle, rejection, or shadow dictionary and convert it."""
        item = _dict_input(value, name="source item")
        canonical = canonical_problem(item)
        ruler_item = cls(
            id=_non_empty_string(item.get("id"), name="id"),
            topic=cast(str, canonical["topic"]),
            blueprint_category=cast(str, canonical["blueprint_category"]),
            kind=cast(str, canonical["kind"]),
            difficulty=cast(float, canonical["difficulty"]),
            stem=cast(str, canonical["stem"]),
            choices=tuple(cast(list[str], canonical["choices"])),
            correct=cast(str, canonical["correct"]),
            figure=cast(str, canonical["figure"]),
            source_ref=cast(str, canonical["source_ref"]),
            source_excerpt=cast(str | None, canonical["source_excerpt"]),
            solution_decomposition=cast(
                tuple[object, ...],
                _freeze_json(canonical["solution_decomposition"]),
            ),
            provenance=cast(
                Mapping[str, object] | None,
                _freeze_json(canonical["provenance"]),
            ),
            computational=cast(
                Mapping[str, object] | None,
                _freeze_json(canonical["computational"]),
            ),
            review_id=cast(
                str | None,
                _provided_assignment(review_id, item, "review_id"),
            ),
            stratum=cast(
                str | None,
                _provided_assignment(stratum, item, "stratum"),
            ),
            split=cast(
                str | None,
                _provided_assignment(split, item, "split"),
            ),
            repeat_of=cast(
                str | None,
                _provided_assignment(repeat_of, item, "repeat_of"),
            ),
            metadata=cast(
                Mapping[str, object],
                _freeze_json(_metadata(item)),
            ),
        )
        ruler_item._verify_serialized_hashes(item)
        return ruler_item

    @classmethod
    def from_source(
        cls,
        value: object,
        **assignments: str | None,
    ) -> RulerItem:
        """Short alias for source-item conversion."""
        allowed = _ASSIGNMENT_FIELDS
        if unknown := set(assignments) - allowed:
            names = ", ".join(sorted(unknown))
            raise TypeError(f"unknown assignment field(s): {names}")
        return cls.from_source_item(
            value,
            review_id=assignments.get("review_id"),
            stratum=assignments.get("stratum"),
            split=assignments.get("split"),
            repeat_of=assignments.get("repeat_of"),
        )

    @classmethod
    def from_dict(cls, value: object) -> RulerItem:
        """Restore and verify a serialized private-manifest item."""
        item = _dict_input(value, name="serialized RulerItem")
        missing_hashes = [name for name in _HASH_FIELDS if name not in item]
        if missing_hashes:
            raise ValueError(
                "serialized RulerItem missing hash field(s): "
                + ", ".join(missing_hashes)
            )
        return cls.from_source_item(item)

    def _source_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "topic": self.topic,
            "blueprint_category": self.blueprint_category,
            "kind": self.kind,
            "difficulty": self.difficulty,
            "stem": self.stem,
            "choices": list(self.choices),
            "correct": self.correct,
            "figure": self.figure,
            "source_ref": self.source_ref,
            "source_excerpt": self.source_excerpt,
            "solution_decomposition": _thaw_json(self.solution_decomposition),
            "provenance": _thaw_json(self.provenance),
            "computational": _thaw_json(self.computational),
        }

    def _verify_serialized_hashes(self, value: dict[str, object]) -> None:
        expected = {
            "content_hash": self.content_hash,
            "pass_a_hash": self.pass_a_hash,
            "pass_b_hash": (
                self.pass_b_hash if self.source_excerpt is not None else None
            ),
        }
        for name, actual in expected.items():
            if name in value and value[name] != actual:
                raise ValueError(f"serialized {name} does not match immutable content")

    @property
    def content_hash(self) -> str:
        return content_hash(self)

    @property
    def pass_a_hash(self) -> str:
        return pass_a_hash(self)

    @property
    def pass_b_hash(self) -> str:
        return pass_b_hash(self)

    def pass_a_content(self) -> dict[str, object]:
        """Return only immutable content a Pass A renderer may receive."""
        return _canonical_pass_a(self)

    def pass_b_content(self) -> dict[str, object]:
        """Return only immutable content a Pass B renderer may receive."""
        return _canonical_pass_b(self)

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-compatible private-manifest representation."""
        return {
            **self._source_dict(),
            "review_id": self.review_id,
            "stratum": self.stratum,
            "split": self.split,
            "repeat_of": self.repeat_of,
            "metadata": _thaw_json(self.metadata),
            "content_hash": self.content_hash,
            "pass_a_hash": self.pass_a_hash,
            "pass_b_hash": (
                self.pass_b_hash if self.source_excerpt is not None else None
            ),
        }


# --- Deterministic stratified ruler construction ---------------------------

_Dimension = Callable[["RulerItem"], object]


def _difficulty_band(value: float) -> str:
    if value < 1.0 / 3.0:
        return "easy"
    if value < 2.0 / 3.0:
        return "medium"
    return "hard"


def _dim_category(item: RulerItem) -> object:
    return item.blueprint_category


def _dim_kind(item: RulerItem) -> object:
    return item.kind


def _dim_figure(item: RulerItem) -> object:
    return bool(item.figure)


def _dim_difficulty(item: RulerItem) -> object:
    return _difficulty_band(item.difficulty)


def _dim_error_mode(item: RulerItem) -> object:
    return item.metadata.get("error_mode")


def _dim_stratum(item: RulerItem) -> object:
    return item.stratum


# Ordered so category coverage is reserved first, then problem kind, figure
# presence, intended difficulty band, and finally known error mode.
_STRATUM_DIMENSIONS: tuple[_Dimension, ...] = (
    _dim_category,
    _dim_kind,
    _dim_figure,
    _dim_difficulty,
    _dim_error_mode,
)


def _by_hash(items: Sequence[RulerItem]) -> list[RulerItem]:
    """Sort by immutable content hash so seeded steps ignore input order."""
    return sorted(items, key=lambda item: item.content_hash)


def _reserve(
    pool: Sequence[RulerItem],
    dimensions: tuple[_Dimension, ...],
    budget: int,
) -> tuple[list[RulerItem], set[int]]:
    """Reserve one representative per value of each dimension, deterministically.

    `pool` must already be sorted by content hash. Reservation stops at `budget`.
    """
    chosen: list[RulerItem] = []
    chosen_ids: set[int] = set()
    for dimension in dimensions:
        if len(chosen) >= budget:
            break
        covered = {dimension(item) for item in chosen}
        for item in pool:
            if len(chosen) >= budget:
                break
            if id(item) in chosen_ids:
                continue
            value = dimension(item)
            if value in covered:
                continue
            chosen.append(item)
            chosen_ids.add(id(item))
            covered.add(value)
    return chosen, chosen_ids


def _fill(
    pool: Sequence[RulerItem],
    chosen: list[RulerItem],
    chosen_ids: set[int],
    budget: int,
    rng: random.Random,
) -> list[RulerItem]:
    """Fill the remaining budget with a seed-local shuffle of unreserved items."""
    rest = [item for item in pool if id(item) not in chosen_ids]
    rng.shuffle(rest)
    for item in rest:
        if len(chosen) >= budget:
            break
        chosen.append(item)
        chosen_ids.add(id(item))
    return chosen


def _select_stratum(
    items: Sequence[RulerItem],
    budget: int,
    rng: random.Random,
) -> list[RulerItem]:
    pool = _by_hash(items)
    chosen, chosen_ids = _reserve(pool, _STRATUM_DIMENSIONS, budget)
    return _fill(pool, chosen, chosen_ids, budget, rng)


def _shadow_family_targets(seed: int) -> dict[str, int]:
    """Return the exact 14/13/13 family allocation for a seed."""
    families = sorted(SHADOW_MODEL_FAMILIES)
    base, remainder = divmod(PRIMARY_PER_STRATUM, len(families))
    targets = {family: base for family in families}
    for offset in range(remainder):
        targets[families[(seed + offset) % len(families)]] += 1
    return targets


def _shadow_family_counts(
    items: Sequence[RulerItem],
    *,
    context: str,
) -> dict[str, int]:
    counts = {family: 0 for family in sorted(SHADOW_MODEL_FAMILIES)}
    for item in items:
        family = item.metadata.get(_MODEL_FAMILY_KEY)
        if not isinstance(family, str) or family not in SHADOW_MODEL_FAMILIES:
            raise ValueError(
                f"{context} item {item.id!r} declares unknown model family "
                f"{family!r}; expected one of: "
                + ", ".join(sorted(SHADOW_MODEL_FAMILIES))
            )
        counts[family] += 1
    return counts


def _require_shadow_capacity(
    items: Sequence[RulerItem],
    seed: int,
) -> dict[str, int]:
    targets = _shadow_family_targets(seed)
    available = _shadow_family_counts(items, context="shadow input")
    for family, required in targets.items():
        if available[family] < required:
            raise ValueError(
                f"shadow model family {family!r}: required {required}, "
                f"available {available[family]} for seed {seed}"
            )
    return targets


def _select_shadow(
    items: Sequence[RulerItem],
    targets: Mapping[str, int],
    rng: random.Random,
) -> list[RulerItem]:
    families = sorted(SHADOW_MODEL_FAMILIES)
    by_family: dict[str, list[RulerItem]] = {family: [] for family in families}
    for item in items:
        by_family[cast(str, item.metadata.get(_MODEL_FAMILY_KEY))].append(item)
    selected: list[RulerItem] = []
    for family in families:
        pool = _by_hash(by_family[family])
        target = targets[family]
        chosen, chosen_ids = _reserve(pool, _STRATUM_DIMENSIONS, target)
        selected.extend(_fill(pool, chosen, chosen_ids, target, rng))
    return selected


def _reserve_split_dimension(
    pool: Sequence[RulerItem],
    split_of: dict[int, str],
    dimension: _Dimension,
) -> None:
    for split, cap in (
        ("validation", VALIDATION_SIZE),
        ("calibration", CALIBRATION_SIZE),
    ):
        assigned = [item for item in pool if split_of.get(id(item)) == split]
        covered = {dimension(item) for item in assigned}
        current = len(assigned)
        for item in pool:
            if current >= cap:
                break
            if id(item) in split_of:
                continue
            value = dimension(item)
            if value in covered:
                continue
            split_of[id(item)] = split
            covered.add(value)
            current += 1


def _reserve_split_categories(
    pool: Sequence[RulerItem],
    split_of: dict[int, str],
) -> None:
    by_category: dict[str, list[RulerItem]] = {}
    for item in pool:
        by_category.setdefault(item.blueprint_category, []).append(item)
    for category in sorted(by_category):
        members = by_category[category]
        split_of[id(members[0])] = "validation"
        if len(members) >= 2:
            split_of[id(members[1])] = "calibration"


def _fill_splits(
    pool: Sequence[RulerItem],
    split_of: dict[int, str],
    rng: random.Random,
) -> None:
    validation = sum(1 for item in pool if split_of.get(id(item)) == "validation")
    unassigned = [item for item in pool if id(item) not in split_of]
    rng.shuffle(unassigned)
    remaining_validation = VALIDATION_SIZE - validation
    for index, item in enumerate(unassigned):
        split_of[id(item)] = (
            "validation" if index < remaining_validation else "calibration"
        )


def _assign_splits(
    primary: Sequence[RulerItem],
    rng: random.Random,
) -> dict[int, str]:
    """Assign an 80/40 split, reserving category, stratum, kind, and figure."""
    pool = _by_hash(primary)
    split_of: dict[int, str] = {}
    _reserve_split_categories(pool, split_of)
    _reserve_split_dimension(pool, split_of, _dim_stratum)
    _reserve_split_dimension(pool, split_of, _dim_kind)
    _reserve_split_dimension(pool, split_of, _dim_figure)
    _fill_splits(pool, split_of, rng)
    return split_of


def _select_repeats(
    primary: Sequence[RulerItem],
    count: int,
    rng: random.Random,
) -> list[RulerItem]:
    pool = _by_hash(primary)
    rng.shuffle(pool)
    chosen, chosen_ids = _reserve(pool, (_dim_stratum, _dim_category), count)
    return _fill(pool, chosen, chosen_ids, count, rng)


_Token = tuple[str, RulerItem]


def _display_is_clean(order: Sequence[_Token]) -> bool:
    return all(left[1] is not right[1] for left, right in zip(order, order[1:]))


def _separate_adjacent(order: list[_Token]) -> list[_Token]:
    """Deterministically break any repeat adjacent to its original."""
    size = len(order)
    for index in range(size - 1):
        if order[index][1] is not order[index + 1][1]:
            continue
        for other in range(size):
            if other in (index, index + 1):
                continue
            order[index + 1], order[other] = order[other], order[index + 1]
            if _display_is_clean(order):
                break
            order[index + 1], order[other] = order[other], order[index + 1]
    return order


def _shuffled_display(
    tokens: Sequence[_Token],
    rng: random.Random,
) -> list[_Token]:
    order = list(tokens)
    for _ in range(256):
        rng.shuffle(order)
        if _display_is_clean(order):
            return order
    order = _separate_adjacent(order)
    if not _display_is_clean(order):
        raise ValueError("unable to separate every hidden repeat from its original")
    return order


def _assemble(
    primary: Sequence[RulerItem],
    split_of: Mapping[int, str],
    repeat_origins: Sequence[RulerItem],
    rng: random.Random,
) -> list[RulerItem]:
    tokens: list[_Token] = [("primary", item) for item in primary]
    tokens.extend(("repeat", item) for item in repeat_origins)
    order = _shuffled_display(tokens, rng)

    review_id_of: dict[int, str] = {}
    display_ids = [f"item-{index:04d}" for index in range(1, len(order) + 1)]
    for review_id, (kind, item) in zip(display_ids, order, strict=True):
        if kind == "primary":
            review_id_of[id(item)] = review_id

    assembled: list[RulerItem] = []
    for review_id, (kind, item) in zip(display_ids, order, strict=True):
        if kind == "primary":
            assembled.append(
                replace(
                    item,
                    review_id=review_id,
                    split=split_of[id(item)],
                )
            )
        else:
            assembled.append(
                replace(
                    item,
                    review_id=review_id,
                    split=None,
                    repeat_of=review_id_of[id(item)],
                )
            )
    return assembled


def _convert(values: object, stratum: str) -> list[RulerItem]:
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
        raise ValueError(f"{stratum} input must be a sequence of problem items")
    items: list[RulerItem] = []
    for index, value in enumerate(cast(Sequence[object], values)):
        try:
            items.append(RulerItem.from_source_item(value, stratum=stratum))
        except (TypeError, ValueError) as error:
            raise ValueError(f"{stratum} item {index}: {error}") from error
    return items


def _reject_duplicate_hashes(items: Sequence[RulerItem]) -> None:
    seen: dict[str, str] = {}
    for item in items:
        digest = item.content_hash
        if digest in seen:
            raise ValueError(
                "duplicate content hash across ruler inputs: "
                f"{seen[digest]!r} and {item.id!r}"
            )
        seen[digest] = item.id


def _require_stratum_support(items: Sequence[RulerItem], stratum: str) -> None:
    if len(items) < PRIMARY_PER_STRATUM:
        raise ValueError(
            f"{stratum} stratum provides only {len(items)} unique items; "
            f"{PRIMARY_PER_STRATUM} are required"
        )


def _require_category_support(items: Sequence[RulerItem]) -> None:
    present = {item.blueprint_category for item in items}
    missing = BLUEPRINT_CATEGORIES - present
    if missing:
        raise ValueError(
            "ruler inputs are missing required blueprint categories: "
            + ", ".join(sorted(missing))
        )


def _require_label_balance(
    primary: Sequence[RulerItem],
    split_of: Mapping[int, str],
) -> None:
    labeled = [
        item for item in primary if item.metadata.get(_HUMAN_LABEL_KEY) in _HUMAN_LABELS
    ]
    if not labeled:
        return
    for split in ("calibration", "validation"):
        counts = {"positive": 0, "negative": 0}
        for item in labeled:
            if split_of[id(item)] == split:
                counts[cast(str, item.metadata.get(_HUMAN_LABEL_KEY))] += 1
        for label, count in counts.items():
            if count < 5:
                raise ValueError(
                    f"{split} split has fewer than five human-{label} candidate "
                    f"labels ({count}); rebalance inputs before construction"
                )


def build_ruler(
    trusted: object,
    failures: object,
    shadow: object,
    *,
    seed: int = 7,
) -> RulerManifest:
    """Build a frozen 120-item stratified ruler plus 12 hidden repeats.

    The 120 primaries hold exactly 40 trusted, 40 failure, and 40 shadow unique
    items, split 80 calibration and 40 locked validation. All nine blueprint
    categories appear; problem kind, figure presence, intended difficulty, known
    error mode, and shadow model family are stratified as far as support permits.
    Shadow families receive an exact seed-rotated 14/13/13 allocation.
    Coverage is reserved deterministically after sorting by content hash, then a
    seed-local shuffle fills the remaining slots, so identical inputs and seed are
    byte-stable while a different seed reorders without changing quotas.
    """
    trusted_items = _convert(trusted, "trusted")
    failure_items = _convert(failures, "failure")
    shadow_items = _convert(shadow, "shadow")

    _reject_duplicate_hashes([*trusted_items, *failure_items, *shadow_items])
    _require_stratum_support(trusted_items, "trusted")
    _require_stratum_support(failure_items, "failure")
    _require_stratum_support(shadow_items, "shadow")
    _require_category_support([*trusted_items, *failure_items, *shadow_items])
    shadow_targets = _require_shadow_capacity(shadow_items, seed)

    rng = random.Random(seed)
    primary = [
        *_select_stratum(trusted_items, PRIMARY_PER_STRATUM, rng),
        *_select_stratum(failure_items, PRIMARY_PER_STRATUM, rng),
        *_select_shadow(shadow_items, shadow_targets, rng),
    ]
    split_of = _assign_splits(primary, rng)
    _require_label_balance(primary, split_of)
    repeat_origins = _select_repeats(primary, REPEAT_COUNT, rng)
    items = _assemble(primary, split_of, repeat_origins, rng)

    manifest = RulerManifest(items=tuple(items), seed=seed)
    validate_manifest(manifest)
    return manifest


@dataclass(frozen=True)
class RulerManifest:
    """A frozen private manifest of ruler items in blind display order."""

    items: tuple[RulerItem, ...]
    seed: int

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-compatible private-manifest representation."""
        return {
            "seed": self.seed,
            "items": [item.to_dict() for item in self.items],
        }

    @classmethod
    def from_dict(cls, value: object) -> RulerManifest:
        """Restore and verify a serialized manifest, recomputing item hashes."""
        if type(value) is not dict:
            raise ValueError("serialized manifest must be a JSON object")
        payload = cast(dict[str, object], value)
        seed = payload.get("seed")
        if type(seed) is not int:
            raise ValueError("manifest seed must be an integer")
        raw_items = payload.get("items")
        if type(raw_items) is not list:
            raise ValueError("manifest items must be a JSON array")
        items = tuple(
            RulerItem.from_dict(item) for item in cast(list[object], raw_items)
        )
        return cls(items=items, seed=seed)


def _validate_manifest_counts(
    primary: Sequence[RulerItem],
    repeats: Sequence[RulerItem],
) -> None:
    if len(primary) != 3 * PRIMARY_PER_STRATUM:
        raise ValueError(
            f"manifest has {len(primary)} primary items; "
            f"{3 * PRIMARY_PER_STRATUM} are required"
        )
    if len(repeats) != REPEAT_COUNT:
        raise ValueError(
            f"manifest has {len(repeats)} repeats; {REPEAT_COUNT} are required"
        )
    strata: dict[str, int] = {}
    splits: dict[str, int] = {}
    for item in primary:
        stratum = item.stratum
        split = item.split
        strata[stratum] = strata.get(stratum, 0) + 1
        splits[split] = splits.get(split, 0) + 1
    if strata != {name: PRIMARY_PER_STRATUM for name in _VALID_STRATA}:
        raise ValueError(f"manifest strata are not 40/40/40: {strata}")
    if splits != {"calibration": CALIBRATION_SIZE, "validation": VALIDATION_SIZE}:
        raise ValueError(f"manifest split is not 80/40: {splits}")


def _validate_manifest_identity(items: Sequence[RulerItem]) -> None:
    review_ids = [item.review_id for item in items]
    if None in review_ids:
        raise ValueError("every manifest item requires a review ID")
    if len(set(review_ids)) != len(review_ids):
        raise ValueError("manifest review IDs must be unique")
    expected = [f"item-{index:04d}" for index in range(1, len(items) + 1)]
    if review_ids != expected:
        raise ValueError(
            "manifest review IDs must use the neutral item-XXXX namespace "
            "in display order"
        )
    for item in items:
        if RulerItem.from_dict(item.to_dict()) != item:
            raise ValueError(
                f"manifest item {item.review_id!r} does not round-trip its hashes"
            )
        _validate_private_markers(item.to_dict(), f"$.{item.review_id}")


def _validate_manifest_splits(primary: Sequence[RulerItem]) -> None:
    hashes: dict[str, list[str]] = {"calibration": [], "validation": []}
    for item in primary:
        hashes[item.split].append(item.content_hash)
    overlap = set(hashes["calibration"]) & set(hashes["validation"])
    if overlap:
        raise ValueError(
            "calibration/validation split content-hash overlap: "
            + ", ".join(sorted(overlap))
        )
    all_hashes = [item.content_hash for item in primary]
    if len(set(all_hashes)) != len(all_hashes):
        raise ValueError("primary manifest items must have unique content hashes")


def _validate_manifest_shadow_families(
    primary: Sequence[RulerItem],
    seed: int,
) -> None:
    shadow = [item for item in primary if item.stratum == "shadow"]
    actual = _shadow_family_counts(shadow, context="manifest shadow")
    expected = _shadow_family_targets(seed)
    if actual != expected:
        raise ValueError(
            f"shadow family counts do not match seed {seed}: "
            f"expected {expected}, actual {actual}"
        )


def _validate_manifest_repeats(
    primary: Sequence[RulerItem],
    repeats: Sequence[RulerItem],
) -> None:
    by_review_id = {item.review_id: item for item in primary}
    for repeat in repeats:
        if repeat.split is not None:
            raise ValueError(
                f"repeat {repeat.review_id!r} must not carry a split assignment"
            )
        origin = by_review_id.get(repeat.repeat_of)
        if origin is None:
            raise ValueError(
                f"repeat {repeat.review_id!r} references unknown original "
                f"{repeat.repeat_of!r}"
            )
        if repeat.content_hash != origin.content_hash:
            raise ValueError(
                f"repeat {repeat.review_id!r} content does not match its original"
            )


def _validate_manifest_display(items: Sequence[RulerItem]) -> None:
    for left, right in zip(items, items[1:]):
        if left.repeat_of == right.review_id:
            raise ValueError(
                f"hidden repeat {left.review_id!r} and original "
                f"{right.review_id!r} are adjacent in display order"
            )
        if right.repeat_of == left.review_id:
            raise ValueError(
                f"hidden repeat {right.review_id!r} and original "
                f"{left.review_id!r} are adjacent in display order"
            )


def _validate_manifest_coverage(primary: Sequence[RulerItem]) -> None:
    category_counts: dict[str, int] = {}
    by_split: dict[str, set[str]] = {"calibration": set(), "validation": set()}
    for item in primary:
        category_counts[item.blueprint_category] = (
            category_counts.get(item.blueprint_category, 0) + 1
        )
        by_split[item.split].add(item.blueprint_category)
    missing = BLUEPRINT_CATEGORIES - set(category_counts)
    if missing:
        raise ValueError(
            "primary manifest is missing blueprint categories: "
            + ", ".join(sorted(missing))
        )
    for split, categories in by_split.items():
        for category, count in category_counts.items():
            if count >= 2 and category not in categories:
                raise ValueError(
                    f"{split} split is missing feasible category {category!r}"
                )


def validate_manifest(manifest: RulerManifest) -> None:
    """Recompute every ruler invariant, raising on the first violation.

    Checks locked counts, 40/40/40 strata, the 80/40 split, unique opaque review
    IDs, immutable-hash round trips, split hash disjointness, exact shadow-family
    counts, repeat references and non-adjacency, split category coverage where
    feasible, and the absence of private markers. It never requires human labels.
    """
    if not isinstance(manifest, RulerManifest):
        raise ValueError("validate_manifest requires a RulerManifest")
    primary = [item for item in manifest.items if item.repeat_of is None]
    repeats = [item for item in manifest.items if item.repeat_of is not None]
    _validate_manifest_counts(primary, repeats)
    _validate_manifest_identity(manifest.items)
    _validate_manifest_splits(primary)
    _validate_manifest_shadow_families(primary, manifest.seed)
    _validate_manifest_repeats(primary, repeats)
    _validate_manifest_display(manifest.items)
    _validate_manifest_coverage(primary)
