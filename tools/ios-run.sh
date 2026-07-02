#!/usr/bin/env bash
# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
#
# Build + launch the pgrep iOS app (PgrepStudy) in the iOS Simulator so the
# review UI is VISIBLE on screen. Unlike tools/ios-smoke.sh (a headless XCTest),
# this builds the app target, boots a Simulator, installs the .app, launches it,
# and opens Simulator.app so you can watch/record the review loop driven by the
# shared Rust engine (rslib/ffi).
#
# Steps:
#   1. tools/build-xcframework.sh      -> out/ios/AnkiFfi.xcframework
#   2. xcodegen generate (mobile/ios)  -> mobile/ios/PgrepStudy.xcodeproj
#   3. detect a Simulator (name + UDID)
#   4. xcodebuild ... build (scheme PgrepStudy) -> out/ios/DerivedData/...app
#   5. boot the Simulator + open Simulator.app
#   6. install + launch net.ankiweb.pgrep.PgrepStudy
#
# Override the device with:  IOS_SIM_NAME="iPhone 16 Pro" tools/ios-run.sh
# Record the run with:       xcrun simctl io booted recordVideo pgrep-ios.mp4
#
# Prerequisites (same as ios-smoke):
#   rustup target add aarch64-apple-ios-sim aarch64-apple-ios
#   brew install xcodegen swift-protobuf
#   Xcode + command line tools (xcodebuild, xcrun simctl).
#
# Usage: tools/ios-run.sh   (or: just ios-run)

set -euo pipefail

# Resolve repo root (this script lives in <root>/tools).
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${ROOT_DIR}"

SCHEME="PgrepStudy"
PROJECT="mobile/ios/PgrepStudy.xcodeproj"
BUNDLE_ID="net.ankiweb.pgrep.PgrepStudy"
DERIVED="${ROOT_DIR}/out/ios/DerivedData"

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

# --- 3. Resolve a Simulator (name + UDID) from a single line ------------------
# Override with IOS_SIM_NAME; otherwise pick the first available "iPhone".
if [[ -n "${IOS_SIM_NAME:-}" ]]; then
    SIM_LINE="$(xcrun simctl list devices available | grep -i "${IOS_SIM_NAME} (" | head -n1 || true)"
else
    SIM_LINE="$(xcrun simctl list devices available | grep -i 'iphone' | head -n1 || true)"
fi
if [[ -z "${SIM_LINE}" ]]; then
    echo "ERROR: no available iOS Simulator found." >&2
    echo "       Create one in Xcode, or set IOS_SIM_NAME to a device from:" >&2
    echo "         xcrun simctl list devices available" >&2
    exit 1
fi
# Line looks like: "    iPhone 17 Pro (UDID) (Shutdown)".
SIM_NAME="$(echo "${SIM_LINE}" | sed -E 's/^[[:space:]]*//; s/ \(.*$//')"
SIM_UDID="$(echo "${SIM_LINE}" | sed -E 's/^[^(]*\(([0-9A-Fa-f-]{36})\).*/\1/')"
echo ">>> Using iOS Simulator: ${SIM_NAME} (${SIM_UDID})"

# --- 4. Build the app for the Simulator ---------------------------------------
DEST="platform=iOS Simulator,id=${SIM_UDID}"
echo ">>> Building app (scheme ${SCHEME}) for the Simulator"
if command -v xcpretty >/dev/null 2>&1; then
    xcodebuild -project "${PROJECT}" -scheme "${SCHEME}" -destination "${DEST}" \
        -derivedDataPath "${DERIVED}" -configuration Debug build | xcpretty
else
    xcodebuild -project "${PROJECT}" -scheme "${SCHEME}" -destination "${DEST}" \
        -derivedDataPath "${DERIVED}" -configuration Debug build
fi

APP_PATH="${DERIVED}/Build/Products/Debug-iphonesimulator/${SCHEME}.app"
if [[ ! -d "${APP_PATH}" ]]; then
    echo "ERROR: built app not found at ${APP_PATH}" >&2
    exit 1
fi

# --- 5. Boot the Simulator and bring it to the foreground ---------------------
echo ">>> Booting Simulator and opening the Simulator app"
xcrun simctl boot "${SIM_UDID}" 2>/dev/null || true
open -a Simulator
xcrun simctl bootstatus "${SIM_UDID}" || true

# --- 6. Install + launch the app ----------------------------------------------
# Uninstall first so the app re-stages the *current* bundled deck. The app keeps
# its Documents collection across launches (StudySandbox.stage freshCopy:false),
# so a stale copy from a previous run would otherwise hide a freshly regenerated
# deck. Uninstalling makes the recipe deterministic -- always the full deck.
echo ">>> Installing and launching ${BUNDLE_ID} (fresh install)"
xcrun simctl uninstall "${SIM_UDID}" "${BUNDLE_ID}" 2>/dev/null || true
xcrun simctl install "${SIM_UDID}" "${APP_PATH}"
xcrun simctl launch "${SIM_UDID}" "${BUNDLE_ID}"

echo ""
echo "Launched ${BUNDLE_ID} on '${SIM_NAME}'. Watch the Simulator window for the"
echo "PGRE review loop (Show Answer -> Answer: Good) with the live Rust-seam footer."
echo "Record it with:  xcrun simctl io booted recordVideo pgrep-ios.mp4"
