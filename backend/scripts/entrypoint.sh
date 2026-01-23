#!/bin/sh
set -e

# Sync intro voice samples from Azure Blob Storage without blocking API startup
echo "Syncing intro voice samples in background..."
(python -m backend.scripts.sync_voices || echo "Voice sync skipped/failed; continuing") &

# Execute the main command
exec "$@"
