#!/usr/bin/env bash
#
# Regenerate the README hero (docs/images/robot_escape_room.gif).
#
# Deterministic renderer: one PNG per planner timeline frame so the robot
# visibly moves every frame. Foxglove MCAP is still exported for interactive
# replay; the GIF no longer depends on flaky headless Lichtblick capture.
#
# Usage:
#   scripts/foxglove_hero/build_escape_room_gif.sh
#
# Regenerate timeline + MCAP first:
#   pip install -e '.[foxglove]'
#   PYTHONPATH=. python3 examples/export_escape_room_foxglove_mcap.py

set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$DIR/../.." && pwd)"
FRAMES="${FRAMES_DIR:-/tmp/erframes}"
GIF_OUT="$ROOT/docs/images/robot_escape_room.gif"
MP4_OUT="$ROOT/docs/images/robot_escape_room.mp4"
FPS="${FPS:-12}"
GIF_WIDTH="${GIF_WIDTH:-1280}"

[ -f "$ROOT/docs/foxglove/robot_escape_room_timeline.json" ] || {
  echo "missing timeline JSON — run export_escape_room_foxglove_mcap.py first"
  exit 1
}

echo "==> rendering deterministic frames (map + camera + 3D sim)"
rm -rf "$FRAMES"
PYTHONPATH="$ROOT" python3 "$DIR/render_escape_room_hero.py" "$FRAMES"

n="$(ls "$FRAMES"/f*.png | wc -l)"
last="$(ls "$FRAMES"/f*.png | sort | tail -1)"
for k in $(seq "$n" $((n + 6))); do
  cp "$last" "$FRAMES/f$(printf '%03d' "$k").png"
done

echo "==> encoding GIF -> $GIF_OUT"
palette="/tmp/erhero_palette.png"
ffmpeg -y -framerate "$FPS" -i "$FRAMES/f%03d.png" \
  -vf "scale=$GIF_WIDTH:-1:flags=lanczos,palettegen=max_colors=128:stats_mode=diff" "$palette"
ffmpeg -y -framerate "$FPS" -i "$FRAMES/f%03d.png" -i "$palette" \
  -lavfi "scale=$GIF_WIDTH:-1:flags=lanczos[x];[x][1:v]paletteuse=dither=bayer:bayer_scale=4:diff_mode=rectangle" "$GIF_OUT"

echo "==> encoding MP4 -> $MP4_OUT"
ffmpeg -y -framerate "$FPS" -i "$FRAMES/f%03d.png" \
  -vf "scale=1280:-2:flags=lanczos,format=yuv420p" -movflags +faststart -crf 22 "$MP4_OUT"

echo "==> done ($n planner frames @ ${FPS}fps)"
ls -lh "$GIF_OUT" "$MP4_OUT"
