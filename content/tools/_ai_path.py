"""Locate the shared AI core for the offline harness.

The harness imports the core the offline way, as ``pgrep.ai.*`` with
``pylib/anki`` on the path (no compiled Anki backend needed). The ``content/``
tree is a symlink into the worktree, so deriving the repo root from ``__file__``
is unreliable (it can resolve to the main checkout, which has no ``pgrep/ai``).
This searches candidate roots, current working directory first, for the one that
actually holds ``pylib/anki/pgrep/ai``, and puts it on ``sys.path``.
"""

from __future__ import annotations

import os
import sys


def add_ai_core() -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    candidates = [os.path.join(os.getcwd(), "pylib", "anki")]
    for base in (here, os.path.realpath(here)):
        repo = os.path.dirname(os.path.dirname(base))  # tools -> content -> repo
        candidates.append(os.path.join(repo, "pylib", "anki"))
    seen = set()
    for cand in candidates:
        if cand in seen:
            continue
        seen.add(cand)
        if os.path.isdir(os.path.join(cand, "pgrep", "ai")):
            # Append, never prepend: pylib/anki holds modules named like stdlib
            # ones (types.py, stats.py, ...). Prepending would shadow the stdlib
            # and crash unrelated imports. Appended, only the unique ``pgrep``
            # name resolves from here; stdlib and site-packages win first.
            if cand not in sys.path:
                sys.path.append(cand)
            return cand
    raise ImportError(
        "could not locate pylib/anki/pgrep/ai; run the harness from the l4-ai worktree root"
    )
