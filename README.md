# TRACE-Q

TRACE-Q is an event-driven MVP for quality control and traceability of physical products. It keeps the encrypted source history separate from rebuildable projections, explains each Defect Birth Window through stored evidence, and leaves the final quality verdict to an authorized controller.

## Architecture

```text
Browser → Streamlit → FastAPI → PostgreSQL 16
             ↕           ↑
       Factory Simulator ┘ (demo only)
                         ↕
                    ERP Emulator
                         ↑
                    Outbox worker
```

Streamlit never connects to PostgreSQL. Authentication, RBAC, event validation, replay, decisions, integration, audit, and integrity checks are enforced by FastAPI and PostgreSQL.

## Quick start (demo only)

Requirements: Docker with Compose, approximately 1 GB free RAM, and ports `8501`, `8080`, `8070`, `8090`, and debug-only `55432` available on localhost.

```bash
cp -n .env.example .env
docker compose -f compose.yaml -f compose.demo.yaml up -d --build --wait
bash scripts/local_smoke.sh
```

Open <http://localhost:8501>. API documentation is available in demo mode at <http://localhost:8080/docs>.

The values below are deliberately non-production credentials from `.env.example`:

| Role | Username | Password |
|---|---|---|
| Quality controller | `controller` | `controller-demo` |
| Area master | `master` | `master-demo` |
| Technologist | `technologist` | `technologist-demo` |
| Production manager | `manager` | `manager-demo` |
| Administrator | `admin` | `admin-demo` |

Never reuse these credentials or the demo crypto keys outside the demo profile. With `DEMO_MODE=false`, known demo secrets are rejected during startup.

## Demo scenarios

Log in as any demo user and open **Приёмочные сценарии**. The runner executes the same S01-S25 acceptance bundles used by PostgreSQL CI, including optional action/request/ERP/tamper/route files, then compares normalized business state with `expected.json`.

For a continuously controlled route-driven flow, open **Симуляция производства**. This separate demo service sends canonical MES/Vision/equipment events through the public ingestion API and waits for real controller decisions in TRACE-Q. See [live simulator](docs/LIVE_FACTORY_SIMULATOR.md) and [simulator testing](docs/SIMULATOR_TESTING.md).

Users with `VIEW_ANALYTICS` see a near-real-time quality dashboard at the top of **Обзор**. It polls the read-only `GET /api/v1/analytics/live-quality` endpoint every two seconds and keeps trusted GOOD, defect signals, human-confirmed NCR, equipment warnings, rework and release visibly separate. See [realtime dashboard](docs/REALTIME_DASHBOARD.md).

Useful demo points: `S03` shows a bounded Defect Birth Window, `S08` runs controller decision → rework → repeat inspection → release, `S19` demonstrates stable-message-ID outbox retry, and `S09` demonstrates tamper detection. See [docs/scenarios.md](docs/scenarios.md).

## Tests and contracts

```bash
./scripts/run_tests.sh unit
./scripts/run_tests.sh postgres
./scripts/run_tests.sh scenarios
./scripts/run_tests.sh security
./scripts/run_tests.sh contracts
./scripts/run_tests.sh all
```

PostgreSQL integration tests use `TRACEQ_TEST_DATABASE_URL`; SQLite is intentionally not a supported integration fallback. CI also regenerates the Pydantic event models from the canonical JSON Schema in check mode, validates all 133 contract fixtures, runs S01-S25 through the real demo API, and performs a bounded Docker Compose demo smoke test.

The read-only environment Doctor and the unified final proof runner are available from the repository root:

```bash
python scripts/traceq_doctor.py --mode preflight
python scripts/traceq_doctor.py --mode live
python scripts/verify_final_improvements.py --default
```

`--default` requires the documented isolated PostgreSQL test environment and Docker. It runs the existing replay, Doctor, coverage, RBAC, scaling, contract, unit, PostgreSQL, S01-S25 and bounded demo-stack proofs. The optional real ML-DSA-65 proof is isolated behind `uv sync --extra pq` and `python scripts/verify_final_improvements.py --pq`; `--all` combines both profiles.

## What to show during review

1. Item timeline with trusted GOOD, operation, warning, and trusted DEFECT.
2. Bounded Defect Birth Window and its boundary/context/limitation evidence.
3. `cause_status = not_established`: a machine warning is context, not an automatic root cause.
4. Append-only controller decision committed while ERP is unavailable.
5. Outbox retry with the same `message_id`, followed by ERP ACK.
6. Late event creating AnalysisVersion v2.
7. Admin-only tamper and integrity verification failure.

## Documentation

- [Architecture](docs/architecture.md)
- [Domain model](docs/domain.md)
- [Events and contracts](docs/events.md)
- [Quality analysis](docs/quality-analysis.md)
- [Routes](docs/routes.md)
- [Integrations](docs/integrations.md)
- [Security](docs/security.md)
- [Scenarios](docs/scenarios.md)
- [5–7 minute demo](docs/demo.md)
- [Vision-control design](docs/vision-control-design.md)
- [Current limitations](docs/limitations.md)
- [Recovery](docs/recovery.md)
- [Local runbook](docs/LOCAL_RUNBOOK.md)
- [Module testing guide](docs/MODULE_TESTING.md)
- [Live factory simulator](docs/LIVE_FACTORY_SIMULATOR.md)
- [Simulator testing](docs/SIMULATOR_TESTING.md)
- [Realtime quality dashboard](docs/REALTIME_DASHBOARD.md)
- [Deterministic scalability proof](docs/SCALING_PROOF.md)
- [Pre-demo audit report](docs/AUDIT_REPORT.md)
- [Assumptions and limitations](docs/assumptions.md)

## Current assumptions and boundaries

- Input observations are structured results from external VisionQC/OperatorVision systems; TRACE-Q contains no proprietary CV model.
- Synthetic identifiers and parameters are not industrial validation data.
- Root cause is never established automatically.
- The JSON product-structure provider keeps item-level QC operational when component structure is unavailable.
- Real 1C, Galaktika, MES, and KOMPAS transports require site-specific API details and credentials; the business-facing ports and fixture adapters are present without invented vendor URLs.

## Completed hardening scope

The canonical envelope owns `item_id` and `operation_run_id`; payloads do not duplicate them. Items pin a RouteRevision at registration. Source Registry supports lifecycle status, event/line/station scopes, legacy shared secrets and HMAC_V1 nonce replay protection. Server-side sessions revoke access immediately for critical actions. Runtime role capabilities are stored in PostgreSQL, editable through an audited admin API/UI, and protected against removing the final enabled human `MANAGE_USERS` capability. Rework requires a completed rework run, trusted repeat GOOD and controller verification before controlled outbound release. Evidence invalidation, Blast Radius proposals with separation of duties, S01-S25 Harness V2, occurrence-based KPI, route coverage-gap analysis, deterministic scaling/outbox recovery proofs, security alerts and isolated test compose are included.

Hybrid checkpoints are a real optional runtime: ECDSA P-256 and ML-DSA-65 sign the same canonical checkpoint payload and both must verify. The default stack does not install the PQ dependency or activate the hybrid profile; the isolated `pq-proof` job exercises real signing, tamper detection, rotation and no-fallback behavior.

CI is configured to execute unit/contract tests, PostgreSQL integration tests with S01-S25, a deterministic scaling smoke proof, the isolated PQ proof, Python compilation, and a bounded Docker Compose demo smoke test. This description is configuration, not a claim that an unobserved workflow run passed for the current revision.
