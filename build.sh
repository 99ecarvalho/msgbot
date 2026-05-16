#!/usr/bin/env bash
set -euo pipefail

echo "=== Building MsgBot stack ==="
docker compose build "$@"
echo "=== Build complete ==="
