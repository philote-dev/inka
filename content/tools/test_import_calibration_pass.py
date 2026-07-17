# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Offline tests for the private two-pass calibration-label importer."""

from __future__ import annotations

import ctypes
import errno
import hashlib
import json
import os
import shutil
import stat
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import cast

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import _ai_path  # noqa: E402

_ai_path.add_ai_core()

import import_calibration_pass as importer  # noqa: E402
from pgrep.ai import calibration_ruler, calibration_sheet  # noqa: E402

_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20">'
    '<path d="M1 1 L19 19"/></svg>'
)
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
_PASS_B_VALUES = {
    "source_supports_stem": "PASS",
    "source_supports_answer": "UNSURE",
    "decomposition_correct": "PASS",
    "decomposition_leaks_answer": "FAIL",
}


def _source(stratum: str, index: int) -> dict[str, object]:
    categories = tuple(sorted(calibration_ruler.BLUEPRINT_CATEGORIES))
    category = categories[index % len(categories)]
    stem = f"Configuration {index} uses {category} principles."
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
        "source_ref": f"SOURCE_REF_SENTINEL_{stratum}_{index}",
        "source_excerpt": f"Grounding excerpt {stratum} {index}.",
        "solution_decomposition": [
            {
                "subgoal": f"Reason about {category}.",
                "rubric": "Name the governing law.",
            }
        ],
        "verifier": {"decision": f"VERIFIER_SENTINEL_{stratum}_{index}"},
        "recommendation": f"RECOMMENDATION_SENTINEL_{stratum}_{index}",
    }
    if stratum == "shadow":
        item["model_family"] = ("sol", "opus", "grok")[index % 3]
    return item


@pytest.fixture(scope="module")
def ruler_manifest() -> calibration_ruler.RulerManifest:
    return calibration_ruler.build_ruler(
        [_source("trusted", index) for index in range(60)],
        [_source("failure", index) for index in range(60)],
        [_source("shadow", index) for index in range(60)],
        seed=7,
    )


def _manifest_document(
    manifest: calibration_ruler.RulerManifest,
    run_id: str,
) -> dict[str, object]:
    builder = importer.ruler_builder
    source_hashes = {
        name: builder.SourceAttestation(
            loaded_sha256=(digest := hashlib.sha256(name.encode()).hexdigest()),
            current_sha256=digest,
            head_blob_sha256=digest,
        )
        for name in builder._SOURCE_PATHS
    }
    attestation = builder.ExecutionAttestation(
        head_sha="a" * 40,
        tree_status="clean",
        source_hashes=source_hashes,
    )
    inputs = {
        "trusted": {"sha256": "b" * 64, "count": 60},
        "failure": {"sha256": "c" * 64, "count": 60},
        "shadow": {
            "manifest_sha256": "d" * 64,
            "run_id": "shadow-test",
            "candidate_count": 60,
        },
    }
    return builder._build_manifest(
        manifest,
        run_id=run_id,
        seed=manifest.seed,
        inputs=inputs,
        attestation=attestation,
    )


def _published_ruler(
    tmp_path: Path,
    manifest: calibration_ruler.RulerManifest,
    *,
    run_id: str = "ruler-test",
) -> Path:
    run_dir = tmp_path / "calibration" / run_id
    (run_dir / "pass-a").mkdir(parents=True)
    (run_dir / "figures").mkdir()
    (run_dir / "manifest.json").write_text(
        json.dumps(
            _manifest_document(manifest, run_id),
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
    )
    (run_dir / "index.md").write_text(
        calibration_sheet.render_index(manifest),
        encoding="utf-8",
    )
    for number, block in enumerate(
        calibration_sheet.render_blocks(manifest, pass_name="a"),
        start=1,
    ):
        (run_dir / "pass-a" / f"block-{number:02d}.md").write_text(
            block,
            encoding="utf-8",
        )
    for relative, raw in calibration_sheet.figure_assets(manifest).items():
        path = run_dir / relative
        path.write_bytes(raw)
    (run_dir / "_SUCCESS").write_text("ok\n", encoding="utf-8")
    return run_dir


def _replace_in_review(
    run_dir: Path,
    pass_name: str,
    review_id: str,
    old: str,
    new: str,
) -> None:
    for path in sorted((run_dir / f"pass-{pass_name}").glob("block-*.md")):
        document = path.read_text(encoding="utf-8")
        heading = f"### {review_id}\n"
        if heading not in document:
            continue
        start = document.index(heading)
        end = document.index("\n---\n", start) + len("\n---\n")
        block = document[start:end]
        assert block.count(old) == 1
        path.write_text(
            document[:start] + block.replace(old, new, 1) + document[end:],
            encoding="utf-8",
        )
        return
    raise AssertionError(f"review ID not found: {review_id}")


def _fill_pass_a(
    run_dir: Path,
    manifest: calibration_ruler.RulerManifest,
    *,
    consistent: bool = True,
) -> None:
    for path in sorted((run_dir / "pass-a").glob("block-*.md")):
        document = path.read_text(encoding="utf-8")
        for field, value in _PASS_A_VALUES.items():
            document = document.replace(
                f"\n{field}:\n",
                f"\n{field}: {value}\n",
            )
        path.write_text(document, encoding="utf-8")
    if not consistent:
        repeats = [item for item in manifest.items if item.repeat_of is not None]
        for repeat in repeats[:2]:
            _replace_in_review(
                run_dir,
                "a",
                cast(str, repeat.review_id),
                "your_answer: B",
                "your_answer: C",
            )


def _fill_pass_b(run_dir: Path) -> None:
    for path in sorted((run_dir / "pass-b").glob("block-*.md")):
        document = path.read_text(encoding="utf-8")
        for field, value in _PASS_B_VALUES.items():
            document = document.replace(
                f"\n{field}:\n",
                f"\n{field}: {value}\n",
            )
        path.write_text(document, encoding="utf-8")


def _import_pass(
    run_dir: Path,
    pass_name: str,
    *,
    io: importer.ImportIO | None = None,
) -> dict[str, object]:
    return importer.import_pass(
        run_dir,
        pass_name,
        _allow_test_paths=True,
        _io=io,
    )


def _read_report(run_dir: Path, pass_name: str) -> dict[str, object]:
    return cast(
        dict[str, object],
        json.loads(
            (run_dir / "reports" / f"pass-{pass_name}-labels.json").read_text(
                encoding="utf-8"
            )
        ),
    )


def test_pass_a_import_renders_pass_b_after_consistency_pass(
    tmp_path: Path,
    ruler_manifest: calibration_ruler.RulerManifest,
) -> None:
    run_dir = _published_ruler(tmp_path, ruler_manifest)
    _fill_pass_a(run_dir, ruler_manifest)

    report = _import_pass(run_dir, "a")

    assert report["status"] == "PASS_A_COMPLETE"
    assert _read_report(run_dir, "a") == report
    assert report["label_count"] == 132
    consistency = cast(Mapping[str, object], report["repeat_consistency"])
    assert consistency["exact_answer"] == {
        "matches": 12,
        "total": 12,
        "raw_agreement": 1.0,
    }
    assert len(list((run_dir / "pass-b").glob("block-*.md"))) == 7
    assert (run_dir / "pass-b" / "_SUCCESS").read_text(encoding="utf-8") == "ok\n"
    labels = cast(Mapping[str, Mapping[str, str]], report["labels"])
    assert set(labels["item-0001"]) == set(calibration_sheet.PASS_A_FIELDS)


def test_low_repeat_consistency_does_not_render_pass_b(
    tmp_path: Path,
    ruler_manifest: calibration_ruler.RulerManifest,
) -> None:
    run_dir = _published_ruler(tmp_path, ruler_manifest)
    _fill_pass_a(run_dir, ruler_manifest, consistent=False)

    report = _import_pass(run_dir, "a")

    assert report["status"] == "ADJUDICATION_REQUIRED"
    gate = cast(Mapping[str, object], report["consistency_gate"])
    assert gate["passed"] is False
    assert "your_answer" in cast(list[str], gate["failed_checks"])
    assert (run_dir / "reports" / "pass-a-labels.json").is_file()
    assert not (run_dir / "pass-b").exists()


def test_pass_b_import_requires_pass_a_and_writes_fixed_shape_labels(
    tmp_path: Path,
    ruler_manifest: calibration_ruler.RulerManifest,
) -> None:
    run_dir = _published_ruler(tmp_path, ruler_manifest)
    _fill_pass_a(run_dir, ruler_manifest)
    _import_pass(run_dir, "a")
    _fill_pass_b(run_dir)

    report = _import_pass(run_dir, "b")

    assert report["status"] == "PASS_B_COMPLETE"
    assert _read_report(run_dir, "b") == report
    assert report["label_count"] == 132
    labels = cast(Mapping[str, Mapping[str, str]], report["labels"])
    assert set(labels["item-0001"]) == set(calibration_sheet.PASS_B_FIELDS)


def test_public_labels_and_pass_b_sheets_never_expose_hidden_manifest_fields(
    tmp_path: Path,
    ruler_manifest: calibration_ruler.RulerManifest,
) -> None:
    run_dir = _published_ruler(tmp_path, ruler_manifest)
    _fill_pass_a(run_dir, ruler_manifest)
    _import_pass(run_dir, "a")
    surfaces = [
        (run_dir / "reports" / "pass-a-labels.json").read_text(encoding="utf-8"),
        *[
            path.read_text(encoding="utf-8")
            for path in sorted((run_dir / "pass-b").glob("block-*.md"))
        ],
    ]
    rendered = "\n".join(surfaces)

    for hidden in (
        "SOURCE_REF_SENTINEL",
        "VERIFIER_SENTINEL",
        "RECOMMENDATION_SENTINEL",
        "model_family",
        "verifier",
        "recommendation",
        "stratum",
        "split",
        "repeat_of",
        "content_hash",
        "pass_a_hash",
        "pass_b_hash",
    ):
        assert hidden not in rendered


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("missing_block", "Pass A block set"),
        ("duplicate_id", "duplicate review ID"),
        ("changed_text", "immutable content"),
        ("unknown_label", "unknown value"),
        ("hidden_metadata", "hidden metadata"),
        ("changed_asset", "asset bytes/hash mismatch"),
    ],
)
def test_pass_a_import_rejects_incomplete_tampered_or_injected_workspace(
    tmp_path: Path,
    ruler_manifest: calibration_ruler.RulerManifest,
    mutation: str,
    message: str,
) -> None:
    run_dir = _published_ruler(tmp_path, ruler_manifest)
    _fill_pass_a(run_dir, ruler_manifest)
    first = cast(str, ruler_manifest.items[0].review_id)
    second = cast(str, ruler_manifest.items[1].review_id)
    if mutation == "missing_block":
        (run_dir / "pass-a" / "block-07.md").unlink()
    elif mutation == "duplicate_id":
        _replace_in_review(run_dir, "a", second, f"### {second}", f"### {first}")
    elif mutation == "changed_text":
        stem = calibration_sheet.protect_markdown_text(ruler_manifest.items[0].stem)
        _replace_in_review(run_dir, "a", first, stem, stem + " changed")
    elif mutation == "unknown_label":
        _replace_in_review(
            run_dir,
            "a",
            first,
            "overall: KEEP",
            "overall: keep",
        )
    elif mutation == "hidden_metadata":
        _replace_in_review(
            run_dir,
            "a",
            first,
            "overall: KEEP",
            "model_family: sol\noverall: KEEP",
        )
    elif mutation == "changed_asset":
        figure = next((run_dir / "figures").iterdir())
        figure.write_bytes(figure.read_bytes() + b" ")
    else:
        raise AssertionError(f"unknown mutation: {mutation}")

    with pytest.raises(importer.CalibrationImportError, match=message):
        _import_pass(run_dir, "a")
    assert not (run_dir / "reports").exists()
    assert not (run_dir / "pass-b").exists()


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("missing_block", "Pass B block set"),
        ("duplicate_id", "duplicate review ID"),
        ("changed_excerpt", "immutable content"),
        ("unknown_label", "unknown value"),
        ("hidden_metadata", "hidden metadata"),
        ("failed_pass_a", "successful Pass A"),
    ],
)
def test_pass_b_import_rejects_bad_state_or_tampered_sheets(
    tmp_path: Path,
    ruler_manifest: calibration_ruler.RulerManifest,
    mutation: str,
    message: str,
) -> None:
    run_dir = _published_ruler(tmp_path, ruler_manifest)
    _fill_pass_a(run_dir, ruler_manifest)
    _import_pass(run_dir, "a")
    _fill_pass_b(run_dir)
    first = cast(str, ruler_manifest.items[0].review_id)
    second = cast(str, ruler_manifest.items[1].review_id)
    if mutation == "missing_block":
        (run_dir / "pass-b" / "block-07.md").unlink()
    elif mutation == "duplicate_id":
        _replace_in_review(run_dir, "b", second, f"### {second}", f"### {first}")
    elif mutation == "changed_excerpt":
        excerpt = calibration_sheet.protect_markdown_text(
            cast(str, ruler_manifest.items[0].source_excerpt)
        )
        _replace_in_review(run_dir, "b", first, excerpt, excerpt + " changed")
    elif mutation == "unknown_label":
        _replace_in_review(
            run_dir,
            "b",
            first,
            "source_supports_stem: PASS",
            "source_supports_stem: pass",
        )
    elif mutation == "hidden_metadata":
        _replace_in_review(
            run_dir,
            "b",
            first,
            "decomposition_correct: PASS",
            "verifier: accept\ndecomposition_correct: PASS",
        )
    elif mutation == "failed_pass_a":
        report = _read_report(run_dir, "a")
        report["status"] = "ADJUDICATION_REQUIRED"
        (run_dir / "reports" / "pass-a-labels.json").write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    else:
        raise AssertionError(f"unknown mutation: {mutation}")

    with pytest.raises(importer.CalibrationImportError, match=message):
        _import_pass(run_dir, "b")
    assert not (run_dir / "reports" / "pass-b-labels.json").exists()


@pytest.mark.parametrize(
    "state",
    [
        "missing_success",
        "failed_marker",
        "partial_reports",
        "partial_pass_b",
        "existing_lock",
    ],
)
def test_pass_a_rejects_wrong_or_partial_run_state(
    tmp_path: Path,
    ruler_manifest: calibration_ruler.RulerManifest,
    state: str,
) -> None:
    run_dir = _published_ruler(tmp_path, ruler_manifest)
    _fill_pass_a(run_dir, ruler_manifest)
    if state == "missing_success":
        (run_dir / "_SUCCESS").unlink()
    elif state == "failed_marker":
        (run_dir / "_FAILED").write_text("failed\n", encoding="utf-8")
    elif state == "partial_reports":
        (run_dir / "reports").mkdir()
    elif state == "partial_pass_b":
        (run_dir / "pass-b").mkdir()
    elif state == "existing_lock":
        (run_dir / ".calibration-import.lock").write_text("held\n", encoding="utf-8")
    else:
        raise AssertionError(f"unknown state: {state}")

    with pytest.raises(importer.CalibrationImportError):
        _import_pass(run_dir, "a")


def test_import_rejects_symlink_run_and_workspace_entries(
    tmp_path: Path,
    ruler_manifest: calibration_ruler.RulerManifest,
) -> None:
    real_run = _published_ruler(tmp_path, ruler_manifest)
    _fill_pass_a(real_run, ruler_manifest)
    run_link = tmp_path / "run-link"
    run_link.symlink_to(real_run, target_is_directory=True)
    with pytest.raises(importer.CalibrationImportError, match="symlink"):
        _import_pass(run_link, "a")

    block = real_run / "pass-a" / "block-01.md"
    copy = tmp_path / "block-copy.md"
    shutil.copyfile(block, copy)
    block.unlink()
    block.symlink_to(copy)
    with pytest.raises(importer.CalibrationImportError, match="symlink"):
        _import_pass(real_run, "a")


def test_os_temp_paths_require_private_test_seam(
    tmp_path: Path,
    ruler_manifest: calibration_ruler.RulerManifest,
) -> None:
    run_dir = _published_ruler(tmp_path, ruler_manifest)
    _fill_pass_a(run_dir, ruler_manifest)

    with pytest.raises(importer.CalibrationImportError, match="exact repository"):
        importer.import_pass(run_dir, "a")
    with pytest.raises(SystemExit):
        importer.main(["--run", str(run_dir), "--pass", "a"])
    with pytest.raises(SystemExit):
        importer.main(["--run", "../escape", "--pass", "a"])


def test_completed_imports_are_never_overwritten(
    tmp_path: Path,
    ruler_manifest: calibration_ruler.RulerManifest,
) -> None:
    run_dir = _published_ruler(tmp_path, ruler_manifest)
    _fill_pass_a(run_dir, ruler_manifest)
    _import_pass(run_dir, "a")
    with pytest.raises(importer.CalibrationImportError, match="already|overwrite"):
        _import_pass(run_dir, "a")

    _fill_pass_b(run_dir)
    _import_pass(run_dir, "b")
    before = (run_dir / "reports" / "pass-b-labels.json").read_bytes()
    with pytest.raises(importer.CalibrationImportError, match="already|overwrite"):
        _import_pass(run_dir, "b")
    assert (run_dir / "reports" / "pass-b-labels.json").read_bytes() == before


class _MutateBeforePublish(importer.ImportIO):
    def __init__(self, path: Path) -> None:
        self.path = path

    def before_publish(self) -> None:
        self.path.write_bytes(self.path.read_bytes() + b" ")


def test_input_race_is_detected_before_publication(
    tmp_path: Path,
    ruler_manifest: calibration_ruler.RulerManifest,
) -> None:
    run_dir = _published_ruler(tmp_path, ruler_manifest)
    _fill_pass_a(run_dir, ruler_manifest)
    block = run_dir / "pass-a" / "block-01.md"

    with pytest.raises(importer.CalibrationImportError, match="changed during import"):
        _import_pass(run_dir, "a", io=_MutateBeforePublish(block))
    assert not (run_dir / "reports").exists()
    assert not (run_dir / "pass-b").exists()


def test_just_recipes_pass_untrusted_run_id_as_quoted_positional_argument() -> None:
    justfile = Path(__file__).resolve().parents[2] / "justfile"
    text = justfile.read_text(encoding="utf-8")
    for recipe_name in ("calibration-import-a", "calibration-import-b"):
        marker = f"{recipe_name} run:"
        assert marker in text
        recipe = text.split(marker, maxsplit=1)[1].split("\n\n", maxsplit=1)[0]
        assert '--run "$1"' in recipe
        assert "{{ run }}" not in recipe


# --- Review hardening: transactional staging and publication ---------------


def _assert_no_import_residue(run_dir: Path) -> None:
    assert not list(run_dir.glob(".calibration-import.*"))
    assert not (run_dir / ".calibration-import.lock").exists()
    assert not (run_dir / "reports").exists()
    assert not (run_dir / "pass-b").exists()


def _quarantine_root(run_dir: Path) -> Path:
    return run_dir.parent / ".calibration-rollback-quarantine"


def _quarantine_paths(run_dir: Path) -> list[Path]:
    root = _quarantine_root(run_dir)
    return list(root.iterdir()) if root.is_dir() else []


def _quarantine_payloads(run_dir: Path) -> list[bytes]:
    payloads: list[bytes] = []
    root = _quarantine_root(run_dir)
    if not root.is_dir():
        return payloads
    for path in root.rglob("*"):
        if path.is_file() and not path.is_symlink():
            payloads.append(path.read_bytes())
    return payloads


def _remove_quarantines(run_dir: Path) -> None:
    root = _quarantine_root(run_dir)
    if root.exists():
        shutil.rmtree(root)


def _capability_probe_root(run_dir: Path) -> Path:
    return run_dir.parent / ".capability-probes"


def _capability_probe_directories(run_dir: Path) -> list[Path]:
    root = _capability_probe_root(run_dir)
    return (
        sorted(path for path in root.iterdir() if path.is_dir())
        if root.is_dir()
        else []
    )


class _FailStageWrite(importer.ImportIO):
    def before_stage_write(self, relative: str) -> None:
        if relative == "report.json":
            raise OSError("injected staging write failure")


class _FailStageFsync(importer.ImportIO):
    def fsync_directory(self, fd: int, relative: str) -> None:
        if relative == "stage":
            raise OSError("injected staging fsync failure")
        os.fsync(fd)


@pytest.mark.parametrize(
    "io",
    [_FailStageWrite(), _FailStageFsync()],
    ids=["write", "fsync"],
)
def test_staging_failure_leaves_no_residue_and_retry_succeeds(
    tmp_path: Path,
    ruler_manifest: calibration_ruler.RulerManifest,
    io: importer.ImportIO,
) -> None:
    run_dir = _published_ruler(tmp_path, ruler_manifest)
    _fill_pass_a(run_dir, ruler_manifest)

    with pytest.raises(importer.CalibrationImportError, match="staging"):
        _import_pass(run_dir, "a", io=io)

    _assert_no_import_residue(run_dir)
    assert _import_pass(run_dir, "a")["status"] == "PASS_A_COMPLETE"


class _FailAfterPublish(importer.ImportIO):
    def __init__(self, target: str) -> None:
        self.target = target

    def after_publish(self, relative: str) -> None:
        if relative == self.target:
            raise OSError(f"injected failure after {relative}")


class _LoseFinalLock(importer.ImportIO):
    def __init__(self, run_dir: Path) -> None:
        self.run_dir = run_dir

    def before_lock_release(self) -> None:
        (self.run_dir / ".calibration-import.lock").unlink()


@pytest.mark.parametrize(
    "failure",
    ["post_report", "mid_pass_b", "final_lock_loss"],
)
def test_post_publication_failure_rolls_back_and_retry_succeeds(
    tmp_path: Path,
    ruler_manifest: calibration_ruler.RulerManifest,
    failure: str,
) -> None:
    run_dir = _published_ruler(tmp_path, ruler_manifest)
    _fill_pass_a(run_dir, ruler_manifest)
    io: importer.ImportIO
    if failure == "post_report":
        io = _FailAfterPublish("reports/pass-a-labels.json")
    elif failure == "mid_pass_b":
        io = _FailAfterPublish("pass-b/block-03.md")
    else:
        io = _LoseFinalLock(run_dir)

    with pytest.raises(importer.CalibrationImportError) as captured:
        _import_pass(run_dir, "a", io=io)

    _assert_no_import_residue(run_dir)
    quarantine_root = _quarantine_root(run_dir)
    assert stat.S_IMODE(quarantine_root.stat().st_mode) == 0o700
    assert _quarantine_paths(run_dir)
    assert str(quarantine_root) in str(captured.value)
    assert "entr" in str(captured.value)
    assert _import_pass(run_dir, "a")["status"] == "PASS_A_COMPLETE"
    _remove_quarantines(run_dir)


# --- Review hardening: published output integrity --------------------------


class _SubstitutePublishedOutput(importer.ImportIO):
    def __init__(self, path: Path, *, commit_artifact: bool) -> None:
        self.path = path
        self.commit_artifact = commit_artifact
        self.substituted = False

    def _substitute(self) -> None:
        if self.substituted:
            return
        self.path.rename(self.path.with_name(f"{self.path.name}.owned-before-attack"))
        self.path.write_bytes(b"attacker-substitution\n")
        self.substituted = True

    def before_published_outputs_attestation(self) -> None:
        if not self.commit_artifact:
            self._substitute()

    def before_commit_artifact_attestation(self, relative: str) -> None:
        if self.commit_artifact:
            self._substitute()


@pytest.mark.parametrize(
    ("target", "pass_name", "relative", "commit_artifact"),
    [
        ("block", "a", "pass-b/block-01.md", False),
        ("marker", "a", "pass-b/_SUCCESS", False),
        ("pass_a_report", "a", "reports/pass-a-labels.json", True),
        ("pass_b_report", "b", "reports/pass-b-labels.json", True),
    ],
)
def test_substituted_published_output_never_becomes_valid_commit(
    tmp_path: Path,
    ruler_manifest: calibration_ruler.RulerManifest,
    target: str,
    pass_name: str,
    relative: str,
    commit_artifact: bool,
) -> None:
    run_dir = _published_ruler(tmp_path, ruler_manifest)
    _fill_pass_a(run_dir, ruler_manifest)
    if pass_name == "b":
        _import_pass(run_dir, "a")
        _fill_pass_b(run_dir)
    target_path = run_dir / relative

    with pytest.raises(importer.CalibrationImportError, match="published|identity"):
        _import_pass(
            run_dir,
            pass_name,
            io=_SubstitutePublishedOutput(
                target_path,
                commit_artifact=commit_artifact,
            ),
        )

    commit_path = (
        run_dir
        / "reports"
        / ("pass-a-labels.json" if pass_name == "a" else "pass-b-labels.json")
    )
    assert not commit_path.exists()
    assert b"attacker-substitution\n" in _quarantine_payloads(run_dir)
    assert _import_pass(run_dir, pass_name)["status"] == (
        "PASS_A_COMPLETE" if pass_name == "a" else "PASS_B_COMPLETE"
    )
    _remove_quarantines(run_dir)


# --- Review hardening: exact Pass A report bytes ----------------------------


@pytest.mark.parametrize(
    "mutation",
    ["minified", "reordered", "trailing_space", "changed_label"],
)
def test_pass_b_requires_exact_canonical_pass_a_report_bytes(
    tmp_path: Path,
    ruler_manifest: calibration_ruler.RulerManifest,
    mutation: str,
) -> None:
    run_dir = _published_ruler(tmp_path, ruler_manifest)
    _fill_pass_a(run_dir, ruler_manifest)
    _import_pass(run_dir, "a")
    _fill_pass_b(run_dir)
    report_path = run_dir / "reports" / "pass-a-labels.json"
    original = report_path.read_bytes()
    payload = json.loads(original)
    if mutation == "minified":
        changed = json.dumps(payload, separators=(",", ":")).encode()
    elif mutation == "reordered":
        changed = (
            json.dumps(
                dict(reversed(list(payload.items()))),
                indent=2,
                sort_keys=False,
            )
            + "\n"
        ).encode()
    elif mutation == "trailing_space":
        changed = original + b" "
    else:
        payload["labels"]["item-0001"]["overall"] = "DROP"
        changed = (
            json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n"
        ).encode()
    assert changed != original
    report_path.write_bytes(changed)

    with pytest.raises(
        importer.CalibrationImportError,
        match="exact immutable Pass A report bytes",
    ):
        _import_pass(run_dir, "b")

    assert not (run_dir / "reports" / "pass-b-labels.json").exists()
    report_path.write_bytes(original)
    assert _import_pass(run_dir, "b")["status"] == "PASS_B_COMPLETE"


# --- Review hardening: exact Task 5 provenance contract --------------------


def _mutate_manifest(run_dir: Path, mutation: str) -> None:
    path = run_dir / "manifest.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    build = payload["build"]
    inputs = payload["inputs"]
    source_hashes = build["source_hashes"]
    source_name = next(iter(source_hashes))
    if mutation == "empty_build":
        payload["build"] = {}
    elif mutation == "missing_build_field":
        build.pop("source_hashes")
    elif mutation == "unknown_build_field":
        build["unexpected"] = True
    elif mutation == "empty_inputs":
        payload["inputs"] = {}
    elif mutation == "missing_input_field":
        inputs["trusted"].pop("sha256")
    elif mutation == "unknown_input_field":
        inputs["shadow"]["unexpected"] = True
    elif mutation == "empty_source_attestation":
        source_hashes[source_name] = {}
    elif mutation == "missing_source_attestation":
        source_hashes.pop(source_name)
    elif mutation == "unknown_source_attestation":
        source_hashes["unknown_source"] = source_hashes[source_name]
    elif mutation == "bad_provenance_hash":
        source_hashes[source_name]["current_sha256"] = "not-a-hash"
    else:
        raise AssertionError(f"unknown mutation: {mutation}")
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )


@pytest.mark.parametrize(
    "mutation",
    [
        "empty_build",
        "missing_build_field",
        "unknown_build_field",
        "empty_inputs",
        "missing_input_field",
        "unknown_input_field",
        "empty_source_attestation",
        "missing_source_attestation",
        "unknown_source_attestation",
        "bad_provenance_hash",
    ],
)
def test_import_rejects_malformed_builder_provenance(
    tmp_path: Path,
    ruler_manifest: calibration_ruler.RulerManifest,
    mutation: str,
) -> None:
    run_dir = _published_ruler(tmp_path, ruler_manifest)
    _fill_pass_a(run_dir, ruler_manifest)
    _mutate_manifest(run_dir, mutation)

    with pytest.raises(
        importer.CalibrationImportError,
        match="manifest (?:build|input|source|provenance)",
    ):
        _import_pass(run_dir, "a")

    _assert_no_import_residue(run_dir)


# --- Review hardening: anchored component-swap defenses --------------------


class _SwapPassADirectoryAfterRead(importer.ImportIO):
    def __init__(self, run_dir: Path, attacker: Path) -> None:
        self.run_dir = run_dir
        self.attacker = attacker
        self.swapped = False

    def after_read(self, relative: str) -> None:
        if relative == "pass-a/block-01.md" and not self.swapped:
            (self.run_dir / "pass-a").rename(self.run_dir / "pass-a-original")
            (self.run_dir / "pass-a").symlink_to(
                self.attacker,
                target_is_directory=True,
            )
            self.swapped = True


def test_component_swap_during_reads_cannot_escape_workspace(
    tmp_path: Path,
    ruler_manifest: calibration_ruler.RulerManifest,
) -> None:
    run_dir = _published_ruler(tmp_path, ruler_manifest)
    _fill_pass_a(run_dir, ruler_manifest)
    attacker = tmp_path / "attacker-read"
    attacker.mkdir()
    sentinel = attacker / "sentinel"
    sentinel.write_text("attacker-owned\n", encoding="utf-8")

    with pytest.raises(importer.CalibrationImportError, match="identity|binding"):
        _import_pass(
            run_dir,
            "a",
            io=_SwapPassADirectoryAfterRead(run_dir, attacker),
        )

    assert sentinel.read_text(encoding="utf-8") == "attacker-owned\n"
    assert (run_dir / "pass-a").is_symlink()
    assert not list((run_dir / "pass-a-original").glob(".calibration-import.*"))
    (run_dir / "pass-a").unlink()
    (run_dir / "pass-a-original").rename(run_dir / "pass-a")
    assert _import_pass(run_dir, "a")["status"] == "PASS_A_COMPLETE"


class _SwapRunDuringStaging(importer.ImportIO):
    def __init__(self, run_dir: Path, attacker: Path) -> None:
        self.run_dir = run_dir
        self.attacker = attacker
        self.moved = run_dir.with_name(f"{run_dir.name}-moved")
        self.swapped = False

    def before_stage_write(self, relative: str) -> None:
        if relative == "report.json" and not self.swapped:
            self.run_dir.rename(self.moved)
            self.run_dir.symlink_to(self.attacker, target_is_directory=True)
            self.swapped = True


def test_component_swap_during_staging_cannot_escape_workspace(
    tmp_path: Path,
    ruler_manifest: calibration_ruler.RulerManifest,
) -> None:
    run_dir = _published_ruler(tmp_path, ruler_manifest)
    _fill_pass_a(run_dir, ruler_manifest)
    attacker = tmp_path / "attacker-stage"
    attacker.mkdir()
    sentinel = attacker / "sentinel"
    sentinel.write_text("attacker-owned\n", encoding="utf-8")
    io = _SwapRunDuringStaging(run_dir, attacker)

    with pytest.raises(importer.CalibrationImportError, match="identity|binding"):
        _import_pass(run_dir, "a", io=io)

    assert sentinel.read_text(encoding="utf-8") == "attacker-owned\n"
    assert not list(io.moved.glob(".calibration-import.*"))
    assert not (io.moved / "reports").exists()
    assert not (io.moved / "pass-b").exists()
    run_dir.unlink()
    io.moved.rename(run_dir)
    assert _import_pass(run_dir, "a")["status"] == "PASS_A_COMPLETE"


class _SwapPassBDuringPublication(importer.ImportIO):
    def __init__(self, run_dir: Path, attacker: Path) -> None:
        self.run_dir = run_dir
        self.attacker = attacker
        self.moved = run_dir / "pass-b-moved"
        self.swapped = False

    def after_publish(self, relative: str) -> None:
        if relative == "pass-b/block-01.md" and not self.swapped:
            (self.run_dir / "pass-b").rename(self.moved)
            (self.run_dir / "pass-b").symlink_to(
                self.attacker,
                target_is_directory=True,
            )
            self.swapped = True


def test_component_swap_during_publication_preserves_attacker_files(
    tmp_path: Path,
    ruler_manifest: calibration_ruler.RulerManifest,
) -> None:
    run_dir = _published_ruler(tmp_path, ruler_manifest)
    _fill_pass_a(run_dir, ruler_manifest)
    attacker = tmp_path / "attacker-publish"
    attacker.mkdir()
    sentinel = attacker / "sentinel"
    sentinel.write_text("attacker-owned\n", encoding="utf-8")
    io = _SwapPassBDuringPublication(run_dir, attacker)

    with pytest.raises(importer.CalibrationImportError, match="identity|binding"):
        _import_pass(run_dir, "a", io=io)

    assert sentinel.read_text(encoding="utf-8") == "attacker-owned\n"
    assert not (run_dir / "pass-b").exists()
    assert any(
        path.is_symlink()
        for transaction_dir in _quarantine_paths(run_dir)
        for path in transaction_dir.rglob("*")
    )
    assert not io.moved.exists()
    assert not (run_dir / "reports").exists()
    assert _import_pass(run_dir, "a")["status"] == "PASS_A_COMPLETE"
    _remove_quarantines(run_dir)


class _SwapReportDuringRollback(_FailAfterPublish):
    def __init__(self, run_dir: Path) -> None:
        super().__init__("reports/pass-a-labels.json")
        self.run_dir = run_dir
        self.swapped = False

    def before_rollback(self, relative: str) -> None:
        if relative == "reports/pass-a-labels.json" and not self.swapped:
            report = self.run_dir / "reports" / "pass-a-labels.json"
            report.rename(self.run_dir / "reports" / "owned-report-moved")
            report.write_text("attacker-owned\n", encoding="utf-8")
            self.swapped = True


def test_component_swap_during_rollback_never_deletes_user_file(
    tmp_path: Path,
    ruler_manifest: calibration_ruler.RulerManifest,
) -> None:
    run_dir = _published_ruler(tmp_path, ruler_manifest)
    _fill_pass_a(run_dir, ruler_manifest)

    with pytest.raises(importer.CalibrationImportError, match="ambig|clean"):
        _import_pass(run_dir, "a", io=_SwapReportDuringRollback(run_dir))

    assert not (run_dir / "reports").exists()
    assert b"attacker-owned\n" in _quarantine_payloads(run_dir)
    assert not (run_dir / "pass-b").exists()
    assert _import_pass(run_dir, "a")["status"] == "PASS_A_COMPLETE"
    _remove_quarantines(run_dir)


# --- Final review: late attestation, close, and quarantine races ------------


class _LateSwapBeforeCommit(importer.ImportIO):
    def __init__(self, path: Path) -> None:
        self.path = path
        self.moved = path.with_name(f"{path.name}.owned-late-swap")
        self.called = False

    def before_final_commit_attestation(self) -> None:
        self.path.rename(self.moved)
        self.path.write_bytes(b"attacker-late-substitution\n")
        self.called = True


@pytest.mark.parametrize(
    ("pass_name", "relative"),
    [
        ("a", "pass-b/block-01.md"),
        ("a", "pass-b/_SUCCESS"),
        ("b", "pass-b/block-01.md"),
    ],
)
def test_late_output_swap_before_report_commit_is_rejected(
    tmp_path: Path,
    ruler_manifest: calibration_ruler.RulerManifest,
    pass_name: str,
    relative: str,
) -> None:
    run_dir = _published_ruler(tmp_path, ruler_manifest)
    _fill_pass_a(run_dir, ruler_manifest)
    if pass_name == "b":
        _import_pass(run_dir, "a")
        _fill_pass_b(run_dir)
    target = run_dir / relative
    io = _LateSwapBeforeCommit(target)

    with pytest.raises(importer.CalibrationImportError, match="identity|published"):
        _import_pass(run_dir, pass_name, io=io)

    assert io.called
    commit = (
        run_dir
        / "reports"
        / ("pass-a-labels.json" if pass_name == "a" else "pass-b-labels.json")
    )
    assert not commit.exists()
    if pass_name == "a":
        assert b"attacker-late-substitution\n" in _quarantine_payloads(run_dir)
    else:
        assert target.read_bytes() == b"attacker-late-substitution\n"
        target.unlink()
        io.moved.rename(target)
    assert _import_pass(run_dir, pass_name)["status"] == (
        "PASS_A_COMPLETE" if pass_name == "a" else "PASS_B_COMPLETE"
    )
    _remove_quarantines(run_dir)


class _CloseFailureAfterCommit(importer.ImportIO):
    def __init__(self) -> None:
        self.called = False

    def close_lock_fd(self, fd: int) -> None:
        os.close(fd)
        self.called = True
        raise OSError("injected cleanup-only lock close failure")


def test_cleanup_only_lock_close_failure_does_not_reverse_commit(
    tmp_path: Path,
    ruler_manifest: calibration_ruler.RulerManifest,
) -> None:
    run_dir = _published_ruler(tmp_path, ruler_manifest)
    _fill_pass_a(run_dir, ruler_manifest)
    io = _CloseFailureAfterCommit()

    report = _import_pass(run_dir, "a", io=io)

    assert io.called
    assert report["status"] == "PASS_A_COMPLETE"
    assert (run_dir / "reports" / "pass-a-labels.json").is_file()
    assert (run_dir / "pass-b" / "_SUCCESS").is_file()
    assert not (run_dir / ".calibration-import.lock").exists()


class _SwapPreservedQuarantineName(_FailAfterPublish):
    def __init__(self, run_dir: Path, *, relative: str, directory: bool) -> None:
        super().__init__("reports/pass-a-labels.json")
        self.run_dir = run_dir
        self.relative = relative
        self.directory = directory
        self.called = False

    def after_rollback_preserve(
        self,
        relative: str,
        quarantine_directory: str,
        item_name: str,
    ) -> None:
        if relative != self.relative or self.called:
            return
        parent = self.run_dir.parent / quarantine_directory
        quarantine = parent / item_name
        quarantine.rename(parent / f"{item_name}.owned-preserved")
        if self.directory:
            quarantine.mkdir()
            (quarantine / "attacker-sentinel").write_bytes(b"attacker-preserved-dir\n")
        else:
            quarantine.write_bytes(b"attacker-preserved-file\n")
        self.called = True


@pytest.mark.parametrize(
    ("relative", "directory", "attacker_bytes"),
    [
        (
            "reports/pass-a-labels.json",
            False,
            b"attacker-preserved-file\n",
        ),
        ("pass-b", True, b"attacker-preserved-dir\n"),
    ],
)
def test_preservation_boundary_never_deletes_swapped_file_or_directory(
    tmp_path: Path,
    ruler_manifest: calibration_ruler.RulerManifest,
    relative: str,
    directory: bool,
    attacker_bytes: bytes,
) -> None:
    run_dir = _published_ruler(tmp_path, ruler_manifest)
    _fill_pass_a(run_dir, ruler_manifest)
    outside = tmp_path / "outside-sentinel"
    outside.write_bytes(b"outside-owned\n")
    io = _SwapPreservedQuarantineName(
        run_dir,
        relative=relative,
        directory=directory,
    )

    with pytest.raises(importer.CalibrationImportError) as captured:
        _import_pass(run_dir, "a", io=io)

    assert io.called
    assert outside.read_bytes() == b"outside-owned\n"
    assert str(_quarantine_root(run_dir)) in str(captured.value)
    assert attacker_bytes in _quarantine_payloads(run_dir)
    assert any(
        "owned-preserved" in path.name
        for transaction_dir in _quarantine_paths(run_dir)
        for path in transaction_dir.rglob("*")
    )
    _assert_no_import_residue(run_dir)
    assert not (run_dir / "reports" / "pass-a-labels.json").exists()
    assert _import_pass(run_dir, "a")["status"] == "PASS_A_COMPLETE"
    _remove_quarantines(run_dir)


# --- Final review: atomic rename-no-replace quarantine destination ----------


@pytest.mark.parametrize("directory", [False, True], ids=["file", "directory"])
def test_platform_rename_noreplace_moves_only_to_absent_destination(
    tmp_path: Path,
    directory: bool,
) -> None:
    source_parent = tmp_path / "source-parent"
    destination_parent = tmp_path / "destination-parent"
    source_parent.mkdir()
    destination_parent.mkdir()
    source = source_parent / "source"
    if directory:
        source.mkdir()
        (source / "sentinel").write_bytes(b"owned-directory\n")
    else:
        source.write_bytes(b"owned-file\n")
    source_fd = os.open(source_parent, os.O_RDONLY | os.O_DIRECTORY)
    destination_fd = os.open(destination_parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        importer._rename_noreplace(
            source_fd,
            "source",
            destination_fd,
            "opaque-target",
        )
    finally:
        os.close(source_fd)
        os.close(destination_fd)

    assert not source.exists()
    target = destination_parent / "opaque-target"
    if directory:
        assert (target / "sentinel").read_bytes() == b"owned-directory\n"
    else:
        assert target.read_bytes() == b"owned-file\n"


@pytest.mark.parametrize("directory", [False, True], ids=["file", "directory"])
def test_platform_rename_noreplace_never_overwrites_existing_destination(
    tmp_path: Path,
    directory: bool,
) -> None:
    source_parent = tmp_path / "source-parent"
    destination_parent = tmp_path / "destination-parent"
    source_parent.mkdir()
    destination_parent.mkdir()
    source = source_parent / "source"
    target = destination_parent / "occupied"
    if directory:
        source.mkdir()
        (source / "source-sentinel").write_bytes(b"owned-directory\n")
        target.mkdir()
        (target / "foreign-sentinel").write_bytes(b"foreign-directory\n")
    else:
        source.write_bytes(b"owned-file\n")
        target.write_bytes(b"foreign-file\n")
    source_fd = os.open(source_parent, os.O_RDONLY | os.O_DIRECTORY)
    destination_fd = os.open(destination_parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        with pytest.raises(FileExistsError):
            importer._rename_noreplace(
                source_fd,
                "source",
                destination_fd,
                "occupied",
            )
    finally:
        os.close(source_fd)
        os.close(destination_fd)

    if directory:
        assert (source / "source-sentinel").read_bytes() == b"owned-directory\n"
        assert (target / "foreign-sentinel").read_bytes() == b"foreign-directory\n"
    else:
        assert source.read_bytes() == b"owned-file\n"
        assert target.read_bytes() == b"foreign-file\n"


def test_rename_noreplace_unsupported_platform_fails_closed(
    tmp_path: Path,
) -> None:
    source_parent = tmp_path / "source-parent"
    destination_parent = tmp_path / "destination-parent"
    source_parent.mkdir()
    destination_parent.mkdir()
    source = source_parent / "source"
    target = destination_parent / "target"
    source.write_bytes(b"owned\n")
    source_fd = os.open(source_parent, os.O_RDONLY | os.O_DIRECTORY)
    destination_fd = os.open(destination_parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        with pytest.raises(importer.CalibrationImportError, match="no-replace"):
            importer._rename_noreplace(
                source_fd,
                "source",
                destination_fd,
                "target",
                _platform="unsupported-test-platform",
            )
    finally:
        os.close(source_fd)
        os.close(destination_fd)
    assert source.read_bytes() == b"owned\n"
    assert not target.exists()


class _FakeSyscall:
    def __init__(self) -> None:
        self.restype: object = None
        self.calls: list[tuple[object, ...]] = []

    def __call__(self, *args: object) -> int:
        self.calls.append(args)
        ctypes.set_errno(errno.EEXIST)
        return -1


class _LinuxLibcWithoutRenameat2:
    def __init__(self) -> None:
        self.syscall = _FakeSyscall()

    def __getattr__(self, name: str) -> object:
        if name == "renameat2":
            raise AttributeError(name)
        raise AssertionError(f"unexpected libc attribute: {name}")


def test_linux_syscall_fallback_normalizes_collision_without_mutation(
    tmp_path: Path,
) -> None:
    source_parent = tmp_path / "source-parent"
    destination_parent = tmp_path / "destination-parent"
    source_parent.mkdir()
    destination_parent.mkdir()
    source = source_parent / "source"
    source.write_bytes(b"owned\n")
    fake = _LinuxLibcWithoutRenameat2()
    source_fd = os.open(source_parent, os.O_RDONLY | os.O_DIRECTORY)
    destination_fd = os.open(destination_parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        with pytest.raises(FileExistsError):
            importer._rename_noreplace(
                source_fd,
                "source",
                destination_fd,
                "target",
                _platform="linux",
                _libc=fake,
                _machine="x86_64",
            )
    finally:
        os.close(source_fd)
        os.close(destination_fd)
    assert fake.syscall.calls
    assert cast(ctypes.c_long, fake.syscall.calls[0][0]).value == 316
    assert source.read_bytes() == b"owned\n"
    assert not (destination_parent / "target").exists()


class _OccupyExactQuarantineDestination(_FailAfterPublish):
    def __init__(self, run_dir: Path, *, relative: str, directory: bool) -> None:
        super().__init__("reports/pass-a-labels.json")
        self.run_dir = run_dir
        self.relative = relative
        self.directory = directory
        self.called = False

    def before_quarantine_rename(
        self,
        relative: str,
        quarantine_directory: str,
        target_name: str,
    ) -> None:
        if relative != self.relative or self.called:
            return
        target = self.run_dir.parent / quarantine_directory / target_name
        if self.directory:
            target.mkdir()
            (target / "foreign-sentinel").write_bytes(
                b"foreign-destination-directory\n"
            )
        else:
            target.write_bytes(b"foreign-destination-file\n")
        self.called = True


@pytest.mark.parametrize(
    ("relative", "directory", "foreign_bytes"),
    [
        (
            "reports/pass-a-labels.json",
            False,
            b"foreign-destination-file\n",
        ),
        ("pass-b", True, b"foreign-destination-directory\n"),
    ],
)
def test_exact_quarantine_destination_race_preserves_source_and_foreign(
    tmp_path: Path,
    ruler_manifest: calibration_ruler.RulerManifest,
    relative: str,
    directory: bool,
    foreign_bytes: bytes,
) -> None:
    run_dir = _published_ruler(tmp_path, ruler_manifest)
    _fill_pass_a(run_dir, ruler_manifest)
    io = _OccupyExactQuarantineDestination(
        run_dir,
        relative=relative,
        directory=directory,
    )

    with pytest.raises(importer.CalibrationImportError) as captured:
        _import_pass(run_dir, "a", io=io)

    assert io.called
    assert "quarantine" in str(captured.value)
    assert foreign_bytes in _quarantine_payloads(run_dir)
    _assert_no_import_residue(run_dir)
    assert _import_pass(run_dir, "a")["status"] == "PASS_A_COMPLETE"
    _remove_quarantines(run_dir)


# --- Final review: rename-no-replace capability preflight ------------------


def _tree_snapshot(root: Path) -> dict[str, tuple[object, ...]]:
    snapshot: dict[str, tuple[object, ...]] = {}
    for path in [root, *sorted(root.rglob("*"))]:
        relative = "." if path == root else path.relative_to(root).as_posix()
        info = path.lstat()
        mode = stat.S_IMODE(info.st_mode)
        if path.is_symlink():
            snapshot[relative] = ("symlink", mode, os.readlink(path))
        elif path.is_dir():
            snapshot[relative] = ("directory", mode)
        else:
            snapshot[relative] = ("file", mode, path.read_bytes())
    return snapshot


def test_actual_rename_noreplace_capability_preflight_is_side_effect_free(
    tmp_path: Path,
) -> None:
    marker = tmp_path / "marker"
    marker.write_bytes(b"unchanged\n")
    before = _tree_snapshot(tmp_path)

    importer._preflight_rename_noreplace()

    assert _tree_snapshot(tmp_path) == before


def test_unsupported_rename_noreplace_preflight_fails_closed() -> None:
    with pytest.raises(importer.CalibrationImportError, match="no-replace"):
        importer._preflight_rename_noreplace(_platform="unsupported-test-platform")


class _UnsupportedRenameCapability(importer.ImportIO):
    def __init__(self) -> None:
        self.called = False

    def preflight_rename_noreplace(self) -> None:
        self.called = True
        raise importer.CalibrationImportError(
            "injected rename-no-replace capability unavailable"
        )


@pytest.mark.parametrize("pass_name", ["a", "b"])
def test_unsupported_capability_mutates_nothing_and_retry_succeeds(
    tmp_path: Path,
    ruler_manifest: calibration_ruler.RulerManifest,
    pass_name: str,
) -> None:
    run_dir = _published_ruler(tmp_path, ruler_manifest)
    _fill_pass_a(run_dir, ruler_manifest)
    if pass_name == "b":
        _import_pass(run_dir, "a")
        _fill_pass_b(run_dir)
    before = _tree_snapshot(run_dir.parent)
    io = _UnsupportedRenameCapability()

    with pytest.raises(
        importer.CalibrationImportError,
        match="capability unavailable",
    ):
        _import_pass(run_dir, pass_name, io=io)

    assert io.called
    assert _tree_snapshot(run_dir.parent) == before
    assert not (run_dir / ".calibration-import.lock").exists()
    assert not list(run_dir.glob(".calibration-import.*"))
    if pass_name == "a":
        assert not (run_dir / "reports").exists()
        assert not (run_dir / "pass-b").exists()
    else:
        assert not (run_dir / "reports" / "pass-b-labels.json").exists()
    assert _import_pass(run_dir, pass_name)["status"] == (
        "PASS_A_COMPLETE" if pass_name == "a" else "PASS_B_COMPLETE"
    )
    _remove_quarantines(run_dir)


class _RuntimeUnsupportedRename(importer.ImportIO):
    def __init__(self, error_number: int) -> None:
        self.error_number = error_number
        self.calls = 0

    def rename_noreplace(
        self,
        source_dir_fd: int,
        source_name: str,
        destination_dir_fd: int,
        destination_name: str,
    ) -> None:
        self.calls += 1
        raise OSError(self.error_number, os.strerror(self.error_number))


class _IncorrectOverwriteRename(importer.ImportIO):
    def __init__(self) -> None:
        self.calls = 0

    def rename_noreplace(
        self,
        source_dir_fd: int,
        source_name: str,
        destination_dir_fd: int,
        destination_name: str,
    ) -> None:
        self.calls += 1
        os.rename(
            source_name,
            destination_name,
            src_dir_fd=source_dir_fd,
            dst_dir_fd=destination_dir_fd,
        )


@pytest.mark.parametrize("pass_name", ["a", "b"])
@pytest.mark.parametrize("error_number", [errno.ENOSYS, errno.ENOTSUP])
def test_runtime_unsupported_probe_mutates_nothing_and_retry_succeeds(
    tmp_path: Path,
    ruler_manifest: calibration_ruler.RulerManifest,
    pass_name: str,
    error_number: int,
) -> None:
    run_dir = _published_ruler(tmp_path, ruler_manifest)
    _fill_pass_a(run_dir, ruler_manifest)
    if pass_name == "b":
        _import_pass(run_dir, "a")
        _fill_pass_b(run_dir)
    before_run = _tree_snapshot(run_dir)
    quarantine_root = _quarantine_root(run_dir)
    before_quarantine = (
        _tree_snapshot(quarantine_root) if quarantine_root.exists() else None
    )
    probes_before = len(_capability_probe_directories(run_dir))
    io = _RuntimeUnsupportedRename(error_number)

    with pytest.raises(
        importer.CalibrationImportError,
        match="runtime rename-no-replace probe",
    ):
        _import_pass(run_dir, pass_name, io=io)

    assert io.calls == 1
    assert _tree_snapshot(run_dir) == before_run
    assert (
        _tree_snapshot(quarantine_root) if quarantine_root.exists() else None
    ) == before_quarantine
    failed_probes = _capability_probe_directories(run_dir)
    assert len(failed_probes) == probes_before + 1
    assert stat.S_IMODE(_capability_probe_root(run_dir).stat().st_mode) == 0o700
    assert stat.S_IMODE(failed_probes[-1].stat().st_mode) == 0o700
    assert _import_pass(run_dir, pass_name)["status"] == (
        "PASS_A_COMPLETE" if pass_name == "a" else "PASS_B_COMPLETE"
    )
    assert len(_capability_probe_directories(run_dir)) == probes_before + 2
    _remove_quarantines(run_dir)


@pytest.mark.parametrize("pass_name", ["a", "b"])
def test_incorrect_overwrite_probe_mutates_nothing_and_retry_succeeds(
    tmp_path: Path,
    ruler_manifest: calibration_ruler.RulerManifest,
    pass_name: str,
) -> None:
    run_dir = _published_ruler(tmp_path, ruler_manifest)
    _fill_pass_a(run_dir, ruler_manifest)
    if pass_name == "b":
        _import_pass(run_dir, "a")
        _fill_pass_b(run_dir)
    before_run = _tree_snapshot(run_dir)
    probes_before = len(_capability_probe_directories(run_dir))
    io = _IncorrectOverwriteRename()

    with pytest.raises(
        importer.CalibrationImportError,
        match="collision semantics",
    ):
        _import_pass(run_dir, pass_name, io=io)

    assert io.calls == 2
    assert _tree_snapshot(run_dir) == before_run
    assert len(_capability_probe_directories(run_dir)) == probes_before + 1
    assert _import_pass(run_dir, pass_name)["status"] == (
        "PASS_A_COMPLETE" if pass_name == "a" else "PASS_B_COMPLETE"
    )
    assert len(_capability_probe_directories(run_dir)) == probes_before + 2
    _remove_quarantines(run_dir)


class _SwapAtProbeRetention(importer.ImportIO):
    def __init__(self, calibration_root: Path, *, directory: bool) -> None:
        self.calibration_root = calibration_root
        self.directory = directory
        self.called = False

    def after_capability_probe(self, probe_directory: str) -> None:
        probe = self.calibration_root / probe_directory
        if self.directory:
            owned = probe.with_name(f"{probe.name}.owned-probe")
            probe.rename(owned)
            probe.mkdir()
            (probe / "foreign-sentinel").write_bytes(b"foreign-probe-directory\n")
        else:
            moved = probe / "moved"
            moved.rename(probe / "moved.owned-probe")
            moved.write_bytes(b"foreign-probe-file\n")
        self.called = True


@pytest.mark.parametrize("directory", [False, True], ids=["file", "directory"])
def test_probe_retention_boundary_never_deletes_foreign_replacement(
    tmp_path: Path,
    ruler_manifest: calibration_ruler.RulerManifest,
    monkeypatch: pytest.MonkeyPatch,
    directory: bool,
) -> None:
    run_dir = _published_ruler(tmp_path, ruler_manifest)
    _fill_pass_a(run_dir, ruler_manifest)
    io = _SwapAtProbeRetention(run_dir.parent, directory=directory)

    def forbidden_delete(*args: object, **kwargs: object) -> None:
        raise AssertionError("probe retention must never unlink/rmdir")

    monkeypatch.setattr(importer.os, "unlink", forbidden_delete)
    monkeypatch.setattr(importer.os, "rmdir", forbidden_delete)

    assert _import_pass(run_dir, "a", io=io)["status"] == "PASS_A_COMPLETE"
    assert io.called
    probe_root = _capability_probe_root(run_dir)
    if directory:
        assert any(
            (path / "foreign-sentinel").read_bytes() == b"foreign-probe-directory\n"
            for path in probe_root.iterdir()
            if (path / "foreign-sentinel").is_file()
        )
        assert any(path.name.endswith(".owned-probe") for path in probe_root.iterdir())
    else:
        assert any(
            path.read_bytes() == b"foreign-probe-file\n"
            for path in probe_root.rglob("moved")
        )
        assert any(path.name == "moved.owned-probe" for path in probe_root.rglob("*"))


def test_successful_passes_accumulate_private_probes_without_ambiguity(
    tmp_path: Path,
    ruler_manifest: calibration_ruler.RulerManifest,
) -> None:
    run_dir = _published_ruler(tmp_path, ruler_manifest)
    _fill_pass_a(run_dir, ruler_manifest)

    assert _import_pass(run_dir, "a")["status"] == "PASS_A_COMPLETE"
    after_a = _capability_probe_directories(run_dir)
    assert len(after_a) == 1
    assert all(stat.S_IMODE(path.stat().st_mode) == 0o700 for path in after_a)

    _fill_pass_b(run_dir)
    assert _import_pass(run_dir, "b")["status"] == "PASS_B_COMPLETE"
    after_b = _capability_probe_directories(run_dir)
    assert len(after_b) == 2
    assert (run_dir / "reports" / "pass-b-labels.json").is_file()


# --- Broad review: final commit, alias, CLI, device, and lock boundaries ----


class _SwapBeforeLockRelease(importer.ImportIO):
    def __init__(self, run_dir: Path, relative: str) -> None:
        self.path = run_dir / relative
        self.moved = self.path.with_name(f"{self.path.name}.pre-lock-original")
        self.called = False

    def before_lock_release(self) -> None:
        self.path.rename(self.moved)
        self.path.write_bytes(b"late-lock-release-mutation\n")
        self.called = True


@pytest.mark.parametrize(
    "relative",
    [
        "manifest.json",
        "pass-b/block-01.md",
        "pass-b/_SUCCESS",
        "reports/pass-a-labels.json",
    ],
)
def test_before_lock_release_reattests_every_input_and_output(
    tmp_path: Path,
    ruler_manifest: calibration_ruler.RulerManifest,
    relative: str,
) -> None:
    run_dir = _published_ruler(tmp_path, ruler_manifest)
    _fill_pass_a(run_dir, ruler_manifest)
    io = _SwapBeforeLockRelease(run_dir, relative)

    with pytest.raises(importer.CalibrationImportError, match="changed|published"):
        _import_pass(run_dir, "a", io=io)

    assert io.called
    if relative in {"manifest.json"}:
        io.path.unlink()
        io.moved.rename(io.path)
    assert not (run_dir / "reports" / "pass-a-labels.json").exists()
    assert not (run_dir / "pass-b").exists()
    assert _import_pass(run_dir, "a")["status"] == "PASS_A_COMPLETE"
    _remove_quarantines(run_dir)


@pytest.mark.parametrize("pass_name", ["a", "b"])
def test_successful_quarantine_files_are_not_live_hardlink_aliases(
    tmp_path: Path,
    ruler_manifest: calibration_ruler.RulerManifest,
    pass_name: str,
) -> None:
    run_dir = _published_ruler(tmp_path, ruler_manifest)
    _fill_pass_a(run_dir, ruler_manifest)
    _import_pass(run_dir, "a")
    if pass_name == "b":
        _fill_pass_b(run_dir)
        _import_pass(run_dir, "b")
    committed = {
        path.relative_to(run_dir).as_posix(): path.read_bytes()
        for path in [
            *sorted((run_dir / "pass-b").glob("*")),
            *sorted((run_dir / "reports").glob("*.json")),
        ]
        if path.is_file()
    }
    committed_inodes = {
        (path.stat().st_dev, path.stat().st_ino)
        for path in [
            *sorted((run_dir / "pass-b").glob("*")),
            *sorted((run_dir / "reports").glob("*.json")),
        ]
        if path.is_file()
    }
    retained_files = [
        path
        for path in _quarantine_root(run_dir).rglob("*")
        if path.is_file() and not path.is_symlink()
    ]
    assert retained_files
    assert not any(
        (path.stat().st_dev, path.stat().st_ino) in committed_inodes
        for path in retained_files
    )

    for path in retained_files:
        path.write_bytes(path.read_bytes() + b"mutated-retained\n")

    assert {
        path.relative_to(run_dir).as_posix(): path.read_bytes()
        for path in [
            *sorted((run_dir / "pass-b").glob("*")),
            *sorted((run_dir / "reports").glob("*.json")),
        ]
        if path.is_file()
    } == committed


def test_cli_prints_only_non_sensitive_summary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    secret = "SENSITIVE-JUDGMENT-SENTINEL"
    fake_report = {
        "status": "PASS_A_COMPLETE",
        "label_count": 132,
        "labels": {"item-0001": {"notes": secret}},
        "manifest_sha256": secret,
        "repeat_consistency": {
            "repeat_count": 12,
            "exact_answer": {"matches": 12, "total": 12, "raw_agreement": 1.0},
            "categorical_fields": {
                "overall": {"matches": 11, "total": 12, "raw_agreement": 11 / 12}
            },
        },
        "consistency_gate": {"status": "PASS", "passed": True},
    }
    monkeypatch.setattr(importer, "CALIBRATION_ROOT", tmp_path)
    monkeypatch.setattr(importer, "import_pass", lambda *args, **kwargs: fake_report)

    assert importer.main(["--run", "safe-run", "--pass", "a"]) == 0

    output = capsys.readouterr().out
    payload = json.loads(output)
    assert set(payload) == {
        "status",
        "report_path",
        "label_count",
        "repeat_consistency",
    }
    assert payload["status"] == "PASS_A_COMPLETE"
    assert payload["label_count"] == 132
    assert payload["report_path"].endswith("reports/pass-a-labels.json")
    assert secret not in output
    assert '"labels":' not in output
    assert "sha256" not in output


def test_cli_errors_are_sanitized_without_raw_reviewer_content(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    secret = "SECRET-MALFORMED-LABEL-SENTINEL"
    monkeypatch.setattr(importer, "CALIBRATION_ROOT", tmp_path)

    def fail_import(*args: object, **kwargs: object) -> object:
        raise importer.CalibrationImportError(
            f"reviewer edit required: unknown value {secret} for overall"
        )

    monkeypatch.setattr(importer, "import_pass", fail_import)

    with pytest.raises(SystemExit):
        importer.main(["--run", "safe-run", "--pass", "a"])

    captured = capsys.readouterr()
    assert captured.out == ""
    assert secret not in captured.err
    assert "CALIBRATION_IMPORT_ERROR" in captured.err
    assert "reviewer_field" in captured.err


class _DeviceMismatch(importer.ImportIO):
    def device_id(self, fd: int, role: str) -> int:
        device = os.fstat(fd).st_dev
        return device + 1 if role == "run" else device


@pytest.mark.parametrize("pass_name", ["a", "b"])
def test_device_mismatch_fails_before_mutation_and_retry_succeeds(
    tmp_path: Path,
    ruler_manifest: calibration_ruler.RulerManifest,
    pass_name: str,
) -> None:
    run_dir = _published_ruler(tmp_path, ruler_manifest)
    _fill_pass_a(run_dir, ruler_manifest)
    if pass_name == "b":
        _import_pass(run_dir, "a")
        _fill_pass_b(run_dir)
    before = _tree_snapshot(run_dir)

    with pytest.raises(importer.CalibrationImportError, match="device"):
        _import_pass(run_dir, pass_name, io=_DeviceMismatch())

    assert _tree_snapshot(run_dir) == before
    assert _import_pass(run_dir, pass_name)["status"] == (
        "PASS_A_COMPLETE" if pass_name == "a" else "PASS_B_COMPLETE"
    )
    _remove_quarantines(run_dir)


class _RenameAndReplaceLock(importer.ImportIO):
    def __init__(self, run_dir: Path) -> None:
        self.run_dir = run_dir
        self.owned_moved = run_dir / ".owned-import-lock-moved"
        self.called = False

    def before_quarantine(self, relative: str) -> None:
        if relative != importer.LOCK_NAME or self.called:
            return
        lock = self.run_dir / importer.LOCK_NAME
        lock.rename(self.owned_moved)
        lock.write_bytes(b"foreign-lock-replacement\n")
        self.called = True


def test_lock_rename_replacement_preserves_owned_and_foreign_and_retry_succeeds(
    tmp_path: Path,
    ruler_manifest: calibration_ruler.RulerManifest,
) -> None:
    run_dir = _published_ruler(tmp_path, ruler_manifest)
    _fill_pass_a(run_dir, ruler_manifest)
    io = _RenameAndReplaceLock(run_dir)

    with pytest.raises(importer.CalibrationImportError, match="lock|quarantine"):
        _import_pass(run_dir, "a", io=io)

    assert io.called
    assert not io.owned_moved.exists()
    assert not (run_dir / importer.LOCK_NAME).exists()
    payloads = _quarantine_payloads(run_dir)
    assert b"foreign-lock-replacement\n" in payloads
    assert any(payload.startswith(b"pid=") for payload in payloads)
    assert _import_pass(run_dir, "a")["status"] == "PASS_A_COMPLETE"
    _remove_quarantines(run_dir)


# --- Final acceptance: post-attestation and root-open race boundaries -------


class _MutateInputDuringLockPreparation(importer.ImportIO):
    def __init__(self, run_dir: Path, boundary: str) -> None:
        self.path = run_dir / "manifest.json"
        self.owned = self.path.with_name("manifest.json.owned-lock-preparation")
        self.boundary = boundary
        self.called = False

    def _mutate(self) -> None:
        if self.called:
            return
        self.path.rename(self.owned)
        self.path.write_bytes(b'{"attacker":"post-attestation"}\n')
        self.called = True

    def before_quarantine(self, relative: str) -> None:
        if self.boundary == "before_quarantine" and relative == importer.LOCK_NAME:
            self._mutate()

    def before_quarantine_rename(
        self,
        relative: str,
        quarantine_directory: str,
        target_name: str,
    ) -> None:
        del quarantine_directory, target_name
        if (
            self.boundary == "before_quarantine_rename"
            and relative == importer.LOCK_NAME
        ):
            self._mutate()


@pytest.mark.parametrize(
    "boundary",
    ["before_quarantine", "before_quarantine_rename"],
)
def test_lock_preparation_mutation_is_rejected_by_final_attestation(
    tmp_path: Path,
    ruler_manifest: calibration_ruler.RulerManifest,
    boundary: str,
) -> None:
    run_dir = _published_ruler(tmp_path, ruler_manifest)
    _fill_pass_a(run_dir, ruler_manifest)
    io = _MutateInputDuringLockPreparation(run_dir, boundary)

    with pytest.raises(importer.CalibrationImportError, match="changed|identity"):
        _import_pass(run_dir, "a", io=io)

    assert io.called
    assert not (run_dir / "reports").exists()
    assert not (run_dir / "pass-b").exists()
    assert not (run_dir / importer.LOCK_NAME).exists()
    io.path.unlink()
    io.owned.rename(io.path)
    assert _import_pass(run_dir, "a")["status"] == "PASS_A_COMPLETE"
    _remove_quarantines(run_dir)


class _SwapDestinationImmediatelyAfterMove(importer.ImportIO):
    def __init__(self, run_dir: Path) -> None:
        self.destination = run_dir / "reports" / "pass-a-labels.json"
        self.owned = self.destination.with_name("pass-a-labels.json.owned-after-move")
        self.called = False

    def after_publish_move_before_attestation(self, relative: str) -> None:
        if relative != "reports/pass-a-labels.json" or self.called:
            return
        self.destination.rename(self.owned)
        self.destination.write_bytes(b"foreign-after-publication-move\n")
        self.called = True


def test_publication_destination_swap_preserves_owned_and_foreign_without_loss(
    tmp_path: Path,
    ruler_manifest: calibration_ruler.RulerManifest,
) -> None:
    run_dir = _published_ruler(tmp_path, ruler_manifest)
    _fill_pass_a(run_dir, ruler_manifest)
    io = _SwapDestinationImmediatelyAfterMove(run_dir)

    with pytest.raises(importer.CalibrationImportError, match="published|identity"):
        _import_pass(run_dir, "a", io=io)

    assert io.called
    assert not io.destination.exists()
    assert not io.owned.exists()
    payloads = _quarantine_payloads(run_dir)
    assert b"foreign-after-publication-move\n" in payloads
    assert any(b'"status": "PASS_A_COMPLETE"' in payload for payload in payloads)
    assert not (run_dir / "pass-b").exists()
    assert _import_pass(run_dir, "a")["status"] == "PASS_A_COMPLETE"
    _remove_quarantines(run_dir)


class _RaceRootOpen(importer.ImportIO):
    def __init__(self, calibration_root: Path, role: str, race: str) -> None:
        self.calibration_root = calibration_root
        self.role = role
        self.race = race
        self.called = False
        self.original: Path | None = None

    def before_root_open(self, role: str, root_name: str) -> None:
        if role != self.role or self.called:
            return
        root = self.calibration_root / root_name
        if self.race == "swap":
            self.original = root.with_name(f"{root.name}.owned-before-open")
            root.rename(self.original)
            root.mkdir(mode=0o700)
            (root / "foreign-root-sentinel").write_bytes(
                f"foreign-{role}-root\n".encode()
            )
        else:
            root.chmod(0o755)
        self.called = True


@pytest.mark.parametrize("role", ["probe_root", "quarantine_root"])
@pytest.mark.parametrize("race", ["swap", "chmod"])
def test_root_open_rechecks_exact_preopen_identity_and_private_mode(
    tmp_path: Path,
    ruler_manifest: calibration_ruler.RulerManifest,
    role: str,
    race: str,
) -> None:
    run_dir = _published_ruler(tmp_path, ruler_manifest)
    _fill_pass_a(run_dir, ruler_manifest)
    root_name = (
        importer.CAPABILITY_PROBE_ROOT_NAME
        if role == "probe_root"
        else importer.QUARANTINE_ROOT_NAME
    )
    protected_root = run_dir.parent / root_name
    protected_root.mkdir(mode=0o700)
    io = _RaceRootOpen(run_dir.parent, role, race)

    with pytest.raises(importer.CalibrationImportError, match="identity|private|0700"):
        _import_pass(run_dir, "a", io=io)

    assert io.called
    assert not (run_dir / "reports" / "pass-a-labels.json").exists()
    assert not (run_dir / importer.LOCK_NAME).exists()
    if race == "swap":
        assert io.original is not None
        assert io.original.is_dir()
        assert (
            protected_root / "foreign-root-sentinel"
        ).read_bytes() == f"foreign-{role}-root\n".encode()
    else:
        assert stat.S_IMODE(protected_root.stat().st_mode) == 0o755
