# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Offline contract tests for the TrueFoundry shadow backend."""

from __future__ import annotations

import importlib
import os
import sys
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace

import pytest

from anki.pgrep.ai import llm, model_backend


def _request(
    *,
    role: str = "generator",
    model_id: str = "gateway/claude-opus-4-8",
    seed: int = 7,
    request_id: str = "shadow-request-1",
    prompt_version: str = "shadow-v1",
) -> model_backend.ModelRequest:
    return model_backend.ModelRequest(
        request_id=request_id,
        role=role,
        model=model_backend.ModelSpec("opus", model_id, "high"),
        system="Return exactly one JSON object.",
        user="Solve the safe physics prompt.",
        prompt_version=prompt_version,
        schema_version="shadow-schema/v1",
        seed=seed,
        corpus_chunk_ids=("chunk-1",),
        source_refs=("OpenStax University Physics, §1",),
    )


class _FakeClient:
    def __init__(self, result: llm.LLMResult) -> None:
        self.result = result
        self.calls: list[tuple[str, str, bool]] = []

    def complete_result(
        self,
        system: str,
        user: str,
        *,
        json_object: bool = False,
        batch_operation_id: str | None = None,
        batch_retry_offset: int = 0,
    ) -> llm.LLMResult:
        del batch_operation_id, batch_retry_offset
        self.calls.append((system, user, json_object))
        return self.result


def _gateway_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    gateway = tmp_path / "gateway.env"
    _write_gateway_env(gateway)
    monkeypatch.setenv("OPENAI_API_KEY", "ambient_direct_provider_key")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
    monkeypatch.setenv("TFY_API_KEY", "ambient_wrong_identity")
    return gateway


def _write_gateway_env(path: Path, **overrides: str) -> None:
    values = {
        "OPENAI_API_KEY": "tfy_gateway_token",
        "OPENAI_BASE_URL": "https://tfy.example/v1",
        "TFY_API_KEY": "tfy_gateway_token",
        **overrides,
    }
    path.write_text(
        "".join(f"{key}={value}\n" for key, value in values.items()),
        encoding="utf-8",
    )


def test_import_is_lazy_and_does_not_load_openai(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delitem(sys.modules, "openai", raising=False)
    monkeypatch.delitem(sys.modules, "anki.pgrep.ai.truefoundry_backend", raising=False)

    imported = importlib.import_module("anki.pgrep.ai.truefoundry_backend")

    assert imported.__name__ == "anki.pgrep.ai.truefoundry_backend"
    assert "openai" not in sys.modules


def test_complete_binds_exact_gateway_metadata_and_requests_json(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from anki.pgrep.ai import truefoundry_backend

    gateway = _gateway_env(monkeypatch, tmp_path)
    request = _request()
    fake = _FakeClient(
        llm.LLMResult(
            text='{"answer":"A"}',
            model=request.model.model_id,
            response_id="chatcmpl-tfy-1",
        )
    )
    backend = truefoundry_backend.TrueFoundryBackend(
        gateway_env_path=gateway,
        client_factory=lambda _model, **_kwargs: fake,
    )

    result = backend.complete(request)

    assert result == model_backend.ModelResult(
        request_id=request.request_id,
        model_id=request.model.model_id,
        status="finished",
        text='{"answer":"A"}',
        agent_id=truefoundry_backend.PROVIDER_IDENTITY,
        run_id="chatcmpl-tfy-1",
    )
    assert fake.calls == [(request.system, request.user, True)]


def test_gateway_loader_requires_file_despite_ambient_direct_key(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from anki.pgrep.ai import truefoundry_backend

    monkeypatch.setenv("OPENAI_API_KEY", "ambient_direct_provider_key")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://api.openai.com/v1")

    with pytest.raises(
        truefoundry_backend.TrueFoundryConfigurationError,
        match="gateway",
    ):
        truefoundry_backend.load_truefoundry_gateway(tmp_path / "missing.env")


def test_gateway_loader_overrides_ambient_provider_values(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from anki.pgrep.ai import truefoundry_backend

    gateway = tmp_path / "gateway.env"
    _write_gateway_env(gateway)
    monkeypatch.setenv("OPENAI_API_KEY", "ambient_direct_provider_key")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
    monkeypatch.setenv("TFY_API_KEY", "ambient_wrong_identity")

    loaded = truefoundry_backend.load_truefoundry_gateway(gateway)

    assert loaded.api_key == "tfy_gateway_token"
    assert loaded.base_url == "https://tfy.example/v1"
    assert loaded.tfy_api_key == "tfy_gateway_token"
    assert os.environ["OPENAI_API_KEY"] == "tfy_gateway_token"
    assert os.environ["OPENAI_BASE_URL"] == "https://tfy.example/v1"
    assert os.environ["TFY_API_KEY"] == "tfy_gateway_token"


@pytest.mark.parametrize(
    "missing",
    ["OPENAI_API_KEY", "OPENAI_BASE_URL"],
)
def test_gateway_loader_rejects_missing_required_values_without_secret_leakage(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    missing: str,
) -> None:
    from anki.pgrep.ai import truefoundry_backend

    gateway = tmp_path / "gateway.env"
    _write_gateway_env(gateway, **{missing: ""})
    monkeypatch.setenv("OPENAI_API_KEY", "ambient_secret_must_not_leak")

    with pytest.raises(truefoundry_backend.TrueFoundryConfigurationError) as raised:
        truefoundry_backend.load_truefoundry_gateway(gateway)

    assert missing in str(raised.value)
    assert "ambient_secret_must_not_leak" not in str(raised.value)
    assert "tfy_gateway_token" not in str(raised.value)


def test_gateway_loader_accepts_missing_optional_tfy_api_key(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from anki.pgrep.ai import truefoundry_backend

    gateway = tmp_path / "gateway.env"
    gateway.write_text(
        "OPENAI_API_KEY=tfy_gateway_token\nOPENAI_BASE_URL=https://tfy.example/v1\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("TFY_API_KEY", "ambient_tfy_value_must_not_be_used")

    loaded = truefoundry_backend.load_truefoundry_gateway(gateway)

    assert loaded.api_key == "tfy_gateway_token"
    assert loaded.base_url == "https://tfy.example/v1"
    assert loaded.tfy_api_key == ""
    assert "TFY_API_KEY" not in os.environ


def test_gateway_loader_accepts_all_recognized_external_variables(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from anki.pgrep.ai import truefoundry_backend

    gateway = tmp_path / "gateway.env"
    gateway.write_text(
        "OPENAI_API_KEY=tfy_gateway_token\n"
        "OPENAI_BASE_URL=https://tfy.example/v1\n"
        "TFY_API_KEY=tfy_optional_token\n"
        "ANTHROPIC_AUTH_TOKEN=anthropic_gateway_token\n"
        "ANTHROPIC_BASE_URL=https://tfy.example/anthropic\n"
        "ANTHROPIC_CUSTOM_HEADERS=x-tfy-provider:truefoundry\n",
        encoding="utf-8",
    )

    truefoundry_backend.load_truefoundry_gateway(gateway)

    assert os.environ["TFY_API_KEY"] == "tfy_optional_token"
    assert os.environ["ANTHROPIC_AUTH_TOKEN"] == "anthropic_gateway_token"
    assert os.environ["ANTHROPIC_BASE_URL"] == "https://tfy.example/anthropic"
    assert os.environ["ANTHROPIC_CUSTOM_HEADERS"] == "x-tfy-provider:truefoundry"


def test_gateway_loader_rejects_unknown_assignment_without_using_ambient_values(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from anki.pgrep.ai import truefoundry_backend

    gateway = tmp_path / "gateway.env"
    gateway.write_text(
        "OPENAI_API_KEY=tfy_gateway_token\n"
        "OPENAI_BASE_URL=https://tfy.example/v1\n"
        "UNRECOGNIZED_PROVIDER_KEY=must_not_be_accepted\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("OPENAI_API_KEY", "ambient_direct_provider_key")

    with pytest.raises(
        truefoundry_backend.TrueFoundryConfigurationError,
        match="unknown gateway variable",
    ):
        truefoundry_backend.load_truefoundry_gateway(gateway)

    assert os.environ["OPENAI_API_KEY"] == "ambient_direct_provider_key"


def test_backend_forwards_each_request_seed_to_client_factory(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from anki.pgrep.ai import truefoundry_backend

    gateway = _gateway_env(monkeypatch, tmp_path)
    constructed: list[tuple[str, float, int]] = []

    def factory(model: str, *, temperature: float, seed: int) -> _FakeClient:
        constructed.append((model, temperature, seed))
        return _FakeClient(
            llm.LLMResult(text="{}", model=model, response_id=f"run-{seed}")
        )

    backend = truefoundry_backend.TrueFoundryBackend(
        gateway_env_path=gateway,
        client_factory=factory,
    )
    generator = _request(role="generator", seed=17)
    verifier = _request(role="verifier", seed=29)

    backend.complete(generator)
    backend.complete(verifier)

    assert constructed == [
        (generator.model.model_id, 0.0, 17),
        (verifier.model.model_id, 0.0, 29),
    ]


def test_backend_passes_privacy_safe_batch_metadata_for_schema_corrections(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from anki.pgrep.ai import truefoundry_backend

    gateway = _gateway_env(monkeypatch, tmp_path)
    calls: list[tuple[str | None, int]] = []

    class MetadataClient:
        def complete_result(
            self,
            system: str,
            user: str,
            *,
            json_object: bool = False,
            batch_operation_id: str | None = None,
            batch_retry_offset: int = 0,
        ) -> llm.LLMResult:
            del system, user, json_object
            calls.append((batch_operation_id, batch_retry_offset))
            return llm.LLMResult(
                text="{}",
                model="gateway/claude-opus-4-8",
                response_id=f"run-{len(calls)}",
            )

    backend = truefoundry_backend.TrueFoundryBackend(
        gateway_env_path=gateway,
        client_factory=lambda _model, **_kwargs: MetadataClient(),
    )
    initial = _request(request_id="shadow-7-sol-generate-0")
    correction = _request(
        request_id="shadow-7-sol-correct-2",
        prompt_version="shadow-problem-schema-correction-v1",
    )
    verifier = _request(
        role="verifier",
        request_id="shadow-29-sol-verify-opus",
        prompt_version="shadow-solve-v1",
    )

    backend.complete(initial)
    backend.complete(correction)
    backend.complete(verifier)

    operation_ids = [operation_id for operation_id, _offset in calls]
    assert [offset for _operation_id, offset in calls] == [0, 2, 0]
    assert all(
        operation_id and operation_id.startswith("tfy-shadow-")
        for operation_id in operation_ids
    )
    assert len(set(operation_ids)) == 3
    for operation_id in operation_ids:
        assert initial.request_id not in str(operation_id)
        assert correction.request_id not in str(operation_id)
        assert verifier.request_id not in str(operation_id)


@pytest.mark.parametrize(
    ("result_factory", "message"),
    [
        (
            lambda: llm.LLMResult(
                text="{}",
                model="other-model",
                response_id="run-1",
            ),
            "model",
        ),
        (
            lambda: llm.LLMResult(
                text="{}",
                model="gateway/claude-opus-4-8",
                response_id="",
            ),
            "response",
        ),
        (
            lambda: llm.LLMResult(
                text="",
                model="gateway/claude-opus-4-8",
                response_id="run-1",
            ),
            "content",
        ),
    ],
)
def test_complete_fails_closed_on_invalid_gateway_response(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    result_factory: Callable[[], llm.LLMResult],
    message: str,
) -> None:
    from anki.pgrep.ai import truefoundry_backend

    gateway = _gateway_env(monkeypatch, tmp_path)
    result = result_factory()
    backend = truefoundry_backend.TrueFoundryBackend(
        gateway_env_path=gateway,
        client_factory=lambda _model, **_kwargs: _FakeClient(result),
    )

    with pytest.raises(truefoundry_backend.TrueFoundryResponseError, match=message):
        backend.complete(_request())


def test_missing_gateway_configuration_does_not_leak_token(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from anki.pgrep.ai import truefoundry_backend

    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    backend = truefoundry_backend.TrueFoundryBackend(
        gateway_env_path=tmp_path / "missing.env"
    )

    with pytest.raises(truefoundry_backend.TrueFoundryConfigurationError) as raised:
        backend.complete(_request())

    assert "tfy_secret_should_never_escape" not in str(raised.value)
    assert "gateway environment file" in str(raised.value)


def test_gateway_model_listing_is_sorted_and_uses_configured_route(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from anki.pgrep.ai import truefoundry_backend

    gateway = _gateway_env(monkeypatch, tmp_path)
    calls: list[bool] = []

    def list_models() -> list[str]:
        calls.append(True)
        return ["grok-4.5", "gateway/claude-opus-4-8", "gpt-5.5"]

    backend = truefoundry_backend.TrueFoundryBackend(
        gateway_env_path=gateway,
        model_lister=list_models,
    )

    assert backend.list_models() == [
        "gateway/claude-opus-4-8",
        "gpt-5.5",
        "grok-4.5",
    ]
    assert calls == [True]


def test_model_listing_error_exposes_only_class_and_integer_status(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from anki.pgrep.ai import truefoundry_backend

    gateway = _gateway_env(monkeypatch, tmp_path)
    secret = "tfy_secret_value"
    malicious_url = "https://gateway.example/private?token=tfy_secret_value"
    malicious_body = '{"token":"tfy_secret_value","prompt":"private"}'

    class AuthenticationError(Exception):
        def __init__(self) -> None:
            super().__init__(
                f"provider said unauthorized at {malicious_url}: {malicious_body}"
            )
            self.status_code = 401
            self.response = SimpleNamespace(
                status_code=403,
                url=malicious_url,
                text=malicious_body,
                headers={"Authorization": f"Bearer {secret}"},
            )

    def list_models() -> list[str]:
        raise AuthenticationError

    backend = truefoundry_backend.TrueFoundryBackend(
        gateway_env_path=gateway,
        model_lister=list_models,
    )

    with pytest.raises(truefoundry_backend.TrueFoundryResponseError) as raised:
        backend.list_models()

    rendered = str(raised.value)
    assert (
        rendered == "TrueFoundry model listing failed (AuthenticationError, status=401)"
    )
    for forbidden in (secret, malicious_url, malicious_body, "unauthorized", "Bearer"):
        assert forbidden not in rendered


def test_model_listing_error_without_status_exposes_only_class(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from anki.pgrep.ai import truefoundry_backend

    gateway = _gateway_env(monkeypatch, tmp_path)

    class RateLimitError(Exception):
        pass

    def list_models() -> list[str]:
        raise RateLimitError("provider body with tfy_secret_value")

    backend = truefoundry_backend.TrueFoundryBackend(
        gateway_env_path=gateway,
        model_lister=list_models,
    )

    with pytest.raises(truefoundry_backend.TrueFoundryResponseError) as raised:
        backend.list_models()

    assert str(raised.value) == "TrueFoundry model listing failed (RateLimitError)"


def test_completion_error_uses_safe_response_status_without_provider_details(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from anki.pgrep.ai import truefoundry_backend

    gateway = _gateway_env(monkeypatch, tmp_path)
    secret = "tfy_secret_value"
    malicious_url = "https://gateway.example/private?token=tfy_secret_value"
    malicious_body = '{"token":"tfy_secret_value","response":"private"}'

    class APIConnectionError(Exception):
        def __init__(self) -> None:
            super().__init__(f"{malicious_url} {malicious_body}")
            self.response = SimpleNamespace(
                status_code=503,
                url=malicious_url,
                text=malicious_body,
                headers={"Authorization": f"Bearer {secret}"},
            )

    class RaisingClient:
        def complete_result(
            self,
            system: str,
            user: str,
            *,
            json_object: bool = False,
            batch_operation_id: str | None = None,
            batch_retry_offset: int = 0,
        ) -> llm.LLMResult:
            del (
                system,
                user,
                json_object,
                batch_operation_id,
                batch_retry_offset,
            )
            raise APIConnectionError

    backend = truefoundry_backend.TrueFoundryBackend(
        gateway_env_path=gateway,
        client_factory=lambda _model, **_kwargs: RaisingClient(),
    )

    with pytest.raises(truefoundry_backend.TrueFoundryResponseError) as raised:
        backend.complete(_request())

    rendered = str(raised.value)
    assert rendered == "TrueFoundry completion failed (APIConnectionError, status=503)"
    for forbidden in (secret, malicious_url, malicious_body, "Bearer"):
        assert forbidden not in rendered


def test_backend_never_uses_cursor_credentials(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from anki.pgrep.ai import truefoundry_backend

    gateway = _gateway_env(monkeypatch, tmp_path)
    monkeypatch.setenv("CURSOR_API_KEY", "cursor_secret_should_not_be_used")
    fake = _FakeClient(
        llm.LLMResult(
            text="{}",
            model="gateway/claude-opus-4-8",
            response_id="run-1",
        )
    )
    backend = truefoundry_backend.TrueFoundryBackend(
        gateway_env_path=gateway,
        client_factory=lambda _model, **_kwargs: fake,
    )

    assert backend.complete(_request()).run_id == "run-1"
