#!/usr/bin/env bash

set -euo pipefail

SOURCE_DIR="/home/homelabuser/docker/ai/ai-gateway"
BACKUP_ROOT="/backup/homelab-core/snapshots"
TIMESTAMP="$(date +%Y-%m-%d_%H-%M-%S)"
DESTINATION="$BACKUP_ROOT/$TIMESTAMP"

mkdir -p "$DESTINATION"

echo "Creating Homelab Core snapshot: $TIMESTAMP"

cd "$SOURCE_DIR"

# Create a consistent SQLite copy if the database exists.
if [ -f "$SOURCE_DIR/data/queue.db" ]; then
    python3 - <<'PY'
import sqlite3
from pathlib import Path

source_path = Path("/home/homelabuser/docker/ai/ai-gateway/data/queue.db")
snapshot_path = Path("/home/homelabuser/docker/ai/ai-gateway/data/queue.snapshot.db")

if snapshot_path.exists():
    snapshot_path.unlink()

source = sqlite3.connect(source_path)
destination = sqlite3.connect(snapshot_path)

source.backup(destination)

destination.close()
source.close()
PY
fi

rsync -a \
  --exclude='.git/' \
  --exclude='__pycache__/' \
  --exclude='*.pyc' \
  --exclude='data/queue.db' \
  --exclude='data/queue.db-wal' \
  --exclude='data/queue.db-shm' \
  --exclude='data/queue.snapshot.db' \
  "$SOURCE_DIR/" \
  "$DESTINATION/"

mkdir -p "$DESTINATION/data"

if [ -f "$SOURCE_DIR/data/queue.snapshot.db" ]; then
    mv \
      "$SOURCE_DIR/data/queue.snapshot.db" \
      "$DESTINATION/data/queue.db"
fi

{
    echo "Homelab Core snapshot"
    echo "Created: $(date --iso-8601=seconds)"
    echo "Version: $(cat "$SOURCE_DIR/VERSION" 2>/dev/null || echo unknown)"
    echo "Hostname: $(hostname)"
} > "$DESTINATION/SNAPSHOT_INFO"

cd "$DESTINATION"

find . \
  -type f \
  ! -name 'SHA256SUMS' \
  -print0 \
  | sort -z \
  | xargs -0 sha256sum \
  > SHA256SUMS

ln -sfn \
  "$DESTINATION" \
  "/backup/homelab-core/latest"

# Keep the latest 7 snapshots.
find "$BACKUP_ROOT" \
  -mindepth 1 \
  -maxdepth 1 \
  -type d \
  -printf '%T@ %p\n' \
  | sort -rn \
  | tail -n +8 \
  | cut -d' ' -f2- \
  | xargs -r rm -rf

echo
echo "Snapshot created:"
echo "$DESTINATION"
