#!/usr/bin/env bash
set -euo pipefail

# Ensure .env exists
if [[ ! -f .env ]]; then
    echo "ERROR: .env file not found. Copy .env.example and fill in your keys:"
    echo "  cp .env.example .env"
    exit 1
fi

echo "=== Starting MsgBot stack ==="
docker compose up "$@"
