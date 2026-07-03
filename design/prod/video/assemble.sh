#!/usr/bin/env bash
# Turn the raw Playwright recording into a clean 1080p MP4.
# Usage: bash design/prod/video/assemble.sh
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RAW="$DIR/raw/walkthrough.webm"
OUT="$DIR/pgrep-concept-walkthrough-1080p.mp4"

if [[ ! -f "$RAW" ]]; then
  echo "Missing $RAW. Run: node design/prod/video/record.mjs" >&2
  exit 1
fi

# Native capture is 1728x1080 (16:10). Pad to 1920x1080 on the warm canvas color,
# force 30fps and yuv420p for broad player and QuickTime compatibility, and put
# the moov atom up front for streaming.
ffmpeg -y -i "$RAW" \
  -vf "pad=1920:1080:(1920-iw)/2:(1080-ih)/2:color=0x262624,fps=30,format=yuv420p" \
  -c:v libx264 -profile:v high -crf 18 -preset slow \
  -movflags +faststart -an \
  "$OUT"

echo "Wrote $OUT"
ffprobe -v error -show_entries format=duration:stream=width,height -of default=noprint_wrappers=1 "$OUT"
