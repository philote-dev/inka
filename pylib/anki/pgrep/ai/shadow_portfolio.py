# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Pure model allocation and cross-verification for shadow candidates."""

from __future__ import annotations

import hashlib
import json
import math
import random
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol, cast

from . import consensus, generation_core, provenance, verify
from .model_backend import (
    ModelBackend,
    ModelRequest,
    ModelResult,
    ModelSpec,
    request_hash,
)

_FAMILIES = ("sol", "opus", "grok")
_LETTERS = ("A", "B", "C", "D", "E")
_PROBLEM_KINDS = frozenset({"conceptual", "computational"})
_CANDIDATE_FIELDS = frozenset(
    {
        "stem",
        "choices",
        "key",
        "distractors",
        "solution_decomposition",
        "problem_kind",
        "difficulty",
        "confidence",
        "computational",
        "refuse",
    }
)
_DISTRACTOR_FIELDS = frozenset({"label", "misconception_tag", "rationale"})
_DECOMPOSITION_FIELDS = frozenset({"subgoal", "rubric"})
_COMPUTATIONAL_FIELDS = frozenset({"expression", "expected", "tolerance"})
_STRUCTURAL_FIELDS = (
    _CANDIDATE_FIELDS
    | _DISTRACTOR_FIELDS
    | _DECOMPOSITION_FIELDS
    | _COMPUTATIONAL_FIELDS
)
_PRIVATE_MARKER = re.compile(
    r"(?i)(?<![a-z0-9])(?:"
    r"(?:gold|ets|gr9677|gr1777)(?=$|[-_/:\\])"
    r"|held[\s_-]*out(?=$|[\s_/:\\-])"
    r"|tier[\s_-]*3(?=$|[\s_/:\\-])"
    r")"
)
_JSON_TOKEN = re.compile(
    r'"(?:\\.|[^"\\])*"'
    r"|-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?"
    r"|\b(?:true|false|null)\b"
)

SCHEMA_VERSION = "pgrep-shadow-problem/v1"
GENERATOR_PROMPT_VERSION = "shadow-problem-v1"
CORRECTION_PROMPT_VERSION = "shadow-problem-schema-correction-v1"
VERIFIER_PROMPT_VERSION = "shadow-solve-v1"
VERIFIER_SCHEMA_VERSION = "pgrep-shadow-solve/v1"
SCHEMA_CORRECTION_SYSTEM = (
    "Correct JSON representation only. Return exactly one JSON object matching "
    "the requested problem schema. Preserve every content value exactly. Do not "
    "solve the problem, add facts, remove candidate content, rewrite prose, alter "
    "numbers, or change the intended key."
)


class CandidateSchemaError(ValueError):
    """A candidate response does not satisfy the shadow problem schema."""


class CandidateRepresentationError(CandidateSchemaError):
    """The response cannot be represented by the required JSON shape."""


class CandidateContentError(CandidateSchemaError):
    """The represented candidate contains invalid or forbidden content."""


class CandidateGenerationError(CandidateSchemaError):
    """Generation did not produce a valid candidate within the correction bound."""

    def __init__(
        self,
        errors: Sequence[str],
        traces: Sequence[dict[str, object]],
    ) -> None:
        self.errors = tuple(errors)
        self.traces = tuple(traces)
        detail = self.errors[-1] if self.errors else "candidate generation failed"
        super().__init__(detail)


class _CompleteTextClient(Protocol):
    def complete_text(
        self,
        system: str,
        user: str,
        *,
        json_object: bool = False,
    ) -> str: ...


@dataclass(frozen=True)
class ModelRoles:
    """The exact model selected for each shadow portfolio family."""

    sol: ModelSpec
    opus: ModelSpec
    grok: ModelSpec

    def __post_init__(self) -> None:
        specs = (self.sol, self.opus, self.grok)
        if any(type(spec) is not ModelSpec for spec in specs):
            raise TypeError("every model role must be a ModelSpec")
        for family, spec in zip(_FAMILIES, specs, strict=True):
            if spec.family != family:
                raise ValueError(f"{family} role must use the {family!r} family")
        if len({spec.model_id for spec in specs}) != len(specs):
            raise ValueError("model roles must use distinct model IDs")

    def by_family(self, family: str) -> ModelSpec:
        """Return the exact model selected for ``family``."""
        return {
            "sol": self.sol,
            "opus": self.opus,
            "grok": self.grok,
        }[family]


def allocate_families(n: int, *, seed: int) -> list[str]:
    """Return a seeded, balanced allocation across all three model families."""
    if type(n) is not int:
        raise TypeError("n must be an integer")
    if n < 0:
        raise ValueError("n must be non-negative")
    if type(seed) is not int:
        raise TypeError("seed must be an integer")

    quotient, remainder = divmod(n, len(_FAMILIES))
    counts = {family: quotient for family in _FAMILIES}
    first_extra = (seed - 1) % len(_FAMILIES)
    for offset in range(remainder):
        counts[_FAMILIES[(first_extra + offset) % len(_FAMILIES)]] += 1

    allocation = [family for family in _FAMILIES for _ in range(counts[family])]
    random.Random(seed).shuffle(allocation)
    return allocation


def verification_families(origin: str) -> tuple[str, str]:
    """Return the two families allowed to verify an origin's candidate."""
    return {
        "sol": ("opus", "grok"),
        "opus": ("sol", "grok"),
        "grok": ("sol", "opus"),
    }[origin]


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    payload: dict[str, object] = {}
    for key, value in pairs:
        if key in payload:
            raise CandidateRepresentationError(f"duplicate field: {key}")
        payload[key] = value
    return payload


def _reject_json_constant(value: str) -> object:
    raise CandidateContentError(f"non-finite number is not allowed: {value}")


def _strict_object(
    value: object,
    *,
    name: str,
    fields: frozenset[str],
) -> dict[str, object]:
    if type(value) is not dict:
        raise CandidateRepresentationError(f"{name} must be an object")
    payload = cast(dict[str, object], value)
    present = set(payload)
    if missing := fields - present:
        raise CandidateRepresentationError(
            f"{name} missing field(s): {', '.join(sorted(missing))}"
        )
    if unknown := present - fields:
        raise CandidateRepresentationError(
            f"{name} has unknown field(s): {', '.join(sorted(unknown))}"
        )
    return payload


def _non_empty_text(value: object, *, name: str) -> str:
    if type(value) is not str:
        raise CandidateRepresentationError(f"{name} must be a string")
    if not value.strip():
        raise CandidateContentError(f"{name} must be non-empty")
    return value


def _unit_score(value: object, *, name: str) -> int | float:
    if type(value) not in (int, float):
        raise CandidateRepresentationError(f"{name} must be a number")
    score = cast(int | float, value)
    if not math.isfinite(score):
        raise CandidateContentError(f"{name} must be finite")
    if not 0.0 <= score <= 1.0:
        raise CandidateContentError(f"{name} must be between 0 and 1")
    return score


def _finite_number(value: object, *, name: str) -> int | float:
    if type(value) not in (int, float):
        raise CandidateRepresentationError(f"{name} must be a number")
    number = cast(int | float, value)
    if not math.isfinite(number):
        raise CandidateContentError(f"{name} must be finite")
    return number


def _raise_for_private_marker(value: object, path: str = "$") -> None:
    if type(value) is str:
        if marker := _PRIVATE_MARKER.search(value):
            raise CandidateContentError(
                f"{path}: private marker {marker.group(0)!r} is not allowed"
            )
    elif type(value) is dict:
        payload = cast(dict[object, object], value)
        for key, nested in payload.items():
            child = f"{path}.{key}" if type(key) is str else f"{path}[{key!r}]"
            if type(key) is str and (marker := _PRIVATE_MARKER.search(key)):
                raise CandidateContentError(
                    f"{child} (key): private marker {marker.group(0)!r} is not allowed"
                )
            _raise_for_private_marker(nested, child)
    elif type(value) is list:
        for index, nested in enumerate(cast(list[object], value)):
            _raise_for_private_marker(nested, f"{path}[{index}]")


def _validate_choices(value: object) -> list[object]:
    if type(value) is not list:
        raise CandidateRepresentationError("choices must be an array")
    choices = cast(list[object], value)
    if len(choices) != len(_LETTERS):
        raise CandidateContentError("choices must contain exactly five strings")
    for index, choice in enumerate(choices):
        _non_empty_text(choice, name=f"choices[{index}]")
    return choices


def _validate_distractors(
    value: object,
    *,
    key: str,
) -> None:
    if type(value) is not list:
        raise CandidateRepresentationError("distractors must be an array")
    distractors = cast(list[object], value)
    if len(distractors) != len(_LETTERS) - 1:
        raise CandidateContentError("distractors must contain exactly four objects")

    labels: list[str] = []
    for index, distractor in enumerate(distractors):
        name = f"distractors[{index}]"
        payload = _strict_object(
            distractor,
            name=name,
            fields=_DISTRACTOR_FIELDS,
        )
        label = _non_empty_text(payload["label"], name=f"{name}.label")
        if label not in _LETTERS:
            raise CandidateContentError(f"{name}.label must be A, B, C, D, or E")
        labels.append(label)
        _non_empty_text(
            payload["misconception_tag"],
            name=f"{name}.misconception_tag",
        )
        _non_empty_text(payload["rationale"], name=f"{name}.rationale")

    expected = set(_LETTERS) - {key}
    if len(labels) != len(set(labels)) or set(labels) != expected:
        raise CandidateContentError(
            "distractor labels must be the four distinct non-key choices"
        )


def _validate_decomposition(value: object) -> None:
    if type(value) is not list:
        raise CandidateRepresentationError("solution_decomposition must be an array")
    decomposition = cast(list[object], value)
    if not decomposition:
        raise CandidateContentError("solution_decomposition must be non-empty")
    for index, step in enumerate(decomposition):
        name = f"solution_decomposition[{index}]"
        payload = _strict_object(
            step,
            name=name,
            fields=_DECOMPOSITION_FIELDS,
        )
        _non_empty_text(payload["subgoal"], name=f"{name}.subgoal")
        _non_empty_text(payload["rubric"], name=f"{name}.rubric")


def _validate_computational(value: object) -> None:
    if value is None:
        return
    payload = _strict_object(
        value,
        name="computational",
        fields=_COMPUTATIONAL_FIELDS,
    )
    _non_empty_text(payload["expression"], name="computational.expression")
    _finite_number(payload["expected"], name="computational.expected")
    tolerance = _finite_number(
        payload["tolerance"],
        name="computational.tolerance",
    )
    if tolerance < 0:
        raise CandidateContentError("computational.tolerance must be non-negative")


def parse_candidate(text: str) -> dict[str, object]:
    """Parse and strictly validate one raw shadow-generation response."""
    if type(text) is not str:
        raise CandidateRepresentationError("candidate response must be text")
    _raise_for_private_marker(text)
    try:
        value = json.loads(
            text,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_json_constant,
        )
    except json.JSONDecodeError as err:
        raise CandidateRepresentationError(
            "candidate response must be exactly one JSON object"
        ) from err

    payload = _strict_object(
        value,
        name="candidate",
        fields=_CANDIDATE_FIELDS,
    )
    _non_empty_text(payload["stem"], name="stem")
    _validate_choices(payload["choices"])
    key = _non_empty_text(payload["key"], name="key")
    if key not in _LETTERS:
        raise CandidateContentError("key must be A, B, C, D, or E")
    _validate_distractors(payload["distractors"], key=key)
    _validate_decomposition(payload["solution_decomposition"])

    problem_kind = _non_empty_text(
        payload["problem_kind"],
        name="problem_kind",
    )
    if problem_kind not in _PROBLEM_KINDS:
        raise CandidateContentError("problem_kind must be conceptual or computational")
    _unit_score(payload["difficulty"], name="difficulty")
    _unit_score(payload["confidence"], name="confidence")
    _validate_computational(payload["computational"])
    if type(payload["refuse"]) is not bool:
        raise CandidateRepresentationError("refuse must be a boolean")
    _raise_for_private_marker(payload)
    return payload


def _normalized_atom(value: object) -> tuple[str, str]:
    if value is None:
        return ("literal", "null")
    if type(value) is bool:
        return ("literal", "true" if value else "false")
    if type(value) in (int, float):
        number = cast(int | float, value)
        if math.isfinite(number):
            return ("number", format(float(number), ".17g"))
        return ("number", str(number))
    if type(value) is str:
        text = value
        if re.fullmatch(
            r"-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?",
            text.strip(),
        ):
            try:
                return ("number", format(float(text), ".17g"))
            except ValueError:
                pass
        return ("text", text)
    return ("other", repr(value))


def _semantic_atoms(
    value: object,
    *,
    include_keys: bool = False,
) -> Counter[tuple[str, str]]:
    atoms: Counter[tuple[str, str]] = Counter()
    if type(value) is dict:
        payload = cast(dict[object, object], value)
        for key, nested in payload.items():
            if include_keys and type(key) is str and key not in _STRUCTURAL_FIELDS:
                atoms[_normalized_atom(key)] += 1
            atoms.update(_semantic_atoms(nested, include_keys=include_keys))
    elif type(value) is list:
        for nested in cast(list[object], value):
            atoms.update(_semantic_atoms(nested, include_keys=include_keys))
    else:
        atoms[_normalized_atom(value)] += 1
    return atoms


def _loosely_decoded(text: str) -> object | None:
    stripped = text.strip()
    if stripped.startswith("```") and stripped.endswith("```"):
        first_newline = stripped.find("\n")
        if first_newline >= 0:
            stripped = stripped[first_newline + 1 : -3].strip()
    try:
        return json.loads(stripped)
    except (json.JSONDecodeError, CandidateSchemaError):
        return None


def _lexical_atoms(text: str) -> Counter[tuple[str, str]]:
    atoms: Counter[tuple[str, str]] = Counter()
    for match in _JSON_TOKEN.finditer(text):
        token = match.group(0)
        try:
            decoded = json.loads(token)
        except json.JSONDecodeError:
            continue
        atoms[_normalized_atom(decoded)] += 1
    return atoms


def _ensure_representation_only(
    original_text: str,
    corrected: dict[str, object],
) -> None:
    original = _loosely_decoded(original_text)
    source_atoms = (
        _semantic_atoms(original, include_keys=True)
        if original is not None
        else _lexical_atoms(original_text)
    )
    corrected_atoms = _semantic_atoms(corrected)
    if corrected_atoms - source_atoms:
        raise CandidateContentError(
            "schema correction invented content not present in the original output"
        )

    if type(original) is dict:
        payload = cast(dict[str, object], original)
        for field in _CANDIDATE_FIELDS & set(payload):
            if _semantic_atoms(payload[field]) != _semantic_atoms(corrected[field]):
                raise CandidateContentError(
                    f"schema correction changed candidate field {field!r}"
                )


def _source_field(item: object, name: str) -> object:
    if isinstance(item, Mapping):
        return item.get(name)
    return getattr(item, name, None)


def _request_context(
    retrieved: Sequence[object],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    if not retrieved:
        raise ValueError("retrieved context must be non-empty")
    chunk_ids: list[str] = []
    source_refs: list[str] = []
    for index, item in enumerate(retrieved):
        chunk_id = _source_field(item, "chunk_id")
        source_ref = _source_field(item, "source_ref")
        if type(chunk_id) is not str or not chunk_id.strip():
            raise ValueError(f"retrieved[{index}].chunk_id must be non-empty")
        if type(source_ref) is not str or not source_ref.strip():
            raise ValueError(f"retrieved[{index}].source_ref must be non-empty")
        chunk_ids.append(chunk_id)
        source_refs.append(source_ref)
    return tuple(chunk_ids), tuple(source_refs)


def _result_dict(result: ModelResult) -> dict[str, object]:
    return {
        "request_id": result.request_id,
        "model_id": result.model_id,
        "status": result.status,
        "text": result.text,
        "agent_id": result.agent_id,
        "run_id": result.run_id,
        "error": result.error,
    }


def _trace(
    request: ModelRequest,
    result: ModelResult,
    *,
    phase: str,
    attempt: int,
) -> dict[str, object]:
    return {
        "phase": phase,
        "attempt": attempt,
        "request_hash": request_hash(request),
        "request": request.to_dict(),
        "result": _result_dict(result),
        "parse_error": None,
    }


def _complete(
    backend: ModelBackend,
    request: ModelRequest,
) -> ModelResult:
    result = backend.complete(request)
    if type(result) is not ModelResult:
        raise TypeError("backend must return a ModelResult")
    if result.request_id != request.request_id:
        raise ValueError("backend result request_id does not match request")
    if result.model_id != request.model.model_id:
        raise ValueError("backend result model_id does not match exact requested model")
    if result.status != "finished":
        raise RuntimeError(f"backend did not finish request: {result.status}")
    return result


class _GeneratorAdapter:
    def __init__(
        self,
        *,
        backend: ModelBackend,
        model: ModelSpec,
        origin: str,
        seed: int,
        chunk_ids: tuple[str, ...],
        source_refs: tuple[str, ...],
        max_schema_corrections: int,
    ) -> None:
        self._backend = backend
        self._model = model
        self._origin = origin
        self._seed = seed
        self._chunk_ids = chunk_ids
        self._source_refs = source_refs
        self._max_schema_corrections = max_schema_corrections
        self._used = False
        self.candidate: dict[str, object] | None = None
        self.traces: list[dict[str, object]] = []

    def _request(
        self,
        *,
        system: str,
        user: str,
        attempt: int,
    ) -> ModelRequest:
        correction = attempt > 0
        return ModelRequest(
            request_id=(
                f"shadow-{self._seed}-{self._origin}-"
                f"{'correct' if correction else 'generate'}-{attempt}"
            ),
            role="generator",
            model=self._model,
            system=system,
            user=user,
            prompt_version=(
                CORRECTION_PROMPT_VERSION if correction else GENERATOR_PROMPT_VERSION
            ),
            schema_version=SCHEMA_VERSION,
            seed=self._seed,
            corpus_chunk_ids=self._chunk_ids,
            source_refs=self._source_refs,
        )

    def _invoke(
        self,
        *,
        system: str,
        user: str,
        attempt: int,
    ) -> tuple[ModelResult, dict[str, object]]:
        request = self._request(
            system=system,
            user=user,
            attempt=attempt,
        )
        result = _complete(self._backend, request)
        trace = _trace(
            request,
            result,
            phase="schema_correction" if attempt else "generation",
            attempt=attempt,
        )
        self.traces.append(trace)
        return result, trace

    def complete_json(self, system: str, user: str) -> dict[str, object]:
        if self._used:
            raise RuntimeError("generator adapter permits exactly one generation pass")
        self._used = True

        result, trace = self._invoke(
            system=system,
            user=user,
            attempt=0,
        )
        original_text = result.text
        errors: list[str] = []
        try:
            self.candidate = parse_candidate(original_text)
            return self.candidate
        except CandidateSchemaError as err:
            errors.append(str(err))
            trace["parse_error"] = str(err)
            if not isinstance(err, CandidateRepresentationError):
                raise CandidateGenerationError(errors, self.traces) from err

        for attempt in range(1, self._max_schema_corrections + 1):
            correction_user = (
                f"SCHEMA ERROR:\n{errors[-1]}\n\nORIGINAL OUTPUT:\n{original_text}"
            )
            result, trace = self._invoke(
                system=SCHEMA_CORRECTION_SYSTEM,
                user=correction_user,
                attempt=attempt,
            )
            try:
                candidate = parse_candidate(result.text)
                _ensure_representation_only(original_text, candidate)
                self.candidate = candidate
                return candidate
            except CandidateSchemaError as err:
                errors.append(str(err))
                trace["parse_error"] = str(err)

        raise CandidateGenerationError(errors, self.traces)


def _stable_seed(seed: int, *parts: str) -> int:
    rendered = "\0".join((str(seed), *parts)).encode("utf-8")
    return int.from_bytes(hashlib.sha256(rendered).digest()[:8], "big")


def _choice_order(
    *,
    seed: int,
    origin: str,
    verifier: str,
    used: Sequence[tuple[int, ...]],
) -> tuple[int, ...]:
    identity = tuple(range(len(_LETTERS)))
    order = list(identity)
    random.Random(_stable_seed(seed, origin, verifier, "choice-order")).shuffle(order)
    candidate = tuple(order)
    if candidate == identity:
        candidate = candidate[1:] + candidate[:1]
    while candidate in used or candidate == identity:
        candidate = candidate[1:] + candidate[:1]
    return candidate


class _VerifierAdapter:
    def __init__(
        self,
        *,
        backend: ModelBackend,
        model: ModelSpec,
        origin: str,
        seed: int,
        chunk_ids: tuple[str, ...],
        source_refs: tuple[str, ...],
    ) -> None:
        self._backend = backend
        self._model = model
        self._origin = origin
        self._seed = seed
        self._chunk_ids = chunk_ids
        self._source_refs = source_refs
        self.trace: dict[str, object] | None = None
        self.error: Exception | None = None

    def complete_text(
        self,
        system: str,
        user: str,
        *,
        json_object: bool = False,
    ) -> str:
        del json_object
        request = ModelRequest(
            request_id=(
                f"shadow-{self._seed}-{self._origin}-verify-{self._model.family}"
            ),
            role="verifier",
            model=self._model,
            system=system,
            user=user,
            prompt_version=VERIFIER_PROMPT_VERSION,
            schema_version=VERIFIER_SCHEMA_VERSION,
            seed=self._seed,
            corpus_chunk_ids=self._chunk_ids,
            source_refs=self._source_refs,
        )
        try:
            result = _complete(self._backend, request)
        except Exception as err:
            self.error = err
            raise
        self.trace = _trace(
            request,
            result,
            phase="verification",
            attempt=0,
        )
        return result.text


def _provenance_for(
    candidate: dict[str, object],
    retrieved: Sequence[object],
) -> dict[str, object] | None:
    support = provenance.best_support(
        cast(str, candidate["stem"]),
        list(retrieved),
    )
    if (
        support is None
        or not support.source_ref.strip()
        or not support.chunk_id.strip()
        or not support.source_title.strip()
        or not math.isfinite(support.support_score)
    ):
        return None
    return cast(dict[str, object], support.as_dict())


def _giveaway_evidence(
    candidate: dict[str, object],
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    choices = cast(list[str], candidate["choices"])
    key = cast(str, candidate["key"])
    answer = choices[_LETTERS.index(key)]

    decomposition: list[dict[str, object]] = []
    for index, step in enumerate(
        cast(list[dict[str, str]], candidate["solution_decomposition"])
    ):
        text = f"{step['subgoal']} {step['rubric']}"
        if reason := verify.find_giveaway(text, answer, choice_label=key):
            decomposition.append({"index": index, "reason": reason})

    distractors: list[dict[str, object]] = []
    for index, distractor in enumerate(
        cast(list[dict[str, str]], candidate["distractors"])
    ):
        if reason := verify.find_giveaway(
            distractor["rationale"],
            answer,
            choice_label=key,
        ):
            distractors.append(
                {
                    "index": index,
                    "label": distractor["label"],
                    "reason": reason,
                }
            )
    return decomposition, distractors


def _collect_verifier_records(
    *,
    candidate: dict[str, object],
    origin: str,
    roles: ModelRoles,
    backend: ModelBackend,
    seed: int,
    chunk_ids: tuple[str, ...],
    source_refs: tuple[str, ...],
) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    used_orders: list[tuple[int, ...]] = []
    for family in verification_families(origin):
        order = _choice_order(
            seed=seed,
            origin=origin,
            verifier=family,
            used=used_orders,
        )
        used_orders.append(order)
        verifier_seed = _stable_seed(seed, origin, family, "verifier")
        client = _VerifierAdapter(
            backend=backend,
            model=roles.by_family(family),
            origin=origin,
            seed=verifier_seed,
            chunk_ids=chunk_ids,
            source_refs=source_refs,
        )
        solved = consensus.solve_once(
            cast(_CompleteTextClient, client),
            {
                "stem": candidate["stem"],
                "choices": candidate["choices"],
            },
            order=list(order),
        )
        if client.error is not None:
            raise client.error
        if client.trace is None:
            raise RuntimeError("verifier produced no call trace")
        confidence = solved.confidence if math.isfinite(solved.confidence) else 0.0
        records.append(
            {
                "family": family,
                "model_id": roles.by_family(family).model_id,
                "choice_order": [_LETTERS[index] for index in order],
                "opinion": {
                    "answer": solved.letter,
                    "reasoning": solved.reasoning,
                    "confidence": confidence,
                },
                "trace": client.trace,
            }
        )
    return records


def run_candidate(
    *,
    topic: str,
    retrieved: Sequence[object],
    origin: str,
    roles: ModelRoles,
    backend: ModelBackend,
    seed: int,
    max_schema_corrections: int = 2,
) -> dict[str, object]:
    """Generate once, then collect two origin-excluding blind solve traces."""
    if type(topic) is not str or not topic.strip():
        raise ValueError("topic must be a non-empty string")
    if type(roles) is not ModelRoles:
        raise TypeError("roles must be ModelRoles")
    if origin not in _FAMILIES:
        raise ValueError(f"unknown origin family: {origin!r}")
    if type(seed) is not int:
        raise TypeError("seed must be an integer")
    if type(max_schema_corrections) is not int:
        raise TypeError("max_schema_corrections must be an integer")
    if max_schema_corrections < 0:
        raise ValueError("max_schema_corrections must be non-negative")

    retrieved_items = list(retrieved)
    chunk_ids, source_refs = _request_context(retrieved_items)
    generator = _GeneratorAdapter(
        backend=backend,
        model=roles.by_family(origin),
        origin=origin,
        seed=seed,
        chunk_ids=chunk_ids,
        source_refs=source_refs,
        max_schema_corrections=max_schema_corrections,
    )

    generated: dict[str, object] | None = None
    generation_core_error: str | None = None
    try:
        generated = generation_core.generate_problem(
            topic=topic,
            retrieved=retrieved_items,
            llm=generator,
            verify_key=False,
            attempts=1,
        )
    except CandidateGenerationError:
        raise
    except Exception as err:  # noqa: BLE001
        if generator.candidate is None:
            raise
        generation_core_error = f"{type(err).__name__}: {err}"

    if generator.candidate is None:
        raise RuntimeError("generation core returned without a candidate")
    candidate = generator.candidate
    provenance_evidence = _provenance_for(candidate, retrieved_items)
    decomposition_giveaways, distractor_giveaways = _giveaway_evidence(candidate)

    enriched_candidate = dict(candidate)
    enriched_candidate["source_ref"] = (
        provenance_evidence["source_ref"] if provenance_evidence else None
    )
    enriched_candidate["provenance"] = provenance_evidence

    verifier_records = _collect_verifier_records(
        candidate=candidate,
        origin=origin,
        roles=roles,
        backend=backend,
        seed=seed,
        chunk_ids=chunk_ids,
        source_refs=source_refs,
    )

    cas_result: bool | None = None
    if generated is not None and type(generated.get("cas_verified")) is bool:
        cas_result = cast(bool, generated["cas_verified"])
    return {
        "schema_version": SCHEMA_VERSION,
        "topic": topic,
        "origin_family": origin,
        "candidate": enriched_candidate,
        "generator": {
            "family": origin,
            "model_id": roles.by_family(origin).model_id,
            "opinion": {
                "key": candidate["key"],
                "confidence": candidate["confidence"],
                "refuse": candidate["refuse"],
            },
            "traces": generator.traces,
        },
        "verifiers": verifier_records,
        "deterministic_evidence": {
            "provenance": provenance_evidence,
            "decomposition_giveaways": decomposition_giveaways,
            "distractor_giveaways": distractor_giveaways,
            "cas_result": cas_result,
            "generation_core_error": generation_core_error,
        },
    }
