# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Two-level topic-tag parsing helpers.

Topic tags are hierarchical Anki tags (Anki uses ``::`` for hierarchy)::

    topic::<category>                 # category-level (required)
    topic::<category>::<subtopic>     # optional finer level

Parsing rules (identical semantics to the Rust selector; see
``docs/pgrep/planning/l1-coordination-schema.md`` §1):

1. Topic tags are all tags whose ``topic::`` prefix matches (case-insensitive).
2. Category is the 2nd ``::`` segment of a topic tag.
3. Finest topic is the full topic-tag string.
4. Blueprint % is keyed by category (subtopics inherit their category's %).
5. Untagged / unrecognized category -> ``unknown`` / ``0.0`` (never dropped).
6. If multiple ``topic::`` tags are present, the **first** one wins.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Union

from anki.pgrep.blueprint import UNKNOWN_CATEGORY, blueprint_percent

# The (case-insensitive) prefix that marks a topic tag.
TOPIC_PREFIX = "topic::"

# Tags may be supplied either as Anki's space-separated string form or as a list.
TagsInput = Union[str, Iterable[str], None]


def _as_tag_list(tags: TagsInput) -> list[str]:
    """Normalize ``str`` / iterable / ``None`` tag input into a list of tags."""
    if tags is None:
        return []
    if isinstance(tags, str):
        return tags.split()
    return [t for t in tags if t]


def is_topic_tag(tag: str) -> bool:
    """Whether ``tag`` is a ``topic::…`` tag (case-insensitive prefix)."""
    return tag.lower().startswith(TOPIC_PREFIX)


def topic_tags(tags: TagsInput) -> list[str]:
    """All ``topic::…`` tags, in their original order."""
    return [t for t in _as_tag_list(tags) if is_topic_tag(t)]


def category_of(topic_tag: str | None) -> str:
    """Category slug (2nd ``::`` segment) of a single topic tag.

    Returns ``unknown`` for ``None``, non-topic tags, or a topic tag with no
    (non-empty) category segment. Result is lowercased so it matches the
    blueprint table.
    """
    if not topic_tag:
        return UNKNOWN_CATEGORY
    segments = topic_tag.split("::")
    if len(segments) >= 2 and segments[0].lower() == "topic" and segments[1].strip():
        return segments[1].strip().lower()
    return UNKNOWN_CATEGORY


def finest_topic(tags: TagsInput) -> str | None:
    """The finest tagged topic: the full string of the first ``topic::`` tag.

    ``None`` if the item carries no topic tag.
    """
    found = topic_tags(tags)
    return found[0] if found else None


def category_for(tags: TagsInput) -> str:
    """Category slug for an item's tags (first topic tag wins).

    ``unknown`` if the item is untagged or has an unrecognized category.
    """
    return category_of(finest_topic(tags))


def blueprint_percent_for(tags: TagsInput) -> float:
    """Blueprint weight (fraction of 1.0) for an item's tags.

    Subtopics inherit their category's %. Untagged / unknown -> ``0.0``.
    """
    return blueprint_percent(category_for(tags))
