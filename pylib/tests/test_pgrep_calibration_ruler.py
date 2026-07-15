# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

from __future__ import annotations

import hashlib
import json
import math
import random
from collections import Counter
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from typing import cast

import pytest

from anki.pgrep.ai import calibration_ruler

_BUNDLE_PATH = (
    Path(calibration_ruler.__file__).resolve().parents[1] / "content_bundle.json"
)
_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20">'
    '<defs><marker id="arrow"><path d="M0 0 L2 1"/></marker></defs>'
    "<style>.line{stroke:currentColor}</style>"
    '<path class="line" d="M1 1 L19 19" marker-end="url(#arrow)"/>'
    "</svg>"
)


def _problem(**over: object) -> dict[str, object]:
    item: dict[str, object] = {
        "id": "p-1",
        "topic": "topic::mechanics::rotation",
        "blueprint_category": "mechanics",
        "kind": "conceptual",
        "difficulty": 0.4,
        "stem": "A wheel rotates.",
        "choices": ["1", "2", "3", "4", "5"],
        "correct": "B",
        "source_ref": "OpenStax, p. 1",
        "source_excerpt": "Angular momentum is conserved.",
        "solution_decomposition": [
            {"subgoal": "Choose a conservation law.", "rubric": "Name the law."}
        ],
    }
    item.update(over)
    return item


def _canonical_hash(value: object) -> str:
    raw = json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def test_content_hash_ignores_metadata_but_covers_hidden_content() -> None:
    first = _problem(
        model_family="sol",
        verifier={"decision": "accept"},
        stratum="shadow",
    )
    second = _problem(
        id="p-2",
        model_family="grok",
        verifier={"decision": "reject"},
        stratum="trusted",
    )

    assert calibration_ruler.content_hash(first) == calibration_ruler.content_hash(
        second
    )

    for field, changed in (
        ("correct", "C"),
        ("topic", "topic::mechanics::oscillations"),
        ("kind", "computational"),
        ("difficulty", 0.8),
        ("source_ref", "OpenStax, p. 2"),
        ("source_excerpt", "A different excerpt."),
    ):
        mutated = deepcopy(second)
        mutated[field] = changed
        assert calibration_ruler.content_hash(first) != calibration_ruler.content_hash(
            mutated
        )


def test_content_hash_is_canonical_utf8_json() -> None:
    item = _problem(stem="  Étude   of rotation. ")

    assert calibration_ruler.content_hash(item) == _canonical_hash(
        calibration_ruler.canonical_problem(item)
    )


def test_canonical_text_and_decomposition_use_nfc_and_stable_whitespace() -> None:
    decomposed = _problem(
        stem="  Cafe\u0301   wheel  ",
        choices=[" e\u0301 ", "2", "3", "4", "5"],
        source_excerpt=" Cafe\u0301   source ",
        solution_decomposition=[
            {
                "subgoal": "  Cafe\u0301\n  reasoning ",
                "rubric": "  Keep   spacing stable. ",
            }
        ],
    )
    composed = _problem(
        stem="Café wheel",
        choices=["é", "2", "3", "4", "5"],
        source_excerpt="Café source",
        solution_decomposition=[
            {
                "subgoal": "Café reasoning",
                "rubric": "Keep spacing stable.",
            }
        ],
    )

    canonical = calibration_ruler.canonical_problem(decomposed)

    assert canonical == calibration_ruler.canonical_problem(composed)
    assert calibration_ruler.content_hash(decomposed) == calibration_ruler.content_hash(
        composed
    )
    decomposition = cast(list[dict[str, str]], canonical["solution_decomposition"])
    assert decomposition[0]["subgoal"] == "Café reasoning"
    assert decomposition[0]["rubric"] == "Keep spacing stable."


def test_pass_a_hash_covers_exactly_visible_immutable_content() -> None:
    first = _problem(
        stem=f'A wheel rotates.\n<div class="pg-figure">{_SVG}</div>',
        model_family="sol",
    )
    second = _problem(
        correct="E",
        source_ref="Source B",
        source_excerpt="Different hidden excerpt.",
        solution_decomposition=[],
        model_family="grok",
        verifier={"decision": "reject"},
    )
    second["stem"] = f'A wheel rotates.<div class="pg-figure">{_SVG}</div>'

    expected = {
        "stem": "A wheel rotates.",
        "choices": ["1", "2", "3", "4", "5"],
        "figure": _SVG,
    }
    assert calibration_ruler.pass_a_hash(first) == _canonical_hash(expected)
    assert calibration_ruler.pass_a_hash(first) == calibration_ruler.pass_a_hash(second)

    changed_stem = deepcopy(second)
    changed_stem["stem"] = f'Changed stem.<div class="pg-figure">{_SVG}</div>'
    assert calibration_ruler.pass_a_hash(first) != calibration_ruler.pass_a_hash(
        changed_stem
    )

    changed_choices = deepcopy(second)
    cast(list[str], changed_choices["choices"])[0] = "changed"
    assert calibration_ruler.pass_a_hash(first) != calibration_ruler.pass_a_hash(
        changed_choices
    )

    changed_figure = deepcopy(second)
    changed_figure["figure"] = _SVG.replace("19 19", "18 18")
    changed_figure["stem"] = "A wheel rotates."
    assert calibration_ruler.pass_a_hash(first) != calibration_ruler.pass_a_hash(
        changed_figure
    )


def test_pass_a_hash_is_recomputable_from_visible_content_only() -> None:
    visible = {
        "stem": " A   wheel rotates. ",
        "choices": [" 1 ", "2", "3", "4", "5"],
        "figure": _SVG,
    }

    assert calibration_ruler.pass_a_hash(visible) == _canonical_hash(
        {
            "stem": "A wheel rotates.",
            "choices": ["1", "2", "3", "4", "5"],
            "figure": _SVG,
        }
    )


def test_pass_b_hash_covers_exactly_displayed_excerpt_and_decomposition() -> None:
    first = _problem(source_ref="Citation A", model_family="sol")
    second = _problem(
        stem="Different hidden stem.",
        choices=["a", "b", "c", "d", "e"],
        correct="E",
        source_ref="Citation B",
        model_family="grok",
    )

    expected = {
        "source_excerpt": "Angular momentum is conserved.",
        "solution_decomposition": [
            {"subgoal": "Choose a conservation law.", "rubric": "Name the law."}
        ],
    }
    assert calibration_ruler.pass_b_hash(first) == _canonical_hash(expected)
    assert calibration_ruler.pass_b_hash(first) == calibration_ruler.pass_b_hash(second)

    changed_excerpt = deepcopy(second)
    changed_excerpt["source_excerpt"] = "Changed excerpt."
    assert calibration_ruler.pass_b_hash(first) != calibration_ruler.pass_b_hash(
        changed_excerpt
    )

    changed_decomposition = deepcopy(second)
    changed_decomposition["solution_decomposition"] = []
    assert calibration_ruler.pass_b_hash(first) != calibration_ruler.pass_b_hash(
        changed_decomposition
    )


def test_pass_b_hash_is_recomputable_from_visible_content_only() -> None:
    visible = {
        "source_excerpt": "Angular momentum is conserved.",
        "solution_decomposition": [],
    }

    assert calibration_ruler.pass_b_hash(visible) == _canonical_hash(visible)


def test_missing_excerpt_is_explicit_and_pass_a_remains_available() -> None:
    item = _problem()
    del item["source_excerpt"]

    canonical = calibration_ruler.canonical_problem(item)
    ruler_item = calibration_ruler.RulerItem.from_source_item(item)

    assert canonical["source_excerpt"] is None
    assert calibration_ruler.pass_a_hash(item) == ruler_item.pass_a_hash
    assert ruler_item.pass_a_content()["stem"] == "A wheel rotates."
    assert ruler_item.to_dict()["source_excerpt"] is None
    assert ruler_item.to_dict()["pass_b_hash"] is None
    assert (
        calibration_ruler.RulerItem.from_dict(
            json.loads(json.dumps(ruler_item.to_dict()))
        )
        == ruler_item
    )
    with pytest.raises(ValueError, match="Pass B source excerpt is unavailable"):
        calibration_ruler.pass_b_hash(item)
    with pytest.raises(ValueError, match="Pass B source excerpt is unavailable"):
        ruler_item.pass_b_content()
    with pytest.raises(ValueError, match="Pass B source excerpt is unavailable"):
        _ = ruler_item.pass_b_hash


def test_full_hash_distinguishes_missing_excerpt_from_real_excerpt() -> None:
    missing = _problem()
    del missing["source_excerpt"]
    real = _problem(source_excerpt="OpenStax, p. 1")

    assert calibration_ruler.content_hash(missing) != calibration_ruler.content_hash(
        real
    )


def test_provenance_quote_anchor_is_a_real_pass_b_excerpt() -> None:
    item = _problem(
        provenance={
            "source_ref": "OpenStax, p. 1",
            "chunk_id": "chunk-1",
            "source_title": "University Physics",
            "quote_anchor": " Angular   momentum is conserved. ",
            "support_score": 0.9,
        }
    )
    del item["source_excerpt"]

    canonical = calibration_ruler.canonical_problem(item)

    assert canonical["source_excerpt"] == "Angular momentum is conserved."
    assert calibration_ruler.pass_b_hash(item)
    assert canonical["provenance"] == {
        "source_ref": "OpenStax, p. 1",
        "chunk_id": "chunk-1",
        "source_title": "University Physics",
        "quote_anchor": "Angular momentum is conserved.",
        "support_score": 0.9,
    }


def test_provenance_source_ref_must_match_top_level_source_ref() -> None:
    item = _problem(
        provenance={
            "source_ref": "Different source, p. 2",
            "quote_anchor": "Angular momentum is conserved.",
        }
    )

    with pytest.raises(ValueError, match="provenance.source_ref.*source_ref"):
        calibration_ruler.validate_source_item(item)


def test_quote_anchor_and_explicit_excerpt_compare_canonically() -> None:
    item = _problem(
        source_excerpt="  Cafe\u0301   angular momentum. ",
        provenance={
            "source_ref": " OpenStax,   p. 1 ",
            "quote_anchor": "Café angular   momentum.",
        },
    )

    canonical = calibration_ruler.canonical_problem(item)

    assert canonical["source_excerpt"] == "Café angular momentum."
    assert cast(dict[str, object], canonical["provenance"])["source_ref"] == (
        "OpenStax, p. 1"
    )


def test_quote_anchor_and_explicit_excerpt_must_not_contradict() -> None:
    item = _problem(
        source_excerpt="Angular momentum is conserved.",
        provenance={
            "source_ref": "OpenStax, p. 1",
            "quote_anchor": "Angular momentum is not conserved.",
        },
    )

    with pytest.raises(ValueError, match="source_excerpt.*quote_anchor"):
        calibration_ruler.validate_source_item(item)


def test_embedded_bundle_figure_is_extracted_without_rewriting_svg() -> None:
    item = _problem(
        stem=f'  A wheel rotates. \n<div class="pg-figure">\n{_SVG}\n</div> '
    )
    original = deepcopy(item)

    canonical = calibration_ruler.canonical_problem(item)

    assert canonical["stem"] == "A wheel rotates."
    assert canonical["figure"] == _SVG
    assert item == original


def test_embedded_svg_bytes_are_not_unicode_normalized() -> None:
    nfd_svg = '<svg xmlns="http://www.w3.org/2000/svg"><text>Cafe\u0301</text></svg>'
    item = _problem(
        stem=(f' Cafe\u0301   prose <div class="pg-figure">{nfd_svg}</div>')
    )

    canonical = calibration_ruler.canonical_problem(item)
    nfc_figure_item = _problem(
        stem="Café prose", figure=nfd_svg.replace("e\u0301", "é")
    )

    assert canonical["stem"] == "Café prose"
    assert canonical["figure"] == nfd_svg
    assert calibration_ruler.pass_a_hash(item) != calibration_ruler.pass_a_hash(
        nfc_figure_item
    )


def test_nfd_embedded_and_explicit_svg_match_by_raw_bytes() -> None:
    nfd_svg = '<svg xmlns="http://www.w3.org/2000/svg"><text>Cafe\u0301</text></svg>'
    item = _problem(
        stem=f'A wheel rotates.<div class="pg-figure">{nfd_svg}</div>',
        figure=nfd_svg,
    )

    assert calibration_ruler.canonical_problem(item)["figure"] == nfd_svg


def test_matching_explicit_and_embedded_figures_are_allowed() -> None:
    item = _problem(
        stem=f'A wheel rotates.<div class="pg-figure">{_SVG}</div>',
        figure=_SVG,
    )

    assert calibration_ruler.canonical_problem(item)["figure"] == _SVG


def test_conflicting_explicit_and_embedded_figures_are_rejected() -> None:
    item = _problem(
        stem=f'A wheel rotates.<div class="pg-figure">{_SVG}</div>',
        figure=_SVG.replace("19 19", "18 18"),
    )

    with pytest.raises(ValueError, match="figure.*conflict"):
        calibration_ruler.validate_source_item(item)


@pytest.mark.parametrize(
    "figure",
    [
        '<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>',
        '<svg xmlns="http://www.w3.org/2000/svg" onload="alert(1)"></svg>',
        (
            '<svg xmlns="http://www.w3.org/2000/svg">'
            '<image href="https://example.com/a.png"/></svg>'
        ),
        (
            '<svg xmlns="http://www.w3.org/2000/svg">'
            "<style>.x{fill:url(https://example.com/x)}</style></svg>"
        ),
        (
            '<svg xmlns="http://www.w3.org/2000/svg">'
            "<foreignObject><div>html</div></foreignObject></svg>"
        ),
    ],
)
def test_unsafe_figure_markup_is_rejected_not_silently_modified(figure: str) -> None:
    item = _problem(figure=figure)
    original = deepcopy(item)

    with pytest.raises(ValueError, match="figure"):
        calibration_ruler.canonical_problem(item)

    assert item == original


@pytest.mark.parametrize(
    "style",
    [
        "@import url(#local); fill: currentColor",
        r"\40 import url(#local); fill: currentColor",
        "width: expression(alert(1))",
        r"fill: u\72l(\68ttps://example.com/fill.svg#x)",
        "fill: url(https://example.com/fill.svg#x)",
        "fill: url(//example.com/fill.svg#x)",
        "fill: url(data:image/svg+xml;base64,PHN2Zz4=)",
        "fill: url( #fade )",
        "fill: url('#fade')",
    ],
)
def test_unsafe_svg_style_attributes_are_rejected(style: str) -> None:
    figure = (
        '<svg xmlns="http://www.w3.org/2000/svg">'
        f'<path style="{style}" d="M0 0 L1 1"/>'
        "</svg>"
    )

    with pytest.raises(ValueError, match="figure"):
        calibration_ruler.validate_source_item(_problem(figure=figure))


def test_safe_svg_style_fragment_reference_is_preserved() -> None:
    figure = (
        '<svg xmlns="http://www.w3.org/2000/svg">'
        '<defs><linearGradient id="fade"><stop offset="0"/></linearGradient></defs>'
        '<path style="fill:url(#fade);stroke:currentColor" d="M0 0 L1 1"/>'
        "</svg>"
    )

    assert (
        calibration_ruler.canonical_problem(_problem(figure=figure))["figure"] == figure
    )


@pytest.mark.parametrize(
    "fill",
    [
        r"u\72l(\68ttps://example.com/fill.svg#x)",
        "url('#fade')",
        "url( #fade )",
    ],
)
def test_svg_presentation_attributes_use_strict_css_urls(fill: str) -> None:
    figure = (
        '<svg xmlns="http://www.w3.org/2000/svg">'
        f'<path fill="{fill}" d="M0 0 L1 1"/>'
        "</svg>"
    )

    with pytest.raises(ValueError, match="figure"):
        calibration_ruler.validate_source_item(_problem(figure=figure))


@pytest.mark.parametrize(
    "choices",
    [
        ["1", "2", "3", "4"],
        ["1", "2", "3", "4", "5", "6"],
        ["1", "2", "", "4", "5"],
        ["1", "2", "   ", "4", "5"],
        ["1", "2", 3, "4", "5"],
        ("1", "2", "3", "4", "5"),
    ],
)
def test_choices_must_be_exactly_five_non_empty_strings(choices: object) -> None:
    with pytest.raises(ValueError, match="choices"):
        calibration_ruler.validate_source_item(_problem(choices=choices))


@pytest.mark.parametrize("correct", ["A", "B", "C", "D", "E"])
def test_stored_key_accepts_exact_letters(correct: str) -> None:
    calibration_ruler.validate_source_item(_problem(correct=correct))


@pytest.mark.parametrize("correct", ["", "a", " F", "F", 1, None])
def test_stored_key_rejects_non_exact_letters(correct: object) -> None:
    with pytest.raises(ValueError, match="correct"):
        calibration_ruler.validate_source_item(_problem(correct=correct))


def test_shadow_key_alias_is_normalized() -> None:
    item = _problem(key="D")
    del item["correct"]

    assert calibration_ruler.canonical_problem(item)["correct"] == "D"


def test_conflicting_key_aliases_are_rejected() -> None:
    with pytest.raises(ValueError, match="correct.*key"):
        calibration_ruler.validate_source_item(_problem(correct="B", key="C"))


def test_explicit_invalid_correct_is_not_hidden_by_key_alias() -> None:
    with pytest.raises(ValueError, match="correct"):
        calibration_ruler.validate_source_item(_problem(correct=None, key="B"))


@pytest.mark.parametrize("category", sorted(calibration_ruler.BLUEPRINT_CATEGORIES))
def test_locked_blueprint_categories_are_accepted(category: str) -> None:
    topic = f"topic::{category}"
    assert (
        calibration_ruler.canonical_problem(
            _problem(topic=topic, blueprint_category=category)
        )["blueprint_category"]
        == category
    )


@pytest.mark.parametrize(
    "category",
    [
        "Classical Mechanics",
        "classical_mechanics",
        "Mechanics",
        " mechanics",
        "mechanics ",
        "optics",
    ],
)
def test_category_must_use_exact_locked_slug(category: str) -> None:
    with pytest.raises(ValueError, match="blueprint_category"):
        calibration_ruler.validate_source_item(_problem(blueprint_category=category))


def test_bundle_category_is_derived_from_topic() -> None:
    item = _problem()
    del item["blueprint_category"]

    assert (
        calibration_ruler.canonical_problem(item)["blueprint_category"] == "mechanics"
    )


def test_explicit_invalid_category_is_not_replaced_from_topic() -> None:
    with pytest.raises(ValueError, match="blueprint_category"):
        calibration_ruler.validate_source_item(_problem(blueprint_category=None))


def test_topic_and_explicit_category_must_agree() -> None:
    with pytest.raises(ValueError, match="blueprint_category.*topic"):
        calibration_ruler.validate_source_item(_problem(blueprint_category="quantum"))


@pytest.mark.parametrize(
    ("field", "invalid"),
    [
        ("id", ""),
        ("topic", " "),
        ("source_ref", None),
        ("source_ref", ""),
        ("source_excerpt", " "),
    ],
)
def test_required_identity_topic_and_source_are_non_empty(
    field: str, invalid: object
) -> None:
    with pytest.raises(ValueError, match=field):
        calibration_ruler.validate_source_item(_problem(**{field: invalid}))


@pytest.mark.parametrize("kind", ["conceptual", "computational"])
def test_problem_kind_accepts_exact_values(kind: str) -> None:
    assert calibration_ruler.canonical_problem(_problem(kind=kind))["kind"] == kind


def test_shadow_problem_kind_shape_is_normalized() -> None:
    item = _problem(kind="problem", problem_kind="computational")

    assert calibration_ruler.canonical_problem(item)["kind"] == "computational"


def test_generic_problem_kind_without_evidence_is_unspecified() -> None:
    item = _problem(kind="problem")

    assert calibration_ruler.canonical_problem(item)["kind"] == "unspecified"


def test_generic_problem_kind_uses_real_computational_evidence() -> None:
    item = _problem(
        kind="problem",
        computational={
            "expression": "2 + 2",
            "expected": 4.0,
            "tolerance": 1e-6,
        },
    )

    assert calibration_ruler.canonical_problem(item)["kind"] == "computational"


def test_generic_problem_kind_does_not_infer_from_weak_evidence() -> None:
    item = _problem(kind="problem", computational={"expression": "2 + 2"})

    assert calibration_ruler.canonical_problem(item)["kind"] == "unspecified"


def test_missing_kind_can_use_shadow_problem_kind() -> None:
    item = _problem(problem_kind="computational")
    del item["kind"]

    assert calibration_ruler.canonical_problem(item)["kind"] == "computational"


def test_explicit_invalid_kind_is_not_hidden_by_problem_kind_alias() -> None:
    with pytest.raises(ValueError, match="kind"):
        calibration_ruler.validate_source_item(
            _problem(kind=None, problem_kind="conceptual")
        )


@pytest.mark.parametrize(
    "item",
    [
        _problem(kind="Conceptual"),
        _problem(kind="card"),
        _problem(kind=None),
        _problem(kind="conceptual", problem_kind="computational"),
    ],
)
def test_invalid_or_conflicting_problem_kind_is_rejected(
    item: dict[str, object],
) -> None:
    with pytest.raises(ValueError, match="kind"):
        calibration_ruler.validate_source_item(item)


@pytest.mark.parametrize("difficulty", [0, 0.0, 0.5, 1, 1.0])
def test_difficulty_accepts_finite_unit_interval(difficulty: int | float) -> None:
    assert calibration_ruler.canonical_problem(_problem(difficulty=difficulty))[
        "difficulty"
    ] == float(difficulty)


@pytest.mark.parametrize(
    "difficulty",
    [-0.1, 1.1, math.nan, math.inf, -math.inf, True, "0.5", None],
)
def test_difficulty_rejects_invalid_values(difficulty: object) -> None:
    with pytest.raises(ValueError, match="difficulty|non-finite"):
        calibration_ruler.validate_source_item(_problem(difficulty=difficulty))


@pytest.mark.parametrize("nonfinite", [math.nan, math.inf, -math.inf])
def test_nonfinite_numbers_are_rejected_recursively(nonfinite: float) -> None:
    with pytest.raises(ValueError, match=r"\$\.verifier\.confidence.*non-finite"):
        calibration_ruler.validate_source_item(
            _problem(verifier={"confidence": nonfinite})
        )


@pytest.mark.parametrize(
    "value",
    [
        ("tuple",),
        {"set"},
        object(),
    ],
)
def test_non_json_types_are_rejected_recursively(value: object) -> None:
    with pytest.raises(ValueError, match="JSON-compatible"):
        calibration_ruler.validate_source_item(_problem(verifier={"value": value}))


def test_non_string_json_keys_are_rejected_recursively() -> None:
    with pytest.raises(ValueError, match="JSON object keys"):
        calibration_ruler.validate_source_item(
            _problem(verifier=cast(object, {1: "value"}))
        )


def test_cyclic_json_values_are_rejected() -> None:
    cycle: list[object] = []
    cycle.append(cycle)

    with pytest.raises(ValueError, match="cyclic"):
        calibration_ruler.validate_source_item(_problem(verifier=cycle))


@pytest.mark.parametrize(
    "path",
    [
        "content/gold/problems/item.json",
        r"content\GOLD\problems\item.json",
        "gold-set/item",
        "gold.items/item",
        "gold.json",
        "heldout/item",
        "held-out/item",
        "held_out/item",
        "held out/item",
        "held/out/item",
        "ETS/item",
        "ets-private.json",
        "tier3-private/item",
        "tier-3/item",
        "tier_3/item",
        "tier 3/item",
        "tier/3/item",
        "gr9677/item",
        "gr1777.item",
    ],
)
def test_private_dataset_paths_are_rejected_recursively(
    path: str,
) -> None:
    with pytest.raises(ValueError, match="private marker"):
        calibration_ruler.validate_source_item(
            _problem(verifier={"nested": [{"path": path}]})
        )


@pytest.mark.parametrize(
    "item_id",
    [
        "gold-17",
        "heldout_17",
        "held-out-17",
        "tier3-17",
        "tier_3_17",
        "ets-17",
        "gr9677-17",
    ],
)
def test_private_dataset_markers_are_rejected_in_ids(item_id: str) -> None:
    with pytest.raises(ValueError, match="private marker"):
        calibration_ruler.validate_source_item(_problem(id=item_id))


@pytest.mark.parametrize(
    "source_ref",
    [
        "content/gold/problems/item.json",
        r"content\held-out\item.json",
        "tier3-private/items/item.json",
        "ets-private/form.json",
    ],
)
def test_private_source_paths_are_rejected(source_ref: str) -> None:
    with pytest.raises(ValueError, match="private marker"):
        calibration_ruler.validate_source_item(_problem(source_ref=source_ref))


def test_private_markers_are_rejected_in_nested_keys() -> None:
    with pytest.raises(ValueError, match=r"\$\.verifier\.gold_path.*private marker"):
        calibration_ruler.validate_source_item(
            _problem(verifier={"gold_path": "hidden"})
        )


def test_nested_source_path_context_reaches_wrapped_value() -> None:
    item = _problem(source_path={"wrapper": [{"value": "gold"}]})

    with pytest.raises(ValueError, match="private marker"):
        calibration_ruler.validate_source_item(item)


def test_repeat_of_is_validated_as_an_opaque_id() -> None:
    with pytest.raises(ValueError, match="private marker"):
        calibration_ruler.RulerItem.from_source_item(
            _problem(),
            repeat_of="heldout-17",
        )


def test_opaque_id_context_survives_list_and_dict_wrappers() -> None:
    item = _problem(audit={"opaque_ids": [{"wrapper": {"value": "tier3-17"}}]})

    with pytest.raises(ValueError, match="private marker"):
        calibration_ruler.validate_source_item(item)


def test_legitimate_gold_physics_prose_is_allowed() -> None:
    item = _problem(
        stem="Alpha particles scatter from a thin gold foil.",
        source_ref="OpenStax discussion of the gold foil experiment",
        source_excerpt="A gold nucleus concentrates the atom's positive charge.",
        solution_decomposition=[
            {
                "subgoal": "Model scattering from the gold nucleus.",
                "rubric": "Use the measured gold foil deflection.",
            }
        ],
    )

    calibration_ruler.validate_source_item(item)


def test_benign_marigold_text_does_not_trip_private_marker_firewall() -> None:
    item = _problem(
        stem="A marigold is placed near a converging lens.",
        source_ref="Open botany, marigold/17",
        source_excerpt="A marigold has yellow petals.",
        verifier={"note": "marigold"},
    )

    calibration_ruler.validate_source_item(item)


def test_ruler_item_round_trip_and_visible_projections() -> None:
    source = _problem(
        model_family="sol",
        verifier={"decision": "accept"},
        generation_seed=7,
    )
    item = calibration_ruler.RulerItem.from_source_item(
        source,
        review_id="item-0001",
        stratum="shadow",
        split="calibration",
    )

    serialized = json.loads(json.dumps(item.to_dict(), ensure_ascii=False))
    restored = calibration_ruler.RulerItem.from_dict(serialized)

    assert restored == item
    assert item.content_hash == calibration_ruler.content_hash(source)
    assert item.pass_a_hash == calibration_ruler.pass_a_hash(source)
    assert item.pass_b_hash == calibration_ruler.pass_b_hash(source)
    assert set(item.pass_a_content()) == {"stem", "choices", "figure"}
    assert set(item.pass_b_content()) == {
        "source_excerpt",
        "solution_decomposition",
    }
    assert "correct" not in item.pass_a_content()
    assert "source_ref" not in item.pass_a_content()
    assert "metadata" not in item.pass_a_content()
    assert "model_family" not in item.pass_a_content()
    assert "verifier" not in item.pass_a_content()
    assert "stratum" not in item.pass_a_content()
    assert item.metadata["model_family"] == "sol"
    assert item.metadata["verifier"] == {"decision": "accept"}
    assert item.stratum == "shadow"


def test_ruler_item_deep_freezes_content_provenance_and_metadata() -> None:
    source = _problem(
        provenance={
            "chunk_id": "chunk-1",
            "source_ref": "OpenStax, p. 1",
            "quote_anchor": "Angular momentum is conserved.",
            "support_score": 0.9,
            "details": {"pages": [1, 2]},
        },
        verifier={"decision": "accept", "checks": [{"name": "key"}]},
    )
    item = calibration_ruler.RulerItem.from_source_item(source)
    before = item.to_dict()
    full_hash = item.content_hash

    cast(dict[str, object], source["provenance"])["chunk_id"] = "changed"
    cast(dict[str, object], source["verifier"])["decision"] = "changed"
    cast(list[dict[str, str]], source["solution_decomposition"])[0]["subgoal"] = (
        "changed"
    )

    with pytest.raises(TypeError):
        cast(dict[str, object], item.metadata)["verifier"] = {}
    with pytest.raises(TypeError):
        cast(dict[str, object], item.metadata["verifier"])["decision"] = "reject"
    with pytest.raises(TypeError):
        cast(dict[str, object], item.provenance)["chunk_id"] = "changed"
    with pytest.raises(TypeError):
        cast(dict[str, object], item.solution_decomposition[0])["subgoal"] = "changed"

    detached = item.to_dict()
    cast(dict[str, object], detached["provenance"])["chunk_id"] = "detached"
    cast(dict[str, object], detached["metadata"])["verifier"] = {}
    cast(list[dict[str, str]], detached["solution_decomposition"])[0]["subgoal"] = (
        "detached"
    )

    assert item.to_dict() == before
    assert item.content_hash == full_hash


def test_full_hash_and_round_trip_preserve_grounding_provenance() -> None:
    first = _problem(
        provenance={
            "chunk_id": "chunk-1",
            "source_ref": "OpenStax, p. 1",
            "quote_anchor": "Angular momentum is conserved.",
            "support_score": 0.9,
        },
        model_family="sol",
        verifier={"decision": "accept"},
        stratum="shadow",
    )
    second = deepcopy(first)
    cast(dict[str, object], second["provenance"])["chunk_id"] = "chunk-2"
    second["model_family"] = "grok"
    second["verifier"] = {"decision": "reject"}
    second["stratum"] = "trusted"

    assert calibration_ruler.content_hash(first) != calibration_ruler.content_hash(
        second
    )

    item = calibration_ruler.RulerItem.from_source_item(first)
    restored = calibration_ruler.RulerItem.from_dict(
        json.loads(json.dumps(item.to_dict()))
    )
    assert restored == item
    assert restored.to_dict()["provenance"] == first["provenance"]


@pytest.mark.parametrize("hash_field", ["content_hash", "pass_a_hash", "pass_b_hash"])
def test_ruler_item_round_trip_rejects_tampered_hash(hash_field: str) -> None:
    payload = calibration_ruler.RulerItem.from_source_item(_problem()).to_dict()
    payload[hash_field] = "0" * 64

    with pytest.raises(ValueError, match=hash_field):
        calibration_ruler.RulerItem.from_dict(payload)


def test_every_shipped_bundle_problem_converts_without_structural_violations() -> None:
    bundle = json.loads(_BUNDLE_PATH.read_text(encoding="utf-8"))
    errors: list[str] = []

    for problem in bundle["problems"]:
        try:
            item = calibration_ruler.RulerItem.from_source_item(problem)
            json.dumps(item.to_dict(), ensure_ascii=False, allow_nan=False)
        except (TypeError, ValueError) as error:
            errors.append(f"{problem.get('id')}: {error}")

    assert errors == []


# --- Task 2: deterministic stratified ruler construction -------------------

_FAMILIES = ("sol", "opus", "grok")
_ERROR_MODES = (
    "wrong_key",
    "free_elimination",
    "ambiguous_stem",
    "figure_contradiction",
    "unsupported_citation",
    "decomposition_leak",
    "out_of_band_difficulty",
)
_KINDS = ("conceptual", "computational", "unspecified")


def _fixture_item(
    stratum: str,
    index: int,
    *,
    categories: tuple[str, ...] | None = None,
) -> dict[str, object]:
    slugs = categories or tuple(sorted(calibration_ruler.BLUEPRINT_CATEGORIES))
    category = slugs[index % len(slugs)]
    stem = f"Consider configuration {index} governed by {category} principles."
    if index % 2 == 0:
        stem = f'{stem}<div class="pg-figure">{_SVG}</div>'
    item: dict[str, object] = {
        "id": f"{stratum}-{index}",
        "topic": f"topic::{category}",
        "blueprint_category": category,
        "kind": _KINDS[index % len(_KINDS)],
        "difficulty": (0.1, 0.5, 0.9)[index % 3],
        "stem": stem,
        "choices": ["1", "2", "3", "4", "5"],
        "correct": "ABCDE"[index % 5],
        "source_ref": f"OpenStax {stratum} chapter {index}",
        "source_excerpt": f"Grounding excerpt {index} covering {category}.",
        "solution_decomposition": [
            {"subgoal": f"Reason about {category}.", "rubric": "Name the law."}
        ],
    }
    if stratum == "shadow":
        item["model_family"] = _FAMILIES[index % len(_FAMILIES)]
    if stratum == "failure":
        item["error_mode"] = _ERROR_MODES[index % len(_ERROR_MODES)]
    return item


def _fixture_items(
    stratum: str,
    count: int,
    *,
    categories: tuple[str, ...] | None = None,
) -> list[dict[str, object]]:
    return [
        _fixture_item(stratum, index, categories=categories) for index in range(count)
    ]


def _shadow_items_with_family_counts(
    counts: dict[str, int],
) -> list[dict[str, object]]:
    items: list[dict[str, object]] = []
    index = 0
    for family in sorted(counts):
        for _ in range(counts[family]):
            item = _fixture_item("shadow", index)
            item["model_family"] = family
            items.append(item)
            index += 1
    return items


def _inputs(
    count: int = 60,
) -> tuple[
    list[dict[str, object]],
    list[dict[str, object]],
    list[dict[str, object]],
]:
    return (
        _fixture_items("trusted", count),
        _fixture_items("failure", count),
        _fixture_items("shadow", count),
    )


def _primary(
    manifest: calibration_ruler.RulerManifest,
) -> list[calibration_ruler.RulerItem]:
    return [item for item in manifest.items if item.repeat_of is None]


def _repeats(
    manifest: calibration_ruler.RulerManifest,
) -> list[calibration_ruler.RulerItem]:
    return [item for item in manifest.items if item.repeat_of is not None]


def test_ruler_has_locked_counts_splits_and_repeats() -> None:
    manifest = calibration_ruler.build_ruler(
        trusted=_fixture_items("trusted", 60),
        failures=_fixture_items("failure", 60),
        shadow=_fixture_items("shadow", 60),
        seed=7,
    )
    primary = _primary(manifest)
    repeats = _repeats(manifest)
    assert len(primary) == 120
    assert len(repeats) == 12
    assert Counter(item.stratum for item in primary) == {
        "trusted": 40,
        "failure": 40,
        "shadow": 40,
    }
    assert Counter(item.split for item in primary) == {
        "calibration": 80,
        "validation": 40,
    }
    assert {item.blueprint_category for item in primary} == set(
        calibration_ruler.BLUEPRINT_CATEGORIES
    )


def test_same_seed_is_byte_stable() -> None:
    first = calibration_ruler.build_ruler(*_inputs(), seed=7).to_dict()
    second = calibration_ruler.build_ruler(*_inputs(), seed=7).to_dict()
    assert first == second


def test_input_order_does_not_change_manifest() -> None:
    trusted, failures, shadow = _inputs()
    first = calibration_ruler.build_ruler(trusted, failures, shadow, seed=7)
    second = calibration_ruler.build_ruler(
        list(reversed(trusted)),
        list(reversed(failures)),
        list(reversed(shadow)),
        seed=7,
    )
    assert first.to_dict() == second.to_dict()


def test_different_seed_changes_order_but_not_quotas() -> None:
    first = calibration_ruler.build_ruler(*_inputs(), seed=7)
    second = calibration_ruler.build_ruler(*_inputs(), seed=11)

    def quotas(manifest: calibration_ruler.RulerManifest) -> dict[str, object]:
        primary = _primary(manifest)
        return {
            "strata": Counter(item.stratum for item in primary),
            "splits": Counter(item.split for item in primary),
            "repeats": len(_repeats(manifest)),
            "categories": frozenset(item.blueprint_category for item in primary),
        }

    assert quotas(first) == quotas(second)
    order_first = [item.content_hash for item in first.items]
    order_second = [item.content_hash for item in second.items]
    assert order_first != order_second


def test_shadow_families_are_balanced() -> None:
    manifest = calibration_ruler.build_ruler(*_inputs(), seed=7)
    shadow = [item for item in _primary(manifest) if item.stratum == "shadow"]
    families = Counter(item.metadata["model_family"] for item in shadow)
    assert set(families) == set(_FAMILIES)
    assert max(families.values()) - min(families.values()) <= 1


@pytest.mark.parametrize("seed", range(6))
def test_shadow_extra_family_rotates_exactly_with_seed(seed: int) -> None:
    manifest = calibration_ruler.build_ruler(*_inputs(), seed=seed)
    shadow = [item for item in _primary(manifest) if item.stratum == "shadow"]
    expected = {family: 13 for family in sorted(_FAMILIES)}
    expected[sorted(_FAMILIES)[seed % len(_FAMILIES)]] = 14
    assert Counter(item.metadata["model_family"] for item in shadow) == expected


def test_repeats_reference_originals_and_leave_support_untouched() -> None:
    manifest = calibration_ruler.build_ruler(*_inputs(), seed=7)
    primary = _primary(manifest)
    repeats = _repeats(manifest)
    by_review_id = {item.review_id: item for item in primary}

    assert all(item.split is None for item in repeats)
    assert all(item.review_id.startswith("item-") for item in repeats)
    for repeat in repeats:
        origin = by_review_id[repeat.repeat_of]
        assert repeat.content_hash == origin.content_hash
    assert {repeat.stratum for repeat in repeats} == {
        "trusted",
        "failure",
        "shadow",
    }
    assert {repeat.blueprint_category for repeat in repeats} == set(
        calibration_ruler.BLUEPRINT_CATEGORIES
    )


def test_repeat_selection_is_seeded_across_feasible_candidates() -> None:
    primary = _primary(calibration_ruler.build_ruler(*_inputs(), seed=7))
    first = calibration_ruler._select_repeats(
        primary,
        calibration_ruler.REPEAT_COUNT,
        random.Random(19),
    )
    same = calibration_ruler._select_repeats(
        primary,
        calibration_ruler.REPEAT_COUNT,
        random.Random(19),
    )
    different = calibration_ruler._select_repeats(
        primary,
        calibration_ruler.REPEAT_COUNT,
        random.Random(23),
    )

    assert [item.content_hash for item in first] == [item.content_hash for item in same]
    assert {item.content_hash for item in first} != {
        item.content_hash for item in different
    }
    coverage_slots = len(calibration_ruler.BLUEPRINT_CATEGORIES)
    assert [item.content_hash for item in first[:coverage_slots]] != [
        item.content_hash for item in different[:coverage_slots]
    ]
    for selected in (first, different):
        assert {item.stratum for item in selected} == {
            "trusted",
            "failure",
            "shadow",
        }
        assert {item.blueprint_category for item in selected} == set(
            calibration_ruler.BLUEPRINT_CATEGORIES
        )


def test_review_ids_are_opaque_and_sequential() -> None:
    manifest = calibration_ruler.build_ruler(*_inputs(), seed=7)
    assert [item.review_id for item in manifest.items] == [
        f"item-{index:04d}" for index in range(1, 133)
    ]
    assert not any(
        item.review_id.startswith(("cal-", "rep-")) for item in manifest.items
    )
    assert all(repeat.repeat_of.startswith("item-") for repeat in _repeats(manifest))


def test_manifest_rejects_origin_revealing_review_id() -> None:
    manifest = calibration_ruler.build_ruler(*_inputs(), seed=7)
    changed = replace(
        manifest.items[0],
        review_id="cal-0001",
    )
    with pytest.raises(ValueError, match="neutral item"):
        calibration_ruler.validate_manifest(
            replace(manifest, items=(changed, *manifest.items[1:]))
        )


def test_no_repeat_is_adjacent_to_its_original() -> None:
    for seed in range(25):
        manifest = calibration_ruler.build_ruler(*_inputs(), seed=seed)
        hashes = [item.content_hash for item in manifest.items]
        for left, right in zip(hashes, hashes[1:]):
            assert left != right


def test_display_shuffle_fails_when_separation_is_impossible() -> None:
    item = calibration_ruler.RulerItem.from_source_item(
        _fixture_item("trusted", 0),
        stratum="trusted",
    )
    with pytest.raises(ValueError, match="unable to separate"):
        calibration_ruler._shuffled_display(
            [("primary", item), ("repeat", item)],
            random.Random(7),
        )


def test_hidden_fields_never_enter_pass_a_projection() -> None:
    manifest = calibration_ruler.build_ruler(*_inputs(), seed=7)
    shadow = next(item for item in _primary(manifest) if item.stratum == "shadow")
    projection = shadow.pass_a_content()
    assert set(projection) == {"stem", "choices", "figure"}
    rendered = json.dumps(projection)
    family = cast(str, shadow.metadata["model_family"])
    for hidden in ("stratum", "split", "repeat_of", "model_family", "shadow", family):
        assert hidden not in rendered


def test_each_split_covers_every_category_when_feasible() -> None:
    manifest = calibration_ruler.build_ruler(*_inputs(), seed=7)
    primary = _primary(manifest)
    calibration = {
        item.blueprint_category for item in primary if item.split == "calibration"
    }
    validation = {
        item.blueprint_category for item in primary if item.split == "validation"
    }
    assert calibration == set(calibration_ruler.BLUEPRINT_CATEGORIES)
    assert validation == set(calibration_ruler.BLUEPRINT_CATEGORIES)


def test_insufficient_stratum_count_is_rejected() -> None:
    with pytest.raises(ValueError, match="trusted stratum"):
        calibration_ruler.build_ruler(
            _fixture_items("trusted", 39),
            _fixture_items("failure", 60),
            _fixture_items("shadow", 60),
        )


def test_missing_category_is_rejected_with_diagnostic() -> None:
    eight = tuple(sorted(calibration_ruler.BLUEPRINT_CATEGORIES))[:8]
    with pytest.raises(ValueError, match="categor"):
        calibration_ruler.build_ruler(
            _fixture_items("trusted", 60, categories=eight),
            _fixture_items("failure", 60, categories=eight),
            _fixture_items("shadow", 60, categories=eight),
        )


def test_duplicate_content_hash_is_rejected() -> None:
    trusted = _fixture_items("trusted", 60)
    duplicate = _fixture_item("trusted", 0)
    duplicate["id"] = "trusted-duplicate"
    trusted.append(duplicate)
    with pytest.raises(ValueError, match="duplicate content hash"):
        calibration_ruler.build_ruler(
            trusted,
            _fixture_items("failure", 60),
            _fixture_items("shadow", 60),
        )


def test_gold_marker_input_is_rejected() -> None:
    trusted = _fixture_items("trusted", 60)
    trusted[0]["source_ref"] = "content/gold/problems/gold-1.json"
    with pytest.raises(ValueError, match="private marker"):
        calibration_ruler.build_ruler(
            trusted,
            _fixture_items("failure", 60),
            _fixture_items("shadow", 60),
        )


def test_absent_shadow_family_fails_before_sampling() -> None:
    shadow = _fixture_items("shadow", 60)
    for item in shadow:
        item["model_family"] = "sol"
    with pytest.raises(ValueError, match="model famil"):
        calibration_ruler.build_ruler(
            _fixture_items("trusted", 60),
            _fixture_items("failure", 60),
            shadow,
        )


@pytest.mark.parametrize(
    ("family", "required"),
    [("grok", 14), ("opus", 13), ("sol", 13)],
)
def test_insufficient_shadow_family_capacity_is_rejected(
    family: str,
    required: int,
) -> None:
    counts = {candidate: 20 for candidate in _FAMILIES}
    counts[family] = required - 1
    shadow = _shadow_items_with_family_counts(counts)

    with pytest.raises(
        ValueError,
        match=rf"family {family!r}.*required {required}.*available {required - 1}",
    ):
        calibration_ruler.build_ruler(
            _fixture_items("trusted", 60),
            _fixture_items("failure", 60),
            shadow,
            seed=0,
        )


def test_unlabeled_inputs_do_not_require_human_labels() -> None:
    manifest = calibration_ruler.build_ruler(*_inputs(), seed=7)
    assert len(_primary(manifest)) == 120


def test_label_imbalance_is_rejected_when_labels_are_available() -> None:
    trusted = _fixture_items("trusted", 60)
    for item in trusted:
        item["human_label"] = "positive"
    with pytest.raises(ValueError, match="fewer than five"):
        calibration_ruler.build_ruler(
            trusted,
            _fixture_items("failure", 60),
            _fixture_items("shadow", 60),
        )


def test_balanced_human_labels_are_accepted() -> None:
    trusted = _fixture_items("trusted", 60)
    failures = _fixture_items("failure", 60)
    for item in trusted:
        item["human_label"] = "positive"
    for item in failures:
        item["human_label"] = "negative"
    manifest = calibration_ruler.build_ruler(
        trusted,
        failures,
        _fixture_items("shadow", 60),
        seed=7,
    )
    assert len(_primary(manifest)) == 120


def test_validate_manifest_accepts_a_built_ruler() -> None:
    manifest = calibration_ruler.build_ruler(*_inputs(), seed=7)
    calibration_ruler.validate_manifest(manifest)


def test_manifest_round_trip_is_stable_and_valid() -> None:
    manifest = calibration_ruler.build_ruler(*_inputs(), seed=7)
    restored = calibration_ruler.RulerManifest.from_dict(
        json.loads(json.dumps(manifest.to_dict(), ensure_ascii=False))
    )
    assert restored.to_dict() == manifest.to_dict()
    calibration_ruler.validate_manifest(restored)


def test_validate_manifest_detects_count_tampering() -> None:
    manifest = calibration_ruler.build_ruler(*_inputs(), seed=7)
    payload = manifest.to_dict()
    cast(list[object], payload["items"]).pop()
    tampered = calibration_ruler.RulerManifest.from_dict(payload)
    with pytest.raises(ValueError):
        calibration_ruler.validate_manifest(tampered)


def test_validate_manifest_rejects_adjacent_repeat_and_original() -> None:
    manifest = calibration_ruler.build_ruler(*_inputs(), seed=7)
    items = list(manifest.items)
    repeat = next(item for item in items if item.repeat_of is not None)
    items.remove(repeat)
    origin_index = next(
        index for index, item in enumerate(items) if item.review_id == repeat.repeat_of
    )
    items.insert(origin_index + 1, repeat)
    renamed = {
        item.review_id: f"item-{index:04d}" for index, item in enumerate(items, start=1)
    }
    tampered = calibration_ruler.RulerManifest(
        tuple(
            replace(
                item,
                review_id=renamed[item.review_id],
                repeat_of=renamed[item.repeat_of] if item.repeat_of else None,
            )
            for item in items
        ),
        manifest.seed,
    )

    with pytest.raises(ValueError, match="adjacent"):
        calibration_ruler.validate_manifest(tampered)


def test_validate_manifest_rejects_calibration_validation_hash_overlap() -> None:
    manifest = calibration_ruler.build_ruler(*_inputs(), seed=7)
    items = list(manifest.items)
    calibration_index, calibration_item = next(
        (index, item)
        for index, item in enumerate(items)
        if item.repeat_of is None
        and item.stratum == "trusted"
        and item.split == "calibration"
    )
    validation_item = next(
        item
        for item in items
        if item.repeat_of is None
        and item.stratum == "trusted"
        and item.split == "validation"
    )
    items[calibration_index] = replace(
        validation_item,
        review_id=calibration_item.review_id,
        split="calibration",
    )
    tampered = calibration_ruler.RulerManifest(tuple(items), manifest.seed)

    with pytest.raises(ValueError, match="split.*overlap"):
        calibration_ruler.validate_manifest(tampered)


def test_validate_manifest_rejects_shadow_family_count_tampering() -> None:
    manifest = calibration_ruler.build_ruler(*_inputs(), seed=7)
    items = list(manifest.items)
    expected = {family: 13 for family in sorted(_FAMILIES)}
    extra = sorted(_FAMILIES)[manifest.seed % len(_FAMILIES)]
    expected[extra] = 14
    replacement_family = next(
        family for family, count in expected.items() if count == 13
    )
    index, item = next(
        (index, item)
        for index, item in enumerate(items)
        if item.repeat_of is None
        and item.stratum == "shadow"
        and item.metadata["model_family"] == extra
    )
    items[index] = replace(
        item,
        metadata={**item.metadata, "model_family": replacement_family},
    )
    tampered = calibration_ruler.RulerManifest(tuple(items), manifest.seed)

    with pytest.raises(ValueError, match="shadow family counts"):
        calibration_ruler.validate_manifest(tampered)
