#!/usr/bin/env bash
# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
#
# Build the `anki-ffi` static library for iOS and assemble AnkiFfi.xcframework,
# which the native iOS/SwiftUI app links against to drive the same shared engine
# that desktop uses (see rslib/ffi).
#
# Slices:
#   * aarch64-apple-ios-sim  -> REQUIRED  (L0 runs on the iOS Simulator)
#   * aarch64-apple-ios      -> best-effort (device; skipped if it fails)
#
# Paths (both live under out/, which is gitignored):
#   * cargo --target-dir : out/ios-rust
#   * xcframework output : out/ios/AnkiFfi.xcframework
#
# Prerequisites:
#   rustup target add aarch64-apple-ios-sim aarch64-apple-ios
#   Xcode command line tools (xcodebuild).
#
# Usage: tools/build-xcframework.sh

set -euo pipefail

# Resolve repo root (this script lives in <root>/tools).
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${ROOT_DIR}"

PACKAGE="anki-ffi"
LIB_NAME="libanki_ffi.a"
FEATURES="rustls"          # avoid system OpenSSL when cross-compiling
PROFILE="release"
HEADERS_DIR="rslib/ffi/include"
TARGET_DIR="out/ios-rust"
OUT_DIR="out/ios"
XCFRAMEWORK="${OUT_DIR}/AnkiFfi.xcframework"

SIM_TARGET="aarch64-apple-ios-sim"   # required
DEVICE_TARGET="aarch64-apple-ios"    # best-effort

# iOS deployment target for all slices.
export IPHONEOS_DEPLOYMENT_TARGET="${IPHONEOS_DEPLOYMENT_TARGET:-13.0}"

slice_lib() {
    echo "${TARGET_DIR}/$1/${PROFILE}/${LIB_NAME}"
}

build_slice() {
    local target="$1"
    echo ">>> Building ${PACKAGE} for ${target} (${PROFILE}, features=${FEATURES}, IPHONEOS_DEPLOYMENT_TARGET=${IPHONEOS_DEPLOYMENT_TARGET})"
    cargo build -p "${PACKAGE}" \
        --"${PROFILE}" \
        --features "${FEATURES}" \
        --target "${target}" \
        --target-dir "${TARGET_DIR}"
}

# --- Simulator slice (required) ------------------------------------------------
build_slice "${SIM_TARGET}"
SIM_LIB="$(slice_lib "${SIM_TARGET}")"
if [[ ! -f "${SIM_LIB}" ]]; then
    echo "ERROR: expected simulator static library not found at ${SIM_LIB}" >&2
    exit 1
fi

# --- Device slice (best-effort) ------------------------------------------------
DEVICE_LIB=""
if build_slice "${DEVICE_TARGET}"; then
    candidate="$(slice_lib "${DEVICE_TARGET}")"
    if [[ -f "${candidate}" ]]; then
        DEVICE_LIB="${candidate}"
    else
        echo "WARNING: device build reported success but ${candidate} is missing; continuing simulator-only." >&2
    fi
else
    echo "WARNING: device slice (${DEVICE_TARGET}) failed to build; producing a simulator-only xcframework." >&2
fi

# --- Assemble the xcframework --------------------------------------------------
rm -rf "${XCFRAMEWORK}"
mkdir -p "${OUT_DIR}"

xcargs=(-create-xcframework -library "${SIM_LIB}" -headers "${HEADERS_DIR}")
if [[ -n "${DEVICE_LIB}" ]]; then
    xcargs+=(-library "${DEVICE_LIB}" -headers "${HEADERS_DIR}")
fi
xcargs+=(-output "${XCFRAMEWORK}")

xcodebuild "${xcargs[@]}"

echo ""
if [[ -n "${DEVICE_LIB}" ]]; then
    echo "Built AnkiFfi.xcframework with simulator + device slices."
else
    echo "Built AnkiFfi.xcframework with simulator slice only (device slice unavailable)."
fi
echo "xcframework: ${ROOT_DIR}/${XCFRAMEWORK}"
