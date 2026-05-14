# A single node in a semantic topology graph.
#
# Mirrors `semantic_toponav.graph.types.TopologyNode`.

string id
string label
string type

# Optional 2D pose. has_pose=false means pose/frame_id are not meaningful.
bool has_pose
string frame_id
geometry_msgs/Pose2D pose

# Arbitrary node properties (e.g. visit history) encoded as a JSON document.
string properties_json
