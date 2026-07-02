# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""The ``pgrep::Problem`` notetype and sample problems for pgrep.

**Stub — implemented by the L2.1 Study surface.**

The scaffolding seed (``anki.pgrep.seed``) and the ``pgrep_seed`` bridge handler
call :func:`seed_sample_problems` opportunistically (guarded by
``NotImplementedError``) so sample Problems appear once L2.1 lands, without the
scaffolding depending on it. Do not change the signatures — the four surfaces
coordinate through the fixed handler contract.

See ``docs/pgrep/planning/l2-api-contract.md`` §3 (L2.1) for the Problem
notetype fields (``stem``, ``choices``, ``correct``, ``distractor_rationales``,
``solution_decomposition``, ``difficulty``, ``source_ref``, topic on tags). The
stored ``solution_decomposition`` drives the reveal-and-self-compare ladder with
AI off. There is no confidence field.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from anki.collection import Collection
    from anki.models import NotetypeDict


def ensure_problem_notetype(col: Collection) -> NotetypeDict:
    """Return the ``pgrep::Problem`` notetype, creating it if missing.

    Raises:
        NotImplementedError: until the L2.1 Study surface implements it.
    """
    raise NotImplementedError("implemented by L2.1 Study")


def seed_sample_problems(col: Collection) -> int:
    """Idempotently seed a few sample Problems; return how many were created.

    Raises:
        NotImplementedError: until the L2.1 Study surface implements it.
    """
    raise NotImplementedError("implemented by L2.1 Study")
