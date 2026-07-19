# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""TrueFoundry's OpenAI-compatible backend for quarantined shadow runs."""

from __future__ import annotations

import hashlib
import os
from collections.abc import Callable
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Protocol

from . import llm
from .model_backend import ModelRequest, ModelResult

PROVIDER_IDENTITY = "truefoundry-openai-compatible"
DEFAULT_GATEWAY_ENV = Path("~/.config/truefoundry/gateway.env").expanduser()
_REQUIRED_GATEWAY_VARS = (
    "OPENAI_API_KEY",
    "OPENAI_BASE_URL",
)
_OPTIONAL_GATEWAY_VARS = (
    "TFY_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "ANTHROPIC_BASE_URL",
    "ANTHROPIC_CUSTOM_HEADERS",
)
_GATEWAY_VARS = _REQUIRED_GATEWAY_VARS + _OPTIONAL_GATEWAY_VARS
_SCHEMA_CORRECTION_PROMPT_VERSION = "shadow-problem-schema-correction-v1"


class TrueFoundryConfigurationError(RuntimeError):
    """The required TrueFoundry gateway route is unavailable."""


class TrueFoundryResponseError(RuntimeError):
    """A gateway response cannot be bound safely to its request."""


def openai_sdk_version() -> str:
    """Return the installed OpenAI Python package version without importing it."""
    try:
        installed = version("openai")
    except PackageNotFoundError:
        raise TrueFoundryConfigurationError(
            "OpenAI Python package metadata is unavailable"
        ) from None
    if not installed.strip():
        raise TrueFoundryConfigurationError("OpenAI Python package version is empty")
    return installed


@dataclass(frozen=True)
class TrueFoundryGateway:
    """Validated OpenAI-compatible TrueFoundry gateway configuration."""

    api_key: str
    base_url: str
    tfy_api_key: str


class _CompletionClient(Protocol):
    def complete_result(
        self,
        system: str,
        user: str,
        *,
        json_object: bool = False,
        batch_operation_id: str | None = None,
        batch_retry_offset: int = 0,
    ) -> llm.LLMResult: ...


def _safe_failure_context(error: Exception) -> str:
    """Return only a safe exception class and optional HTTP status."""
    error_type = type(error).__name__
    if not error_type.isidentifier():
        error_type = "Exception"

    status: object = None
    try:
        status = getattr(error, "status_code", None)
    except Exception:  # noqa: BLE001
        pass
    if type(status) is not int:
        try:
            response = getattr(error, "response", None)
            status = getattr(response, "status_code", None)
        except Exception:  # noqa: BLE001
            status = None
    if type(status) is int and 100 <= status <= 599:
        return f"{error_type}, status={status}"
    return error_type


def load_truefoundry_gateway(
    env_path: str | os.PathLike[str] = DEFAULT_GATEWAY_ENV,
) -> TrueFoundryGateway:
    """Load only the dedicated TrueFoundry gateway file, overriding ambient values."""
    path = Path(env_path).expanduser()
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError):
        raise TrueFoundryConfigurationError(
            "TrueFoundry gateway environment file is unavailable"
        ) from None

    values: dict[str, str] = {}
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        if key not in _GATEWAY_VARS:
            raise TrueFoundryConfigurationError(
                "TrueFoundry gateway environment contains an unknown gateway variable"
            )
        values[key] = value.strip().strip('"').strip("'")

    for name in _REQUIRED_GATEWAY_VARS:
        if not values.get(name, "").strip():
            raise TrueFoundryConfigurationError(
                f"TrueFoundry gateway environment is missing {name}"
            )
    for name in _REQUIRED_GATEWAY_VARS:
        os.environ[name] = values[name]
    for name in _OPTIONAL_GATEWAY_VARS:
        if value := values.get(name, "").strip():
            os.environ[name] = value
        else:
            os.environ.pop(name, None)
    tfy_api_key = values.get("TFY_API_KEY", "").strip()
    return TrueFoundryGateway(
        api_key=values["OPENAI_API_KEY"],
        base_url=values["OPENAI_BASE_URL"],
        tfy_api_key=tfy_api_key,
    )


def _batch_metadata(request: ModelRequest) -> tuple[str, int]:
    operation_id = (
        "tfy-shadow-" + hashlib.sha256(request.request_id.encode("utf-8")).hexdigest()
    )
    retry_offset = 0
    if request.prompt_version == _SCHEMA_CORRECTION_PROMPT_VERSION:
        _prefix, separator, suffix = request.request_id.rpartition("-")
        if not separator or not suffix.isdecimal() or int(suffix) <= 0:
            raise ValueError("schema-correction request has no retry attempt")
        retry_offset = int(suffix)
    return operation_id, retry_offset


class TrueFoundryBackend:
    """Submit exact shadow requests through the configured TrueFoundry gateway."""

    def __init__(
        self,
        *,
        gateway_env_path: str | os.PathLike[str] = DEFAULT_GATEWAY_ENV,
        client_factory: Callable[..., _CompletionClient] | None = None,
        model_lister: Callable[[], list[str]] | None = None,
    ) -> None:
        self._gateway_env_path = gateway_env_path
        self._client_factory = client_factory or llm.LLMClient
        self._model_lister = model_lister or (
            lambda: llm.list_models(load_credentials=False)
        )

    def _require_gateway_configuration(self) -> TrueFoundryGateway:
        return load_truefoundry_gateway(self._gateway_env_path)

    def list_models(self) -> list[str]:
        """Return exact gateway-visible model IDs in deterministic order."""
        self._require_gateway_configuration()
        try:
            models = self._model_lister()
        except Exception as error:  # noqa: BLE001
            context = _safe_failure_context(error)
            raise TrueFoundryResponseError(
                f"TrueFoundry model listing failed ({context})"
            ) from None
        if any(
            type(model_id) is not str or not model_id.strip() for model_id in models
        ):
            raise TrueFoundryResponseError(
                "TrueFoundry model listing contains an invalid model ID"
            )
        return sorted(models)

    def complete(self, request: ModelRequest) -> ModelResult:
        """Complete one validated request and bind gateway metadata exactly."""
        if type(request) is not ModelRequest:
            raise TypeError("request must be a ModelRequest")
        self._require_gateway_configuration()
        operation_id, retry_offset = _batch_metadata(request)
        try:
            client = self._client_factory(
                request.model.model_id,
                temperature=0.0,
                seed=request.seed,
            )
            response = client.complete_result(
                request.system,
                request.user,
                json_object=True,
                batch_operation_id=operation_id,
                batch_retry_offset=retry_offset,
            )
        except Exception as error:  # noqa: BLE001
            context = _safe_failure_context(error)
            raise TrueFoundryResponseError(
                f"TrueFoundry completion failed ({context})"
            ) from None

        if type(response.model) is not str or response.model != request.model.model_id:
            raise TrueFoundryResponseError(
                "TrueFoundry response model does not match the requested model"
            )
        if type(response.response_id) is not str or not response.response_id.strip():
            raise TrueFoundryResponseError("TrueFoundry response has no response ID")
        if type(response.text) is not str or not response.text.strip():
            raise TrueFoundryResponseError("TrueFoundry response has no content")

        return ModelResult(
            request_id=request.request_id,
            model_id=request.model.model_id,
            status="finished",
            text=response.text,
            agent_id=PROVIDER_IDENTITY,
            run_id=response.response_id,
        )
