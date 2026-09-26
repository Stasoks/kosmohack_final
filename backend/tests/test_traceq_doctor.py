from __future__ import annotations

import base64
import json
import subprocess
from pathlib import Path

import pytest

from scripts import traceq_doctor as doctor


VALID_ENV = {
    "POSTGRES_OWNER_PASSWORD": "owner-password",
    "POSTGRES_APP_PASSWORD": "app-password",
    "JWT_SIGNING_SECRET": "j" * 32,
    "AES_DATA_KEY_B64": base64.b64encode(b"a" * 32).decode(),
    "INTEGRITY_HMAC_KEY_B64": base64.b64encode(b"h" * 32).decode(),
}


def _write_root(root: Path, env: dict[str, str] | None = None) -> None:
    for name in doctor.REPO_MARKERS:
        path = root / name
        if "." in name:
            path.write_text("", encoding="utf-8")
        else:
            path.mkdir()
    (root / "compose.yaml").write_text(
        "password: ${POSTGRES_OWNER_PASSWORD:?required}\n"
        "app: ${POSTGRES_APP_PASSWORD:?required}\n",
        encoding="utf-8",
    )
    (root / "compose.demo.yaml").write_text("services: {}\n", encoding="utf-8")
    example = env or VALID_ENV
    (root / ".env.example").write_text(
        "\n".join(f"{key}={value}" for key, value in example.items()) + "\n",
        encoding="utf-8",
    )
    if env is not None:
        (root / ".env").write_text(
            "\n".join(f"{key}={value}" for key, value in env.items()) + "\n",
            encoding="utf-8",
        )


def _runner(*, compose_exit: int = 0):
    def run(command, **_kwargs):
        return_code = (
            compose_exit
            if command[-2:] == ["config", "-q"]
            else 0
        )
        return subprocess.CompletedProcess(command, return_code, "ok", "secret stderr")

    return run


def test_missing_env_is_a_preflight_blocker(tmp_path: Path) -> None:
    _write_root(tmp_path)

    results = doctor.run_preflight(
        tmp_path, runner=_runner(), port_checker=lambda _port: False
    )

    env_check = next(row for row in results if row.check == "environment:file")
    assert env_check.status == "FAIL"
    assert doctor.summarize(results) == ("NOT READY", 1)


def test_missing_required_var_and_environment_drift_are_reported(tmp_path: Path) -> None:
    actual = {key: value for key, value in VALID_ENV.items() if key != "POSTGRES_APP_PASSWORD"}
    _write_root(tmp_path, actual)
    (tmp_path / ".env.example").write_text(
        "\n".join(f"{key}={value}" for key, value in VALID_ENV.items()) + "\n",
        encoding="utf-8",
    )

    results = doctor.run_preflight(
        tmp_path, runner=_runner(), port_checker=lambda _port: False
    )

    assert next(
        row for row in results if row.check == "environment:example-keys"
    ).status == "FAIL"
    assert next(
        row for row in results if row.check == "environment:compose-required"
    ).status == "FAIL"


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("AES_DATA_KEY_B64", "not-base64"),
        ("AES_DATA_KEY_B64", base64.b64encode(b"short").decode()),
        ("INTEGRITY_HMAC_KEY_B64", "not-base64"),
    ],
)
def test_invalid_secret_shapes_fail_without_echoing_values(key: str, value: str) -> None:
    env = {**VALID_ENV, key: value}

    results = doctor.secret_shape_checks(env)
    rendered = json.dumps([doctor.asdict(row) for row in results])

    assert next(row for row in results if row.check == f"secret:{key}").status == "FAIL"
    assert value not in rendered


def test_extra_environment_key_is_a_non_blocking_warning() -> None:
    results = doctor.env_drift_checks(VALID_ENV, {**VALID_ENV, "LOCAL_ONLY": "value"})

    assert results[0].status == "PASS"
    assert results[1].status == "WARN"
    assert doctor.summarize(results) == ("READY WITH WARNINGS", 0)


def test_compose_config_failure_is_a_blocker(tmp_path: Path) -> None:
    _write_root(tmp_path, VALID_ENV)

    results = doctor.run_preflight(
        tmp_path, runner=_runner(compose_exit=1), port_checker=lambda _port: False
    )

    check = next(row for row in results if row.check == "compose:config")
    assert check.status == "FAIL"
    assert "secret stderr" not in check.message


def test_occupied_preflight_port_is_a_warning(tmp_path: Path) -> None:
    _write_root(tmp_path, VALID_ENV)

    results = doctor.run_preflight(
        tmp_path, runner=_runner(), port_checker=lambda port: port == 8080
    )

    assert next(row for row in results if row.check == "port:backend").status == "WARN"
    assert doctor.summarize(results)[1] == 0


def test_compose_service_states_accept_jobs_exited_zero_and_reject_unhealthy() -> None:
    rows = [
        {"Service": "migrate", "State": "exited", "ExitCode": 0},
        {"Service": "seed", "State": "exited", "ExitCode": 0},
        {"Service": "postgres", "State": "running", "Health": "healthy"},
        {"Service": "backend", "State": "running", "Health": "unhealthy"},
        {"Service": "worker", "State": "running", "Health": ""},
        {"Service": "streamlit", "State": "running", "Health": "healthy"},
        {"Service": "erp-emulator", "State": "running", "Health": "healthy"},
        {"Service": "factory-simulator", "State": "running", "Health": "healthy"},
    ]

    results = doctor.service_state_checks(rows)

    assert next(row for row in results if row.check == "service:migrate").status == "PASS"
    assert next(row for row in results if row.check == "service:seed").status == "PASS"
    assert next(row for row in results if row.check == "service:backend").status == "FAIL"


def test_json_cli_output_is_parseable_and_never_contains_secrets(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        doctor,
        "run_preflight",
        lambda _root: doctor.secret_shape_checks(VALID_ENV),
    )

    exit_code = doctor.main(["--mode", "preflight", "--json"])
    output = capsys.readouterr().out
    value = json.loads(output)

    assert exit_code == 0
    assert value["overall"] == "READY"
    assert value["checks"]
    assert all(secret not in output for secret in VALID_ENV.values())


def test_parse_compose_ps_accepts_json_lines() -> None:
    rows = doctor.parse_compose_ps(
        '{"Service":"migrate","State":"exited","ExitCode":0}\n'
        '{"Service":"backend","State":"running","Health":"healthy"}\n'
    )

    assert [row["Service"] for row in rows] == ["migrate", "backend"]


def test_alembic_current_must_equal_heads() -> None:
    assert doctor.alembic_revision_check(
        "20260926_0005 (head)\n", "20260926_0005 (head)\n"
    ).status == "PASS"
    assert doctor.alembic_revision_check(
        "20260926_0004\n", "20260926_0005 (head)\n"
    ).status == "FAIL"
    assert doctor.ALEMBIC_CURRENT_SHELL == (
        'MIGRATION_DATABASE_URL="$DATABASE_URL" alembic current'
    )
