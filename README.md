# TRACE-Q

TRACE-Q is an event-driven MVP for quality control and traceability of physical products. It keeps the encrypted source history separate from rebuildable projections, explains each Defect Birth Window through stored evidence, and leaves the final quality verdict to an authorized controller.

## Architecture

```text
Browser → Streamlit → FastAPI → PostgreSQL 16
                         ↕
                    ERP Emulator
                         ↑
                    Outbox worker
```

Streamlit never connects to PostgreSQL. Authentication, RBAC, event validation, replay, decisions, integration, audit, and integrity checks are enforced by FastAPI and PostgreSQL.

## Quick start (demo only)

Requirements: Docker with Compose, approximately 1 GB free RAM, and ports `8501`, `8080`, `8090`, and debug-only `55432` available on localhost.

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

Log in as any demo user and open **Scenario Runner**. The runner executes the same S01-S25 acceptance bundles used by PostgreSQL CI, including optional action/request/ERP/tamper/route files, then compares normalized business state with `expected.json`.

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
- [Pre-demo audit report](docs/AUDIT_REPORT.md)
- [Assumptions and limitations](docs/assumptions.md)

## Current assumptions and boundaries

- Input observations are structured results from external VisionQC/OperatorVision systems; TRACE-Q contains no proprietary CV model.
- Synthetic identifiers and parameters are not industrial validation data.
- Root cause is never established automatically.
- The JSON product-structure provider keeps item-level QC operational when component structure is unavailable.
- Real 1C, Galaktika, MES, and KOMPAS transports require site-specific API details and credentials; the business-facing ports and fixture adapters are present without invented vendor URLs.

## Completed hardening scope

The canonical envelope owns `item_id` and `operation_run_id`; payloads do not duplicate them. Items pin a RouteRevision at registration. Source Registry supports lifecycle status, event/line/station scopes, legacy shared secrets and HMAC_V1 nonce replay protection. Server-side sessions revoke access immediately for critical actions. Rework requires a completed rework run, trusted repeat GOOD and controller verification before controlled outbound release. Evidence invalidation, Blast Radius proposals with separation of duties, S01-S25 Harness V2, occurrence-based KPI, security alerts, isolated test compose and optional hybrid-PQ profile metadata are included.

The CI workflow executes unit/contract tests, PostgreSQL integration tests, the full S01-S25 acceptance runner, Python compilation, and a bounded Docker Compose demo smoke test.
