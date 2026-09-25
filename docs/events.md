# Events and contracts

The source of truth is [the JSON Schema](../contracts/events/canonical-event.schema.json). Generated registry artifacts live in `shared_contracts/generated/` and are checked with:

```bash
make generate-contracts
make check-contracts
```

Supported P0 types at exact version `1.0` are `item.registered`, `operation.started`, `operation.finished`, `inspection.result`, `machine.state`, and `operator.action`. Unknown versions return `UNSUPPORTED_SCHEMA_VERSION`; parsers for versions present in raw history must not be removed.

External sources authenticate independently from human users with `X-Source-Id` and `X-Source-Token`. A source is enabled and restricted to explicit event types. Random high-entropy tokens are stored only as SHA-256 hashes and compared in constant time; they are never logged. Human passwords separately use the deliberately expensive Argon2id scheme.

Validation outcomes:

- malformed JSON, missing required fields, invalid enums, types, or versions: reject and write a rejected `ingest_attempt`;
- impossible semantics such as a negative duration: `SEMANTIC_VALIDATION_ERROR`;
- suspicious but possible duration: accept with a data-quality warning;
- absent optional value: accept without inventing a business default;
- `impossible_to_assess`: valid observation and `UNASSESSABLE` trust.

Canonical JSON uses sorted keys, UTF-8, and compact separators. Same event ID plus the same canonical hash is a successful duplicate; no domain count changes. Same ID plus different content is `409 EVENT_ID_CONFLICT`; the original remains unchanged.

`received_at` is assigned by TRACE-Q. `ingest_seq` is recovery/audit order, never production time. Source clocks should be monitored; deterministic ordering cannot prove causality when timestamps collide.
