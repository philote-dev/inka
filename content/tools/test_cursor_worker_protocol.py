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
WORKER_ROOT = REPO_ROOT / "tools" / "shadow_worker"
WORKER_PATH = WORKER_ROOT / "worker.py"


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
        self.error: Exception | None = None
        self.last_api_key: str | None = None

    def list(self, *, client=None, api_key=None):
        del client
        self.last_api_key = api_key
        if self.error:
            raise self.error
        return list(self._models)


class _FakeRunResult:
    def __init__(
        self,
        *,
        status: str,
        model_id: str | None,
        text: str = "",
        run_id: str = "run-1",
        agent_id: str = "agent-1",
    ) -> None:
        self.status = status
        self.result = text
        self.id = run_id
        self.agent_id = agent_id
        self.model = (
            types.SimpleNamespace(id=model_id) if model_id is not None else None
        )


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
    startup_error: Exception | None = None
    status = "finished"
    returned_model_id: str | None = None
    omit_model = False
    result_text = "ok"

    @classmethod
    def prompt(cls, message, options=None, *, client=None):
        del client
        cls.last_prompt = message
        cls.last_options = options
        if cls.startup_error:
            raise cls.startup_error
        requested_model = options.kwargs["model"]
        model_id = (
            None
            if cls.omit_model
            else cls.returned_model_id
            if cls.returned_model_id is not None
            else requested_model
        )
        return _FakeRunResult(
            status=cls.status,
            model_id=model_id,
            text=cls.result_text,
            run_id="run-1",
            agent_id="agent-1",
        )


@pytest.fixture
def fake_cursor(monkeypatch):
    monkeypatch.setenv("CURSOR_API_KEY", "cursor_test_secret")
    _FakeAgent.last_prompt = None
    _FakeAgent.last_options = None
    _FakeAgent.startup_error = None
    _FakeAgent.status = "finished"
    _FakeAgent.returned_model_id = None
    _FakeAgent.omit_model = False
    _FakeAgent.result_text = "ok"
    return types.SimpleNamespace(
        __version__="0.1.9-test",
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


def _prompt_payload(model_id: str = "gpt-5.6-sol-max") -> dict[str, str]:
    return {"action": "prompt", "model_id": model_id, "prompt": "private prompt"}


def test_worker_import_does_not_load_cursor_sdk(worker) -> None:
    assert worker is not None
    assert "cursor_sdk" not in sys.modules


def test_models_action_serializes_account_ids(
    worker, fake_cursor, tmp_path: Path
) -> None:
    request = tmp_path / "request.json"
    result = tmp_path / "result.json"
    request.write_text('{"action":"models"}', encoding="utf-8")
    exit_code = worker.run(request, result, cursor=fake_cursor)
    payload = json.loads(result.read_text(encoding="utf-8"))
    assert exit_code == 0
    assert payload["status"] == "finished"
    assert [m["id"] for m in payload["models"]] == [
        "claude-opus-4-8-thinking-high-fast",
        "cursor-grok-4.5-high-fast",
        "gpt-5.6-sol-max",
    ]
    assert payload["sdk_version"] == "0.1.9-test"
    assert fake_cursor.models.last_api_key == "cursor_test_secret"


def test_models_action_serializes_nested_parameter_metadata(
    worker, fake_cursor
) -> None:
    fake_cursor.models._models = [
        _FakeModel(
            "gpt-5.6-sol-max",
            parameters=(
                types.SimpleNamespace(
                    id="reasoning",
                    display_name="Reasoning",
                    values=(types.SimpleNamespace(value="high", display_name="High"),),
                ),
            ),
            variants=(
                types.SimpleNamespace(
                    display_name="Max",
                    params=(types.SimpleNamespace(id="max", value="true"),),
                    is_default=True,
                ),
            ),
        )
    ]
    assert worker.list_models(cursor=fake_cursor) == [
        {
            "id": "gpt-5.6-sol-max",
            "parameters": [
                {
                    "id": "reasoning",
                    "display_name": "Reasoning",
                    "values": [{"value": "high", "display_name": "High"}],
                }
            ],
            "variants": [
                {
                    "display_name": "Max",
                    "params": [{"id": "max", "value": "true"}],
                    "is_default": True,
                }
            ],
        }
    ]


def test_prompt_rejects_auto_even_when_catalog_lists_it(worker, fake_cursor) -> None:
    fake_cursor.models._models.append(_FakeModel("auto"))
    with pytest.raises(ValueError, match="not available"):
        worker.run_prompt(_prompt_payload("auto"), cursor=fake_cursor)


def test_prompt_rejects_arbitrary_unlisted_model(worker, fake_cursor) -> None:
    with pytest.raises(ValueError, match="not available"):
        worker.run_prompt(_prompt_payload("invented-model"), cursor=fake_cursor)


def test_prompt_rejects_missing_model_id(worker, fake_cursor) -> None:
    with pytest.raises(ValueError, match="not available"):
        worker.run_prompt(
            {"action": "prompt", "prompt": "private prompt"},
            cursor=fake_cursor,
        )


def test_prompt_records_verified_finished_model(
    worker, fake_cursor, tmp_path: Path
) -> None:
    payload = worker.run_prompt(
        _prompt_payload(),
        workdir=str(tmp_path),
        cursor=fake_cursor,
    )
    assert payload == {
        "status": "finished",
        "text": "ok",
        "agent_id": "agent-1",
        "run_id": "run-1",
        "requested_model_id": "gpt-5.6-sol-max",
        "model_id": "gpt-5.6-sol-max",
        "error_kind": None,
    }
    assert _FakeAgent.last_options.kwargs["model"] == "gpt-5.6-sol-max"
    assert _FakeAgent.last_options.kwargs["api_key"] == "cursor_test_secret"
    assert _FakeAgent.last_options.kwargs["local"].kwargs["cwd"] == str(tmp_path)


def test_prompt_fails_when_returned_model_is_substituted(worker, fake_cursor) -> None:
    _FakeAgent.returned_model_id = "different-model"
    payload = worker.run_prompt(_prompt_payload(), cursor=fake_cursor)
    assert payload["status"] == "error"
    assert payload["error_kind"] == "model_identity"
    assert payload["requested_model_id"] == "gpt-5.6-sol-max"
    assert payload["model_id"] == "different-model"
    assert "gpt-5.6-sol-max" not in payload["model_id"]


def test_prompt_fails_when_returned_model_is_missing(worker, fake_cursor) -> None:
    _FakeAgent.omit_model = True
    payload = worker.run_prompt(_prompt_payload(), cursor=fake_cursor)
    assert payload["status"] == "error"
    assert payload["error_kind"] == "model_identity"
    assert payload["requested_model_id"] == "gpt-5.6-sol-max"
    assert payload["model_id"] == ""


def test_list_models_sdk_exception_is_startup_error(
    worker, fake_cursor, tmp_path: Path
) -> None:
    fake_cursor.models.error = _FakeCursorAgentError("authentication failed")
    request = tmp_path / "request.json"
    result = tmp_path / "result.json"
    request.write_text('{"action":"models"}', encoding="utf-8")
    exit_code = worker.run(request, result, cursor=fake_cursor)
    payload = json.loads(result.read_text(encoding="utf-8"))
    assert exit_code == 1
    assert payload["status"] == "startup_error"
    assert payload["error_kind"] == "startup"
    assert payload["models"] == []


def test_prompt_sdk_exception_is_startup_error(worker, fake_cursor) -> None:
    _FakeAgent.startup_error = _FakeCursorAgentError("network unavailable")
    payload = worker.run_prompt(_prompt_payload(), cursor=fake_cursor)
    assert payload["status"] == "startup_error"
    assert payload["error_kind"] == "startup"
    assert payload["requested_model_id"] == "gpt-5.6-sol-max"
    assert payload["model_id"] == ""
    assert payload["agent_id"] == ""
    assert payload["run_id"] == ""


@pytest.mark.parametrize("status", ["error", "cancelled", "expired"])
def test_terminal_nonfinished_status_is_explicit_run_failure(
    worker, fake_cursor, tmp_path: Path, status: str
) -> None:
    _FakeAgent.status = status
    request = tmp_path / "request.json"
    result = tmp_path / "result.json"
    request.write_text(json.dumps(_prompt_payload()), encoding="utf-8")
    exit_code = worker.run(request, result, cursor=fake_cursor)
    payload = json.loads(result.read_text(encoding="utf-8"))
    assert exit_code != 0
    assert payload["status"] == status
    assert payload["error_kind"] == "run"
    assert payload["model_id"] == "gpt-5.6-sol-max"


def test_unknown_status_is_explicit_failure(
    worker, fake_cursor, tmp_path: Path
) -> None:
    _FakeAgent.status = "surprising"
    request = tmp_path / "request.json"
    result = tmp_path / "result.json"
    request.write_text(json.dumps(_prompt_payload()), encoding="utf-8")
    exit_code = worker.run(request, result, cursor=fake_cursor)
    payload = json.loads(result.read_text(encoding="utf-8"))
    assert exit_code != 0
    assert payload["status"] == "error"
    assert payload["sdk_status"] == "surprising"
    assert payload["error_kind"] == "unknown_status"


def test_protocol_rejects_api_key_in_request(
    worker, fake_cursor, tmp_path: Path
) -> None:
    request = tmp_path / "request.json"
    result = tmp_path / "result.json"
    payload = _prompt_payload() | {"api_key": "must-not-be-here"}
    request.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="unexpected request fields"):
        worker.run(request, result, cursor=fake_cursor)


def test_startup_errors_redact_environment_key_prompt_and_authorization_tokens(
    worker, fake_cursor, monkeypatch
) -> None:
    key = "cursor_super_secret_value"
    prompt = "PRIVATE-PROMPT-CONTENT"
    monkeypatch.setenv("CURSOR_API_KEY", key)
    _FakeAgent.startup_error = _FakeCursorAgentError(
        f"failed {key}; prompt={prompt}; "
        "Authorization: Bearer eyJhbGciOiJIUzI1Ni.secret; "
        "Proxy-Authorization: Basic dXNlcjpwYXNzd29yZA==; "
        "api_key=sk-another-secret"
    )
    payload = worker.run_prompt(
        {"action": "prompt", "model_id": "gpt-5.6-sol-max", "prompt": prompt},
        cursor=fake_cursor,
    )
    persisted = json.dumps(payload)
    assert payload["status"] == "startup_error"
    assert "[REDACTED]" in persisted
    assert key not in persisted
    assert prompt not in persisted
    assert "eyJhbGciOiJIUzI1Ni.secret" not in persisted
    assert "dXNlcjpwYXNzd29yZA==" not in persisted
    assert "sk-another-secret" not in persisted


def test_returned_error_text_redacts_secrets(worker, fake_cursor, monkeypatch) -> None:
    key = "cursor_result_secret"
    monkeypatch.setenv("CURSOR_API_KEY", key)
    _FakeAgent.status = "error"
    _FakeAgent.result_text = f"Authorization=Bearer token-value api-key: {key}"
    payload = worker.run_prompt(_prompt_payload(), cursor=fake_cursor)
    persisted = json.dumps(payload)
    assert payload["error_kind"] == "run"
    assert key not in persisted
    assert "token-value" not in persisted


def test_dockerfile_pins_exact_uv_python_and_digests() -> None:
    dockerfile = (WORKER_ROOT / "Dockerfile").read_text(encoding="utf-8")
    from_lines = [line for line in dockerfile.splitlines() if line.startswith("FROM ")]
    assert "ghcr.io/astral-sh/uv:0.9.17@sha256:" in from_lines[0]
    assert "python:3.13.13-slim-bookworm@sha256:" in from_lines[1]
    assert all("@sha256:" in line for line in from_lines)
    assert "COPY . " not in dockerfile


def test_dockerignore_whitelists_worker_runtime_files() -> None:
    dockerignore = (WORKER_ROOT / ".dockerignore").read_text(encoding="utf-8")
    assert dockerignore.startswith("*\n")
    assert "!.venv" not in dockerignore
    assert "!worker.py" in dockerignore
    assert "!pyproject.toml" in dockerignore
    assert "!uv.lock" in dockerignore
    assert "__pycache__/" in dockerignore
    assert "test*" in dockerignore


def test_worker_sync_recipe_uses_out_environment() -> None:
    justfile = (REPO_ROOT / "justfile").read_text(encoding="utf-8")
    assert "shadow-worker-sync:" in justfile
    assert 'UV_PROJECT_ENVIRONMENT="$PWD/out/shadow-worker-venv"' in justfile
    assert "sync --project tools/shadow_worker --locked --no-config" in justfile
