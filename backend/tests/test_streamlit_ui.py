from __future__ import annotations

from datetime import date, datetime, time, timezone
from types import SimpleNamespace

import httpx
import pytest

from streamlit_app.api_client import client
from streamlit_app.ui import views
from streamlit_app.ui.navigation import authorized_page_specs
from streamlit_app.ui.presentation import (
    EQUIPMENT_WARNINGS_CAPTION,
    EQUIPMENT_WARNINGS_TITLE,
    TIMELINE_CSS,
    analysis_evidence_rows,
    analysis_history_rows,
    activity_presentation,
    api_error_message,
    birth_window_presentation,
    coverage_explanation,
    coverage_analysis_rows,
    cause_chart_rows,
    control_device_label,
    control_device_invalidation_payload,
    defect_chart_rows,
    defect_label,
    decision_validation_error,
    detection_chart_rows,
    duration_label,
    draft_revision_label,
    equipment_issue_suggestion,
    evidence_groups,
    evidence_presentation,
    alert_explanation,
    label,
    operation_label,
    pinned_operation_names,
    period_validation_error,
    profile_header_label,
    route_name_label,
    route_revision_label,
    scenario_acceptance_checks,
    scenario_human_checks,
    scenario_title,
    split_nonconformances,
    structure_notice,
    timeline_csv,
    timeline_export_rows,
    timeline_html,
    utc_iso,
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


def test_defect_operation_and_route_labels_hide_known_technical_codes() -> None:
    assert defect_label("surface_crack") == "Поверхностная трещина"
    assert defect_label("scratch_or_gouge") == "Царапина или задир"
    assert defect_label("custom_defect") == "custom_defect"
    assert operation_label("OP-MILL") == "Фрезерование"
    assert operation_label("CUSTOM-OP", "Чистовая обработка") == "Чистовая обработка"
    assert operation_label("CUSTOM-OP") == "CUSTOM-OP"
    assert route_revision_label("Основной маршрут корпуса", 2) == (
        "Основной маршрут корпуса · Версия 2"
    )
    assert route_name_label("Fixture route ROUTE-A", "ROUTE-A") == (
        "Маршрут приёмочного сценария"
    )
    assert label(None) == "—"
    assert "None" not in duration_label(None)


def test_header_roles_and_draft_revision_are_human_readable() -> None:
    assert profile_header_label(
        {"username": "stas", "roles": ["technologist"]}
    ) == "stas · Технолог"
    assert profile_header_label(
        {"username": "controller", "roles": ["controller"]}
    ) == "controller · Контролёр качества"
    assert profile_header_label(
        {"username": "admin", "roles": ["admin"]}
    ) == "admin · Администратор"
    assert draft_revision_label(
        {"id": "fbc5e52a-9192-4d28-ac5e-a95907ab6207", "revision": 3}
    ) == "Версия 3 · Черновик"


def test_timeline_css_is_theme_safe() -> None:
    normalized = TIMELINE_CSS.lower().replace(" ", "")

    assert "color:inherit" in normalized
    assert "background:currentcolor" in normalized
    assert "var(--background-color" in normalized
    for hardcoded in ("#101828", "#475467", "#667085"):
        assert hardcoded not in normalized


def test_timeline_uses_operation_name_from_the_items_pinned_revision() -> None:
    routes = [
        {
            "code": "ROUTE-X",
            "active_revision_id": "revision-2",
            "revisions": [
                {
                    "id": "revision-1",
                    "revision": 1,
                    "steps": [
                        {
                            "operation_id": "OP-CUSTOM",
                            "operation_name": "Лазерная сварка",
                        }
                    ],
                },
                {
                    "id": "revision-2",
                    "revision": 2,
                    "steps": [
                        {
                            "operation_id": "OP-CUSTOM",
                            "operation_name": "Роботизированная сварка",
                        }
                    ],
                },
            ],
        }
    ]
    item = {
        "route_code": "ROUTE-X",
        "route_revision_id": "revision-1",
        "route_revision": 1,
    }

    operation_names = pinned_operation_names(item, routes)
    shown = activity_presentation(
        {
            "type": "operation_started",
            "occurred_at": "2026-09-26T11:42:00Z",
            "details": {"operation_id": "OP-CUSTOM"},
        },
        operation_names,
    )

    assert operation_names == {"OP-CUSTOM": "Лазерная сварка"}
    assert shown["title"] == "Операция «Лазерная сварка» начата"
    assert "Роботизированная" not in shown["title"]


def test_timeline_html_renders_human_cards_without_technical_ids() -> None:
    activity = [
        {
            "type": "operation_started",
            "occurred_at": "2026-09-26T11:42:00Z",
            "event_id": "EV-TECH-1",
            "source_id": "MES-01",
            "details": {
                "operation_id": "OP-CUSTOM",
                "operation_run_id": "RUN-SIM-1",
            },
        },
        {
            "type": "controller_decision",
            "occurred_at": "2026-09-26T11:50:00Z",
            "details": {
                "verdict": "confirmed",
                "disposition": "REWORK_REQUIRED",
                "reason": "Нужна доработка поверхности",
            },
        },
    ]

    html = timeline_html(activity, {"OP-CUSTOM": "Лазерная сварка"})

    assert '<div class="traceq-timeline">' in html
    assert '<div class="traceq-event action">' in html
    assert "Операция «Лазерная сварка» начата" in html
    assert 'title="26.09.2026 11:42:00 UTC"' in html
    assert "EV-TECH-1" not in html
    assert "MES-01" not in html
    assert "RUN-SIM-1" not in html


def test_timeline_csv_is_a_human_readable_excel_compatible_export() -> None:
    rows = timeline_export_rows(
        [
            {
                "type": "operation_finished",
                "occurred_at": "2026-09-26T11:43:00Z",
                "event_id": "EV-TECH-2",
                "details": {
                    "operation_id": "OP-MILL",
                    "operation_run_id": "RUN-SIM-2",
                },
            }
        ]
    )
    exported = timeline_csv(rows)
    decoded = exported.decode("utf-8")

    assert exported.startswith(b"\xef\xbb\xbf")
    assert "Дата и время,Событие,Подробности,Важность" in decoded
    assert "Операция «Фрезерование» завершена" in decoded
    assert "EV-TECH-2" not in decoded
    assert "RUN-SIM-2" not in decoded


def test_analysis_tables_explain_evidence_without_raw_ids() -> None:
    evidence = [
        {
            "type": "OPERATION_IN_WINDOW",
            "role": "CONTEXT",
            "source_event_id": "EV-OP-1",
            "occurred_at": "2026-09-26T11:45:00Z",
            "details": {
                "operation_id": "OP-CUSTOM",
                "operation_run_id": "RUN-RAW-1",
            },
        },
        {
            "type": "MACHINE_WARNING",
            "role": "CONTEXT",
            "source_event_id": "EV-MACHINE-1",
            "occurred_at": "2026-09-26T11:46:00Z",
            "details": {"state": "SIM_VIBRATION_HIGH", "equipment_id": "CNC-04"},
        },
    ]

    rows = analysis_evidence_rows(evidence, {"OP-CUSTOM": "Лазерная сварка"})
    history = analysis_history_rows(
        [
            {
                "version": 2,
                "status": "BOUNDED",
                "created_at": "2026-09-26T11:52:00Z",
                "reason": "late_event_recalculation",
            }
        ]
    )
    rendered = str(rows)

    assert rows[0]["Событие"] == "Операция «Лазерная сварка»"
    assert rows[1]["Событие"] == "Предупреждение оборудования: Повышенная вибрация"
    assert "Контекст, не доказанная причина" in rows[1]["Что это значит"]
    assert "EV-OP-1" not in rendered
    assert "RUN-RAW-1" not in rendered
    assert "CNC-04" not in rendered
    assert history[0]["Почему изменилось"] == (
        "Получено событие, которое пришло с задержкой"
    )


def test_equipment_warning_copy_does_not_claim_a_proven_fault() -> None:
    assert EQUIPMENT_WARNINGS_TITLE == "Недавние предупреждения оборудования"
    assert EQUIPMENT_WARNINGS_CAPTION == (
        "Предупреждение само по себе не доказывает неисправность и не означает "
        "наличие дефекта на изделиях."
    )
    assert "требующие анализа" not in EQUIPMENT_WARNINGS_TITLE.lower()


def test_date_time_helpers_produce_utc_iso_and_human_validation() -> None:
    start = utc_iso(date(2026, 9, 26), time(11, 27, 17))
    end = utc_iso(date(2026, 9, 26), time(11, 27, 22))

    assert start == "2026-09-26T11:27:17Z"
    assert period_validation_error(start, end) is None
    assert period_validation_error(end, start) == (
        "Окончание периода не может быть раньше его начала."
    )

    invalidation = control_device_invalidation_payload(
        device_id="SIM-CAMERA-01",
        affected_from_date=date(2026, 9, 26),
        affected_from_time=time(11, 27, 17),
        affected_to_date=date(2026, 9, 26),
        affected_to_time=time(11, 27, 22),
        reason="Сбой калибровки",
        invalidation_type="CALIBRATION_FAILURE",
    )
    assert invalidation["device_id"] == "SIM-CAMERA-01"
    assert invalidation["affected_from"] == start
    assert invalidation["affected_to"] == end


def test_equipment_issue_suggestion_only_prefills_editable_period() -> None:
    suggestion = equipment_issue_suggestion(
        {
            "equipment_id": "EQ-LATHE-01",
            "occurred_at": "2026-09-26T11:27:22Z",
        }
    )

    assert suggestion["factor_type"] == "equipment"
    assert suggestion["factor_value"] == "EQ-LATHE-01"
    assert suggestion["affected_to"] == datetime(
        2026, 9, 26, 11, 27, 22, tzinfo=timezone.utc
    )
    assert suggestion["affected_from"] == datetime(
        2026, 9, 26, 10, 57, 22, tzinfo=timezone.utc
    )
    assert "proposal" not in suggestion


def test_analytics_helpers_localize_defects_and_handle_empty_series() -> None:
    assert defect_chart_rows({"surface_crack": 2}) == [
        {"Тип дефекта": "Поверхностная трещина", "Количество": 2}
    ]
    assert defect_chart_rows({}) == []
    assert detection_chart_rows([]) == []
    assert cause_chart_rows({}) == [
        {"Статус причины": "Причина подтверждена человеком", "Количество": 0},
        {"Статус причины": "Причина не установлена", "Количество": 0},
    ]
    assert control_device_label("SIM-CAMERA-01") == "Камера симулятора"


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


def test_timeline_presentation_keeps_ids_out_of_the_main_text() -> None:
    operation = activity_presentation(
        {
            "type": "operation_started",
            "occurred_at": "2026-09-26T11:42:00Z",
            "event_id": "EV-TECH-1",
            "source_id": "MES-01",
            "details": {
                "operation_id": "OP-MILL",
                "operation_run_id": "RUN-SIM-1",
            },
        }
    )
    defect = activity_presentation(
        {
            "type": "nonconformance_opened",
            "occurred_at": "2026-09-26T11:47:00Z",
            "nonconformance_id": "NCR-UUID",
            "details": {"defect_type": "surface_crack"},
        }
    )

    assert operation["title"] == "Операция «Фрезерование» начата"
    assert operation["short_time"] == "11:42:00"
    assert "RUN-SIM" not in " ".join(operation["lines"])
    assert defect["title"] == "Обнаружено несоответствие: Поверхностная трещина"
    assert defect["tone"] == "critical"


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


def test_coverage_analysis_is_presented_with_human_labels() -> None:
    rows = coverage_analysis_rows(
        {
            "rows": [
                {
                    "component_selector": "*",
                    "defect_type": "surface_crack",
                    "status": "PARTIAL_ONLY",
                    "control_points": ["CP-INCOMING"],
                }
            ]
        }
    )

    assert rows == [
        {
            "Компонент": "Все компоненты",
            "Тип дефекта": "Поверхностная трещина",
            "Результат": "Только частичное покрытие",
            "Контрольные точки": "CP-INCOMING",
        }
    ]


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


def test_all_scenario_titles_and_main_assertions_are_human_readable() -> None:
    titles = [scenario_title(f"S{index:02d}") for index in range(1, 26)]

    assert len(set(titles)) == 25
    assert all(any("А" <= char <= "я" or char == "ё" for char in title) for title in titles)
    forbidden = {
        "GOOD",
        "raw history",
        "rework lifecycle",
        "duplicate delivery",
        "inspection",
        "impossible_to_assess",
    }
    assert not any(term in title for title in titles for term in forbidden)

    checks = scenario_human_checks(
        {
            "scenario": "S06",
            "expected": {"duplicate_deliveries": 1},
            "actual": {"duplicate_deliveries": 1},
            "failures": [],
        }
    )
    assert checks == [
        {"name": "Повторная доставка распознана", "passed": True},
        {"name": "Исходное событие сохранено один раз", "passed": True},
        {"name": "Наблюдения и показатели не удвоились", "passed": True},
    ]
    assert all(not isinstance(value, (dict, list)) for row in checks for value in row.values())
