# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""pgrep AI core (L4), the shared, Collection-free generation and RAG layer.

This subpackage is the one place the AI logic lives, imported two ways:

- the running app imports it as ``anki.pgrep.ai.*`` (AI on only, lazy loaded, so
  an AI-off session never touches these modules or their heavy deps);
- the offline eval harness in ``content/tools/`` imports it as ``pgrep.ai.*``
  (put ``pylib/anki`` on the path, so no compiled backend is needed).

To keep both paths working, modules here use relative imports for their siblings
and never import ``anki.collection`` at module load. Heavy optional deps
(``fastembed``, ``sqlite_vec``, ``openai``, ``sympy``, ``sentence_transformers``)
are imported inside functions, never at module top level.

Modules:
  - ``retrieval``: local ONNX bge query embedding plus sqlite-vec search over the
    corpus index, with a parity gate against the sentence-transformers model the
    index was built with.
"""
