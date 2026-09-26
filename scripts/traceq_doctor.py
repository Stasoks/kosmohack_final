from __future__ import annotations

import argparse
import base64
import json
import os
import re
import socket
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Iterable


COMPOSE_FILES = ("compose.yaml", "compose.demo.yaml")
REPO_MARKERS = (
    "compose.yaml",
    "compose.demo.yaml",
    ".env.example",
    "pyproject.toml",
    "backend",
    "streamlit_app",
)
SERVICE_NAMES = (
    "postgres",
    "migrate",
    "seed",
    "backend",
    "worker",
    "streamlit",
    "erp-emulator",
    "factory-simulator",
)
REQUIRED_VAR_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*):\?[^}]*}")


@dataclass(frozen=True)
class CheckResult:
    check: str
    status: str
    message: str


def parse_env_text(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def required_compose_vars(compose_texts: Iterable[str]) -> set[str]:
    return {
        match.group(1)
        for text in compose_texts
        for match in REQUIRED_VAR_PATTERN.finditer(text)
    }


def _decoded_length(value: str) -> int | None:
    try:
        return len(base64.b64decode(value, validate=True))
    except (ValueError, TypeError):
        return None


def secret_shape_checks(env: dict[str, str]) -> list[CheckResult]:
    checks: list[CheckResult] = []
    aes_length = _decoded_length(env.get("AES_DATA_KEY_B64", ""))
    checks.append(
        CheckResult(
            "secret:AES_DATA_KEY_B64",
            "PASS" if aes_length == 32 else "FAIL",
            "valid 32-byte base64 key" if aes_length == 32 else "must be valid base64 decoding to 32 bytes",
        )
    )
    hmac_length = _decoded_length(env.get("INTEGRITY_HMAC_KEY_B64", ""))
    checks.append(
        CheckResult(
            "secret:INTEGRITY_HMAC_KEY_B64",
            "PASS" if hmac_length is not None and hmac_length >= 32 else "FAIL",
            "valid base64 key of at least 32 bytes"
            if hmac_length is not None and hmac_length >= 32
            else "must be valid base64 decoding to at least 32 bytes",
        )
    )
    jwt_length = len(env.get("JWT_SIGNING_SECRET", ""))
    checks.append(
        CheckResult(
            "secret:JWT_SIGNING_SECRET",
            "PASS" if jwt_length >= 32 else "FAIL",
            "length is at least 32 characters" if jwt_length >= 32 else "must contain at least 32 characters",
        )
    )
    return checks


def env_drift_checks(example: dict[str, str], actual: dict[str, str]) -> list[CheckResult]:
    missing = sorted(set(example) - set(actual))
    extra = sorted(set(actual) - set(example))
    checks = [
        CheckResult(
            "environment:example-keys",
            "FAIL" if missing else "PASS",
            f"missing keys: {', '.join(missing)}" if missing else "all example keys are present",
        )
    ]
    if extra:
        checks.append(
            CheckResult(
                "environment:extra-keys",
                "WARN",
                f"additional local keys: {', '.join(extra)}",
            )
        )
    return checks


def parse_compose_ps(output: str) -> list[dict[str, Any]]:
    stripped = output.strip()
    if not stripped:
        return []
    try:
        value = json.loads(stripped)
        return value if isinstance(value, list) else [value]
    except json.JSONDecodeError:
        return [json.loads(line) for line in stripped.splitlines() if line.strip()]


def service_state_checks(rows: Iterable[dict[str, Any]]) -> list[CheckResult]:
    by_service = {
        str(row.get("Service") or row.get("service") or ""): row for row in rows
    }
    checks: list[CheckResult] = []
    for service in SERVICE_NAMES:
        row = by_service.get(service)
        if row is None:
            checks.append(CheckResult(f"service:{service}", "FAIL", "service is absent"))
            continue
        state = str(row.get("State") or row.get("state") or "").lower()
        health = str(row.get("Health") or row.get("health") or "").lower()
        exit_code = row.get("ExitCode", row.get("exit_code"))
        if service in {"migrate", "seed"}:
            passed = state == "exited" and int(exit_code or 0) == 0
            checks.append(
                CheckResult(
                    f"service:{service}",
                    "PASS" if passed else "FAIL",
                    "completed successfully" if passed else "must be Exited 0",
                )
            )
            continue
        passed = state == "running" and health not in {"unhealthy", "starting"}
        checks.append(
            CheckResult(
                f"service:{service}",
                "PASS" if passed else "FAIL",
                "running" if passed else f"state={state or 'unknown'}, health={health or 'unknown'}",
            )
        )
    return checks


CommandRunner = Callable[..., subprocess.CompletedProcess[str]]


def _command_check(
    name: str,
    command: list[str],
    *,
    cwd: Path,
    runner: CommandRunner,
    unavailable_is_skip: bool = False,
) -> CheckResult:
    try:
        result = runner(
            command,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return CheckResult(name, "SKIP" if unavailable_is_skip else "FAIL", "command unavailable")
    if result.returncode == 0:
        return CheckResult(name, "PASS", "command completed successfully")
    combined = f"{result.stdout}\n{result.stderr}"
    if unavailable_is_skip and (
        "ModuleNotFoundError" in combined or "No module named" in combined
    ):
        return CheckResult(name, "SKIP", "host dependency unavailable")
    return CheckResult(name, "FAIL", f"command returned exit code {result.returncode}")


def _port_is_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(0.15)
        return probe.connect_ex(("127.0.0.1", port)) == 0


def run_preflight(
    root: Path,
    *,
    runner: CommandRunner = subprocess.run,
    port_checker: Callable[[int], bool] = _port_is_open,
) -> list[CheckResult]:
    checks: list[CheckResult] = []
    missing_markers = [name for name in REPO_MARKERS if not (root / name).exists()]
    checks.append(
        CheckResult(
            "repository:root",
            "FAIL" if missing_markers else "PASS",
            f"missing: {', '.join(missing_markers)}" if missing_markers else "repository markers found",
        )
    )
    checks.append(
        _command_check("docker:cli", ["docker", "--version"], cwd=root, runner=runner)
    )
    checks.append(
        _command_check(
            "docker:compose", ["docker", "compose", "version"], cwd=root, runner=runner
        )
    )

    env_path = root / ".env"
    if not env_path.exists():
        checks.append(CheckResult("environment:file", "FAIL", ".env is missing"))
        return checks
    checks.append(CheckResult("environment:file", "PASS", ".env is present"))
    actual = parse_env_text(env_path.read_text(encoding="utf-8"))
    example = parse_env_text((root / ".env.example").read_text(encoding="utf-8"))
    checks.extend(env_drift_checks(example, actual))

    compose_texts = [
        (root / name).read_text(encoding="utf-8")
        for name in COMPOSE_FILES
        if (root / name).exists()
    ]
    required = required_compose_vars(compose_texts)
    missing_required = sorted(key for key in required if not actual.get(key))
    checks.append(
        CheckResult(
            "environment:compose-required",
            "FAIL" if missing_required else "PASS",
            f"missing required keys: {', '.join(missing_required)}"
            if missing_required
            else "all required Compose variables are set",
        )
    )
    checks.extend(secret_shape_checks(actual))
    checks.append(
        _command_check(
            "compose:config",
            [
                "docker",
                "compose",
                "-f",
                "compose.yaml",
                "-f",
                "compose.demo.yaml",
                "config",
                "-q",
            ],
            cwd=root,
            runner=runner,
        )
    )
    ports = {
        "database": int(actual.get("TRACEQ_DB_DEBUG_PORT", "55432")),
        "backend": int(actual.get("TRACEQ_API_PORT", "8080")),
        "streamlit": int(actual.get("TRACEQ_UI_PORT", "8501")),
        "erp": int(actual.get("TRACEQ_ERP_PORT", "8090")),
        "simulator": int(actual.get("TRACEQ_SIMULATOR_PORT", "8070")),
    }
    for name, port in ports.items():
        occupied = port_checker(port)
        checks.append(
            CheckResult(
                f"port:{name}",
                "WARN" if occupied else "PASS",
                f"port {port} is already occupied" if occupied else f"port {port} is available",
            )
        )
    return checks


def _http_check(name: str, url: str, headers: dict[str, str] | None = None) -> CheckResult:
    request = urllib.request.Request(url, headers=headers or {}, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=3) as response:
            response.read()
            status = response.status
    except (urllib.error.URLError, TimeoutError, OSError):
        return CheckResult(name, "FAIL", "endpoint is unavailable")
    return CheckResult(
        name,
        "PASS" if 200 <= status < 300 else "FAIL",
        f"HTTP {status}",
    )


def _http_json(
    name: str, url: str, headers: dict[str, str] | None = None
) -> tuple[CheckResult, dict[str, Any] | None]:
    request = urllib.request.Request(url, headers=headers or {}, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=3) as response:
            payload = json.loads(response.read())
            status = response.status
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError):
        return CheckResult(name, "FAIL", "endpoint is unavailable or returned invalid JSON"), None
    check = CheckResult(
        name,
        "PASS" if 200 <= status < 300 else "FAIL",
        f"HTTP {status}",
    )
    return check, payload if isinstance(payload, dict) else None


def alembic_revision_check(current_output: str, heads_output: str) -> CheckResult:
    revision_pattern = re.compile(r"\b[0-9A-Za-z_]+\b")
    current = revision_pattern.findall(current_output)
    heads = revision_pattern.findall(heads_output)
    matches = bool(current and heads and current[0] == heads[0])
    return CheckResult(
        "database:alembic-revision",
        "PASS" if matches else "FAIL",
        "database is at the migration head" if matches else "database revision differs from head",
    )


def run_live(
    root: Path,
    *,
    runner: CommandRunner = subprocess.run,
    environ: dict[str, str] | None = None,
) -> list[CheckResult]:
    env = dict(os.environ if environ is None else environ)
    file_env = (
        parse_env_text((root / ".env").read_text(encoding="utf-8"))
        if (root / ".env").exists()
        else {}
    )
    checks: list[CheckResult] = []
    compose = [
        "docker",
        "compose",
        "-f",
        "compose.yaml",
        "-f",
        "compose.demo.yaml",
    ]
    try:
        ps = runner(
            [*compose, "ps", "--all", "--format", "json"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return [CheckResult("compose:services", "FAIL", "Docker Compose is unavailable")]
    if ps.returncode != 0:
        return [CheckResult("compose:services", "FAIL", "unable to read service state")]
    try:
        checks.extend(service_state_checks(parse_compose_ps(ps.stdout)))
    except (json.JSONDecodeError, TypeError, ValueError):
        checks.append(CheckResult("compose:services", "FAIL", "invalid Compose state output"))

    api_port = int(file_env.get("TRACEQ_API_PORT", "8080"))
    checks.extend(
        [
            _http_check("http:backend-live", f"http://127.0.0.1:{api_port}/health/live"),
            _http_check("http:backend-ready", f"http://127.0.0.1:{api_port}/health/ready"),
            _http_check(
                "http:erp",
                f"http://127.0.0.1:{int(file_env.get('TRACEQ_ERP_PORT', '8090'))}/health",
            ),
            _http_check(
                "http:streamlit",
                f"http://127.0.0.1:{int(file_env.get('TRACEQ_UI_PORT', '8501'))}/_stcore/health",
            ),
            _http_check(
                "http:simulator",
                f"http://127.0.0.1:{int(file_env.get('TRACEQ_SIMULATOR_PORT', '8070'))}/health",
            ),
        ]
    )

    try:
        current = runner(
            [*compose, "exec", "-T", "backend", "alembic", "current"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        heads = runner(
            [*compose, "exec", "-T", "backend", "alembic", "heads"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        if current.returncode == 0 and heads.returncode == 0:
            checks.append(alembic_revision_check(current.stdout, heads.stdout))
        else:
            checks.append(
                CheckResult("database:alembic-revision", "FAIL", "could not read revisions")
            )
    except (OSError, subprocess.TimeoutExpired):
        checks.append(
            CheckResult("database:alembic-revision", "FAIL", "command unavailable")
        )
    for name, command in (
        ("contracts:generated", [sys.executable, "scripts/generate_contracts.py", "--check"]),
        ("contracts:evolution", [sys.executable, "scripts/check_contract_evolution.py"]),
        ("contracts:fixtures", [sys.executable, "scripts/check_contract_fixtures.py"]),
    ):
        checks.append(
            _command_check(
                name,
                command,
                cwd=root,
                runner=runner,
                unavailable_is_skip=True,
            )
        )

    token = env.get("TRACEQ_DOCTOR_BEARER_TOKEN")
    if token:
        headers = {"Authorization": f"Bearer {token}"}
        data_health_check, data_health = _http_json(
            "api:data-health",
            f"http://127.0.0.1:{api_port}/api/v1/analytics/data-health",
            headers,
        )
        checks.append(data_health_check)
        if data_health is not None:
            projection_failed = int((data_health.get("projections") or {}).get("failed", 0))
            problems = data_health.get("problem_items") or []
            checks.append(
                CheckResult(
                    "api:projection-health",
                    "PASS" if projection_failed == 0 and not problems else "FAIL",
                    "all projections are current"
                    if projection_failed == 0 and not problems
                    else "one or more projections require attention",
                )
            )
            outbox = data_health.get("outbox") or {}
            terminal_failures = int(outbox.get("FAILED", 0)) + int(outbox.get("DEAD", 0))
            checks.append(
                CheckResult(
                    "api:outbox-health",
                    "PASS" if terminal_failures == 0 else "FAIL",
                    "no terminal outbox failures"
                    if terminal_failures == 0
                    else "terminal outbox failures are present",
                )
            )
            workers = data_health.get("worker_heartbeats") or []
            workers_ok = bool(workers) and all(
                str(row.get("status") or "").upper() in {"RUNNING", "HEALTHY"}
                for row in workers
            )
            checks.append(
                CheckResult(
                    "api:worker-heartbeat",
                    "PASS" if workers_ok else "FAIL",
                    "worker heartbeat is healthy" if workers_ok else "healthy worker heartbeat is absent",
                )
            )
        checks.append(
            _http_check(
                "api:integration-health",
                f"http://127.0.0.1:{api_port}/api/v1/integrations",
                headers,
            )
        )
    else:
        checks.append(
            CheckResult(
                "api:authenticated-health",
                "SKIP",
                "set TRACEQ_DOCTOR_BEARER_TOKEN for read-only authenticated API checks",
            )
        )
    return checks


def summarize(results: Iterable[CheckResult]) -> tuple[str, int]:
    statuses = {result.status for result in results}
    if "FAIL" in statuses:
        return "NOT READY", 1
    if statuses & {"WARN", "SKIP"}:
        return "READY WITH WARNINGS", 0
    return "READY", 0


def _render_text(mode: str, results: list[CheckResult], overall: str) -> str:
    lines = [f"TRACE-Q Doctor · {mode}", ""]
    lines.extend(
        f"[{result.status:4}] {result.check}: {result.message}" for result in results
    )
    lines.extend(["", f"OVERALL: {overall}"])
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only TRACE-Q environment diagnostics")
    parser.add_argument("--mode", choices=("preflight", "live", "all"), default="preflight")
    parser.add_argument("--json", action="store_true", dest="json_output")
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parents[1]
    try:
        results: list[CheckResult] = []
        if args.mode in {"preflight", "all"}:
            results.extend(run_preflight(root))
        if args.mode in {"live", "all"}:
            results.extend(run_live(root))
        overall, exit_code = summarize(results)
        if args.json_output:
            print(
                json.dumps(
                    {
                        "tool": "TRACE-Q Doctor",
                        "mode": args.mode,
                        "overall": overall,
                        "exit_code": exit_code,
                        "checks": [asdict(result) for result in results],
                    },
                    ensure_ascii=False,
                )
            )
        else:
            print(_render_text(args.mode, results, overall))
        return exit_code
    except Exception as exc:
        if args.json_output:
            print(
                json.dumps(
                    {
                        "tool": "TRACE-Q Doctor",
                        "mode": args.mode,
                        "overall": "INTERNAL ERROR",
                        "exit_code": 2,
                        "error": type(exc).__name__,
                    }
                )
            )
        else:
            print(f"TRACE-Q Doctor internal error: {type(exc).__name__}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
