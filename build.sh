#!/usr/bin/env bash
set -euo pipefail

# Build wheel and sdist using uv
echo "[pktai] Building distribution artifacts..."
uv build

echo "[pktai] Build complete. Artifacts in ./dist"
