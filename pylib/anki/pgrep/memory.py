# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Memory (the honest per-topic readiness signal) for pgrep.

Memory answers "is the raw material in your head" as ``P(recall now)`` — the
expected fraction of your reviewed cards you would recall right now,
blueprint-weighted. It is pure math over FSRS state and topic tags: no AI, no
attempt log, no schedule mutation (``l2-api-contract.md`` §0).

Math (``scoring-and-readiness.md`` §1):

- **Per card** the retrievability ``R in [0, 1]`` is the engine's own FSRS
  retrievability (the same primitive the L1 selector uses, so Memory and the
  selector never disagree). We read it in one SQL pass via the engine UDF
  ``extract_fsrs_retrievability(card.data, card.due, card.ivl, days_elapsed,
  next_day_at, now)`` (``rslib/src/storage/sqlite.rs``), which returns ``NULL``
  for a card with no FSRS memory state — i.e. a new / unreviewed card, which is
  excluded. R is never re-derived from a formula here.
- **Per topic (category):** ``point = mean(R)`` over that category's reviewed
  cards. Treating each card as ``Bernoulli(R_i)``, the fraction recallable is a
  Poisson-binomial with mean ``mean(R)`` and standard deviation
  ``sqrt(sum R_i (1 - R_i)) / n``. The 80% likely range is the normal-approx
  central interval ``point +/- 1.2816 * sd`` clamped to ``[0, 1]``.
- **Abstain:** a category with fewer than ``k_mem`` (default 5) reviewed cards
  abstains ("Not enough cards yet") instead of showing a number.
- **Overall:** the blueprint-weighted mean of the scored (non-abstaining)
  categories, normalized by their blueprint weight so it reads honestly as "of
  what is scored." The range combines the per-topic variances with the same
  (normalized) weights, treating topics as independent.

The scaffolding bridge handler ``pgrep_memory_score`` in ``qt/aqt/pgrep.py``
calls :func:`memory_score`; the signature is fixed by the L2 API contract (§3).
"""

from __future__ import annotations

import math
import time
from typing import TYPE_CHECKING, Any

from anki.pgrep.blueprint import BLUEPRINT_PERCENT, CATEGORY_SLUGS
from anki.pgrep.tags import category_for

if TYPE_CHECKING:
    from anki.collection import Collection

# Default abstain threshold: a topic needs at least this many reviewed cards to
# show a Memory number (tunable; ``scoring-and-readiness.md`` §5).
K_MEM_DEFAULT = 5

# z for the 80% two-sided central interval (the 10th/90th normal percentiles).
_Z_80 = 1.2816

_ABSTAIN_REASON = "Not enough cards yet"

# One SQL pass: each in-scope card's note tags plus the engine's FSRS
# retrievability (NULL when the card has no memory state, i.e. unreviewed).
_R_SELECT = (
    "SELECT n.tags, "
    "extract_fsrs_retrievability(c.data, c.due, c.ivl, ?, ?, ?) "
    "FROM cards c JOIN notes n ON c.nid = n.id"
)


def _clamp01(value: float) -> float:
    return 0.0 if value < 0.0 else 1.0 if value > 1.0 else value


def memory_score(
    col: Collection, deck_id: int | None = None, k_mem: int = K_MEM_DEFAULT
) -> dict:
    """Return the Memory score for the collection (or one deck).

    ``deck_id`` scopes the score to a single deck (and its children) when given;
    otherwise the whole collection is scored. ``k_mem`` is the per-topic abstain
    threshold. The result is JSON-serializable and matches the
    ``pgrepMemoryScore`` response in the L2 API contract (§3, L2.2): ``overall``
    plus a per-category ``by_topic`` breakdown, each with a point estimate, an
    80% ``low``/``high`` range, an ``n_cards`` count, and an ``abstain`` flag.
    """
    # Timing for the retrievability UDF (only used for cards without a stored
    # last-review time; seeded/reviewed cards carry one, so ``now`` dominates).
    now = int(time.time())
    params: list[Any] = [col.sched.today, col.sched.day_cutoff, now]

    sql = _R_SELECT
    if deck_id is not None:
        from anki.decks import DeckId

        deck_ids = col.decks.deck_and_child_ids(DeckId(deck_id))
        placeholders = ",".join("?" for _ in deck_ids)
        sql = f"{_R_SELECT} WHERE c.did IN ({placeholders})"
        params.extend(int(did) for did in deck_ids)

    # Accumulate mean(R) and the Poisson-binomial variance term per category.
    counts: dict[str, int] = {}
    sum_r: dict[str, float] = {}
    sum_var: dict[str, float] = {}
    for tags, retrievability in col.db.all(sql, *params):
        if retrievability is None:
            continue  # new / unreviewed card: excluded from Memory
        category = category_for(tags)
        if category not in BLUEPRINT_PERCENT:
            continue  # untagged / unknown / off-blueprint: excluded
        r = _clamp01(float(retrievability))
        counts[category] = counts.get(category, 0) + 1
        sum_r[category] = sum_r.get(category, 0.0) + r
        sum_var[category] = sum_var.get(category, 0.0) + r * (1.0 - r)

    by_topic: list[dict[str, Any]] = []
    # (blueprint weight, point, variance-of-the-mean) for each scored category.
    scored: list[tuple[float, float, float]] = []
    total_reviewed = 0

    for category in CATEGORY_SLUGS:
        blueprint = BLUEPRINT_PERCENT[category]
        n = counts.get(category, 0)
        total_reviewed += n
        if n < k_mem:
            by_topic.append(
                {
                    "category": category,
                    "blueprint": blueprint,
                    "point": None,
                    "low": None,
                    "high": None,
                    "n_cards": n,
                    "abstain": True,
                    "reason": _ABSTAIN_REASON,
                }
            )
            continue
        point = sum_r[category] / n
        sd = math.sqrt(sum_var[category]) / n
        by_topic.append(
            {
                "category": category,
                "blueprint": blueprint,
                "point": point,
                "low": _clamp01(point - _Z_80 * sd),
                "high": _clamp01(point + _Z_80 * sd),
                "n_cards": n,
                "abstain": False,
                "reason": None,
            }
        )
        scored.append((blueprint, point, sum_var[category] / (n * n)))

    return {
        "overall": _overall(scored),
        "by_topic": by_topic,
        "k_mem": k_mem,
        "last_updated": now if total_reviewed > 0 else None,
    }


def _overall(scored: list[tuple[float, float, float]]) -> dict[str, Any]:
    """Blueprint-weighted overall Memory over the scored categories.

    ``scored`` is ``(blueprint_weight, point, variance_of_mean)`` per scored
    category. The point is the weight-normalized mean; the range propagates the
    per-topic variances with the same normalized weights (topics independent).
    Abstains when nothing is scored.
    """
    if not scored:
        return {
            "point": None,
            "low": None,
            "high": None,
            "abstain": True,
            "reason": _ABSTAIN_REASON,
        }
    total_weight = sum(weight for weight, _, _ in scored)
    point = sum(weight * pt for weight, pt, _ in scored) / total_weight
    variance = sum(
        (weight / total_weight) ** 2 * var for weight, _, var in scored
    )
    sd = math.sqrt(variance)
    return {
        "point": point,
        "low": _clamp01(point - _Z_80 * sd),
        "high": _clamp01(point + _Z_80 * sd),
        "abstain": False,
        "reason": None,
    }
