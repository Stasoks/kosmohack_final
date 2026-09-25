# TRACE-Q local runbook

This is the shortest path from a clean checkout to a working demo stack.

## 1. Requirements

- Docker Engine with Docker Compose v2
- Git
- Free ports: `8501`, `8080`, `8090`, and demo-only PostgreSQL port `55432`
- The demo stack is intentionally self-contained. A local Python/uv installation is not required just to run the application.

## 2. First start

From the repository root:

```bash
git pull --ff-only
cp -n .env.example .env
docker compose -f compose.yaml -f compose.demo.yaml up -d --build --wait
bash scripts/local_smoke.sh
```

If `.env` already exists, `cp -n` leaves it untouched.

Successful smoke output must include:

- backend `/health/live` -> alive
- backend `/health/ready` -> ready
- ERP emulator -> healthy
- Streamlit health -> ok
- final line: `TRACE-Q local smoke: OK`

## 3. URLs

- Streamlit UI: http://localhost:8501
- FastAPI Swagger: http://localhost:8080/docs
- Backend readiness: http://localhost:8080/health/ready
- ERP emulator health: http://localhost:8090/health
- Debug PostgreSQL: `127.0.0.1:55432`

## 4. Demo users

| Role | Username | Password |
|---|---|---|
| Quality controller | `controller` | `controller-demo` |
| Area master | `master` | `master-demo` |
| Technologist | `technologist` | `technologist-demo` |
| Production manager | `manager` | `manager-demo` |
| Administrator | `admin` | `admin-demo` |

These credentials are demo-only and come from `.env.example`.

## 5. Everyday commands

Show status:

```bash
docker compose -f compose.yaml -f compose.demo.yaml ps
```

Follow all logs:

```bash
docker compose -f compose.yaml -f compose.demo.yaml logs -f
```

Backend logs only:

```bash
docker compose -f compose.yaml -f compose.demo.yaml logs -f backend
```

Worker/outbox logs only:

```bash
docker compose -f compose.yaml -f compose.demo.yaml logs -f worker
```

Stop without deleting PostgreSQL data:

```bash
docker compose -f compose.yaml -f compose.demo.yaml down
```

Start again without rebuilding:

```bash
docker compose -f compose.yaml -f compose.demo.yaml up -d --wait
```

Rebuild after code changes:

```bash
docker compose -f compose.yaml -f compose.demo.yaml up -d --build --wait
```

## 6. Clean reset

The Scenario Runner has its own demo reset and should be preferred while testing scenarios.

If the whole local environment has become dirty after manual role/route/database experiments, reset the Docker volume:

```bash
docker compose -f compose.yaml -f compose.demo.yaml down -v --remove-orphans
docker compose -f compose.yaml -f compose.demo.yaml up -d --build --wait
bash scripts/local_smoke.sh
```

This deletes the local demo database. Do not use `down -v` on a database whose contents you want to keep.

## 7. Quick automated tests

If Python 3.12 and `uv` are installed:

```bash
uv sync --all-groups
./scripts/run_tests.sh unit
./scripts/run_tests.sh contracts
./scripts/run_tests.sh security
```

The PostgreSQL suite requires an isolated test database. The easiest Docker-backed sequence is:

```bash
docker compose -f compose.test.yaml down -v --remove-orphans
docker compose -f compose.test.yaml up -d --build postgres-test
docker compose -f compose.test.yaml run --rm migrate-test
docker compose -f compose.test.yaml run --rm seed-test
docker compose -f compose.test.yaml run --rm postgres-tests
docker compose -f compose.test.yaml down -v --remove-orphans
```

The PostgreSQL suite includes the real S01-S25 acceptance run through FastAPI and PostgreSQL.

## 8. If startup fails

### A port is already occupied

Check:

```bash
ss -ltnp | grep -E ':8501|:8080|:8090|:55432'
```

Either stop the conflicting process or override demo ports in `.env`, for example:

```text
TRACEQ_UI_PORT=18501
TRACEQ_API_PORT=18080
TRACEQ_ERP_PORT=18090
TRACEQ_DB_DEBUG_PORT=55433
```

### Backend is alive but not ready

Run:

```bash
curl -fsS http://127.0.0.1:8080/health/ready
docker compose -f compose.yaml -f compose.demo.yaml logs migrate seed backend
```

The expected migration at this revision is `20260926_0004`.

### Login fails after manual experiments

Use the clean reset from section 6. Seeding is idempotent, but manual changes to demo users/roles are deliberately not silently erased on every start.

### ERP/outbox looks stuck

Check:

```bash
docker compose -f compose.yaml -f compose.demo.yaml logs -f worker erp-emulator
```

Then open Streamlit -> Data Health / Administration -> Integrations. Outbox states should be `PENDING`, `RETRYING`, `FAILED`, or `DELIVERED`.

## 9. Before a presentation

Run these four commands:

```bash
docker compose -f compose.yaml -f compose.demo.yaml up -d --build --wait
bash scripts/local_smoke.sh
docker compose -f compose.yaml -f compose.demo.yaml ps
curl -fsS http://127.0.0.1:8080/health/ready
```

Then open Streamlit and execute the short demo sequence from `docs/MODULE_TESTING.md`.
