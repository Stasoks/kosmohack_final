from __future__ import annotations

import argparse
import json
import random
import sys
import time
from datetime import datetime, timedelta, timezone
from itertools import count
from typing import Any, Iterable

import httpx


def event_stream(sources: int, items: int, duplicate_rate: float, late_rate: float, loss_rate: float, seed: int) -> Iterable[dict[str, Any]]:
    rng = random.Random(seed)
    sequence = [count(1) for _ in range(sources)]
    base = datetime.now(timezone.utc).replace(microsecond=0)
    history: list[dict[str, Any]] = []
    for item_number in range(1, items + 1):
        item_id = f"LOAD-ITEM-{item_number:06d}"
        source_number = item_number % sources
        source_id = f"LOAD-MES-{source_number + 1:02d}"
        occurred_at = base + timedelta(milliseconds=item_number * 10)
        event = {
            "event_id": f"LOAD-E-{item_number:08d}",
            "event_type": "item.registered",
            "schema_version": "1.0",
            "occurred_at": occurred_at.isoformat().replace("+00:00", "Z"),
            "source": {
                "source_id": source_id,
                "source_type": "mes",
                "sequence": next(sequence[source_number]),
            },
            "item_id": item_id,
            "payload": {
                "product_definition_id": "PD-TRACE-01",
                "revision": "A",
                "line_id": "LINE-A" if item_number % 2 else "LINE-B",
                "route_id": "ROUTE-DEFAULT",
            },
        }
        if rng.random() >= loss_rate:
            history.append(event)
            yield event
        if history and rng.random() < duplicate_rate:
            yield dict(rng.choice(history))
        if history and rng.random() < late_rate:
            late = dict(rng.choice(history))
            late["event_id"] = late["event_id"] + f"-L{item_number}"
            late["occurred_at"] = (occurred_at - timedelta(minutes=5)).isoformat().replace("+00:00", "Z")
            late["source"] = dict(late["source"])
            late["source"]["sequence"] = next(sequence[source_number])
            yield late


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate reproducible TRACE-Q event load")
    parser.add_argument("--sources", type=int, default=5)
    parser.add_argument("--items", type=int, default=100)
    parser.add_argument("--events-per-second", type=float, default=20)
    parser.add_argument("--duplicate-rate", type=float, default=0.02)
    parser.add_argument("--late-rate", type=float, default=0.03)
    parser.add_argument("--loss-rate", type=float, default=0.0)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--send-url", help="POST events instead of JSONL output")
    parser.add_argument("--source-token")
    args = parser.parse_args()
    if args.sources < 1 or args.items < 1 or args.events_per_second <= 0:
        parser.error("sources/items/rate must be positive")
    for name in ("duplicate_rate", "late_rate", "loss_rate"):
        value = getattr(args, name)
        if not 0 <= value <= 1:
            parser.error(f"{name.replace('_', '-')} must be between 0 and 1")
    interval = 1 / args.events_per_second
    emitted = accepted = duplicates = 0
    started = time.monotonic()
    for event in event_stream(
        args.sources, args.items, args.duplicate_rate, args.late_rate, args.loss_rate, args.seed
    ):
        if args.send_url:
            if not args.source_token:
                parser.error("--source-token is required with --send-url")
            response = httpx.post(
                args.send_url,
                json=event,
                headers={
                    "X-Source-Id": event["source"]["source_id"],
                    "X-Source-Token": args.source_token,
                },
                timeout=30,
            )
            response.raise_for_status()
            status = response.json()["ingestion_status"]
            accepted += status == "accepted"
            duplicates += status == "duplicate"
            target = started + (emitted + 1) * interval
            time.sleep(max(0, target - time.monotonic()))
        else:
            print(json.dumps(event, ensure_ascii=False, separators=(",", ":")))
        emitted += 1
    print(
        json.dumps(
            {"emitted": emitted, "accepted": accepted, "duplicates": duplicates, "seed": args.seed}
        ),
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
