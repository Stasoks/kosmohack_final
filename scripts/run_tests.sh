#!/usr/bin/env bash
set -Eeuo pipefail

mode="${1:-all}"
export ENVIRONMENT=test
export TRACEQ_TEST_DATABASE_URL="${TRACEQ_TEST_DATABASE_URL:-postgresql+psycopg://traceq_test:traceq_test@127.0.0.1:55433/traceq_test}"

section() { printf '\n== TRACE-Q: %s ==\n' "$1"; }
unit() { section unit; uv run pytest -m "not postgres" backend/tests erp_emulator/tests; }
postgres() { section postgres; RUN_POSTGRES_TESTS=1 uv run pytest -m postgres backend/tests; }
scenarios() { section scenarios; uv run pytest backend/tests/test_scenarios_v2.py; }
security() { section security; uv run pytest backend/tests/test_security.py backend/tests/test_security_extensions.py; }
contracts() {
  section contracts
  uv run python scripts/generate_contracts.py --check
  uv run python scripts/check_contract_fixtures.py
}

case "$mode" in
  unit) unit ;; postgres) postgres ;; scenarios) scenarios ;; security) security ;;
  contracts) contracts ;;
  all) contracts; unit; security; scenarios; postgres ;;
  *) echo "Usage: $0 {unit|postgres|scenarios|security|contracts|all}" >&2; exit 64 ;;
esac
