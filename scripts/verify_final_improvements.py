from __future__ import annotations

import argparse
import os
import shlex
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Sequence


ROOT = Path(__file__).resolve().parents[1]
PYTHON = sys.executable
COMPOSE = (
    "docker",
    "compose",
    "-f",
    "compose.yaml",
    "-f",
    "compose.demo.yaml",
)


@dataclass(frozen=True)
class Command:
    argv: tuple[str, ...]
    timeout: int
    env: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Step:
    key: str
    label: str
    commands: tuple[Command, ...]
    cleanup: Command | None = None
    cleanup_after: int | None = None


@dataclass(frozen=True)
class StepResult:
    key: str
    label: str
    status: str
    detail: str


CommandRunner = Callable[..., subprocess.CompletedProcess[str]]


def _command(*argv: str, timeout: int = 180, env: dict[str, str] | None = None) -> Command:
    return Command(tuple(argv), timeout, env or {})


def _default_steps() -> tuple[Step, ...]:
    unit_env = {"DEMO_MODE": "false", "SOURCE_DEMO_TOKEN": ""}
    postgres_env = {"RUN_POSTGRES_TESTS": "1"}
    compose_env = {"COMPOSE_PROJECT_NAME": f"traceq-acceptance-{os.getpid()}"}
    compose = (*COMPOSE,)
    return (
        Step(
            "compileall",
            "compileall",
            (
                _command(
                    PYTHON,
                    "-m",
                    "compileall",
                    "-q",
                    "backend",
                    "erp_emulator",
                    "factory_simulator",
                    "worker",
                    "streamlit_app",
                    "scripts",
                    "shared_contracts",
                    timeout=120,
                ),
            ),
        ),
        Step(
            "contracts",
            "contracts",
            (
                _command(PYTHON, "scripts/generate_contracts.py", "--check", timeout=60),
                _command(
                    PYTHON,
                    "scripts/generate_contracts.py",
                    "--check",
                    "--schema",
                    "contracts/events/evolution/canonical-event-1.1-demo.schema.json",
                    "--output-dir",
                    "contracts/events/evolution/generated",
                    timeout=60,
                ),
                _command(PYTHON, "scripts/check_contract_evolution.py", timeout=60),
                _command(PYTHON, "scripts/check_contract_fixtures.py", timeout=60),
            ),
        ),
        Step(
            "unit",
            "unit",
            (
                _command(
                    PYTHON,
                    "-m",
                    "pytest",
                    "-m",
                    "not postgres and not pq",
                    "-q",
                    timeout=240,
                    env=unit_env,
                ),
            ),
        ),
        Step(
            "postgres",
            "postgres / S01-S25",
            (
                _command(
                    PYTHON,
                    "-m",
                    "pytest",
                    "-m",
                    "postgres",
                    "backend/tests",
                    "-q",
                    timeout=420,
                    env=postgres_env,
                ),
            ),
        ),
        Step(
            "scaling",
            "scaling smoke",
            (
                _command(
                    PYTHON,
                    "scripts/scaling_proof.py",
                    "--profile",
                    "configs/scaling/smoke.json",
                    "--concurrency",
                    "1,2",
                    "--outbox-workers",
                    "1,2",
                    "--recovery",
                    timeout=300,
                ),
            ),
        ),
        Step(
            "docker",
            "docker demo smoke",
            (
                _command(
                    PYTHON,
                    "scripts/traceq_doctor.py",
                    "--mode",
                    "preflight",
                    "--json",
                    timeout=90,
                    env=compose_env,
                ),
                _command(*compose, "config", "-q", timeout=60, env=compose_env),
                _command(*compose, "up", "-d", "--build", "--wait", timeout=240, env=compose_env),
                _command("bash", "scripts/local_smoke.sh", timeout=60, env=compose_env),
                _command(
                    PYTHON,
                    "scripts/traceq_doctor.py",
                    "--mode",
                    "live",
                    "--json",
                    timeout=120,
                    env=compose_env,
                ),
            ),
            cleanup=_command(
                *compose,
                "down",
                "-v",
                "--remove-orphans",
                timeout=120,
                env=compose_env,
            ),
            cleanup_after=2,
        ),
    )


def _pq_step() -> Step:
    return Step(
        "pq",
        "hybrid PQ",
        (
            _command(PYTHON, "scripts/pq_smoke.py", timeout=180),
            _command(
                PYTHON,
                "-m",
                "pytest",
                "backend/tests/test_checkpoint_security.py",
                "-q",
                timeout=240,
            ),
        ),
    )


def selected_steps(profile: str) -> tuple[Step, ...]:
    if profile == "default":
        return _default_steps()
    if profile == "pq":
        return (_pq_step(),)
    if profile == "all":
        return (*_default_steps(), _pq_step())
    raise ValueError(f"unknown profile: {profile}")


def _run_command(command: Command, runner: CommandRunner) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment.update(command.env)
    print(f"$ {shlex.join(command.argv)}", flush=True)
    return runner(
        list(command.argv),
        cwd=ROOT,
        env=environment,
        timeout=command.timeout,
        check=False,
    )


def execute_step(step: Step, runner: CommandRunner = subprocess.run) -> StepResult:
    cleanup_armed = False
    result = StepResult(step.key, step.label, "PASS", "all commands passed")
    try:
        for index, command in enumerate(step.commands):
            if step.cleanup_after == index:
                cleanup_armed = True
            try:
                completed = _run_command(command, runner)
            except subprocess.TimeoutExpired:
                result = StepResult(
                    step.key,
                    step.label,
                    "FAIL",
                    f"timed out after {command.timeout}s: {shlex.join(command.argv)}",
                )
                break
            except OSError as exc:
                result = StepResult(
                    step.key,
                    step.label,
                    "FAIL",
                    f"could not start {command.argv[0]}: {exc}",
                )
                break
            if completed.returncode != 0:
                result = StepResult(
                    step.key,
                    step.label,
                    "FAIL",
                    f"exit {completed.returncode}: {shlex.join(command.argv)}",
                )
                break
    finally:
        if cleanup_armed and step.cleanup is not None:
            try:
                cleanup = _run_command(step.cleanup, runner)
                if cleanup.returncode != 0 and result.status == "PASS":
                    result = StepResult(
                        step.key,
                        step.label,
                        "FAIL",
                        f"cleanup exited {cleanup.returncode}",
                    )
            except (OSError, subprocess.TimeoutExpired) as exc:
                if result.status == "PASS":
                    result = StepResult(
                        step.key,
                        step.label,
                        "FAIL",
                        f"cleanup failed: {type(exc).__name__}",
                    )
    return result


def run_profile(
    profile: str,
    runner: CommandRunner = subprocess.run,
) -> list[StepResult]:
    return [execute_step(step, runner) for step in selected_steps(profile)]


def _combined_status(results: dict[str, StepResult], keys: Iterable[str]) -> str:
    values = [results[key].status for key in keys if key in results]
    if not values:
        return "SKIP"
    if "FAIL" in values:
        return "FAIL"
    return "PASS"


def report_rows(
    profile: str,
    step_results: Sequence[StepResult],
) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    results = {result.key: result for result in step_results}
    features = [
        ("Replay Idempotency Fix", _combined_status(results, ("postgres",))),
        ("Doctor", _combined_status(results, ("unit", "docker"))),
        ("Coverage Gap Analyzer", _combined_status(results, ("unit",))),
        ("Role Capability Management", _combined_status(results, ("unit", "postgres"))),
        ("Scalability Proof", _combined_status(results, ("scaling",))),
        ("Hybrid PQ", _combined_status(results, ("pq",))),
    ]
    regression = [
        ("compileall", _combined_status(results, ("compileall",))),
        ("contracts", _combined_status(results, ("contracts",))),
        ("unit", _combined_status(results, ("unit",))),
        ("postgres", _combined_status(results, ("postgres",))),
        ("S01-S25", _combined_status(results, ("postgres",))),
        ("docker demo smoke", _combined_status(results, ("docker",))),
    ]
    if profile == "pq":
        regression = []
    return features, regression


def render_report(profile: str, step_results: Sequence[StepResult]) -> str:
    features, regression = report_rows(profile, step_results)
    statuses = [status for _, status in (*features, *regression) if status != "SKIP"]
    overall = "FAIL" if "FAIL" in statuses or not statuses else "PASS"
    lines = ["TRACE-Q FINAL IMPROVEMENTS", ""]
    width = max(len(label) for label, _ in features)
    lines.extend(f"{label:<{width}}  {status}" for label, status in features)
    if regression:
        lines.extend(["", "Regression"])
        regression_width = max(len(label) for label, _ in regression)
        lines.extend(
            f"  {label:<{regression_width}}  {status}"
            for label, status in regression
        )
    failures = [result for result in step_results if result.status == "FAIL"]
    if failures:
        lines.extend(["", "Failures"])
        lines.extend(f"  {result.label}: {result.detail}" for result in failures)
    lines.extend(["", f"OVERALL: {overall}"])
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the real TRACE-Q final reliability and security proofs"
    )
    profiles = parser.add_mutually_exclusive_group(required=True)
    profiles.add_argument("--default", action="store_const", const="default", dest="profile")
    profiles.add_argument("--pq", action="store_const", const="pq", dest="profile")
    profiles.add_argument("--all", action="store_const", const="all", dest="profile")
    args = parser.parse_args(argv)
    try:
        results = run_profile(args.profile)
        print("\n" + render_report(args.profile, results))
        return 1 if any(result.status == "FAIL" for result in results) else 0
    except Exception as exc:
        print(f"TRACE-Q final runner internal error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
