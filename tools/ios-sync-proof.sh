#!/usr/bin/env bash
# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
#
# L3 exit-gate proof for the real iOS FFI sync path (phone -> server -> desktop):
#   1. build the xcframework + regenerate the Xcode project,
#   2. start a throwaway self-hosted sync server on a free port,
#   3. hand the server details to the iOS test via /tmp/pgrep-sync-test.json,
#   4. run the on-Simulator XCTest, whose SyncSmokeTests reviews a card and
#      uploads the collection over the shared C ABI,
#   5. confirm a *desktop* engine can download that review from the same server.
#
# The engine sync stack (rslib/src/sync/**) is reused unmodified. macOS-only.
#
# Usage: tools/ios-sync-proof.sh   (or: just ios-sync-proof)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${ROOT_DIR}"

SCHEME="PgrepStudy"
PROJECT="mobile/ios/PgrepStudy.xcodeproj"
PYTHON="out/pyenv/bin/python"
CONFIG="/tmp/pgrep-sync-test.json"

# --- 1. Build the xcframework + project ---------------------------------------
echo ">>> Building iOS xcframework"
tools/build-xcframework.sh
echo ">>> Generating Xcode project"
( cd mobile/ios && xcodegen generate )

# --- Detect a Simulator -------------------------------------------------------
SIM="${IOS_SIM_NAME:-}"
if [[ -z "${SIM}" ]]; then
    SIM="$(xcrun simctl list devices available | grep -i 'iphone' | head -n1 | sed -E 's/^[[:space:]]*//; s/ \(.*$//')"
fi
[[ -n "${SIM}" ]] || { echo "ERROR: no available iOS Simulator" >&2; exit 1; }
echo ">>> Using iOS Simulator: ${SIM}"

# --- 2. Start a throwaway sync server on a free port --------------------------
PORT="$(${PYTHON} -c 'import socket;s=socket.socket();s.bind(("127.0.0.1",0));print(s.getsockname()[1]);s.close()')"
BASE="$(mktemp -d)"
URL="http://127.0.0.1:${PORT}/"
echo ">>> Starting sync server on ${URL} (base ${BASE})"
SYNC_USER1="pgrep:pgrep" SYNC_HOST="127.0.0.1" SYNC_PORT="${PORT}" SYNC_BASE="${BASE}" \
    ${PYTHON} tools/sync-server.py >/tmp/pgrep-sync-server.log 2>&1 &
SERVER_PID=$!

cleanup() {
    kill "${SERVER_PID}" 2>/dev/null || true
    rm -f "${CONFIG}"
    rm -rf "${BASE}"
}
trap cleanup EXIT

# Wait for health.
for _ in $(seq 1 60); do
    if curl -fsS -o /dev/null "${URL}health" 2>/dev/null; then break; fi
    sleep 0.5
done
curl -fsS -o /dev/null "${URL}health" || { echo "ERROR: sync server not healthy" >&2; exit 1; }

# --- 3. Hand the server details to the iOS test -------------------------------
printf '{"url":"%s","user":"pgrep","pass":"pgrep"}\n' "${URL}" > "${CONFIG}"

# --- 4. Run the on-Simulator test (EngineSmokeTests + SyncSmokeTests) ---------
echo ">>> Running iOS tests (includes the sync upload over FFI)"
DEST="platform=iOS Simulator,name=${SIM}"
if command -v xcpretty >/dev/null 2>&1; then
    xcodebuild -project "${PROJECT}" -scheme "${SCHEME}" -destination "${DEST}" test | xcpretty
else
    xcodebuild -project "${PROJECT}" -scheme "${SCHEME}" -destination "${DEST}" test
fi

# --- 5. Desktop engine downloads the iOS review from the same server ----------
echo ">>> Verifying a desktop engine receives the iOS review"
PGREP_SYNC_URL="${URL}" PYTHONPATH="pylib:out/pylib:qt:out/qt" ${PYTHON} - <<'PY'
import os, sys, tempfile
from anki.collection import Collection
from anki.sync_pb2 import SyncAuth

endpoint = os.environ["PGREP_SYNC_URL"]
path = os.path.join(tempfile.mkdtemp(), "collection.anki2")
col = Collection(path)
raw = col.sync_login("pgrep", "pgrep", endpoint)
auth = SyncAuth(hkey=raw.hkey, endpoint=endpoint)
out = col.sync_collection(auth=auth, sync_media=False)
if out.required != out.NO_CHANGES:
    col.close_for_full_sync()
    col.full_upload_or_download(auth=auth, server_usn=None, upload=False)
    col.reopen(after_full_sync=True)
revlog = col.db.scalar("select count(*) from revlog")
cards = col.db.scalar("select count(*) from cards")
col.close()
print(f"    desktop after download: cards={cards} revlog={revlog}")
assert cards >= 1, "desktop did not receive the iOS cards"
assert revlog >= 1, "desktop did not receive the iOS review"
print("    OK: phone review -> server -> desktop")
PY

echo ""
echo "iOS sync proof passed: the iOS FFI sync path uploaded a review that a desktop engine then downloaded."
