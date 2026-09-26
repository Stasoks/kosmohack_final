from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from scripts.canonical_state_snapshot import canonical_json_bytes, normalize, stable_hash
from scripts.generate_load import generate
from scripts.scaling_proof import build_report, render_markdown


ROOT = Path(__file__).resolve().parents[2]


def test_scaling_proof_direct_cli_help_runs_from_repository_root() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/scaling_proof.py", "--help"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "--outbox-workers" in result.stdout


def test_canonical_snapshot_direct_cli_help_runs_from_repository_root() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/canonical_state_snapshot.py", "--help"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "--output" in result.stdout


def test_scaling_dataset_is_reused_byte_for_byte() -> None:
    profile = {
        "seed": 42,
        "items": 10,
        "sources": 2,
        "duplicate_probability": 0.2,
        "late_probability": 0.1,
        "defect_probability": 0.3,
        "warning_probability": 0.1,
    }
    first = b"".join(canonical_json_bytes(row) + b"\n" for row in generate(profile))
    second = b"".join(canonical_json_bytes(row) + b"\n" for row in generate(profile))

    assert first == second
    assert stable_hash(first.hex()) == stable_hash(second.hex())


def test_canonical_normalization_ignores_only_declared_volatile_noise() -> None:
    base = {
        "item_id": "ITEM-1",
        "status": "IN_PROCESS",
        "created_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
        "recalculated_at": "first",
        "trust_reasons": ["B", "A"],
    }
    noisy = {**base, "created_at": "different", "recalculated_at": "second"}

    assert stable_hash(base) == stable_hash(noisy)
    assert normalize(base)["trust_reasons"] == ["A", "B"]


def test_meaningful_business_change_changes_canonical_hash() -> None:
    before = {"item_id": "ITEM-1", "status": "IN_PROCESS", "trust": "TRUSTED"}
    after = {**before, "status": "REWORK_REQUIRED"}

    assert stable_hash(before) != stable_hash(after)


def test_scaling_profiles_are_valid_and_bounded() -> None:
    for name, items in (("smoke", 100), ("standard", 1000)):
        profile = json.loads(
            Path(f"configs/scaling/{name}.json").read_text(encoding="utf-8")
        )
        assert profile["items"] == items
        assert profile["sources"] <= 10


def test_scaling_report_is_json_and_markdown_parseable(tmp_path: Path) -> None:
    run = {
        "dataset_hash": "a" * 64,
        "raw_unique_count": 2,
        "projection_hash": "b" * 64,
        "projection_hash_after_rebuild": "b" * 64,
        "replay_stable": True,
        "kpi_hash": "c" * 64,
        "kpi": {"number_of_unique_defects": 0, "observed_defect_signals": 0},
        "projection_failed": 0,
        "projection_backlog": 0,
        "projection_response_failures": 0,
        "request_failures": 0,
        "concurrent_senders": 1,
        "events_per_second": 1.0,
    }
    outbox = {
        "all_delivered": True,
        "message_id_stable": True,
        "duplicate_final_delivery": 0,
        "duplicate_adapter_delivery": 0,
        "invalid_ack_alerts": 0,
        "message_ids": ["M1"],
    }
    events = [
        {"event_id": "E1", "event_type": "item.registered", "item_id": "I1"},
        {
            "event_id": "E2",
            "event_type": "inspection.result",
            "item_id": "I1",
            "payload": {"inspection_result": "no_defect"},
        },
    ]
    report = build_report(
        profile_path=Path("profile.json"),
        dataset_path=tmp_path / "load.jsonl",
        dataset_hash="a" * 64,
        events=events,
        ingestion_runs=[run],
        outbox_runs=[outbox],
        recovery=None,
    )

    assert json.loads(json.dumps(report))["overall"] == "PASS"
    markdown = render_markdown(report)
    assert "**Overall: PASS**" in markdown
    assert "Throughput is measured" in markdown
