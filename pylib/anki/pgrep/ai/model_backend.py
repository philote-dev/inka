# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Provider-neutral model request and result contracts for shadow runs."""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from typing import Protocol, cast

_ALLOWED_ROLES = frozenset({"generator", "verifier"})
_ALLOWED_REASONING_EFFORTS = frozenset({"low", "medium", "high"})

_MODEL_SPEC_FIELDS = frozenset({"family", "model_id", "reasoning_effort"})
_REQUEST_FIELDS = frozenset(
    {
        "request_id",
        "role",
        "model",
        "system",
        "user",
        "prompt_version",
        "schema_version",
        "seed",
        "corpus_chunk_ids",
        "source_refs",
    }
)
_RESULT_REQUIRED_FIELDS = frozenset({"request_id", "model_id", "status", "text"})
_RESULT_OPTIONAL_FIELDS = frozenset({"agent_id", "run_id", "error"})

# Keep this boundary-aware expression aligned with preference.py's hardened
# training-data firewall. In particular, "marigold" must not match "gold".
_PRIVATE_MARKER = re.compile(
    r"(?i)(?<![a-z0-9])(?:"
    r"(?:gold|ets|gr9677|gr1777)(?=$|[-_/:\\])"
    r"|held[\s_-]*out(?=$|[\s_/:\\-])"
    r"|tier[\s_-]*3(?=$|[\s_/:\\-])"
    r")"
)


def _child_path(path: str, key: object) -> str:
    return f"{path}.{key}" if type(key) is str else f"{path}[{key!r}]"


def _raise_for_nonfinite(value: object, path: str = "$") -> None:
    if type(value) is float:
        if not math.isfinite(value):
            raise ValueError(f"{path}: non-finite numbers are not allowed")
    elif type(value) is dict:
        for key, nested in value.items():
            child = _child_path(path, key)
            _raise_for_nonfinite(key, f"{child} (key)")
            _raise_for_nonfinite(nested, child)
    elif type(value) in (list, tuple):
        sequence = cast(list[object] | tuple[object, ...], value)
        for index, nested in enumerate(sequence):
            _raise_for_nonfinite(nested, f"{path}[{index}]")


def _raise_for_private_marker(value: object, path: str = "$") -> None:
    if type(value) is str:
        if marker := _PRIVATE_MARKER.search(value):
            raise ValueError(
                f"{path}: private marker {marker.group(0)!r} is not allowed"
            )
    elif type(value) is dict:
        for key, nested in value.items():
            child = _child_path(path, key)
            if type(key) is str and (marker := _PRIVATE_MARKER.search(key)):
                raise ValueError(
                    f"{child} (key): private marker {marker.group(0)!r} is not allowed"
                )
            _raise_for_private_marker(nested, child)
    elif type(value) in (list, tuple):
        sequence = cast(list[object] | tuple[object, ...], value)
        for index, nested in enumerate(sequence):
            _raise_for_private_marker(nested, f"{path}[{index}]")


def _strict_object(
    value: object,
    *,
    name: str,
    required: frozenset[str],
    optional: frozenset[str] = frozenset(),
) -> dict[str, object]:
    if type(value) is not dict:
        raise ValueError(f"{name} must be an object")
    if any(type(key) is not str for key in value):
        raise ValueError(f"{name} field names must be strings")

    payload = cast(dict[str, object], value)
    fields = set(payload)
    if missing := required - fields:
        raise ValueError(f"{name} missing field(s): {', '.join(sorted(missing))}")
    if unknown := fields - required - optional:
        raise ValueError(f"{name} has unknown field(s): {', '.join(sorted(unknown))}")
    return payload


def _non_empty_string(value: object, *, name: str) -> str:
    if type(value) is not str or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _string(value: object, *, name: str) -> str:
    if type(value) is not str:
        raise ValueError(f"{name} must be a string")
    return value


def _optional_identifier(value: object, *, name: str) -> str:
    parsed = _string(value, name=name)
    if parsed and not parsed.strip():
        raise ValueError(f"{name} must be empty or a non-empty identifier")
    return parsed


def _allowed_string(
    value: object,
    *,
    name: str,
    allowed: frozenset[str],
) -> str:
    parsed = _non_empty_string(value, name=name)
    if parsed not in allowed:
        choices = ", ".join(sorted(allowed))
        raise ValueError(f"{name} must be exactly one of: {choices}")
    return parsed


def _integer(value: object, *, name: str) -> int:
    if type(value) is not int:
        raise ValueError(f"{name} must be an integer")
    return value


def _string_tuple(value: object, *, name: str) -> tuple[str, ...]:
    if type(value) not in (list, tuple):
        raise ValueError(f"{name} must be an array")
    if not value:
        raise ValueError(f"{name} must be a non-empty array")

    parsed: list[str] = []
    sequence = cast(list[object] | tuple[object, ...], value)
    for index, item in enumerate(sequence):
        parsed.append(_non_empty_string(item, name=f"{name}[{index}]"))
    return tuple(parsed)


@dataclass(frozen=True)
class ModelSpec:
    """The exact model identity and reasoning setting for one request."""

    family: str
    model_id: str
    reasoning_effort: str

    def __post_init__(self) -> None:
        _non_empty_string(self.family, name="family")
        _non_empty_string(self.model_id, name="model_id")
        _allowed_string(
            self.reasoning_effort,
            name="reasoning_effort",
            allowed=_ALLOWED_REASONING_EFFORTS,
        )


def _model_spec_from_dict(value: object) -> ModelSpec:
    payload = _strict_object(
        value,
        name="model",
        required=_MODEL_SPEC_FIELDS,
    )
    return ModelSpec(
        family=_non_empty_string(payload["family"], name="family"),
        model_id=_non_empty_string(payload["model_id"], name="model_id"),
        reasoning_effort=_allowed_string(
            payload["reasoning_effort"],
            name="reasoning_effort",
            allowed=_ALLOWED_REASONING_EFFORTS,
        ),
    )


@dataclass(frozen=True)
class ModelRequest:
    """A complete, deterministic prompt request with provenance references."""

    request_id: str
    role: str
    model: ModelSpec
    system: str
    user: str
    prompt_version: str
    schema_version: str
    seed: int
    corpus_chunk_ids: tuple[str, ...]
    source_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        model_value: object
        if type(self.model) is ModelSpec:
            model_value = {
                "family": self.model.family,
                "model_id": self.model.model_id,
                "reasoning_effort": self.model.reasoning_effort,
            }
        else:
            model_value = self.model
        request_value = {
            "request_id": self.request_id,
            "role": self.role,
            "model": model_value,
            "system": self.system,
            "user": self.user,
            "prompt_version": self.prompt_version,
            "schema_version": self.schema_version,
            "seed": self.seed,
            "corpus_chunk_ids": self.corpus_chunk_ids,
            "source_refs": self.source_refs,
        }
        _raise_for_nonfinite(request_value)
        _raise_for_private_marker(request_value)

        _non_empty_string(self.request_id, name="request_id")
        _allowed_string(self.role, name="role", allowed=_ALLOWED_ROLES)
        if type(self.model) is not ModelSpec:
            raise ValueError("model must be a ModelSpec")
        _non_empty_string(self.system, name="system")
        _non_empty_string(self.user, name="user")
        _non_empty_string(self.prompt_version, name="prompt_version")
        _non_empty_string(self.schema_version, name="schema_version")
        _integer(self.seed, name="seed")
        if type(self.corpus_chunk_ids) is not tuple:
            raise ValueError("corpus_chunk_ids must be a tuple")
        if type(self.source_refs) is not tuple:
            raise ValueError("source_refs must be a tuple")
        _string_tuple(self.corpus_chunk_ids, name="corpus_chunk_ids")
        _string_tuple(self.source_refs, name="source_refs")

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-compatible representation with arrays as lists."""
        return {
            "request_id": self.request_id,
            "role": self.role,
            "model": {
                "family": self.model.family,
                "model_id": self.model.model_id,
                "reasoning_effort": self.model.reasoning_effort,
            },
            "system": self.system,
            "user": self.user,
            "prompt_version": self.prompt_version,
            "schema_version": self.schema_version,
            "seed": self.seed,
            "corpus_chunk_ids": list(self.corpus_chunk_ids),
            "source_refs": list(self.source_refs),
        }

    @classmethod
    def from_dict(cls, value: object) -> ModelRequest:
        """Validate and normalize a serialized request."""
        _raise_for_nonfinite(value)
        _raise_for_private_marker(value)
        payload = _strict_object(
            value,
            name="model request",
            required=_REQUEST_FIELDS,
        )
        return cls(
            request_id=_non_empty_string(
                payload["request_id"],
                name="request_id",
            ),
            role=_allowed_string(
                payload["role"],
                name="role",
                allowed=_ALLOWED_ROLES,
            ),
            model=_model_spec_from_dict(payload["model"]),
            system=_non_empty_string(payload["system"], name="system"),
            user=_non_empty_string(payload["user"], name="user"),
            prompt_version=_non_empty_string(
                payload["prompt_version"],
                name="prompt_version",
            ),
            schema_version=_non_empty_string(
                payload["schema_version"],
                name="schema_version",
            ),
            seed=_integer(payload["seed"], name="seed"),
            corpus_chunk_ids=_string_tuple(
                payload["corpus_chunk_ids"],
                name="corpus_chunk_ids",
            ),
            source_refs=_string_tuple(
                payload["source_refs"],
                name="source_refs",
            ),
        )


@dataclass(frozen=True)
class ModelResult:
    """Raw provider output and identifiers for one matching request."""

    request_id: str
    model_id: str
    status: str
    text: str
    agent_id: str = ""
    run_id: str = ""
    error: str = ""

    def __post_init__(self) -> None:
        _non_empty_string(self.request_id, name="request_id")
        _non_empty_string(self.model_id, name="model_id")
        _non_empty_string(self.status, name="status")
        _string(self.text, name="text")
        _optional_identifier(self.agent_id, name="agent_id")
        _optional_identifier(self.run_id, name="run_id")
        _string(self.error, name="error")

    @classmethod
    def from_dict(
        cls,
        value: object,
        *,
        expected: ModelRequest,
    ) -> ModelResult:
        """Validate provider output and bind it to the expected request."""
        if type(expected) is not ModelRequest:
            raise ValueError("expected must be a ModelRequest")
        _raise_for_nonfinite(value)
        payload = _strict_object(
            value,
            name="model result",
            required=_RESULT_REQUIRED_FIELDS,
            optional=_RESULT_OPTIONAL_FIELDS,
        )
        result = cls(
            request_id=_non_empty_string(
                payload["request_id"],
                name="request_id",
            ),
            model_id=_non_empty_string(payload["model_id"], name="model_id"),
            status=_non_empty_string(payload["status"], name="status"),
            text=_string(payload["text"], name="text"),
            agent_id=_optional_identifier(
                payload.get("agent_id", ""),
                name="agent_id",
            ),
            run_id=_optional_identifier(
                payload.get("run_id", ""),
                name="run_id",
            ),
            error=_string(payload.get("error", ""), name="error"),
        )
        if result.request_id != expected.request_id:
            raise ValueError("result request_id does not match request")
        if result.model_id != expected.model.model_id:
            raise ValueError("result model_id does not match request")
        return result


class ModelBackend(Protocol):
    """Provider-neutral completion boundary."""

    def complete(self, request: ModelRequest) -> ModelResult: ...


def request_hash(request: ModelRequest) -> str:
    """Return the SHA-256 hash of the request's canonical JSON form."""
    if type(request) is not ModelRequest:
        raise TypeError("request must be a ModelRequest")
    raw = json.dumps(
        request.to_dict(),
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
