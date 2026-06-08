# Robot Escape Room — 3D room meshes

Axis-aligned box meshes generated from `examples/robot_escape_room.yaml`.
One OBJ per topology node (room / corridor / stairwell / exit).

## Regenerate

```bash
PYTHONPATH=. python3 examples/generate_escape_room_meshes.py
```

## Files

| File | Purpose |
|---|---|
| `<node_id>.obj` | Single room mesh (metres, Z-up, `map` frame) |
| `escape_room_scene.obj` | Full facility merged for import |
| `manifest.json` | Centres, sizes, colours — hook for tooling |

## Import into Blender

1. File → Import → Wavefront (.obj) → `escape_room_scene.obj`
2. Scene units: metres
3. Each `o <node_id>` group is one navigable space from the topology graph

## Import into 3ds Max

File → Import → `escape_room_scene.obj` (Z-up; scale 1.0 = 1 metre).

## Facility mesh render (README hero)

Detailed interior rooms (tiled floor, doorways, ceiling lights, props) export
to OBJ and feed the hero GIF renderer:

```bash
PYTHONPATH=. python3 examples/generate_escape_room_meshes.py
PYTHONPATH=. python3 examples/generate_escape_room_3dgs_map.py
```

Each `<node_id>.obj` is a furnished room shell — import `escape_room_scene.obj`
into Blender for the full facility.

## Gazebo / Foxglove

The MCAP exporter (`export_escape_room_foxglove_mcap.py`) and README hero
renderer (`render_escape_room_hero.py`) use the same box dimensions from
`escape_room_meshes.py` — regenerate OBJs after editing mesh sizes there.
