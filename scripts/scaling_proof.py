from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import create_engine, func, select, text

from scripts.canonical_state_snapshot import (
    build_kpi_snapshot,
    build_state_snapshot,
    stable_hash,
)
from scripts.generate_load import generate


class ProofFailure(RuntimeError):
    pass


def _parse_positive_list(value: str, option: str) -> list[int]:
    try:
        result = [int(item.strip()) for item in value.split(",") if item.strip()]
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"{option} must be comma-separated integers") from exc
    if not result or any(item < 1 for item in result):
        raise argparse.ArgumentTypeError(f"{option} values must be positive")
    return result


def _write_dataset(profile: dict[str, Any], path: Path) -> tuple[list[dict[str, Any]], str]:
    events = list(generate(profile))
    payload = b"".join(
        json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        + b"\n"
        for row in events
    )
    path.write_bytes(payload)
    return events, hashlib.sha256(payload).hexdigest()


def _load_dataset(path: Path) -> tuple[list[dict[str, Any]], str]:
    payload = path.read_bytes()
    events = [json.loads(line) for line in payload.splitlines() if line.strip()]
    return events, hashlib.sha256(payload).hexdigest()


def _privileged_engine():
    from backend.app.settings import get_settings

    settings = get_settings()
    if not settings.demo_privileged_database_url:
        raise RuntimeError("DEMO_PRIVILEGED_DATABASE_URL is required for isolated A/B runs")
    return create_engine(settings.demo_privileged_database_url, future=True)


def _reset_business_data() -> None:
    from backend.app.scenarios.runtime import DEMO_TABLES

    engine = _privileged_engine()
    with engine.begin() as connection:
        connection.execute(
            text(f"TRUNCATE TABLE {', '.join(DEMO_TABLES)} RESTART IDENTITY CASCADE")
        )
        connection.execute(
            text(
                "UPDATE event_sources SET last_source_sequence = NULL "
                "WHERE source_id LIKE 'LOAD-%' OR source_id IN "
                "('VISION-02', 'MACHINE-01')"
            )
        )
    engine.dispose()


async def _send_dataset(
    events: list[dict[str, Any]], concurrency: int, token: str
) -> list[dict[str, Any]]:
    from backend.app.main import app

    semaphore = asyncio.Semaphore(concurrency)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://traceq.test") as client:
        async def send(event: dict[str, Any]) -> dict[str, Any]:
            async with semaphore:
                started = time.perf_counter()
                response = await client.post(
                    "/api/v1/events",
                    json=event,
                    headers={
                        "X-Source-Id": event["source"]["source_id"],
                        "X-Source-Token": token,
                    },
                    timeout=30,
                )
                elapsed_ms = (time.perf_counter() - started) * 1000
                if not response.is_success:
                    return {
                        "status": "failed",
                        "projection_status": "failed",
                        "status_code": response.status_code,
                        "body": response.text[:500],
                        "latency_ms": elapsed_ms,
                    }
                body = response.json()
                return {
                    "status": body.get("ingestion_status", "failed"),
                    "projection_status": body.get("projection_status"),
                    "status_code": response.status_code,
                    "latency_ms": elapsed_ms,
                }

        return list(await asyncio.gather(*(send(event) for event in events)))


def _database_result(
    *,
    concurrency: int,
    elapsed: float,
    statuses: list[dict[str, Any]],
    dataset_hash: str,
) -> dict[str, Any]:
    from backend.app.persistence.database import SessionLocal
    from backend.app.persistence.models import ProjectionState, RawEvent
    from backend.app.projections.rebuild import rebuild_item
    from backend.app.settings import get_settings

    db = SessionLocal()
    try:
        state = build_state_snapshot(db)
        kpi = build_kpi_snapshot(db)
        state_hash = stable_hash(state)
        kpi_hash = stable_hash(kpi)
        raw_unique_count = db.scalar(select(func.count(RawEvent.event_id))) or 0
        projection_failed = db.scalar(
            select(func.count(ProjectionState.item_id)).where(
                ProjectionState.status == "failed"
            )
        ) or 0
        projection_backlog = db.scalar(
            select(func.count(ProjectionState.item_id)).where(
                (ProjectionState.latest_raw_ingest_seq > ProjectionState.last_projected_ingest_seq)
                | (ProjectionState.status != "up_to_date")
            )
        ) or 0
        item_ids = list(db.scalars(select(ProjectionState.item_id).order_by(ProjectionState.item_id)).all())
        for item_id in item_ids:
            rebuild_item(db, item_id, get_settings())
        replay_hash = stable_hash(build_state_snapshot(db))
    finally:
        db.close()

    latencies = sorted(row["latency_ms"] for row in statuses)
    p95_index = int(0.95 * (len(latencies) - 1)) if latencies else 0
    return {
        "concurrent_senders": concurrency,
        "dataset_hash": dataset_hash,
        "raw_unique_count": raw_unique_count,
        "projection_hash": state_hash,
        "projection_hash_after_rebuild": replay_hash,
        "replay_stable": state_hash == replay_hash,
        "kpi_hash": kpi_hash,
        "kpi": kpi,
        "projection_failed": projection_failed,
        "projection_backlog": projection_backlog,
        "accepted": sum(row["status"] == "accepted" for row in statuses),
        "duplicates": sum(row["status"] == "duplicate" for row in statuses),
        "request_failures": sum(row["status"] == "failed" for row in statuses),
        "projection_response_failures": sum(
            row["projection_status"] == "failed" for row in statuses
        ),
        "elapsed_seconds": round(elapsed, 6),
        "events_per_second": round(len(statuses) / elapsed, 3) if elapsed else None,
        "p95_latency_ms": round(latencies[p95_index], 3) if latencies else None,
    }


def _run_ingestion_case(
    dataset_path: Path,
    concurrency: int,
    token: str,
) -> dict[str, Any]:
    events, dataset_hash = _load_dataset(dataset_path)
    _reset_business_data()
    started = time.perf_counter()
    statuses = asyncio.run(_send_dataset(events, concurrency, token))
    elapsed = time.perf_counter() - started
    return _database_result(
        concurrency=concurrency,
        elapsed=elapsed,
        statuses=statuses,
        dataset_hash=dataset_hash,
    )


def _reset_outbox() -> None:
    engine = _privileged_engine()
    with engine.begin() as connection:
        connection.execute(
            text(
                "TRUNCATE TABLE integration_messages, outbox_messages, "
                "security_alerts RESTART IDENTITY CASCADE"
            )
        )
    engine.dispose()


def _seed_outbox(count: int) -> list[str]:
    from backend.app.persistence.database import SessionLocal
    from backend.app.persistence.models import OutboxMessage, WorkerHeartbeat
    from backend.app.security.crypto import utcnow
    from worker import main as worker_main

    message_ids = [f"SCALE-OUTBOX-{index:04d}" for index in range(count)]
    db = SessionLocal()
    try:
        heartbeat = db.get(WorkerHeartbeat, worker_main.worker_id)
        if heartbeat is None:
            db.add(
                WorkerHeartbeat(
                    worker_id=worker_main.worker_id,
                    worker_type="outbox",
                    status="healthy",
                )
            )
        for message_id in message_ids:
            db.add(
                OutboxMessage(
                    message_id=message_id,
                    destination="erp-emulator",
                    message_type="quality_result",
                    payload={"message_id": message_id, "item_id": message_id},
                    state="PENDING",
                    attempts=0,
                    next_attempt_at=utcnow(),
                )
            )
        db.commit()
    finally:
        db.close()
    return message_ids


def _drain_outbox(worker_replicas: int) -> dict[str, Any]:
    from backend.app.persistence.database import SessionLocal
    from backend.app.persistence.models import IntegrationMessage, OutboxMessage, SecurityAlert
    from worker import main as worker_main

    delivered_calls: list[str] = []
    delivery_lock = threading.Lock()
    original_send = worker_main.EmulatorAdapter.send_quality_result

    def acknowledge(_adapter, payload: dict[str, Any]) -> dict[str, str]:
        with delivery_lock:
            delivered_calls.append(payload["message_id"])
        return {"message_id": payload["message_id"], "status": "ACK"}

    def replica() -> None:
        while worker_main.process_one():
            pass

    worker_main.EmulatorAdapter.send_quality_result = acknowledge
    try:
        with ThreadPoolExecutor(max_workers=worker_replicas) as pool:
            list(pool.map(lambda _: replica(), range(worker_replicas)))
    finally:
        worker_main.EmulatorAdapter.send_quality_result = original_send

    db = SessionLocal()
    try:
        outbox = db.scalars(select(OutboxMessage).order_by(OutboxMessage.message_id)).all()
        integration_ids = list(
            db.scalars(
                select(IntegrationMessage.message_id).where(
                    IntegrationMessage.status == "DELIVERED"
                )
            ).all()
        )
        invalid_ack_alerts = db.scalar(
            select(func.count(SecurityAlert.id)).where(
                SecurityAlert.alert_type == "INVALID_ACK"
            )
        ) or 0
        return {
            "worker_replicas": worker_replicas,
            "message_ids": [row.message_id for row in outbox],
            "states": {row.message_id: row.state for row in outbox},
            "attempts": {row.message_id: row.attempts for row in outbox},
            "delivery_calls": sorted(delivered_calls),
            "integration_message_ids": sorted(integration_ids),
            "all_delivered": bool(outbox) and all(row.state == "DELIVERED" for row in outbox),
            "duplicate_final_delivery": len(integration_ids) - len(set(integration_ids)),
            "duplicate_adapter_delivery": len(delivered_calls) - len(set(delivered_calls)),
            "invalid_ack_alerts": invalid_ack_alerts,
        }
    finally:
        db.close()


def _run_outbox_case(worker_replicas: int, count: int = 12) -> dict[str, Any]:
    _reset_outbox()
    expected = _seed_outbox(count)
    result = _drain_outbox(worker_replicas)
    result["expected_message_ids"] = expected
    result["message_id_stable"] = result["message_ids"] == expected
    return result


def _run_recovery_case(worker_replicas: int) -> dict[str, Any]:
    from backend.app.persistence.database import SessionLocal
    from backend.app.persistence.models import OutboxMessage

    _reset_outbox()
    expected = _seed_outbox(5)
    db = SessionLocal()
    try:
        before = list(
            db.scalars(
                select(OutboxMessage.message_id)
                .where(OutboxMessage.state == "PENDING")
                .order_by(OutboxMessage.message_id)
            ).all()
        )
    finally:
        db.close()
    drained = _drain_outbox(worker_replicas)
    return {
        "backlog_persisted_while_stopped": before == expected,
        "backlog_before": before,
        "message_ids_after": drained["message_ids"],
        "same_message_ids": drained["message_ids"] == expected,
        "all_delivered": drained["all_delivered"],
        "duplicate_final_delivery": drained["duplicate_final_delivery"],
        "duplicate_adapter_delivery": drained["duplicate_adapter_delivery"],
        "invalid_ack_alerts": drained["invalid_ack_alerts"],
    }


def build_report(
    *,
    profile_path: Path,
    dataset_path: Path,
    dataset_hash: str,
    events: list[dict[str, Any]],
    ingestion_runs: list[dict[str, Any]],
    outbox_runs: list[dict[str, Any]],
    recovery: dict[str, Any] | None,
) -> dict[str, Any]:
    unique_events = {row["event_id"]: row for row in events}
    expected_defects = len(
        {
            row["item_id"]
            for row in unique_events.values()
            if row["event_type"] == "inspection.result"
            and row["payload"]["inspection_result"] == "defect_detected"
        }
    )
    baseline = ingestion_runs[0]
    checks = {
        "same_physical_dataset_reused": all(
            row["dataset_hash"] == dataset_hash for row in ingestion_runs
        ),
        "raw_unique_count_match": all(
            row["raw_unique_count"] == len(unique_events) for row in ingestion_runs
        ),
        "projection_hash_match": all(
            row["projection_hash"] == baseline["projection_hash"]
            for row in ingestion_runs
        ),
        "kpi_hash_match": all(
            row["kpi_hash"] == baseline["kpi_hash"] for row in ingestion_runs
        ),
        "projection_failures_zero": all(
            row["projection_failed"] == 0
            and row["projection_response_failures"] == 0
            and row["request_failures"] == 0
            for row in ingestion_runs
        ),
        "projection_backlog_zero": all(
            row["projection_backlog"] == 0 for row in ingestion_runs
        ),
        "duplicate_kpi_inflation_zero": all(
            row["kpi"]["number_of_unique_defects"] == expected_defects
            and row["kpi"]["observed_defect_signals"] == expected_defects
            for row in ingestion_runs
        ),
        "repeated_rebuild_same_hash": all(row["replay_stable"] for row in ingestion_runs),
        "outbox_exactly_once_business_outcome": all(
            row["all_delivered"]
            and row["message_id_stable"]
            and row["duplicate_final_delivery"] == 0
            and row["duplicate_adapter_delivery"] == 0
            and row["invalid_ack_alerts"] == 0
            for row in outbox_runs
        ),
        "outbox_worker_counts_match": all(
            row["message_ids"] == outbox_runs[0]["message_ids"]
            for row in outbox_runs
        ),
    }
    if recovery is not None:
        checks["recovery_persists_and_drains_backlog"] = bool(
            recovery["backlog_persisted_while_stopped"]
            and recovery["same_message_ids"]
            and recovery["all_delivered"]
            and recovery["duplicate_final_delivery"] == 0
            and recovery["duplicate_adapter_delivery"] == 0
            and recovery["invalid_ack_alerts"] == 0
        )
    return {
        "proof": "TRACE-Q deterministic scalability proof",
        "profile": str(profile_path),
        "dataset": str(dataset_path),
        "dataset_sha256": dataset_hash,
        "physical_event_lines": len(events),
        "unique_event_ids": len(unique_events),
        "expected_unique_defects": expected_defects,
        "ingestion_runs": ingestion_runs,
        "outbox_runs": outbox_runs,
        "recovery": recovery,
        "checks": checks,
        "overall": "PASS" if all(checks.values()) else "FAIL",
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# TRACE-Q Scalability Proof",
        "",
        f"**Overall: {report['overall']}**",
        "",
        f"Dataset SHA-256: `{report['dataset_sha256']}`",
        f"Physical lines: {report['physical_event_lines']}; unique event IDs: {report['unique_event_ids']}.",
        "",
        "## Checks",
        "",
    ]
    lines.extend(
        f"- {'PASS' if passed else 'FAIL'} — `{name}`"
        for name, passed in report["checks"].items()
    )
    lines.extend(["", "## Ingestion", "", "| Senders | events/s | projection | KPI | replay |", "|---:|---:|---|---|---|"])
    for row in report["ingestion_runs"]:
        lines.append(
            f"| {row['concurrent_senders']} | {row['events_per_second']} | "
            f"`{row['projection_hash']}` | `{row['kpi_hash']}` | "
            f"{'PASS' if row['replay_stable'] else 'FAIL'} |"
        )
    lines.extend(["", "Throughput is measured for evidence; linear speedup is not a pass criterion.", ""])
    return "\n".join(lines)


def run(args: argparse.Namespace) -> dict[str, Any]:
    from backend.app.settings import get_settings

    profile = json.loads(args.profile.read_text(encoding="utf-8"))
    settings = get_settings()
    if not settings.demo_mode or not settings.source_demo_token:
        raise RuntimeError("Scaling proof requires DEMO_MODE=true and SOURCE_DEMO_TOKEN")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    dataset_path = args.output_dir / "load.jsonl"
    events, dataset_hash = _write_dataset(profile, dataset_path)

    ingestion_runs = [
        _run_ingestion_case(
            dataset_path,
            concurrency,
            settings.source_demo_token.get_secret_value(),
        )
        for concurrency in args.concurrency
    ]
    outbox_runs = [
        _run_outbox_case(worker_replicas) for worker_replicas in args.outbox_workers
    ]
    recovery = (
        _run_recovery_case(max(args.outbox_workers)) if args.recovery else None
    )
    report = build_report(
        profile_path=args.profile,
        dataset_path=dataset_path,
        dataset_hash=dataset_hash,
        events=events,
        ingestion_runs=ingestion_runs,
        outbox_runs=outbox_runs,
        recovery=recovery,
    )
    (args.output_dir / "scaling-proof.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (args.output_dir / "scaling-proof.md").write_text(
        render_markdown(report), encoding="utf-8"
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the TRACE-Q deterministic scalability proof")
    parser.add_argument("--profile", type=Path, default=Path("configs/scaling/smoke.json"))
    parser.add_argument("--concurrency", default="1,2")
    parser.add_argument("--outbox-workers", default="1,2")
    parser.add_argument("--recovery", action="store_true")
    parser.add_argument("--output-dir", type=Path, default=Path("tmp/scaling-proof"))
    args = parser.parse_args()
    args.concurrency = _parse_positive_list(args.concurrency, "--concurrency")
    args.outbox_workers = _parse_positive_list(args.outbox_workers, "--outbox-workers")

    try:
        report = run(args)
    except ProofFailure as exc:
        print(f"scaling proof failed: {exc}")
        return 1
    except Exception as exc:
        print(f"scaling proof internal error: {type(exc).__name__}: {exc}")
        return 2
    print(render_markdown(report))
    return 0 if report["overall"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
