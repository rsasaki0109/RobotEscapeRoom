#!/usr/bin/env bash
#
# Regenerate the README hero (docs/images/robot_escape_room.gif) as a 3D
# Gazebo/RViz-style Foxglove replay of the escape-room MCAP.
#
# Usage:
#   scripts/foxglove_hero/build_escape_room_gif.sh
#
# Regenerate the MCAP first:
#   pip install -e '.[foxglove]'
#   PYTHONPATH=. python3 examples/export_escape_room_foxglove_mcap.py

set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$DIR/../.." && pwd)"
MCAP="$ROOT/docs/foxglove/robot_escape_room_demo.mcap"
FRAMES="${FRAMES_DIR:-/tmp/erframes}"
PORT="${PORT:-8081}"
CONTAINER="lichtblick-escape-hero"
IMAGE="ghcr.io/lichtblick-suite/lichtblick:latest"
GIF_OUT="$ROOT/docs/images/robot_escape_room.gif"
MP4_OUT="$ROOT/docs/images/robot_escape_room.mp4"
FPS="${FPS:-20}"
GIF_WIDTH="${GIF_WIDTH:-960}"

cleanup() { docker rm -f "$CONTAINER" >/dev/null 2>&1 || true; }
trap cleanup EXIT

[ -f "$MCAP" ] || { echo "missing MCAP: $MCAP"; exit 1; }

echo "==> starting Lichtblick on :$PORT"
cleanup
docker run -d --name "$CONTAINER" -p "$PORT:8080" "$IMAGE" >/dev/null
for _ in $(seq 1 30); do
  if curl -sf "http://localhost:$PORT/" >/dev/null 2>&1; then break; fi
  sleep 1
done

echo "==> serving MCAP"
docker cp "$MCAP" "$CONTAINER:/src/escape_room.mcap"

echo "==> rendering 3D frames"
node "$DIR/render_escape_room.cjs" "$FRAMES" "http://localhost:$PORT" "http://localhost:$PORT/escape_room.mcap"

last="$(ls "$FRAMES"/f*.png | sort | tail -1)"
n="$(ls "$FRAMES"/f*.png | wc -l)"
for k in $(seq "$n" $((n + 8))); do
  cp "$last" "$FRAMES/f$(printf '%03d' "$k").png"
done

echo "==> encoding GIF -> $GIF_OUT"
palette="/tmp/erhero_palette.png"
ffmpeg -y -framerate "$FPS" -i "$FRAMES/f%03d.png" \
  -vf "scale=$GIF_WIDTH:-1:flags=lanczos,palettegen=max_colors=160:stats_mode=full" "$palette"
ffmpeg -y -framerate "$FPS" -i "$FRAMES/f%03d.png" -i "$palette" \
  -lavfi "scale=$GIF_WIDTH:-1:flags=lanczos[x];[x][1:v]paletteuse=dither=bayer:bayer_scale=3" "$GIF_OUT"

echo "==> encoding MP4 -> $MP4_OUT"
ffmpeg -y -framerate "$FPS" -i "$FRAMES/f%03d.png" \
  -vf "scale=1280:-2:flags=lanczos,format=yuv420p" -movflags +faststart -crf 22 "$MP4_OUT"

echo "==> done"
ls -lh "$GIF_OUT" "$MP4_OUT"
