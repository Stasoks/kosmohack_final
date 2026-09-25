#!/usr/bin/env sh
set -eu

source_file=${1:?usage: restore_db.sh BACKUP.sql.gz}
if [ "${TRACEQ_RESTORE_CONFIRM:-}" != "YES" ]; then
  echo "Refusing destructive restore. Set TRACEQ_RESTORE_CONFIRM=YES." >&2
  exit 2
fi

gzip -dc "$source_file" | docker compose exec -T postgres psql \
  --username "${POSTGRES_OWNER_USER:-traceq_owner}" \
  --dbname "${POSTGRES_DB:-traceq}" \
  --set ON_ERROR_STOP=on

echo "Restore completed; run migrations, recovery, and integrity verification."
