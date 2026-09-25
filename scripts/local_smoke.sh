#!/usr/bin/env bash
set -Eeuo pipefail

api="${TRACEQ_API_BASE:-http://127.0.0.1:8080}"
erp="${TRACEQ_ERP_BASE:-http://127.0.0.1:8090}"
ui="${TRACEQ_UI_BASE:-http://127.0.0.1:8501}"

printf 'Backend live: '
curl --fail --silent --show-error "${api}/health/live"
printf '\nBackend ready: '
curl --fail --silent --show-error "${api}/health/ready"
printf '\nERP emulator: '
curl --fail --silent --show-error "${erp}/health"
printf '\nStreamlit: '
curl --fail --silent --show-error "${ui}/_stcore/health"
printf '\nTRACE-Q local smoke: OK\n'
