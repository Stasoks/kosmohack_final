.PHONY: install test test-unit test-integration generate-contracts check-contracts check-contract-evolution up down logs

install:
	uv sync --all-groups

test: test-unit
	@echo "Prefer ./scripts/run_tests.sh all for the complete isolated suite"

test-unit:
	uv run pytest -m "not postgres"

test-integration:
	RUN_POSTGRES_TESTS=1 TRACEQ_TEST_DATABASE_URL="${TRACEQ_TEST_DATABASE_URL}" uv run pytest -m postgres

generate-contracts:
	uv run python scripts/generate_contracts.py

check-contracts:
	uv run python scripts/generate_contracts.py --check
	uv run python scripts/check_contract_fixtures.py
	uv run python scripts/generate_contracts.py --check --schema contracts/events/evolution/canonical-event-1.1-demo.schema.json --output-dir contracts/events/evolution/generated
	uv run python scripts/check_contract_evolution.py

check-contract-evolution:
	uv run python scripts/generate_contracts.py --check --schema contracts/events/evolution/canonical-event-1.1-demo.schema.json --output-dir contracts/events/evolution/generated
	uv run python scripts/check_contract_evolution.py

up:
	docker compose -f compose.yaml -f compose.demo.yaml up --build

down:
	docker compose -f compose.yaml -f compose.demo.yaml down

logs:
	docker compose -f compose.yaml -f compose.demo.yaml logs -f
