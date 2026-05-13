# A single edge in a semantic topology graph.
#
# Mirrors `semantic_toponav.graph.types.TopologyEdge`.

string id
string source
string target
string type
float64 cost
bool bidirectional

# Arbitrary edge properties encoded as a JSON document.
string properties_json
