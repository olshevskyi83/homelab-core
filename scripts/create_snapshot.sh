
#!/usr/bin/env bash

set -euo pipefail

SOURCE_DIR="/home/homelabuser/docker/ai/ai-gateway"

BACKUP_ROOT="/backup/homelab-core/snapshots"

TIMESTAMP="$(date +%Y-%m-%d_%H-%M-%S)"

DESTINATION="$BACKUP_ROOT/$TIMESTAMP"

mkdir -p "$DESTINATION"

echo "Creating Homelab Core snapshot: $TIMESTAMP"

cd "$SOURCE_DIR"

if docker compose ps --status running --services | grep -qx ai-gateway; then

    docker compose exec -T ai-gateway python - <<'PY'

import sqlite3

source = sqlite3.connect("/app/data/queue.db")

destination = sqlite3.connect("/app/data/queue.snapshot.db")

source.backup(destination)

destination.close()

source.close()

PY

fi

rsync -a \

    --exclude '.git/' \

    --exclude '__pycache__/' \

    --exclude '*.pyc' \

    --exclude 'data/queue.db-wal' \

    --exclude 'data/queue.db-shm' \

    "$SOURCE_DIR/" \

    "$DESTINATION/"

if [ -f "$DESTINATION/data/queue.snapshot.db" ]; then

    mv \

        "$DESTINATION/data/queue.snapshot.db" \

        "$DESTINATION/data/queue.db"

fi

{

    echo "Homelab Core snapshot"

    echo "Created: $(date --iso-8601=seconds)"

    echo "Version: $(cat "$SOURCE_DIR/VERSION" 2>/dev/null || echo unknown)"

    echo "Hostname: $(hostname)"

} > "$DESTINATION/SNAPSHOT_INFO"

cd "$DESTINATION"

find . -type f \

    ! -name SHA256SUMS \

    -print0 |

    sort -z |

    xargs -0 sha256sum > SHA256SUMS

ln -sfn "$DESTINATION" "$BACKUP_ROOT/../latest"

find "$BACKUP_ROOT" \

    -mindepth 1 \

    -maxdepth 1 \

    -type d \

    -printf '%T@ %p\n' |

    sort -rn |

    tail -n +8 |

    cut -d' ' -f2- |

    xargs -r rm -rf

echo "Snapshot created:"

echo "$DESTINATION"

