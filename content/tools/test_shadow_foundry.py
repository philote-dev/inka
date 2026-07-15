# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Offline tests for the quarantined multi-model shadow-foundry CLI."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import sys
import threading
import types
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import _ai_path  # noqa: E402

_ai_path.add_ai_core()

import shadow_foundry  # noqa: E402
from pgrep.ai import (  # type: ignore[import-not-found]  # noqa: E402
    model_backend,
    shadow_portfolio,
)


def _roles() -> shadow_portfolio.ModelRoles:
    return shadow_portfolio.ModelRoles(
        sol=model_backend.ModelSpec("sol", "gpt-5.6-sol-max", "high"),
        opus=model_backend.ModelSpec(
            "opus",
            "claude-opus-4-8-thinking-high-fast",
            "high",
        ),
        grok=model_backend.ModelSpec(
            "grok",
            "cursor-grok-4.5-high-fast",
            "high",
        ),
    )


def _candidate() -> dict[str, object]:
    return {
        "stem": "A particle moves in a circle. Which statement is correct?",
        "choices": [
            "The speed is constant.",
            "The velocity is constant.",
            "The acceleration is zero.",
            "The momentum is zero.",
            "The radius must increase.",
        ],
        "key": "A",
        "distractors": [
            {
                "label": "B",
                "misconception_tag": "speed-is-velocity",
                "rationale": "Confuses constant speed with constant velocity.",
            },
            {
                "label": "C",
                "misconception_tag": "no-tangential-change",
                "rationale": "Ignores centripetal acceleration.",
            },
            {
                "label": "D",
                "misconception_tag": "vector-cancellation",
                "rationale": "Treats changing momentum as zero momentum.",
            },
            {
                "label": "E",
                "misconception_tag": "radius-drift",
                "rationale": "Assumes circular motion cannot stay bounded.",
            },
        ],
        "solution_decomposition": [
            {
                "subgoal": "UNIQUE_SUBGOAL_ALPHA_BLIND",
                "rubric": "UNIQUE_RUBRIC_BETA_BLIND",
            },
            {
                "subgoal": "Identify the invariant scalar.",
                "rubric": "Uses the definition of uniform circular motion.",
            },
        ],
        "problem_kind": "conceptual",
        "difficulty": 0.4,
        "confidence": 0.8,
        "computational": None,
        "refuse": False,
    }


def _retrieved() -> list[dict[str, object]]:
    return [
        {
            "chunk_id": "chunk-1",
            "source_ref": "OpenStax University Physics, p. 1",
            "source_title": "OpenStax University Physics",
            "text": "Uniform circular motion keeps speed constant while velocity changes.",
            "score": 0.95,
        }
    ]


class FakeBackend:
    """Records requests and returns deterministic generation/solve text."""

    def __init__(
        self,
        generator_replies: list[str] | None = None,
        *,
        fail_families: frozenset[str] | set[str] | None = None,
    ) -> None:
        self.generator_replies = list(
            generator_replies
            if generator_replies is not None
            else [json.dumps(_candidate())]
        )
        self.fail_families = frozenset(fail_families or ())
        self.requests: list[model_backend.ModelRequest] = []

    def complete(
        self,
        request: model_backend.ModelRequest,
    ) -> model_backend.ModelResult:
        self.requests.append(request)
        if request.model.family in self.fail_families:
            raise RuntimeError(f"{request.model.family} backend unavailable")
        if request.role == "generator":
            if not self.generator_replies:
                text = json.dumps(_candidate())
            else:
                text = self.generator_replies.pop(0)
                if not self.generator_replies:
                    self.generator_replies.append(text)
        else:
            text = json.dumps(
                {
                    "answer": "A",
                    "reasoning": f"{request.model.family} independent solve",
                    "confidence": 0.75,
                }
            )
        call = len(self.requests)
        return model_backend.ModelResult(
            request_id=request.request_id,
            model_id=request.model.model_id,
            status="finished",
            text=text,
            agent_id=f"agent-{call}",
            run_id=f"run-{call}",
        )


class MissingGrokBackend(FakeBackend):
    def __init__(self) -> None:
        super().__init__(fail_families={"grok"})


def _fake_search(query: str, k: int = 6, **_kwargs: object) -> list[dict[str, object]]:
    del query, k
    return _retrieved()


def test_shadow_run_is_atomic_and_has_no_training_artifacts(tmp_path: Path) -> None:
    candidates, manifest = shadow_foundry.offline_fixture(
        run_id="run-1",
        environment=_environment(),
    )
    run_dir = shadow_foundry.publish_run(
        tmp_path,
        "run-1",
        candidates=candidates,
        failures=[],
        manifest=manifest,
        allow_test_output=True,
    )
    assert (run_dir / "_SUCCESS").exists()
    assert (run_dir / "manifest.json").is_file()
    assert (run_dir / "candidates.json").is_file()
    assert (run_dir / "failures.json").is_file()
    assert not (run_dir / "preferences.jsonl").exists()
    assert not (run_dir / "accepted.json").exists()
    assert (
        json.loads((run_dir / "manifest.json").read_text())["training_eligible"]
        is False
    )


def test_shadow_run_publishes_independently_bound_raw_responses(
    tmp_path: Path,
) -> None:
    run_dir = shadow_foundry.run_shadow(
        roles=_roles(),
        backend=FakeBackend(),
        environment=_environment(),
        output_root=tmp_path,
        allow_test_output=True,
        search_fn=_fake_search,
        n=3,
        seed=7,
        topic="mechanics/circular-motion",
        run_id="raw-binding",
    )
    manifest = json.loads((run_dir / "manifest.json").read_text())
    candidates = json.loads((run_dir / "candidates.json").read_text())
    raw = json.loads((run_dir / "raw-responses.json").read_text())

    assert manifest["artifact_digests"]["raw_responses_json"] == (
        "sha256:"
        + hashlib.sha256((run_dir / "raw-responses.json").read_bytes()).hexdigest()
    )
    assert len(raw) == 9
    by_request = {response["request_id"]: response for response in raw}
    for candidate in candidates:
        traces = candidate["generator"]["traces"]
        final = next(trace for trace in traces if trace["parser_outcome"] == "parsed")
        response = by_request[final["request_id"]]
        assert response["response_hash"] == final["response_hash"]
        assert response["parsed_candidate_sha256"] == final["parsed_candidate_sha256"]
        assert response["parsed_candidate_sha256"].startswith("sha256:")


def test_raw_response_artifact_retains_generator_correction_chain(
    tmp_path: Path,
) -> None:
    valid = json.dumps(_candidate())
    run_dir = shadow_foundry.run_shadow(
        roles=_roles(),
        backend=FakeBackend([f"```json\n{valid}\n```", valid]),
        environment=_environment(),
        output_root=tmp_path,
        allow_test_output=True,
        search_fn=_fake_search,
        n=3,
        seed=7,
        topic="mechanics/circular-motion",
        run_id="raw-corrections",
    )
    raw = json.loads((run_dir / "raw-responses.json").read_text())
    first_slot_generator = [
        response
        for response in raw
        if response["slot"] == 0 and response["role"] == "generator"
    ]
    assert [response["phase"] for response in first_slot_generator] == [
        "generation",
        "schema_correction",
    ]
    assert [response["attempt"] for response in first_slot_generator] == [0, 1]
    assert first_slot_generator[0]["parser_outcome"] == "parse_error"
    assert first_slot_generator[0]["parsed_candidate_sha256"] is None
    assert first_slot_generator[1]["parser_outcome"] == "parsed"
    assert first_slot_generator[1]["parsed_candidate_sha256"].startswith("sha256:")


def test_failed_generator_retains_safe_raw_correction_evidence(
    tmp_path: Path,
) -> None:
    invalid = "```json\n{}\n```"
    with pytest.raises(shadow_foundry.ShadowRunFailed) as raised:
        shadow_foundry.run_shadow(
            roles=_roles(),
            backend=FakeBackend([invalid, invalid, invalid]),
            environment=_environment(),
            output_root=tmp_path,
            allow_test_output=True,
            search_fn=_fake_search,
            n=3,
            seed=7,
            topic="mechanics/circular-motion",
            run_id="failed-raw-corrections",
        )
    raw = json.loads((raised.value.run_dir / "raw-responses.json").read_text())
    generator = [
        record
        for record in raw
        if record["role"] == "generator" and record["slot"] == 0
    ]
    assert [record["attempt"] for record in generator] == [0, 1, 2]
    assert all(record["parser_outcome"] == "parse_error" for record in generator)
    assert all(record["parsed_candidate_sha256"] is None for record in generator)


def test_raw_responses_are_secret_redacted_before_persistence(
    tmp_path: Path,
) -> None:
    secret = "cursor_secret_DO_NOT_PERSIST"
    candidate = _candidate()
    candidate["stem"] = f"{candidate['stem']} {secret}"
    run_dir = shadow_foundry.run_shadow(
        roles=_roles(),
        backend=FakeBackend([json.dumps(candidate)]),
        environment=_environment(),
        output_root=tmp_path,
        allow_test_output=True,
        search_fn=_fake_search,
        n=3,
        seed=7,
        topic="mechanics/circular-motion",
        run_id="raw-redaction",
        secrets=[secret],
    )
    raw_text = (run_dir / "raw-responses.json").read_text()
    assert secret not in raw_text
    assert "[REDACTED]" in raw_text


@pytest.mark.parametrize(
    "unsafe",
    [
        "content/gold/items.json",
        "../private/response.json",
    ],
)
def test_raw_response_is_private_marker_and_path_scanned(unsafe: str) -> None:
    record = shadow_portfolio.run_candidate(
        topic="mechanics/circular-motion",
        retrieved=_retrieved(),
        origin="sol",
        roles=_roles(),
        backend=FakeBackend(),
        seed=7,
    )
    trace = record["generator"]["traces"][0]
    trace["result"]["text"] = unsafe
    with pytest.raises(shadow_foundry.ShadowLeakageError):
        shadow_foundry._raw_response_record(
            trace,
            slot=0,
            choice_order=None,
            binding=shadow_foundry._trace_binding(
                slot=0,
                origin="sol",
                role="generator",
                model_family="sol",
            ),
            secrets=(),
            parsed_candidate_sha256=None,
        )


def test_offline_environment_is_explicitly_synthetic_test_fake() -> None:
    environment = shadow_foundry._offline_environment()
    assert environment.synthetic is True
    assert environment.execution_mode == "test-fake"


def test_synthetic_run_cannot_publish_in_production_shadow_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    production_root = tmp_path / "shadow-foundry"
    monkeypatch.setattr(shadow_foundry, "QUARANTINE_ROOT", production_root)
    monkeypatch.setattr(
        shadow_foundry,
        "_git_ignored_quarantine_root",
        lambda: None,
    )
    candidates, manifest = shadow_foundry.offline_fixture(
        run_id="synthetic-production",
        environment=_environment(),
    )
    with pytest.raises(ValueError, match="synthetic.*production"):
        shadow_foundry.publish_run(
            production_root,
            "synthetic-production",
            candidates=candidates,
            failures=[],
            manifest=manifest,
        )
    assert not production_root.exists()


def _published_artifact_bytes(
    manifest: dict[str, object],
    candidates: Sequence[object],
    failures: Sequence[object],
    raw_responses: Sequence[object] | None = None,
) -> dict[str, bytes]:
    if raw_responses is None:
        raw_responses = getattr(candidates, "raw_responses", ())
    return {
        "candidates.json": shadow_foundry._strict_json(candidates).encode(),
        "failures.json": shadow_foundry._strict_json(failures).encode(),
        "probe.json": shadow_foundry._strict_json(manifest["probe"]).encode(),
        "raw-responses.json": shadow_foundry._strict_json(raw_responses).encode(),
    }


def _candidate_slot(candidate: dict[str, object]) -> int:
    slot = candidate["slot"]
    assert type(slot) is int
    return slot


def test_manifest_binds_candidate_payloads_and_artifact_bytes(
    tmp_path: Path,
) -> None:
    candidates, manifest = shadow_foundry.offline_fixture(
        run_id="bound-artifacts",
        environment=_environment(),
    )
    run_dir = shadow_foundry.publish_run(
        tmp_path,
        "bound-artifacts",
        candidates=candidates,
        failures=[],
        manifest=manifest,
        allow_test_output=True,
    )
    published = json.loads((run_dir / "manifest.json").read_text())
    assert published["synthetic"] is True
    assert (run_dir / "probe.json").is_file()
    assert published["candidate_payload_hashes"] == [
        {
            "slot": candidate["slot"],
            "sha256": shadow_foundry._canonical_hash(candidate["candidate"]),
        }
        for candidate in sorted(candidates, key=_candidate_slot)
    ]
    assert published["artifact_digests"] == {
        field: "sha256:" + hashlib.sha256((run_dir / filename).read_bytes()).hexdigest()
        for field, filename in {
            "candidates_json": "candidates.json",
            "failures_json": "failures.json",
            "probe_json": "probe.json",
            "raw_responses_json": "raw-responses.json",
        }.items()
    }


def test_validate_manifest_rejects_changed_candidate_payload() -> None:
    candidates, manifest = shadow_foundry.offline_fixture(
        run_id="changed-payload",
        environment=_environment(),
    )
    changed = copy.deepcopy(candidates)
    payload = changed[0]["candidate"]
    assert isinstance(payload, dict)
    payload["stem"] = "Changed after manifest creation."
    with pytest.raises(ValueError, match="candidate payload hash"):
        shadow_foundry.validate_manifest(
            manifest,
            candidates=changed,
            failures=[],
            raw_responses=getattr(candidates, "raw_responses", ()),
            artifact_bytes=_published_artifact_bytes(manifest, changed, []),
        )


def test_validate_manifest_rejects_changed_candidate_artifact_bytes() -> None:
    candidates, manifest = shadow_foundry.offline_fixture(
        run_id="changed-bytes",
        environment=_environment(),
    )
    artifacts = _published_artifact_bytes(manifest, candidates, [])
    artifacts["candidates.json"] += b" "
    with pytest.raises(ValueError, match="candidates.json.*digest"):
        shadow_foundry.validate_manifest(
            manifest,
            candidates=candidates,
            failures=[],
            raw_responses=getattr(candidates, "raw_responses", ()),
            artifact_bytes=artifacts,
        )


def test_publish_run_collision_fails(tmp_path: Path) -> None:
    candidates, manifest = shadow_foundry.offline_fixture(
        run_id="run-1",
        environment=_environment(),
    )
    shadow_foundry.publish_run(
        tmp_path,
        "run-1",
        candidates=candidates,
        failures=[],
        manifest=manifest,
        allow_test_output=True,
    )
    with pytest.raises(ValueError, match="already exists"):
        shadow_foundry.publish_run(
            tmp_path,
            "run-1",
            candidates=candidates,
            failures=[],
            manifest=manifest,
            allow_test_output=True,
        )


def test_publish_run_rejects_private_markers(tmp_path: Path) -> None:
    candidates, dirty = shadow_foundry.offline_fixture(
        run_id="run-dirty",
        environment=_environment(),
    )
    dirty["topic"] = "path content/gold/items.json"
    with pytest.raises(ValueError, match="private marker"):
        shadow_foundry.publish_run(
            tmp_path,
            "run-dirty",
            candidates=candidates,
            failures=[],
            manifest=dirty,
            allow_test_output=True,
        )
    assert not (tmp_path / "run-dirty").exists()
    assert not list(tmp_path.glob("*/_SUCCESS"))


def test_partial_portfolio_never_publishes_success(tmp_path: Path) -> None:
    with pytest.raises(shadow_foundry.ShadowRunFailed) as raised:
        shadow_foundry.run_shadow(
            roles=_roles(),
            backend=MissingGrokBackend(),
            environment=_environment(),
            output_root=tmp_path,
            allow_test_output=True,
            search_fn=_fake_search,
            n=3,
            seed=7,
            topic="mechanics/circular-motion",
            run_id="partial-1",
        )
    assert not list(tmp_path.glob("*/_SUCCESS"))
    assert (raised.value.run_dir / "_FAILED").is_file()


def test_run_shadow_requires_probe_ids_before_generation(tmp_path: Path) -> None:
    backend = FakeBackend()
    incomplete = shadow_foundry.RunEnvironment(
        code_sha="a" * 40,
        tree_status="clean",
        worker_image="pgrep-shadow-worker:test",
        worker_image_digest="sha256:" + ("b" * 64),
        corpus_index_fingerprint="sha256:" + ("c" * 64),
        probe=shadow_foundry.make_probe_metadata(
            [{"id": "gpt-5.6-sol-max", "parameters": [], "variants": []}],
            sdk_version="0.1.9",
        ),
        synthetic=True,
    )
    with pytest.raises(shadow_foundry.ShadowRunFailed) as raised:
        shadow_foundry.run_shadow(
            roles=_roles(),
            backend=backend,
            environment=incomplete,
            output_root=tmp_path,
            allow_test_output=True,
            search_fn=_fake_search,
            n=3,
            seed=7,
            topic="mechanics/circular-motion",
            run_id="probe-miss",
        )
    assert backend.requests == []
    assert not list(tmp_path.glob("*/_SUCCESS"))
    assert (raised.value.run_dir / "_FAILED").is_file()


def test_run_shadow_rejects_auto_and_duplicate_ids(tmp_path: Path) -> None:
    roles = shadow_portfolio.ModelRoles(
        sol=model_backend.ModelSpec("sol", "auto", "high"),
        opus=model_backend.ModelSpec(
            "opus",
            "claude-opus-4-8-thinking-high-fast",
            "high",
        ),
        grok=model_backend.ModelSpec(
            "grok",
            "cursor-grok-4.5-high-fast",
            "high",
        ),
    )
    with pytest.raises(shadow_foundry.ShadowRunFailed) as raised:
        shadow_foundry.run_shadow(
            roles=roles,
            backend=FakeBackend(),
            environment=_environment(),
            output_root=tmp_path,
            allow_test_output=True,
            search_fn=_fake_search,
            n=3,
            seed=7,
            topic="mechanics/circular-motion",
            run_id="auto-1",
        )
    assert (raised.value.run_dir / "_FAILED").is_file()


def test_sanitize_chunks_keeps_only_sandbox_safe_fields() -> None:
    chunks = shadow_foundry.sanitize_retrieved(
        [
            {
                "chunk_id": "chunk-1",
                "source_ref": "OpenStax, p. 1",
                "text": "Speed is scalar.",
                "source_file": "/secret/corpus/file.pdf",
                "source_title": "OpenStax",
                "page": 1,
                "score": 0.0,
            }
        ]
    )
    assert chunks == [
        {
            "chunk_id": "chunk-1",
            "source_ref": "OpenStax, p. 1",
            "source_title": "OpenStax",
            "text": "Speed is scalar.",
            "score": 0.0,
        }
    ]


def test_sanitize_chunks_rejects_private_markers_and_paths() -> None:
    with pytest.raises(ValueError, match="private marker|source path"):
        shadow_foundry.sanitize_retrieved(
            [
                {
                    "chunk_id": "chunk-bad",
                    "source_ref": "content/heldout/form.json",
                    "source_title": "Unsafe",
                    "text": "leaky",
                    "score": 0.9,
                }
            ]
        )


def test_run_shadow_publishes_complete_portfolio(tmp_path: Path) -> None:
    backend = FakeBackend()
    run_dir = shadow_foundry.run_shadow(
        roles=_roles(),
        backend=backend,
        environment=_environment(),
        output_root=tmp_path,
        allow_test_output=True,
        search_fn=_fake_search,
        n=3,
        seed=7,
        topic="mechanics/circular-motion",
        run_id="full-1",
    )
    assert (run_dir / "_SUCCESS").exists()
    manifest = json.loads((run_dir / "manifest.json").read_text())
    candidates = json.loads((run_dir / "candidates.json").read_text())
    failures = json.loads((run_dir / "failures.json").read_text())
    assert manifest["training_eligible"] is False
    assert manifest["code"]["sha"] == "a" * 40
    assert {role["model_id"] for role in manifest["roles"].values()} == {
        "gpt-5.6-sol-max",
        "claude-opus-4-8-thinking-high-fast",
        "cursor-grok-4.5-high-fast",
    }
    assert {c["origin_family"] for c in candidates} == {"sol", "opus", "grok"}
    assert failures == []
    assert "probe" in manifest
    assert "request_traces" in manifest
    assert not (run_dir / "preferences.jsonl").exists()
    assert not (run_dir / "accepted.json").exists()


def test_verifier_prompts_contain_neither_stored_key_nor_decomposition(
    tmp_path: Path,
) -> None:
    backend = FakeBackend()
    shadow_foundry.run_shadow(
        roles=_roles(),
        backend=backend,
        environment=_environment(),
        output_root=tmp_path,
        allow_test_output=True,
        search_fn=_fake_search,
        n=3,
        seed=7,
        topic="mechanics/circular-motion",
        run_id="blind-1",
    )
    verifier_requests = [req for req in backend.requests if req.role == "verifier"]
    assert len(verifier_requests) == 6
    for request in verifier_requests:
        blob = f"{request.system}\n{request.user}"
        assert "UNIQUE_SUBGOAL_ALPHA_BLIND" not in blob
        assert "UNIQUE_RUBRIC_BETA_BLIND" not in blob
        assert "solution_decomposition" not in blob
        assert '"key"' not in blob
        assert "stored key" not in blob.lower()
        assert "NOT told the intended answer" in request.system


def test_validate_exact_roles_requires_distinct_probed_ids() -> None:
    roles = _roles()
    shadow_foundry.validate_exact_roles(
        roles,
        [
            {"id": "gpt-5.6-sol-max"},
            {"id": "claude-opus-4-8-thinking-high-fast"},
            {"id": "cursor-grok-4.5-high-fast"},
        ],
    )
    with pytest.raises(ValueError, match="exact model"):
        shadow_foundry.validate_exact_roles(
            roles,
            [{"id": "gpt-5.6-sol-max"}],
        )


def test_self_check_is_offline_and_succeeds(
    tmp_path: Path,
) -> None:
    assert shadow_foundry._self_check_at(tmp_path, allow_test_output=True) == 0
    successes = list(tmp_path.glob("*/_SUCCESS"))
    assert len(successes) == 1
    run_dir = successes[0].parent
    manifest = json.loads((run_dir / "manifest.json").read_text())
    assert manifest["training_eligible"] is False
    assert not (run_dir / "preferences.jsonl").exists()


def test_format_probe_lists_models() -> None:
    text, payload = shadow_foundry.format_probe(
        [
            {"id": "gpt-5.6-sol-max", "name": "Sol"},
            {"id": "claude-opus-4-8-thinking-high-fast"},
        ]
    )
    assert "gpt-5.6-sol-max" in text
    assert payload["models"][0]["id"] == "gpt-5.6-sol-max"


def test_main_self_check_exit_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called: list[bool] = []
    monkeypatch.setattr(
        shadow_foundry,
        "self_check",
        lambda: called.append(True) or 0,
    )
    assert shadow_foundry.main(["--self-check"]) == 0
    assert called == [True]


def _probe_metadata() -> dict[str, object]:
    return shadow_foundry.make_probe_metadata(
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
        sdk_version="0.1.9",
        probed_at="2026-07-15T10:00:00Z",
    )


def _environment() -> shadow_foundry.RunEnvironment:
    return shadow_foundry.RunEnvironment(
        code_sha="a" * 40,
        tree_status="dirty",
        worker_image="pgrep-shadow-worker:0123456789abcdef",
        worker_image_digest="sha256:" + ("b" * 64),
        corpus_index_fingerprint="sha256:" + ("c" * 64),
        probe=_probe_metadata(),
        synthetic=True,
        corpus_index_mtime_ns=123456789,
        corpus_index_size=4096,
    )


@pytest.mark.parametrize(
    ("family", "model_id"),
    [
        ("sol", "claude-opus-4-8-for-sol"),
        ("opus", "cursor-grok-4.5-for-opus"),
        ("grok", "gpt-5.6-sol-for-grok"),
        ("sol", "gpt-5.5-sol-max"),
        ("opus", "claude-opus-4-7-thinking-high"),
        ("grok", "cursor-grok-4.4-high-fast"),
    ],
)
def test_exact_roles_require_semantic_family_identity(
    family: str,
    model_id: str,
) -> None:
    roles = _roles()
    invalid = shadow_portfolio.ModelRoles(
        sol=(
            model_backend.ModelSpec("sol", model_id, "high")
            if family == "sol"
            else roles.sol
        ),
        opus=(
            model_backend.ModelSpec("opus", model_id, "high")
            if family == "opus"
            else roles.opus
        ),
        grok=(
            model_backend.ModelSpec("grok", model_id, "high")
            if family == "grok"
            else roles.grok
        ),
    )
    with pytest.raises(ValueError, match="family identity"):
        shadow_foundry.validate_exact_roles(
            invalid,
            _probe_metadata()["models"],
        )


def test_retrieval_projection_preserves_provenance_without_source_path() -> None:
    chunks = shadow_foundry.sanitize_retrieved(
        [
            {
                "chunk_id": "chunk-1",
                "source_ref": "OpenStax University Physics, p. 1",
                "source_title": "OpenStax University Physics",
                "source_file": "/private/corpus/book.pdf",
                "text": "Uniform circular motion keeps speed constant.",
                "score": 0.91,
            }
        ]
    )
    assert chunks == [
        {
            "chunk_id": "chunk-1",
            "source_ref": "OpenStax University Physics, p. 1",
            "source_title": "OpenStax University Physics",
            "text": "Uniform circular motion keeps speed constant.",
            "score": 0.91,
        }
    ]
    assert "source_file" not in chunks[0]


def test_incomplete_manifest_cannot_publish_success(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="manifest"):
        shadow_foundry.publish_run(
            tmp_path,
            "incomplete",
            candidates=[_candidate()],
            failures=[],
            manifest={"mode": "shadow", "training_eligible": False},
            allow_test_output=True,
        )
    assert not list(tmp_path.rglob("_SUCCESS"))


def test_nested_success_manifest_contract_is_strict(tmp_path: Path) -> None:
    candidates, manifest = shadow_foundry.offline_fixture(
        run_id="nested-incomplete",
        environment=_environment(),
    )
    del manifest["worker"]["image_digest"]
    with pytest.raises(ValueError, match="worker"):
        shadow_foundry.publish_run(
            tmp_path,
            "nested-incomplete",
            candidates=candidates,
            failures=[],
            manifest=manifest,
            allow_test_output=True,
        )
    assert not list(tmp_path.rglob("_SUCCESS"))


def test_candidate_failure_publishes_finalized_diagnostic(tmp_path: Path) -> None:
    backend = MissingGrokBackend()
    with pytest.raises(shadow_foundry.ShadowRunFailed) as raised:
        shadow_foundry.run_shadow(
            roles=_roles(),
            backend=backend,
            output_root=tmp_path,
            allow_test_output=True,
            search_fn=_fake_search,
            n=3,
            seed=7,
            topic="mechanics/circular-motion",
            run_id="failed-1",
            environment=_environment(),
        )
    run_dir = raised.value.run_dir
    assert (run_dir / "_FAILED").is_file()
    assert not (run_dir / "_SUCCESS").exists()
    failures = json.loads((run_dir / "failures.json").read_text())
    assert failures
    assert failures[0]["error_type"] == "RuntimeError"
    manifest = json.loads((run_dir / "manifest.json").read_text())
    assert manifest["status"] == "failed"
    assert manifest["training_eligible"] is False


def test_success_manifest_has_replay_and_environment_metadata(tmp_path: Path) -> None:
    run_dir = shadow_foundry.run_shadow(
        roles=_roles(),
        backend=FakeBackend(),
        output_root=tmp_path,
        allow_test_output=True,
        search_fn=_fake_search,
        n=3,
        seed=7,
        topic="mechanics/circular-motion",
        run_id="auditable-1",
        environment=_environment(),
    )
    manifest = json.loads((run_dir / "manifest.json").read_text())
    assert manifest["mode"] == "shadow"
    assert manifest["status"] == "success"
    assert manifest["expected_candidate_count"] == 3
    assert manifest["candidate_count"] == 3
    assert manifest["failure_count"] == 0
    assert manifest["origins"] == ["grok", "opus", "sol"]
    assert manifest["code"] == {"sha": "a" * 40, "tree_status": "dirty"}
    assert manifest["worker"]["image_digest"] == "sha256:" + ("b" * 64)
    assert manifest["probe"]["sdk_version"] == "0.1.9"
    assert manifest["probe"]["model_catalog_hash"].startswith("sha256:")
    assert manifest["corpus_index"]["fingerprint"] == "sha256:" + ("c" * 64)
    assert len(manifest["request_traces"]) >= 9
    assert all(trace["request_hash"] for trace in manifest["request_traces"])
    assert all(trace["actual_model_id"] for trace in manifest["request_traces"])
    assert all(trace["agent_id"] for trace in manifest["request_traces"])
    assert all(trace["run_id"] for trace in manifest["request_traces"])
    verifier_traces = [
        trace for trace in manifest["request_traces"] if trace["role"] == "verifier"
    ]
    assert all(trace["choice_order"] for trace in verifier_traces)
    assert all(trace["run_id"].startswith("run-") for trace in verifier_traces)


def test_every_non_refused_candidate_has_bound_provenance(tmp_path: Path) -> None:
    run_dir = shadow_foundry.run_shadow(
        roles=_roles(),
        backend=FakeBackend(),
        output_root=tmp_path,
        allow_test_output=True,
        search_fn=_fake_search,
        n=3,
        seed=7,
        topic="mechanics/circular-motion",
        run_id="provenance-1",
        environment=_environment(),
    )
    records = json.loads((run_dir / "candidates.json").read_text())
    for record in records:
        candidate = record["candidate"]
        if not candidate["refuse"]:
            assert candidate["source_ref"]
            assert candidate["provenance"]["source_title"]
            assert candidate["provenance"]["support_score"] >= 0.45


class FailingPublicationIO(shadow_foundry.PublicationIO):
    def __init__(self, stage: str) -> None:
        self.stage = stage

    def dumps(self, value: object) -> str:
        if self.stage == "json":
            raise ValueError("injected JSON failure")
        return super().dumps(value)

    def create_lock(self, path: Path) -> int:
        if self.stage == "lock":
            raise OSError("injected lock failure")
        return super().create_lock(path)

    def write_payload(self, path: Path, content: str) -> None:
        if self.stage == "write":
            raise OSError("injected write failure")
        super().write_payload(path, content)

    def write_marker(self, path: Path, content: str) -> None:
        if self.stage == "marker":
            raise OSError("injected marker failure")
        super().write_marker(path, content)


class CollisionPublicationIO(shadow_foundry.PublicationIO):
    def reserve_final(self, path: Path) -> None:
        path.mkdir()
        (path / "foreign").write_text("foreign", encoding="utf-8")
        raise FileExistsError("injected collision")


@pytest.mark.parametrize("stage", ["json", "lock", "write", "marker"])
def test_publication_failures_leave_no_false_marker_or_temp(
    tmp_path: Path,
    stage: str,
) -> None:
    candidates, manifest = shadow_foundry.offline_fixture(
        run_id=f"fault-{stage}",
        environment=_environment(),
    )
    with pytest.raises((OSError, ValueError)):
        shadow_foundry.publish_run(
            tmp_path,
            f"fault-{stage}",
            candidates=candidates,
            failures=[],
            manifest=manifest,
            allow_test_output=True,
            io=FailingPublicationIO(stage),
        )
    assert not list(tmp_path.rglob("_SUCCESS"))
    assert not list(tmp_path.rglob("_FAILED"))
    assert not list(tmp_path.glob(".*.tmp"))
    assert not list(tmp_path.glob(".*.lock"))
    assert not (tmp_path / f"fault-{stage}").exists()


def test_publication_collision_cleans_lock_and_temp_without_overwrite(
    tmp_path: Path,
) -> None:
    candidates, manifest = shadow_foundry.offline_fixture(
        run_id="collision-race",
        environment=_environment(),
    )
    with pytest.raises(FileExistsError, match="collision"):
        shadow_foundry.publish_run(
            tmp_path,
            "collision-race",
            candidates=candidates,
            failures=[],
            manifest=manifest,
            allow_test_output=True,
            io=CollisionPublicationIO(),
        )
    assert not list(tmp_path.rglob("_SUCCESS"))
    assert not list(tmp_path.glob(".*.tmp"))
    assert not list(tmp_path.glob(".*.lock"))
    assert (tmp_path / "collision-race" / "foreign").read_text() == "foreign"


def test_cli_rejects_arbitrary_output_argument() -> None:
    with pytest.raises(SystemExit) as raised:
        shadow_foundry.main(["--self-check", "--out", "tracked/output"])
    assert raised.value.code == 2


def test_output_root_rejects_symlink_components(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    linked = tmp_path / "linked"
    linked.symlink_to(real, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        shadow_foundry.validate_output_root(
            linked / "shadow-foundry",
            allow_test_output=True,
        )


def test_output_root_rejects_arbitrary_temp_without_internal_opt_in(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError, match="exact git-ignored"):
        shadow_foundry.validate_output_root(tmp_path)


def test_real_sandbox_wiring_discovers_builds_and_pins_image() -> None:
    endpoint = types.SimpleNamespace(
        kind="docker",
        socket=Path("/var/run/docker.sock"),
    )
    observed: dict[str, object] = {"configs": []}

    class FakeSandbox:
        def __init__(self, config, **kwargs):  # noqa: ANN001
            observed["configs"].append(config)
            observed["kwargs"] = kwargs

        def image_digest(self) -> str:
            return "sha256:" + ("d" * 64)

        def build_image(self, *, context=None):  # noqa: ANN001
            observed["context"] = context
            return observed["configs"][0].image

    prepared = shadow_foundry.prepare_real_sandbox(
        "cursor_test_key",
        runtime_detector=lambda: "docker",
        runtime_discoverer=lambda runtime: endpoint,
        sandbox_factory=FakeSandbox,
    )
    tagged, immutable = observed["configs"]
    assert tagged.runtime == "docker"
    assert tagged.socket == "/var/run/docker.sock"
    assert tagged.image.startswith("pgrep-shadow-worker:")
    assert immutable.image == "sha256:" + ("d" * 64)
    assert observed["context"] == shadow_foundry.WORKER_CONTEXT
    assert prepared.image == "sha256:" + ("d" * 64)
    assert prepared.image_digest == "sha256:" + ("d" * 64)


def test_real_shadow_cli_wires_host_retrieval(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    observed: dict[str, object] = {}
    prepared = shadow_foundry.PreparedSandbox(
        sandbox=object(),
        image="pgrep-shadow-worker:0123456789abcdef",
        image_digest="sha256:" + ("d" * 64),
        runtime="docker",
        socket="/var/run/docker.sock",
    )
    monkeypatch.setattr(shadow_foundry, "_load_api_key", lambda: "cursor_test_key")
    monkeypatch.setattr(
        shadow_foundry,
        "prepare_real_sandbox",
        lambda _key: prepared,
    )
    monkeypatch.setattr(
        shadow_foundry,
        "_real_probe",
        lambda _prepared: _probe_metadata(),
    )
    monkeypatch.setattr(
        shadow_foundry,
        "file_attestation",
        lambda _path: ("sha256:" + ("c" * 64), 123456789, 4096),
    )
    from pgrep.ai import retrieval

    monkeypatch.setattr(
        retrieval,
        "default_index_path",
        lambda: str(tmp_path / "corpus.db"),
    )

    def fake_search(query: str, *, k: int, db_path: str) -> list[dict[str, object]]:
        observed["retrieval"] = (query, k, db_path)
        return _retrieved()

    monkeypatch.setattr(retrieval, "search", fake_search)

    def fake_run_shadow(**kwargs: object) -> Path:
        search_fn = kwargs["search_fn"]
        search_fn("mechanics/circular-motion", 6)
        observed["run"] = kwargs
        return tmp_path / "published"

    monkeypatch.setattr(shadow_foundry, "run_shadow", fake_run_shadow)
    assert (
        shadow_foundry.main(
            [
                "--shadow",
                "--sol-model",
                "gpt-5.6-sol-max",
                "--opus-model",
                "claude-opus-4-8-thinking-high-fast",
                "--grok-model",
                "cursor-grok-4.5-high-fast",
            ]
        )
        == 0
    )
    assert observed["retrieval"][0] == "mechanics/circular-motion"
    assert observed["run"]["output_root"] == shadow_foundry.QUARANTINE_ROOT


def test_security_failure_aborts_after_first_failed_slot(tmp_path: Path) -> None:
    class SecurityBackend(FakeBackend):
        def complete(
            self,
            request: model_backend.ModelRequest,
        ) -> model_backend.ModelResult:
            self.requests.append(request)
            raise shadow_foundry.cursor_sandbox.SecurityCleanupError(
                "container cleanup failed"
            )

    backend = SecurityBackend()
    with pytest.raises(shadow_foundry.ShadowRunFailed) as raised:
        shadow_foundry.run_shadow(
            roles=_roles(),
            backend=backend,
            output_root=tmp_path,
            allow_test_output=True,
            search_fn=_fake_search,
            n=3,
            seed=7,
            topic="mechanics/circular-motion",
            run_id="security-1",
            environment=_environment(),
        )
    assert len(backend.requests) == 1
    assert (raised.value.run_dir / "_FAILED").is_file()


def test_trace_secret_is_redacted_before_publication(tmp_path: Path) -> None:
    candidate = _candidate()
    candidate["distractors"][0]["rationale"] = (
        "api_key=sk-example-secret-value explains the misconception."
    )
    run_dir = shadow_foundry.run_shadow(
        roles=_roles(),
        backend=FakeBackend([json.dumps(candidate)]),
        output_root=tmp_path,
        allow_test_output=True,
        search_fn=_fake_search,
        n=3,
        seed=7,
        topic="mechanics/circular-motion",
        run_id="redact-1",
        environment=_environment(),
    )
    rendered = "\n".join(
        path.read_text() for path in run_dir.iterdir() if path.name.endswith(".json")
    )
    assert "sk-example-secret-value" not in rendered
    assert "[REDACTED]" in rendered


def test_path_leak_in_raw_output_finalizes_failed_diagnostic(tmp_path: Path) -> None:
    candidate = _candidate()
    candidate["distractors"][0]["rationale"] = (
        "Consult ../private/result.json before selecting this answer."
    )
    with pytest.raises(shadow_foundry.ShadowRunFailed) as raised:
        shadow_foundry.run_shadow(
            roles=_roles(),
            backend=FakeBackend([json.dumps(candidate)]),
            output_root=tmp_path,
            allow_test_output=True,
            search_fn=_fake_search,
            n=3,
            seed=7,
            topic="mechanics/circular-motion",
            run_id="path-leak-1",
            environment=_environment(),
        )
    run_dir = raised.value.run_dir
    assert (run_dir / "_FAILED").is_file()
    rendered = "\n".join(
        path.read_text() for path in run_dir.iterdir() if path.name.endswith(".json")
    )
    assert "../private/result.json" not in rendered
    assert "ShadowLeakageError" in rendered


def test_source_file_field_cannot_be_published(tmp_path: Path) -> None:
    candidates, manifest = shadow_foundry.offline_fixture(
        run_id="source-file-1",
        environment=_environment(),
    )
    candidates[0]["candidate"]["source_file"] = "book.pdf"
    with pytest.raises(shadow_foundry.ShadowLeakageError, match="path field"):
        shadow_foundry.publish_run(
            tmp_path,
            "source-file-1",
            candidates=candidates,
            failures=[],
            manifest=manifest,
            allow_test_output=True,
        )
    assert not list(tmp_path.rglob("_SUCCESS"))


def test_parser_retry_outcomes_survive_failed_diagnostic(tmp_path: Path) -> None:
    with pytest.raises(shadow_foundry.ShadowRunFailed) as raised:
        shadow_foundry.run_shadow(
            roles=_roles(),
            backend=FakeBackend(["not JSON"]),
            output_root=tmp_path,
            allow_test_output=True,
            search_fn=_fake_search,
            n=3,
            seed=7,
            topic="mechanics/circular-motion",
            run_id="parser-failure-1",
            environment=_environment(),
        )
    manifest = json.loads((raised.value.run_dir / "manifest.json").read_text())
    assert any(
        trace["parser_outcome"] == "parse_error" for trace in manifest["request_traces"]
    )


def test_same_vendor_triple_fails_semantic_role_validation() -> None:
    roles = shadow_portfolio.ModelRoles(
        sol=model_backend.ModelSpec("sol", "gpt-5.6-sol-max", "high"),
        opus=model_backend.ModelSpec("opus", "gpt-5.6-sol-opus-slot", "high"),
        grok=model_backend.ModelSpec("grok", "gpt-5.6-sol-grok-slot", "high"),
    )
    models = [
        {"id": spec.model_id, "parameters": [], "variants": []}
        for spec in (roles.sol, roles.opus, roles.grok)
    ]
    with pytest.raises(ValueError, match="family identity"):
        shadow_foundry.validate_exact_roles(roles, models)


class HoldingPublicationIO(shadow_foundry.PublicationIO):
    def __init__(self) -> None:
        self.locked = threading.Event()
        self.release = threading.Event()

    def create_temp(self, root: Path, run_id: str) -> Path:
        self.locked.set()
        if not self.release.wait(timeout=5):
            raise TimeoutError("test did not release publication")
        return super().create_temp(root, run_id)


def test_concurrent_lock_failure_never_removes_owned_lock(tmp_path: Path) -> None:
    candidates, manifest = shadow_foundry.offline_fixture(
        run_id="concurrent-lock",
        environment=_environment(),
    )
    holding = HoldingPublicationIO()
    lock_path = tmp_path / ".concurrent-lock.lock"
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(
            shadow_foundry.publish_run,
            tmp_path,
            "concurrent-lock",
            candidates=candidates,
            failures=[],
            manifest=manifest,
            allow_test_output=True,
            io=holding,
        )
        assert holding.locked.wait(timeout=5)
        try:
            with pytest.raises(FileExistsError):
                shadow_foundry.publish_run(
                    tmp_path,
                    "concurrent-lock",
                    candidates=candidates,
                    failures=[],
                    manifest=manifest,
                    allow_test_output=True,
                )
            lock_survived = lock_path.is_file()
        finally:
            holding.release.set()
        assert first.result(timeout=5) == tmp_path / "concurrent-lock"
    assert lock_survived


def test_preexisting_lock_is_never_unlinked(tmp_path: Path) -> None:
    candidates, manifest = shadow_foundry.offline_fixture(
        run_id="foreign-lock",
        environment=_environment(),
    )
    lock_path = tmp_path / ".foreign-lock.lock"
    lock_path.write_text("foreign-owner\n", encoding="utf-8")
    with pytest.raises(FileExistsError):
        shadow_foundry.publish_run(
            tmp_path,
            "foreign-lock",
            candidates=candidates,
            failures=[],
            manifest=manifest,
            allow_test_output=True,
        )
    assert lock_path.read_text(encoding="utf-8") == "foreign-owner\n"
    assert not (tmp_path / "foreign-lock").exists()


@pytest.mark.parametrize("cancel", [KeyboardInterrupt(), SystemExit(9)])
def test_candidate_cancellation_propagates_without_later_calls(
    tmp_path: Path,
    cancel: BaseException,
) -> None:
    class CancellingBackend(FakeBackend):
        def complete(
            self,
            request: model_backend.ModelRequest,
        ) -> model_backend.ModelResult:
            self.requests.append(request)
            raise cancel

    backend = CancellingBackend()
    with pytest.raises(type(cancel)):
        shadow_foundry.run_shadow(
            roles=_roles(),
            backend=backend,
            output_root=tmp_path,
            allow_test_output=True,
            search_fn=_fake_search,
            n=3,
            seed=7,
            topic="mechanics/circular-motion",
            run_id=f"cancel-{type(cancel).__name__}",
            environment=_environment(),
        )
    assert len(backend.requests) == 1
    assert not list(tmp_path.rglob("_FAILED"))
    assert not list(tmp_path.rglob("_SUCCESS"))


@pytest.mark.parametrize(
    "error_type",
    [
        shadow_foundry.cursor_sandbox.ModelMismatchError,
        shadow_foundry.cursor_sandbox.RequestDirectoryError,
        shadow_foundry.cursor_sandbox.LeakageError,
        shadow_foundry.cursor_sandbox.RuntimeEndpointError,
        shadow_foundry.cursor_sandbox.MountProbeError,
        shadow_foundry.cursor_sandbox.SecurityCleanupError,
        shadow_foundry.cursor_sandbox.RequestCleanupError,
        shadow_foundry.cursor_sandbox.RequestRetentionError,
        shadow_foundry.cursor_sandbox.SandboxLimitError,
        shadow_foundry.cursor_sandbox.DescriptorOpenError,
    ],
)
def test_every_sandbox_security_error_stops_later_model_calls(
    tmp_path: Path,
    error_type: type[Exception],
) -> None:
    class SecurityBackend(FakeBackend):
        def complete(
            self,
            request: model_backend.ModelRequest,
        ) -> model_backend.ModelResult:
            self.requests.append(request)
            raise error_type("injected security failure")

    backend = SecurityBackend()
    with pytest.raises(shadow_foundry.ShadowRunFailed) as raised:
        shadow_foundry.run_shadow(
            roles=_roles(),
            backend=backend,
            output_root=tmp_path,
            allow_test_output=True,
            search_fn=_fake_search,
            n=3,
            seed=7,
            topic="mechanics/circular-motion",
            run_id=f"security-{error_type.__name__}",
            environment=_environment(),
        )
    assert len(backend.requests) == 1
    assert (raised.value.run_dir / "_FAILED").is_file()


def test_prepared_sandbox_executes_only_immutable_digest() -> None:
    endpoint = types.SimpleNamespace(
        kind="docker",
        socket=Path("/var/run/docker.sock"),
    )
    digest = "sha256:" + ("d" * 64)
    instances: list[object] = []

    class FakeSandbox:
        def __init__(self, config, **_kwargs):  # noqa: ANN001
            self.config = config
            self.built = False
            instances.append(self)

        def build_image(self, *, context=None):  # noqa: ANN001
            assert context == shadow_foundry.WORKER_CONTEXT
            self.built = True
            return self.config.image

        def image_digest(self) -> str:
            return digest

    prepared = shadow_foundry.prepare_real_sandbox(
        "cursor_test_key",
        runtime_detector=lambda: "docker",
        runtime_discoverer=lambda _runtime: endpoint,
        sandbox_factory=FakeSandbox,
    )
    assert len(instances) == 2
    assert instances[0].built is True
    assert instances[0].config.image.startswith("pgrep-shadow-worker:")
    assert instances[1].config.image == digest
    assert prepared.sandbox is instances[1]
    assert prepared.image == digest
    assert prepared.image_digest == digest


def test_manifest_run_id_must_match_publication_directory(tmp_path: Path) -> None:
    candidates, manifest = shadow_foundry.offline_fixture(
        run_id="manifest-id",
        environment=_environment(),
    )
    with pytest.raises(ValueError, match="run ID"):
        shadow_foundry.publish_run(
            tmp_path,
            "different-directory",
            candidates=candidates,
            failures=[],
            manifest=manifest,
            allow_test_output=True,
        )
    assert not list(tmp_path.rglob("_SUCCESS"))


def test_candidate_replay_metadata_is_complete() -> None:
    candidates, manifest = shadow_foundry.offline_fixture(
        run_id="replay-complete",
        environment=_environment(),
    )
    assert manifest["category"] == "mechanics"
    assert manifest["execution_mode"] == "test-fake"
    assert manifest["replayable"] is False
    for slot, candidate in enumerate(candidates):
        assert candidate["topic"] == manifest["topic"]
        assert candidate["category"] == manifest["category"]
        assert candidate["seed"] == manifest["seeds"]["slots"][slot]
        assert candidate["origin_family"] == manifest["allocation"][slot]
        assert candidate["retrieval"] == {
            "chunk_ids": ["chunk-self-check-1"],
            "source_refs": ["OpenStax University Physics, p. 1"],
        }
        traces = shadow_foundry._candidate_traces(candidate)
        assert traces
        assert all(trace["request_hash"] for trace in traces)
        assert all(trace["response_hash"] for trace in traces)
        assert all(
            trace["retrieved_chunk_ids"] == candidate["retrieval"]["chunk_ids"]
            for trace in traces
        )
        assert all(
            trace["retrieved_source_refs"] == candidate["retrieval"]["source_refs"]
            for trace in traces
        )


@pytest.mark.parametrize(
    "tamper",
    ["topic", "category", "candidate_seed", "portfolio_seed"],
)
def test_manifest_replay_cross_checks_reject_tampering(
    tmp_path: Path,
    tamper: str,
) -> None:
    candidates, manifest = shadow_foundry.offline_fixture(
        run_id=f"tamper-{tamper}",
        environment=_environment(),
    )
    if tamper == "topic":
        candidates[0]["topic"] = "electromagnetism/fields"
    elif tamper == "category":
        candidates[0]["category"] = "electromagnetism"
    elif tamper == "candidate_seed":
        candidates[0]["seed"] = 999
    else:
        manifest["seeds"]["portfolio"] = 999
    with pytest.raises(ValueError, match="topic|category|seed|allocation"):
        shadow_foundry.publish_run(
            tmp_path,
            f"tamper-{tamper}",
            candidates=candidates,
            failures=[],
            manifest=manifest,
            allow_test_output=True,
        )
    assert not list(tmp_path.rglob("_SUCCESS"))


def test_dirty_real_run_refuses_success_before_model_calls(tmp_path: Path) -> None:
    environment = _environment()
    object.__setattr__(environment, "execution_mode", "real")
    backend = FakeBackend()
    with pytest.raises(shadow_foundry.ShadowRunFailed) as raised:
        shadow_foundry.run_shadow(
            roles=_roles(),
            backend=backend,
            output_root=tmp_path,
            allow_test_output=True,
            search_fn=_fake_search,
            n=3,
            seed=7,
            topic="mechanics/circular-motion",
            run_id="dirty-real",
            environment=environment,
        )
    assert backend.requests == []
    assert (raised.value.run_dir / "_FAILED").is_file()


def _request_with(
    *,
    user: str = "CORPUS CONTEXT: safe physics.",
    source_refs: tuple[str, ...] = ("OpenStax University Physics, p. 1",),
) -> model_backend.ModelRequest:
    return model_backend.ModelRequest(
        request_id="security-request",
        role="generator",
        model=_roles().sol,
        system="Return strict JSON.",
        user=user,
        prompt_version=shadow_portfolio.GENERATOR_PROMPT_VERSION,
        schema_version=shadow_portfolio.SCHEMA_VERSION,
        seed=7,
        corpus_chunk_ids=("chunk-1",),
        source_refs=source_refs,
    )


def test_original_request_secret_is_rejected_before_backend() -> None:
    backend = FakeBackend()
    recorder = shadow_foundry._RecordingBackend(
        backend,
        secrets=("cursor_test_secret",),
    )
    recorder.allowed_source_refs = frozenset({"OpenStax University Physics, p. 1"})
    request = _request_with(user="api_key=cursor_test_secret")
    with pytest.raises(shadow_foundry.ShadowLeakageError, match="secret"):
        recorder.complete(request)
    assert backend.requests == []


def test_request_source_refs_must_match_bound_retrieval_exactly() -> None:
    backend = FakeBackend()
    recorder = shadow_foundry._RecordingBackend(backend, secrets=())
    recorder.allowed_source_refs = frozenset({"OpenStax University Physics, p. 1"})
    request = _request_with(source_refs=("Different citation",))
    with pytest.raises(shadow_foundry.ShadowLeakageError, match="source reference"):
        recorder.complete(request)
    assert backend.requests == []


@pytest.mark.parametrize(
    "source_ref",
    [
        "/work/request.json",
        "/usr/local/share/model.txt",
        "/etc/passwd",
        "/home/user/notes.md",
        "../private/notes.txt",
        "notes.md",
        "results.json",
    ],
)
def test_path_like_source_refs_are_rejected(source_ref: str) -> None:
    dirty = _retrieved()
    dirty[0]["source_ref"] = source_ref
    with pytest.raises(shadow_foundry.ShadowLeakageError, match="filesystem path"):
        shadow_foundry.sanitize_retrieved(dirty)


class RecordingDurabilityIO(shadow_foundry.PublicationIO):
    def __init__(self, root: Path, run_id: str) -> None:
        self.root = root
        self.run_id = run_id
        self.events: list[str] = []

    def _label(self, path: Path) -> str:
        if path == self.root:
            return "root"
        if path.name == self.run_id:
            return "final"
        return "temp"

    def write_payload(self, path: Path, content: str) -> None:
        self.events.append("payload")
        super().write_payload(path, content)

    def reserve_final(self, path: Path) -> None:
        self.events.append("reserve")
        super().reserve_final(path)

    def link_payload(self, source: Path, destination: Path) -> None:
        self.events.append("link")
        super().link_payload(source, destination)

    def sync_directory(self, path: Path) -> None:
        self.events.append(f"sync:{self._label(path)}")
        super().sync_directory(path)

    def cleanup_tree(self, path: Path) -> None:
        self.events.append(f"cleanup:{self._label(path)}")
        super().cleanup_tree(path)

    def remove_lock(
        self,
        path: Path,
        identity: shadow_foundry.LockIdentity,
    ) -> None:
        self.events.append("remove-lock")
        super().remove_lock(path, identity)

    def write_marker(self, path: Path, content: str) -> None:
        self.events.append("marker")
        super().write_marker(path, content)


def test_publication_fsync_order_makes_payloads_durable_before_marker(
    tmp_path: Path,
) -> None:
    candidates, manifest = shadow_foundry.offline_fixture(
        run_id="durable",
        environment=_environment(),
    )
    io = RecordingDurabilityIO(tmp_path, "durable")
    shadow_foundry.publish_run(
        tmp_path,
        "durable",
        candidates=candidates,
        failures=[],
        manifest=manifest,
        allow_test_output=True,
        io=io,
    )
    marker = io.events.index("marker")
    assert io.events.index("sync:temp") < io.events.index("reserve")
    assert io.events.index("sync:final") < marker
    assert io.events.index("remove-lock") < marker
    assert io.events[marker + 1 : marker + 3] == ["sync:final", "sync:root"]


class FailingDirectorySyncIO(shadow_foundry.PublicationIO):
    def __init__(self, run_id: str) -> None:
        self.run_id = run_id

    def sync_directory(self, path: Path) -> None:
        if path.name == self.run_id:
            raise OSError("injected directory fsync failure")
        super().sync_directory(path)


def test_directory_fsync_failure_cleans_false_finalization(tmp_path: Path) -> None:
    candidates, manifest = shadow_foundry.offline_fixture(
        run_id="sync-failure",
        environment=_environment(),
    )
    with pytest.raises(OSError, match="fsync"):
        shadow_foundry.publish_run(
            tmp_path,
            "sync-failure",
            candidates=candidates,
            failures=[],
            manifest=manifest,
            allow_test_output=True,
            io=FailingDirectorySyncIO("sync-failure"),
        )
    assert not (tmp_path / "sync-failure").exists()
    assert not list(tmp_path.rglob("_SUCCESS"))
    assert not list(tmp_path.glob(".*.tmp"))
    assert not list(tmp_path.glob(".*.lock"))


class FailingPostMarkerSyncIO(shadow_foundry.PublicationIO):
    def __init__(self, run_id: str) -> None:
        self.run_id = run_id
        self.final_syncs = 0

    def sync_directory(self, path: Path) -> None:
        if path.name == self.run_id:
            self.final_syncs += 1
            if self.final_syncs == 2:
                raise OSError("injected post-marker fsync failure")
        super().sync_directory(path)


def test_post_marker_fsync_failure_removes_false_marker(tmp_path: Path) -> None:
    candidates, manifest = shadow_foundry.offline_fixture(
        run_id="post-marker-sync-failure",
        environment=_environment(),
    )
    with pytest.raises(OSError, match="post-marker"):
        shadow_foundry.publish_run(
            tmp_path,
            "post-marker-sync-failure",
            candidates=candidates,
            failures=[],
            manifest=manifest,
            allow_test_output=True,
            io=FailingPostMarkerSyncIO("post-marker-sync-failure"),
        )
    assert not (tmp_path / "post-marker-sync-failure").exists()
    assert not list(tmp_path.rglob("_SUCCESS"))
    assert not list(tmp_path.glob(".*.tmp"))
    assert not list(tmp_path.glob(".*.lock"))


_CANONICAL_TRACE_FIELDS = (
    "request_id",
    "request_hash",
    "role",
    "family",
    "requested_model_id",
    "actual_model_id",
    "response_hash",
    "prompt_version",
    "schema_version",
    "agent_id",
    "run_id",
    "seed",
    "choice_order",
    "parser_outcome",
    "phase",
    "attempt",
    "binding",
)


def test_canonical_trace_summary_contains_complete_binding() -> None:
    candidates, manifest = shadow_foundry.offline_fixture(
        run_id="canonical-trace",
        environment=_environment(),
    )
    trace = manifest["request_traces"][0]
    assert set(_CANONICAL_TRACE_FIELDS) <= set(trace)
    assert trace["binding"] == {
        "candidate_slot": candidates[0]["slot"],
        "candidate_origin_family": candidates[0]["origin_family"],
        "kind": "generator",
        "verifier_family": None,
    }
    assert "request" not in trace
    assert "result" not in trace


def _mutated_trace_value(field: str, current: object) -> object:
    if field in {"request_hash", "response_hash"}:
        return "f" * 64 if current != "f" * 64 else "e" * 64
    if field in {"seed", "attempt"}:
        return int(current) + 100
    if field == "choice_order":
        return list(reversed(current)) if current else list("EDCBA")
    if field == "binding":
        changed = dict(current)
        changed["candidate_slot"] = int(changed["candidate_slot"]) + 1
        return changed
    return f"mutated-{field}"


@pytest.mark.parametrize("field", _CANONICAL_TRACE_FIELDS)
def test_manifest_rejects_every_canonical_trace_field_mismatch(
    tmp_path: Path,
    field: str,
) -> None:
    candidates, manifest = shadow_foundry.offline_fixture(
        run_id=f"trace-field-{field}",
        environment=_environment(),
    )
    trace = manifest["request_traces"][0]
    if field not in trace:
        pytest.fail(f"canonical trace is missing {field}")
    trace[field] = _mutated_trace_value(field, trace[field])
    with pytest.raises(ValueError, match="trace|binding|model|seed|hash|role|family"):
        shadow_foundry.publish_run(
            tmp_path,
            f"trace-field-{field}",
            candidates=candidates,
            failures=[],
            manifest=manifest,
            allow_test_output=True,
        )
    assert not list(tmp_path.rglob("_SUCCESS"))


def test_candidate_trace_enclosing_binding_mismatch_fails_closed(
    tmp_path: Path,
) -> None:
    candidates, manifest = shadow_foundry.offline_fixture(
        run_id="enclosing-binding",
        environment=_environment(),
    )
    verifier = candidates[0]["verifiers"][0]
    verifier["trace"]["binding"]["verifier_family"] = "wrong-family"
    with pytest.raises(ValueError, match="binding"):
        shadow_foundry.publish_run(
            tmp_path,
            "enclosing-binding",
            candidates=candidates,
            failures=[],
            manifest=manifest,
            allow_test_output=True,
        )
    assert not list(tmp_path.rglob("_SUCCESS"))


def test_conflicting_duplicate_candidate_trace_fails_closed(tmp_path: Path) -> None:
    candidates, manifest = shadow_foundry.offline_fixture(
        run_id="duplicate-trace",
        environment=_environment(),
    )
    duplicate = copy.deepcopy(candidates[0]["generator"]["traces"][0])
    duplicate["response_hash"] = "f" * 64
    candidates[0]["generator"]["traces"].append(duplicate)
    with pytest.raises(ValueError, match="duplicate|trace"):
        shadow_foundry.publish_run(
            tmp_path,
            "duplicate-trace",
            candidates=candidates,
            failures=[],
            manifest=manifest,
            allow_test_output=True,
        )
    assert not list(tmp_path.rglob("_SUCCESS"))


def _clean_real_environment() -> shadow_foundry.RunEnvironment:
    environment = _environment()
    object.__setattr__(environment, "tree_status", "clean")
    object.__setattr__(environment, "execution_mode", "real")
    object.__setattr__(
        environment,
        "worker_image",
        environment.worker_image_digest,
    )
    object.__setattr__(environment, "corpus_index_mtime_ns", 123456789)
    object.__setattr__(environment, "corpus_index_size", 4096)
    return environment


@pytest.mark.parametrize(
    ("change", "attested"),
    [
        (
            "head",
            ("b" * 40, "clean", "sha256:" + ("c" * 64), 123456789, 4096),
        ),
        (
            "dirty",
            ("a" * 40, "dirty", "sha256:" + ("c" * 64), 123456789, 4096),
        ),
        (
            "index-bytes",
            ("a" * 40, "clean", "sha256:" + ("d" * 64), 123456789, 4096),
        ),
        (
            "index-mtime",
            ("a" * 40, "clean", "sha256:" + ("c" * 64), 123456790, 4096),
        ),
    ],
)
def test_final_state_change_publishes_failed_diagnostic(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    change: str,
    attested: tuple[str, str, str, int, int],
) -> None:
    environment = _clean_real_environment()
    calls: list[bool] = []

    def reattest(_environment: shadow_foundry.RunEnvironment):
        calls.append(True)
        return attested

    monkeypatch.setattr(
        shadow_foundry,
        "_reattest_success_state",
        reattest,
        raising=False,
    )
    with pytest.raises(shadow_foundry.ShadowRunFailed) as raised:
        shadow_foundry.run_shadow(
            roles=_roles(),
            backend=FakeBackend(),
            output_root=tmp_path,
            allow_test_output=True,
            search_fn=_fake_search,
            n=3,
            seed=7,
            topic="mechanics/circular-motion",
            run_id=f"reattest-{change}",
            environment=environment,
        )
    assert calls == [True]
    assert (raised.value.run_dir / "_FAILED").is_file()
    assert not (raised.value.run_dir / "_SUCCESS").exists()
    manifest = json.loads((raised.value.run_dir / "manifest.json").read_text())
    failures = json.loads((raised.value.run_dir / "failures.json").read_text())
    assert manifest["status"] == "failed"
    assert manifest["training_eligible"] is False
    assert manifest["replayable"] is False
    assert failures[-1]["stage"] == "reattest"


def test_final_clean_unchanged_state_publishes_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    environment = _clean_real_environment()
    calls: list[bool] = []

    def reattest(_environment: shadow_foundry.RunEnvironment):
        calls.append(True)
        return (
            environment.code_sha,
            "clean",
            environment.corpus_index_fingerprint,
            environment.corpus_index_mtime_ns,
            environment.corpus_index_size,
        )

    monkeypatch.setattr(
        shadow_foundry,
        "_reattest_success_state",
        reattest,
        raising=False,
    )
    run_dir = shadow_foundry.run_shadow(
        roles=_roles(),
        backend=FakeBackend(),
        output_root=tmp_path,
        allow_test_output=True,
        search_fn=_fake_search,
        n=3,
        seed=7,
        topic="mechanics/circular-motion",
        run_id="reattest-clean",
        environment=environment,
    )
    assert calls == [True]
    assert (run_dir / "_SUCCESS").is_file()
    assert not (run_dir / "_FAILED").exists()
