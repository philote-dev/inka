# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

from __future__ import annotations

import hashlib
import json
import math
from typing import cast

import pytest

from anki.pgrep.ai import model_backend


def _request() -> model_backend.ModelRequest:
    return model_backend.ModelRequest(
        request_id="req-1",
        role="generator",
        model=model_backend.ModelSpec(
            family="sol",
            model_id="gpt-5.6-sol-max",
            reasoning_effort="high",
        ),
        system="Return JSON.",
        user="CORPUS CONTEXT: x",
        prompt_version="shadow-problem-v1",
        schema_version="pgrep-shadow-problem/v1",
        seed=7,
        corpus_chunk_ids=("chunk-1",),
        source_refs=("OpenStax, p. 1",),
    )


def _set_path(payload: dict, path: tuple[str, ...], value: object) -> None:
    node = payload
    for key in path[:-1]:
        node = node[key]
    node[path[-1]] = value


def _result_payload() -> dict:
    request = _request()
    return {
        "request_id": request.request_id,
        "model_id": request.model.model_id,
        "status": "finished",
        "text": "{}",
    }


def test_request_json_round_trip_preserves_tuples_and_hash() -> None:
    request = _request()
    payload = request.to_dict()

    assert payload["corpus_chunk_ids"] == ["chunk-1"]
    assert payload["source_refs"] == ["OpenStax, p. 1"]
    restored = model_backend.ModelRequest.from_dict(json.loads(json.dumps(payload)))

    assert restored == request
    assert model_backend.request_hash(restored) == model_backend.request_hash(request)


def test_request_from_dict_normalizes_tuple_arrays() -> None:
    request = _request()
    payload = request.to_dict()
    payload["corpus_chunk_ids"] = tuple(cast(list[str], payload["corpus_chunk_ids"]))
    payload["source_refs"] = tuple(cast(list[str], payload["source_refs"]))

    assert model_backend.ModelRequest.from_dict(payload) == request


def test_request_hash_uses_canonical_utf8_json() -> None:
    request = model_backend.ModelRequest.from_dict(
        {
            **_request().to_dict(),
            "source_refs": ["Étude, §1"],
        }
    )
    raw = json.dumps(
        request.to_dict(),
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )

    assert (
        model_backend.request_hash(request)
        == hashlib.sha256(raw.encode("utf-8")).hexdigest()
    )


@pytest.mark.parametrize("role", ["generator", "verifier"])
def test_request_accepts_exact_roles(role: str) -> None:
    payload = _request().to_dict()
    payload["role"] = role

    assert model_backend.ModelRequest.from_dict(payload).role == role


@pytest.mark.parametrize("role", ["Generator", "judge", " generator", ""])
def test_request_rejects_role_variants(role: str) -> None:
    payload = _request().to_dict()
    payload["role"] = role

    with pytest.raises(ValueError, match="role"):
        model_backend.ModelRequest.from_dict(payload)


@pytest.mark.parametrize("effort", ["low", "medium", "high"])
def test_model_spec_accepts_exact_reasoning_values(effort: str) -> None:
    spec = model_backend.ModelSpec("family", "model", effort)

    assert spec.reasoning_effort == effort


@pytest.mark.parametrize("effort", ["High", "none", " high", ""])
def test_model_spec_rejects_reasoning_variants(effort: str) -> None:
    with pytest.raises(ValueError, match="reasoning_effort"):
        model_backend.ModelSpec("family", "model", effort)


@pytest.mark.parametrize(
    "path",
    [
        ("request_id",),
        ("system",),
        ("user",),
        ("prompt_version",),
        ("schema_version",),
        ("model", "family"),
        ("model", "model_id"),
    ],
)
@pytest.mark.parametrize("invalid", ["", "   "])
def test_request_rejects_empty_required_strings(
    path: tuple[str, ...], invalid: str
) -> None:
    payload = _request().to_dict()
    _set_path(payload, path, invalid)

    with pytest.raises(ValueError, match=path[-1]):
        model_backend.ModelRequest.from_dict(payload)


@pytest.mark.parametrize(
    ("path", "invalid"),
    [
        (("request_id",), 1),
        (("role",), 1),
        (("system",), None),
        (("user",), ["context"]),
        (("prompt_version",), 1),
        (("schema_version",), 1),
        (("model", "family"), 1),
        (("model", "model_id"), None),
        (("model", "reasoning_effort"), 1),
        (("seed",), True),
        (("seed",), 7.0),
        (("seed",), "7"),
        (("corpus_chunk_ids",), "chunk-1"),
        (("corpus_chunk_ids",), {"chunk-1"}),
        (("source_refs",), "OpenStax"),
        (("source_refs",), {"OpenStax"}),
    ],
)
def test_request_rejects_wrong_field_types(
    path: tuple[str, ...], invalid: object
) -> None:
    payload = _request().to_dict()
    _set_path(payload, path, invalid)

    with pytest.raises(ValueError, match=path[-1]):
        model_backend.ModelRequest.from_dict(payload)


@pytest.mark.parametrize("nonfinite", [math.nan, math.inf, -math.inf])
def test_request_rejects_nonfinite_numbers(nonfinite: float) -> None:
    payload = _request().to_dict()
    payload["seed"] = nonfinite

    with pytest.raises(ValueError, match="non-finite"):
        model_backend.ModelRequest.from_dict(payload)


@pytest.mark.parametrize("field", ["corpus_chunk_ids", "source_refs"])
def test_request_rejects_empty_or_invalid_identifier_arrays(field: str) -> None:
    payload = _request().to_dict()
    payload[field] = []
    with pytest.raises(ValueError, match=field):
        model_backend.ModelRequest.from_dict(payload)

    payload[field] = ["valid", " "]
    with pytest.raises(ValueError, match=field):
        model_backend.ModelRequest.from_dict(payload)

    payload[field] = ["valid", 1]
    with pytest.raises(ValueError, match=field):
        model_backend.ModelRequest.from_dict(payload)


@pytest.mark.parametrize(
    ("target", "field"),
    [
        ("request", "unexpected"),
        ("model", "unexpected"),
    ],
)
def test_request_rejects_unknown_fields(target: str, field: str) -> None:
    payload = _request().to_dict()
    node = payload if target == "request" else cast(dict[str, object], payload["model"])
    node[field] = "value"

    with pytest.raises(ValueError, match="unknown field"):
        model_backend.ModelRequest.from_dict(payload)


@pytest.mark.parametrize(
    ("target", "field"),
    [
        ("request", "seed"),
        ("model", "family"),
    ],
)
def test_request_rejects_missing_fields(target: str, field: str) -> None:
    payload = _request().to_dict()
    node = payload if target == "request" else cast(dict[str, object], payload["model"])
    del node[field]

    with pytest.raises(ValueError, match="missing field"):
        model_backend.ModelRequest.from_dict(payload)


@pytest.mark.parametrize("payload", [None, [], "request"])
def test_request_requires_an_object(payload: object) -> None:
    with pytest.raises(ValueError, match="object"):
        model_backend.ModelRequest.from_dict(payload)


@pytest.mark.parametrize("model", [None, [], "model"])
def test_request_model_requires_an_object(model: object) -> None:
    payload = _request().to_dict()
    payload["model"] = model

    with pytest.raises(ValueError, match="model.*object"):
        model_backend.ModelRequest.from_dict(payload)


@pytest.mark.parametrize(
    "marker",
    [
        "gold-17",
        "gold_17",
        "gold/17",
        "heldout:17",
        "held-out:17",
        "held_out/17",
        "held out:17",
        "ets-17",
        "tier 3/item",
        "tier3_17",
        "tier-3/17",
        "tier_3:17",
        "gr9677/17",
        "gr1777_17",
    ],
)
def test_request_rejects_private_marker_separator_variants(marker: str) -> None:
    payload = _request().to_dict()
    payload["source_refs"] = [f"corpus/{marker}"]

    with pytest.raises(ValueError, match="private marker"):
        model_backend.ModelRequest.from_dict(payload)


def test_request_detects_private_markers_in_nested_keys() -> None:
    payload = _request().to_dict()
    cast(dict[str, object], payload["model"])["gold_ref"] = "hidden"

    with pytest.raises(ValueError, match=r"\$\.model\.gold_ref.*private marker"):
        model_backend.ModelRequest.from_dict(payload)


def test_request_direct_constructor_enforces_private_marker_firewall() -> None:
    with pytest.raises(ValueError, match="private marker"):
        model_backend.ModelRequest(
            request_id="req-1",
            role="generator",
            model=model_backend.ModelSpec("sol", "gpt-5.6-sol-max", "high"),
            system="Return JSON.",
            user="content/tier3-private/items/form.json",
            prompt_version="shadow-problem-v1",
            schema_version="pgrep-shadow-problem/v1",
            seed=7,
            corpus_chunk_ids=("chunk-1",),
            source_refs=("OpenStax, p. 1",),
        )


def test_request_allows_benign_marigold_text() -> None:
    payload = _request().to_dict()
    payload["user"] = "A marigold is placed near a converging lens."
    payload["source_refs"] = ["marigold/17"]

    assert model_backend.ModelRequest.from_dict(payload).user == payload["user"]


def test_result_round_trip_fills_optional_metadata_defaults() -> None:
    result = model_backend.ModelResult.from_dict(
        _result_payload(),
        expected=_request(),
    )

    assert result == model_backend.ModelResult(
        request_id="req-1",
        model_id="gpt-5.6-sol-max",
        status="finished",
        text="{}",
    )
    assert result.agent_id == result.run_id == result.error == ""


def test_result_accepts_error_metadata_and_empty_text() -> None:
    payload = {
        **_result_payload(),
        "status": "error",
        "text": "",
        "agent_id": "agent-1",
        "run_id": "run-1",
        "error": "backend failed",
    }

    result = model_backend.ModelResult.from_dict(payload, expected=_request())

    assert result.error == "backend failed"
    assert result.text == ""


@pytest.mark.parametrize(
    ("field", "invalid"),
    [
        ("request_id", ""),
        ("request_id", 1),
        ("model_id", " "),
        ("model_id", None),
        ("status", ""),
        ("status", 1),
        ("text", None),
        ("agent_id", None),
        ("agent_id", " "),
        ("run_id", 1),
        ("run_id", "\t"),
        ("error", []),
    ],
)
def test_result_rejects_invalid_field_values(field: str, invalid: object) -> None:
    payload = {
        **_result_payload(),
        "agent_id": "",
        "run_id": "",
        "error": "",
    }
    payload[field] = invalid

    with pytest.raises(ValueError, match=field):
        model_backend.ModelResult.from_dict(payload, expected=_request())


def test_result_rejects_unknown_and_missing_fields() -> None:
    payload = _result_payload()
    payload["unexpected"] = True
    with pytest.raises(ValueError, match="unknown field"):
        model_backend.ModelResult.from_dict(payload, expected=_request())

    payload = _result_payload()
    del payload["status"]
    with pytest.raises(ValueError, match="missing field"):
        model_backend.ModelResult.from_dict(payload, expected=_request())


@pytest.mark.parametrize("payload", [None, [], "result"])
def test_result_requires_an_object(payload: object) -> None:
    with pytest.raises(ValueError, match="object"):
        model_backend.ModelResult.from_dict(payload, expected=_request())


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("request_id", "other"),
        ("model_id", "other-model"),
    ],
)
def test_result_requires_matching_request_and_model(field: str, value: str) -> None:
    payload = _result_payload()
    payload[field] = value

    with pytest.raises(ValueError, match=field):
        model_backend.ModelResult.from_dict(payload, expected=_request())
