# A complete semantic topology graph.
#
# Mirrors `semantic_toponav.graph.topology_graph.TopologyGraph` at the message
# level. The graph is what `graph_loader_node` validates at startup.

std_msgs/Header header

TopologyNode[] nodes
TopologyEdge[] edges
