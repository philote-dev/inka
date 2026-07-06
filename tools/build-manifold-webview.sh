#!/usr/bin/env bash
# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
#
# Bundle the pgrep 3D knowledge manifold (Three.js + the shared renderer in
# ts/lib/pgrep/manifold3d.ts) into a single self-contained classic script for the
# native iOS Home's WKWebView. The output is committed as an app resource, so the
# iOS build (tools/build-xcframework.sh + xcodegen + xcodebuild) does not need a
# JS toolchain. Re-run this whenever the manifold TS or Three.js version changes.
#
# Output:
#   mobile/ios/PgrepStudy/Resources/Manifold/manifold.bundle.js
#
# Usage: tools/build-manifold-webview.sh   (or: just ios-manifold)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${ROOT_DIR}"

ESBUILD="node_modules/.bin/esbuild"
ENTRY="ts/lib/pgrep/manifold-embed.ts"
OUT="mobile/ios/PgrepStudy/Resources/Manifold/manifold.bundle.js"

if [[ ! -x "${ESBUILD}" ]]; then
    echo "ERROR: esbuild not found at ${ESBUILD}. Run the web deps install first (esbuild ships with the ts/ toolchain)." >&2
    exit 1
fi

echo ">>> Bundling ${ENTRY} -> ${OUT} (IIFE, minified, Three.js inlined)"
mkdir -p "$(dirname "${OUT}")"
"${ESBUILD}" "${ENTRY}" \
    --bundle \
    --format=iife \
    --platform=browser \
    --target=safari16 \
    --minify \
    --legal-comments=none \
    --outfile="${OUT}"

bytes="$(wc -c <"${OUT}" | tr -d ' ')"
echo "Built ${OUT} (${bytes} bytes)."
