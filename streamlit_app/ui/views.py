from __future__ import annotations

import json
from functools import wraps
from typing import Callable

import streamlit as st

from streamlit_app.api_client.client import APIError, logout, request
from streamlit_app.ui.presentation import (
    activity_presentation,
    actual_state_rows,
    api_error_message,
    birth_window_presentation,
    coverage_explanation,
    decision_validation_error,
    evidence_groups,
    evidence_presentation,
    format_timestamp,
    is_actionable_nonconformance,
    is_completed_nonconformance,
    item_table_rows,
    label,
    nonconformance_table_rows,
    reason_validation_error,
    scenario_acceptance_checks,
    split_nonconformances,
    structure_notice,
)


def guarded(render: Callable[[], None]) -> Callable[[], None]:
    @wraps(render)
    def wrapped() -> None:
        try:
            render()
        except APIError as exc:
            st.error(api_error_message(exc.code, exc.message, exc.details))
            st.caption(f"Технический код: {exc.code}")
            if exc.status_code == 401:
                st.rerun()

    return wrapped


def header(title: str) -> None:
    profile = st.session_state.profile
    left, right = st.columns([5, 1])
    left.title(title)
    left.caption(f"{profile['username']} · {', '.join(profile['roles'])}")
    if right.button("Выйти", use_container_width=True):
        logout()
        st.rerun()


def technical_data(value, title: str = "Технические данные") -> None:
    with st.expander(title):
        st.json(value, expanded=False)


def overview() -> None:
    header("TRACE-Q · Обзор")
    permissions = set(st.session_state.profile["permissions"])
    if "VIEW_PRODUCT" in permissions:
        items = request("GET", "/api/v1/items")
        st.subheader("Изделия")
        st.dataframe(item_table_rows(items), use_container_width=True, hide_index=True)
        if any(item.get("structure_status") == "degraded" for item in items):
            st.info(
                "Для части изделий структура компонентов недоступна. "
                "Контроль продолжается на уровне изделия."
            )
    if "VIEW_NONCONFORMANCE" in permissions:
        ncrs = request("GET", "/api/v1/nonconformances")
        st.subheader("Несоответствия")
        st.dataframe(nonconformance_table_rows(ncrs), use_container_width=True, hide_index=True)
    if "MANAGE_USERS" in permissions:
        users = request("GET", "/api/v1/admin/users")
        st.subheader("Пользователи")
        st.dataframe(users, use_container_width=True, hide_index=True)


def pending_reviews() -> None:
    header("Решения QC")
    rows = request("GET", "/api/v1/nonconformances")
    pending, all_rows, completed = split_nonconformances(rows)
    tabs = st.tabs(
        [
            f"Ожидают решения · {len(pending)}",
            f"Все несоответствия · {len(all_rows)}",
            f"Завершённые · {len(completed)}",
        ]
    )
    for tab, values, empty_message in (
        (tabs[0], pending, "Нет несоответствий, ожидающих решения."),
        (tabs[1], all_rows, "Несоответствия ещё не зарегистрированы."),
        (tabs[2], completed, "Завершённых несоответствий пока нет."),
    ):
        with tab:
            if values:
                st.dataframe(
                    nonconformance_table_rows(values),
                    use_container_width=True,
                    hide_index=True,
                )
            else:
                st.info(empty_message)

    if not all_rows:
        return
    labels = {
        f"{row['item_id']} · {row['defect_type']} · {label(row['verdict'])}": row["id"]
        for row in all_rows
    }
    selected = labels[st.selectbox("Карточка несоответствия", labels)]
    card = request("GET", f"/api/v1/nonconformances/{selected}")
    st.subheader(f"Несоответствие · {card['defect_type']}")
    metrics = st.columns(4)
    metrics[0].metric("Статус решения", label(card.get("verdict")))
    metrics[1].metric("Решение по изделию", label(card.get("disposition")))
    metrics[2].metric("Локализация", label(card.get("containment"), domain="containment"))
    metrics[3].metric("Верификация", label(card.get("verification_status")))
    details_metrics = st.columns(2)
    details_metrics[0].metric("Способ завершения", label(card.get("resolution_type")))
    details_metrics[1].metric(
        "Текущая версия анализа", card.get("current_analysis_version") or "—"
    )
    st.caption(
        f"Открыто: {format_timestamp(card.get('opened_at'))} · "
        f"Завершено: {format_timestamp(card.get('resolved_at') or card.get('closed_at'))}"
    )
    if is_completed_nonconformance(card):
        st.success("Несоответствие завершено. Карточка доступна только для просмотра.")

    decisions = card.get("decisions") or []
    if decisions:
        st.markdown("#### Решения контролёра")
        st.dataframe(
            [
                {
                    "Время": format_timestamp(row.get("created_at")),
                    "Вердикт": label(row.get("verdict")),
                    "Решение": label(row.get("disposition")),
                    "Локализация": label(row.get("containment"), domain="containment"),
                    "Обоснование": row.get("reason"),
                    "Версия анализа": row.get("analysis_version"),
                }
                for row in decisions
            ],
            use_container_width=True,
            hide_index=True,
        )
    technical_data(card)

    if card.get("verdict") in {"pending_review", "needs_extra_check"}:
        with st.form("decision"):
            verdict = st.selectbox(
                "Вердикт", ["confirmed", "rejected"], format_func=label
            )
            disposition = st.selectbox(
                "Решение по изделию",
                ["IN_PROCESS", "REWORK_REQUIRED", "RELEASED", "USE_AS_IS", "SCRAPPED"],
                format_func=label,
            )
            containment = st.selectbox(
                "Локализация",
                ["REVIEW_REQUIRED", "HOLD", "REINSPECTION_REQUIRED", "NONE"],
                format_func=lambda value: label(value, domain="containment"),
            )
            reason = st.text_area("Обоснование")
            submitted = st.form_submit_button("Сохранить решение")
            if submitted:
                validation_error = decision_validation_error(verdict, disposition, reason)
                if validation_error:
                    st.error(validation_error)
                else:
                    result = request(
                        "POST",
                        f"/api/v1/nonconformances/{selected}/decision",
                        json={
                            "verdict": verdict,
                            "disposition": disposition,
                            "containment": containment,
                            "reason": reason,
                        },
                    )
                    st.success("Решение сохранено.")
                    if result.get("message_id"):
                        st.caption(f"Outbox message: {result['message_id']}")
                    st.rerun()

    if not is_completed_nonconformance(card):
        with st.expander("Запросить дополнительный контроль"):
            extra_reason = st.text_input("Причина", key="extra_reason")
            control_point = st.text_input("Контрольная точка", key="extra_cp")
            if st.button("Запросить"):
                validation_error = reason_validation_error(extra_reason)
                if validation_error:
                    st.error(validation_error)
                else:
                    request(
                        "POST",
                        f"/api/v1/nonconformances/{selected}/request-inspection",
                        json={"reason": extra_reason, "control_point_id": control_point or None},
                    )
                    st.success("Дополнительный контроль запрошен")
    if card.get("verification_status") == "PENDING":
        st.info("Доработка ожидает верификации контролёром.")
        with st.form("verify_rework"):
            passed = st.checkbox("Повторный контроль подтверждает устранение дефекта")
            verification_reason = st.text_area("Обоснование верификации")
            if st.form_submit_button("Зафиксировать верификацию"):
                validation_error = reason_validation_error(verification_reason)
                if validation_error:
                    st.error(validation_error)
                else:
                    result = request(
                        "POST",
                        f"/api/v1/nonconformances/{selected}/verify-rework",
                        json={"passed": passed, "reason": verification_reason},
                    )
                    st.success(f"Верификация: {label(result['verification_status'])}")
                    st.rerun()
    elif is_actionable_nonconformance(card):
        st.caption("Для этого несоответствия доступно решение контролёра.")


def timeline() -> None:
    header("История изделия")
    items = request("GET", "/api/v1/items")
    if not items:
        st.info("Изделия ещё не зарегистрированы.")
        return
    item_id = st.selectbox("Изделие", [item["item_id"] for item in items])
    item = request("GET", f"/api/v1/items/{item_id}")
    timeline_value = request("GET", f"/api/v1/items/{item_id}/timeline")
    analyses = request("GET", f"/api/v1/items/{item_id}/analysis")
    cols = st.columns(3)
    cols[0].metric("Статус изделия", label(item.get("status")))
    cols[1].metric("Ревизия", item.get("revision") or "—")
    cols[2].metric("Структура", label(item.get("structure_status")))
    notice = structure_notice(item.get("structure_status"))
    if notice:
        st.info(f"**{notice[0]}**  \n{notice[1]}")
    technical_data(item, "Технические данные изделия")

    st.subheader("История действий и решений")
    activity = timeline_value.get("activity") or []
    if not activity:
        st.info("Для изделия пока нет записей в истории.")
    for row in activity:
        shown = activity_presentation(row)
        if row.get("type") == "control_device_invalidated":
            st.warning(f"**{shown['time']} — {shown['title']}**")
        elif (row.get("details") or {}).get("trust_status") == "CONFLICTED":
            st.warning(f"**{shown['time']} — Конфликт результатов контроля**")
            st.write(
                "Две эквивалентные проверки дали несовместимые результаты. До разрешения "
                "конфликта ни один результат не используется как достоверная граница."
            )
        else:
            st.markdown(f"**{shown['time']} — {shown['title']}**")
        if shown["lines"]:
            st.write(" · ".join(shown["lines"]))
        coverage_rows = (row.get("details") or {}).get("coverage") or []
        for coverage in coverage_rows:
            st.caption(
                f"{coverage.get('defect_type')}: "
                f"{label(coverage.get('coverage'), domain='coverage')} — "
                f"{coverage_explanation(coverage.get('coverage'))}"
            )
        technical_bits = [
            value
            for value in (
                f"event {shown['event_id']}" if shown.get("event_id") else None,
                f"source {shown['source_id']}" if shown.get("source_id") else None,
                f"NCR {shown['nonconformance_id']}" if shown.get("nonconformance_id") else None,
            )
            if value
        ]
        if technical_bits:
            st.caption(" · ".join(technical_bits))
        st.divider()

    with st.expander("Техническая история событий"):
        st.dataframe(timeline_value["events"], use_container_width=True, hide_index=True)

    st.subheader("Интервалы возникновения дефектов")
    if not analyses:
        st.info("Для изделия нет анализа несоответствий.")
    for analysis in analyses:
        with st.expander(
            f"{analysis['defect_type']} · {label(analysis['cause_status'])}", expanded=True
        ):
            st.info(
                "События внутри интервала являются контекстом. "
                "TRACE-Q не назначает причину автоматически."
            )
            for index, version in enumerate(analysis["versions"]):
                if index:
                    reason = version.get("reason") or "пересчёт производных данных"
                    if "invalid" in reason.lower():
                        reason = "инвалидация контрольного устройства"
                    st.markdown(f"↓ **Почему изменилось:** {reason}")
                summary = birth_window_presentation(version)
                st.markdown(
                    f"### Analysis v{version['version']} · {summary['title']}"
                )
                st.caption(f"Технический статус: {version['status']}")
                st.write(summary["explanation"])
                boundaries = st.columns(2)
                if summary["last_good"]:
                    boundaries[0].markdown("**Последняя достоверная проверка без дефекта**")
                    boundaries[0].write(format_timestamp(summary["last_good"].get("occurred_at")))
                    boundaries[0].caption(
                        f"event id: {summary['last_good'].get('source_event_id') or '—'}"
                    )
                else:
                    boundaries[0].markdown("**Последняя достоверная проверка без дефекта**")
                    boundaries[0].write("Отсутствует")
                boundaries[1].markdown("**Первая достоверная фиксация дефекта**")
                boundaries[1].write(
                    format_timestamp(
                        (summary["first_defect"] or {}).get("occurred_at")
                        or version.get("right_boundary_at")
                    )
                )
                boundaries[1].caption(
                    f"event id: {(summary['first_defect'] or {}).get('source_event_id') or '—'}"
                )
                if summary["operations"]:
                    st.markdown("**Операции внутри интервала**")
                    for operation in summary["operations"]:
                        details = operation.get("details") or {}
                        st.write(
                            f"{format_timestamp(operation.get('occurred_at'))} — "
                            f"{details.get('operation_id') or details.get('operation_run_id') or 'Операция'}"
                        )

                for group_name, evidence in evidence_groups(version["evidence"]).items():
                    if not evidence:
                        continue
                    st.markdown(f"#### {group_name}")
                    for evidence_row in evidence:
                        shown = evidence_presentation(evidence_row)
                        if evidence_row.get("type") == "CONFLICTING_OBSERVATION":
                            st.warning(f"**{shown['title']}** — {shown['note']}")
                        elif evidence_row.get("type") == "DEVICE_VALIDITY":
                            st.warning(f"**{shown['title']}** — {shown['note']}")
                        else:
                            st.markdown(f"**{shown['title']}**")
                            if shown["note"]:
                                st.caption(shown["note"])
                        st.write(
                            f"{shown['time']} · event id: {shown['event_id']}"
                        )
                        coverage = evidence_row.get("coverage")
                        if coverage:
                            st.write(
                                f"Покрытие: **{label(coverage, domain='coverage')}** — "
                                f"{coverage_explanation(coverage)}"
                            )
                        observation = evidence_row.get("observation") or {}
                        if observation:
                            st.caption(
                                " · ".join(
                                    str(value)
                                    for value in (
                                        f"source: {observation.get('source_id')}"
                                        if observation.get("source_id")
                                        else None,
                                        label(observation.get("inspection_result")),
                                        label(observation.get("trust_status")),
                                    )
                                    if value
                                )
                            )
                technical_data(version, "Технические данные AnalysisVersion")


def analytics() -> None:
    header("Производственная аналитика")
    kpi = request("GET", "/api/v1/analytics/kpi")
    cols = st.columns(4)
    cols[0].metric("Проверено изделий", kpi["inspected_items"])
    cols[1].metric("Подтверждённые НС", kpi["items_with_confirmed_nc"])
    cols[2].metric("Физические дефекты", kpi["number_of_unique_defects"])
    fpy = kpi.get("first_pass_yield")
    cols[3].metric("First Pass Yield", "—" if fpy is None else f"{fpy:.1%}")
    technical_data(kpi, "Технические данные KPI")


def data_health() -> None:
    header("Состояние данных")
    st.json(request("GET", "/api/v1/analytics/data-health"), expanded=True)


def route_editor() -> None:
    header("Редактор маршрутов")
    routes = request("GET", "/api/v1/routes")
    if routes:
        labels = {f"{route['code']} · {route['name']}": route for route in routes}
        route = labels[st.selectbox("Маршрут", labels)]
        st.json(route, expanded=False)
        revisions = route["revisions"]
        base = revisions[-1]["steps"] if revisions else []
        default_json = json.dumps(
            [
                {
                    "operation_id": step["operation_id"],
                    "operation_name": step["operation_name"],
                    "station_id": step.get("station_id"),
                    "control_point_id": step["control_point_id"],
                    "required": step["required"],
                    "inspection_scope": step["inspection_scope"],
                }
                for step in base
            ],
            ensure_ascii=False,
            indent=2,
        )
        st.caption("Таблица поддерживает добавление и удаление строк; позиция задаёт порядок.")
        editable = [{"position": i + 1, "operation_id": step["operation_id"], "operation_name": step["operation_name"],
                     "station_id": step.get("station_id"), "control_point_id": step["control_point_id"],
                     "required": step["required"]} for i, step in enumerate(base)]
        edited = st.data_editor(editable, num_rows="dynamic", use_container_width=True, key="route_steps")
        edited = sorted(edited, key=lambda row: row.get("position", 0))
        steps_text = json.dumps([{k: v for k, v in row.items() if k != "position"} for row in edited], ensure_ascii=False)
        if st.button("Клонировать и сохранить новую revision"):
            result = request(
                "POST", f"/api/v1/routes/{route['id']}/revisions", json={"steps": json.loads(steps_text)}
            )
            st.success(f"Создана revision {result['revision']}")
            st.rerun()
        draft_ids = [revision["id"] for revision in revisions if revision["status"] == "draft"]
        if draft_ids:
            draft = st.selectbox("Draft revision", draft_ids)
            activation_reason = st.text_input("Причина активации")
            if st.button("Активировать"):
                request("POST", f"/api/v1/routes/{route['id']}/activate", params={"revision_id": draft, "reason": activation_reason})
                st.success("Revision активирована")
                st.rerun()
    with st.expander("Импорт маршрута JSON"):
        payload = st.text_area("Route JSON", key="route_import")
        if st.button("Импортировать") and payload:
            st.json(request("POST", "/api/v1/routes/import", json=json.loads(payload)))


def admin_panel() -> None:
    header("Администрирование")
    tabs = st.tabs(["Пользователи", "Источники", "Интеграции", "Аудит", "Целостность", "Security Alerts"])
    with tabs[0]:
        users = request("GET", "/api/v1/admin/users")
        st.dataframe(users, use_container_width=True, hide_index=True)
        with st.expander("Создать пользователя"):
            with st.form("create_user"):
                username = st.text_input("Логин")
                display_name = st.text_input("Отображаемое имя")
                password = st.text_input("Пароль", type="password")
                roles = st.multiselect(
                    "Роли",
                    ["controller", "master", "technologist", "manager", "admin"],
                )
                if st.form_submit_button("Создать"):
                    result = request(
                        "POST",
                        "/api/v1/admin/users",
                        json={
                            "username": username,
                            "display_name": display_name,
                            "password": password,
                            "roles": roles,
                        },
                    )
                    st.success(f"Создан пользователь {result['username']}")
                    st.rerun()
    with tabs[1]:
        sources = request("GET", "/api/v1/admin/sources")
        st.dataframe(sources, use_container_width=True, hide_index=True)
        with st.expander("Зарегистрировать источник"):
            with st.form("create_source"):
                source_id = st.text_input("Source ID")
                source_type = st.text_input("Source type")
                auth_method = st.selectbox("Аутентификация", ["shared_secret_legacy", "HMAC_V1"])
                event_types = st.multiselect(
                    "Разрешённые события",
                    [
                        "item.registered",
                        "operation.started",
                        "operation.finished",
                        "inspection.result",
                        "machine.state",
                        "operator.action",
                        "control_device.invalidated",
                    ],
                )
                key_id = st.text_input("HMAC key_id (для HMAC_V1)")
                line_ids = st.text_input("Line IDs через запятую")
                station_ids = st.text_input("Station IDs через запятую")
                if st.form_submit_button("Создать источник"):
                    body = {
                        "source_id": source_id,
                        "source_type": source_type,
                        "auth_method": auth_method,
                        "allowed_event_types": event_types,
                        "allowed_line_ids": [x.strip() for x in line_ids.split(",") if x.strip()],
                        "allowed_station_ids": [x.strip() for x in station_ids.split(",") if x.strip()],
                    }
                    if auth_method == "HMAC_V1" and key_id:
                        body["key_id"] = key_id
                    result = request("POST", "/api/v1/admin/sources", json=body)
                    if result.get("token"):
                        st.warning("Токен показывается один раз. Сохраните его сейчас.")
                        st.code(result["token"])
                    else:
                        st.success(f"Источник {result['source_id']} зарегистрирован")
                    st.rerun()
    with tabs[2]:
        st.json(request("GET", "/api/v1/integrations"), expanded=True)
        if st.button("Синхронизировать ERP"):
            st.json(request("POST", "/api/v1/integrations/erp/sync"))
    with tabs[3]:
        st.dataframe(request("GET", "/api/v1/admin/audit"), use_container_width=True, hide_index=True)
    with tabs[4]:
        st.json(request("GET", "/api/v1/admin/crypto-profile"), expanded=False)
        if st.button("Verify Integrity", type="primary"):
            result = request("POST", "/api/v1/admin/integrity/verify")
            (st.success if result["status"] == "OK" else st.error)(result["status"])
            st.json(result)
        item_id = st.text_input("Item ID для replay")
        if st.button("Rebuild") and item_id:
            st.json(request("POST", f"/api/v1/admin/rebuild/{item_id}"))
    with tabs[5]:
        st.dataframe(request("GET", "/api/v1/admin/security-alerts"), use_container_width=True, hide_index=True)


def blast_radius() -> None:
    header("Risk, Blast Radius и invalidation")
    permissions = set(st.session_state.profile["permissions"])

    if "RUN_BLAST_RADIUS" in permissions:
        st.subheader("Blast Radius")
        with st.form("blast_radius"):
            factor_type = st.selectbox("Фактор", ["equipment", "tool", "material_lot", "control_device", "component", "time_interval"])
            factor_value = st.text_input("ID / значение")
            affected_from = st.text_input("Начало ISO-8601", key="blast_from")
            affected_to = st.text_input("Конец ISO-8601", key="blast_to")
            action = st.selectbox("Предложение", ["REVIEW_REQUIRED", "REINSPECTION_REQUIRED", "HOLD"])
            rationale = st.text_area("Обоснование")
            if st.form_submit_button("Рассчитать и создать proposal"):
                result = request("POST", "/api/v1/risk/blast-radius", json={
                    "factor_type": factor_type,
                    "factor_value": factor_value,
                    "affected_from": affected_from,
                    "affected_to": affected_to,
                    "proposed_action": action,
                    "rationale": rationale,
                })
                st.warning("Расчёт сам по себе не создаёт дефект и не применяет containment.")
                st.json(result)

    if "APPROVE_CONTAINMENT" in permissions:
        st.subheader("Ожидающие approvals")
        approvals = request("GET", "/api/v1/risk/approvals")
        if approvals:
            st.dataframe(approvals, use_container_width=True, hide_index=True)
            labels = {
                f"{row['action_type']} · {row['target_id']} · {row['id']}": row["id"]
                for row in approvals
            }
            approval_id = labels[st.selectbox("Approval", labels)]
            approval_reason = st.text_area("Обоснование approval")
            if st.button("Подтвердить containment", type="primary"):
                result = request(
                    "POST",
                    f"/api/v1/risk/approvals/{approval_id}/approve",
                    json={"reason": approval_reason},
                )
                st.success(f"Статус: {result['status']}; применено к {len(result['applied_items'])} изделиям")
                st.json(result)
                st.rerun()
        else:
            st.info("Нет containment proposals, ожидающих approval.")

    if "INVALIDATE_CONTROL_DEVICE" in permissions:
        st.subheader("Инвалидация контрольного устройства")
        with st.form("invalidate_device"):
            device_id = st.text_input("Device ID")
            invalid_from = st.text_input("Начало affected interval ISO-8601")
            invalid_to = st.text_input("Конец affected interval ISO-8601")
            invalid_reason = st.text_area("Причина инвалидации")
            invalid_type = st.text_input("Тип / код инвалидации")
            if st.form_submit_button("Зафиксировать invalidation"):
                result = request(
                    "POST",
                    "/api/v1/risk/control-devices/invalidate",
                    json={
                        "device_id": device_id,
                        "affected_from": invalid_from,
                        "affected_to": invalid_to,
                        "reason": invalid_reason,
                        "invalidation_type": invalid_type or None,
                        "supporting_evidence_refs": [],
                    },
                )
                st.success(f"Пересчитано изделий: {len(result['affected_items'])}")
                st.json(result)


def scenario_runner() -> None:
    header("Scenario Runner")
    scenarios = request("GET", "/api/v1/demo/scenarios")
    if not scenarios:
        st.info("Сценарии не найдены")
        return
    labels = {f"{row['name']} · {row['description']}": row for row in scenarios}
    selected = labels[st.selectbox("Сценарий", labels)]
    st.caption(
        "Сценарий подаёт фиксированные входные события. Результат ниже рассчитывается "
        "через ingestion, persisted facts, projections и доменные правила TRACE-Q."
    )
    col1, col2 = st.columns(2)
    if col1.button("Run", type="primary"):
        result = request("POST", f"/api/v1/demo/scenarios/{selected['name']}/run")
        st.session_state.scenario_result = result
    if col2.button("Reset demo data"):
        request("POST", "/api/v1/demo/reset")
        st.session_state.pop("scenario_result", None)
        st.success("Демонстрационные данные сброшены")

    result = st.session_state.get("scenario_result")
    if not result or result.get("scenario") != selected["name"]:
        return
    st.header("✅ PASS" if result["passed"] else "❌ FAIL")
    (st.success if result["passed"] else st.error)(
        "PASS — сценарий выполнен" if result["passed"] else "FAIL — есть расхождения"
    )
    st.subheader("Рассчитанное состояние системы")
    st.dataframe(
        actual_state_rows(result.get("actual") or {}),
        use_container_width=True,
        hide_index=True,
    )
    st.subheader("Проверки acceptance-сценария")
    for check in scenario_acceptance_checks(result):
        icon = "✓" if check["passed"] else "✗"
        st.markdown(f"**{icon} {check['name']}**")
        if not check["passed"]:
            st.write({"Рассчитано": check["actual"], "Ожидалось": check["expected"]})
    if result.get("failures"):
        st.error("\n".join(str(value) for value in result["failures"]))
    technical_data(result, "Технический JSON")
