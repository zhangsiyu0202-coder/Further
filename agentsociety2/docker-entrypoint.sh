#!/bin/sh
set -eu

python - <<'PY'
import os
import socket
import sys
import time
from urllib.parse import urlparse

neo4j_uri = os.getenv("NEO4J_URI", "bolt://neo4j:7687")
timeout = int(os.getenv("NEO4J_WAIT_TIMEOUT", "90"))
interval = float(os.getenv("NEO4J_WAIT_INTERVAL", "2"))

parsed = urlparse(neo4j_uri)
host = parsed.hostname or "neo4j"
port = parsed.port or 7687
deadline = time.time() + timeout

while True:
    try:
        with socket.create_connection((host, port), timeout=5):
            break
    except OSError:
        if time.time() >= deadline:
            print(f"Timed out waiting for Neo4j at {host}:{port}", file=sys.stderr)
            sys.exit(1)
        time.sleep(interval)

print(f"Neo4j is reachable at {host}:{port}")
PY

exec "$@"
