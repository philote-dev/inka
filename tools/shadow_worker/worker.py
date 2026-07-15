# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Isolated Cursor SDK worker for shadow-foundry model probes.

Reads ``/work/request.json`` and writes ``/work/result.json``. Supports only
``models`` and ``prompt`` actions. The ``cursor_sdk`` package is imported lazily
so root CI can load this module through an import loader without installing the
SDK.
"""

from __future__ import annotations

import json
import os
import re
import sys
from importlib import metadata
from pathlib import Path
from typing import Any

DEFAULT_REQUEST = Path("/work/request.json")
DEFAULT_RESULT = Path("/work/result.json")
DEFAULT_WORKDIR = "/work"

EXIT_SUCCESS = 0
EXIT_STARTUP_ERROR = 1
EXIT_RUN_ERROR = 2
EXIT_PROTOCOL_ERROR = 3

_MODEL_REQUEST_FIELDS = frozenset({"action"})
_PROMPT_REQUEST_FIELDS = frozenset({"action", "model_id", "prompt"})
_KNOWN_FAILURE_STATUSES = frozenset({"error", "cancelled", "expired"})

_AUTHORIZATION_RE = re.compile(
    r"(?i)(\b(?:proxy-)?authorization\s*[:=]\s*)"
    r"(?:(?:bearer|basic|token)\s+)?[^\s;,]+"
)
_BEARER_RE = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/\-=]+")
_API_KEY_RE = re.compile(r"(?i)(\bapi[-_ ]?key\s*[:=]\s*)[^\s;,]+")
_COMMON_SECRET_RE = re.compile(
    r"(?i)\b(?:cursor|crsr)_[A-Za-z0-9._-]{6,}\b"
    r"|\bsk-[A-Za-z0-9._-]{6,}\b"
)


def _jsonable(value: Any) -> Any:
    """Best-effort conversion of SDK dataclasses into JSON-safe values."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if hasattr(value, "__dict__"):
        public = {
            key: item for key, item in vars(value).items() if not key.startswith("_")
        }
        if public:
            return _jsonable(public)
    if hasattr(value, "_asdict"):
        return _jsonable(value._asdict())
    return str(value)


def _resolve_sdk(cursor: Any | None) -> tuple[Any, Any, Any, Any]:
    if cursor is not None:
        return (
            cursor,
            cursor.Agent,
            cursor.AgentOptions,
            cursor.LocalAgentOptions,
        )
    from cursor_sdk import (  # type: ignore[import-not-found]
        Agent,
        AgentOptions,
        Cursor,
        LocalAgentOptions,
    )

    return Cursor, Agent, AgentOptions, LocalAgentOptions


def _api_key() -> str:
    key = os.environ.get("CURSOR_API_KEY")
    if not key:
        raise RuntimeError("CURSOR_API_KEY is required")
    return key


def _redact(text: Any, *sensitive_values: str) -> str:
    redacted = str(text or "")
    for value in sensitive_values:
        if value:
            redacted = redacted.replace(value, "[REDACTED]")
    redacted = _AUTHORIZATION_RE.sub(r"\1[REDACTED]", redacted)
    redacted = _BEARER_RE.sub("Bearer [REDACTED]", redacted)
    redacted = _API_KEY_RE.sub(r"\1[REDACTED]", redacted)
    return _COMMON_SECRET_RE.sub("[REDACTED]", redacted)


def _startup_failure(
    error: BaseException,
    *,
    api_key: str = "",
    prompt: str = "",
    requested_model_id: str = "",
    models: bool = False,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "status": "startup_error",
        "text": _redact(
            getattr(error, "message", None) or str(error),
            api_key,
            prompt,
        ),
        "agent_id": "",
        "run_id": "",
        "model_id": "",
        "error_kind": "startup",
    }
    if requested_model_id:
        body["requested_model_id"] = requested_model_id
    if models:
        body["models"] = []
    return body


def list_models(*, cursor: Any | None = None) -> list[dict[str, Any]]:
    """Return account-listed model IDs plus parameter and variant metadata."""
    Cursor, _, _, _ = _resolve_sdk(cursor)
    models = Cursor.models.list(api_key=_api_key())
    return [
        {
            "id": model.id,
            "parameters": _jsonable(getattr(model, "parameters", ())),
            "variants": _jsonable(getattr(model, "variants", ())),
        }
        for model in models
    ]


def _sdk_version(cursor: Any | None) -> str:
    injected = getattr(cursor, "__version__", "") if cursor is not None else ""
    if isinstance(injected, str) and injected.strip():
        return injected.strip()
    return metadata.version("cursor-sdk")


def run_models(*, cursor: Any | None = None) -> dict[str, Any]:
    """Probe the account model catalog with startup-failure semantics."""
    api_key = os.environ.get("CURSOR_API_KEY", "")
    try:
        models = list_models(cursor=cursor)
        sdk_version = _sdk_version(cursor)
    except Exception as err:
        return _startup_failure(err, api_key=api_key, models=True)
    return {
        "status": "finished",
        "models": models,
        "sdk_version": sdk_version,
        "text": "",
        "agent_id": "",
        "run_id": "",
        "model_id": "",
        "error_kind": None,
    }


def _prompt_result(
    result: Any,
    *,
    requested_model_id: str,
    api_key: str,
    prompt: str,
) -> dict[str, Any]:
    agent_id = getattr(result, "agent_id", "") or ""
    run_id = getattr(result, "id", "") or ""
    sdk_status = str(getattr(result, "status", "") or "")
    returned_model = getattr(result, "model", None)
    actual_model_id = getattr(returned_model, "id", "") or ""
    base = {
        "agent_id": agent_id,
        "run_id": run_id,
        "requested_model_id": requested_model_id,
        "model_id": actual_model_id,
    }

    if not actual_model_id or actual_model_id != requested_model_id:
        reason = (
            "returned model identity is missing"
            if not actual_model_id
            else "returned model identity does not match the requested model"
        )
        return {
            **base,
            "status": "error",
            "sdk_status": sdk_status,
            "text": reason,
            "error_kind": "model_identity",
        }

    text = _redact(getattr(result, "result", "") or "", api_key, prompt)
    if sdk_status == "finished":
        return {
            **base,
            "status": "finished",
            "text": text,
            "error_kind": None,
        }
    if sdk_status in _KNOWN_FAILURE_STATUSES:
        return {
            **base,
            "status": sdk_status,
            "text": text,
            "error_kind": "run",
        }
    return {
        **base,
        "status": "error",
        "sdk_status": sdk_status,
        "text": text,
        "error_kind": "unknown_status",
    }


def run_prompt(
    payload: dict[str, Any],
    *,
    workdir: str = DEFAULT_WORKDIR,
    cursor: Any | None = None,
) -> dict[str, Any]:
    """Run one prompt and verify the SDK-reported model identity."""
    model_id = payload.get("model_id")
    if not isinstance(model_id, str) or not model_id or model_id == "auto":
        raise ValueError(f"model {model_id!r} is not available")
    prompt = payload.get("prompt")
    if not isinstance(prompt, str):
        raise ValueError("prompt must be a string")

    api_key = os.environ.get("CURSOR_API_KEY", "")
    try:
        available = {model["id"] for model in list_models(cursor=cursor)}
    except Exception as err:
        return _startup_failure(
            err,
            api_key=api_key,
            prompt=prompt,
            requested_model_id=model_id,
        )
    if model_id not in available:
        raise ValueError(f"model {model_id!r} is not available")

    _, Agent, AgentOptions, LocalAgentOptions = _resolve_sdk(cursor)
    try:
        result = Agent.prompt(
            prompt,
            AgentOptions(
                api_key=api_key,
                model=model_id,
                local=LocalAgentOptions(cwd=workdir),
            ),
        )
    except Exception as err:
        return _startup_failure(
            err,
            api_key=api_key,
            prompt=prompt,
            requested_model_id=model_id,
        )
    return _prompt_result(
        result,
        requested_model_id=model_id,
        api_key=api_key,
        prompt=prompt,
    )


def _validate_request_fields(payload: dict[str, Any], allowed: frozenset[str]) -> None:
    unexpected = sorted(set(payload) - allowed)
    if unexpected:
        raise ValueError(f"unexpected request fields: {', '.join(unexpected)}")


def _exit_code(body: dict[str, Any]) -> int:
    if body.get("status") == "finished":
        return EXIT_SUCCESS
    if body.get("status") == "startup_error":
        return EXIT_STARTUP_ERROR
    return EXIT_RUN_ERROR


def run(
    request_path: Path | str = DEFAULT_REQUEST,
    result_path: Path | str = DEFAULT_RESULT,
    *,
    cursor: Any | None = None,
) -> int:
    """Execute one worker request file, persist its result, and return exit code."""
    request = Path(request_path)
    result = Path(result_path)
    payload = json.loads(request.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("request must be a JSON object")
    action = payload.get("action")

    if action == "models":
        _validate_request_fields(payload, _MODEL_REQUEST_FIELDS)
        body = run_models(cursor=cursor)
    elif action == "prompt":
        _validate_request_fields(payload, _PROMPT_REQUEST_FIELDS)
        body = run_prompt(payload, cursor=cursor)
    else:
        raise ValueError(f"unsupported action {action!r}")

    result.write_text(json.dumps(body, sort_keys=True) + "\n", encoding="utf-8")
    return _exit_code(body)


def main(argv: list[str] | None = None) -> int:
    del argv
    try:
        return run(DEFAULT_REQUEST, DEFAULT_RESULT)
    except Exception as err:
        # Never include request payload fields that may hold secrets.
        print(f"worker failed: {type(err).__name__}", file=sys.stderr)
        return EXIT_PROTOCOL_ERROR


if __name__ == "__main__":
    raise SystemExit(main())
