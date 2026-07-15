# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Offline protocol tests for the isolated Cursor SDK shadow worker.

Loads ``tools/shadow_worker/worker.py`` by path so root pytest does not need
``cursor-sdk`` installed. All SDK calls are injected fakes.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import types
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKER_PATH = REPO_ROOT / "tools" / "shadow_worker" / "worker.py"


def _load_worker():
    """Import worker.py without pulling ``cursor_sdk`` into the process."""
    assert "cursor_sdk" not in sys.modules
    spec = importlib.util.spec_from_file_location("pgrep_shadow_worker", WORKER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert "cursor_sdk" not in sys.modules
    return module


@pytest.fixture
def worker():
    return _load_worker()


class _FakeModel:
    def __init__(self, model_id: str, *, parameters=(), variants=()) -> None:
        self.id = model_id
        self.parameters = parameters
        self.variants = variants


class _FakeModels:
    def __init__(self, models: list[_FakeModel]) -> None:
        self._models = models

    def list(self, *, client=None, api_key=None):
        del client, api_key
        return list(self._models)


class _FakeRunResult:
    def __init__(
        self,
        *,
        status: str,
        text: str = "",
        run_id: str = "run-1",
        agent_id: str = "agent-1",
    ) -> None:
        self.status = status
        self.result = text
        self.id = run_id
        self.agent_id = agent_id


class _FakeCursorAgentError(Exception):
    def __init__(self, message: str, *, is_retryable: bool = False) -> None:
        super().__init__(message)
        self.message = message
        self.is_retryable = is_retryable


class _FakeAgentOptions:
    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs


class _FakeLocalAgentOptions:
    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs


class _FakeAgent:
    last_prompt = None
    last_options = None
    behavior = "finished"

    @classmethod
    def prompt(cls, message, options=None, *, client=None):
        del client
        cls.last_prompt = message
        cls.last_options = options
        if cls.behavior == "startup_error":
            raise _FakeCursorAgentError("auth failed", is_retryable=False)
        if cls.behavior == "run_error":
            return _FakeRunResult(
                status="error", text="", run_id="run-err", agent_id="agent-err"
            )
        return _FakeRunResult(
            status="finished",
            text="ok",
            run_id="run-ok",
            agent_id="agent-ok",
        )


@pytest.fixture
def fake_cursor():
    _FakeAgent.behavior = "finished"
    _FakeAgent.last_prompt = None
    _FakeAgent.last_options = None
    cursor = types.SimpleNamespace(
        models=_FakeModels(
            [
                _FakeModel("claude-opus-4-8-thinking-high-fast"),
                _FakeModel("cursor-grok-4.5-high-fast"),
                _FakeModel("gpt-5.6-sol-max"),
            ]
        ),
        Agent=_FakeAgent,
        AgentOptions=_FakeAgentOptions,
        LocalAgentOptions=_FakeLocalAgentOptions,
        CursorAgentError=_FakeCursorAgentError,
    )
    return cursor


def test_worker_import_does_not_load_cursor_sdk(worker) -> None:
    assert worker is not None
    assert "cursor_sdk" not in sys.modules


def test_models_action_serializes_account_ids(
    worker, fake_cursor, tmp_path: Path
) -> None:
    request = tmp_path / "request.json"
    result = tmp_path / "result.json"
    request.write_text('{"action":"models"}', encoding="utf-8")
    worker.run(request, result, cursor=fake_cursor)
    payload = json.loads(result.read_text(encoding="utf-8"))
    assert [m["id"] for m in payload["models"]] == [
        "claude-opus-4-8-thinking-high-fast",
        "cursor-grok-4.5-high-fast",
        "gpt-5.6-sol-max",
    ]
    assert "parameters" in payload["models"][0]
    assert "variants" in payload["models"][0]


def test_prompt_rejects_unlisted_model(worker, fake_cursor) -> None:
    with pytest.raises(ValueError, match="not available"):
        worker.run_prompt(
            {"model_id": "auto", "prompt": "x"},
            cursor=fake_cursor,
        )


def test_prompt_rejects_missing_model_id(worker, fake_cursor) -> None:
    with pytest.raises(ValueError, match="not available"):
        worker.run_prompt({"prompt": "x"}, cursor=fake_cursor)


def test_prompt_records_finished_run(worker, fake_cursor, tmp_path: Path) -> None:
    payload = worker.run_prompt(
        {"model_id": "gpt-5.6-sol-max", "prompt": "secret-prompt"},
        api_key="cursor_secret",
        workdir=str(tmp_path),
        cursor=fake_cursor,
    )
    assert payload == {
        "status": "finished",
        "text": "ok",
        "agent_id": "agent-ok",
        "run_id": "run-ok",
        "model_id": "gpt-5.6-sol-max",
        "error_kind": None,
    }
    assert _FakeAgent.last_options.kwargs["model"] == "gpt-5.6-sol-max"
    assert _FakeAgent.last_options.kwargs["api_key"] == "cursor_secret"
    assert _FakeAgent.last_options.kwargs["local"].kwargs["cwd"] == str(tmp_path)


def test_prompt_distinguishes_startup_error_from_run_error(
    worker, fake_cursor, tmp_path: Path
) -> None:
    _FakeAgent.behavior = "startup_error"
    startup = worker.run_prompt(
        {"model_id": "gpt-5.6-sol-max", "prompt": "x"},
        api_key="k",
        workdir=str(tmp_path),
        cursor=fake_cursor,
    )
    assert startup["status"] == "startup_error"
    assert startup["error_kind"] == "startup"
    assert startup["model_id"] == "gpt-5.6-sol-max"
    assert startup["agent_id"] == ""
    assert startup["run_id"] == ""
    assert "auth failed" in startup["text"]

    _FakeAgent.behavior = "run_error"
    run_err = worker.run_prompt(
        {"model_id": "gpt-5.6-sol-max", "prompt": "x"},
        api_key="k",
        workdir=str(tmp_path),
        cursor=fake_cursor,
    )
    assert run_err["status"] == "error"
    assert run_err["error_kind"] == "run"
    assert run_err["agent_id"] == "agent-err"
    assert run_err["run_id"] == "run-err"
    assert run_err["model_id"] == "gpt-5.6-sol-max"


def test_run_prompt_action_writes_result_without_leaking_secrets(
    worker, fake_cursor, tmp_path: Path, capsys
) -> None:
    request = tmp_path / "request.json"
    result = tmp_path / "result.json"
    request.write_text(
        json.dumps(
            {
                "action": "prompt",
                "model_id": "cursor-grok-4.5-high-fast",
                "prompt": "TOP-SECRET-PROMPT",
                "api_key": "cursor_TOP-SECRET-KEY",
                "workdir": str(tmp_path),
            }
        ),
        encoding="utf-8",
    )
    worker.run(request, result, cursor=fake_cursor)
    out = result.read_text(encoding="utf-8")
    payload = json.loads(out)
    assert payload["status"] == "finished"
    assert payload["model_id"] == "cursor-grok-4.5-high-fast"
    assert "TOP-SECRET-PROMPT" not in out
    assert "TOP-SECRET-KEY" not in out
    captured = capsys.readouterr()
    assert "TOP-SECRET-PROMPT" not in captured.out
    assert "TOP-SECRET-PROMPT" not in captured.err
    assert "TOP-SECRET-KEY" not in captured.out
    assert "TOP-SECRET-KEY" not in captured.err
