# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import FrozenInstanceError, replace
from pathlib import PurePosixPath
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
_ADVERSARIAL_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 40">\n'
    "<!-- SVG comment with a Markdown-looking payload -->\n"
    '<text x="1" y="12">### injected-heading\n'
    "your_answer: A\n"
    "---\n"
    "```injected-fence```\n"
    "&lt;!-- injected text comment --&gt;</text>\n"
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
    review_id = cast(str, over.pop("review_id", "item-0001"))
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
        review_id = f"item-{index + 1:04d}"
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
                repeat_of="item-0001" if is_repeat else None,
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


def test_pass_a_header_lists_allowed_values_without_prefilling_fields() -> None:
    block = calibration_sheet.render_blocks([_manifest_item()], pass_name="a")[0]
    header, _, item = block.partition("\n### ")

    expected_legend = (
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
    assert "## Allowed rubric values" in header
    assert all(legend in header for legend in expected_legend)
    assert all(f"{field}:" not in header for field in calibration_sheet.PASS_A_FIELDS)
    assert all(f"{field}:\n" in item for field in calibration_sheet.PASS_A_FIELDS)


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
        review_id="item-0042",
    )
    repeat = _manifest_item(
        id="p-hidden-1-repeat",
        stem=f'A wheel rotates.\n<div class="pg-figure">{_SVG}</div>',
        difficulty=0.937,
        **_HIDDEN_SENTINELS,
        stratum="shadow",
        split=None,
        repeat_of="item-0042",
        review_id="item-0043",
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
    assert "item-0042" in joined
    assert "item-0043" in joined


def test_identical_content_hashes_are_not_exposed_across_repeats() -> None:
    shared = _problem(id="p-shared")
    original = calibration_ruler.RulerItem.from_source_item(
        shared,
        review_id="item-0007",
        stratum="trusted",
        split="calibration",
    )
    repeat = calibration_ruler.RulerItem.from_source_item(
        shared,
        review_id="item-0008",
        stratum="trusted",
        split=None,
        repeat_of="item-0007",
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
    assert rendered.count("item-0007") >= 1
    assert rendered.count("item-0008") >= 1


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
    item = _manifest_item(stem=stem, choices=choices, review_id="item-0009")
    rendered = calibration_sheet.render_pass_a_block(item)
    assert "$E=mc^2$" in rendered
    assert "x &lt; y" in rendered
    # Exactly one item heading for this review id.
    assert rendered.count("\n### ") + (1 if rendered.startswith("### ") else 0) == 1
    assert "### item-0009" in rendered
    assert "### injected-heading" not in rendered
    # Rubric fields appear once each, unfilled.
    for field in calibration_sheet.PASS_A_FIELDS:
        assert rendered.count(f"{field}:") == 1
        assert f"{field}: " not in rendered


@pytest.mark.parametrize(
    "text",
    [
        "",
        "ordinary prose and $E=mc^2$",
        "\u200b",
        "existing\u200bzero-width\u200bspaces",
        "### heading\n```fence```\n---\n***\n___",
        "<!-- comment -->\nyour_answer: A\noverall: KEEP",
        "&amp; &#35; &unknown; x < y > z",
        "[x](../manifest.json)",
        "![x](../figures/secret.svg)",
        "<file:///etc/passwd>",
        "https://example.invalid/manifest.json",
        "[x][secret]\n[secret]: ../manifest.json",
        "\n".join(f"{field}: injected" for field in calibration_sheet.PASS_A_FIELDS),
    ],
)
def test_markdown_protection_round_trips_exactly(text: str) -> None:
    protected = calibration_sheet.protect_markdown_text(text)

    assert calibration_sheet.unprotect_markdown_text(protected) == text


def test_markdown_protection_has_no_injectable_contract_tokens() -> None:
    text = "### heading\n```fence```\n<!-- comment -->\n---\n" + "\n".join(
        f"{field}: injected" for field in calibration_sheet.PASS_A_FIELDS
    )
    protected = calibration_sheet.protect_markdown_text(text)

    assert "### " not in protected
    assert "```" not in protected
    assert "<!--" not in protected
    assert "\n---\n" not in protected
    assert all(
        f"{field}:" not in protected for field in calibration_sheet.PASS_A_FIELDS
    )


@pytest.mark.parametrize(
    "text",
    [
        "[x](../manifest.json)",
        "![x](../figures/secret.svg)",
        "<file:///etc/passwd>",
        "https://example.invalid/manifest.json",
        "[x][secret] [secret]: ../manifest.json",
    ],
)
def test_markdown_protection_neutralizes_links_images_and_autolinks(
    text: str,
) -> None:
    protected = calibration_sheet.protect_markdown_text(text)
    assert calibration_sheet.unprotect_markdown_text(protected) == text
    for token in ("[", "]", "(", ")", "!", "<", ">", "://", ".json"):
        assert token not in protected


def test_figure_is_linked_and_asset_bytes_are_identical() -> None:
    item = _manifest_item(
        stem=f'A wheel rotates.\n<div class="pg-figure">{_SVG}</div>',
        review_id="item-0010",
    )
    content = item.pass_a_content()
    assert content["figure"] == _SVG
    rendered = calibration_sheet.render_pass_a_block(item)
    assets = calibration_sheet.figure_assets([item])

    assert "![Figure](../figures/item-0010.svg)" in rendered
    assert "<svg" not in rendered.lower()
    assert "</svg>" not in rendered.lower()
    assert _SVG not in rendered
    assert assets == {"figures/item-0010.svg": _SVG.encode("utf-8")}
    visible = {**content, "figure": assets["figures/item-0010.svg"].decode("utf-8")}
    assert calibration_ruler.pass_a_hash(visible) == item.pass_a_hash


def test_repeats_receive_distinct_figure_asset_paths() -> None:
    shared = _problem(
        id="p-shared-figure",
        stem=f'A wheel rotates.\n<div class="pg-figure">{_SVG}</div>',
    )
    original = calibration_ruler.RulerItem.from_source_item(
        shared,
        review_id="item-0011",
        stratum="trusted",
        split="calibration",
    )
    repeat = calibration_ruler.RulerItem.from_source_item(
        shared,
        review_id="item-0012",
        stratum="trusted",
        split=None,
        repeat_of="item-0011",
    )

    assets = calibration_sheet.figure_assets([original, repeat])
    rendered = calibration_sheet.render_blocks(
        [original, repeat],
        pass_name="a",
    )[0]

    assert assets == {
        "figures/item-0011.svg": _SVG.encode("utf-8"),
        "figures/item-0012.svg": _SVG.encode("utf-8"),
    }
    assert "![Figure](../figures/item-0011.svg)" in rendered
    assert "![Figure](../figures/item-0012.svg)" in rendered
    assert original.content_hash not in rendered


@pytest.mark.parametrize(
    "review_id",
    [
        "/item-0001",
        "../item-0001",
        "item-0001/extra",
        r"item-0001\extra",
        "item 0001",
        "item-0001.svg",
        "ITEM-0001",
        "item-%2e%2e",
        "cal-0001",
        "rep-0001",
    ],
)
def test_unsafe_review_ids_are_rejected(review_id: str) -> None:
    item = _manifest_item(
        stem=f'A wheel rotates.\n<div class="pg-figure">{_SVG}</div>',
        review_id=review_id,
    )

    with pytest.raises(ValueError, match="safe review ID"):
        calibration_sheet.render_pass_a_block(item)
    with pytest.raises(ValueError, match="safe review ID"):
        calibration_sheet.figure_assets([item])


def test_duplicate_review_id_asset_collisions_are_rejected() -> None:
    first = _manifest_item(
        id="p-first",
        stem=f'First.\n<div class="pg-figure">{_SVG}</div>',
        review_id="item-0012",
    )
    second = _manifest_item(
        id="p-second",
        stem=f'Second.\n<div class="pg-figure">{_SVG}</div>',
        review_id="item-0012",
    )

    with pytest.raises(ValueError, match="duplicate review ID"):
        calibration_sheet.figure_assets([first, second])
    with pytest.raises(ValueError, match="duplicate review ID"):
        calibration_sheet.render_blocks([first, second], pass_name="a")
    with pytest.raises(ValueError, match="duplicate review ID"):
        calibration_sheet.render_index([first, second])


def test_adversarial_svg_is_only_an_image_line_in_markdown() -> None:
    items = [
        _manifest_item(
            id=f"p-svg-{index}",
            stem=(
                f'Inspect the figure.\n<div class="pg-figure">{_ADVERSARIAL_SVG}</div>'
            ),
            review_id=f"item-{index:04d}",
        )
        for index in range(1, 22)
    ]

    blocks = calibration_sheet.render_blocks(items, pass_name="a")
    assets = calibration_sheet.figure_assets(items)
    rendered = "\n".join(blocks)

    assert len(blocks) == 2
    assert [block.count("\n### ") for block in blocks] == [20, 1]
    assert [block.count("![Figure](") for block in blocks] == [20, 1]
    assert "<svg" not in rendered.lower()
    assert "### injected-heading" not in rendered
    assert "your_answer: A" not in rendered
    assert "```injected-fence```" not in rendered
    assert "<!-- SVG comment" not in rendered
    assert assets["figures/item-0001.svg"] == _ADVERSARIAL_SVG.encode("utf-8")


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
    assert "item-0001" in blocks[0]
    assert "item-0021" in blocks[1]


def test_render_blocks_rejects_unknown_pass_name() -> None:
    with pytest.raises(ValueError, match="pass_name"):
        calibration_sheet.render_blocks([_manifest_item()], pass_name="b")


# --- Task 4: strict Pass A parsing and repeat consistency -------------------

_PASS_A_VALUES = {
    "your_answer": "B",
    "stem_clear": "PASS",
    "distractor_A": "VALID",
    "distractor_B": "CORRECT_ANSWER",
    "distractor_C": "INVALID",
    "distractor_D": "UNSURE",
    "distractor_E": "VALID",
    "figure": "MATCHES",
    "difficulty": "3",
    "overall": "KEEP",
}
_CATEGORICAL_FIELDS = {
    "stem_clear",
    "distractor_A",
    "distractor_B",
    "distractor_C",
    "distractor_D",
    "distractor_E",
    "figure",
    "difficulty",
    "overall",
}


def _ruler_source(stratum: str, index: int) -> dict[str, object]:
    categories = tuple(sorted(calibration_ruler.BLUEPRINT_CATEGORIES))
    category = categories[index % len(categories)]
    stem = f"Café configuration #{index}: apply {category} principles."
    if index % 3 == 0:
        stem += f'<div class="pg-figure">{_SVG}</div>'
    item: dict[str, object] = {
        "id": f"{stratum}-{index}",
        "topic": f"topic::{category}",
        "blueprint_category": category,
        "kind": ("conceptual", "computational", "unspecified")[index % 3],
        "difficulty": (0.1, 0.5, 0.9)[index % 3],
        "stem": stem,
        "choices": [
            f"{stratum}-{index}-A",
            f"{stratum}-{index}-B",
            f"{stratum}-{index}-C",
            f"{stratum}-{index}-D",
            f"{stratum}-{index}-E",
        ],
        "correct": "ABCDE"[index % 5],
        "source_ref": f"OpenStax {stratum} chapter {index}",
        "source_excerpt": f"Grounding excerpt {stratum} {index}.",
        "solution_decomposition": [
            {"subgoal": f"Reason about {category}.", "rubric": "Name the law."}
        ],
    }
    if stratum == "shadow":
        item["model_family"] = ("sol", "opus", "grok")[index % 3]
    return item


def _strict_manifest() -> calibration_ruler.RulerManifest:
    return calibration_ruler.build_ruler(
        [_ruler_source("trusted", index) for index in range(60)],
        [_ruler_source("failure", index) for index in range(60)],
        [_ruler_source("shadow", index) for index in range(60)],
        seed=7,
    )


def _filled_documents(
    manifest: calibration_ruler.RulerManifest,
) -> list[str]:
    documents = calibration_sheet.render_blocks(manifest, pass_name="a")
    for index, document in enumerate(documents):
        for field, value in _PASS_A_VALUES.items():
            document = document.replace(
                f"\n{field}:\n",
                f"\n{field}: {value}\n",
            )
        documents[index] = document
    return documents


@pytest.fixture(scope="module")
def strict_case() -> tuple[
    calibration_ruler.RulerManifest,
    list[str],
    dict[str, bytes],
]:
    manifest = _strict_manifest()
    return (
        manifest,
        _filled_documents(manifest),
        calibration_sheet.figure_assets(manifest),
    )


@pytest.fixture(scope="module")
def parsed_labels(
    strict_case: tuple[
        calibration_ruler.RulerManifest,
        list[str],
        dict[str, bytes],
    ],
) -> dict[str, calibration_sheet.PassALabel]:
    manifest, documents, assets = strict_case
    return calibration_sheet.parse_pass_a(
        documents,
        manifest=manifest,
        assets=assets,
    )


def _review_span(document: str, review_id: str) -> tuple[int, int]:
    start = document.index(f"### {review_id}\n")
    end = document.index("\n---\n", start) + len("\n---\n")
    return start, end


def _replace_in_review(
    documents: list[str],
    review_id: str,
    old: str,
    new: str,
) -> list[str]:
    changed = list(documents)
    for index, document in enumerate(changed):
        if f"### {review_id}\n" not in document:
            continue
        start, end = _review_span(document, review_id)
        block = document[start:end]
        assert block.count(old) == 1
        changed[index] = document[:start] + block.replace(old, new, 1) + document[end:]
        return changed
    raise AssertionError(f"review ID not found in fixture: {review_id}")


def _item_with_figure(
    manifest: calibration_ruler.RulerManifest,
) -> calibration_ruler.RulerItem:
    return next(item for item in manifest.items if item.figure)


def test_pass_a_round_trip_requires_all_documents_and_assets(
    strict_case: tuple[
        calibration_ruler.RulerManifest,
        list[str],
        dict[str, bytes],
    ],
) -> None:
    manifest, documents, assets = strict_case

    labels = calibration_sheet.parse_pass_a(
        documents,
        manifest=manifest,
        assets=assets,
    )

    assert list(labels) == [item.review_id for item in manifest.items]
    assert labels["item-0001"].your_answer == "B"
    assert labels["item-0001"].overall == "KEEP"
    assert labels["item-0001"].notes == ""
    calibration_sheet.validate_pass_a_complete(labels, manifest=manifest)


def test_pass_a_value_sets_are_exact_and_frozen() -> None:
    assert calibration_sheet.ANSWERS == frozenset({"A", "B", "C", "D", "E", "UNSURE"})
    assert calibration_sheet.PASS_FAIL == frozenset({"PASS", "FAIL", "UNSURE"})
    assert calibration_sheet.DISTRACTOR == frozenset(
        {"VALID", "INVALID", "CORRECT_ANSWER", "UNSURE"}
    )
    assert calibration_sheet.FIGURE == frozenset(
        {"MATCHES", "CONTRADICTS", "UNNECESSARY", "MISSING", "N_A", "UNSURE"}
    )
    assert calibration_sheet.DIFFICULTY == frozenset(
        {"1", "2", "3", "4", "5", "UNSURE"}
    )
    assert calibration_sheet.OVERALL == frozenset({"KEEP", "DROP", "UNSURE"})


def _invalid_documents(  # noqa: PLR0911
    mutation: str,
    manifest: calibration_ruler.RulerManifest,
    documents: list[str],
) -> list[str]:
    first = manifest.items[0].review_id
    second = manifest.items[1].review_id
    if mutation == "missing_field":
        return _replace_in_review(
            documents,
            first,
            "stem_clear: PASS\n",
            "",
        )
    if mutation == "blank_field":
        return _replace_in_review(
            documents,
            first,
            "your_answer: B",
            "your_answer:",
        )
    if mutation == "unknown_label":
        return _replace_in_review(
            documents,
            first,
            "overall: KEEP",
            "overall: keep",
        )
    if mutation == "edited_stem":
        stem = calibration_sheet.protect_markdown_text(manifest.items[0].stem)
        return _replace_in_review(documents, first, stem, stem + " edited")
    if mutation == "edited_choice":
        choice = calibration_sheet.protect_markdown_text(manifest.items[0].choices[0])
        return _replace_in_review(documents, first, choice, choice + " edited")
    if mutation == "duplicate_id":
        return _replace_in_review(
            documents,
            second,
            f"### {second}",
            f"### {first}",
        )
    if mutation == "extra_id":
        return _replace_in_review(
            documents,
            second,
            f"### {second}",
            "### item-9999",
        )
    if mutation == "heading_injection":
        stem = calibration_sheet.protect_markdown_text(manifest.items[0].stem)
        return _replace_in_review(
            documents,
            first,
            stem,
            stem + "\n### injected-heading",
        )
    if mutation == "separator_injection":
        return _replace_in_review(
            documents,
            first,
            "stem_clear: PASS",
            "---\nstem_clear: PASS",
        )
    if mutation == "duplicate_field":
        return _replace_in_review(
            documents,
            first,
            "stem_clear: PASS",
            "stem_clear: PASS\nstem_clear: PASS",
        )
    if mutation == "hidden_metadata":
        return _replace_in_review(
            documents,
            first,
            "overall: KEEP",
            "model_family: sol\noverall: KEEP",
        )
    if mutation == "filled_legend":
        changed = list(documents)
        changed[0] = changed[0].replace(
            "`your_answer` = `A`, `B`, `C`, `D`, `E`, or `UNSURE`",
            "`your_answer` = `B`",
            1,
        )
        return changed
    if mutation == "truncated_block":
        changed = list(documents)
        last = manifest.items[-1].review_id
        start, _ = _review_span(changed[-1], last)
        changed[-1] = changed[-1][:start]
        return changed
    if mutation == "extra_block":
        return [*documents, documents[0]]
    if mutation == "changed_figure_reference":
        figure_item = _item_with_figure(manifest)
        review_id = figure_item.review_id
        return _replace_in_review(
            documents,
            review_id,
            f"![Figure](../figures/{review_id}.svg)",
            "![Figure](../figures/item-9999.svg)",
        )
    if mutation == "unicode_tampering":
        stem = calibration_sheet.protect_markdown_text(manifest.items[0].stem)
        assert "é" in stem
        return _replace_in_review(
            documents,
            first,
            stem,
            stem.replace("é", "e\u0301", 1),
        )
    if mutation == "protection_tampering":
        stem = calibration_sheet.protect_markdown_text(manifest.items[0].stem)
        assert "&#35;" in stem
        return _replace_in_review(
            documents,
            first,
            stem,
            stem.replace("&#35;", "&#x23;", 1),
        )
    raise AssertionError(f"unknown mutation: {mutation}")


@pytest.mark.parametrize(
    ("mutation", "message", "error_type"),
    [
        ("missing_field", "incomplete.*stem_clear", "schema"),
        ("blank_field", "incomplete.*your_answer", "reviewer"),
        ("unknown_label", "unknown value.*overall", "reviewer"),
        ("edited_stem", "immutable content.*stem", "schema"),
        ("edited_choice", "immutable content.*choice A", "schema"),
        ("duplicate_id", "duplicate review ID", "schema"),
        ("extra_id", "unexpected review ID", "schema"),
        ("heading_injection", "unexpected review ID", "schema"),
        ("separator_injection", "separator", "schema"),
        ("duplicate_field", "duplicate field.*stem_clear", "schema"),
        ("hidden_metadata", "hidden metadata.*model_family", "schema"),
        ("filled_legend", "header", "schema"),
        ("truncated_block", "missing review ID", "schema"),
        ("extra_block", "document count", "schema"),
        ("changed_figure_reference", "changed figure reference", "schema"),
        ("unicode_tampering", "immutable content.*stem", "schema"),
        ("protection_tampering", "protection tampering.*stem", "schema"),
    ],
)
def test_pass_a_rejects_any_non_renderer_or_invalid_reviewer_edit(
    mutation: str,
    message: str,
    error_type: str,
    strict_case: tuple[
        calibration_ruler.RulerManifest,
        list[str],
        dict[str, bytes],
    ],
) -> None:
    manifest, documents, assets = strict_case
    expected_error = (
        calibration_sheet.ReviewerEditError
        if error_type == "reviewer"
        else calibration_sheet.RendererSchemaError
    )

    with pytest.raises(expected_error, match=message):
        calibration_sheet.parse_pass_a(
            _invalid_documents(mutation, manifest, documents),
            manifest=manifest,
            assets=assets,
        )


class _CollisionAssets(Mapping[str, bytes]):
    def __init__(self, values: dict[str, bytes]) -> None:
        self._values = values
        self._duplicate = next(iter(values))

    def __getitem__(self, key: str) -> bytes:
        return self._values[key]

    def __iter__(self):
        return iter([*self._values, self._duplicate])

    def __len__(self) -> int:
        return len(self._values) + 1


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("missing", "missing asset"),
        ("extra", "extra asset"),
        ("changed_bytes", "asset bytes/hash mismatch"),
        ("invalid_utf8", "strict UTF-8"),
        ("path_key", "asset mapping keys"),
        ("non_bytes", "raw bytes"),
        ("collision", "asset path collision"),
    ],
)
def test_pass_a_rejects_any_asset_mapping_drift(
    mutation: str,
    message: str,
    strict_case: tuple[
        calibration_ruler.RulerManifest,
        list[str],
        dict[str, bytes],
    ],
) -> None:
    manifest, documents, expected_assets = strict_case
    assets: Mapping[str, bytes]
    changed: dict[object, object] = {}
    for expected_path, expected_raw in expected_assets.items():
        changed[expected_path] = expected_raw
    path = next(iter(expected_assets))
    if mutation == "missing":
        changed.pop(path)
        assets = cast(Mapping[str, bytes], changed)
    elif mutation == "extra":
        changed["figures/item-9999.svg"] = _SVG.encode("utf-8")
        assets = cast(Mapping[str, bytes], changed)
    elif mutation == "changed_bytes":
        changed[path] = expected_assets[path].replace(b"19 19", b"18 18")
        assets = cast(Mapping[str, bytes], changed)
    elif mutation == "invalid_utf8":
        changed[path] = b"\xff"
        assets = cast(Mapping[str, bytes], changed)
    elif mutation == "path_key":
        raw = changed.pop(path)
        changed[PurePosixPath(path)] = raw
        assets = cast(Mapping[str, bytes], changed)
    elif mutation == "non_bytes":
        changed[path] = PurePosixPath("figure.svg")
        assets = cast(Mapping[str, bytes], changed)
    elif mutation == "collision":
        assets = _CollisionAssets(expected_assets)
    else:
        raise AssertionError(f"unknown asset mutation: {mutation}")

    with pytest.raises(calibration_sheet.RendererSchemaError, match=message):
        calibration_sheet.parse_pass_a(
            documents,
            manifest=manifest,
            assets=assets,
        )


def test_pass_a_label_is_frozen_and_json_safe(
    parsed_labels: dict[str, calibration_sheet.PassALabel],
) -> None:
    label = next(iter(parsed_labels.values()))

    with pytest.raises(FrozenInstanceError):
        setattr(label, "overall", "DROP")
    payload = {review_id: value.to_dict() for review_id, value in parsed_labels.items()}
    assert set(label.to_dict()) == set(calibration_sheet.PASS_A_FIELDS)
    assert (
        json.loads(json.dumps(payload, ensure_ascii=False, allow_nan=False)) == payload
    )


def test_missing_no_figure_rubric_raises_actionable_schema_error() -> None:
    item = _manifest_item(review_id="item-0001")
    cursor = calibration_sheet._LineCursor(lines=[], document_number=3)

    with pytest.raises(
        calibration_sheet.RendererSchemaError,
        match=r"document 3.*truncated.*item-0001.*figure or rubric",
    ):
        calibration_sheet._parse_figure_reference(
            cursor,
            item,
            "item-0001",
            {},
        )


def test_notes_are_bounded_and_cannot_create_structured_metadata(
    strict_case: tuple[
        calibration_ruler.RulerManifest,
        list[str],
        dict[str, bytes],
    ],
) -> None:
    manifest, documents, assets = strict_case
    review_id = manifest.items[0].review_id
    safe_note = "model_family: remains plain reviewer prose"
    with_note = _replace_in_review(
        documents,
        review_id,
        "notes:",
        f"notes: {safe_note}",
    )

    labels = calibration_sheet.parse_pass_a(
        with_note,
        manifest=manifest,
        assets=assets,
    )

    assert labels[review_id].notes == safe_note
    assert set(labels[review_id].to_dict()) == set(calibration_sheet.PASS_A_FIELDS)
    too_long = _replace_in_review(
        documents,
        review_id,
        "notes:",
        f"notes: {'x' * (calibration_sheet.MAX_NOTES_LENGTH + 1)}",
    )
    with pytest.raises(
        calibration_sheet.ReviewerEditError,
        match="notes.*at most",
    ):
        calibration_sheet.parse_pass_a(
            too_long,
            manifest=manifest,
            assets=assets,
        )


@pytest.mark.parametrize(
    "note",
    [
        "first line\nsecond line",
        "contains\ta tab",
        "contains a control \x00 character",
        "contains a zero-width\u200bspace",
        "contains a line\u2028separator",
        "contains a paragraph\u2029separator",
    ],
    ids=[
        "newline",
        "tab",
        "control",
        "zero-width-space",
        "line-separator",
        "paragraph-separator",
    ],
)
def test_notes_reject_nonordinary_or_multiline_unicode(
    note: str,
    parsed_labels: dict[str, calibration_sheet.PassALabel],
) -> None:
    label = next(iter(parsed_labels.values()))

    with pytest.raises(
        calibration_sheet.ReviewerEditError,
        match="notes must be one line of ordinary Unicode",
    ):
        replace(label, notes=note)


def test_notes_accept_ordinary_unicode(
    parsed_labels: dict[str, calibration_sheet.PassALabel],
) -> None:
    label = next(iter(parsed_labels.values()))
    note = "Café ΔE = 2 μJ; 中文说明; 🙂"

    updated = replace(label, notes=note)

    assert updated.notes == note
    assert (
        json.loads(json.dumps(updated.to_dict(), ensure_ascii=False))["notes"] == note
    )


def test_validate_pass_a_complete_rejects_missing_label(
    strict_case: tuple[
        calibration_ruler.RulerManifest,
        list[str],
        dict[str, bytes],
    ],
    parsed_labels: dict[str, calibration_sheet.PassALabel],
) -> None:
    manifest, _, _ = strict_case
    incomplete = dict(parsed_labels)
    incomplete.pop(next(iter(incomplete)))

    with pytest.raises(calibration_sheet.ReviewerEditError, match="incomplete"):
        calibration_sheet.validate_pass_a_complete(incomplete, manifest=manifest)


def _changed_repeats(
    labels: dict[str, calibration_sheet.PassALabel],
    manifest: calibration_ruler.RulerManifest,
    *,
    field: str,
    count: int,
    value: str,
) -> dict[str, calibration_sheet.PassALabel]:
    changed = dict(labels)
    repeats = [item for item in manifest.items if item.repeat_of is not None]
    for item in repeats[:count]:
        review_id = item.review_id
        changed[review_id] = replace(changed[review_id], **{field: value})
    return changed


def test_repeat_consistency_uses_private_pairs_and_excludes_repeat_support(
    strict_case: tuple[
        calibration_ruler.RulerManifest,
        list[str],
        dict[str, bytes],
    ],
    parsed_labels: dict[str, calibration_sheet.PassALabel],
) -> None:
    manifest, _, _ = strict_case
    labels = dict(parsed_labels)
    repeat = next(item for item in manifest.items if item.repeat_of is not None)
    repeat_id = repeat.review_id
    origin_id = repeat.repeat_of
    labels[repeat_id] = replace(labels[repeat_id], your_answer="C")
    labels[origin_id] = replace(labels[origin_id], your_answer="C")

    report = calibration_sheet.repeat_consistency(labels, manifest)

    assert report["repeat_count"] == 12
    assert report["split_support"] == {
        "calibration": 80,
        "validation": 40,
        "total": 120,
    }
    assert report["exact_answer"] == {
        "matches": 12,
        "total": 12,
        "raw_agreement": 1.0,
    }
    assert set(cast(dict[str, object], report["categorical_fields"])) == (
        _CATEGORICAL_FIELDS
    )


def test_consistency_gate_has_separate_answer_and_categorical_floors(
    strict_case: tuple[
        calibration_ruler.RulerManifest,
        list[str],
        dict[str, bytes],
    ],
    parsed_labels: dict[str, calibration_sheet.PassALabel],
) -> None:
    manifest, _, _ = strict_case
    answer_floor = _changed_repeats(
        parsed_labels,
        manifest,
        field="your_answer",
        count=1,
        value="C",
    )
    answer_fail = _changed_repeats(
        parsed_labels,
        manifest,
        field="your_answer",
        count=2,
        value="C",
    )
    categorical_floor = _changed_repeats(
        parsed_labels,
        manifest,
        field="overall",
        count=1,
        value="DROP",
    )
    categorical_fail = _changed_repeats(
        parsed_labels,
        manifest,
        field="overall",
        count=2,
        value="DROP",
    )

    assert calibration_sheet.consistency_gate(
        calibration_sheet.repeat_consistency(answer_floor, manifest)
    )["passed"]
    assert not calibration_sheet.consistency_gate(
        calibration_sheet.repeat_consistency(answer_fail, manifest)
    )["passed"]
    assert calibration_sheet.consistency_gate(
        calibration_sheet.repeat_consistency(categorical_floor, manifest)
    )["passed"]
    failed = calibration_sheet.consistency_gate(
        calibration_sheet.repeat_consistency(categorical_fail, manifest)
    )
    assert failed["status"] == "ADJUDICATION_REQUIRED"
    assert failed["failed_checks"] == ["overall"]
    assert parsed_labels[next(iter(parsed_labels))].overall == "KEEP"


def test_repeat_content_must_match_before_labels_are_compared(
    strict_case: tuple[
        calibration_ruler.RulerManifest,
        list[str],
        dict[str, bytes],
    ],
    parsed_labels: dict[str, calibration_sheet.PassALabel],
) -> None:
    manifest, _, _ = strict_case
    items = list(manifest.items)
    repeat_index = next(
        index for index, item in enumerate(items) if item.repeat_of is not None
    )
    repeat = items[repeat_index]
    wrong_origin = next(
        item
        for item in items
        if item.repeat_of is None
        and item.review_id != repeat.repeat_of
        and item.content_hash != repeat.content_hash
    )
    items[repeat_index] = replace(
        repeat,
        repeat_of=wrong_origin.review_id,
    )
    invalid_manifest = replace(manifest, items=tuple(items))

    with pytest.raises(
        calibration_sheet.RendererSchemaError,
        match="content does not match",
    ):
        calibration_sheet.repeat_consistency(parsed_labels, invalid_manifest)
