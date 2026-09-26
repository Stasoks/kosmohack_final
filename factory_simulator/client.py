from __future__ import annotations

from typing import Any

import httpx

from factory_simulator.models import RouteSnapshot, RouteStepSnapshot


class TraceQClient:
    def __init__(self, base_url: str, source_token: str, username: str, password: str):
        self.base_url = base_url.rstrip("/")
        self.source_token = source_token
        self.username = username
        self.password = password
        self._access_token: str | None = None

    async def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        headers = dict(kwargs.pop("headers", {}))
        if self._access_token:
            headers["Authorization"] = f"Bearer {self._access_token}"
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.request(
                method, f"{self.base_url}{path}", headers=headers, **kwargs
            )
        if response.status_code == 401 and path != "/api/v1/auth/login":
            await self.login()
            return await self._request(method, path, **kwargs)
        response.raise_for_status()
        return response

    async def login(self) -> None:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(
                f"{self.base_url}/api/v1/auth/login",
                json={"username": self.username, "password": self.password},
            )
        response.raise_for_status()
        self._access_token = response.json()["access_token"]

    async def route_snapshot(self, route_code: str) -> RouteSnapshot:
        response = await self._request("GET", "/api/v1/routes")
        route = next(
            (value for value in response.json() if value["code"] == route_code), None
        )
        if route is None or not route.get("active_revision_id"):
            raise ValueError(f"Active route not found: {route_code}")
        revision = next(
            value
            for value in route["revisions"]
            if value["id"] == route["active_revision_id"]
        )
        return RouteSnapshot(
            route_id=route["id"],
            route_code=route["code"],
            route_name=route["name"],
            revision_id=revision["id"],
            revision=revision["revision"],
            steps=[RouteStepSnapshot(**value) for value in revision["steps"]],
        )

    async def available_routes(self) -> list[dict[str, Any]]:
        response = await self._request("GET", "/api/v1/routes")
        result = []
        for route in response.json():
            if route["code"] == "ROUTE-A":
                # Acceptance-fixture route; it is not a live production route.
                continue
            active_id = route.get("active_revision_id")
            active = next(
                (value for value in route["revisions"] if value["id"] == active_id),
                None,
            )
            if active:
                result.append(
                    {
                        "code": route["code"],
                        "name": route["name"],
                        "revision": active["revision"],
                        "step_count": len(active["steps"]),
                    }
                )
        return result

    async def publish(self, event: dict[str, Any]) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(
                f"{self.base_url}/api/v1/events",
                headers={
                    "X-Source-Id": event["source"]["source_id"],
                    "X-Source-Token": self.source_token,
                },
                json=event,
            )
        response.raise_for_status()
        return response.json()

    async def item_state(self, item_id: str) -> dict[str, Any] | None:
        response = await self._request("GET", f"/api/v1/items/{item_id}")
        return response.json()

    async def nonconformances(self) -> list[dict[str, Any]]:
        response = await self._request("GET", "/api/v1/nonconformances")
        return response.json()
