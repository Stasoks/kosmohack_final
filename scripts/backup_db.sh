#!/usr/bin/env sh
set -eu

target=${1:-output/backups/traceq.sql.gz}
target_dir=$(dirname "$target")
mkdir -p "$target_dir"

docker compose exec -T postgres pg_dump \
  --username "${POSTGRES_OWNER_USER:-traceq_owner}" \
  --dbname "${POSTGRES_DB:-traceq}" \
  --format=plain \
  --no-password | gzip -9 > "$target"

echo "Backup written to $target"
