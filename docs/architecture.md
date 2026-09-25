# Architecture

TRACE-Q is a modular monolith with separate deployable UI, API, outbox worker, ERP emulator, and PostgreSQL database. This keeps a low resource footprint while preserving explicit boundaries.

```text
┌─────────┐  HTTP  ┌───────────┐  HTTP/JWT  ┌──────────────────────────────┐
│ Browser │───────▶│ Streamlit │───────────▶│ FastAPI                      │
└─────────┘        └───────────┘            │ auth / ingest / projections  │
                                            │ quality / routes / adapters  │
                                            └──────────────┬───────────────┘
                                                           │ SQLAlchemy
                                            ┌──────────────▼───────────────┐
                                            │ PostgreSQL 16                │
                                            │ raw record + projections     │
                                            └──────────────┬───────────────┘
                                                           │ SKIP LOCKED
                                            ┌──────────────▼───────────────┐
                                            │ Outbox worker ───────┐       │
                                            └──────────────────────┼───────┘
                                                                   │ HTTP
                                                         ┌─────────▼────────┐
                                                         │ ERP Emulator     │
                                                         └──────────────────┘
```

## Boundaries

- `domain` and `quality` contain pure validation, trust, occurrence, and Birth Window rules.
- `ingestion` authenticates service sources and commits encrypted source records.
- `projections` decrypts accepted history, takes an item-scoped PostgreSQL advisory transaction lock, sorts deterministically, and atomically replaces rebuildable state.
- `integrations` exposes business-facing ports; vendor field mapping remains at the adapter boundary.
- `security` owns user/source authentication, encryption, integrity, permissions, and safe audit.
- Streamlit holds tokens only in server-side session state and has no DB credentials.

## Consistency and concurrency

Raw acceptance and projection rebuild are intentionally separate transactions. A committed source fact is never reported as rejected merely because replay failed. `projection_state` records `stale`, `rebuilding`, `up_to_date`, or `failed`; startup recovery finds every item whose latest ingest sequence is newer than the last projected sequence.

Events for one item serialize through `pg_advisory_xact_lock` using the signed first 64 bits of SHA-256 of the item ID. Python's randomized `hash()` is not used. Different items can rebuild concurrently. Outbox workers use `FOR UPDATE SKIP LOCKED`.

Business order is:

```text
occurred_at, source_id, source_sequence NULLS LAST, received_at, event_id
```

This is a deterministic tie-break, not a claim of causality.

## Extension path

- Add OpenTelemetry by instrumenting FastAPI middleware, SQLAlchemy, HTTPX adapters, and the worker loop; domain modules do not change.
- Add a broker by implementing an ingress transport that calls the same ingestion application service and an outbox publisher destination. Idempotency and event contracts remain unchanged.
- Add a vendor system by implementing `ProductionSystemAdapter`; no production rule references 1C/Galaktika field names.

The principal bottlenecks are item-hotspot replay, source-scoped integrity serialization, PostgreSQL I/O, and analytical scans. The current demo uses one API process and one worker to fit about 1 CPU/1 GB RAM. Horizontal replicas require the same database, crypto keys, contract registry, and clock discipline.
