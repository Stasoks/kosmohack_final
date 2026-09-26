from __future__ import annotations

import os
from typing import Any

import httpx
import streamlit as st


BASE_URL = os.getenv("TRACEQ_API_URL", "http://localhost:8080").rstrip("/")


class APIError(RuntimeError):
    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        details: list[dict[str, Any]] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details or []


def _parse(response: httpx.Response) -> Any:
    if response.is_success:
        if response.status_code == 204:
            return None
        return response.json()
    try:
        error = response.json()["error"]
        raise APIError(
            response.status_code,
            error.get("code", "API_ERROR"),
            error.get("message", "API error"),
            error.get("details") if isinstance(error.get("details"), list) else None,
        )
    except (ValueError, KeyError, TypeError):
        raise APIError(response.status_code, "API_ERROR", "Backend request failed")


def login(username: str, password: str) -> dict[str, Any]:
    response = httpx.post(
        f"{BASE_URL}/api/v1/auth/login",
        json={"username": username, "password": password},
        timeout=10,
    )
    tokens = _parse(response)
    st.session_state.auth = tokens
    profile = request("GET", "/api/v1/auth/me", retry_refresh=False)
    st.session_state.profile = profile
    return profile


def clear_session() -> None:
    st.session_state.pop("auth", None)
    st.session_state.pop("profile", None)


def _refresh() -> bool:
    auth = st.session_state.get("auth")
    if not auth or not auth.get("refresh_token"):
        return False
    response = httpx.post(
        f"{BASE_URL}/api/v1/auth/refresh",
        json={"refresh_token": auth["refresh_token"]},
        timeout=10,
    )
    if not response.is_success:
        clear_session()
        return False
    st.session_state.auth = response.json()
    return True


def request(
    method: str,
    path: str,
    *,
    params: dict[str, Any] | None = None,
    json: dict[str, Any] | list[Any] | None = None,
    retry_refresh: bool = True,
) -> Any:
    auth = st.session_state.get("auth")
    headers = {"Authorization": f"Bearer {auth['access_token']}"} if auth else {}
    try:
        response = httpx.request(
            method,
            f"{BASE_URL}{path}",
            params=params,
            json=json,
            headers=headers,
            timeout=15,
        )
    except httpx.RequestError as exc:
        raise APIError(503, "BACKEND_UNAVAILABLE", "TRACE-Q backend is unavailable") from exc
    if response.status_code == 401 and retry_refresh and _refresh():
        return request(method, path, params=params, json=json, retry_refresh=False)
    if response.status_code == 401:
        clear_session()
    return _parse(response)


def logout() -> None:
    auth = st.session_state.get("auth")
    if auth and auth.get("refresh_token"):
        try:
            request(
                "POST",
                "/api/v1/auth/logout",
                json={"refresh_token": auth["refresh_token"]},
                retry_refresh=False,
            )
        except APIError:
            pass
    clear_session()
