
import sys
import scripts
import scripts.graph_client


# inside GraphClient._build_app()

print("sys.path[0]:", sys.path[0])
print("scripts package:", scripts.__file__)
print("graph_client:", scripts.graph_client.__file__)
