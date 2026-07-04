# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
#
# Launch a self-hosted Anki sync server for pgrep, reusing Anki's own sync stack
# (rslib/src/sync/**, unmodified). This is the demo/dev host that the desktop and
# the iOS app sync against; point clients at it with a custom sync URL.
#
# It mirrors tools/run.py's sys.path setup so the built `anki` package (pure
# Python in pylib/ plus generated + compiled bits in out/pylib/) is importable,
# then calls anki.syncserver.run_sync_server(), which drives the same
# SimpleServer the packaged `anki --syncserver` and `python -m anki.syncserver`
# use.
#
# Configure via env (read by the Rust SimpleServer):
#   SYNC_USER1=user:pass   (required; add SYNC_USER2=... for more accounts)
#   SYNC_HOST=0.0.0.0      (default 0.0.0.0)
#   SYNC_PORT=8080         (default 8080)
#   SYNC_BASE=~/.syncserver (default; per-user collections live under it)
#
# Usage: SYNC_USER1=pgrep:pgrep just sync-server
#    or: SYNC_USER1=pgrep:pgrep out/pyenv/bin/python tools/sync-server.py

import sys

sys.path.extend(["pylib", "qt", "out/pylib", "out/qt"])

from anki.syncserver import run_sync_server

run_sync_server()
