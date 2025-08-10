#!/usr/bin/env bash
set -euo pipefail

# Validate artifacts with Twine
echo "[pktai] Checking distribution artifacts with Twine..."
uvx twine check dist/*

# Upload to PyPI via Twine (interactive for credentials or uses configured token)
echo "[pktai] Uploading artifacts to PyPI..."
uvx twine upload dist/*

echo "[pktai] Upload complete."
