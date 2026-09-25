from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

import httpx


class ProductionSystemAdapter(ABC):
    @abstractmethod
    def fetch_jobs(self) -> list[dict[str, Any]]: ...

    @abstractmethod
    def fetch_references(self) -> dict[str, Any]: ...

    @abstractmethod
    def send_quality_result(self, payload: dict[str, Any]) -> dict[str, Any]: ...


@dataclass
class EmulatorAdapter(ProductionSystemAdapter):
    base_url: str
    timeout: float = 5.0

    def fetch_jobs(self) -> list[dict[str, Any]]:
        response = httpx.get(f"{self.base_url}/api/v1/jobs", timeout=self.timeout)
        response.raise_for_status()
        return response.json()

    def fetch_references(self) -> dict[str, Any]:
        response = httpx.get(f"{self.base_url}/api/v1/references", timeout=self.timeout)
        response.raise_for_status()
        return response.json()

    def send_quality_result(self, payload: dict[str, Any]) -> dict[str, Any]:
        response = httpx.post(
            f"{self.base_url}/api/v1/quality-results", json=payload, timeout=self.timeout
        )
        response.raise_for_status()
        return response.json()


class FixtureAdapter(ProductionSystemAdapter):
    """Deterministic boundary fixture shared by planned 1C/Galaktika/MES transports."""

    def __init__(self, fixture: dict[str, Any]) -> None:
        self.fixture = fixture

    def fetch_jobs(self) -> list[dict[str, Any]]:
        return list(self.fixture.get("jobs", []))

    def fetch_references(self) -> dict[str, Any]:
        return dict(self.fixture.get("references", {}))

    def send_quality_result(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {"status": "fixture_ack", "message_id": payload["message_id"]}


class OneCAdapter(FixtureAdapter):
    """1C port implementation for fixtures; vendor transport is intentionally injected later."""


class GalaktikaAdapter(FixtureAdapter):
    """Galaktika ERP port implementation for fixtures; no invented vendor URL."""


class FixtureMesAdapter(FixtureAdapter):
    """MES adapter fixture implementing the same core-facing port."""
