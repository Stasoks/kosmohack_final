# TRACE-Q code audit report

Date: 2026-09-26

Scope: repository-wide pre-demo audit of the current TRACE-Q MVP. The goal is practical readiness for local startup and manual testing, not a claim of formal security certification or production acceptance.

## 1. Audit method

The review covered:

- Docker Compose startup, migration, seed and health flow;
- FastAPI routes and authorization boundaries;
- source authentication, replay/idempotency and source scope;
- encrypted raw-event storage and integrity chains;
- deterministic projections and replay;
- observation trust and Defect Birth Window logic;
- NCR/controller/rework/controlled release flow;
- Blast Radius, approvals and control-device invalidation;
- ERP adapter/outbox/worker behavior;
- route revisions and immutable history;
- contract schema/code generation;
- S01-S25 ScenarioHarness acceptance execution;
- Streamlit navigation and API/UI contract;
- load/test helper scripts;
- documentation claims versus implemented behavior.

GitHub Actions is configured as the final acceptance gate. This report describes the checks configured for the repository; it does not assert that the current HEAD has passed a new CI run after every change documented below.

## 2. P0/P1 issues found and fixed during hardening

### PostgreSQL tests were capable of silently skipping

Fixed by explicitly enabling `RUN_POSTGRES_TESTS=1` in CI/test execution and seeding an isolated PostgreSQL database before the integration suite.

### Scenario fixtures existed without being real end-to-end acceptance tests

Fixed by connecting ScenarioHarness V2 to the FastAPI demo endpoint and a PostgreSQL-backed runtime. S01-S25 now execute events plus optional actions, requests, ERP behavior, tamper actions, analysis requests and route changes.

### Projection replay could recreate closed defect episodes

Fixed by preserving defect-occurrence/NCR identity across rebuilds. Repeating replay does not duplicate an already closed occurrence or its analysis; a genuinely new post-closure defect still creates one new episode. PostgreSQL regression tests cover both cases.

### Rework verification could accept an unrelated GOOD

Fixed. Repeat GOOD must be trusted and cover the original defect type/component scope. Item-level NCRs require item-wide component coverage rather than a check scoped only to one component.

### Inspection capability was treated as a simple allow-list

Fixed with per-defect/per-component `FULL`, `PARTIAL`, `NONE` and `TARGET_ONLY` capability. Effective coverage is the intersection of the configured RouteStep capability, the source-reported inspection scope and, for rework verification, the targeted NCR scope. `PARTIAL` remains usable as trusted context but cannot become a GOOD Birth Window boundary.

### Conflict detection grouped unrelated observations too broadly

Fixed. A conflict now requires the same item, logical inspection session and control point, equal source priority, overlapping component scope, overlapping defect type and incompatible outcomes. The fallback logical-session key includes item, control point, operation run and a 60-second bucket; observations for different defect types no longer conflict only because their top-level outcomes differ.

### Source line/station restrictions were too payload-dependent

Fixed by resolving scope through Item, OperationRun, RouteStep, Station and Equipment context. Scoped sources fail closed when required context cannot be resolved.

### Blast Radius approval stopped at proposal status

Fixed by materializing immutable `ContainmentApplication` facts only after the required human approval count is reached. Proposal creation itself still creates no defect and applies no containment.

The S18 scenario regression now derives automatic defect assignment from the persisted NCR count delta captured before and after Blast Radius analysis. An NCR that existed before the query is not attributed to Blast Radius.

### Audit chain fields existed without a complete write path

Fixed with a serialized HMAC-SHA256 audit chain and verification alongside raw-event integrity.

### HMAC source metadata and secret resolution were inconsistent

Fixed around `EventSource.key_id` and the external `SOURCE_HMAC_SECRETS_JSON` secret store. Secrets remain outside database rows.

### Runtime role authorization was not administratively manageable

Fixed with audited Role Capability Management backed by `RolePermission` in PostgreSQL. Effective permissions are resolved from the database on every request, so an already-issued access token sees a removal or restoration immediately. The admin API/UI exposes human-readable capabilities, protects the system `simulator_reader` role, requires a reason, records before/after/added/removed values, and rejects any role or user change that would remove the last enabled human `MANAGE_USERS` capability. Seed does not restore a permission removed from an existing role.

### Route revision import could activate a new revision without superseding the previous one

Fixed. Route JSON import is now a critical authenticated action, writes audit, and supersedes the prior active revision when `activate=true`.

### Load generator duplicated an envelope identifier in payload

Fixed. `scripts/generate_events.py` now emits canonical item registration with `item_id` only in the event envelope.

### Contract code generation did not include a TypeScript artifact or evolution proof

Fixed. The canonical JSON Schema now deterministically generates Pydantic models, TypeScript interfaces and the registry. An isolated 1.1 demonstration schema preserves the production 1.0 contract and adds only optional `analyzer_version` to `inspection.result`; fixture-based compatibility, generated drift and stale-output detection are checked without advertising 1.1 runtime support.

### Readiness and route coverage were difficult to inspect consistently

Fixed with the read-only TRACE-Q Doctor and Coverage Gap Analyzer. Doctor checks repository/environment shape, Compose/service state, health endpoints, migration head and contract drift without editing `.env`, migrations or data. The route analyzer reports uncovered product/route/defect/component combinations through the API and Streamlit without direct UI database access.

### Scaling correctness had no reproducible A/B proof

Fixed with a deterministic proof that writes one physical `load.jsonl`, records its SHA-256, and reuses the same bytes for 1-vs-N concurrent sender runs. Canonical projection and KPI hashes remove only declared volatile fields. The proof also compares actual 1-vs-N outbox workers, checks final business delivery uniqueness, and demonstrates persisted-backlog recovery. The 100-item profile is configured for CI; the 1000-item profile remains an explicit local proof rather than a per-push stress test.

### The hybrid checkpoint profile was metadata-only

Fixed with signer/key-provider abstractions and real optional ML-DSA-65 via pinned `liboqs-python`. ECDSA P-256 and ML-DSA-65 sign the same canonical checkpoint payload; hybrid verification requires both. Tests cover tamper of either signature, key rotation, unavailable historical keys, unavailable runtime and the absence of a silent classic fallback. Private key material remains in external keyrings, not PostgreSQL. The default stack remains independent of the optional PQ runtime.

### Scenario acceptance contained several hard-coded positive/negative flags

Strengthened. Projection failure, duplicate/idempotency behavior, Blast Radius automatic defect assignment, degraded-structure workflow continuity and S24 route pinning are derived from persisted runtime state instead of fixed constants.

Some negative architecture assertions still deliberately describe route availability rather than database state, for example the production absence of demo-only tamper behavior. Those are backed by code structure and separate security review rather than pretending that a Boolean literal is a database proof.

### Outbox worker did not reflect delivery failures in IntegrationHealth

Fixed. HTTP/network/invalid-ACK failures mark the integration unhealthy; a later valid ACK restores healthy state. A PostgreSQL integration test exercises the real `worker.process_one()` retry and delivery path with the same message ID.

### One HMAC test was tautological

Fixed by comparing the computed signature with a fixed known digest rather than comparing an expression with itself. Humanity survives another unit test that actually tests something.

## 3. Verified architecture boundaries

### Raw facts versus projections

Raw events are encrypted and append-only. Projections are rebuildable and may change after late evidence or invalidation. User decisions and analysis versions are separate records.

### Causality language

Machine warnings and operator actions are contextual evidence. They are not automatically promoted to proven root causes. Default NCR cause state remains `not_established`.

### Controlled outbound

Observation or automatic analysis cannot directly publish a final ERP quality result. The outbound path requires an authorized controller decision and, for rework, successful verification.

### External systems

One bidirectional integration is implemented against the ERP emulator. 1C, Galaktika and MES remain explicit fixture/adapter boundaries because no production customer contracts were supplied. KOMPAS remains behind the ProductStructureProvider boundary.

## 4. Automated verification expected on the final revision

The CI workflow is configured with five jobs. The statements below describe configuration and test scope; they do not claim that the current revision's remote workflow has completed successfully.

### unit-and-contracts

Checks:

- deterministic JSON Schema -> Pydantic/TypeScript/registry generation drift;
- isolated contract-evolution generated artifacts, complete schema delta, 1.0 inspection-fixture compatibility and stale-output detection;
- contract fixtures;
- non-PostgreSQL unit/security tests, including Doctor, coverage and RBAC unit proofs;
- ERP emulator tests;
- Python `compileall`.

### postgres-integration

Checks:

- migrations on PostgreSQL 16;
- restricted runtime role;
- demo seed;
- database append-only restrictions;
- full S01-S25 acceptance run through the real FastAPI/PostgreSQL stack;
- replay idempotency and dynamic RolePermission enforcement;
- Blast Radius approval/application;
- route import activation lifecycle;
- real outbox worker retry/ACK flow.

### scaling-smoke-proof

Creates a separate PostgreSQL service, migrates and seeds it, then runs the 100-item deterministic A/B ingestion, projection/KPI, multi-worker outbox and recovery proof. JSON and Markdown evidence are configured as a workflow artifact.

### pq-proof

Installs the optional PQ dependency in isolation, runs real ML-DSA-65 sign/verify/tamper smoke and the checkpoint tamper, rotation, unavailable-key and no-fallback test module. Default CI jobs do not require the PQ runtime.

### docker-demo-smoke

On PR/main, builds and starts the complete Compose demo stack:

- PostgreSQL;
- migrations;
- seed;
- FastAPI backend;
- outbox worker;
- ERP emulator;
- Streamlit.

It then runs `scripts/local_smoke.sh`, including backend readiness, before tearing the stack down.

## 5. Residual limitations, not hidden as completed features

These are not blockers for the hackathon MVP but must not be oversold.

### Real vendor transports

No real 1C/Galaktika/MES/KOMPAS customer endpoint, authentication scheme or schema was supplied. The repository therefore provides stable ports, mappings, fixtures/emulator and the KOMPAS provider boundary rather than invented production URLs.

### Post-quantum runtime

`HYBRID_PQ_V1` is implemented and has an isolated real-runtime proof, but remains optional and inactive in the default stack. This repository proof does not validate production key custody, HSM integration, deployment hardening or a cryptographic certification process.

### TLS termination

The local demo intentionally binds localhost ports. A production-like deployment still needs a real HTTPS boundary/reverse proxy and deployment secret management.

### Browser automation

CI verifies the Streamlit process health and backend/API behavior, but it does not run a full browser-click E2E suite. The manual UI path is documented in `docs/MODULE_TESTING.md`.

### Backup/restore destructive recovery

Scripts exist with an explicit restore confirmation guard, but the final pre-demo audit does not run a destructive backup/restore cycle against the demo database.

### Long-duration load benchmark

The final audit intentionally avoids a long stress benchmark. The bounded 100-item CI smoke and optional 1000-item local profile prove deterministic business outcomes, not production capacity or linear throughput scaling.

### Migration style debt

Some early hackathon migrations use current SQLAlchemy metadata with `create_all(checkfirst=True)` to support fresh installs and the existing upgrade path. CI is configured to test a clean database; this local documentation update does not claim that PostgreSQL job was rerun. A long-lived production release train should replace that pattern with fully explicit historical migrations.

## 6. Demo readiness decision

No code-level P0 blocker is currently identified in the reviewed scope. Demo readiness remains conditional on the checks below; this statement is not a substitute for a current CI run and manual verification.

Before presenting, require all of the following:

1. PR/main CI is green.
2. `docker compose ... up -d --build --wait` succeeds locally.
3. `bash scripts/local_smoke.sh` prints `TRACE-Q local smoke: OK`.
4. Run at least S03, S08, S17, S18, S19, S09 and S22 manually in Streamlit.
5. Do not claim real vendor integration, production PQ deployment validation or capacity results beyond the documented proof boundaries.

For exact commands see `docs/LOCAL_RUNBOOK.md`. For module-by-module manual checks see `docs/MODULE_TESTING.md`.
