#!/usr/bin/env bash
#
# Regenerate the README hero (docs/images/22_foxglove_replay.gif + .mp4) from
# the committed MCAP, fully automated — no manual screen recording.
#
# Pipeline:
#   1. start a local, headless open-source Foxglove (Lichtblick) container
#   2. serve the committed MCAP from inside it (same origin -> no CORS, no upload)
#   3. drive it with Playwright (render.cjs): inject a layout, play, capture frames
#   4. assemble the frames into a GIF + MP4 with ffmpeg
#
# Requirements (none are repo/CI deps — this is a local authoring tool):
#   - docker
#   - node + playwright  (npm install playwright; npx playwright install chrome)
#   - ffmpeg
#
# Usage:
#   scripts/foxglove_hero/build_hero_gif.sh
#
# Regenerate the MCAP first if the graph/route changed:
#   pip install -e '.[foxglove]' && python examples/export_foxglove_mcap.py

set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$DIR/../.." && pwd)"
MCAP="$ROOT/docs/foxglove/semantic_toponav_demo.mcap"
FRAMES="${FRAMES_DIR:-/tmp/fxframes}"
PORT="${PORT:-8080}"
CONTAINER="lichtblick-hero"
IMAGE="ghcr.io/lichtblick-suite/lichtblick:latest"
GIF_OUT="$ROOT/docs/images/22_foxglove_replay.gif"
MP4_OUT="$ROOT/docs/images/22_foxglove_replay.mp4"
FPS="${FPS:-24}"
GIF_WIDTH="${GIF_WIDTH:-900}"

cleanup() { docker rm -f "$CONTAINER" >/dev/null 2>&1 || true; }
trap cleanup EXIT

[ -f "$MCAP" ] || { echo "missing MCAP: $MCAP (run examples/export_foxglove_mcap.py)"; exit 1; }

echo "==> starting Lichtblick ($IMAGE) on :$PORT"
cleanup
docker run -d --name "$CONTAINER" -p "$PORT:8080" "$IMAGE" >/dev/null
# Wait for the static server to come up.
for _ in $(seq 1 30); do
  if curl -sf "http://localhost:$PORT/" >/dev/null 2>&1; then break; fi
  sleep 1
done

echo "==> serving MCAP same-origin"
docker cp "$MCAP" "$CONTAINER:/src/demo.mcap"

echo "==> rendering frames with Playwright"
node "$DIR/render.cjs" "$FRAMES" "http://localhost:$PORT" "http://localhost:$PORT/demo.mcap"

# Hold the final (goal-reached) frame for a short beat so the loop pauses.
last="$(ls "$FRAMES"/f*.png | sort | tail -1)"
n="$(ls "$FRAMES"/f*.png | wc -l)"
for k in $(seq "$n" $((n + 5))); do
  cp "$last" "$FRAMES/f$(printf '%03d' "$k").png"
done

echo "==> encoding GIF -> $GIF_OUT"
palette="/tmp/fxhero_palette.png"
ffmpeg -y -framerate "$FPS" -i "$FRAMES/f%03d.png" \
  -vf "scale=$GIF_WIDTH:-1:flags=lanczos,palettegen=max_colors=160:stats_mode=full" "$palette"
ffmpeg -y -framerate "$FPS" -i "$FRAMES/f%03d.png" -i "$palette" \
  -lavfi "scale=$GIF_WIDTH:-1:flags=lanczos[x];[x][1:v]paletteuse=dither=bayer:bayer_scale=3" "$GIF_OUT"

echo "==> encoding MP4 -> $MP4_OUT"
ffmpeg -y -framerate "$FPS" -i "$FRAMES/f%03d.png" \
  -vf "scale=1280:-2:flags=lanczos,format=yuv420p" -movflags +faststart -crf 22 "$MP4_OUT"

echo "==> done"
ls -lh "$GIF_OUT" "$MP4_OUT"
