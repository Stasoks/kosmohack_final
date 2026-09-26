from __future__ import annotations

import os
import time

import httpx


def main() -> None:
    base = os.getenv("TRACEQ_SIMULATOR_BASE", "http://127.0.0.1:8070").rstrip("/")
    with httpx.Client(timeout=10) as client:
        health = client.get(f"{base}/health")
        health.raise_for_status()
        created = client.post(
            f"{base}/sessions",
            json={
                "route_code": "ROUTE-DEFAULT",
                "item_count": 1,
                "mode": "normal",
                "interval_seconds": 0.2,
            },
        )
        created.raise_for_status()
        session_id = created.json()["id"]
        client.post(f"{base}/sessions/{session_id}/start").raise_for_status()
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            value = client.get(f"{base}/sessions/{session_id}").json()
            if value["status"] == "completed":
                print(f"Factory simulator smoke: OK ({value['event_counter']} events)")
                return
            if value["status"] == "error":
                raise RuntimeError(value.get("last_error") or "simulator failed")
            time.sleep(0.25)
        raise TimeoutError("factory simulator did not complete within 20 seconds")


if __name__ == "__main__":
    main()
