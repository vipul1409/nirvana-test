#!/usr/bin/env bash
set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
docker compose -f "$SCRIPT_DIR/docker-compose.yml" up -d
echo "Temporal gRPC : localhost:7233"
echo "Temporal UI   : http://localhost:8080"
