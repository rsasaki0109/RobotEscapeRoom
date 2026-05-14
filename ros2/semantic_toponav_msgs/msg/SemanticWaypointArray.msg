# An ordered list of semantic waypoints with the original node-ID path.
#
# This is the canonical output of a route plan and is what
# `waypoint_publisher_node` publishes when `output_format:=msg`.

std_msgs/Header header

# The planned path as a sequence of topology-graph node IDs.
string[] path

# One semantic waypoint per entry in `path`, in the same order.
SemanticWaypoint[] waypoints
