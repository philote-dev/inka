# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Offline tests for the private blind calibration ruler builder CLI."""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import _ai_path  # noqa: E402

_ai_path.add_ai_core()

import build_calibration_ruler as builder  # noqa: E402

# --- Fixtures --------------------------------------------------------------


def _write_items(path: Path, stratum: str, count: int) -> Path:
    items = [builder.offline_problem_item(stratum, index) for index in range(count)]
    path.write_text(json.dumps(items), encoding="utf-8")
    return path


@pytest.fixture(scope="session")
def shadow_run(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("shadow-runs")
    return builder.offline_shadow_run(root, run_id="offline-shadow", n=45)


@pytest.fixture()
def inputs(tmp_path: Path, shadow_run: Path) -> dict[str, Path]:
    return {
        "trusted": _write_items(tmp_path / "trusted.json", "trusted", 50),
        "failures": _write_items(tmp_path / "failure.json", "failure", 50),
        "shadow": shadow_run,
    }


def _build(inputs: dict[str, Path], out_root: Path, **kwargs: object) -> Path:
    return builder.build(
        trusted_path=inputs["trusted"],
        failures_path=inputs["failures"],
        shadow_path=inputs["shadow"],
        out_root=out_root,
        run_id=str(kwargs.pop("run_id", "ruler-1")),
        **kwargs,  # type: ignore[arg-type]
    )


# --- Happy path ------------------------------------------------------------


def test_build_publishes_private_pass_a_workspace(
    tmp_path: Path, inputs: dict[str, Path]
) -> None:
    run_dir = _build(inputs, tmp_path / "calibration", run_id="ruler-1", seed=7)
    assert (run_dir / "_SUCCESS").exists()
    assert (run_dir / "manifest.json").exists()
    assert (run_dir / "index.md").exists()
    assert len(list((run_dir / "pass-a").glob("block-*.md"))) == 7
    assert (run_dir / "figures").is_dir()
    assert not (run_dir / "pass-b").exists()


def test_manifest_is_private_and_records_provenance(
    tmp_path: Path, inputs: dict[str, Path]
) -> None:
    run_dir = _build(inputs, tmp_path / "calibration")
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["private"] is True
    assert manifest["seed"] == 7
    assert manifest["build"]["code_sha"]
    assert manifest["inputs"]["trusted"]["sha256"]
    assert manifest["inputs"]["failure"]["sha256"]
    assert manifest["inputs"]["shadow"]["manifest_sha256"]
    assert manifest["counts"]["primary"] == 120
    assert manifest["counts"]["repeats"] == 12
    assert manifest["counts"]["strata"] == {"trusted": 40, "failure": 40, "shadow": 40}
    # The private manifest legitimately carries the hidden answer keys and
    # split labels; the human sheets must not.
    assert "correct" in (run_dir / "manifest.json").read_text(encoding="utf-8")


def test_human_sheets_hide_keys_split_and_origin(
    tmp_path: Path, inputs: dict[str, Path]
) -> None:
    run_dir = _build(inputs, tmp_path / "calibration")
    sheets = (run_dir / "index.md").read_text(encoding="utf-8")
    for block in sorted((run_dir / "pass-a").glob("block-*.md")):
        sheets += block.read_text(encoding="utf-8")
    for forbidden in (
        "model_family",
        "solution_decomposition",
        "calibration",
        "validation",
        "repeat_of",
        "OpenStax University Physics",
    ):
        assert forbidden not in sheets


def test_no_figure_asset_leaks_repeat_or_origin(
    tmp_path: Path, inputs: dict[str, Path]
) -> None:
    run_dir = _build(inputs, tmp_path / "calibration")
    for figure in (run_dir / "figures").iterdir():
        assert figure.suffix == ".svg"
        assert figure.stem.split("-")[0] in {"cal", "rep"}


# --- Quotas and no partial success -----------------------------------------


def test_build_failure_leaves_no_final_directory(
    tmp_path: Path, inputs: dict[str, Path]
) -> None:
    trusted = _write_items(tmp_path / "short.json", "trusted", 39)
    with pytest.raises(ValueError):
        builder.build(
            trusted_path=trusted,
            failures_path=inputs["failures"],
            shadow_path=inputs["shadow"],
            out_root=tmp_path / "calibration",
            run_id="bad",
            seed=7,
        )
    assert not (tmp_path / "calibration" / "bad").exists()


# --- Input shapes and hardening --------------------------------------------


def test_accepts_items_and_candidates_shapes(
    tmp_path: Path, inputs: dict[str, Path]
) -> None:
    items = [builder.offline_problem_item("trusted", i) for i in range(50)]
    wrapped_items = tmp_path / "wrapped_items.json"
    wrapped_items.write_text(json.dumps({"items": items}), encoding="utf-8")
    wrapped_candidates = tmp_path / "wrapped_candidates.json"
    wrapped_candidates.write_text(
        json.dumps(
            {
                "candidates": [
                    builder.offline_problem_item("failure", i) for i in range(50)
                ]
            }
        ),
        encoding="utf-8",
    )
    run_dir = builder.build(
        trusted_path=wrapped_items,
        failures_path=wrapped_candidates,
        shadow_path=inputs["shadow"],
        out_root=tmp_path / "calibration",
        run_id="shapes",
        seed=7,
    )
    assert (run_dir / "_SUCCESS").exists()


def test_rejects_non_finite_numbers(tmp_path: Path) -> None:
    raw = '[{"id": "x", "difficulty": Infinity}]'
    path = tmp_path / "bad.json"
    path.write_text(raw, encoding="utf-8")
    with pytest.raises(ValueError, match="non-finite"):
        builder.load_problem_set(path, name="trusted")


def test_rejects_source_path_leakage(tmp_path: Path) -> None:
    item = builder.offline_problem_item("trusted", 0)
    item["source_file"] = "corpus/private.json"
    path = tmp_path / "leak.json"
    path.write_text(json.dumps([item]), encoding="utf-8")
    with pytest.raises(ValueError, match="source path field"):
        builder.load_problem_set(path, name="trusted")


def test_rejects_private_dataset_path(tmp_path: Path) -> None:
    gold_dir = tmp_path / "gold"
    gold_dir.mkdir()
    path = gold_dir / "items.json"
    path.write_text(json.dumps([]), encoding="utf-8")
    with pytest.raises(ValueError, match="gold"):
        builder.load_problem_set(path, name="trusted")


def test_rejects_recursive_dataset_marker(tmp_path: Path) -> None:
    item = builder.offline_problem_item("trusted", 0)
    item["note"] = "sourced from the tier 3 archive"
    path = tmp_path / "marked.json"
    path.write_text(json.dumps([item]), encoding="utf-8")
    with pytest.raises(ValueError, match="dataset marker"):
        builder.load_problem_set(path, name="trusted")


# --- Output-root safety ----------------------------------------------------


def test_rejects_arbitrary_tracked_output_root(
    tmp_path: Path, inputs: dict[str, Path]
) -> None:
    with pytest.raises(ValueError, match="calibration root or an OS temporary"):
        builder.build(
            trusted_path=inputs["trusted"],
            failures_path=inputs["failures"],
            shadow_path=inputs["shadow"],
            out_root=builder.REPO_ROOT / "docs_pgrep",
            run_id="tracked",
            seed=7,
        )


def test_rejects_symlink_output_component(
    tmp_path: Path, inputs: dict[str, Path]
) -> None:
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink component"):
        builder.build(
            trusted_path=inputs["trusted"],
            failures_path=inputs["failures"],
            shadow_path=inputs["shadow"],
            out_root=link / "calibration",
            run_id="sym",
            seed=7,
        )


# --- Shadow contract -------------------------------------------------------


def test_rejects_failed_shadow_run(tmp_path: Path) -> None:
    run = tmp_path / "failed-run"
    run.mkdir()
    (run / "_FAILED").write_text("no\n", encoding="utf-8")
    with pytest.raises(ValueError, match="_FAILED"):
        builder.load_shadow_run(run)


def test_rejects_unfinalized_shadow_run(tmp_path: Path) -> None:
    run = tmp_path / "partial-run"
    run.mkdir()
    with pytest.raises(ValueError, match="_SUCCESS"):
        builder.load_shadow_run(run)


def test_rejects_tampered_shadow_manifest(tmp_path: Path, shadow_run: Path) -> None:
    tampered = tmp_path / "offline-shadow"
    shutil.copytree(shadow_run, tampered)
    manifest = json.loads((tampered / "manifest.json").read_text(encoding="utf-8"))
    manifest["training_eligible"] = True
    (tampered / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="manifest contract|training"):
        builder.load_shadow_run(tampered)


def test_accepts_valid_shadow_run(shadow_run: Path) -> None:
    items, run_id, manifest_sha = builder.load_shadow_run(shadow_run)
    assert len(items) == 45
    assert run_id == "offline-shadow"
    assert len(manifest_sha) == 64
    families = {item["model_family"] for item in items}
    assert families == {"sol", "opus", "grok"}


# --- Publication fault injection -------------------------------------------


class _FailWrite(builder.PublicationIO):
    def __init__(self, target: str) -> None:
        self.target = target

    def write_text(self, path: Path, content: str) -> None:
        if path.name == self.target:
            raise OSError("injected write failure")
        super().write_text(path, content)


class _FailRename(builder.PublicationIO):
    def rename(self, source: Path, destination: Path) -> None:
        raise OSError("injected rename failure")


class _FailFsync(builder.PublicationIO):
    def __init__(self) -> None:
        self.calls = 0

    def fsync_dir(self, path: Path) -> None:
        self.calls += 1
        # Fail only the workspace temp fsync, letting cleanup's own fsync run.
        if self.calls == 2:
            raise OSError("injected fsync failure")
        super().fsync_dir(path)


class _CorruptFigure(builder.PublicationIO):
    def read_bytes(self, path: Path) -> bytes:
        data = super().read_bytes(path)
        if path.suffix == ".svg":
            return data + b"<!-- tamper -->"
        return data


def _assert_no_final(out_root: Path, run_id: str) -> None:
    assert not (out_root / run_id).exists()


@pytest.mark.parametrize(
    "io_factory",
    [
        lambda: _FailWrite("manifest.json"),
        lambda: _FailWrite("block-03.md"),
        _FailRename,
        _FailFsync,
        _CorruptFigure,
    ],
)
def test_injected_publication_failures_leave_no_final(
    tmp_path: Path, inputs: dict[str, Path], io_factory
) -> None:
    out_root = tmp_path / "calibration"
    with pytest.raises((OSError, ValueError)):
        builder.build(
            trusted_path=inputs["trusted"],
            failures_path=inputs["failures"],
            shadow_path=inputs["shadow"],
            out_root=out_root,
            run_id="fault",
            seed=7,
            io=io_factory(),
        )
    _assert_no_final(out_root, "fault")
    assert not (out_root / ".fault.lock").exists()


def test_publication_lock_collision_fails_closed(
    tmp_path: Path, inputs: dict[str, Path]
) -> None:
    out_root = tmp_path / "calibration"
    out_root.mkdir()
    (out_root / ".locked.lock").write_text("held\n", encoding="utf-8")
    with pytest.raises(ValueError, match="lock already exists"):
        builder.build(
            trusted_path=inputs["trusted"],
            failures_path=inputs["failures"],
            shadow_path=inputs["shadow"],
            out_root=out_root,
            run_id="locked",
            seed=7,
        )
    _assert_no_final(out_root, "locked")


def test_existing_run_directory_fails_closed(
    tmp_path: Path, inputs: dict[str, Path]
) -> None:
    out_root = tmp_path / "calibration"
    out_root.mkdir()
    (out_root / "dup").mkdir()
    with pytest.raises(ValueError, match="already exists"):
        builder.build(
            trusted_path=inputs["trusted"],
            failures_path=inputs["failures"],
            shadow_path=inputs["shadow"],
            out_root=out_root,
            run_id="dup",
            seed=7,
        )


# --- Blinding leak scan ----------------------------------------------------


def test_blinding_sentinel_does_not_leak(
    tmp_path: Path, inputs: dict[str, Path]
) -> None:
    sentinel = "ZZZ-blinding-sentinel-42"
    items = [builder.offline_problem_item("trusted", i) for i in range(50)]
    for item in items:
        item["source_excerpt"] = sentinel
    trusted = tmp_path / "sentinel.json"
    trusted.write_text(json.dumps(items), encoding="utf-8")
    run_dir = builder.build(
        trusted_path=trusted,
        failures_path=inputs["failures"],
        shadow_path=inputs["shadow"],
        out_root=tmp_path / "calibration",
        run_id="sentinel",
        seed=7,
    )
    sheets = (run_dir / "index.md").read_text(encoding="utf-8")
    for block in (run_dir / "pass-a").glob("block-*.md"):
        sheets += block.read_text(encoding="utf-8")
    assert sentinel not in sheets
    # The private manifest still retains the excerpt.
    assert sentinel in (run_dir / "manifest.json").read_text(encoding="utf-8")


def test_leak_scan_rejects_exposed_hidden_value() -> None:
    with pytest.raises(ValueError, match="blinding leak"):
        builder._assert_no_blinding_leak(
            ["a block mentioning OpenStax secret excerpt"],
            {"OpenStax secret excerpt"},
            context="test",
        )


def test_determinism_same_seed_same_bytes(
    tmp_path: Path, inputs: dict[str, Path]
) -> None:
    first = _build(inputs, tmp_path / "cal-a", run_id="det")
    second = _build(inputs, tmp_path / "cal-b", run_id="det")
    assert (first / "manifest.json").read_text(encoding="utf-8") == (
        second / "manifest.json"
    ).read_text(encoding="utf-8")
    for name in ("index.md",):
        assert (first / name).read_text(encoding="utf-8") == (second / name).read_text(
            encoding="utf-8"
        )
