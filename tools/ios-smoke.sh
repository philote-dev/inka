#!/usr/bin/env bash
# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
#
# End-to-end iOS smoke: build the shared engine's iOS xcframework, (re)generate
# the XcodeGen project, and run the on-Simulator engine XCTest. This proves the
# native iOS app links and drives the same shared engine that desktop uses
# (see rslib/ffi) on a real iOS Simulator.
#
# Steps:
#   1. tools/build-xcframework.sh     -> out/ios/AnkiFfi.xcframework
#   2. xcodegen generate (mobile/ios) -> mobile/ios/PgrepStudy.xcodeproj (gitignored)
#   3. xcodebuild ... -scheme PgrepStudy test on a detected iOS Simulator
#
# The Simulator is auto-detected (first available "iPhone"); override with:
#   IOS_SIM_NAME="iPhone 15 Pro" tools/ios-smoke.sh
#
# Prerequisites:
#   rustup target add aarch64-apple-ios-sim aarch64-apple-ios
#   brew install xcodegen swift-protobuf
#   Xcode + command line tools (xcodebuild, xcrun simctl).
#
# Usage: tools/ios-smoke.sh   (or: just ios-smoke)

set -euo pipefail

# Resolve repo root (this script lives in <root>/tools).
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${ROOT_DIR}"

SCHEME="PgrepStudy"
PROJECT="mobile/ios/PgrepStudy.xcodeproj"

# --- 1. Build the iOS xcframework ---------------------------------------------
echo ">>> Building iOS xcframework (tools/build-xcframework.sh)"
tools/build-xcframework.sh

# --- 2. Regenerate the Xcode project ------------------------------------------
if ! command -v xcodegen >/dev/null 2>&1; then
    echo "ERROR: xcodegen not found. Install with: brew install xcodegen" >&2
    exit 1
fi
echo ">>> Generating Xcode project (xcodegen generate in mobile/ios)"
( cd mobile/ios && xcodegen generate )

if [[ ! -d "${PROJECT}" ]]; then
    echo "ERROR: expected generated project not found at ${PROJECT}" >&2
    exit 1
fi

# --- 3. Detect an available iOS Simulator -------------------------------------
# Override with IOS_SIM_NAME; otherwise pick the first available "iPhone" and
# strip the trailing " (UUID) (state)" columns to leave just the device name.
SIM="${IOS_SIM_NAME:-}"
if [[ -z "${SIM}" ]]; then
    SIM="$(xcrun simctl list devices available \
        | grep -i 'iphone' \
        | head -n1 \
        | sed -E 's/^[[:space:]]*//; s/ \(.*$//')"
fi
if [[ -z "${SIM}" ]]; then
    echo "ERROR: no available iOS Simulator found." >&2
    echo "       Create one in Xcode, or set IOS_SIM_NAME to a device from:" >&2
    echo "         xcrun simctl list devices available" >&2
    exit 1
fi
echo ">>> Using iOS Simulator: ${SIM}"

# --- 4. Run the on-Simulator engine XCTest ------------------------------------
echo ">>> Running XCTest (scheme ${SCHEME}) on '${SIM}'"
DEST="platform=iOS Simulator,name=${SIM}"
# Pipe through xcpretty when available for readable output; pipefail preserves
# xcodebuild's real exit status either way.
if command -v xcpretty >/dev/null 2>&1; then
    xcodebuild -project "${PROJECT}" -scheme "${SCHEME}" -destination "${DEST}" test | xcpretty
else
    xcodebuild -project "${PROJECT}" -scheme "${SCHEME}" -destination "${DEST}" test
fi

echo ""
echo "iOS smoke passed: xcframework built, project generated, and XCTest (scheme ${SCHEME}) green on '${SIM}'."
