# Backup and recovery

Back up the PostgreSQL database together with an independently protected inventory of the AES/HMAC/JWT key IDs and secret-store versions. The SQL backup deliberately does not contain keys. Without the matching AES key, encrypted raw payloads cannot be recovered; without the HMAC key, integrity cannot be re-established.

Demo backup:

```bash
bash scripts/backup_db.sh output/backups/traceq.sql.gz
```

Restore into a stopped/isolated environment with the same schema owner and externally supplied secrets:

```bash
bash scripts/restore_db.sh output/backups/traceq.sql.gz
docker compose -f compose.yaml run --rm migrate
```

After restore:

1. Start backend and let startup recovery rebuild stale projections.
2. Log in as admin and run integrity verification.
3. Compare outbox states and ERP ACK records; retry only undelivered messages with stable IDs.
4. Confirm worker heartbeat and all health endpoints.
5. Run S01/S03 in a separate demo database, not against restored production evidence.

Restore is destructive to the target database. The script requires `TRACEQ_RESTORE_CONFIRM=YES` and should run only after a fresh target backup and explicit operator review.
