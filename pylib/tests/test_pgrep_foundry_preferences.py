# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

TOOLS_DIR = Path(__file__).parents[2] / "content" / "tools"
sys.path.insert(0, str(TOOLS_DIR))

import foundry  # type: ignore[import-not-found]  # noqa: E402
import leakage_check  # type: ignore[import-not-found]  # noqa: E402


def _valid_pair() -> dict:
    return {
        "schema": 1,
        "slot": {"topic": "optics", "blueprint_category": "optics"},
        "chosen": {
            "id": "candidate-1",
            "stem": "chosen stem",
            "choices": ["a", "b", "c", "d", "e"],
            "correct": "A",
            "source_ref": "corpus://synthetic/chosen",
            "panel": {"decision": "accept", "checks": []},
        },
        "rejected": {
            "id": "candidate-2",
            "stem": "rejected stem",
            "choices": ["a", "b", "c", "d", "e"],
            "correct": "B",
            "source_ref": "corpus://synthetic/rejected",
            "panel": {"decision": "reject", "checks": []},
            "failing_gates": ["answer_key"],
        },
        "run_id": "run-1",
    }


def _write_pair(path: Path, pair: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(pair) + "\n", encoding="utf-8")


def test_foundry_cli_writes_preferences_in_run_directory(tmp_path: Path) -> None:
    argv = [
        "foundry.py",
        "--dry-run",
        "--n",
        "3",
        "--topic",
        "optics",
        "--category",
        "geometric_optics",
        "--run",
        "run-42",
        "--out",
        str(tmp_path),
    ]

    with patch.object(sys, "argv", argv):
        assert foundry.main() == 0

    path = tmp_path / "run-42" / "preferences.jsonl"
    rows = [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
    ]
    assert len(rows) == 1
    assert rows[0]["slot"] == {
        "topic": "optics",
        "blueprint_category": "geometric_optics",
    }
    assert rows[0]["run_id"] == "run-42"
    assert rows[0]["chosen"]["id"] == "dry-1"
    assert rows[0]["rejected"]["id"] == "dry-2"
    assert rows[0]["chosen"]["source_ref"].startswith("synthetic://foundry/")
    summary = json.loads((tmp_path / "run-42" / "summary.json").read_text())
    assert summary["preferences"] == {
        "pair_count": 1,
        "category_count": 1,
        "categories": ["geometric_optics"],
    }


def test_foundry_cli_defaults_category_to_topic(tmp_path: Path) -> None:
    argv = [
        "foundry.py",
        "--dry-run",
        "--n",
        "3",
        "--topic",
        "optics",
        "--run",
        "run-default-category",
        "--out",
        str(tmp_path),
    ]

    with patch.object(sys, "argv", argv):
        assert foundry.main() == 0

    pair = json.loads(
        (tmp_path / "run-default-category" / "preferences.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()[0]
    )
    assert pair["slot"]["blueprint_category"] == "optics"


def test_foundry_cli_rejects_reused_run_id(tmp_path: Path, capsys) -> None:
    argv = [
        "foundry.py",
        "--dry-run",
        "--n",
        "3",
        "--run",
        "same-run",
        "--out",
        str(tmp_path),
    ]
    with patch.object(sys, "argv", argv):
        assert foundry.main() == 0
    original = (tmp_path / "same-run" / "summary.json").read_text()

    with patch.object(sys, "argv", argv), pytest.raises(SystemExit) as exc:
        foundry.main()

    assert exc.value.code == 2
    assert "already exists" in capsys.readouterr().err
    assert (tmp_path / "same-run" / "summary.json").read_text() == original


def test_write_result_cleans_temporary_run_after_failure(tmp_path: Path) -> None:
    result = foundry._dry_run("optics", 3, category="optics")
    slot = {"topic": "optics", "blueprint_category": "optics"}

    with (
        patch.object(
            foundry.preference,
            "write_jsonl",
            side_effect=ValueError("synthetic write failure"),
        ),
        pytest.raises(ValueError, match="synthetic write failure"),
    ):
        foundry._write_result(str(tmp_path), "failed-run", result, slot)

    assert not (tmp_path / "failed-run").exists()
    assert list(tmp_path.iterdir()) == []


def test_write_result_rejects_preference_count_mismatch(tmp_path: Path) -> None:
    result = foundry._dry_run("optics", 3, category="optics")
    slot = {"topic": "optics", "blueprint_category": "optics"}

    with (
        patch.object(foundry.preference, "write_jsonl", return_value=0),
        pytest.raises(ValueError, match="preference count mismatch"),
    ):
        foundry._write_result(str(tmp_path), "bad-count", result, slot)

    assert not (tmp_path / "bad-count").exists()
    assert list(tmp_path.iterdir()) == []


def test_foundry_cli_surfaces_pair_validation_error(
    tmp_path: Path, capsys
) -> None:
    argv = [
        "foundry.py",
        "--dry-run",
        "--n",
        "3",
        "--run",
        "invalid-pairs",
        "--out",
        str(tmp_path),
    ]

    with (
        patch.object(sys, "argv", argv),
        patch.object(
            foundry.preference,
            "pairs_from_slot",
            side_effect=ValueError("invalid preference pair: chosen.source_ref"),
        ),
        pytest.raises(SystemExit) as exc,
    ):
        foundry.main()

    assert exc.value.code == 2
    assert "chosen.source_ref" in capsys.readouterr().err
    assert not (tmp_path / "invalid-pairs").exists()


@pytest.mark.parametrize(
    "marker", ["content/gold", "content/heldout", "tier3-private"]
)
def test_foundry_jsonl_flags_forbidden_private_root(
    tmp_path: Path, marker: str
):
    pair = _valid_pair()
    pair["chosen"]["panel"]["evidence"] = {
        "source": f"copied from {marker}/items/example.json"
    }
    path = tmp_path / "preferences.jsonl"
    _write_pair(path, pair)

    errs = leakage_check.foundry_jsonl_is_clean(str(path))

    assert any(
        "line 1" in err
        and "$.chosen.panel.evidence.source" in err
        and marker in err
        for err in errs
    )


def test_foundry_jsonl_accepts_clean_record(tmp_path: Path):
    path = tmp_path / "preferences.jsonl"
    _write_pair(path, _valid_pair())

    assert leakage_check.foundry_jsonl_is_clean(str(path)) == []


def test_foundry_preference_check_passes_when_no_files_exist(tmp_path: Path):
    result = leakage_check.check_foundry_preferences(
        [], leakage_check.DEFAULT_SPAN_THRESHOLD, foundry_dir=str(tmp_path / "missing")
    )

    assert result.name == "foundry-preferences"
    assert result.ok
    assert "no foundry preference" in result.detail.lower()


def test_foundry_preference_check_scans_nested_jsonl(tmp_path: Path):
    pair = _valid_pair()
    pair["rejected"]["panel"]["evidence"] = {
        "source": "content/gold/problems/example.json"
    }
    path = tmp_path / "nested" / "run-1" / "preferences.jsonl"
    _write_pair(path, pair)

    result = leakage_check.check_foundry_preferences(
        [], leakage_check.DEFAULT_SPAN_THRESHOLD, foundry_dir=str(tmp_path)
    )

    assert not result.ok
    assert any("preferences.jsonl:line 1" in hit for hit in result.hits)


def test_foundry_preference_check_flags_private_copy_in(tmp_path: Path):
    private_text = " ".join(f"privateword{i}" for i in range(30))
    pair = _valid_pair()
    pair["chosen"]["stem"] = private_text
    path = tmp_path / "run-1" / "preferences.jsonl"
    _write_pair(path, pair)

    result = leakage_check.check_foundry_preferences(
        [("gold:synthetic", private_text)], 25, foundry_dir=str(tmp_path)
    )

    assert not result.ok
    assert any("30-word span" in hit for hit in result.hits)


def test_run_checks_includes_foundry_preference_check(tmp_path: Path):
    with (
        patch.object(leakage_check, "_heldout_item_texts", return_value=[]),
        patch.object(leakage_check, "_gold_item_texts", return_value=[]),
    ):
        results = leakage_check.run_checks(
            db_path=str(tmp_path / "missing.db"),
            foundry_dir=str(tmp_path / "missing-foundry"),
        )

    assert "foundry-preferences" in {result.name for result in results}
