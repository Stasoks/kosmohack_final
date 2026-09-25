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

The final acceptance gate is GitHub Actions on PR #1. A revision is considered demo-ready only when all applicable jobs are green.

## 2. P0/P1 issues found and fixed during hardening

### PostgreSQL tests were capable of silently skipping

Fixed by explicitly enabling `RUN_POSTGRES_TESTS=1` in CI/test execution and seeding an isolated PostgreSQL database before the integration suite.

### Scenario fixtures existed without being real end-to-end acceptance tests

Fixed by connecting ScenarioHarness V2 to the FastAPI demo endpoint and a PostgreSQL-backed runtime. S01-S25 now execute events plus optional actions, requests, ERP behavior, tamper actions, analysis requests and route changes.

### Rework verification could accept an unrelated GOOD

Fixed. Repeat GOOD must be trusted and cover the original defect type/component scope. Item-level NCRs require item-wide component coverage rather than a check scoped only to one component.

### Source line/station restrictions were too payload-dependent

Fixed by resolving scope through Item, OperationRun, RouteStep, Station and Equipment context. Scoped sources fail closed when required context cannot be resolved.

### Blast Radius approval stopped at proposal status

Fixed by materializing immutable `ContainmentApplication` facts only after the required human approval count is reached. Proposal creation itself still creates no defect and applies no containment.

### Audit chain fields existed without a complete write path

Fixed with a serialized HMAC-SHA256 audit chain and verification alongside raw-event integrity.

### HMAC source metadata and secret resolution were inconsistent

Fixed around `EventSource.key_id` and the external `SOURCE_HMAC_SECRETS_JSON` secret store. Secrets remain outside database rows.

### Route revision import could activate a new revision without superseding the previous one

Fixed. Route JSON import is now a critical authenticated action, writes audit, and supersedes the prior active revision when `activate=true`.

### Load generator duplicated an envelope identifier in payload

Fixed. `scripts/generate_events.py` now emits canonical item registration with `item_id` only in the event envelope.

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

The CI gate contains three jobs.

### unit-and-contracts

Checks:

- deterministic JSON Schema -> Pydantic generation drift;
- contract fixtures;
- non-PostgreSQL unit/security tests;
- ERP emulator tests;
- Python `compileall`.

### postgres-integration

Checks:

- migrations on PostgreSQL 16;
- restricted runtime role;
- demo seed;
- database append-only restrictions;
- full S01-S25 acceptance run through the real FastAPI/PostgreSQL stack;
- Blast Radius approval/application;
- route import activation lifecycle;
- real outbox worker retry/ACK flow.

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

`HYBRID_PQ_V1` is an optional architecture/profile boundary. ML-DSA-65 runtime signing/verification is not part of the default tested stack. The tested path is classical AES-256-GCM + HMAC-SHA256, with ECDSA-P256 checkpoint support when a key is provisioned.

### TLS termination

The local demo intentionally binds localhost ports. A production-like deployment still needs a real HTTPS boundary/reverse proxy and deployment secret management.

### Browser automation

CI verifies the Streamlit process health and backend/API behavior, but it does not run a full browser-click E2E suite. The manual UI path is documented in `docs/MODULE_TESTING.md`.

### Backup/restore destructive recovery

Scripts exist with an explicit restore confirmation guard, but the final pre-demo audit does not run a destructive backup/restore cycle against the demo database.

### Long-duration load benchmark

The final audit intentionally avoids a long stress benchmark. Small load tooling is available, while correctness and deterministic acceptance are prioritized before the presentation.

### Migration style debt

Some early hackathon migrations use current SQLAlchemy metadata with `create_all(checkfirst=True)` to support fresh installs and the existing upgrade path. The current revision is tested from a clean database, but a long-lived production release train should replace that pattern with fully explicit historical migrations.

## 6. Demo readiness decision

No known P0 blocker remains in the reviewed code after the fixes above.

Before presenting, require all of the following:

1. PR/main CI is green.
2. `docker compose ... up -d --build --wait` succeeds locally.
3. `bash scripts/local_smoke.sh` prints `TRACE-Q local smoke: OK`.
4. Run at least S03, S08, S17, S18, S19, S09 and S22 manually in Streamlit.
5. Do not claim real vendor integration or verified ML-DSA runtime beyond the documented boundary.

For exact commands see `docs/LOCAL_RUNBOOK.md`. For module-by-module manual checks see `docs/MODULE_TESTING.md`.
