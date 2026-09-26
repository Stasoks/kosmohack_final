from __future__ import annotations

import subprocess

from scripts.verify_final_improvements import (
    StepResult,
    execute_step,
    render_report,
    report_rows,
    selected_steps,
)


def test_acceptance_profiles_select_real_proof_steps() -> None:
    default = {step.key for step in selected_steps("default")}
    pq = {step.key for step in selected_steps("pq")}
    all_steps = {step.key for step in selected_steps("all")}

    assert default == {"compileall", "contracts", "unit", "postgres", "scaling", "docker"}
    assert pq == {"pq"}
    assert all_steps == default | pq

    scaling = next(step for step in selected_steps("default") if step.key == "scaling")
    assert "configs/scaling/smoke.json" in scaling.commands[0].argv
    assert "--recovery" in scaling.commands[0].argv

    postgres = next(step for step in selected_steps("default") if step.key == "postgres")
    assert postgres.commands[0].env["RUN_POSTGRES_TESTS"] == "1"
    assert ("-m", "postgres") == postgres.commands[0].argv[3:5]


def test_docker_step_always_cleans_up_after_start_attempt() -> None:
    docker = next(step for step in selected_steps("default") if step.key == "docker")
    calls: list[list[str]] = []

    def runner(argv, **_kwargs):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 1 if "up" in argv else 0)

    result = execute_step(docker, runner)

    assert result.status == "FAIL"
    assert "up" in calls[2]
    assert calls[-1][-3:] == ["down", "-v", "--remove-orphans"]
    assert "down" in calls[-1]


def test_report_maps_shared_suites_without_fake_feature_passes() -> None:
    results = [
        StepResult("compileall", "compileall", "PASS", "ok"),
        StepResult("contracts", "contracts", "PASS", "ok"),
        StepResult("unit", "unit", "PASS", "ok"),
        StepResult("postgres", "postgres", "FAIL", "database failed"),
        StepResult("scaling", "scaling", "PASS", "ok"),
        StepResult("docker", "docker", "PASS", "ok"),
    ]
    features, regression = report_rows("default", results)

    assert dict(features)["Replay Idempotency Fix"] == "FAIL"
    assert dict(features)["Role Capability Management"] == "FAIL"
    assert dict(features)["Hybrid PQ"] == "SKIP"
    assert dict(regression)["S01-S25"] == "FAIL"
    report = render_report("default", results)
    assert "OVERALL: FAIL" in report
    assert "postgres: database failed" in report


def test_pq_only_report_does_not_claim_unexecuted_features() -> None:
    report = render_report(
        "pq", [StepResult("pq", "hybrid PQ", "PASS", "all commands passed")]
    )

    assert "Hybrid PQ" in report and "PASS" in report
    assert "Replay Idempotency Fix" in report and "SKIP" in report
    assert "Regression" not in report
    assert report.endswith("OVERALL: PASS")
