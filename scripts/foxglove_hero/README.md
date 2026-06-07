# Foxglove hero GIF — automated regeneration

`docs/images/22_foxglove_replay.gif` (the multi-floor office gallery GIF) and
`docs/images/robot_escape_room.gif` (the **README hero** — 3D escape-room replay)
are rendered **headless,
with no manual screen recording**, from committed MCAPs
([`semantic_toponav_demo.mcap`](../../docs/foxglove/semantic_toponav_demo.mcap),
[`robot_escape_room_demo.mcap`](../../docs/foxglove/robot_escape_room_demo.mcap)).

The hosted app at `app.foxglove.dev` requires sign-in and would upload the MCAP
to a third party, so instead we self-host the open-source Foxglove fork
([Lichtblick](https://github.com/lichtblick-suite/lichtblick)) in a container,
serve the MCAP same-origin, drive it with Playwright, and assemble the captured
frames with ffmpeg.

## Run

```bash
# one-time tooling (not repo/CI deps):
npm install playwright && npx playwright install chrome   # Chrome channel
# docker + ffmpeg must also be on PATH

scripts/foxglove_hero/build_hero_gif.sh          # office demo
scripts/foxglove_hero/build_escape_room_gif.sh  # README hero
```

`build_hero_gif.sh` overwrites `docs/images/22_foxglove_replay.{gif,mp4}`.
`build_escape_room_gif.sh` overwrites `docs/images/robot_escape_room.{gif,mp4}`.
It renders **one PNG per planner timeline frame** via `render_escape_room_hero.py`
(deterministic robot motion). The older `render_escape_room.cjs` Lichtblick capture
path is kept for optional manual use but is no longer the default — headless
playback often froze mid-GIF.

## What it does

| step | file | detail |
|---|---|---|
| 1 | `build_hero_gif.sh` | starts `ghcr.io/lichtblick-suite/lichtblick` on `:8080`, `docker cp`s the MCAP into its web root |
| 2 | `render.cjs` | Playwright: injects a single-3D-panel layout into Lichtblick's IndexedDB, loads the MCAP via `?ds=remote-file`, plays it, and captures the canvas via CDP `Page.captureScreenshot` |
| 3 | `build_hero_gif.sh` | ffmpeg `palettegen`/`paletteuse` → GIF, plus an H.264 MP4 |

## Tuning

`render.cjs` reads a few env vars (`SPEED`, `CAPTURE_MS`, `WIDTH`, `HEIGHT`);
`build_hero_gif.sh` reads `FPS`, `GIF_WIDTH`, `PORT`. The camera (a fixed
`map`-frame view framed on the `y=0` route plane) and the dark theme live in
`render.cjs`'s `heroLayout()`.

The replay content itself — topology, route, the cyan "traveled" progress line,
robot pose — comes from the MCAP. Change the graph/route there:

```bash
pip install -e '.[foxglove]'
python examples/export_foxglove_mcap.py
PYTHONPATH=. python3 examples/export_escape_room_foxglove_mcap.py
```
