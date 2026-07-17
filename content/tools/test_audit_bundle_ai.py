# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Offline regressions for audit selection and safety-stop propagation."""

from __future__ import annotations

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

import audit_bundle_ai  # noqa: E402
from pgrep.ai.batch_safety import (  # type: ignore[import-not-found]  # noqa: E402
    BatchStopped,
    BatchStopReason,
)


class _StoppedClient:
    model = "fake-2026-01-01"

    def complete_text(self, *_args: object, **_kwargs: object) -> str:
        raise BatchStopped(BatchStopReason.CALL_LIMIT)


def _bundle(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "problems": [
                    {
                        "id": "problem-1",
                        "topic": "mechanics",
                        "stem": "A test problem.",
                        "choices": ["1", "2", "3", "4", "5"],
                        "correct": "A",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )


def test_audit_cap_stop_propagates_instead_of_reporting_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = tmp_path / "bundle.json"
    out = tmp_path / "audit"
    _bundle(bundle)
    monkeypatch.setattr(audit_bundle_ai.llm, "load_api_key", lambda _path=None: None)
    monkeypatch.setattr(audit_bundle_ai.llm, "has_api_key", lambda: True)
    monkeypatch.setattr(
        audit_bundle_ai.llm,
        "judge_client",
        lambda *_args, **_kwargs: _StoppedClient(),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "audit_bundle_ai.py",
            "--only",
            "answer_key",
            "--workers",
            "1",
            "--bundle",
            os.fspath(bundle),
            "--out",
            os.fspath(out),
        ],
    )

    with pytest.raises(BatchStopped) as raised:
        audit_bundle_ai.main()

    assert raised.value.reason is BatchStopReason.CALL_LIMIT
    assert not (out / "audit_report.json").exists()
    assert not (out / "audit_summary.md").exists()


def test_audit_safety_classification_uses_selected_audits() -> None:
    classify = getattr(audit_bundle_ai, "audit_requires_protection", None)
    assert callable(classify), "audit safety classifier is missing"

    assert classify([]) is True
    assert classify(["--only", "answer_key"]) is True
    assert classify(["--only", "decomposition_leak", "citation"]) is False
    assert classify(["--only", "decomposition_leak citation"]) is False
    assert (
        classify(
            [
                "--only",
                "decomposition_leak",
                "citation",
                "--include-variant-solve",
            ]
        )
        is True
    )
