from __future__ import annotations

import argparse, json, random, uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path


def generate(profile: dict):
    rng = random.Random(profile["seed"])
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    for index in range(profile["items"]):
        item = f"LOAD-{index:08d}"
        source = f"LOAD-MES-{index % profile['sources'] + 1:02d}"
        event = {"event_id": str(uuid.UUID(int=rng.getrandbits(128))), "event_type": "item.registered",
                 "schema_version": "1.0", "occurred_at": (base + timedelta(seconds=index)).isoformat(),
                 "source": {"source_id": source, "source_type": "mes", "sequence": index},
                 "item_id": item, "operation_run_id": None,
                 "payload": {"product_definition_id": "PD-TRACE-01", "revision": "A", "line_id": "LINE-A", "route_id": "ROUTE-DEFAULT"}}
        yield event
        if rng.random() < profile["duplicate_probability"]: yield dict(event)
        defect = rng.random() < profile["defect_probability"]
        inspected_at = base + timedelta(seconds=index + (3600 if rng.random() < profile["late_probability"] else 2))
        inspection = {"event_id": str(uuid.UUID(int=rng.getrandbits(128))), "event_type": "inspection.result",
            "schema_version": "1.0", "occurred_at": inspected_at.isoformat(),
            "source": {"source_id": "VISION-02", "source_type": "vision_qc", "sequence": index},
            "item_id": item, "operation_run_id": None,
            "payload": {"inspection_result": "defect_detected" if defect else "no_defect", "observation_quality": "good",
                "control_point_id": "CP-FINAL", "defects": [{"defect_type": "LOAD_DEFECT"}] if defect else [],
                "evidence_refs": [], "control_device_id": "LOAD-CAMERA"}}
        yield inspection
        if rng.random() < profile["warning_probability"]:
            yield {"event_id": str(uuid.UUID(int=rng.getrandbits(128))), "event_type": "machine.state", "schema_version": "1.0",
                   "occurred_at": inspected_at.isoformat(), "source": {"source_id": "MACHINE-01", "source_type": "machine_logs", "sequence": index},
                   "item_id": item, "operation_run_id": None, "payload": {"equipment_id": "EQ-LATHE-01", "state": "warning", "code": "LOAD-WARN"}}


def main():
    parser = argparse.ArgumentParser(); parser.add_argument("--profile", default="configs/load_profile.json"); parser.add_argument("--output", required=True)
    args = parser.parse_args(); profile = json.loads(Path(args.profile).read_text(encoding="utf-8"))
    Path(args.output).write_text("".join(json.dumps(row, separators=(",", ":")) + "\n" for row in generate(profile)), encoding="utf-8")


if __name__ == "__main__": main()
