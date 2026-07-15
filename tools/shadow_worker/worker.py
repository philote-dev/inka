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
import sys
from pathlib import Path
from typing import Any

DEFAULT_REQUEST = Path("/work/request.json")
DEFAULT_RESULT = Path("/work/result.json")


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


def _resolve_cursor(cursor: Any | None) -> Any:
    if cursor is not None:
        return cursor
    from cursor_sdk import Cursor

    return Cursor


def _resolve_agent_types(
    cursor: Any | None,
) -> tuple[Any, Any, Any, type[BaseException]]:
    if cursor is not None:
        return (
            cursor.Agent,
            cursor.AgentOptions,
            cursor.LocalAgentOptions,
            cursor.CursorAgentError,
        )
    from cursor_sdk import Agent, AgentOptions, CursorAgentError, LocalAgentOptions

    return Agent, AgentOptions, LocalAgentOptions, CursorAgentError


def list_models(*, cursor: Any | None = None, api_key: str | None = None) -> list[dict]:
    """Return account-listed model IDs plus parameter and variant metadata."""
    sdk = _resolve_cursor(cursor)
    kwargs: dict[str, Any] = {}
    if api_key is not None:
        kwargs["api_key"] = api_key
    models = sdk.models.list(**kwargs)
    return [
        {
            "id": model.id,
            "parameters": _jsonable(getattr(model, "parameters", ())),
            "variants": _jsonable(getattr(model, "variants", ())),
        }
        for model in models
    ]


def run_prompt(
    payload: dict,
    *,
    api_key: str | None = None,
    workdir: str | None = None,
    cursor: Any | None = None,
) -> dict:
    """Run one prompt against an exact listed model ID.

    Distinguishes SDK startup failures (``CursorAgentError``) from returned run
    statuses such as ``error``. Never logs the API key or prompt text.
    """
    model_id = payload.get("model_id")
    if not isinstance(model_id, str) or not model_id or model_id == "auto":
        raise ValueError(f"model {model_id!r} is not available")

    available = {model["id"] for model in list_models(cursor=cursor, api_key=api_key)}
    if model_id not in available:
        raise ValueError(f"model {model_id!r} is not available")

    Agent, AgentOptions, LocalAgentOptions, CursorAgentError = _resolve_agent_types(
        cursor
    )
    key = api_key if api_key is not None else payload.get("api_key")
    cwd = workdir if workdir is not None else payload.get("workdir") or os.getcwd()
    prompt_text = payload.get("prompt")
    if not isinstance(prompt_text, str):
        raise ValueError("prompt must be a string")
    if not isinstance(key, str) or not key:
        raise ValueError("api_key is required")

    try:
        result = Agent.prompt(
            prompt_text,
            AgentOptions(
                api_key=key,
                model=model_id,
                local=LocalAgentOptions(cwd=cwd),
            ),
        )
    except CursorAgentError as err:
        message = getattr(err, "message", None) or str(err)
        return {
            "status": "startup_error",
            "text": message,
            "agent_id": "",
            "run_id": "",
            "model_id": model_id,
            "error_kind": "startup",
        }

    status = getattr(result, "status", "")
    error_kind = "run" if status == "error" else None
    return {
        "status": status,
        "text": getattr(result, "result", None) or "",
        "agent_id": getattr(result, "agent_id", "") or "",
        "run_id": getattr(result, "id", "") or "",
        "model_id": model_id,
        "error_kind": error_kind,
    }


def run(
    request_path: Path | str = DEFAULT_REQUEST,
    result_path: Path | str = DEFAULT_RESULT,
    *,
    cursor: Any | None = None,
) -> None:
    """Execute one worker request file and write the result file."""
    request = Path(request_path)
    result = Path(result_path)
    payload = json.loads(request.read_text(encoding="utf-8"))
    action = payload.get("action")

    if action == "models":
        api_key = payload.get("api_key")
        if api_key is not None and not isinstance(api_key, str):
            raise ValueError("api_key must be a string when provided")
        body = {"models": list_models(cursor=cursor, api_key=api_key)}
    elif action == "prompt":
        body = run_prompt(
            payload,
            api_key=payload.get("api_key")
            if isinstance(payload.get("api_key"), str)
            else None,
            workdir=payload.get("workdir")
            if isinstance(payload.get("workdir"), str)
            else None,
            cursor=cursor,
        )
    else:
        raise ValueError(f"unsupported action {action!r}")

    result.write_text(json.dumps(body, sort_keys=True) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    del argv
    try:
        run()
    except Exception as err:
        # Never include request payload fields that may hold secrets.
        print(f"worker failed: {type(err).__name__}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
