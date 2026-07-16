# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""The AI on/off seam for pgrep (L4).

AI is an upgrade, never a dependency. This module is the single place the app
asks "is AI on?", stored in the collection config. The pure default is off, so a
bare collection (and the test harness) scores and studies with no AI and no AI
dependencies. The app itself applies a first-run default of AI-*on* via
:func:`ensure_first_run_defaults`, so onboarding makes calibration the paramount
step (card-sets plan §4); the unadvertised Settings escape hatch turns it back
off. The generation, problem, and tutor paths all gate on :func:`ai_enabled` and
lazily import the heavy AI modules only when it returns true.

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
# Marks that a collection has been through its first pgrep run, so the AI-on
# first-run default is applied exactly once (see ensure_first_run_defaults).
FIRST_RUN_KEY = "pgrepFirstRunDone"


def ai_enabled(col: Collection) -> bool:
    return bool(col.get_config(AI_ENABLED_KEY, False))


def set_ai_enabled(col: Collection, enabled: bool) -> None:
    col.set_config(AI_ENABLED_KEY, bool(enabled))


def ensure_first_run_defaults(col: Collection) -> None:
    """Apply the first-run defaults for a collection, once. AI defaults on.

    Idempotent (guarded by :data:`FIRST_RUN_KEY`). AI is turned on only if it was
    never explicitly configured, so a learner who has chosen AI off is never
    overridden. This is the app's onboarding default (calibration-paramount); the
    pure :func:`ai_enabled` default stays off so bare collections and tests need
    no AI. Called from the ``pgrep_ai_status`` bridge handler.
    """
    if col.get_config(FIRST_RUN_KEY, False):
        return
    col.set_config(FIRST_RUN_KEY, True)
    if col.get_config(AI_ENABLED_KEY, None) is None:
        col.set_config(AI_ENABLED_KEY, True)


def ai_model(col: Collection) -> str | None:
    return col.get_config(AI_MODEL_KEY, None)


def set_ai_model(col: Collection, model: str | None) -> None:
    col.set_config(AI_MODEL_KEY, model)


def has_api_key() -> bool:
    """True when the TrueFoundry gateway (or OpenAI-compatible) key is loaded."""
    if os.environ.get("OPENAI_API_KEY"):
        return True
    from anki.pgrep.ai import llm

    return llm.has_api_key()


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
