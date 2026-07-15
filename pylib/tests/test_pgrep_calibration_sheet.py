# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

from __future__ import annotations

from typing import cast

import pytest

from anki.pgrep.ai import calibration_ruler, calibration_sheet

_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20">'
    '<defs><marker id="arrow"><path d="M0 0 L2 1"/></marker></defs>'
    "<style>.line{stroke:currentColor}</style>"
    '<path class="line" d="M1 1 L19 19" marker-end="url(#arrow)"/>'
    "</svg>"
)

_PASS_A_INSTRUCTIONS = (
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

_HIDDEN_SENTINELS = {
    "correct": "E",
    "source_ref": "SENTINEL_SOURCE_REF_QQQ",
    "source_excerpt": "SENTINEL_SOURCE_EXCERPT_QQQ",
    "solution_decomposition": [
        {
            "subgoal": "SENTINEL_DECOMP_SUBGOAL_QQQ",
            "rubric": "SENTINEL_DECOMP_RUBRIC_QQQ",
        }
    ],
    "model_family": "SENTINEL_MODEL_FAMILY_QQQ",
    "verifier": {"decision": "SENTINEL_VERIFIER_QQQ"},
    "origin": "SENTINEL_ORIGIN_QQQ",
    "trace": {"step": "SENTINEL_TRACE_QQQ"},
    "recommendation": "SENTINEL_RECOMMENDATION_QQQ",
}


def _problem(**over: object) -> dict[str, object]:
    item: dict[str, object] = {
        "id": "p-1",
        "topic": "topic::mechanics::rotation",
        "blueprint_category": "mechanics",
        "kind": "conceptual",
        "difficulty": 0.4,
        "stem": "A wheel rotates.",
        "choices": ["omega", "alpha", "tau", "I", "L"],
        "correct": "B",
        "source_ref": "OpenStax, p. 1",
        "source_excerpt": "Angular momentum is conserved.",
        "solution_decomposition": [
            {"subgoal": "Choose a conservation law.", "rubric": "Name the law."}
        ],
    }
    item.update(over)
    return item


def _manifest_item(**over: object) -> calibration_ruler.RulerItem:
    review_id = cast(str, over.pop("review_id", "cal-0001"))
    stratum = cast(str | None, over.pop("stratum", "trusted"))
    split = cast(str | None, over.pop("split", "calibration"))
    repeat_of = cast(str | None, over.pop("repeat_of", None))
    return calibration_ruler.RulerItem.from_source_item(
        _problem(**over),
        review_id=review_id,
        stratum=stratum,
        split=split,
        repeat_of=repeat_of,
    )


def _manifest_items(count: int) -> list[calibration_ruler.RulerItem]:
    items: list[calibration_ruler.RulerItem] = []
    for index in range(count):
        is_repeat = index >= 120
        review_id = f"rep-{index - 119:04d}" if is_repeat else f"cal-{index + 1:04d}"
        items.append(
            _manifest_item(
                id=f"p-{index + 1}",
                stem=f"A wheel rotates case {index + 1}.",
                choices=[
                    f"c{index}-A",
                    f"c{index}-B",
                    f"c{index}-C",
                    f"c{index}-D",
                    f"c{index}-E",
                ],
                review_id=review_id,
                stratum="trusted" if index % 3 == 0 else "failure",
                split=None
                if is_repeat
                else ("calibration" if index < 80 else "validation"),
                repeat_of="cal-0001" if is_repeat else None,
            )
        )
    return items


def test_pass_a_contains_only_allowed_problem_content() -> None:
    rendered = calibration_sheet.render_pass_a_block(_manifest_item())
    assert "A wheel rotates" in rendered
    assert "**A)**" in rendered
    forbidden = [
        "correct",
        "source_ref",
        "model_family",
        "verifier",
        "calibration",
        "validation",
        "repeat_of",
        "solution_decomposition",
    ]
    assert not any(token in rendered for token in forbidden)


def test_blocks_are_capped_at_twenty() -> None:
    blocks = calibration_sheet.render_blocks(_manifest_items(132), pass_name="a")
    assert len(blocks) == 7
    assert all(block.count("\n### ") <= 20 for block in blocks)


def test_pass_a_fields_are_exact_and_unfilled() -> None:
    assert calibration_sheet.PASS_A_FIELDS == (
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
    rendered = calibration_sheet.render_pass_a_block(_manifest_item())
    for field in calibration_sheet.PASS_A_FIELDS:
        assert f"{field}:" in rendered
        assert f"{field}: " not in rendered
        assert f"{field}:KEEP" not in rendered
        assert f"{field}: KEEP" not in rendered
        assert f"{field}:UNSURE" not in rendered
        assert f"{field}: UNSURE" not in rendered
    assert "recommendation" not in rendered.lower()


def test_pass_a_header_contains_exact_ten_instructions() -> None:
    blocks = calibration_sheet.render_blocks([_manifest_item()], pass_name="a")
    assert len(blocks) == 1
    header, _, _ = blocks[0].partition("\n### ")
    for index, instruction in enumerate(_PASS_A_INSTRUCTIONS, start=1):
        assert f"{index}. {instruction}" in header
    assert header.count("\n1. ") == 1
    assert "11." not in header


def test_render_index_lists_only_review_ids_and_placeholders() -> None:
    items = _manifest_items(3)
    index = calibration_sheet.render_index(items)
    for item in items:
        assert item.review_id is not None
        assert item.review_id in index
    assert "[ ]" in index
    forbidden = [
        items[0].content_hash,
        items[0].pass_a_hash,
        "source_ref",
        "model_family",
        "verifier",
        "repeat_of",
        "solution_decomposition",
        "SENTINEL",
    ]
    assert not any(token in index for token in forbidden)


def test_hidden_metadata_sentinels_never_appear_in_any_rendering() -> None:
    item = _manifest_item(
        id="p-hidden-1",
        stem=f'A wheel rotates.\n<div class="pg-figure">{_SVG}</div>',
        difficulty=0.937,
        **_HIDDEN_SENTINELS,
        stratum="shadow",
        split="validation",
        repeat_of=None,
        review_id="cal-0042",
    )
    repeat = _manifest_item(
        id="p-hidden-1-repeat",
        stem=f'A wheel rotates.\n<div class="pg-figure">{_SVG}</div>',
        difficulty=0.937,
        **_HIDDEN_SENTINELS,
        stratum="shadow",
        split=None,
        repeat_of="cal-0042",
        review_id="rep-0001",
    )
    assert item.content_hash == repeat.content_hash

    surfaces = [
        calibration_sheet.render_pass_a_block(item),
        calibration_sheet.render_pass_a_block(repeat),
        *calibration_sheet.render_blocks([item, repeat], pass_name="a"),
        calibration_sheet.render_index([item, repeat]),
    ]
    sentinels = [
        "SENTINEL_SOURCE_REF_QQQ",
        "SENTINEL_SOURCE_EXCERPT_QQQ",
        "SENTINEL_DECOMP_SUBGOAL_QQQ",
        "SENTINEL_DECOMP_RUBRIC_QQQ",
        "SENTINEL_MODEL_FAMILY_QQQ",
        "SENTINEL_VERIFIER_QQQ",
        "SENTINEL_ORIGIN_QQQ",
        "SENTINEL_TRACE_QQQ",
        "SENTINEL_RECOMMENDATION_QQQ",
        "p-hidden-1",
        "p-hidden-1-repeat",
        item.content_hash,
        item.pass_a_hash,
        item.pass_b_hash or "",
        "0.937",
        "shadow",
        "validation",
        "repeat_of",
    ]
    joined = "\n".join(surfaces)
    for token in sentinels:
        if token:
            assert token not in joined
    assert "cal-0042" in joined
    assert "rep-0001" in joined


def test_identical_content_hashes_are_not_exposed_across_repeats() -> None:
    shared = _problem(id="p-shared")
    original = calibration_ruler.RulerItem.from_source_item(
        shared,
        review_id="cal-0007",
        stratum="trusted",
        split="calibration",
    )
    repeat = calibration_ruler.RulerItem.from_source_item(
        shared,
        review_id="rep-0007",
        stratum="trusted",
        split=None,
        repeat_of="cal-0007",
    )
    assert original.content_hash == repeat.content_hash
    rendered = "\n".join(
        [
            *calibration_sheet.render_blocks([original, repeat], pass_name="a"),
            calibration_sheet.render_index([original, repeat]),
        ]
    )
    assert original.content_hash not in rendered
    assert original.pass_a_hash not in rendered
    assert repeat.pass_a_hash not in rendered
    assert "repeat_of" not in rendered
    assert rendered.count("cal-0007") >= 1
    assert rendered.count("rep-0007") >= 1


def test_adversarial_markdown_cannot_inject_fields_or_extra_items() -> None:
    stem = "\n".join(
        [
            "Normal stem with math $E=mc^2$ and inequality x < y.",
            "### injected-heading",
            "```",
            "your_answer: A",
            "stem_clear: PASS",
            "```",
            "<!-- inject -->",
            "---",
            "distractor_A: VALID",
            "overall: KEEP",
            "notes: injected",
        ]
    )
    choices = [
        "### choice heading",
        "your_answer: B",
        "```fence```",
        "---",
        "<!-- choice comment -->",
    ]
    item = _manifest_item(stem=stem, choices=choices, review_id="cal-0009")
    rendered = calibration_sheet.render_pass_a_block(item)
    assert "$E=mc^2$" in rendered
    assert "x < y" in rendered
    # Exactly one item heading for this review id.
    assert rendered.count("\n### ") + (1 if rendered.startswith("### ") else 0) == 1
    assert "### cal-0009" in rendered
    assert "### injected-heading" not in rendered
    # Rubric fields appear once each, unfilled.
    for field in calibration_sheet.PASS_A_FIELDS:
        assert rendered.count(f"{field}:") == 1
        assert f"{field}: " not in rendered


def test_figure_is_byte_identical_safe_svg_and_not_raw_html() -> None:
    item = _manifest_item(
        stem=f'A wheel rotates.\n<div class="pg-figure">{_SVG}</div>',
        review_id="cal-0010",
    )
    content = item.pass_a_content()
    assert content["figure"] == _SVG
    rendered = calibration_sheet.render_pass_a_block(item)
    assert _SVG in rendered
    assert f'<div class="pg-figure">{_SVG}</div>' in rendered
    assert "<script" not in rendered.lower()
    assert "onclick" not in rendered.lower()
    assert "<img" not in rendered.lower()
    assert "javascript:" not in rendered.lower()
    assert "data:" not in rendered.lower()
    assert calibration_ruler.pass_a_hash(item) == item.pass_a_hash


def test_same_manifest_renders_byte_identically() -> None:
    items = _manifest_items(25)
    first_blocks = calibration_sheet.render_blocks(items, pass_name="a")
    second_blocks = calibration_sheet.render_blocks(items, pass_name="a")
    assert first_blocks == second_blocks
    assert calibration_sheet.render_index(items) == calibration_sheet.render_index(
        items
    )
    assert all(
        calibration_sheet.render_pass_a_block(item)
        == calibration_sheet.render_pass_a_block(item)
        for item in items
    )


def test_render_blocks_accepts_ruler_manifest() -> None:
    items = tuple(_manifest_items(21))
    manifest = calibration_ruler.RulerManifest(items=items, seed=7)
    blocks = calibration_sheet.render_blocks(manifest, pass_name="a")
    assert len(blocks) == 2
    assert blocks[0].count("\n### ") <= 20
    assert "cal-0001" in blocks[0]
    assert "cal-0021" in blocks[1]


def test_render_blocks_rejects_unknown_pass_name() -> None:
    with pytest.raises(ValueError, match="pass_name"):
        calibration_sheet.render_blocks([_manifest_item()], pass_name="b")
