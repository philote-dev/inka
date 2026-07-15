# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Offline tests for the private blind calibration ruler builder CLI."""

from __future__ import annotations

import hashlib
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


def _clean_repo_state() -> tuple[str, str]:
    return ("a" * 40, "clean")


def _stable_attestation() -> builder.ExecutionAttestation:
    digest = "b" * 64
    return builder.ExecutionAttestation(
        head_sha="a" * 40,
        tree_status="clean",
        loaded_builder_sha256=digest,
        current_builder_sha256=digest,
        head_builder_sha256=digest,
        core_source_sha256={
            "calibration_ruler": "c" * 64,
            "calibration_sheet": "d" * 64,
            "shadow_foundry": "e" * 64,
        },
    )


def _write_items(path: Path, stratum: str, count: int) -> Path:
    items = [builder.offline_problem_item(stratum, index) for index in range(count)]
    path.write_text(json.dumps(items), encoding="utf-8")
    return path


@pytest.fixture(scope="session")
def shadow_run(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("shadow-runs")
    return builder._production_shaped_test_shadow_run(
        root,
        run_id="test-shadow",
        n=45,
    )


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
        allow_test_paths=True,
        _repo_state_fn=_clean_repo_state,
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
    assert manifest["build"]["tree_status"] == "clean"
    assert manifest["build"]["builder_source"]["loaded_sha256"]
    assert manifest["build"]["builder_source"]["current_sha256"]
    assert manifest["build"]["builder_source"]["head_blob_sha256"]
    assert set(manifest["build"]["core_sources"]) == {
        "calibration_ruler",
        "calibration_sheet",
        "shadow_foundry",
    }
    assert manifest["inputs"]["trusted"]["sha256"]
    assert manifest["inputs"]["failure"]["sha256"]
    assert manifest["inputs"]["shadow"]["manifest_sha256"]
    assert manifest["counts"]["primary"] == 120
    assert manifest["counts"]["repeats"] == 12
    assert manifest["counts"]["strata"] == {"trusted": 40, "failure": 40, "shadow": 40}
    # The private manifest legitimately carries the hidden answer keys and
    # split labels; the human sheets must not.
    assert "correct" in (run_dir / "manifest.json").read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("repo_state", "message"),
    [
        (("unknown", "clean"), "code SHA"),
        (("a" * 40, "dirty"), "clean git tree"),
    ],
)
def test_build_requires_resolved_clean_repo_state_before_publication(
    tmp_path: Path,
    inputs: dict[str, Path],
    repo_state: tuple[str, str],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        builder.build(
            trusted_path=inputs["trusted"],
            failures_path=inputs["failures"],
            shadow_path=inputs["shadow"],
            out_root=tmp_path / "calibration",
            run_id="dirty-build",
            seed=7,
            allow_test_paths=True,
            _repo_state_fn=lambda: repo_state,
        )
    assert not (tmp_path / "calibration" / "dirty-build").exists()


def test_dirty_loaded_then_reverted_builder_source_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    current = Path(builder.__file__).resolve().read_bytes()
    monkeypatch.setattr(
        builder,
        "_LOADED_BUILDER_SHA256",
        hashlib.sha256(b"dirty loaded source").hexdigest(),
    )
    with pytest.raises(ValueError, match="loaded builder source"):
        builder._capture_execution_attestation(
            repo_state_fn=_clean_repo_state,
            head_blob_fn=lambda _head, _path: current,
        )


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
        assert figure.stem.startswith("item-")


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
            allow_test_paths=True,
            _repo_state_fn=_clean_repo_state,
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
        allow_test_paths=True,
        _repo_state_fn=_clean_repo_state,
    )
    assert (run_dir / "_SUCCESS").exists()


def test_rejects_non_finite_numbers(tmp_path: Path) -> None:
    raw = '[{"id": "x", "difficulty": Infinity}]'
    path = tmp_path / "bad.json"
    path.write_text(raw, encoding="utf-8")
    with pytest.raises(ValueError, match="non-finite"):
        builder.load_problem_set(path, name="trusted", allow_test_paths=True)


def test_rejects_source_path_leakage(tmp_path: Path) -> None:
    item = builder.offline_problem_item("trusted", 0)
    item["source_file"] = "corpus/private.json"
    path = tmp_path / "leak.json"
    path.write_text(json.dumps([item]), encoding="utf-8")
    with pytest.raises(ValueError, match="source path field"):
        builder.load_problem_set(path, name="trusted", allow_test_paths=True)


def test_rejects_private_dataset_path(tmp_path: Path) -> None:
    gold_dir = tmp_path / "gold"
    gold_dir.mkdir()
    path = gold_dir / "items.json"
    path.write_text(json.dumps([]), encoding="utf-8")
    with pytest.raises(ValueError, match="gold"):
        builder.load_problem_set(path, name="trusted", allow_test_paths=True)


def test_rejects_recursive_dataset_marker(tmp_path: Path) -> None:
    item = builder.offline_problem_item("trusted", 0)
    item["note"] = "sourced from the tier 3 archive"
    path = tmp_path / "marked.json"
    path.write_text(json.dumps([item]), encoding="utf-8")
    with pytest.raises(ValueError, match="dataset marker"):
        builder.load_problem_set(path, name="trusted", allow_test_paths=True)


def test_scans_complete_wrapper_before_extracting_items(tmp_path: Path) -> None:
    path = tmp_path / "wrapped.json"
    path.write_text(
        json.dumps(
            {
                "items": [
                    builder.offline_problem_item("trusted", index)
                    for index in range(50)
                ],
                "original_path": "../held-out/private.json",
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="path field|dataset marker"):
        builder.load_problem_set(path, name="trusted", allow_test_paths=True)


@pytest.mark.parametrize(
    "key",
    [
        "original_path",
        "input_file",
        "sourceFilename",
        "fixture_directory",
        "workingDir",
    ],
)
def test_rejects_generic_path_and_file_key_variants(
    tmp_path: Path,
    key: str,
) -> None:
    item = builder.offline_problem_item("trusted", 0)
    item[key] = "private/input.json"
    path = tmp_path / f"{key}.json"
    path.write_text(json.dumps([item]), encoding="utf-8")
    with pytest.raises(ValueError, match="path field"):
        builder.load_problem_set(path, name="trusted", allow_test_paths=True)


@pytest.mark.parametrize(
    "value",
    [
        "../private/input.json",
        "/Users/reviewer/input.json",
        r"C:\private\input.json",
        "content/run/private.json",
        "figures/diagram.svg",
        "images/plot.png",
        "images/photo.jpg",
        "images/photo.jpeg",
        "tex/equation.tex",
        "notes/review.md",
        "notes/review.txt",
        "data/items.json",
        "data/items.yaml",
        "papers/source.pdf",
    ],
)
def test_rejects_filesystem_looking_values(tmp_path: Path, value: str) -> None:
    item = builder.offline_problem_item("trusted", 0)
    item["note"] = value
    path = tmp_path / "filesystem-value.json"
    path.write_text(json.dumps([item]), encoding="utf-8")
    with pytest.raises(ValueError, match="filesystem"):
        builder.load_problem_set(path, name="trusted", allow_test_paths=True)


def test_named_source_citation_is_not_treated_as_filesystem_path(
    tmp_path: Path,
) -> None:
    item = builder.offline_problem_item("trusted", 0)
    item["source_ref"] = "OpenStax University Physics, Volume 1, section 7.4"
    path = tmp_path / "citation.json"
    path.write_text(json.dumps([item]), encoding="utf-8")
    loaded = builder.load_problem_set(
        path,
        name="trusted",
        allow_test_paths=True,
    )
    assert loaded[0]["source_ref"] == item["source_ref"]


def test_gold_foil_prose_is_allowed_in_problem_content(tmp_path: Path) -> None:
    item = builder.offline_problem_item("trusted", 0)
    item["stem"] = "Rutherford scatters alpha particles from a gold foil nucleus."
    item["choices"] = [
        "The gold nucleus is compact.",
        "The foil is electrically neutral overall.",
        "The atom is mostly empty space.",
        "The alpha particle is positively charged.",
        "The gold foil is thin.",
    ]
    path = tmp_path / "gold-foil-prose.json"
    path.write_text(json.dumps([item]), encoding="utf-8")
    loaded = builder.load_problem_set(
        path,
        name="trusted",
        allow_test_paths=True,
    )
    stem = loaded[0]["stem"]
    assert isinstance(stem, str)
    assert "gold foil nucleus" in stem


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("note", "content/gold/items.json"),
        ("dataset_id", "gold-set"),
        ("source_id", "gold-17"),
        ("source_path", "gold-17"),
    ],
)
def test_structured_private_dataset_markers_are_rejected(
    tmp_path: Path,
    key: str,
    value: str,
) -> None:
    item = builder.offline_problem_item("trusted", 0)
    item[key] = value
    path = tmp_path / "structured-marker.json"
    path.write_text(json.dumps([item]), encoding="utf-8")
    with pytest.raises(ValueError, match="dataset marker|path field|filesystem"):
        builder.load_problem_set(path, name="trusted", allow_test_paths=True)


def test_rejects_symlink_input_parent(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    path = _write_items(real / "trusted.json", "trusted", 50)
    link = tmp_path / "link"
    link.symlink_to(real, target_is_directory=True)
    assert path.is_file()
    with pytest.raises(ValueError, match="symlink component"):
        builder.load_problem_set(
            link / "trusted.json",
            name="trusted",
            allow_test_paths=True,
        )


def test_rejects_dot_dot_input_escape(tmp_path: Path) -> None:
    inside = tmp_path / "inside"
    inside.mkdir()
    path = _write_items(tmp_path / "trusted.json", "trusted", 50)
    assert path.is_file()
    with pytest.raises(ValueError, match="path escape"):
        builder.load_problem_set(
            inside / ".." / "trusted.json",
            name="trusted",
            allow_test_paths=True,
        )


def test_reads_inputs_once_then_reattests_each_fingerprint(
    tmp_path: Path,
    inputs: dict[str, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    counts: dict[Path, int] = {}
    original = builder._read_file_once

    def counted(path: Path, *, name: str) -> bytes:
        resolved = path.resolve()
        counts[resolved] = counts.get(resolved, 0) + 1
        return original(path, name=name)

    monkeypatch.setattr(builder, "_read_file_once", counted)
    _build(inputs, tmp_path / "calibration", run_id="single-read")
    assert counts[inputs["trusted"].resolve()] == 2
    assert counts[inputs["failures"].resolve()] == 2
    for filename in (
        "manifest.json",
        "candidates.json",
        "failures.json",
        "probe.json",
        "raw-responses.json",
    ):
        assert counts[(inputs["shadow"] / filename).resolve()] == 2
    assert counts[(inputs["shadow"] / "_SUCCESS").resolve()] == 2


# --- Output-root safety ----------------------------------------------------


def test_rejects_arbitrary_tracked_output_root(
    tmp_path: Path, inputs: dict[str, Path]
) -> None:
    with pytest.raises(ValueError, match="exact repository calibration root"):
        builder.build(
            trusted_path=inputs["trusted"],
            failures_path=inputs["failures"],
            shadow_path=inputs["shadow"],
            out_root=builder.REPO_ROOT / "docs_pgrep",
            run_id="tracked",
            seed=7,
        )


def test_temp_paths_require_internal_flag(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="exact repository"):
        builder.validate_output_root(tmp_path / "calibration")


def test_cli_does_not_expose_test_path_override() -> None:
    with pytest.raises(SystemExit):
        builder.main(["--allow-test-paths"])


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
            allow_test_paths=True,
            _repo_state_fn=_clean_repo_state,
        )


# --- Shadow contract -------------------------------------------------------


def test_offline_shadow_run_is_synthetic_and_rejected(tmp_path: Path) -> None:
    run_dir = builder.offline_shadow_run(
        tmp_path / "shadow-runs",
        run_id="offline-shadow",
        n=45,
    )
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["synthetic"] is True
    assert manifest["execution_mode"] == "test-fake"
    with pytest.raises(ValueError, match="synthetic|real execution"):
        builder.load_shadow_run(run_dir, allow_test_paths=True)


def test_rejects_failed_shadow_run(tmp_path: Path) -> None:
    run = tmp_path / "failed-run"
    run.mkdir()
    (run / "_FAILED").write_text("no\n", encoding="utf-8")
    with pytest.raises(ValueError, match="_FAILED"):
        builder.load_shadow_run(run, allow_test_paths=True)


def test_rejects_unfinalized_shadow_run(tmp_path: Path) -> None:
    run = tmp_path / "partial-run"
    run.mkdir()
    with pytest.raises(ValueError, match="_SUCCESS"):
        builder.load_shadow_run(run, allow_test_paths=True)


def test_rejects_tampered_shadow_manifest(tmp_path: Path, shadow_run: Path) -> None:
    tampered = tmp_path / "test-shadow"
    shutil.copytree(shadow_run, tampered)
    manifest = json.loads((tampered / "manifest.json").read_text(encoding="utf-8"))
    manifest["training_eligible"] = True
    (tampered / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="manifest contract|training"):
        builder.load_shadow_run(tampered, allow_test_paths=True)


def test_rejects_tampered_shadow_candidate_bytes(
    tmp_path: Path,
    shadow_run: Path,
) -> None:
    tampered = tmp_path / "test-shadow"
    shutil.copytree(shadow_run, tampered)
    candidates = tampered / "candidates.json"
    candidates.write_bytes(candidates.read_bytes() + b" ")
    with pytest.raises(ValueError, match="candidates.json.*digest"):
        builder.load_shadow_run(tampered, allow_test_paths=True)


def test_rejects_tampered_parsed_candidate_payload(
    tmp_path: Path,
    shadow_run: Path,
) -> None:
    tampered = tmp_path / "test-shadow"
    shutil.copytree(shadow_run, tampered)
    candidates_path = tampered / "candidates.json"
    manifest_path = tampered / "manifest.json"
    candidates = json.loads(candidates_path.read_text(encoding="utf-8"))
    candidates[0]["candidate"]["stem"] = "Changed after finalized publication."
    candidate_bytes = (
        json.dumps(candidates, indent=2, sort_keys=True, allow_nan=False) + "\n"
    ).encode()
    candidates_path.write_bytes(candidate_bytes)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["artifact_digests"]["candidates_json"] = (
        "sha256:" + hashlib.sha256(candidate_bytes).hexdigest()
    )
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="candidate payload hash"):
        builder.load_shadow_run(tampered, allow_test_paths=True)


def test_rejects_candidate_and_manifest_rehash_without_matching_raw_response(
    tmp_path: Path,
    shadow_run: Path,
) -> None:
    tampered = tmp_path / "test-shadow"
    shutil.copytree(shadow_run, tampered)
    candidates_path = tampered / "candidates.json"
    manifest_path = tampered / "manifest.json"
    candidates = json.loads(candidates_path.read_text(encoding="utf-8"))
    candidate = candidates[0]
    candidate["candidate"]["stem"] = "Coordinated candidate and manifest tamper."
    authored_hash = builder.shadow_foundry._parsed_candidate_hash(
        candidate["candidate"]
    )
    final_trace = next(
        trace
        for trace in candidate["generator"]["traces"]
        if trace["parser_outcome"] == "parsed"
    )
    final_trace["parsed_candidate_sha256"] = authored_hash
    candidate_bytes = (
        json.dumps(candidates, indent=2, sort_keys=True, allow_nan=False) + "\n"
    ).encode()
    candidates_path.write_bytes(candidate_bytes)

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["candidate_payload_hashes"] = (
        builder.shadow_foundry._candidate_payload_hashes(candidates)
    )
    manifest["request_traces"] = (
        builder.shadow_foundry.canonical_candidate_trace_summaries(candidates)
    )
    manifest["artifact_digests"]["candidates_json"] = (
        "sha256:" + hashlib.sha256(candidate_bytes).hexdigest()
    )
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="raw response|raw parsed|final raw"):
        builder.load_shadow_run(tampered, allow_test_paths=True)


def test_ruler_independently_reparses_raw_generator_response(
    tmp_path: Path,
    shadow_run: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tampered = tmp_path / "test-shadow"
    shutil.copytree(shadow_run, tampered)
    candidates_path = tampered / "candidates.json"
    manifest_path = tampered / "manifest.json"
    candidates = json.loads(candidates_path.read_text(encoding="utf-8"))
    candidates[0]["candidate"]["stem"] = "Tampered candidate with re-signed metadata."
    authored_hash = builder.shadow_foundry._parsed_candidate_hash(
        candidates[0]["candidate"]
    )
    final_trace = next(
        trace
        for trace in candidates[0]["generator"]["traces"]
        if trace["parser_outcome"] == "parsed"
    )
    final_trace["parsed_candidate_sha256"] = authored_hash
    candidate_bytes = (
        json.dumps(candidates, indent=2, sort_keys=True, allow_nan=False) + "\n"
    ).encode()
    candidates_path.write_bytes(candidate_bytes)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["candidate_payload_hashes"] = (
        builder.shadow_foundry._candidate_payload_hashes(candidates)
    )
    manifest["request_traces"] = (
        builder.shadow_foundry.canonical_candidate_trace_summaries(candidates)
    )
    manifest["artifact_digests"]["candidates_json"] = (
        "sha256:" + hashlib.sha256(candidate_bytes).hexdigest()
    )
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        builder.shadow_foundry, "validate_manifest", lambda *a, **k: None
    )
    monkeypatch.setattr(
        builder.shadow_foundry,
        "validate_raw_response_binding",
        lambda *a, **k: None,
    )
    with pytest.raises(ValueError, match="independent raw response"):
        builder.load_shadow_run(tampered, allow_test_paths=True)


@pytest.mark.parametrize(
    ("execution_mode", "synthetic"),
    [
        ("offline-self-check", True),
        ("test-fake", True),
        ("real", True),
    ],
)
def test_rejects_synthetic_or_non_real_shadow_run(
    tmp_path: Path,
    shadow_run: Path,
    execution_mode: str,
    synthetic: bool,
) -> None:
    tampered = tmp_path / "test-shadow"
    shutil.copytree(shadow_run, tampered)
    path = tampered / "manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["execution_mode"] = execution_mode
    manifest["synthetic"] = synthetic
    path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="synthetic|real execution"):
        builder.load_shadow_run(tampered, allow_test_paths=True)


def test_accepts_candidates_json_path(shadow_run: Path) -> None:
    from_directory = builder.load_shadow_run(shadow_run, allow_test_paths=True)
    from_candidates = builder.load_shadow_run(
        shadow_run / "candidates.json",
        allow_test_paths=True,
    )
    assert from_candidates == from_directory


def test_accepts_valid_shadow_run(shadow_run: Path) -> None:
    items, run_id, manifest_sha = builder.load_shadow_run(
        shadow_run, allow_test_paths=True
    )
    assert len(items) == 45
    assert run_id == "test-shadow"
    assert len(manifest_sha) == 64
    families = {item["model_family"] for item in items}
    assert families == {"sol", "opus", "grok"}
    manifest = json.loads((shadow_run / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["synthetic"] is False
    assert manifest["execution_mode"] == "real"


# --- Publication fault injection -------------------------------------------


class _FailWrite(builder.PublicationIO):
    def __init__(self, target: str) -> None:
        self.target = target

    def write_text(self, path: Path, content: str) -> None:
        if path.name == self.target:
            raise OSError("injected write failure")
        super().write_text(path, content)


class _FailReserve(builder.PublicationIO):
    def reserve_final(self, path: Path) -> None:
        raise OSError("injected final reservation failure")


class _FailLink(builder.PublicationIO):
    def link_payload(self, source: Path, destination: Path) -> None:
        raise OSError("injected payload publication failure")


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


class _FailMarker(builder.PublicationIO):
    def write_marker(self, path: Path, content: str) -> None:
        raise OSError("injected marker failure")


class _FailPostMarkerSync(builder.PublicationIO):
    def __init__(self) -> None:
        self.marker_written = False

    def write_marker(self, path: Path, content: str) -> None:
        super().write_marker(path, content)
        self.marker_written = True

    def fsync_dir(self, path: Path) -> None:
        if self.marker_written and (path / "_SUCCESS").exists():
            self.marker_written = False
            raise OSError("injected post-marker directory fsync failure")
        super().fsync_dir(path)


class _FailReleaseOnce(builder.PublicationIO):
    def __init__(self) -> None:
        self.calls = 0

    def remove_lock(
        self,
        path: Path,
        identity: builder.LockIdentity,
    ) -> None:
        self.calls += 1
        if self.calls == 1:
            raise OSError("injected lock release failure")
        super().remove_lock(path, identity)


class _FailLockWrite(builder.PublicationIO):
    def write_lock(self, fd: int, content: bytes) -> None:
        raise OSError("injected lock write failure")


class _FailLockFsync(builder.PublicationIO):
    def sync_lock(self, fd: int) -> None:
        raise OSError("injected lock fsync failure")


class _ConcurrentEmptyDestination(builder.PublicationIO):
    def reserve_final(self, path: Path) -> None:
        path.mkdir(mode=0o700, exist_ok=False)
        super().reserve_final(path)


class _RecordingOrder(builder.PublicationIO):
    def __init__(self) -> None:
        self.events: list[str] = []

    def remove_lock(
        self,
        path: Path,
        identity: builder.LockIdentity,
    ) -> None:
        self.events.append("remove_lock")
        super().remove_lock(path, identity)

    def write_marker(self, path: Path, content: str) -> None:
        self.events.append("write_marker")
        super().write_marker(path, content)


class _MutateInputOnLink(builder.PublicationIO):
    def __init__(self, input_path: Path) -> None:
        self.input_path = input_path
        self.mutated = False

    def link_payload(self, source: Path, destination: Path) -> None:
        if not self.mutated:
            self.input_path.write_bytes(self.input_path.read_bytes() + b" ")
            self.mutated = True
        super().link_payload(source, destination)


def _assert_no_final(out_root: Path, run_id: str) -> None:
    assert not (out_root / run_id).exists()


@pytest.mark.parametrize(
    "io_factory",
    [
        lambda: _FailWrite("manifest.json"),
        lambda: _FailWrite("block-03.md"),
        _FailReserve,
        _FailLink,
        _FailFsync,
        _CorruptFigure,
        _FailMarker,
        _FailPostMarkerSync,
        _FailReleaseOnce,
        _FailLockWrite,
        _FailLockFsync,
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
            allow_test_paths=True,
            _repo_state_fn=_clean_repo_state,
        )
    _assert_no_final(out_root, "fault")
    assert not (out_root / ".fault.lock").exists()


@pytest.mark.parametrize("io", [_FailLockWrite(), _FailLockFsync()])
def test_open_lock_failure_removes_owned_lock(tmp_path: Path, io) -> None:
    lock = tmp_path / ".owned.lock"
    with pytest.raises(OSError):
        io.open_lock(lock)
    assert not lock.exists()


def test_lock_is_removed_before_success_marker(
    tmp_path: Path,
    inputs: dict[str, Path],
) -> None:
    io = _RecordingOrder()
    run_dir = builder.build(
        trusted_path=inputs["trusted"],
        failures_path=inputs["failures"],
        shadow_path=inputs["shadow"],
        out_root=tmp_path / "calibration",
        run_id="ordered",
        seed=7,
        io=io,
        allow_test_paths=True,
        _repo_state_fn=_clean_repo_state,
    )
    assert io.events == ["remove_lock", "write_marker"]
    assert (run_dir / "_SUCCESS").is_file()


def test_concurrent_empty_destination_is_never_replaced(
    tmp_path: Path,
    inputs: dict[str, Path],
) -> None:
    out_root = tmp_path / "calibration"
    with pytest.raises(FileExistsError):
        builder.build(
            trusted_path=inputs["trusted"],
            failures_path=inputs["failures"],
            shadow_path=inputs["shadow"],
            out_root=out_root,
            run_id="concurrent",
            seed=7,
            io=_ConcurrentEmptyDestination(),
            allow_test_paths=True,
            _repo_state_fn=_clean_repo_state,
        )
    destination = out_root / "concurrent"
    assert destination.is_dir()
    assert not any(destination.iterdir())
    assert not (destination / "_SUCCESS").exists()


def test_during_build_input_drift_removes_final_output(
    tmp_path: Path,
    inputs: dict[str, Path],
) -> None:
    out_root = tmp_path / "calibration"
    with pytest.raises(ValueError, match="input fingerprint changed"):
        builder.build(
            trusted_path=inputs["trusted"],
            failures_path=inputs["failures"],
            shadow_path=inputs["shadow"],
            out_root=out_root,
            run_id="input-drift",
            seed=7,
            io=_MutateInputOnLink(inputs["trusted"]),
            allow_test_paths=True,
            _attestation_fn=_stable_attestation,
        )
    assert not (out_root / "input-drift").exists()
    assert not (out_root / "input-drift" / "_SUCCESS").exists()


def test_during_build_source_or_head_drift_removes_final_output(
    tmp_path: Path,
    inputs: dict[str, Path],
) -> None:
    entry = _stable_attestation()
    changed = builder.ExecutionAttestation(
        head_sha="f" * 40,
        tree_status="clean",
        loaded_builder_sha256=entry.loaded_builder_sha256,
        current_builder_sha256=entry.current_builder_sha256,
        head_builder_sha256=entry.head_builder_sha256,
        core_source_sha256={
            **entry.core_source_sha256,
            "shadow_foundry": "0" * 64,
        },
    )
    attestations = iter((entry, changed))
    out_root = tmp_path / "calibration"
    with pytest.raises(ValueError, match="execution attestation changed"):
        builder.build(
            trusted_path=inputs["trusted"],
            failures_path=inputs["failures"],
            shadow_path=inputs["shadow"],
            out_root=out_root,
            run_id="source-drift",
            seed=7,
            allow_test_paths=True,
            _attestation_fn=lambda: next(attestations),
        )
    assert not (out_root / "source-drift").exists()
    assert not (out_root / "source-drift" / "_SUCCESS").exists()


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
            allow_test_paths=True,
            _repo_state_fn=_clean_repo_state,
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
            allow_test_paths=True,
            _repo_state_fn=_clean_repo_state,
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
        allow_test_paths=True,
        _repo_state_fn=_clean_repo_state,
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


@pytest.mark.parametrize("channel", ["title", "desc", "text", "style"])
def test_svg_hidden_content_channels_fail_before_publication(
    tmp_path: Path,
    inputs: dict[str, Path],
    channel: str,
) -> None:
    sentinel = f"HIDDEN-SOURCE-{channel.upper()}-SENTINEL"
    if channel == "style":
        body = f"<style>.axis{{--hidden-token:{sentinel};}}</style>"
    else:
        body = f"<{channel}>{sentinel}</{channel}>"
    figure = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">'
        f'{body}<path d="M0 0 L10 10"/></svg>'
    )
    items = [builder.offline_problem_item("trusted", index) for index in range(50)]
    for index, item in enumerate(items):
        item["source_ref"] = sentinel
        item["stem"] = (
            f'Trusted configuration {index}.<div class="pg-figure">{figure}</div>'
        )
    trusted = tmp_path / f"trusted-{channel}.json"
    trusted.write_text(json.dumps(items), encoding="utf-8")
    out_root = tmp_path / "calibration"
    with pytest.raises(ValueError, match="figure asset.*hidden"):
        builder.build(
            trusted_path=trusted,
            failures_path=inputs["failures"],
            shadow_path=inputs["shadow"],
            out_root=out_root,
            run_id=f"svg-{channel}",
            seed=7,
            allow_test_paths=True,
            _repo_state_fn=_clean_repo_state,
        )
    assert not out_root.exists()


def test_svg_forbidden_metadata_term_fails_before_publication(
    tmp_path: Path,
    inputs: dict[str, Path],
) -> None:
    figure = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">'
        "<text>model_family</text></svg>"
    )
    items = [builder.offline_problem_item("trusted", index) for index in range(50)]
    for index, item in enumerate(items):
        item["stem"] = (
            f'Trusted configuration {index}.<div class="pg-figure">{figure}</div>'
        )
    trusted = tmp_path / "trusted-metadata.json"
    trusted.write_text(json.dumps(items), encoding="utf-8")
    with pytest.raises(ValueError, match="figure asset.*metadata"):
        builder.build(
            trusted_path=trusted,
            failures_path=inputs["failures"],
            shadow_path=inputs["shadow"],
            out_root=tmp_path / "calibration",
            run_id="svg-metadata",
            seed=7,
            allow_test_paths=True,
            _repo_state_fn=_clean_repo_state,
        )


@pytest.mark.parametrize(
    ("channel", "disclosure"),
    [
        ("title", "key: C"),
        ("desc", "correct answer: C"),
        ("text", "answer_key: C"),
        (
            "style",
            "/* your_answer: C; recommendation: KEEP; confidence: 0.99; */",
        ),
    ],
)
def test_svg_structured_answer_disclosure_channels_fail(
    tmp_path: Path,
    inputs: dict[str, Path],
    channel: str,
    disclosure: str,
) -> None:
    body = (
        f"<style>{disclosure}</style>"
        if channel == "style"
        else f"<{channel}>{disclosure}</{channel}>"
    )
    figure = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">{body}</svg>'
    items = [builder.offline_problem_item("trusted", index) for index in range(50)]
    for index, item in enumerate(items):
        item["correct"] = "C"
        item["stem"] = (
            f'Gold foil configuration {index}.<div class="pg-figure">{figure}</div>'
        )
    trusted = tmp_path / f"answer-disclosure-{channel}.json"
    trusted.write_text(json.dumps(items), encoding="utf-8")
    with pytest.raises(ValueError, match="figure asset.*answer|metadata"):
        builder.build(
            trusted_path=trusted,
            failures_path=inputs["failures"],
            shadow_path=inputs["shadow"],
            out_root=tmp_path / "calibration",
            run_id=f"answer-{channel}",
            seed=7,
            allow_test_paths=True,
            _repo_state_fn=_clean_repo_state,
        )


def test_svg_bare_choice_letters_and_gold_foil_prose_are_allowed(
    tmp_path: Path,
    inputs: dict[str, Path],
) -> None:
    figure = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">'
        "<text>A B C D E, gold foil nucleus</text></svg>"
    )
    items = [builder.offline_problem_item("trusted", index) for index in range(50)]
    for index, item in enumerate(items):
        item["stem"] = (
            f'Gold foil configuration {index}.<div class="pg-figure">{figure}</div>'
        )
    trusted = tmp_path / "allowed-gold-foil-svg.json"
    trusted.write_text(json.dumps(items), encoding="utf-8")
    run_dir = builder.build(
        trusted_path=trusted,
        failures_path=inputs["failures"],
        shadow_path=inputs["shadow"],
        out_root=tmp_path / "calibration",
        run_id="allowed-gold-foil",
        seed=7,
        allow_test_paths=True,
        _repo_state_fn=_clean_repo_state,
    )
    assert (run_dir / "_SUCCESS").is_file()


def test_svg_additional_answer_and_verifier_metadata_fails(
    tmp_path: Path,
    inputs: dict[str, Path],
) -> None:
    disclosure = (
        "correct_key: C; correct_value: choice C; model_output: C; "
        "stored-key: C; verifier_decision: accept"
    )
    figure = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">'
        f"<text>{disclosure}</text></svg>"
    )
    items = [builder.offline_problem_item("trusted", index) for index in range(50)]
    for index, item in enumerate(items):
        item["correct"] = "C"
        item["stem"] = f'Configuration {index}.<div class="pg-figure">{figure}</div>'
    trusted = tmp_path / "additional-answer-metadata.json"
    trusted.write_text(json.dumps(items), encoding="utf-8")
    with pytest.raises(ValueError, match="figure asset.*answer|metadata"):
        builder.build(
            trusted_path=trusted,
            failures_path=inputs["failures"],
            shadow_path=inputs["shadow"],
            out_root=tmp_path / "calibration",
            run_id="answer-metadata",
            seed=7,
            allow_test_paths=True,
            _repo_state_fn=_clean_repo_state,
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
