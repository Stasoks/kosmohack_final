from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest

from streamlit_app.api_client import client
from streamlit_app.ui import views
from streamlit_app.ui.navigation import authorized_page_specs
from streamlit_app.ui.presentation import (
    api_error_message,
    birth_window_presentation,
    coverage_explanation,
    decision_validation_error,
    evidence_groups,
    evidence_presentation,
    alert_explanation,
    label,
    scenario_acceptance_checks,
    split_nonconformances,
    structure_notice,
)


def test_guarded_preserves_unique_page_callable_names() -> None:
    page_functions = [
        views.overview,
        views.pending_reviews,
        views.timeline,
        views.analytics,
        views.data_health,
        views.route_editor,
        views.blast_radius,
        views.admin_panel,
        views.factory_simulator,
        views.scenario_runner,
    ]

    guarded_pages = [views.guarded(render) for render in page_functions]

    assert [page.__name__ for page in guarded_pages] == [
        render.__name__ for render in page_functions
    ]
    assert len({page.__name__ for page in guarded_pages}) == len(guarded_pages)


@pytest.mark.parametrize(
    ("value", "domain", "expected"),
    [
        ("IN_PROCESS", None, "В производстве"),
        ("REWORK_REQUIRED", None, "Требуется доработка"),
        ("pending_review", None, "Ожидает решения"),
        ("not_established", None, "Причина не установлена"),
        ("CONFLICTED", None, "Конфликт результатов"),
        ("INVALIDATED", None, "Инвалидировано"),
        ("FULL", "coverage", "Полное покрытие"),
        ("PARTIAL", "coverage", "Частичное покрытие"),
        ("NONE", "coverage", "Не проверяется"),
        ("TARGET_ONLY", "coverage", "Только целевая проверка после доработки"),
        ("equipment", "risk_factor", "Оборудование"),
        ("UNHEALTHY", "integration_health", "Есть проблема"),
        ("RETRYING", "outbox", "Повторная отправка"),
        ("CRITICAL", "severity", "Критическая"),
    ],
)
def test_presentation_labels_are_centralized(value: str, domain: str | None, expected: str) -> None:
    assert label(value, domain=domain) == expected


def test_birth_window_presentation_explains_bounded_and_left_open() -> None:
    bounded = birth_window_presentation(
        {
            "status": "BOUNDED",
            "evidence": [
                {"type": "LAST_TRUSTED_GOOD", "source_event_id": "GOOD-1"},
                {"type": "FIRST_TRUSTED_DEFECT", "source_event_id": "BAD-1"},
                {"type": "OPERATION_IN_WINDOW", "source_event_id": "OP-1"},
            ],
        }
    )
    left_open = birth_window_presentation({"status": "LEFT_OPEN", "evidence": []})

    assert bounded["title"] == "Интервал возникновения локализован"
    assert "после последней достоверной проверки" in bounded["explanation"]
    assert bounded["last_good"]["source_event_id"] == "GOOD-1"
    assert bounded["operations"][0]["source_event_id"] == "OP-1"
    assert left_open["title"] == "Левая граница неизвестна"
    assert "нет проверки" in left_open["explanation"]


def test_degraded_structure_and_partial_coverage_are_explained_as_fallbacks() -> None:
    assert structure_notice("degraded") == (
        "Структура компонентов недоступна",
        "Контроль продолжается на уровне изделия.",
    )
    assert structure_notice("available") is None
    assert coverage_explanation("PARTIAL") == (
        "Проверка достоверна, но покрывает этот тип дефекта только частично. "
        "Поэтому отсутствие дефекта на этой проверке не доказывает, что дефекта не было."
    )


def test_security_alerts_have_human_explanations() -> None:
    assert label("SOURCE_AUTH_FAILED", domain="alert") == (
        "Не удалось проверить источник"
    )
    assert "Событие отклонено" in alert_explanation("SOURCE_AUTH_FAILED")
    assert label("INVALID_ACK", domain="alert") == "Некорректное подтверждение ERP"


def test_evidence_is_grouped_and_context_is_not_presented_as_cause() -> None:
    evidence = [
        {"type": "FIRST_TRUSTED_DEFECT", "role": "BOUNDARY"},
        {"type": "MACHINE_WARNING", "role": "CONTEXT"},
        {"type": "CONFLICTING_OBSERVATION", "role": "LIMITATION"},
    ]

    grouped = evidence_groups(evidence)

    assert len(grouped["Границы интервала"]) == 1
    assert len(grouped["Что происходило внутри интервала"]) == 1
    assert len(grouped["Ограничения и проблемы данных"]) == 1
    assert evidence_presentation(evidence[1])["note"] == "Контекст, не доказанная причина"
    assert "несовместимые результаты" in evidence_presentation(evidence[2])["note"]


def test_logout_state_has_no_authorized_navigation(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_streamlit = SimpleNamespace(
        session_state={
            "auth": {"access_token": "access"},
            "profile": {"permissions": ["VIEW_PRODUCT", "MANAGE_USERS"]},
        }
    )
    monkeypatch.setattr(client, "st", fake_streamlit)

    client.clear_session()

    assert fake_streamlit.session_state == {}
    assert authorized_page_specs(None) == []


def test_authorized_navigation_is_rebuilt_for_the_new_role() -> None:
    controller = authorized_page_specs(
        {"permissions": ["VIEW_PRODUCT", "REVIEW_NONCONFORMANCE", "VIEW_TIMELINE"]}
    )
    admin = authorized_page_specs({"permissions": ["VIEW_PRODUCT", "MANAGE_USERS"]})

    assert {page.view_name for page in controller} == {
        "overview",
        "pending_reviews",
        "timeline",
    }
    assert {page.view_name for page in admin} == {"overview", "admin_panel"}


def test_demo_navigation_is_explicitly_gated() -> None:
    profile = {"permissions": ["RUN_DEMO_SCENARIOS"]}

    assert {page.view_name for page in authorized_page_specs(profile, demo_mode=False)} == {
        "overview"
    }
    assert {page.view_name for page in authorized_page_specs(profile, demo_mode=True)} == {
        "overview",
        "factory_simulator",
        "scenario_runner",
    }


def test_completed_nonconformances_remain_in_all_and_completed_views() -> None:
    rows = [
        {"id": "pending", "verdict": "pending_review", "disposition": "IN_PROCESS"},
        {
            "id": "complete",
            "verdict": "confirmed",
            "disposition": "RELEASED",
            "resolved_at": "2026-09-26T10:00:00Z",
        },
    ]

    pending, all_rows, completed = split_nonconformances(rows)

    assert [row["id"] for row in pending] == ["pending"]
    assert [row["id"] for row in all_rows] == ["pending", "complete"]
    assert [row["id"] for row in completed] == ["complete"]


def test_validation_errors_are_human_readable() -> None:
    assert decision_validation_error("confirmed", "RELEASED", "x") == (
        "Укажите обоснование не короче 3 символов."
    )
    assert decision_validation_error("rejected", "REWORK_REQUIRED", "valid reason") == (
        "Отклонённое несоответствие нельзя отправить на доработку."
    )
    assert api_error_message("REWORK_NOT_COMPLETED", "technical") == (
        "Сначала должна быть завершена операция доработки."
    )
    assert api_error_message("EVIDENCE_INTEGRITY_FAILED", "technical") == (
        "Решение заблокировано: нарушена целостность подтверждающих данных."
    )
    assert api_error_message(
        "REQUEST_VALIDATION_ERROR",
        "Request validation failed",
        [{"field": "reason", "type": "string_too_short", "message": "too short"}],
    ) == "Укажите обоснование не короче 3 символов."


def test_api_client_preserves_fastapi_validation_details() -> None:
    response = httpx.Response(
        422,
        json={
            "error": {
                "code": "REQUEST_VALIDATION_ERROR",
                "message": "Request validation failed",
                "details": [
                    {
                        "field": "reason",
                        "type": "string_too_short",
                        "message": "String should have at least 3 characters",
                    }
                ],
            }
        },
    )

    with pytest.raises(client.APIError) as caught:
        client._parse(response)

    assert caught.value.details[0]["field"] == "reason"
    assert api_error_message(
        caught.value.code, caught.value.message, caught.value.details
    ) == "Укажите обоснование не короче 3 символов."


def test_scenario_presentation_separates_actual_from_generic_assertions() -> None:
    result = {
        "scenario": "ARBITRARY-NAME",
        "actual": {"ncr_count": 1, "item_disposition": "RELEASED"},
        "expected": {"ncr_count": 1, "item_disposition": "REWORK_REQUIRED"},
        "failures": ["$.item_disposition: expected 'REWORK_REQUIRED', got 'RELEASED'"],
    }

    checks = scenario_acceptance_checks(result)

    assert checks == [
        {"name": "Количество несоответствий", "passed": True, "actual": 1, "expected": 1},
        {
            "name": "Статус изделия",
            "passed": False,
            "actual": "RELEASED",
            "expected": "REWORK_REQUIRED",
        },
    ]
