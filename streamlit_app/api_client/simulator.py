from __future__ import annotations

import os
from typing import Any

import httpx

from streamlit_app.api_client.client import APIError


BASE_URL = os.getenv("FACTORY_SIMULATOR_URL", "http://localhost:8070").rstrip("/")


def simulator_request(
    method: str, path: str, *, json: dict[str, Any] | None = None
) -> Any:
    try:
        response = httpx.request(method, f"{BASE_URL}{path}", json=json, timeout=15)
    except httpx.RequestError as exc:
        raise APIError(
            503,
            "SIMULATOR_UNAVAILABLE",
            "Сервис симуляции недоступен.",
        ) from exc
    if response.is_success:
        return None if response.status_code == 204 else response.json()
    try:
        detail = response.json().get("detail")
    except ValueError:
        detail = None
    raise APIError(
        response.status_code,
        "SIMULATOR_ERROR",
        str(detail or "Ошибка сервиса симуляции производства"),
    )
