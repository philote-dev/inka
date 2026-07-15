# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Offline tests for the quarantined multi-model shadow-foundry CLI."""

from __future__ import annotations

import json
import os
import sys
import types
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
    observed: dict[str, object] = {}

    class FakeSandbox:
        def __init__(self, config, **kwargs):  # noqa: ANN001
            observed["config"] = config
            observed["kwargs"] = kwargs
            self.built = False

        def image_digest(self) -> str:
            if not self.built:
                raise shadow_foundry.cursor_sandbox.MountProbeError("image missing")
            return "sha256:" + ("d" * 64)

        def build_image(self, *, context=None):  # noqa: ANN001
            observed["context"] = context
            self.built = True
            return observed["config"].image

    prepared = shadow_foundry.prepare_real_sandbox(
        "cursor_test_key",
        runtime_detector=lambda: "docker",
        runtime_discoverer=lambda runtime: endpoint,
        sandbox_factory=FakeSandbox,
    )
    config = observed["config"]
    assert config.runtime == "docker"
    assert config.socket == "/var/run/docker.sock"
    assert config.image.startswith("pgrep-shadow-worker:")
    assert observed["context"] == shadow_foundry.WORKER_CONTEXT
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
        "file_fingerprint",
        lambda _path: "sha256:" + ("c" * 64),
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
