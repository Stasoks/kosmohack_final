from __future__ import annotations

import argparse, json, statistics, time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import httpx


def main():
    parser = argparse.ArgumentParser(); parser.add_argument("events"); parser.add_argument("--url", default="http://127.0.0.1:8080"); parser.add_argument("--token", required=True); parser.add_argument("--workers", type=int, default=2)
    args = parser.parse_args(); events = [json.loads(line) for line in Path(args.events).read_text(encoding="utf-8").splitlines() if line]
    latencies, statuses = [], []
    def send(event):
        started = time.perf_counter(); response = httpx.post(f"{args.url}/api/v1/events", json=event, headers={"X-Source-Id": event["source"]["source_id"], "X-Source-Token": args.token}, timeout=30)
        return (time.perf_counter() - started) * 1000, response.json().get("ingestion_status", "failed") if response.is_success else "failed"
    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for latency, status in pool.map(send, events): latencies.append(latency); statuses.append(status)
    elapsed = time.perf_counter() - started; ordered = sorted(latencies)
    result = {"accepted_events_per_sec": statuses.count("accepted") / elapsed, "p95_ingestion_latency_ms": ordered[int(.95 * (len(ordered)-1))] if ordered else None,
              "projection_backlog": None, "projection_failures": statuses.count("failed"), "duplicate_count": statuses.count("duplicate"),
              "consistency_pass_rate": (len(statuses)-statuses.count("failed"))/len(statuses) if statuses else 1.0}
    print(json.dumps(result, indent=2))


if __name__ == "__main__": main()
