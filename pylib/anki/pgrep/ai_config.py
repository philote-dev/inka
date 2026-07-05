# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""The AI on/off seam for pgrep (L4).

AI is an upgrade, never a dependency. This module is the single place the app
asks "is AI on?", stored in the collection config and defaulting to off, so a
fresh collection scores and studies with no AI and no AI dependencies. The
generation, problem, and tutor paths all gate on :func:`ai_enabled` and lazily
import the heavy AI modules only when it returns true.

The model snapshot is resolved once and cached in config, so a graded or live run
records exactly which dated snapshot produced it. The API key is read from the
environment (never synced, never committed), matching ``content-and-dependencies.md``.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from anki.collection import Collection

AI_ENABLED_KEY = "pgrepAiEnabled"
AI_MODEL_KEY = "pgrepAiModel"


def ai_enabled(col: Collection) -> bool:
    return bool(col.get_config(AI_ENABLED_KEY, False))


def set_ai_enabled(col: Collection, enabled: bool) -> None:
    col.set_config(AI_ENABLED_KEY, bool(enabled))


def ai_model(col: Collection) -> str | None:
    return col.get_config(AI_MODEL_KEY, None)


def set_ai_model(col: Collection, model: str | None) -> None:
    col.set_config(AI_MODEL_KEY, model)


def has_api_key() -> bool:
    return bool(os.environ.get("OPENAI_API_KEY"))


def ai_status(col: Collection) -> dict:
    """A small status blob for the Settings surface and callers to gate on."""
    return {
        "enabled": ai_enabled(col),
        "model": ai_model(col),
        "has_key": has_api_key(),
        "ready": ai_enabled(col) and has_api_key(),
    }


def resolve_model(col: Collection) -> str:
    """The pinned dated snapshot to use, resolved once and cached in config.

    Order: the config value, then ``PGREP_AI_MODEL`` in the environment, then the
    strongest snapshot discovered on the account. The result is stored so a run
    manifest can record exactly which snapshot produced it.
    """
    configured = ai_model(col)
    if configured:
        return configured
    env_model = os.environ.get("PGREP_AI_MODEL")
    if env_model:
        set_ai_model(col, env_model)
        return env_model
    from anki.pgrep.ai import llm

    picked = llm.pick_generator_snapshot()
    set_ai_model(col, picked)
    return picked
