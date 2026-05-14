# A single semantic waypoint produced by semantic-toponav.
#
# Mirrors `semantic_toponav.waypoint.semantic_waypoint.SemanticWaypoint`.

string node_id           # graph node id (unique within the topology graph)
string node_label        # human-readable label for the node
string node_type         # e.g. "room", "corridor", "elevator", "stairs"
string action            # e.g. "start", "enter", "take_elevator", "arrive"
string instruction       # natural-language instruction for the action

# Optional 2D pose. has_pose=false means pose/frame_id are not meaningful and
# downstream consumers should treat this waypoint as pose-less.
bool has_pose
string frame_id
geometry_msgs/Pose2D pose

# Arbitrary node properties carried over from the topology graph, encoded
# as a JSON document. Empty string when there are no properties.
string properties_json
