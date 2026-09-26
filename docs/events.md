# Events and contracts

The source of truth is [the JSON Schema](../contracts/events/canonical-event.schema.json). Generated Pydantic payload models, TypeScript interfaces, and the contract registry live in `shared_contracts/generated/`. `scripts/generate_contracts.py` renders all three artifacts deterministically from the JSON Schema; `--check` regenerates into a temporary location and fails on drift. They are checked with:

```bash
make generate-contracts
make check-contracts
```

Supported P0 types at exact version `1.0` are `item.registered`, `operation.started`, `operation.finished`, `inspection.result`, `machine.state`, `operator.action`, and `control_device.invalidated`. Unknown versions return `UNSUPPORTED_SCHEMA_VERSION`; parsers for versions present in raw history must not be removed.

`analyzer_version` is not a current P0 field. The isolated [1.1 evolution proof](../contracts/events/evolution/README.md) adds it only to a non-runtime demonstration schema, generates separate Python/TypeScript/registry artifacts, and proves stale-output detection. Run `make check-contract-evolution`; the runtime registry remains `1.0` only.

External sources authenticate independently from human users with `X-Source-Id` and `X-Source-Token`. A source is enabled and restricted to explicit event types. Random high-entropy tokens are stored only as SHA-256 hashes and compared in constant time; they are never logged. Human passwords separately use the deliberately expensive Argon2id scheme.

Validation outcomes:

- malformed JSON, missing required fields, invalid enums, types, or versions: reject and write a rejected `ingest_attempt`;
- impossible semantics such as a negative duration: `SEMANTIC_VALIDATION_ERROR`;
- suspicious but possible duration: accept with a data-quality warning;
- absent optional value: accept without inventing a business default;
- `impossible_to_assess`: valid observation and `UNASSESSABLE` trust.

Canonical JSON uses sorted keys, UTF-8, and compact separators. Same event ID plus the same canonical hash is a successful duplicate; no domain count changes. Same ID plus different content is `409 EVENT_ID_CONFLICT`; the original remains unchanged.

`received_at` is assigned by TRACE-Q. `ingest_seq` is recovery/audit order, never production time. Source clocks should be monitored; deterministic ordering cannot prove causality when timestamps collide.

## Canonical envelope and device invalidation

`item_id` and `operation_run_id` belong only to the envelope. Legacy fixtures are normalized at ingestion and contract-check boundaries. `duration` remains `{value, unit, meaning}`. `control_device.invalidated` carries `device_id`, affected interval, reason and optional evidence; only a calibration-system source or the privileged human workflow may create it. Unknown `(event_type, schema_version)` pairs are rejected.
