#!/usr/bin/env bash
# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
#
# Vendor the offline MathJax build for the native iOS math renderer's WKWebView
# (mobile/ios/PgrepStudy/MathText.swift). We ship the same self-contained
# tex-svg-full build the ts toolchain imports (ts/lib/pgrep/math.ts). SVG output
# embeds its glyphs in the script, so there are no CHTML web-font downloads and
# nothing touches the network at runtime. The output is committed as an app
# resource, so the iOS build needs no JS toolchain. Re-run this whenever the
# pinned MathJax version in node_modules changes.
#
# Output:
#   mobile/ios/PgrepStudy/Resources/MathJax/tex-svg-full.js
#
# Usage: tools/build-mathjax-webview.sh   (or: just ios-mathjax)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${ROOT_DIR}"

SRC="node_modules/mathjax/es5/tex-svg-full.js"
OUT="mobile/ios/PgrepStudy/Resources/MathJax/tex-svg-full.js"

if [[ ! -f "${SRC}" ]]; then
    echo "ERROR: MathJax not found at ${SRC}. Install the web deps first (mathjax ships with the ts/ toolchain)." >&2
    exit 1
fi

echo ">>> Vendoring ${SRC} -> ${OUT} (offline, SVG output)"
mkdir -p "$(dirname "${OUT}")"
cp "${SRC}" "${OUT}"

# Neutralize MathJax's dormant Speech Rule Engine CDN fallbacks. The combined
# builds embed jsdelivr URLs for the a11y/speech mathmaps; we never enable a11y
# (SVG output, no menu), so they are never fetched, but a hard-offline app should
# carry no live CDN host at all. Repoint them at a reserved non-resolving TLD so
# nothing can ever reach the network, even if a11y were switched on later.
perl -pi -e 's/\Qcdn.jsdelivr.net\E/offline.invalid/g' "${OUT}"

if grep -q "cdn.jsdelivr" "${OUT}"; then
    echo "ERROR: cdn.jsdelivr still present in ${OUT} after neutralization." >&2
    exit 1
fi

bytes="$(wc -c <"${OUT}" | tr -d ' ')"
echo "Vendored ${OUT} (${bytes} bytes, CDN fallbacks neutralized)."
