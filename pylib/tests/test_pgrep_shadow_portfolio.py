# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

from __future__ import annotations

import json
import math
import re
from collections import Counter
from typing import cast

import pytest

from anki.pgrep.ai import model_backend, shadow_portfolio


def _roles() -> shadow_portfolio.ModelRoles:
    return shadow_portfolio.ModelRoles(
        sol=model_backend.ModelSpec("sol", "gpt-5.6-sol-max", "high"),
        opus=model_backend.ModelSpec(
            "opus",
            "claude-opus-4-8-thinking-high-fast",
            "high",
        ),
        grok=model_backend.ModelSpec(
            "grok",
            "cursor-grok-4.5-high-fast",
            "high",
        ),
    )


def _candidate() -> dict[str, object]:
    return {
        "stem": "A particle moves in a circle. Which statement is correct?",
        "choices": [
            "The speed is constant.",
            "The velocity is constant.",
            "The acceleration is zero.",
            "The momentum is zero.",
            "The radius must increase.",
        ],
        "key": "A",
        "distractors": [
            {
                "label": "B",
                "misconception_tag": "speed-is-velocity",
                "rationale": "Confuses constant speed with constant velocity.",
            },
            {
                "label": "C",
                "misconception_tag": "no-tangential-change",
                "rationale": "Ignores centripetal acceleration.",
            },
            {
                "label": "D",
                "misconception_tag": "vector-cancellation",
                "rationale": "Treats changing momentum as zero momentum.",
            },
            {
                "label": "E",
                "misconception_tag": "radius-drift",
                "rationale": "Assumes circular motion cannot stay bounded.",
            },
        ],
        "solution_decomposition": [
            {
                "subgoal": "Separate speed from velocity.",
                "rubric": "Identifies velocity as a vector.",
            },
            {
                "subgoal": "Identify the invariant scalar.",
                "rubric": "Uses the definition of uniform circular motion.",
            },
        ],
        "problem_kind": "conceptual",
        "difficulty": 0.4,
        "confidence": 0.8,
        "computational": None,
        "refuse": False,
    }


def _candidate_json(**changes: object) -> str:
    candidate = _candidate()
    candidate.update(changes)
    return json.dumps(candidate)


def test_allocation_is_14_13_13_and_deterministic() -> None:
    first = shadow_portfolio.allocate_families(40, seed=7)
    second = shadow_portfolio.allocate_families(40, seed=7)

    assert first == second
    assert Counter(first) == {"sol": 14, "opus": 13, "grok": 13}


@pytest.mark.parametrize("n", range(12))
def test_allocation_is_balanced_for_arbitrary_size(n: int) -> None:
    counts = Counter(shadow_portfolio.allocate_families(n, seed=17))

    values = [counts[family] for family in ("sol", "opus", "grok")]
    assert sum(values) == n
    assert max(values, default=0) - min(values, default=0) <= 1


def test_remainder_rotates_without_family_advantage() -> None:
    owners = [
        next(
            family
            for family, count in Counter(
                shadow_portfolio.allocate_families(40, seed=seed)
            ).items()
            if count == 14
        )
        for seed in (7, 8, 9)
    ]

    assert owners == ["sol", "opus", "grok"]


@pytest.mark.parametrize(
    ("origin", "judges"),
    [
        ("sol", ("opus", "grok")),
        ("opus", ("sol", "grok")),
        ("grok", ("sol", "opus")),
    ],
)
def test_origin_never_judges_its_candidate(
    origin: str,
    judges: tuple[str, str],
) -> None:
    assert shadow_portfolio.verification_families(origin) == judges
    assert origin not in judges


def test_model_roles_resolve_exact_specs() -> None:
    roles = _roles()

    assert roles.by_family("sol").model_id == "gpt-5.6-sol-max"
    assert roles.by_family("opus").model_id == "claude-opus-4-8-thinking-high-fast"
    assert roles.by_family("grok").model_id == "cursor-grok-4.5-high-fast"


@pytest.mark.parametrize(("n", "seed"), [(-1, 0), (1.0, 0), (True, 0), (1, 1.0)])
def test_allocation_rejects_invalid_arguments(n: object, seed: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        shadow_portfolio.allocate_families(n, seed=seed)  # type: ignore[arg-type]


def test_parse_candidate_accepts_exact_schema() -> None:
    candidate = _candidate()

    assert shadow_portfolio.parse_candidate(json.dumps(candidate)) == candidate


@pytest.mark.parametrize(
    "rendered",
    [
        "[]",
        "```json\n{}\n```",
        "{}{}",
        '{"stem":"first","stem":"second"}',
    ],
)
def test_parse_candidate_requires_exactly_one_unwrapped_object(
    rendered: str,
) -> None:
    with pytest.raises(ValueError):
        shadow_portfolio.parse_candidate(rendered)


@pytest.mark.parametrize(
    "mutation",
    [
        {"extra": "unknown"},
        {"stem": None},
    ],
)
def test_parse_candidate_rejects_unknown_or_missing_fields(
    mutation: dict[str, object],
) -> None:
    candidate = _candidate()
    if mutation.get("stem", object()) is None:
        del candidate["stem"]
    else:
        candidate.update(mutation)

    with pytest.raises(ValueError, match="field"):
        shadow_portfolio.parse_candidate(json.dumps(candidate))


@pytest.mark.parametrize(
    "choices",
    [
        ["A", "B", "C", "D"],
        ["A", "B", "C", "D", ""],
        ["A", "B", "C", "D", 5],
        {"A": "one", "B": "two", "C": "three", "D": "four", "E": "five"},
    ],
)
def test_parse_candidate_requires_five_non_empty_choice_strings(
    choices: object,
) -> None:
    with pytest.raises(ValueError, match="choices"):
        shadow_portfolio.parse_candidate(_candidate_json(choices=choices))


@pytest.mark.parametrize("key", ["", "F", "a", 1, None])
def test_parse_candidate_requires_exact_a_to_e_key(key: object) -> None:
    with pytest.raises(ValueError, match="key"):
        shadow_portfolio.parse_candidate(_candidate_json(key=key))


@pytest.mark.parametrize("field", ["difficulty", "confidence"])
@pytest.mark.parametrize(
    "score",
    [math.nan, math.inf, -math.inf, True, "0.5", -0.1, 1.1],
)
def test_parse_candidate_requires_finite_unit_interval_scores(
    field: str,
    score: object,
) -> None:
    with pytest.raises(ValueError):
        shadow_portfolio.parse_candidate(_candidate_json(**{field: score}))


@pytest.mark.parametrize("kind", ["", "numeric", "Conceptual", 1])
def test_parse_candidate_requires_known_problem_kind(kind: object) -> None:
    with pytest.raises(ValueError, match="problem_kind"):
        shadow_portfolio.parse_candidate(_candidate_json(problem_kind=kind))


def test_parse_candidate_requires_four_distinct_non_key_distractors() -> None:
    candidate = _candidate()
    distractors = list(cast(list[dict[str, str]], candidate["distractors"]))
    distractors[-1] = dict(distractors[0])

    with pytest.raises(ValueError, match="distractor"):
        shadow_portfolio.parse_candidate(
            _candidate_json(distractors=distractors),
        )


@pytest.mark.parametrize(
    "distractor",
    [
        {"label": "B", "misconception_tag": "x", "rationale": ""},
        {
            "label": "B",
            "misconception_tag": "x",
            "rationale": "r",
            "extra": "x",
        },
        "not an object",
    ],
)
def test_parse_candidate_requires_structured_distractors(
    distractor: object,
) -> None:
    distractors: list[object] = list(
        cast(list[dict[str, str]], _candidate()["distractors"])
    )
    distractors[0] = distractor

    with pytest.raises(ValueError, match="distractor"):
        shadow_portfolio.parse_candidate(
            _candidate_json(distractors=distractors),
        )


@pytest.mark.parametrize(
    "decomposition",
    [
        [],
        [{"subgoal": "", "rubric": "r"}],
        [{"subgoal": "s", "rubric": "r", "extra": "x"}],
        ["not an object"],
    ],
)
def test_parse_candidate_requires_structured_decomposition(
    decomposition: object,
) -> None:
    with pytest.raises(ValueError, match="solution_decomposition"):
        shadow_portfolio.parse_candidate(
            _candidate_json(solution_decomposition=decomposition),
        )


def test_parse_candidate_preserves_decomposition_for_later_leak_evidence() -> None:
    leaky = [{"subgoal": "Reveal", "rubric": "The answer is choice A."}]

    parsed = shadow_portfolio.parse_candidate(
        _candidate_json(solution_decomposition=leaky),
    )

    assert parsed["solution_decomposition"] == leaky


@pytest.mark.parametrize(
    "computational",
    [
        {"expression": "", "expected": 1.0, "tolerance": 0.01},
        {"expression": "2", "expected": math.inf, "tolerance": 0.01},
        {"expression": "2", "expected": 2.0, "tolerance": -0.01},
        {
            "expression": "2",
            "expected": 2.0,
            "tolerance": 0.01,
            "extra": True,
        },
        "not an object",
    ],
)
def test_parse_candidate_requires_structured_computational_evidence(
    computational: object,
) -> None:
    with pytest.raises(ValueError):
        shadow_portfolio.parse_candidate(
            _candidate_json(computational=computational),
        )


@pytest.mark.parametrize(
    "marker",
    [
        "gold-17",
        "held_out/17",
        "tier 3/item",
        "gr9677:17",
        "ets/17",
    ],
)
def test_parse_candidate_rejects_private_markers_recursively(marker: str) -> None:
    distractors = list(cast(list[dict[str, str]], _candidate()["distractors"]))
    distractors[0] = {
        **distractors[0],
        "rationale": f"Derived from {marker}.",
    }

    with pytest.raises(ValueError, match="private marker"):
        shadow_portfolio.parse_candidate(
            _candidate_json(distractors=distractors),
        )


def test_parse_candidate_allows_benign_marigold_text() -> None:
    parsed = shadow_portfolio.parse_candidate(
        _candidate_json(stem="A marigold moves in uniform circular motion."),
    )

    assert cast(str, parsed["stem"]).startswith("A marigold")


def _retrieved(*, score: float = 0.9) -> list[dict[str, object]]:
    return [
        {
            "score": score,
            "text": (
                "In uniform circular motion, speed is constant while velocity "
                "changes direction."
            ),
            "source_ref": "OpenStax University Physics, section 6.2",
            "chunk_id": "openstax-university-physics#6.2#1",
            "source_title": "OpenStax University Physics",
        }
    ]


def _display_letter(user: str, answer_text: str) -> str:
    for line in user.splitlines():
        match = re.fullmatch(r"\s*([A-E])\.\s+(.*)", line)
        if match and match.group(2) == answer_text:
            return match.group(1)
    raise AssertionError(f"answer text not presented: {answer_text}")


class FakeBackend:
    """Records exact requests and returns deterministic generated/solved output."""

    def __init__(
        self,
        generator_replies: list[str] | None = None,
        *,
        verifier_answers: dict[str, str] | None = None,
    ) -> None:
        self.generator_replies = list(generator_replies or [json.dumps(_candidate())])
        self.verifier_answers = verifier_answers or {}
        self.requests: list[model_backend.ModelRequest] = []

    def complete(
        self,
        request: model_backend.ModelRequest,
    ) -> model_backend.ModelResult:
        self.requests.append(request)
        if request.role == "generator":
            text = self.generator_replies.pop(0)
        else:
            answer_text = self.verifier_answers.get(
                request.model.family,
                cast(list[str], _candidate()["choices"])[0],
            )
            displayed = _display_letter(request.user, answer_text)
            text = json.dumps(
                {
                    "answer": displayed,
                    "reasoning": f"{request.model.family} independent solve",
                    "confidence": 0.75,
                }
            )
        call = len(self.requests)
        return model_backend.ModelResult(
            request_id=request.request_id,
            model_id=request.model.model_id,
            status="finished",
            text=text,
            agent_id=f"agent-{call}",
            run_id=f"run-{call}",
        )


def _run(
    backend: FakeBackend,
    *,
    origin: str = "sol",
    seed: int = 31,
    retrieved: list[dict[str, object]] | None = None,
    max_schema_corrections: int = 2,
) -> dict[str, object]:
    return shadow_portfolio.run_candidate(
        topic="mechanics/circular-motion",
        retrieved=retrieved or _retrieved(),
        origin=origin,
        roles=_roles(),
        backend=backend,
        seed=seed,
        max_schema_corrections=max_schema_corrections,
    )


@pytest.mark.parametrize("origin", ["sol", "opus", "grok"])
def test_run_candidate_uses_exact_models_and_excludes_origin(origin: str) -> None:
    backend = FakeBackend()

    run = _run(backend, origin=origin)

    judges = shadow_portfolio.verification_families(origin)
    roles = _roles()
    assert run["origin_family"] == origin
    assert cast(dict[str, object], run["generator"])["model_id"] == (
        roles.by_family(origin).model_id
    )
    verifiers = cast(list[dict[str, object]], run["verifiers"])
    assert [verifier["family"] for verifier in verifiers] == list(judges)
    assert origin not in {verifier["family"] for verifier in verifiers}
    assert [request.model.model_id for request in backend.requests] == [
        roles.by_family(origin).model_id,
        *(roles.by_family(family).model_id for family in judges),
    ]
    assert [request.role for request in backend.requests] == [
        "generator",
        "verifier",
        "verifier",
    ]


def test_verifiers_get_independent_permutations_mapped_to_original_labels() -> None:
    backend = FakeBackend()

    run = _run(backend, seed=117)

    verifiers = cast(list[dict[str, object]], run["verifiers"])
    orders = [cast(list[str], verifier["choice_order"]) for verifier in verifiers]
    assert orders[0] != orders[1]
    assert all(sorted(order) == list("ABCDE") for order in orders)
    assert all(order != list("ABCDE") for order in orders)
    assert [
        cast(dict[str, object], verifier["opinion"])["answer"] for verifier in verifiers
    ] == ["A", "A"]
    assert backend.requests[1].user != backend.requests[2].user


def test_schema_correction_retries_representation_without_regeneration() -> None:
    valid = json.dumps(_candidate())
    backend = FakeBackend([f"```json\n{valid}\n```", valid])

    run = _run(backend)

    generator = cast(dict[str, object], run["generator"])
    traces = cast(list[dict[str, object]], generator["traces"])
    assert [trace["phase"] for trace in traces] == [
        "generation",
        "schema_correction",
    ]
    assert [request.role for request in backend.requests[:2]] == [
        "generator",
        "generator",
    ]
    assert backend.requests[0].model.model_id == backend.requests[1].model.model_id
    assert "representation only" in backend.requests[1].system.lower()
    assert len(backend.requests) == 4


def test_schema_correction_rejects_invented_content_then_accepts_exact_content() -> (
    None
):
    represented = _candidate()
    represented["answer"] = represented.pop("key")
    invented = _candidate()
    invented["stem"] = "An invented projectile problem."
    backend = FakeBackend(
        [
            json.dumps(represented),
            json.dumps(invented),
            json.dumps(_candidate()),
        ]
    )

    run = _run(backend)

    generator = cast(dict[str, object], run["generator"])
    traces = cast(list[dict[str, object]], generator["traces"])
    assert len(traces) == 3
    assert "invent" in str(traces[1]["parse_error"]).lower()
    assert cast(dict[str, object], run["candidate"])["stem"] == _candidate()["stem"]


def test_malformed_candidate_stops_after_bounded_corrections() -> None:
    backend = FakeBackend(["not json", "still not json", "also not json"])

    with pytest.raises(shadow_portfolio.CandidateGenerationError) as exc:
        _run(backend)

    assert len(backend.requests) == 3
    assert all(request.role == "generator" for request in backend.requests)
    assert len(exc.value.traces) == 3
    assert len(exc.value.errors) == 3


def test_content_failure_is_not_rewritten_by_schema_correction() -> None:
    private = _candidate()
    private["stem"] = "Copied from held-out/item-17."
    backend = FakeBackend([json.dumps(private), json.dumps(_candidate())])

    with pytest.raises(shadow_portfolio.CandidateGenerationError):
        _run(backend)

    assert len(backend.requests) == 1


def test_cross_model_disagreement_and_deterministic_failures_are_evidence_only() -> (
    None
):
    leaky = _candidate()
    leaky["solution_decomposition"] = [
        {"subgoal": "Reveal", "rubric": "The answer is choice A."}
    ]
    choices = cast(list[str], leaky["choices"])
    backend = FakeBackend(
        [json.dumps(leaky)],
        verifier_answers={
            "opus": choices[1],
            "grok": choices[2],
        },
    )

    run = _run(backend)

    verifiers = cast(list[dict[str, object]], run["verifiers"])
    assert [
        cast(dict[str, object], verifier["opinion"])["answer"] for verifier in verifiers
    ] == ["B", "C"]
    evidence = cast(dict[str, object], run["deterministic_evidence"])
    assert evidence["decomposition_giveaways"]
    assert evidence["provenance"] is not None
    assert len(backend.requests) == 3
    forbidden = {
        "accept",
        "accepted",
        "reject",
        "rejected",
        "escalate",
        "escalated",
        "decision",
        "preference",
        "preference_pair",
        "bundle",
    }
    assert forbidden.isdisjoint(run)
    assert forbidden.isdisjoint(evidence)


def test_unsupported_provenance_is_recorded_without_short_circuiting_solves() -> None:
    backend = FakeBackend()

    run = _run(backend, retrieved=_retrieved(score=0.1))

    evidence = cast(dict[str, object], run["deterministic_evidence"])
    assert evidence["provenance"] is None
    assert len(cast(list[dict[str, object]], run["verifiers"])) == 2
    assert len(backend.requests) == 3


def test_run_candidate_is_deterministically_repeatable() -> None:
    first_backend = FakeBackend()
    second_backend = FakeBackend()

    first = _run(first_backend, seed=2026)
    second = _run(second_backend, seed=2026)

    assert first == second
    assert [request.to_dict() for request in first_backend.requests] == [
        request.to_dict() for request in second_backend.requests
    ]
