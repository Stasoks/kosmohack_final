.PHONY: install test test-unit test-integration generate-contracts check-contracts up down logs

install:
	uv sync --all-groups

test: test-unit
	@echo "Prefer ./scripts/run_tests.sh all for the complete isolated suite"

test-unit:
	uv run pytest -m "not postgres"

test-integration:
	TRACEQ_TEST_DATABASE_URL="$${TRACEQ_TEST_DATABASE_URL}" uv run pytest -m postgres

generate-contracts:
	uv run python scripts/generate_contracts.py

check-contracts:
	uv run python scripts/generate_contracts.py --check
	uv run python scripts/check_contract_fixtures.py

up:
	docker compose -f compose.yaml -f compose.demo.yaml up --build

down:
	docker compose -f compose.yaml -f compose.demo.yaml down

logs:
	docker compose -f compose.yaml -f compose.demo.yaml logs -f
