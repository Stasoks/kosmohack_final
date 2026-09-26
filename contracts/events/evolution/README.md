# Contract evolution proof

`canonical-event-1.1-demo.schema.json` is an isolated, non-runtime example. It adds the optional `analyzer_version` field to `inspection.result` and registers only demo version `1.1`. The P0 runtime registry remains sourced solely from `contracts/events/canonical-event.schema.json` and accepts only `1.0`.

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

The final command also proves that a deliberately stale temporary generated file is rejected. It does not modify the runtime registry.
