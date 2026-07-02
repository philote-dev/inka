#!/usr/bin/env bash
# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
#
# Generate SwiftProtobuf message types for the native iOS/SwiftUI app from the
# shared `proto/anki/*.proto` contracts. The generated .swift files are checked
# in (see mobile/ios/PgrepStudy/Generated) so the Xcode app builds without a
# codegen step; re-run this script whenever the .proto files change.
#
# Messages only: we do NOT generate gRPC/service stubs. The engine is driven
# entirely by run_service_method(service, method, bytes) over the C ABI (see
# mobile/ios/PgrepStudy/AnkiBackend.swift), so only the request/response
# message types are needed.
#
# Prerequisites:
#   brew install swift-protobuf      # provides protoc-gen-swift
#   (protoc: repo's out/extracted/protoc/bin/protoc is used if present, else
#    the system `protoc` on PATH)
#
# Usage: tools/gen-swift-protos.sh

set -euo pipefail

# Resolve repo root (this script lives in <root>/tools).
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${ROOT_DIR}"

PROTO_DIR="proto"
OUT_DIR="mobile/ios/PgrepStudy/Generated"

# Prefer the repo's pinned protoc, fall back to a system install.
if [[ -x "out/extracted/protoc/bin/protoc" ]]; then
    PROTOC="out/extracted/protoc/bin/protoc"
elif command -v protoc >/dev/null 2>&1; then
    PROTOC="$(command -v protoc)"
else
    echo "ERROR: protoc not found (looked for out/extracted/protoc/bin/protoc and \$PATH)." >&2
    exit 1
fi

if ! command -v protoc-gen-swift >/dev/null 2>&1; then
    echo "ERROR: protoc-gen-swift not found. Install with: brew install swift-protobuf" >&2
    exit 1
fi

echo ">>> protoc:            ${PROTOC} ($(${PROTOC} --version))"
echo ">>> protoc-gen-swift:  $(protoc-gen-swift --version)"

# Fresh output dir (only ever holds generated files).
rm -rf "${OUT_DIR}"
mkdir -p "${OUT_DIR}"

# Generate message types for every anki proto. DropPath flattens the output so
# files land directly in Generated/ (all anki/*.proto basenames are unique).
"${PROTOC}" \
    -I "${PROTO_DIR}" \
    --plugin=protoc-gen-swift="$(command -v protoc-gen-swift)" \
    --swift_opt=Visibility=Public \
    --swift_opt=FileNaming=DropPath \
    --swift_out="${OUT_DIR}" \
    "${PROTO_DIR}"/anki/*.proto

count="$(find "${OUT_DIR}" -name '*.swift' | wc -l | tr -d ' ')"
echo ""
echo "Generated ${count} Swift files into ${OUT_DIR}"
