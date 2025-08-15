# inside GraphClient._build_app()


import sys

print("sys.path[0]:", sys.path[0])
import scripts
import scripts.graph_client

print("scripts package:", scripts.__file__)
print("graph_client:", scripts.graph_client.__file__)
