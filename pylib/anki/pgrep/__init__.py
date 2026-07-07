# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""pgrep (Physics-GRE prep) data-model helpers.

This package holds the pure-Python data model for pgrep:

- ``blueprint``: PGRE topic blueprint weights (per-category %).
- ``tags``: two-level ``topic::category[::subtopic]`` tag parsing helpers.
- ``attempt_log``: the attempt log as immutable notes ("notes-as-log") plus the
  single read-model seam used by all attempt analytics.

See ``docs_pgrep/reference/tag-and-attempt-log-schema.md`` for the shared contract.
"""
