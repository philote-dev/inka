# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Offline end-to-end regressions for decomposition batch safety."""

from __future__ import annotations

import copy
import json
import os
import sys
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parent
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import _ai_path  # noqa: E402

_ai_path.add_ai_core()

import generate_decompositions  # noqa: E402
from pgrep.ai.batch_safety import (  # type: ignore[import-not-found]  # noqa: E402
    BatchStopped,
    BatchStopReason,
)


class _Connection:
    def close(self) -> None:
        pass


def _variant(stem: str, key: str = "A") -> dict[str, object]:
    return {
        "stem": stem,
        "choices": ["1", "2", "3", "4", "5"],
        "key": key,
        "distractor_rationales": {
            "B": "misconception B",
            "C": "misconception C",
            "D": "misconception D",
            "E": "misconception E",
        },
        "explain_why": "Because physics.",
    }


def _tutor_reply() -> dict[str, object]:
    return {
        "subproblems": [
            {"prompt": "Step one", "variants": [_variant("First step?")]},
            {"prompt": "Step two", "variants": [_variant("Second step?")]},
        ],
        "parent_variants": [],
    }


class _StopAfterOneClient:
    model = "fake-2026-01-01"

    def __init__(self) -> None:
        self.calls = 0

    def complete_json(self, *_args: object, **_kwargs: object) -> dict[str, object]:
        self.calls += 1
        if self.calls == 1:
            return copy.deepcopy(_tutor_reply())
        raise BatchStopped(BatchStopReason.CALL_LIMIT)


class _StopDuringDefaultKeyVerificationClient:
    model = "fake-2026-01-01"

    def __init__(self) -> None:
        self.calls = 0

    def complete_json(self, *_args: object, **_kwargs: object) -> dict[str, object]:
        self.calls += 1
        if self.calls in {1, 4}:
            return copy.deepcopy(_tutor_reply())
        if self.calls in {2, 3}:
            return {"answer": "A"}
        raise BatchStopped(BatchStopReason.CALL_LIMIT)


def test_decomposition_cap_stop_aborts_apply_without_partial_bundle_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = tmp_path / "bundle.json"
    out = tmp_path / "decompositions"
    payload = {
        "problems": [
            {
                "id": "problem-1",
                "topic": "pgrep::mechanics",
                "stem": "Parent one?",
                "choices": ["10", "20", "30", "40", "50"],
                "correct": "A",
                "source_ref": "OpenStax, section 1",
                "solution_decomposition": [],
            },
            {
                "id": "problem-2",
                "topic": "pgrep::mechanics",
                "stem": "Parent two?",
                "choices": ["11", "21", "31", "41", "51"],
                "correct": "A",
                "source_ref": "OpenStax, section 2",
                "solution_decomposition": [],
            },
        ]
    }
    bundle.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    original = bundle.read_bytes()
    client = _StopAfterOneClient()
    monkeypatch.setenv("OPENAI_API_KEY", "offline-test-key")
    monkeypatch.setattr(
        generate_decompositions.llm_mod,
        "LLMClient",
        lambda *_args, **_kwargs: client,
    )
    monkeypatch.setattr(
        generate_decompositions.retrieval,
        "open_index",
        lambda _path: _Connection(),
    )
    monkeypatch.setattr(
        generate_decompositions.retrieval,
        "search",
        lambda *_args, **_kwargs: [],
    )
    monkeypatch.setattr(
        generate_decompositions.gc,
        "build_context",
        lambda _retrieved: "offline context",
    )
    monkeypatch.setattr(
        generate_decompositions.verify,
        "find_giveaway",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "generate_decompositions.py",
            "--workers",
            "1",
            "--no-verify-keys",
            "--bundle",
            os.fspath(bundle),
            "--db",
            os.fspath(tmp_path / "corpus.db"),
            "--out",
            os.fspath(out),
            "--apply",
        ],
    )

    with pytest.raises(BatchStopped) as raised:
        generate_decompositions.main()

    assert raised.value.reason is BatchStopReason.CALL_LIMIT
    assert client.calls == 2
    assert bundle.read_bytes() == original
    assert all(
        "decomposition_tutor" not in problem
        for problem in json.loads(bundle.read_text(encoding="utf-8"))["problems"]
    )


def test_default_key_verification_cap_stop_aborts_partial_apply(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = tmp_path / "bundle.json"
    out = tmp_path / "decompositions"
    payload = {
        "problems": [
            {
                "id": "problem-1",
                "topic": "pgrep::mechanics",
                "stem": "Parent one?",
                "choices": ["10", "20", "30", "40", "50"],
                "correct": "A",
                "source_ref": "OpenStax, section 1",
                "solution_decomposition": [],
            },
            {
                "id": "problem-2",
                "topic": "pgrep::mechanics",
                "stem": "Parent two?",
                "choices": ["11", "21", "31", "41", "51"],
                "correct": "A",
                "source_ref": "OpenStax, section 2",
                "solution_decomposition": [],
            },
        ]
    }
    bundle.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    original = bundle.read_bytes()
    client = _StopDuringDefaultKeyVerificationClient()
    monkeypatch.setenv("OPENAI_API_KEY", "offline-test-key")
    monkeypatch.setattr(
        generate_decompositions.llm_mod,
        "LLMClient",
        lambda *_args, **_kwargs: client,
    )
    monkeypatch.setattr(
        generate_decompositions.retrieval,
        "open_index",
        lambda _path: _Connection(),
    )
    monkeypatch.setattr(
        generate_decompositions.retrieval,
        "search",
        lambda *_args, **_kwargs: [],
    )
    monkeypatch.setattr(
        generate_decompositions.gc,
        "build_context",
        lambda _retrieved: "offline context",
    )
    monkeypatch.setattr(
        generate_decompositions.verify,
        "find_giveaway",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "generate_decompositions.py",
            "--workers",
            "1",
            "--bundle",
            os.fspath(bundle),
            "--db",
            os.fspath(tmp_path / "corpus.db"),
            "--out",
            os.fspath(out),
            "--apply",
        ],
    )

    with pytest.raises(BatchStopped) as raised:
        generate_decompositions.main()

    assert raised.value.reason is BatchStopReason.CALL_LIMIT
    assert client.calls == 5
    assert bundle.read_bytes() == original
    assert all(
        "decomposition_tutor" not in problem
        for problem in json.loads(bundle.read_text(encoding="utf-8"))["problems"]
    )
