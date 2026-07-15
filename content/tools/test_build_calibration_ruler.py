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
from pgrep.ai import model_backend, shadow_portfolio  # noqa: E402

# --- Fixtures --------------------------------------------------------------


def _clean_repo_state() -> tuple[str, str]:
    return ("a" * 40, "clean")


def _stable_attestation() -> builder.ExecutionAttestation:
    sources = {
        name: builder.SourceAttestation(
            loaded_sha256=character * 64,
            current_sha256=character * 64,
            head_blob_sha256=character * 64,
        )
        for name, character in {
            "build_calibration_ruler": "b",
            "calibration_ruler": "c",
            "calibration_sheet": "d",
            "shadow_foundry": "e",
            "shadow_portfolio": "f",
        }.items()
    }
    return builder.ExecutionAttestation(
        head_sha="a" * 40,
        tree_status="clean",
        source_hashes=sources,
    )


def _write_items(path: Path, stratum: str, count: int) -> Path:
    items = [builder.offline_problem_item(stratum, index) for index in range(count)]
    path.write_text(json.dumps(items), encoding="utf-8")
    return path


class _ProductionFixtureBackend:
    def __init__(self) -> None:
        self.calls = 0

    def complete(
        self,
        request: model_backend.ModelRequest,
    ) -> model_backend.ModelResult:
        self.calls += 1
        if request.role == "generator":
            candidate = builder.shadow_foundry._offline_candidate()
            candidate["stem"] = (
                "A particle moves uniformly in a circle. "
                f"Fixture variant {request.seed} has distinct wording."
            )
            text = json.dumps(candidate)
        else:
            text = json.dumps(
                {
                    "answer": "A",
                    "reasoning": f"{request.model.family} independent solve",
                    "confidence": 0.75,
                }
            )
        return model_backend.ModelResult(
            request_id=request.request_id,
            model_id=request.model.model_id,
            status="finished",
            text=text,
            agent_id=f"fixture-agent-{self.calls}",
            run_id=f"fixture-run-{self.calls}",
        )


def _production_fixture_environment() -> "builder.shadow_foundry.RunEnvironment":
    image_digest = "sha256:" + hashlib.sha256(b"fixture-worker").hexdigest()
    corpus = b"fixture-corpus"
    probe = builder.shadow_foundry.make_probe_metadata(
        [
            {"id": "gpt-5.6-sol-max", "parameters": [], "variants": []},
            {
                "id": "claude-opus-4-8-thinking-high-fast",
                "parameters": [],
                "variants": [],
            },
            {
                "id": "cursor-grok-4.5-high-fast",
                "parameters": [],
                "variants": [],
            },
        ],
        sdk_version="test-fixture-1",
    )
    return builder.shadow_foundry.RunEnvironment(
        code_sha="a" * 40,
        tree_status="clean",
        worker_image=image_digest,
        worker_image_digest=image_digest,
        corpus_index_fingerprint="sha256:" + hashlib.sha256(corpus).hexdigest(),
        probe=probe,
        synthetic=False,
        execution_mode="real",
        corpus_index_mtime_ns=0,
        corpus_index_size=len(corpus),
    )


def _write_production_shaped_shadow_run(
    root: Path,
    *,
    run_id: str,
    n: int,
    seed: int = builder.shadow_foundry.DEFAULT_SEED,
) -> Path:
    roles = builder.shadow_foundry._default_roles()
    environment = _production_fixture_environment()
    allocation = shadow_portfolio.allocate_families(n, seed=seed)
    recorder = builder.shadow_foundry._RecordingBackend(
        _ProductionFixtureBackend(),
        secrets=(),
    )
    chunks = builder.shadow_foundry.sanitize_retrieved(
        builder.shadow_foundry._offline_search(builder.shadow_foundry.DEFAULT_TOPIC)
    )
    candidates: list[dict[str, object]] = []
    raw_responses: list[dict[str, object]] = []
    for slot, origin in enumerate(allocation):
        recorder.slot = slot
        recorder.bind_retrieval(chunks, origin=origin)
        record = shadow_portfolio.run_candidate(
            topic=builder.shadow_foundry.DEFAULT_TOPIC,
            retrieved=chunks,
            origin=origin,
            roles=roles,
            backend=recorder,
            seed=seed + slot,
        )
        builder.shadow_foundry._bind_candidate_replay_metadata(
            record,
            topic=builder.shadow_foundry.DEFAULT_TOPIC,
            seed=seed + slot,
            retrieved=chunks,
        )
        candidate, raw = builder.shadow_foundry._sanitize_candidate_evidence(
            record,
            slot=slot,
            secrets=(),
        )
        candidates.append(candidate)
        raw_responses.extend(raw)
    manifest = builder.shadow_foundry.build_run_manifest(
        run_id=run_id,
        status="success",
        roles=roles,
        environment=environment,
        topic=builder.shadow_foundry.DEFAULT_TOPIC,
        expected_candidate_count=n,
        seed=seed,
        allocation=allocation,
        candidates=candidates,
        failures=[],
        raw_responses=raw_responses,
    )
    artifacts = builder.shadow_foundry._publication_artifact_bytes(
        candidates,
        [],
        manifest["probe"],
        raw_responses,
    )
    builder.shadow_foundry.validate_manifest(
        manifest,
        candidates=candidates,
        failures=[],
        raw_responses=raw_responses,
        artifact_bytes=artifacts,
        publication_run_id=run_id,
    )
    run_dir = root / run_id
    run_dir.mkdir(mode=0o700)
    payloads = {
        "manifest.json": manifest,
        "candidates.json": candidates,
        "failures.json": [],
        "probe.json": manifest["probe"],
        "raw-responses.json": raw_responses,
    }
    for filename, payload in payloads.items():
        (run_dir / filename).write_text(
            builder.shadow_foundry._strict_json(payload),
            encoding="utf-8",
        )
    (run_dir / "_SUCCESS").write_text("ok\n", encoding="utf-8")
    return run_dir


@pytest.fixture(scope="session")
def shadow_run(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("shadow-runs")
    return _write_production_shaped_shadow_run(
        root,
        run_id="test-shadow",
        n=45,
    )


def test_production_module_exposes_no_real_shaped_fixture_bypass() -> None:
    assert not hasattr(builder, "_production_shaped_test_shadow_run")


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
    assert set(manifest["build"]["source_hashes"]) == {
        "build_calibration_ruler",
        "calibration_ruler",
        "calibration_sheet",
        "shadow_foundry",
        "shadow_portfolio",
    }
    for hashes in manifest["build"]["source_hashes"].values():
        assert hashes["loaded_sha256"]
        assert hashes["current_sha256"]
        assert hashes["head_blob_sha256"]
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


@pytest.mark.parametrize(
    "module_name",
    [
        "build_calibration_ruler",
        "calibration_ruler",
        "calibration_sheet",
        "shadow_foundry",
        "shadow_portfolio",
    ],
)
def test_dirty_loaded_then_reverted_source_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
    module_name: str,
) -> None:
    current_by_path = {
        path: path.read_bytes() for path in builder._SOURCE_PATHS.values()
    }
    loaded = dict(builder._LOADED_SOURCE_SHA256)
    loaded[module_name] = hashlib.sha256(b"dirty loaded source").hexdigest()
    monkeypatch.setattr(
        builder,
        "_LOADED_SOURCE_SHA256",
        loaded,
    )
    with pytest.raises(ValueError, match=module_name):
        builder._capture_execution_attestation(
            repo_state_fn=_clean_repo_state,
            head_blob_fn=lambda _head, path: current_by_path[path],
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


@pytest.mark.parametrize(
    "module_name",
    [
        "build_calibration_ruler",
        "calibration_ruler",
        "calibration_sheet",
        "shadow_foundry",
        "shadow_portfolio",
    ],
)
def test_during_build_source_or_head_drift_removes_final_output(
    tmp_path: Path,
    inputs: dict[str, Path],
    module_name: str,
) -> None:
    entry = _stable_attestation()
    changed_sources = dict(entry.source_hashes)
    original = changed_sources[module_name]
    changed_sources[module_name] = builder.SourceAttestation(
        loaded_sha256=original.loaded_sha256,
        current_sha256="0" * 64,
        head_blob_sha256=original.head_blob_sha256,
    )
    changed = builder.ExecutionAttestation(
        head_sha="f" * 40,
        tree_status="clean",
        source_hashes=changed_sources,
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
    with pytest.raises(ValueError, match="figure asset.*forbidden word"):
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


def _scan_single_svg(body: str) -> None:
    source = builder.offline_problem_item("trusted", 1)
    source["correct"] = "C"
    source["stem"] = f'Configuration.<div class="pg-figure">{body}</div>'
    item = builder.calibration_ruler.RulerItem.from_source_item(
        source,
        review_id="item-0001",
        stratum="trusted",
        split="calibration",
    )
    ruler = builder.calibration_ruler.RulerManifest(items=(item,), seed=7)
    assets = builder.calibration_sheet.figure_assets(ruler)
    builder._assert_blind_figure_assets(assets, ruler=ruler, model_ids=())


@pytest.mark.parametrize(
    "body",
    [
        '<text xmlns="http://www.w3.org/2000/svg">answer</text>',
        '<title xmlns="http://www.w3.org/2000/svg">ANSWERS</title>',
        '<desc xmlns="http://www.w3.org/2000/svg">solution</desc>',
        '<style xmlns="http://www.w3.org/2000/svg">/* correct */</style>',
        '<text xmlns="http://www.w3.org/2000/svg" aria-label="incorrect">A</text>',
        '<text xmlns="http://www.w3.org/2000/svg">key</text>',
        '<title xmlns="http://www.w3.org/2000/svg">choice</title>',
        '<desc xmlns="http://www.w3.org/2000/svg">choices</desc>',
        '<style xmlns="http://www.w3.org/2000/svg">/* recommendation */</style>',
        '<text xmlns="http://www.w3.org/2000/svg" aria-label="confidence">A</text>',
        '<text xmlns="http://www.w3.org/2000/svg">model</text>',
        '<title xmlns="http://www.w3.org/2000/svg">modelOutput</title>',
        '<desc xmlns="http://www.w3.org/2000/svg">verifier-decision</desc>',
        '<text xmlns="http://www.w3.org/2000/svg">answ&#101;r</text>',
        '<text xmlns="http://www.w3.org/2000/svg">ｓｏｌｕｔｉｏｎ</text>',
    ],
)
def test_svg_forbidden_answer_words_fail_closed(body: str) -> None:
    svg = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">{body}</svg>'
    with pytest.raises(ValueError, match="figure asset.*forbidden word"):
        _scan_single_svg(svg)


def test_svg_css_escapes_are_decoded_before_word_scan() -> None:
    decoded = builder._decode_svg_scan_text(r".\61 nswer \63 hoice")
    assert decoded == ".answer choice"
    assert builder._forbidden_svg_words(decoded) == {"answer", "choice"}


def test_svg_related_words_and_physics_labels_are_allowed() -> None:
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">'
        "<title>Vectors A and B are orthogonal.</title>"
        "<desc>C is heat capacity; E is electric field.</desc>"
        "<text>Answering requires modeling and a correction factor.</text>"
        "<style>/* keyed shaft; confident estimate; verification step; "
        "recommending refinement */</style>"
        "</svg>"
    )
    _scan_single_svg(svg)


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
    with pytest.raises(ValueError, match="figure asset.*forbidden word"):
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


@pytest.mark.parametrize(
    ("channel", "disclosure"),
    [
        ("text", "answer: C"),
        ("title", "INTENDED ANSWER = C"),
        ("desc", "AnSwEr \t : \t C"),
        ("style", "/* intended_answer:C */"),
    ],
)
def test_svg_bare_and_intended_answer_assignments_fail(
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
        item["stem"] = f'Configuration {index}.<div class="pg-figure">{figure}</div>'
    trusted = tmp_path / f"bare-answer-{channel}.json"
    trusted.write_text(json.dumps(items), encoding="utf-8")
    with pytest.raises(ValueError, match="figure asset.*forbidden word"):
        builder.build(
            trusted_path=trusted,
            failures_path=inputs["failures"],
            shadow_path=inputs["shadow"],
            out_root=tmp_path / "calibration",
            run_id=f"bare-answer-{channel}",
            seed=7,
            allow_test_paths=True,
            _repo_state_fn=_clean_repo_state,
        )


@pytest.mark.parametrize(
    ("channel", "disclosure", "stored_key"),
    [
        ("text", "answer is C", "C"),
        ("title", "Intended answer is choice B.", "B"),
        ("desc", "D is the answer!", "D"),
        ("style", "/* choice E is correct */", "E"),
        ("text", "correct choice is A", "A"),
        ("desc", "THE ANSWER... IS [C]!", "C"),
        ("text", "answer&#32;is&#32;C", "C"),
    ],
)
def test_svg_natural_language_answer_disclosures_fail(
    tmp_path: Path,
    inputs: dict[str, Path],
    channel: str,
    disclosure: str,
    stored_key: str,
) -> None:
    body = (
        f"<style>{disclosure}</style>"
        if channel == "style"
        else f"<{channel}>{disclosure}</{channel}>"
    )
    figure = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">{body}</svg>'
    items = [builder.offline_problem_item("trusted", index) for index in range(50)]
    for index, item in enumerate(items):
        item["correct"] = stored_key
        item["stem"] = f'Configuration {index}.<div class="pg-figure">{figure}</div>'
    trusted = tmp_path / f"natural-answer-{channel}-{stored_key}.json"
    trusted.write_text(json.dumps(items), encoding="utf-8")
    with pytest.raises(ValueError, match="figure asset.*forbidden word"):
        builder.build(
            trusted_path=trusted,
            failures_path=inputs["failures"],
            shadow_path=inputs["shadow"],
            out_root=tmp_path / "calibration",
            run_id=f"natural-answer-{channel}-{stored_key}",
            seed=7,
            allow_test_paths=True,
            _repo_state_fn=_clean_repo_state,
        )


def test_svg_variable_label_prose_is_not_an_answer_leak(
    tmp_path: Path,
    inputs: dict[str, Path],
) -> None:
    figure = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">'
        "<title>Vector A is perpendicular to B.</title>"
        "<desc>C is the heat capacity; E is the electric field.</desc>"
        "<text>Label C marks the contour. The field depends on variable C.</text>"
        "<style>/* The gauge selection is arbitrary. */</style>"
        "</svg>"
    )
    items = [builder.offline_problem_item("trusted", index) for index in range(50)]
    for index, item in enumerate(items):
        item["correct"] = "C"
        item["stem"] = f'Configuration {index}.<div class="pg-figure">{figure}</div>'
    trusted = tmp_path / "variable-label-prose.json"
    trusted.write_text(json.dumps(items), encoding="utf-8")
    run_dir = builder.build(
        trusted_path=trusted,
        failures_path=inputs["failures"],
        shadow_path=inputs["shadow"],
        out_root=tmp_path / "calibration",
        run_id="variable-label-prose",
        seed=7,
        allow_test_paths=True,
        _repo_state_fn=_clean_repo_state,
    )
    assert (run_dir / "_SUCCESS").is_file()


def test_svg_related_answer_substring_is_not_a_false_positive(
    tmp_path: Path,
    inputs: dict[str, Path],
) -> None:
    figure = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">'
        "<text>Answering requires a correction factor; label C marks the axis.</text>"
        "</svg>"
    )
    items = [builder.offline_problem_item("trusted", index) for index in range(50)]
    for index, item in enumerate(items):
        item["correct"] = "C"
        item["stem"] = f'Configuration {index}.<div class="pg-figure">{figure}</div>'
    trusted = tmp_path / "related-answer-substring.json"
    trusted.write_text(json.dumps(items), encoding="utf-8")
    run_dir = builder.build(
        trusted_path=trusted,
        failures_path=inputs["failures"],
        shadow_path=inputs["shadow"],
        out_root=tmp_path / "calibration",
        run_id="related-answer-substring",
        seed=7,
        allow_test_paths=True,
        _repo_state_fn=_clean_repo_state,
    )
    assert (run_dir / "_SUCCESS").is_file()


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
    with pytest.raises(ValueError, match="figure asset.*forbidden word"):
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
