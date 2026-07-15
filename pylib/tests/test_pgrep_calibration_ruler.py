# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

from __future__ import annotations

import hashlib
import json
import math
from copy import deepcopy
from typing import cast

import pytest

from anki.pgrep.ai import calibration_ruler

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


def test_bundle_source_ref_is_the_excerpt_fallback() -> None:
    item = _problem()
    del item["source_excerpt"]

    canonical = calibration_ruler.canonical_problem(item)

    assert canonical["source_excerpt"] == "OpenStax, p. 1"
    assert calibration_ruler.pass_b_hash(item) == calibration_ruler.pass_b_hash(
        {
            "source_excerpt": "OpenStax, p. 1",
            "solution_decomposition": item["solution_decomposition"],
        }
    )


def test_embedded_bundle_figure_is_extracted_without_rewriting_svg() -> None:
    item = _problem(
        stem=f'  A wheel rotates. \n<div class="pg-figure">\n{_SVG}\n</div> '
    )
    original = deepcopy(item)

    canonical = calibration_ruler.canonical_problem(item)

    assert canonical["stem"] == "A wheel rotates."
    assert canonical["figure"] == _SVG
    assert item == original


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
        _problem(kind="problem"),
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
    "marker",
    [
        "gold",
        "content/gold/problems/item.json",
        r"content\GOLD\problems\item.json",
        "gold-set/item",
        "gold.items/item",
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
def test_private_markers_and_path_variants_are_rejected_recursively(
    marker: str,
) -> None:
    with pytest.raises(ValueError, match="private marker"):
        calibration_ruler.validate_source_item(
            _problem(verifier={"nested": [{"path": marker}]})
        )


def test_private_markers_are_rejected_in_nested_keys() -> None:
    with pytest.raises(ValueError, match=r"\$\.verifier\.gold_path.*private marker"):
        calibration_ruler.validate_source_item(
            _problem(verifier={"gold_path": "hidden"})
        )


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
        review_id="cal-0001",
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


@pytest.mark.parametrize("hash_field", ["content_hash", "pass_a_hash", "pass_b_hash"])
def test_ruler_item_round_trip_rejects_tampered_hash(hash_field: str) -> None:
    payload = calibration_ruler.RulerItem.from_source_item(_problem()).to_dict()
    payload[hash_field] = "0" * 64

    with pytest.raises(ValueError, match=hash_field):
        calibration_ruler.RulerItem.from_dict(payload)
