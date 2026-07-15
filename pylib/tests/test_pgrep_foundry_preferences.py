# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

from __future__ import annotations

import json
import sqlite3
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
        "synthetic": False,
        "slot": {"topic": "thin lenses", "blueprint_category": "optics_waves"},
        "chosen": {
            "id": "candidate-1",
            "stem": "chosen stem",
            "choices": ["a", "b", "c", "d", "e"],
            "correct": "A",
            "source_ref": "corpus://source/chosen",
            "panel": {
                "decision": "accept",
                "checks": [
                    {
                        "name": "key",
                        "passed": True,
                        "severity": "hard",
                        "evidence": "verified",
                    }
                ],
            },
        },
        "rejected": {
            "id": "candidate-2",
            "stem": "rejected stem",
            "choices": ["a", "b", "c", "d", "e"],
            "correct": "B",
            "source_ref": "corpus://source/rejected",
            "panel": {
                "decision": "reject",
                "checks": [
                    {
                        "name": "answer_key",
                        "passed": False,
                        "severity": "hard",
                        "evidence": "disagreed",
                    }
                ],
            },
            "failing_gates": ["answer_key"],
            "reason": "answer_key: disagree",
            "refused": False,
        },
        "run_id": "run-1",
    }


def _write_pair(path: Path, pair: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(pair) + "\n", encoding="utf-8")


def _finalize(path: Path) -> None:
    (path.parent / "_SUCCESS").write_text("ok\n", encoding="utf-8")


def _write_index(path: Path, source_refs: list[str]) -> None:
    database = sqlite3.connect(path)
    try:
        database.execute(
            "CREATE TABLE chunks (source_file TEXT NOT NULL, source_ref TEXT NOT NULL)"
        )
        database.executemany(
            "INSERT INTO chunks(source_file, source_ref) VALUES (?, ?)",
            [("corpus.pdf", source_ref) for source_ref in source_refs],
        )
        database.commit()
    finally:
        database.close()


def test_foundry_cli_writes_preferences_in_run_directory(tmp_path: Path) -> None:
    argv = [
        "foundry.py",
        "--dry-run",
        "--n",
        "3",
        "--topic",
        "optics",
        "--category",
        "optics_waves",
        "--run",
        "run-42",
        "--out",
        str(tmp_path),
    ]

    with patch.object(sys, "argv", argv):
        assert foundry.main() == 0

    path = tmp_path / "run-42" / "preferences.jsonl"
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 1
    assert rows[0]["slot"] == {
        "topic": "optics",
        "blueprint_category": "optics_waves",
    }
    assert rows[0]["run_id"] == "run-42"
    assert rows[0]["chosen"]["id"] == "dry-1"
    assert rows[0]["rejected"]["id"] == "dry-2"
    assert rows[0]["chosen"]["source_ref"].startswith("synthetic://foundry/")
    assert rows[0]["synthetic"] is True
    assert (tmp_path / "run-42" / "_SUCCESS").is_file()
    summary = json.loads((tmp_path / "run-42" / "summary.json").read_text())
    assert summary["blueprint_category"] == "optics_waves"
    assert summary["synthetic"] is True
    assert summary["preference_summary"] == {
        "emitted": 1,
        "excluded": 0,
        "exclusion_reasons": {},
        "pair_counts": {
            "validated_pair_count": 1,
            "pair_count": 0,
            "category_count": 0,
            "categories": [],
        },
    }


def test_foundry_cli_defaults_category_to_mechanics(tmp_path: Path) -> None:
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
    assert pair["slot"]["blueprint_category"] == "mechanics"


def test_publication_excludes_refusal_and_reports_reason(tmp_path: Path) -> None:
    accepted = foundry._dry_run("dynamics", 1, category="mechanics").accepted[0]
    refusal = {
        "refused": True,
        "refusal_reason": "generation incomplete",
        "panel": {
            "decision": "reject",
            "checks": [],
            "refusal": True,
        },
        "reason": "generation incomplete",
        "preference_exclusion_reason": "panel refusal",
    }
    result = foundry.foundry_loop.SlotResult(
        accepted=[accepted],
        rejected=[refusal],
    )

    run_dir = foundry._write_result(
        str(tmp_path),
        "refusal-run",
        result,
        {"topic": "dynamics", "blueprint_category": "mechanics"},
        synthetic=True,
    )

    assert (run_dir / "_SUCCESS").is_file()
    assert (run_dir / "preferences.jsonl").read_text() == ""
    summary = json.loads((run_dir / "summary.json").read_text())
    assert summary["preference_summary"]["emitted"] == 0
    assert summary["preference_summary"]["excluded"] == 1
    assert summary["preference_summary"]["exclusion_reasons"] == {"panel_refusal": 1}


@pytest.mark.parametrize(
    "category",
    ["optics", "Mechanics", " mechanics", "mechanics ", "special-relativity"],
)
def test_foundry_cli_rejects_invalid_category(
    tmp_path: Path, capsys, category: str
) -> None:
    argv = [
        "foundry.py",
        "--dry-run",
        "--n",
        "3",
        "--category",
        category,
        "--run",
        "invalid-category",
        "--out",
        str(tmp_path),
    ]

    with patch.object(sys, "argv", argv), pytest.raises(SystemExit) as exc:
        foundry.main()

    assert exc.value.code == 2
    assert "blueprint category" in capsys.readouterr().err.lower()
    assert not (tmp_path / "invalid-category").exists()


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
    result = foundry._dry_run("optics", 3, category="optics_waves")
    slot = {"topic": "optics", "blueprint_category": "optics_waves"}

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
    result = foundry._dry_run("optics", 3, category="optics_waves")
    slot = {"topic": "optics", "blueprint_category": "optics_waves"}

    with (
        patch.object(foundry.preference, "write_jsonl", return_value=0),
        pytest.raises(ValueError, match="preference count mismatch"),
    ):
        foundry._write_result(str(tmp_path), "bad-count", result, slot)

    assert not (tmp_path / "bad-count").exists()
    assert list(tmp_path.iterdir()) == []


def test_write_result_uses_exclusive_publication_lock(tmp_path: Path) -> None:
    result = foundry._dry_run("optics", 3, category="optics_waves")
    slot = {"topic": "optics", "blueprint_category": "optics_waves"}
    lock = tmp_path / ".locked-run.lock"
    lock.write_text("other publisher", encoding="utf-8")

    with pytest.raises(ValueError, match="publication lock"):
        foundry._write_result(str(tmp_path), "locked-run", result, slot)

    assert lock.exists()
    assert not (tmp_path / "locked-run").exists()


def test_foundry_cli_surfaces_pair_validation_error(tmp_path: Path, capsys) -> None:
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
            "build_pairs_from_slot",
            side_effect=ValueError("invalid preference pair: chosen.source_ref"),
        ),
        pytest.raises(SystemExit) as exc,
    ):
        foundry.main()

    assert exc.value.code == 2
    assert "chosen.source_ref" in capsys.readouterr().err
    assert not (tmp_path / "invalid-pairs").exists()


@pytest.mark.parametrize("marker", ["content/gold", "content/heldout", "tier3-private"])
def test_foundry_jsonl_flags_forbidden_private_root(tmp_path: Path, marker: str):
    pair = _valid_pair()
    pair["chosen"]["panel"]["evidence"] = {
        "source": f"copied from {marker}/items/example.json"
    }
    path = tmp_path / "preferences.jsonl"
    _write_pair(path, pair)

    errs = leakage_check.foundry_jsonl_is_clean(str(path))

    assert any(
        "line 1" in err and "$.chosen.panel.evidence.source" in err and marker in err
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
    _finalize(path)

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
    _finalize(path)

    result = leakage_check.check_foundry_preferences(
        [("gold:synthetic", private_text)], 25, foundry_dir=str(tmp_path)
    )

    assert not result.ok
    assert any("30-word span" in hit for hit in result.hits)


def test_foundry_preference_check_verifies_corpus_source_refs(tmp_path: Path):
    pair = _valid_pair()
    path = tmp_path / "foundry" / "run-1" / "preferences.jsonl"
    _write_pair(path, pair)
    _finalize(path)
    db_path = tmp_path / "corpus.db"
    _write_index(
        db_path,
        [pair["chosen"]["source_ref"], pair["rejected"]["source_ref"]],
    )

    result = leakage_check.check_foundry_preferences(
        [],
        leakage_check.DEFAULT_SPAN_THRESHOLD,
        foundry_dir=str(tmp_path / "foundry"),
        db_path=str(db_path),
    )

    assert result.ok
    assert "source references verified" in result.detail


def test_foundry_preference_check_rejects_unknown_source_ref(tmp_path: Path):
    pair = _valid_pair()
    path = tmp_path / "foundry" / "run-1" / "preferences.jsonl"
    _write_pair(path, pair)
    _finalize(path)
    db_path = tmp_path / "corpus.db"
    _write_index(db_path, [pair["chosen"]["source_ref"]])

    result = leakage_check.check_foundry_preferences(
        [],
        leakage_check.DEFAULT_SPAN_THRESHOLD,
        foundry_dir=str(tmp_path / "foundry"),
        db_path=str(db_path),
    )

    assert not result.ok
    assert any("rejected.source_ref" in hit for hit in result.hits)


def test_foundry_preference_check_requires_index_when_files_exist(tmp_path: Path):
    path = tmp_path / "foundry" / "run-1" / "preferences.jsonl"
    _write_pair(path, _valid_pair())
    _finalize(path)

    result = leakage_check.check_foundry_preferences(
        [],
        leakage_check.DEFAULT_SPAN_THRESHOLD,
        foundry_dir=str(tmp_path / "foundry"),
        db_path=str(tmp_path / "missing.db"),
    )

    assert not result.ok
    assert any("source verification unavailable" in hit for hit in result.hits)


def test_foundry_preference_check_rejects_cross_run_duplicates(tmp_path: Path):
    first = _valid_pair()
    duplicate = json.loads(json.dumps(first))
    duplicate["run_id"] = "run-2"
    _write_pair(tmp_path / "run-1" / "preferences.jsonl", first)
    _write_pair(tmp_path / "run-2" / "preferences.jsonl", duplicate)
    _finalize(tmp_path / "run-1" / "preferences.jsonl")
    _finalize(tmp_path / "run-2" / "preferences.jsonl")
    db_path = tmp_path / "corpus.db"
    _write_index(
        db_path,
        [first["chosen"]["source_ref"], first["rejected"]["source_ref"]],
    )

    result = leakage_check.check_foundry_preferences(
        [],
        leakage_check.DEFAULT_SPAN_THRESHOLD,
        foundry_dir=str(tmp_path),
        db_path=str(db_path),
    )

    assert not result.ok
    assert any("duplicate chosen/rejected pair" in hit for hit in result.hits)


def test_leakage_discovery_only_reads_finalized_runs(tmp_path: Path):
    valid = _valid_pair()
    finalized = tmp_path / "run-final" / "preferences.jsonl"
    active = tmp_path / ".run-active.tmp" / "preferences.jsonl"
    orphan = tmp_path / "run-orphan" / "preferences.jsonl"
    bare = tmp_path / "preferences.jsonl"
    _write_pair(finalized, valid)
    _finalize(finalized)

    invalid = json.loads(json.dumps(valid))
    invalid["chosen"]["source_ref"] = "content/gold/private.json"
    for path in (active, orphan, bare):
        _write_pair(path, invalid)
    _finalize(active)

    db_path = tmp_path / "corpus.db"
    _write_index(
        db_path,
        [valid["chosen"]["source_ref"], valid["rejected"]["source_ref"]],
    )

    result = leakage_check.check_foundry_preferences(
        [],
        leakage_check.DEFAULT_SPAN_THRESHOLD,
        foundry_dir=str(tmp_path),
        db_path=str(db_path),
    )

    assert result.ok
    assert "1 foundry preference file" in result.detail


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
