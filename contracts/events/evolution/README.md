# Contract evolution proof

`canonical-event-1.1-demo.schema.json` is an isolated, non-runtime example. It preserves the complete production 1.0 schema and changes only the schema/version metadata plus one backward-compatible optional field, `inspection.result.payload.analyzer_version`. The P0 runtime registry remains sourced solely from `contracts/events/canonical-event.schema.json`, accepts only `1.0`, and does not contain that field.

Regenerate and verify the evolution artifacts with:

```bash
uv run python scripts/generate_contracts.py \
  --schema contracts/events/evolution/canonical-event-1.1-demo.schema.json \
  --output-dir contracts/events/evolution/generated
uv run python scripts/generate_contracts.py --check \
  --schema contracts/events/evolution/canonical-event-1.1-demo.schema.json \
  --output-dir contracts/events/evolution/generated
uv run python scripts/check_contract_evolution.py
```

The final command validates every current `inspection.result` fixture twice: first against production 1.0, then—after changing only `schema_version` to `1.1`—against the demo schema. It also validates a fixture containing `analyzer_version`, checks the complete schema delta, and proves that a deliberately stale generated file is rejected. It does not modify the runtime registry.
