from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.app.read_models.live_quality import first_pass_yield
from streamlit_app.ui import views
from streamlit_app.ui.presentation import (
    LIVE_ACTIVITY_LABELS,
    LIVE_DETECTION_DISCLAIMER,
    LIVE_EQUIPMENT_DISCLAIMER,
    LIVE_WINDOW_LABELS,
    live_quality_activity_rows,
    live_quality_metric_cards,
    live_quality_station_rows,
    live_quality_timeline_rows,
)


ROOT = Path(__file__).resolve().parents[2]


def _snapshot() -> dict:
    return {
        "calculated_at": "2026-09-26T15:42:18Z",
        "window": "1h",
        "inspections": {"total": 0, "trusted_good": 0, "trusted_defect": 0},
        "quality": {
            "confirmed_ncr": 0,
            "pending_review": 0,
            "rework_required": 0,
            "released": 0,
            "first_pass_yield": None,
        },
        "stations": [],
        "defects_by_type": [],
        "timeline": [],
        "equipment_context": [],
        "recent_activity": [],
    }


def test_live_fpy_reuses_the_existing_kpi_formula() -> None:
    assert first_pass_yield(0, 0) is None
    assert first_pass_yield(10, 2) == 0.8


def test_live_cards_keep_zero_visible_and_separate_signals_from_ncr() -> None:
    cards = live_quality_metric_cards(_snapshot())

    assert [row["title"] for row in cards["main"]] == [
        "Проверено",
        "GOOD",
        "Сигналы дефекта",
        "Подтверждённые NCR",
        "FPY",
    ]
    assert [row["value"] for row in cards["main"]] == [0, 0, 0, 0, "0%"]
    assert [row["title"] for row in cards["state"]] == [
        "Ожидают решения",
        "На доработке",
        "Выпущено",
    ]


def test_live_chart_and_activity_helpers_are_human_first() -> None:
    snapshot = _snapshot()
    snapshot["timeline"] = [
        {"bucket": "2026-09-26T15:40:00Z", "good": 2, "defect": 1}
    ]
    snapshot["stations"] = [
        {"station_id": "ST-GRIND-01", "trusted_defect": 1},
        {"station_id": "ST-CLEAN-01", "trusted_defect": 0},
    ]
    snapshot["recent_activity"] = [
        {
            "at": "2026-09-26T15:42:17Z",
            "item_id": "ITEM-127",
            "kind": "ncr_confirmed",
        }
    ]

    assert live_quality_timeline_rows(snapshot) == [
        {
            "Время": "2026-09-26T15:40:00Z",
            "GOOD": 2,
            "Сигналы дефекта": 1,
        }
    ]
    assert live_quality_station_rows(snapshot) == [
        {"Место обнаружения": "ST-GRIND-01", "Сигналы дефекта": 1}
    ]
    activity = live_quality_activity_rows(snapshot)
    assert activity[0]["Изменение"] == "Несоответствие подтверждено контролёром"
    assert "ncr_confirmed" not in str(activity)


def test_live_dashboard_contract_has_neutral_causality_language() -> None:
    assert LIVE_WINDOW_LABELS == {
        "15m": "15 минут",
        "1h": "1 час",
        "24h": "24 часа",
        "all": "Всё время",
    }
    assert "не является" in LIVE_DETECTION_DISCLAIMER
    assert "причиной" in LIVE_DETECTION_DISCLAIMER
    assert "контекстом" in LIVE_EQUIPMENT_DISCLAIMER
    assert "доказанной причиной" in LIVE_EQUIPMENT_DISCLAIMER
    assert set(LIVE_ACTIVITY_LABELS) >= {
        "inspection_good",
        "inspection_defect",
        "ncr_confirmed",
        "ncr_rejected",
        "rework_started",
        "reinspection_good",
        "release",
        "equipment_warning",
    }


def test_live_dashboard_is_above_existing_overview_and_permission_gated() -> None:
    source = (ROOT / "streamlit_app" / "ui" / "views.py").read_text(encoding="utf-8")
    overview = source[source.index("def overview()") : source.index("def pending_reviews()")]
    fragment = source[
        source.index("@st.fragment(run_every=2.0)") : source.index("def overview()")
    ]

    assert '@st.fragment(run_every=2.0)' in fragment
    assert 'index=windows.index("1h")' in fragment
    assert 'except APIError as exc:' in fragment
    assert "Оперативный мониторинг временно недоступен." in fragment
    assert 'if "VIEW_ANALYTICS" in permissions:' in overview
    assert overview.index("_live_quality_dashboard()") < overview.index('st.subheader("Изделия")')
    assert 'st.subheader("Изделия")' in overview
    assert 'st.subheader("Несоответствия")' in overview
    assert "виновн" not in fragment.lower()
    assert "root cause" not in fragment.lower()


def test_live_api_failure_is_contained_inside_fragment(monkeypatch: pytest.MonkeyPatch) -> None:
    warnings: list[str] = []
    fake_streamlit = SimpleNamespace(
        selectbox=lambda *args, **kwargs: "1h",
        warning=warnings.append,
    )

    def unavailable(*args, **kwargs):
        raise views.APIError(503, "BACKEND_UNAVAILABLE", "unavailable")

    monkeypatch.setattr(views, "st", fake_streamlit)
    monkeypatch.setattr(views, "request", unavailable)

    views._live_quality_dashboard.__wrapped__()

    assert warnings == ["Оперативный мониторинг временно недоступен."]


@pytest.mark.parametrize("status_code", [401, 403])
def test_live_auth_failure_preserves_existing_session_flow(
    monkeypatch: pytest.MonkeyPatch, status_code: int
) -> None:
    calls: list[str] = []

    def rerun() -> None:
        calls.append("rerun")
        raise RuntimeError("rerun")

    fake_streamlit = SimpleNamespace(
        selectbox=lambda *args, **kwargs: "1h",
        rerun=rerun,
        warning=lambda message: calls.append("warning"),
    )

    def unavailable(*args, **kwargs):
        raise views.APIError(status_code, "AUTH_FAILURE", "unavailable")

    monkeypatch.setattr(views, "st", fake_streamlit)
    monkeypatch.setattr(views, "request", unavailable)
    monkeypatch.setattr(views, "refresh_profile", lambda: calls.append("refresh"))

    with pytest.raises(RuntimeError, match="rerun"):
        views._live_quality_dashboard.__wrapped__()

    assert calls == (["refresh", "rerun"] if status_code == 403 else ["rerun"])


def test_overview_without_analytics_permission_never_calls_live_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    fake_streamlit = SimpleNamespace(
        session_state=SimpleNamespace(profile={"permissions": ["VIEW_PRODUCT"]}),
        subheader=lambda *args, **kwargs: None,
        dataframe=lambda *args, **kwargs: None,
        info=lambda *args, **kwargs: None,
    )

    def request(method: str, path: str, **kwargs):
        calls.append(path)
        return []

    monkeypatch.setattr(views, "st", fake_streamlit)
    monkeypatch.setattr(views, "header", lambda title: None)
    monkeypatch.setattr(views, "request", request)

    views.overview()

    assert calls == ["/api/v1/items", "/api/v1/routes"]
    assert "/api/v1/analytics/live-quality" not in calls


def test_live_activity_timestamp_is_human_readable() -> None:
    snapshot = _snapshot()
    snapshot["recent_activity"] = [
        {
            "at": datetime(2026, 9, 26, 15, 42, 17, tzinfo=timezone.utc),
            "item_id": "ITEM-127",
            "kind": "inspection_good",
        }
    ]

    assert live_quality_activity_rows(snapshot)[0]["Время"] == "26.09.2026 15:42:17 UTC"
