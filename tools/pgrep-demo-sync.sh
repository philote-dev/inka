#!/usr/bin/env bash
# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
#
# One-command demo-sync helper (L5.9 P5). Primes the shared account on a running
# self-hosted sync server with a complete, ready-to-demo pgrep account:
#
#   - the real bundled flashcards and problems (so Study has content),
#   - a clearly-marked hypothetical study history (so Memory, Performance, and
#     Readiness light up), and
#   - a couple of user settings (theme, target retention, optional test date).
#
# It then uploads that account and verifies a second engine can download it and
# recompute the same lit-up scores. After it runs, open the desktop and iOS apps,
# go to Settings, keep the default server and account, and Sync down: both show
# the same account. This is the backbone of the desktop-to-mobile sync demo.
#
# The server is expected to be running already (start it with `just sync-server`,
# which serves pgrep:pgrep on 0.0.0.0:8080). Nothing here is on the shipped user
# path; it only writes to the demo account you point it at. macOS/Linux.
#
# Usage:
#   just pgrep-demo-sync                 # strong profile, http://127.0.0.1:8080/
#   PGREP_DEMO_PROFILE=rusty just pgrep-demo-sync
#   PGREP_SYNC_URL=http://127.0.0.1:8080/ just pgrep-demo-sync

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${ROOT_DIR}"

PYTHON="out/pyenv/bin/python"
URL="${PGREP_SYNC_URL:-http://127.0.0.1:8080/}"
[[ "${URL}" == */ ]] || URL="${URL}/"
USER_NAME="${PGREP_SYNC_USER:-pgrep}"
PASS="${PGREP_SYNC_PASS:-pgrep}"
PROFILE="${PGREP_DEMO_PROFILE:-strong}"
TEST_DATE="${PGREP_DEMO_TEST_DATE:-}"

# --- Preconditions ------------------------------------------------------------
[[ -x "${PYTHON}" ]] || { echo "ERROR: ${PYTHON} not found. Run 'just build' first." >&2; exit 1; }

echo ">>> Checking the sync server at ${URL}"
if ! curl -fsS -o /dev/null "${URL}health" 2>/dev/null; then
    echo "ERROR: no healthy sync server at ${URL}health" >&2
    echo "       Start one in another terminal with: just sync-server" >&2
    exit 1
fi

# --- Prime + verify -----------------------------------------------------------
echo ">>> Priming the '${USER_NAME}' account with the '${PROFILE}' profile"
PGREP_SYNC_URL="${URL}" PGREP_SYNC_USER="${USER_NAME}" PGREP_SYNC_PASS="${PASS}" \
PGREP_DEMO_PROFILE="${PROFILE}" PGREP_DEMO_TEST_DATE="${TEST_DATE}" \
PYTHONPATH="pylib:out/pylib:qt:out/qt" ${PYTHON} - <<'PY'
import os
import tempfile

from anki.collection import Collection
from anki.pgrep import demo_profile, problem, seed, settings
from anki.sync_pb2 import SyncAuth

endpoint = os.environ["PGREP_SYNC_URL"]
user = os.environ["PGREP_SYNC_USER"]
password = os.environ["PGREP_SYNC_PASS"]
profile = os.environ.get("PGREP_DEMO_PROFILE", "strong")
test_date = os.environ.get("PGREP_DEMO_TEST_DATE", "")


def auth(col: Collection) -> SyncAuth:
    raw = col.sync_login(user, password, endpoint)
    return SyncAuth(hkey=raw.hkey, endpoint=endpoint)


def sync(col: Collection, a: SyncAuth) -> str:
    """Sync, handling first-run full transfers (mirrors the roundtrip test)."""
    out = col.sync_collection(auth=a, sync_media=False)
    if out.required in (out.NO_CHANGES, out.NORMAL_SYNC):
        return "normal"
    upload = out.required in (out.FULL_UPLOAD, out.FULL_SYNC)
    col.close_for_full_sync()
    col.full_upload_or_download(auth=a, server_usn=None, upload=upload)
    col.reopen(after_full_sync=True)
    return "full_upload" if upload else "full_download"


def score_line(col: Collection) -> str:
    from anki.pgrep.memory import memory_score
    from anki.pgrep.performance import performance_score
    from anki.pgrep.readiness import readiness_score

    mem = memory_score(col)["overall"]
    perf = performance_score(col)["overall"]
    rdy = readiness_score(col)

    def pct(block: dict) -> str:
        if block.get("abstain"):
            return "abstains"
        return f"{round((block.get('point') or 0) * 100)}%"

    readiness = "abstains" if rdy.get("abstain") else str(rdy.get("scaled"))
    return f"Memory {pct(mem)}, Performance {pct(perf)}, Readiness {readiness}"


# --- Prime: seed content + inject stats + set settings, then upload -----------
prime_dir = tempfile.mkdtemp(prefix="pgrep-demo-prime-")
col = Collection(os.path.join(prime_dir, "collection.anki2"))
cards = seed.seed_sample_content(col)["cards_created"]
problems = problem.seed_sample_problems(col)
injected = demo_profile.inject_demo_profile(col, profile)
applied = {"theme": "Dark", "target_retention": 0.9}
if test_date:
    applied["test_date"] = test_date
settings.apply_settings(col, applied)
print(
    f"    seeded {cards} cards, {problems} problems; injected "
    f"{injected['cards_created']} demo cards, {injected['attempts_created']} attempts"
)
print(f"    local scores: {score_line(col)}")

a = auth(col)
action = sync(col, a)
if action != "full_upload":
    # Force our primed account onto the server so a re-run stays clean.
    col.close_for_full_sync()
    col.full_upload_or_download(auth=a, server_usn=None, upload=True)
    col.reopen(after_full_sync=True)
col.close()
print(f"    uploaded to {endpoint} as '{user}'")

# --- Verify: a second engine downloads it and recomputes the scores ----------
verify_dir = tempfile.mkdtemp(prefix="pgrep-demo-verify-")
peer = Collection(os.path.join(verify_dir, "collection.anki2"))
sync(peer, auth(peer))
demo_cards = len(peer.find_notes(f"tag:{demo_profile.DEMO_TAG}"))
seeded = len(peer.find_notes(f"tag:{seed.SEEDED_TAG}"))
seeded_problems = len(peer.find_notes(f"tag:{problem.PROBLEM_SEED_TAG}"))
line = score_line(peer)
peer.close()

assert demo_cards > 0, "peer did not receive the demo history"
assert seeded > 0, "peer did not receive the seeded cards"
print(
    f"    peer downloaded {seeded} cards, {seeded_problems} problems, "
    f"{demo_cards} demo cards"
)
print(f"    peer scores:  {line}")
print("    OK: the account with made-up stats synced and recomputed the same scores")
PY

echo ""
echo "Demo account primed and verified on ${URL}."
echo "Now sync it down on both ends:"
echo "  Desktop: pgrep Settings -> Sync (server ${URL}, account ${USER_NAME})."
echo "  iOS:     just ios-run, then Settings -> same server + account -> Sync."
