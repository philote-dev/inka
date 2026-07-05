# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""The pinned LLM client for generation (L4.0f).

One thin wrapper over the OpenAI client so every call is reproducible and
recorded: an exact dated model snapshot (never a floating alias), a low
temperature, a seed when the model supports it, and JSON-only responses. The
generator uses the strongest available snapshot; the judge (elsewhere) uses a
different one so it never grades its own output.

``openai`` is imported lazily, so an AI-off app never loads it and importing this
module stays cheap. Snapshot discovery is a helper for pinning at gate time; the
resolved IDs go straight into the run manifest.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

# Ranking hints for "strongest" chat snapshot, high to low. Matched as substrings
# against the account's available model ids; the newest matching family wins, and
# an explicit dated snapshot always beats a floating alias.
_FAMILY_RANK = ("gpt-5", "gpt-4.1", "gpt-4o", "o4", "o3", "gpt-4")
_SNAPSHOT_RE = re.compile(r"-\d{4}-\d{2}-\d{2}$")


@dataclass
class LLMResult:
    text: str
    model: str
    raw: dict = field(default_factory=dict)


class LLMClient:
    """A pinned OpenAI chat client that returns JSON objects."""

    def __init__(self, model: str, *, temperature: float = 0.0, seed: int | None = 7):
        from openai import OpenAI  # type: ignore[import-not-found]

        if _is_floating_alias(model):
            raise ValueError(
                f"refusing a floating alias '{model}'; pin an exact dated snapshot"
            )
        self.model = model
        self.temperature = temperature
        self.seed = seed
        self._client = OpenAI()

    def complete_json(self, system: str, user: str) -> dict:
        """One JSON-object completion, parsed.

        Reasoning and gpt-5 snapshots can reject a non-default ``temperature`` or
        ``seed``; on that error the call retries with the offending option
        dropped, so the strongest snapshot still works. Transient errors retry
        with a short backoff.
        """
        import json
        import time

        base: dict = {
            "model": self.model,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        # Try richest options first, then progressively drop unsupported ones.
        option_sets: list[dict[str, float | int | None]] = [
            {"temperature": self.temperature, "seed": self.seed},
            {"temperature": self.temperature},
            {"seed": self.seed},
            {},
        ]
        last_exc: Exception | None = None
        for options in option_sets:
            kwargs = dict(base)
            kwargs.update({k: v for k, v in options.items() if v is not None})
            for attempt in range(3):
                try:
                    resp = self._client.chat.completions.create(**kwargs)
                    return json.loads(resp.choices[0].message.content)
                except Exception as exc:  # noqa: BLE001
                    name = type(exc).__name__
                    if name in ("BadRequestError", "UnprocessableEntityError"):
                        last_exc = exc
                        break  # option unsupported; try the next option set
                    if name in (
                        "RateLimitError",
                        "APITimeoutError",
                        "APIConnectionError",
                        "InternalServerError",
                    ):
                        last_exc = exc
                        time.sleep(2 * (attempt + 1))
                        continue
                    raise
        assert last_exc is not None
        raise last_exc


def _is_floating_alias(model: str) -> bool:
    """A model id with no dated snapshot suffix is a floating alias."""
    return _SNAPSHOT_RE.search(model) is None


def list_models() -> list[str]:
    """Model ids available on the account (needs the API key)."""
    from openai import OpenAI  # type: ignore[import-not-found]

    client = OpenAI()
    return sorted(m.id for m in client.models.list().data)


def _rank(model_id: str) -> tuple:
    for i, fam in enumerate(_FAMILY_RANK):
        if fam in model_id:
            dated = 1 if _SNAPSHOT_RE.search(model_id) else 0
            return (-i, dated, model_id)
    return (-len(_FAMILY_RANK), 0, model_id)


def pick_generator_snapshot(available: list[str] | None = None) -> str:
    """The strongest dated chat snapshot on the account, for the generator."""
    models = available if available is not None else list_models()
    dated = [
        m
        for m in models
        if _SNAPSHOT_RE.search(m) and any(f in m for f in _FAMILY_RANK)
    ]
    pool = dated or [m for m in models if any(f in m for f in _FAMILY_RANK)]
    if not pool:
        raise RuntimeError("no suitable chat model found on the account")
    return sorted(pool, key=_rank, reverse=True)[0]


def pick_judge_snapshot(exclude: str, available: list[str] | None = None) -> str:
    """A dated chat snapshot different from ``exclude``, for the judge."""
    models = available if available is not None else list_models()
    pool = [
        m
        for m in models
        if m != exclude and _SNAPSHOT_RE.search(m) and any(f in m for f in _FAMILY_RANK)
    ]
    if not pool:
        # Fall back to any model that is not the generator.
        pool = [m for m in models if m != exclude]
    if not pool:
        raise RuntimeError("no distinct judge model found on the account")
    return sorted(pool, key=_rank, reverse=True)[0]


def has_api_key() -> bool:
    return bool(os.environ.get("OPENAI_API_KEY"))
