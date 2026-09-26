from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Iterable


LABELS: dict[str, str] = {
    "IN_PROCESS": "В производстве",
    "REWORK_REQUIRED": "Требуется доработка",
    "RELEASED": "Разрешено к выпуску",
    "USE_AS_IS": "Использовать без доработки",
    "SCRAPPED": "Списано",
    "pending_review": "Ожидает решения",
    "needs_extra_check": "Нужен дополнительный контроль",
    "confirmed": "Подтверждено",
    "rejected": "Отклонено",
    "not_established": "Причина не установлена",
    "BOUNDED": "Интервал возникновения локализован",
    "LEFT_OPEN": "Левая граница неизвестна",
    "EVIDENCE_INVALIDATED": "Наблюдение инвалидировано",
    "UNRESOLVED_DEFECT_BOUNDARY": "Достоверная граница дефекта не определена",
    "TRUSTED": "Достоверное наблюдение",
    "UNTRUSTED": "Недостоверное наблюдение",
    "CONFLICTED": "Конфликт результатов",
    "INVALIDATED": "Инвалидировано",
    "UNASSESSABLE": "Невозможно оценить",
    "PENDING": "Ожидает верификации",
    "PASSED": "Пройдено",
    "FAILED": "Не пройдено",
    "OPEN": "Открыто",
    "CLOSED": "Завершено",
    "defect_detected": "Дефект обнаружен",
    "no_defect": "Дефект не обнаружен",
    "good": "Качественное наблюдение",
    "available": "Доступна",
    "degraded": "Недоступна — контроль продолжается на уровне изделия",
    "rework": "Доработка",
    "success": "Успешно",
    "failure": "Ошибка",
    "denied": "Отказано",
    "pending": "Ожидает",
}

DOMAIN_LABELS: dict[str, dict[str, str]] = {
    "coverage": {
        "FULL": "Полное покрытие",
        "PARTIAL": "Частичное покрытие",
        "NONE": "Не проверяется",
        "TARGET_ONLY": "Только целевая проверка после доработки",
    },
    "containment": {
        "NONE": "Без ограничений",
        "REVIEW_REQUIRED": "Требуется рассмотрение",
        "HOLD": "Удержать изделие",
        "REINSPECTION_REQUIRED": "Требуется повторный контроль",
    },
    "risk_factor": {
        "equipment": "Оборудование",
        "tool": "Инструмент",
        "material_lot": "Партия материала",
        "control_device": "Контрольное устройство",
        "component": "Компонент",
        "time_interval": "Временной интервал",
    },
    "integration_health": {
        "HEALTHY": "Работает",
        "UNHEALTHY": "Есть проблема",
        "DEGRADED": "Работает с ограничениями",
        "UNKNOWN": "Нет актуальных данных",
        "implemented": "Подключён",
        "fixture_transport": "Демонстрационный транспорт",
        "json_structure_provider": "Поставщик структуры JSON",
    },
    "outbox": {
        "PENDING": "Ожидает отправки",
        "PROCESSING": "Отправляется",
        "RETRY": "Ожидает повторной отправки",
        "RETRYING": "Повторная отправка",
        "DELIVERED": "Доставлено",
        "FAILED": "Ошибка доставки",
        "DEAD": "Отправка прекращена после ошибок",
    },
    "severity": {
        "LOW": "Низкая",
        "MEDIUM": "Средняя",
        "HIGH": "Высокая",
        "CRITICAL": "Критическая",
        "low": "Низкая",
        "medium": "Средняя",
        "high": "Высокая",
        "critical": "Критическая",
    },
    "projection": {
        "up_to_date": "Актуальна",
        "rebuilding": "Перестраивается",
        "failed": "Ошибка построения",
    },
    "ingestion": {
        "accepted": "Принято",
        "duplicate": "Повторная доставка",
        "rejected": "Отклонено",
    },
    "worker": {
        "RUNNING": "Работает",
        "HEALTHY": "Работает",
        "STALE": "Нет свежего heartbeat",
        "STOPPED": "Остановлен",
    },
    "source_status": {
        "ACTIVE": "Активен",
        "SUSPENDED": "Приостановлен",
        "REVOKED": "Отозван",
        "EXPIRED": "Истёк",
    },
    "alert": {
        "SOURCE_SEQUENCE_ANOMALY": "Нарушена последовательность событий источника",
        "SOURCE_AUTH_FAILED": "Не удалось проверить источник",
        "TRANSPORT_REPLAY": "Обнаружена повторная транспортная доставка",
        "REPLAY_ATTEMPT": "Повтор транспортного запроса",
        "RBAC_DENIED": "Доступ запрещён политикой ролей",
        "CRITICAL_ACTION_DENIED": "Критическое действие не подтверждено",
        "EVENT_ID_CONFLICT": "Одинаковый ID события с другим содержимым",
        "RAW_LOG_INTEGRITY_FAILED": "Нарушена целостность журнала",
        "AUDIT_LOG_INTEGRITY_FAILED": "Нарушена целостность журнала действий",
        "INVALID_ACK": "Некорректное подтверждение ERP",
    },
    "role": {
        "controller": "Контролёр качества",
        "master": "Мастер участка",
        "technologist": "Технолог",
        "manager": "Руководитель производства",
        "admin": "Администратор",
        "simulator_reader": "Симулятор: только чтение",
    },
    "event_type": {
        "item.registered": "Изделие зарегистрировано",
        "operation.started": "Операция начата",
        "operation.finished": "Операция завершена",
        "inspection.result": "Получен результат контроля",
        "machine.state": "Получено состояние оборудования",
        "operator.action": "Зафиксировано действие оператора",
    },
}

ALERT_EXPLANATIONS = {
    "SOURCE_AUTH_FAILED": (
        "Источник не зарегистрирован или не прошёл аутентификацию. Событие отклонено."
    ),
    "SOURCE_SEQUENCE_ANOMALY": (
        "Номер события не продолжает ранее принятую последовательность этого источника."
    ),
    "REPLAY_ATTEMPT": "Повторно получен уже использованный транспортный запрос.",
    "EVENT_ID_CONFLICT": "Получен существующий ID события с другим содержимым.",
    "RAW_LOG_INTEGRITY_FAILED": "Криптографическая проверка исходного журнала не пройдена.",
    "AUDIT_LOG_INTEGRITY_FAILED": "Криптографическая проверка аудита не пройдена.",
    "RBAC_DENIED": "Пользователь попытался выполнить действие, запрещённое его ролью.",
    "INVALID_ACK": "Внешняя ERP вернула неподходящее подтверждение сообщения.",
}


def alert_explanation(alert_type: str | None) -> str:
    return ALERT_EXPLANATIONS.get(str(alert_type or ""), "Требуется проверка технических деталей.")

EVIDENCE_TITLES = {
    "LAST_TRUSTED_GOOD": "Последняя достоверная проверка без дефекта",
    "FIRST_TRUSTED_DEFECT": "Первая достоверная фиксация дефекта",
    "OPERATION_IN_WINDOW": "Операция внутри интервала",
    "MACHINE_WARNING": "Предупреждение оборудования",
    "OPERATOR_ACTION": "Действие оператора",
    "NO_PREVIOUS_TRUSTED_INSPECTION": "Нет надёжной левой границы",
    "CONFLICTING_OBSERVATION": "Конфликт результатов контроля",
    "DEVICE_VALIDITY": "Наблюдение инвалидировано",
    "POOR_OBSERVATION": "Наблюдение не может быть достоверной границей",
    "MISSING_CHECK": "Отсутствует обязательная проверка",
}

ACTUAL_FIELD_LABELS = {
    "ncr": "Несоответствие",
    "ncr_count": "Количество несоответствий",
    "ncr_count_delta": "Новые несоответствия",
    "birth_windows": "Интервалы возникновения",
    "analysis_versions": "Версии анализа",
    "trust": "Доверие к наблюдениям",
    "defect_occurrence_count": "Физические дефекты",
    "item_disposition": "Статус изделия",
    "verification": "Результат верификации",
    "outbox_final_state": "Состояние результата в outbox",
    "accepted_events": "Принятые события",
    "accepted_unique_events": "Уникальные события",
    "duplicate_count": "Повторные доставки",
    "limitations": "Ограничения данных",
    "evidence": "Доказательства",
    "root_cause_status": "Статус причины",
    "observations": "Наблюдения",
    "observation_count": "Количество наблюдений",
}

ACTIVITY_TITLES = {
    "item_registered": "Изделие зарегистрировано",
    "operation_started": "Производственная операция начата",
    "operation_finished": "Производственная операция завершена",
    "inspection_result": "Выполнен контроль",
    "nonconformance_opened": "Создано несоответствие",
    "controller_decision": "Контролёр зафиксировал решение",
    "extra_inspection_requested": "Запрошен дополнительный контроль",
    "rework_started": "Доработка начата",
    "rework_finished": "Доработка завершена",
    "rework_verification": "Контролёр проверил результат доработки",
    "final_disposition": "Зафиксировано итоговое решение по изделию",
    "control_device_invalidated": "Контрольное устройство инвалидировано",
}


def label(value: Any, *, domain: str | None = None) -> str:
    if value is None or value == "":
        return "—"
    raw = str(value)
    if domain and raw in DOMAIN_LABELS.get(domain, {}):
        return DOMAIN_LABELS[domain][raw]
    return LABELS.get(raw, raw)


def format_timestamp(value: Any) -> str:
    if value is None or value == "":
        return "—"
    parsed = value
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return value
    if isinstance(parsed, datetime):
        timezone = f" {parsed.tzname()}" if parsed.tzinfo and parsed.tzname() else ""
        return parsed.strftime("%d.%m.%Y %H:%M:%S") + timezone
    return str(value)


def structure_notice(structure_status: str | None) -> tuple[str, str] | None:
    if structure_status != "degraded":
        return None
    return (
        "Структура компонентов недоступна",
        "Контроль продолжается на уровне изделия.",
    )


def coverage_explanation(coverage: str | None) -> str:
    return {
        "FULL": "Может подтверждать отсутствие дефекта.",
        "PARTIAL": (
            "Проверка достоверна, но покрывает этот тип дефекта только частично. "
            "Поэтому отсутствие дефекта на этой проверке не доказывает, что дефекта не было."
        ),
        "NONE": "Эта проверка не оценивает данный тип дефекта.",
        "TARGET_ONLY": "Применимо только к целевой проверке после доработки.",
    }.get(coverage or "", "Покрытие для этого наблюдения не рассчитано.")


def birth_window_presentation(version: dict[str, Any]) -> dict[str, Any]:
    status = version.get("status")
    evidence = version.get("evidence") or []
    by_type = {row.get("type"): row for row in evidence}
    if status == "BOUNDED":
        explanation = (
            "Дефект мог возникнуть после последней достоверной проверки, где он "
            "отсутствовал, и не позднее первого достоверного обнаружения."
        )
    elif status == "LEFT_OPEN":
        explanation = (
            "До первого достоверного обнаружения нет проверки, которая надёжно "
            "подтверждает отсутствие этого дефекта."
        )
    elif status == "EVIDENCE_INVALIDATED":
        explanation = (
            "Контрольное устройство признано недостоверным. Исходное наблюдение "
            "сохранено, но больше не используется как достоверная граница."
        )
    else:
        explanation = "Границы интервала определены по доступным достоверным наблюдениям."
    return {
        "title": label(status),
        "explanation": explanation,
        "last_good": by_type.get("LAST_TRUSTED_GOOD"),
        "first_defect": by_type.get("FIRST_TRUSTED_DEFECT"),
        "operations": [row for row in evidence if row.get("type") == "OPERATION_IN_WINDOW"],
    }


def evidence_groups(evidence: Iterable[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    groups: dict[str, list[dict[str, Any]]] = {
        "Границы интервала": [],
        "Что происходило внутри интервала": [],
        "Ограничения и проблемы данных": [],
    }
    for row in evidence:
        role = row.get("role")
        if role == "BOUNDARY":
            groups["Границы интервала"].append(row)
        elif role == "CONTEXT":
            groups["Что происходило внутри интервала"].append(row)
        else:
            groups["Ограничения и проблемы данных"].append(row)
    return groups


def evidence_presentation(row: dict[str, Any]) -> dict[str, str]:
    kind = str(row.get("type") or "")
    details = row.get("details") or {}
    observation = row.get("observation") or {}
    trust_status = observation.get("trust_status") or details.get("trust_status")
    context_note = ""
    if kind in {"MACHINE_WARNING", "OPERATOR_ACTION"}:
        context_note = "Контекст, не доказанная причина"
    elif kind == "CONFLICTING_OBSERVATION":
        context_note = (
            "Две эквивалентные проверки дали несовместимые результаты. До разрешения "
            "конфликта ни один результат не используется как достоверная граница."
        )
    elif kind == "DEVICE_VALIDITY":
        context_note = "Причина: контрольное устройство признано недостоверным."
    elif trust_status:
        context_note = label(trust_status)
    return {
        "title": EVIDENCE_TITLES.get(kind, label(kind)),
        "note": context_note,
        "time": format_timestamp(row.get("occurred_at")),
        "event_id": str(row.get("source_event_id") or "—"),
    }


def activity_presentation(row: dict[str, Any]) -> dict[str, Any]:
    activity_type = str(row.get("type") or "")
    details = row.get("details") or {}
    lines: list[str] = []
    if activity_type == "inspection_result":
        lines.append(label(details.get("inspection_result")))
        lines.append(label(details.get("trust_status")))
        if details.get("trust_reasons"):
            lines.append(
                "Основание доверия: "
                + ", ".join(str(value) for value in details["trust_reasons"])
            )
    elif activity_type in {"controller_decision", "extra_inspection_requested"}:
        lines.extend(
            [
                label(details.get("verdict")),
                label(details.get("disposition")),
                str(details.get("reason") or ""),
            ]
        )
    elif activity_type == "rework_verification":
        lines.extend(
            [
                f"Верификация: {label(details.get('verification_status'))}",
                f"Решение: {label(details.get('disposition'))}",
                str(details.get("reason") or ""),
            ]
        )
    elif activity_type == "final_disposition":
        lines.append(label(details.get("disposition")))
    elif activity_type in {"operation_started", "operation_finished", "rework_started", "rework_finished"}:
        if details.get("operation_id"):
            lines.append(f"Операция: {details['operation_id']}")
        if details.get("operation_run_id"):
            lines.append(f"Запуск: {details['operation_run_id']}")
    elif activity_type == "nonconformance_opened":
        lines.append(f"Дефект: {details.get('defect_type') or '—'}")
    elif activity_type == "control_device_invalidated":
        lines.extend(
            [
                f"Устройство: {details.get('device_id') or '—'}",
                f"Причина: {details.get('reason') or '—'}",
            ]
        )
    title = ACTIVITY_TITLES.get(activity_type, label(activity_type))
    if activity_type == "inspection_result" and details.get("is_rework_check"):
        title = "Повторный контроль после доработки"
    return {
        "title": title,
        "time": format_timestamp(row.get("occurred_at")),
        "lines": [line for line in lines if line and line != "—"],
        "event_id": row.get("event_id"),
        "source_id": row.get("source_id"),
        "nonconformance_id": row.get("nonconformance_id"),
    }


def split_nonconformances(
    rows: Iterable[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    all_rows = list(rows)
    pending = [
        row
        for row in all_rows
        if row.get("verdict") in {"pending_review", "needs_extra_check"}
        or row.get("verification_status") == "PENDING"
    ]
    completed = [row for row in all_rows if is_completed_nonconformance(row)]
    return pending, all_rows, completed


def is_completed_nonconformance(row: dict[str, Any]) -> bool:
    return bool(
        row.get("resolved_at")
        or row.get("closed_at")
        or (
            row.get("verdict") in {"confirmed", "rejected"}
            and row.get("disposition") in {"RELEASED", "USE_AS_IS", "SCRAPPED"}
        )
    )


def is_actionable_nonconformance(row: dict[str, Any]) -> bool:
    return not is_completed_nonconformance(row) and (
        row.get("verdict") in {"pending_review", "needs_extra_check"}
        or row.get("verification_status") == "PENDING"
    )


def decision_validation_error(verdict: str, disposition: str, reason: str) -> str | None:
    if len(reason.strip()) < 3:
        return "Укажите обоснование не короче 3 символов."
    if verdict == "rejected" and disposition == "REWORK_REQUIRED":
        return "Отклонённое несоответствие нельзя отправить на доработку."
    return None


def reason_validation_error(reason: str) -> str | None:
    if len(reason.strip()) < 3:
        return "Укажите обоснование не короче 3 символов."
    return None


def api_error_message(
    code: str,
    message: str,
    details: list[dict[str, Any]] | None = None,
) -> str:
    known = {
        "REWORK_NOT_COMPLETED": "Сначала должна быть завершена операция доработки.",
        "EVIDENCE_INTEGRITY_FAILED": (
            "Решение заблокировано: нарушена целостность подтверждающих данных."
        ),
        "BACKEND_UNAVAILABLE": "Сервис TRACE-Q временно недоступен.",
    }
    if code in known:
        return known[code]
    if code == "REQUEST_VALIDATION_ERROR":
        for detail in details or []:
            field = str(detail.get("field") or "")
            error_type = str(detail.get("type") or "")
            detail_message = str(detail.get("message") or "")
            if field.endswith("reason") and (
                "too_short" in error_type or "at least 3" in detail_message
            ):
                return "Укажите обоснование не короче 3 символов."
            if "rejected NCR cannot require rework" in detail_message:
                return "Отклонённое несоответствие нельзя отправить на доработку."
        return "Проверьте заполнение обязательных полей и допустимые значения."
    return message


def scenario_acceptance_checks(result: dict[str, Any]) -> list[dict[str, Any]]:
    expected = result.get("expected") or {}
    actual = result.get("actual") or {}
    failures = [str(value) for value in result.get("failures") or []]
    checks = []
    for key, expected_value in expected.items():
        prefixes = (f"$.{key}", f"$[{key!r}]")
        passed = not any(failure.startswith(prefixes) or failure.startswith("$: ") for failure in failures)
        checks.append(
            {
                "name": ACTUAL_FIELD_LABELS.get(key, key.replace("_", " ")),
                "passed": passed,
                "actual": actual.get(key),
                "expected": expected_value,
            }
        )
    return checks


def actual_state_rows(actual: dict[str, Any]) -> list[dict[str, str]]:
    rows = []
    for key, value in actual.items():
        if isinstance(value, (dict, list)):
            shown = json.dumps(value, ensure_ascii=False, sort_keys=True)
        else:
            shown = label(value) if isinstance(value, str) else str(value)
        rows.append(
            {
                "Показатель": ACTUAL_FIELD_LABELS.get(key, key.replace("_", " ")),
                "Рассчитанное значение": shown,
            }
        )
    return rows


def item_table_rows(items: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "Изделие": row.get("item_id"),
            "Определение": row.get("product_definition_id"),
            "Ревизия": row.get("revision"),
            "Маршрут": row.get("route_code") or "—",
            "Ревизия маршрута": (
                f"v{row['route_revision']}" if row.get("route_revision") else "—"
            ),
            "Линия": row.get("line_id") or "—",
            "Статус": label(row.get("status")),
            "Структура": label(row.get("structure_status")),
            "Зарегистрировано": format_timestamp(row.get("registered_at")),
        }
        for row in items
    ]


def nonconformance_table_rows(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "Изделие": row.get("item_id"),
            "Дефект": row.get("defect_type"),
            "Компонент": row.get("component_instance_id") or "Изделие целиком",
            "Статус решения": label(row.get("verdict")),
            "Решение по изделию": label(row.get("disposition")),
            "Верификация": label(row.get("verification_status")),
            "Открыто": format_timestamp(row.get("opened_at")),
        }
        for row in rows
    ]
