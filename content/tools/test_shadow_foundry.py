# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Offline tests for the quarantined multi-model shadow-foundry CLI."""

from __future__ import annotations

import json
import os
import sys
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


def _manifest() -> dict[str, object]:
    return {
        "run_id": "run-1",
        "schema_version": shadow_portfolio.SCHEMA_VERSION,
        "prompt_versions": {
            "generator": shadow_portfolio.GENERATOR_PROMPT_VERSION,
            "verifier": shadow_portfolio.VERIFIER_PROMPT_VERSION,
        },
        "roles": {
            "sol": "gpt-5.6-sol-max",
            "opus": "claude-opus-4-8-thinking-high-fast",
            "grok": "cursor-grok-4.5-high-fast",
        },
        "seed": 7,
        "n": 3,
        "code_sha": "deadbeef",
        "probe": {"models": ["gpt-5.6-sol-max"]},
        "training_eligible": False,
    }


def _retrieved() -> list[dict[str, object]]:
    return [
        {
            "chunk_id": "chunk-1",
            "source_ref": "OpenStax University Physics, p. 1",
            "text": "Uniform circular motion keeps speed constant while velocity changes.",
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
    run_dir = shadow_foundry.publish_run(
        tmp_path,
        "run-1",
        candidates=[_candidate()],
        failures=[],
        manifest=_manifest(),
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
    shadow_foundry.publish_run(
        tmp_path,
        "run-1",
        candidates=[],
        failures=[],
        manifest=_manifest(),
    )
    with pytest.raises(ValueError, match="already exists"):
        shadow_foundry.publish_run(
            tmp_path,
            "run-1",
            candidates=[],
            failures=[],
            manifest=_manifest(),
        )


def test_publish_run_rejects_private_markers(tmp_path: Path) -> None:
    dirty = _manifest()
    dirty["note"] = "path content/gold/items.json"
    with pytest.raises(ValueError, match="private marker"):
        shadow_foundry.publish_run(
            tmp_path,
            "run-dirty",
            candidates=[],
            failures=[],
            manifest=dirty,
        )
    assert not (tmp_path / "run-dirty").exists()
    assert not list(tmp_path.glob("*/_SUCCESS"))


def test_partial_portfolio_never_publishes_success(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="all three model families"):
        shadow_foundry.run_shadow(
            roles=_roles(),
            backend=MissingGrokBackend(),
            output_root=tmp_path,
            search_fn=_fake_search,
            n=3,
            seed=7,
            topic="mechanics/circular-motion",
            run_id="partial-1",
            probe_models=[
                {"id": "gpt-5.6-sol-max"},
                {"id": "claude-opus-4-8-thinking-high-fast"},
                {"id": "cursor-grok-4.5-high-fast"},
            ],
        )
    assert not list(tmp_path.glob("*/_SUCCESS"))


def test_run_shadow_requires_probe_ids_before_generation(tmp_path: Path) -> None:
    backend = FakeBackend()
    with pytest.raises(ValueError, match="exact model"):
        shadow_foundry.run_shadow(
            roles=_roles(),
            backend=backend,
            output_root=tmp_path,
            search_fn=_fake_search,
            n=3,
            seed=7,
            topic="mechanics/circular-motion",
            run_id="probe-miss",
            probe_models=[
                {"id": "gpt-5.6-sol-max"},
                {"id": "claude-opus-4-8-thinking-high-fast"},
            ],
        )
    assert backend.requests == []
    assert not list(tmp_path.glob("*/_SUCCESS"))


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
    with pytest.raises(ValueError, match="auto|substitut"):
        shadow_foundry.run_shadow(
            roles=roles,
            backend=FakeBackend(),
            output_root=tmp_path,
            search_fn=_fake_search,
            n=3,
            seed=7,
            topic="mechanics/circular-motion",
            run_id="auto-1",
            probe_models=[
                {"id": "auto"},
                {"id": "claude-opus-4-8-thinking-high-fast"},
                {"id": "cursor-grok-4.5-high-fast"},
            ],
        )


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
            }
        ]
    )
    assert chunks == [
        {
            "chunk_id": "chunk-1",
            "source_ref": "OpenStax, p. 1",
            "text": "Speed is scalar.",
        }
    ]


def test_sanitize_chunks_rejects_private_markers_and_paths() -> None:
    with pytest.raises(ValueError, match="private marker|source path"):
        shadow_foundry.sanitize_retrieved(
            [
                {
                    "chunk_id": "chunk-bad",
                    "source_ref": "content/heldout/form.json",
                    "text": "leaky",
                }
            ]
        )


def test_run_shadow_publishes_complete_portfolio(tmp_path: Path) -> None:
    backend = FakeBackend()
    run_dir = shadow_foundry.run_shadow(
        roles=_roles(),
        backend=backend,
        output_root=tmp_path,
        search_fn=_fake_search,
        n=3,
        seed=7,
        topic="mechanics/circular-motion",
        run_id="full-1",
        probe_models=[
            {"id": "gpt-5.6-sol-max"},
            {"id": "claude-opus-4-8-thinking-high-fast"},
            {"id": "cursor-grok-4.5-high-fast"},
        ],
        code_sha="abc123",
    )
    assert (run_dir / "_SUCCESS").exists()
    manifest = json.loads((run_dir / "manifest.json").read_text())
    candidates = json.loads((run_dir / "candidates.json").read_text())
    failures = json.loads((run_dir / "failures.json").read_text())
    assert manifest["training_eligible"] is False
    assert manifest["code_sha"] == "abc123"
    assert set(manifest["roles"].values()) == {
        "gpt-5.6-sol-max",
        "claude-opus-4-8-thinking-high-fast",
        "cursor-grok-4.5-high-fast",
    }
    assert {c["origin_family"] for c in candidates} == {"sol", "opus", "grok"}
    assert failures == []
    assert "probe" in manifest
    assert "request_hashes" in manifest
    assert not (run_dir / "preferences.jsonl").exists()
    assert not (run_dir / "accepted.json").exists()


def test_verifier_prompts_contain_neither_stored_key_nor_decomposition(
    tmp_path: Path,
) -> None:
    backend = FakeBackend()
    shadow_foundry.run_shadow(
        roles=_roles(),
        backend=backend,
        output_root=tmp_path,
        search_fn=_fake_search,
        n=3,
        seed=7,
        topic="mechanics/circular-motion",
        run_id="blind-1",
        probe_models=[
            {"id": "gpt-5.6-sol-max"},
            {"id": "claude-opus-4-8-thinking-high-fast"},
            {"id": "cursor-grok-4.5-high-fast"},
        ],
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
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(shadow_foundry, "DEFAULT_OUTPUT_ROOT", tmp_path)
    assert shadow_foundry.self_check() == 0
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
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(shadow_foundry, "DEFAULT_OUTPUT_ROOT", tmp_path)
    assert shadow_foundry.main(["--self-check"]) == 0
