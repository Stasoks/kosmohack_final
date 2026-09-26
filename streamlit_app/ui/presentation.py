from __future__ import annotations

import json
from datetime import date, datetime, time, timedelta, timezone
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

DEFECT_LABELS: dict[str, str] = {
    "surface_crack": "Поверхностная трещина",
    "scratch_or_gouge": "Царапина или задир",
    "dent_or_deformation": "Вмятина или деформация",
    "contamination": "Загрязнение",
    "missing_component": "Отсутствующий компонент",
    "misplaced_component": "Неправильно установленный компонент",
    "burr": "Заусенец",
}

OPERATION_LABELS: dict[str, str] = {
    "OP-INCOMING": "Входной контроль",
    "OP-MILL": "Фрезерование",
    "OP-GRIND": "Шлифование",
    "OP-FINAL": "Финальная операция",
    "OP-REWORK": "Доработка",
    "OP-REWORK-VERIFY": "Контроль после доработки",
    "OP-CLEAN": "Очистка",
    "OP-TURN": "Механическая обработка",
    "OP-ASSEMBLY": "Сборка",
}

ROUTE_LABELS: dict[str, str] = {
    "ROUTE-A": "Маршрут приёмочного сценария",
}

EQUIPMENT_ISSUE_LABELS: dict[str, str] = {
    "SIM_VIBRATION_HIGH": "Повышенная вибрация",
    "VIBRATION_HIGH": "Повышенная вибрация",
    "TEMPERATURE_HIGH": "Повышенная температура",
    "PRESSURE_LOW": "Пониженное давление",
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
        "up_to_date": "Актуально",
        "rebuilding": "Пересчитывается",
        "stale": "Требует внимания",
        "failed": "Ошибка расчёта",
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
    "invalidation_type": {
        "CALIBRATION_FAILURE": "Сбой калибровки",
        "DEVICE_FAILURE": "Неисправность устройства",
        "MISCONFIGURATION": "Ошибка настройки",
        "INCORRECT_CONFIGURATION": "Некорректная конфигурация",
        "OTHER": "Другое",
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

SCENARIO_PRESENTATIONS: dict[str, dict[str, Any]] = {
    "S01": {
        "title": "Нормальный поток без дефекта",
        "proof": "TRACE-Q корректно проводит изделие по маршруту без ложных несоответствий и учитывает его как годное с первого раза.",
        "assertions": [
            ("Производственные события приняты", ("accepted_events",)),
            ("Ложное несоответствие не создано", ("ncr_count",)),
            ("Показатель выпуска с первого раза рассчитан корректно", ("kpi_expectations",)),
        ],
    },
    "S02": {
        "title": "Входной дефект до начала производства",
        "proof": "Дефект, обнаруженный до операций, регистрируется без выдуманной предыдущей границы и без необоснованного назначения причины.",
        "assertions": [
            ("Несоответствие зарегистрировано", ("ncr",)),
            ("Интервал возникновения оставлен открытым слева", ("birth_windows",)),
            ("Причина не назначена автоматически", ("root_cause_status",)),
        ],
    },
    "S03": {
        "title": "Локализация интервала появления дефекта",
        "proof": "Система ограничивает интервал появления дефекта достоверными проверками, а предупреждение оборудования сохраняет только как контекст.",
        "assertions": [
            ("Интервал появления дефекта локализован", ("birth_windows",)),
            ("Подтверждающие факты распределены по ролям", ("evidence",)),
            ("Автоматическое утверждение причины не сделано", ("root_cause_status", "must_not_output")),
        ],
    },
    "S04": {
        "title": "Недостоверный результат контроля не используется как граница",
        "proof": "Результат контроля низкого качества сохраняется, но не сужает интервал появления дефекта.",
        "assertions": [
            ("Недостоверное наблюдение распознано", ("trust",)),
            ("Интервал не сужен ошибочно", ("birth_windows",)),
            ("Ограничение данных объяснено", ("limitations",)),
        ],
    },
    "S05": {
        "title": "Пропущен обязательный контроль",
        "proof": "Пропуск обязательной проверки отмечается как разрыв данных и не создаёт ложную границу анализа.",
        "assertions": [
            ("Пропущенная контрольная точка обнаружена", ("missing_control_point",)),
            ("Разрыв данных отражён в ограничениях", ("limitations",)),
            ("Интервал рассчитан без выдуманных фактов", ("birth_windows",)),
        ],
    },
    "S06": {
        "title": "Повторная доставка события не создаёт дубликат",
        "proof": "Повторная доставка безопасна: TRACE-Q распознаёт дубликат, хранит исходное событие один раз и не искажает показатели.",
        "assertions": [
            ("Повторная доставка распознана", ("duplicate_deliveries",)),
            ("Исходное событие сохранено один раз", ("accepted_unique_events", "raw_event_count")),
            ("Наблюдения и показатели не удвоились", ("observation_count", "kpi_must_not_double_count")),
        ],
    },
    "S07": {
        "title": "Позднее событие корректно перестраивает анализ",
        "proof": "Поздно доставленный достоверный факт создаёт новую версию анализа, не переписывая исходную историю.",
        "assertions": [
            ("Создана новая версия анализа", ("analysis_versions",)),
            ("Исходная история не переписана", ("raw_history_rewritten",)),
        ],
    },
    "S08": {
        "title": "Доработка, повторный контроль и выпуск",
        "proof": "Контролёр назначает доработку, после неё выполняется повторный контроль, а выпуск разрешается только после проверки результата.",
        "assertions": [
            ("Контролёр назначил доработку", ("ncr",)),
            ("Доработка и повторный контроль выполнены", ("rework_count_delta",)),
            ("Изделие разрешено к выпуску", ("item_disposition",)),
        ],
    },
    "S09": {
        "title": "Обнаружение изменения защищённой истории",
        "proof": "Криптографическая проверка обнаруживает изменение сохранённых данных, а обычный производственный API не предоставляет способ такой подмены.",
        "assertions": [
            ("До изменения целостность подтверждена", ("before_tamper",)),
            ("Изменение защищённой записи обнаружено", ("after_tamper",)),
            ("Производственный API не открывает такую операцию", ("production_api_must_not_expose_tamper",)),
        ],
    },
    "S10": {
        "title": "Противоречащие результаты контроля",
        "proof": "Равноправные противоречащие результаты не разрешаются по уверенности автоматически и требуют дополнительной проверки.",
        "assertions": [
            ("Противоречие результатов обнаружено", ("trust_state", "inspection_session")),
            ("Несоответствие требует дополнительной проверки", ("ncr_status",)),
            ("Недостоверные границы не использованы", ("trusted_good_boundary", "trusted_defect_boundary", "birth_window_status")),
        ],
    },
    "S11": {
        "title": "Нет предыдущей достоверной проверки",
        "proof": "Если исторических доказательств нет, TRACE-Q честно оставляет левую границу неизвестной.",
        "assertions": [
            ("Интервал оставлен открытым слева", ("birth_windows",)),
            ("Недостаток исторических данных объяснён", ("limitations",)),
        ],
    },
    "S12": {
        "title": "Несколько типов дефекта в одном результате контроля",
        "proof": "Один результат контроля может описывать несколько физических дефектов; изделия и дефекты при этом считаются раздельно.",
        "assertions": [
            ("Каждый физический дефект учтён отдельно", ("defect_occurrence_count",)),
            ("Изделие не посчитано несколько раз", ("items_with_defects_count",)),
            ("Для дефектов рассчитаны отдельные интервалы", ("birth_windows",)),
        ],
    },
    "S13": {
        "title": "Результат контроля невозможно оценить",
        "proof": "Неоцениваемый результат сохраняется как ограничение и не трактуется ни как отсутствие, ни как наличие дефекта.",
        "assertions": [
            ("Результат отмечен как неоцениваемый", ("trust",)),
            ("Интервал не изменён ошибочно", ("birth_windows",)),
            ("Ограничение данных сохранено", ("limitations",)),
        ],
    },
    "S14": {
        "title": "Один идентификатор события с разным содержимым",
        "proof": "Попытка повторно использовать идентификатор для других данных отклоняется, а исходная запись остаётся неизменной.",
        "assertions": [
            ("Первое событие принято", ("first_delivery",)),
            ("Конфликтующая доставка отклонена", ("second_delivery",)),
            ("Исходная запись сохранена без изменения", ("raw_event_count", "stored_revision")),
        ],
    },
    "S15": {
        "title": "События пришли не по порядку",
        "proof": "Состояние операции восстанавливается по производственному времени, даже если завершение было доставлено раньше начала.",
        "assertions": [
            ("Оба события операции приняты", ("accepted_events",)),
            ("Ход операции восстановлен корректно", ("operation_run",)),
            ("Пересчёт состояния не завершился ошибкой", ("projection_failure",)),
        ],
    },
    "S16": {
        "title": "Доработка не устранила дефект",
        "proof": "Повторное обнаружение того же дефекта не создаёт новый физический дефект и не закрывает исходное несоответствие.",
        "assertions": [
            ("Исходное несоответствие осталось открытым", ("ncr", "item_disposition")),
            ("Физический дефект не продублирован", ("same_defect_occurrence",)),
            ("Проверка доработки зафиксировала неуспех", ("verification",)),
        ],
    },
    "S17": {
        "title": "Инвалидация доказательства и пересчёт",
        "proof": "После признания контрольного устройства недостоверным создаётся новая версия анализа, а предыдущая версия остаётся в истории.",
        "assertions": [
            ("Создана новая версия анализа", ("analysis_versions",)),
            ("Наблюдение исключено из достоверных доказательств", ("derived_trust",)),
            ("Предыдущая версия анализа сохранена", ("old_analysis_preserved",)),
        ],
    },
    "S18": {
        "title": "Радиус влияния без автоматического назначения дефекта",
        "proof": "Система находит потенциально затронутые изделия и создаёт только предложение; дефект и ограничения автоматически не назначаются.",
        "assertions": [
            ("Потенциально затронутые изделия найдены", ("potentially_affected", "must_not_include")),
            ("Дефект автоматически не назначен", ("automatic_defect_assignment",)),
            ("Ограничения автоматически не применены", ("automatic_containment_application", "proposal_actions")),
        ],
    },
    "S19": {
        "title": "Недоступность внешней системы и повторная доставка",
        "proof": "Решение контролёра сохраняется при недоступности ERP, а одно и то же сообщение безопасно доставляется после восстановления.",
        "assertions": [
            ("Решение контролёра сохранено", ("controller_decision_committed", "decision_must_not_rollback")),
            ("Отправка восстановлена после повторной попытки", ("outbox_final_state",)),
            ("Повтор использовал то же сообщение", ("same_message_id_on_retry",)),
        ],
    },
    "S20": {
        "title": "Неавторизованный источник контроля отклонён",
        "proof": "Событие от неизвестного источника не попадает в производственную историю и создаёт оповещение безопасности.",
        "assertions": [
            ("Запрос источника отклонён", ("http_status",)),
            ("Производственные записи не созданы", ("raw_event_count_delta", "ncr_count_delta")),
            ("Создано оповещение безопасности", ("security_alert",)),
        ],
    },
    "S21": {
        "title": "Защита от повтора запроса и безопасная повторная доставка",
        "proof": "TRACE-Q отличает транспортную атаку повтора от нормальной повторной доставки уже принятого бизнес-события.",
        "assertions": [
            ("Первый подписанный запрос принят", ("REQ-S21-1",)),
            ("Повтор транспортного запроса отклонён", ("REQ-S21-2-REPLAY",)),
            ("Повторная доставка события распознана как дубликат", ("REQ-S21-3-LEGIT-RETRY", "raw_event_count")),
        ],
    },
    "S22": {
        "title": "Разделение полномочий и контролируемый выпуск",
        "proof": "Администратор не может подменить контролёра, а результат не отправляется наружу до разрешённого решения.",
        "assertions": [
            ("Запрещённое решение администратора отклонено", ("admin_issue_qc_decision",)),
            ("Преждевременный выпуск заблокирован", ("export_before_controller_disposition",)),
            ("Разрешённое решение и выпуск зафиксированы в аудите", ("controller_decision", "export_after_disposition", "audit_entries_required")),
        ],
    },
    "S23": {
        "title": "Работа без структуры компонентов",
        "proof": "Отсутствие структуры изделия не блокирует контроль: анализ продолжается на уровне изделия целиком.",
        "assertions": [
            ("Отсутствие структуры распознано", ("component_structure",)),
            ("Процесс контроля не заблокирован", ("workflow_blocked",)),
            ("Дефект и интервал рассчитаны на уровне изделия", ("defect_key", "birth_window_status")),
        ],
    },
    "S24": {
        "title": "Изделие сохраняет назначенную версию маршрута",
        "proof": "Изменение действующего маршрута влияет только на новые изделия и не переписывает маршрут уже запущенного изделия.",
        "assertions": [
            ("Старое изделие осталось на исходной версии", ("ITEM-S24-OLD",)),
            ("Новое изделие получило новую версию", ("ITEM-S24-NEW",)),
            ("История маршрута не переписана", ("old_route_rewritten",)),
        ],
    },
    "S25": {
        "title": "Проверка производственных показателей",
        "proof": "Изделия, сигналы контроля, физические дефекты, решения контролёра и доработки учитываются раздельно.",
        "assertions": [
            ("Проверенные изделия посчитаны корректно", ("population_items", "inspected_items", "assessable_inspected_items")),
            ("Подтверждённые несоответствия и дефекты разделены", ("items_with_confirmed_nonconformities", "unique_confirmed_defect_occurrences", "confirmed_defects_by_type")),
            ("Доработки и отклонённые сигналы учтены корректно", ("rework_count", "rework_item_count", "rejected_signal_must_not_count_as_confirmed_nc")),
        ],
    },
}


def label(value: Any, *, domain: str | None = None) -> str:
    if value is None or value == "":
        return "—"
    raw = str(value)
    if domain and raw in DOMAIN_LABELS.get(domain, {}):
        return DOMAIN_LABELS[domain][raw]
    return LABELS.get(raw, raw)


def defect_label(value: Any) -> str:
    if value is None or value == "":
        return "—"
    raw = str(value)
    return DEFECT_LABELS.get(raw, raw)


def operation_label(operation_id: Any, operation_name: Any = None) -> str:
    if operation_name:
        return str(operation_name)
    if operation_id is None or operation_id == "":
        return "Операция"
    raw = str(operation_id)
    return OPERATION_LABELS.get(raw, raw)


def route_name_label(route_name: Any, route_code: Any = None) -> str:
    raw_code = str(route_code or "")
    return ROUTE_LABELS.get(raw_code, str(route_name or "Маршрут"))


def route_revision_label(
    route_name: Any, revision: Any, *, route_code: Any = None
) -> str:
    name = route_name_label(route_name, route_code)
    return f"{name} · Версия {revision}" if revision not in (None, "") else name


def equipment_issue_label(code: Any) -> str:
    if code is None or code == "":
        return "Предупреждение оборудования"
    raw = str(code)
    return EQUIPMENT_ISSUE_LABELS.get(raw, raw)


def control_device_label(device_id: Any) -> str:
    raw = str(device_id or "")
    if raw == "SIM-CAMERA-01":
        return "Камера симулятора"
    if raw.startswith("CAM-"):
        return f"Камера контроля · {raw}"
    return f"Контрольное устройство · {raw}" if raw else "Контрольное устройство"


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


def short_timestamp(value: Any) -> str:
    parsed = value
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return "—"
    if isinstance(parsed, datetime):
        return parsed.strftime("%H:%M:%S")
    return "—"


def utc_iso(date_value: date, time_value: time) -> str:
    combined = datetime.combine(date_value, time_value).replace(tzinfo=timezone.utc)
    return combined.isoformat().replace("+00:00", "Z")


def period_validation_error(affected_from: str, affected_to: str) -> str | None:
    try:
        start = datetime.fromisoformat(affected_from.replace("Z", "+00:00"))
        end = datetime.fromisoformat(affected_to.replace("Z", "+00:00"))
    except ValueError:
        return "Проверьте дату и время начала и окончания периода."
    if end < start:
        return "Окончание периода не может быть раньше его начала."
    return None


def control_device_invalidation_payload(
    *,
    device_id: str,
    affected_from_date: date,
    affected_from_time: time,
    affected_to_date: date,
    affected_to_time: time,
    reason: str,
    invalidation_type: str,
) -> dict[str, Any]:
    return {
        "device_id": device_id,
        "affected_from": utc_iso(affected_from_date, affected_from_time),
        "affected_to": utc_iso(affected_to_date, affected_to_time),
        "reason": reason,
        "invalidation_type": invalidation_type,
        "supporting_evidence_refs": [],
    }


def equipment_issue_suggestion(
    issue: dict[str, Any], *, window_minutes: int = 30
) -> dict[str, Any]:
    raw_at = issue.get("occurred_at")
    occurred_at = (
        raw_at
        if isinstance(raw_at, datetime)
        else datetime.fromisoformat(str(raw_at).replace("Z", "+00:00"))
    )
    if occurred_at.tzinfo is None:
        occurred_at = occurred_at.replace(tzinfo=timezone.utc)
    occurred_at = occurred_at.astimezone(timezone.utc)
    return {
        "factor_type": "equipment",
        "factor_value": str(issue.get("equipment_id") or ""),
        "affected_from": occurred_at - timedelta(minutes=window_minutes),
        "affected_to": occurred_at,
    }


def duration_label(value: Any) -> str:
    if value is None:
        return "Недостаточно данных"
    seconds = float(value)
    if seconds >= 3600:
        return f"{seconds / 3600:.1f} ч"
    if seconds >= 60:
        return f"{seconds / 60:.1f} мин"
    return f"{seconds:.1f} сек"


def percentage_label(value: Any) -> str:
    return "Недостаточно данных" if value is None else f"{float(value):.1%}"


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
    tone = "normal"
    if activity_type == "inspection_result":
        inspection_result = details.get("inspection_result")
        if inspection_result == "defect_detected":
            title = "Контроль: обнаружен дефект"
            tone = "warning"
        elif inspection_result == "no_defect":
            title = "Контроль: дефект не обнаружен"
        else:
            title = f"Контроль: {label(inspection_result)}"
        if details.get("trust_status") in {"CONFLICTED", "INVALIDATED", "UNTRUSTED"}:
            lines.append(label(details.get("trust_status")))
            tone = "critical"
        if details.get("trust_status") == "CONFLICTED":
            title = "Конфликт результатов контроля"
            lines.append(
                "До разрешения конфликта результаты не используются как достоверная граница"
            )
    elif activity_type in {"controller_decision", "extra_inspection_requested"}:
        title = (
            "Запрошен дополнительный контроль"
            if activity_type == "extra_inspection_requested"
            else "Контролёр зафиксировал решение"
        )
        lines.extend(
            [
                label(details.get("verdict")),
                label(details.get("disposition")),
                str(details.get("reason") or ""),
            ]
        )
        if details.get("disposition") == "REWORK_REQUIRED":
            title = "Контролёр назначил доработку"
            tone = "action"
    elif activity_type == "rework_verification":
        title = "Контролёр проверил результат доработки"
        lines.extend(
            [
                f"Верификация: {label(details.get('verification_status'))}",
                f"Решение: {label(details.get('disposition'))}",
                str(details.get("reason") or ""),
            ]
        )
    elif activity_type == "final_disposition":
        title = "Зафиксировано итоговое решение по изделию"
        lines.append(label(details.get("disposition")))
    elif activity_type in {"operation_started", "operation_finished", "rework_started", "rework_finished"}:
        operation = operation_label(details.get("operation_id"), details.get("operation_name"))
        if activity_type == "operation_started":
            title = f"Операция «{operation}» начата"
        elif activity_type == "operation_finished":
            title = f"Операция «{operation}» завершена"
        elif activity_type == "rework_started":
            title = "Доработка начата"
        else:
            title = "Доработка завершена"
    elif activity_type == "nonconformance_opened":
        title = f"Обнаружено несоответствие: {defect_label(details.get('defect_type'))}"
        lines.append("Требуется решение контролёра")
        tone = "critical"
    elif activity_type == "control_device_invalidated":
        title = "Результаты контрольного устройства признаны недостоверными"
        lines.extend(
            [
                f"Причина: {details.get('reason') or '—'}",
            ]
        )
        tone = "critical"
    else:
        title = ACTIVITY_TITLES.get(activity_type, label(activity_type))
    if activity_type == "inspection_result" and details.get("is_rework_check"):
        result = details.get("inspection_result")
        title = (
            "Повторный контроль: дефект не обнаружен"
            if result == "no_defect"
            else "Повторный контроль: дефект обнаружен"
        )
    return {
        "title": title,
        "time": format_timestamp(row.get("occurred_at")),
        "short_time": short_timestamp(row.get("occurred_at")),
        "tone": tone,
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


def scenario_title(scenario_id: str, fallback: str | None = None) -> str:
    presentation = SCENARIO_PRESENTATIONS.get(scenario_id) or {}
    return str(presentation.get("title") or fallback or scenario_id)


def scenario_proof(scenario_id: str, fallback: str | None = None) -> str:
    presentation = SCENARIO_PRESENTATIONS.get(scenario_id) or {}
    return str(
        presentation.get("proof")
        or fallback
        or "Сценарий подтверждает заявленные бизнес-инварианты TRACE-Q."
    )


def scenario_human_checks(result: dict[str, Any]) -> list[dict[str, Any]]:
    scenario_id = str(result.get("scenario") or "")
    presentation = SCENARIO_PRESENTATIONS.get(scenario_id) or {}
    assertions = presentation.get("assertions") or []
    failures = [str(value) for value in result.get("failures") or []]
    if not assertions:
        return [
            {"name": row["name"], "passed": row["passed"]}
            for row in scenario_acceptance_checks(result)
        ]
    checks = []
    for name, keys in assertions:
        prefixes = tuple(
            prefix
            for key in keys
            for prefix in (f"$.{key}", f"$[{key!r}]")
        )
        passed = not any(
            failure.startswith(prefixes) or failure.startswith("$: ")
            for failure in failures
        )
        checks.append({"name": name, "passed": passed})
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


def item_table_rows(
    items: Iterable[dict[str, Any]],
    route_names: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    route_names = route_names or {}
    return [
        {
            "Изделие": row.get("item_id"),
            "Определение": row.get("product_definition_id"),
            "Ревизия": row.get("revision"),
            "Маршрут": route_names.get(
                str(row.get("route_code") or ""), row.get("route_code") or "—"
            ),
            "Версия маршрута": row.get("route_revision") or "—",
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
            "Дефект": defect_label(row.get("defect_type")),
            "Компонент": row.get("component_instance_id") or "Изделие целиком",
            "Статус решения": label(row.get("verdict")),
            "Решение по изделию": label(row.get("disposition")),
            "Верификация": label(row.get("verification_status")),
            "Открыто": format_timestamp(row.get("opened_at")),
        }
        for row in rows
    ]


def defect_chart_rows(values: dict[str, Any] | None) -> list[dict[str, Any]]:
    return [
        {"Тип дефекта": defect_label(defect_type), "Количество": int(count)}
        for defect_type, count in sorted(
            (values or {}).items(), key=lambda row: (-int(row[1]), row[0])
        )
    ]


def detection_chart_rows(values: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "Место обнаружения": " · ".join(
                value
                for value in (
                    str(row.get("line_id") or "Линия не указана"),
                    str(row.get("station_id") or "Станция не указана"),
                )
                if value
            ),
            "Количество": int(row.get("count") or 0),
        }
        for row in values
    ]


def cause_chart_rows(kpi: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "Статус причины": "Причина подтверждена человеком",
            "Количество": int(kpi.get("established_causes") or 0),
        },
        {
            "Статус причины": "Причина не установлена",
            "Количество": int(kpi.get("unknown_causes") or 0),
        },
    ]


def simulator_feed_message(row: dict[str, Any]) -> str:
    if row.get("status") == "waiting":
        return str(row.get("message") or "Ожидается действие пользователя")
    event_type = row.get("event_type")
    return {
        "item.registered": "Изделие зарегистрировано",
        "operator.action": "Оператор подтвердил этап маршрута",
        "operation.started": "Производственная операция начата",
        "operation.finished": "Производственная операция завершена",
        "inspection.result": "Результат контроля принят TRACE-Q",
        "machine.state": "Предупреждение оборудования принято TRACE-Q",
    }.get(str(event_type or ""), str(row.get("message") or "Событие обработано"))
