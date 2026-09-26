from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from functools import wraps
from typing import Callable

import streamlit as st

from streamlit_app.api_client.client import APIError, logout, request
from streamlit_app.api_client.simulator import simulator_request
from streamlit_app.ui.presentation import (
    EQUIPMENT_WARNINGS_CAPTION,
    EQUIPMENT_WARNINGS_TITLE,
    TIMELINE_CSS,
    analysis_evidence_rows,
    analysis_history_rows,
    activity_presentation,
    alert_explanation,
    api_error_message,
    birth_window_presentation,
    cause_chart_rows,
    control_device_label,
    control_device_invalidation_payload,
    defect_chart_rows,
    defect_label,
    decision_validation_error,
    detection_chart_rows,
    duration_label,
    draft_revision_label,
    equipment_issue_label,
    equipment_issue_suggestion,
    format_timestamp,
    is_actionable_nonconformance,
    is_completed_nonconformance,
    item_table_rows,
    label,
    nonconformance_table_rows,
    pinned_operation_names,
    percentage_label,
    period_validation_error,
    profile_header_label,
    reason_validation_error,
    route_name_label,
    route_revision_label,
    scenario_human_checks,
    scenario_proof,
    scenario_title,
    simulator_feed_message,
    split_nonconformances,
    structure_notice,
    timeline_csv,
    timeline_export_rows,
    timeline_html,
    utc_iso,
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
    left.caption(profile_header_label(profile))
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
        routes = request("GET", "/api/v1/routes")
        route_names = {
            row["code"]: route_name_label(row["name"], row["code"])
            for row in routes
        }
        st.subheader("Изделия")
        st.dataframe(
            item_table_rows(items, route_names),
            use_container_width=True,
            hide_index=True,
        )
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
    header("Контроль качества")
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
        f"{row['item_id']} · {defect_label(row['defect_type'])} · {label(row['verdict'])}": row["id"]
        for row in all_rows
    }
    selected = labels[st.selectbox("Карточка несоответствия", labels)]
    card = request("GET", f"/api/v1/nonconformances/{selected}")
    st.subheader(f"Несоответствие · {defect_label(card['defect_type'])}")
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
                        st.caption(f"Сообщение во внешнюю систему: {result['message_id']}")
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
    routes = request("GET", "/api/v1/routes")
    route = next(
        (row for row in routes if row.get("code") == item.get("route_code")), None
    )
    operation_names = pinned_operation_names(item, routes)
    cols = st.columns(4)
    cols[0].metric("Статус изделия", label(item.get("status")))
    cols[1].metric(
        "Действующий маршрут",
        route_name_label((route or {}).get("name") or "Маршрут изделия", item.get("route_code")),
    )
    cols[2].metric("Версия маршрута", item.get("route_revision") or "—")
    cols[3].metric("Структура", label(item.get("structure_status")))
    notice = structure_notice(item.get("structure_status"))
    if notice:
        st.info(f"**{notice[0]}**  \n{notice[1]}")
    technical_data(item, "Технические данные изделия")

    st.subheader("История действий и решений")
    activity = timeline_value.get("activity") or []
    if not activity:
        st.info("Для изделия пока нет записей в истории.")
        return

    st.caption(
        "Слева показано время события. Наведите на него, чтобы увидеть полную дату. "
        "Оранжевые карточки отмечают предупреждения, фиолетовые — решения и действия, "
        "красные — события, требующие внимания."
    )
    export_rows = timeline_export_rows(activity, operation_names)
    safe_item_id = "".join(
        character if character.isalnum() or character in "-_" else "_"
        for character in str(item_id)
    )
    download_columns = st.columns(2)
    download_columns[0].download_button(
        "Скачать понятную историю (CSV)",
        data=timeline_csv(export_rows),
        file_name=f"history-{safe_item_id}.csv",
        mime="text/csv; charset=utf-8",
        use_container_width=True,
        key=f"history_csv_{safe_item_id}",
    )
    download_columns[1].download_button(
        "Скачать техническую историю (JSON)",
        data=json.dumps(
            {"item": item, "timeline": timeline_value, "analyses": analyses},
            ensure_ascii=False,
            indent=2,
            default=str,
        ).encode("utf-8"),
        file_name=f"history-{safe_item_id}-technical.json",
        mime="application/json",
        use_container_width=True,
        key=f"history_json_{safe_item_id}",
    )
    st.html(TIMELINE_CSS + timeline_html(activity, operation_names))

    technical_activity = []
    for row in activity:
        shown = activity_presentation(row, operation_names)
        technical_activity.append(
            {
                "Время": shown["time"],
                "Тип": row.get("type"),
                "event_id": shown.get("event_id"),
                "source_id": shown.get("source_id"),
                "NCR": shown.get("nonconformance_id"),
                "details": row.get("details"),
            }
        )

    with st.expander("Технические сведения истории"):
        st.dataframe(technical_activity, use_container_width=True, hide_index=True)
        raw_events = timeline_value.get("events") or []
        if raw_events:
            st.dataframe(raw_events, use_container_width=True, hide_index=True)

    st.subheader("Когда мог возникнуть дефект")
    st.caption(
        "Здесь показан возможный интервал появления дефекта по данным проверок. "
        "События внутри интервала помогают восстановить картину, но сами по себе "
        "не доказывают причину дефекта."
    )
    if not analyses:
        st.info("У изделия нет дефектов, для которых нужно рассчитывать интервал.")
    for analysis in analyses:
        versions = analysis.get("versions") or []
        if not versions:
            continue
        current = versions[-1]
        summary = birth_window_presentation(current)
        evidence_rows = analysis_evidence_rows(
            current.get("evidence") or [], operation_names
        )
        with st.container(border=True):
            st.markdown(f"### {defect_label(analysis.get('defect_type'))}")
            st.caption(
                f"Статус причины: {label(analysis.get('cause_status'))}. "
                "Причину подтверждает специалист; система её не назначает автоматически."
            )

            if current.get("status") == "BOUNDED":
                st.success(f"**{summary['title']}.** {summary['explanation']}")
            else:
                st.warning(f"**{summary['title']}.** {summary['explanation']}")

            boundaries = st.columns(2)
            boundaries[0].markdown("**После этой проверки дефекта ещё не было**")
            boundaries[0].write(
                format_timestamp(
                    (summary["last_good"] or {}).get("occurred_at")
                    or current.get("left_boundary_at")
                )
                if summary["last_good"] or current.get("left_boundary_at")
                else "Надёжной предыдущей проверки нет"
            )
            boundaries[1].markdown("**К этому моменту дефект уже обнаружен**")
            boundaries[1].write(
                format_timestamp(
                    (summary["first_defect"] or {}).get("occurred_at")
                    or current.get("right_boundary_at")
                )
            )

            context_rows = [
                row
                for row in evidence_rows
                if row["Роль"] == "Событие внутри интервала"
            ]
            if context_rows:
                st.markdown("**Что происходило в этом интервале**")
                st.dataframe(
                    [
                        {
                            "Время": row["Время"],
                            "Событие": row["Событие"],
                            "Пояснение": row["Что это значит"],
                        }
                        for row in context_rows
                    ],
                    use_container_width=True,
                    hide_index=True,
                )
            else:
                st.info("Между границами нет дополнительных производственных событий.")

            limitation_rows = [
                row for row in evidence_rows if row["Роль"] == "Ограничение данных"
            ]
            if limitation_rows:
                st.warning(
                    "Есть ограничения данных. Они учтены в расчёте и могут делать "
                    "интервал менее точным."
                )
                st.dataframe(
                    limitation_rows,
                    use_container_width=True,
                    hide_index=True,
                )

            with st.expander("Почему система выбрала этот интервал"):
                st.dataframe(
                    evidence_rows,
                    use_container_width=True,
                    hide_index=True,
                )
            if len(versions) > 1:
                with st.expander("Как менялся расчёт"):
                    st.dataframe(
                        analysis_history_rows(versions),
                        use_container_width=True,
                        hide_index=True,
                    )
            technical_data(analysis, "Технические данные расчёта")


def analytics() -> None:
    header("Производственная аналитика")
    kpi = request("GET", "/api/v1/analytics/kpi")
    cols = st.columns(5)
    cols[0].metric("Проверено изделий", kpi["inspected_items"])
    cols[1].metric(
        "С подтверждёнными несоответствиями", kpi["items_with_confirmed_nc"]
    )
    cols[2].metric("Выход годных с первого раза", percentage_label(kpi.get("first_pass_yield")))
    cols[3].metric("Доля изделий с доработкой", percentage_label(kpi.get("rework_item_rate")))
    cols[4].metric("Подтверждённых физических дефектов", kpi["confirmed_physical_defects"])
    st.caption(
        "Выход годных с первого раза = доля оценимых проверенных изделий без "
        "подтверждённого несоответствия. Повторные сигналы одного дефекта не увеличивают "
        "число физических дефектов."
    )

    left, right = st.columns(2)
    with left:
        st.subheader("Дефекты по типам")
        defect_rows = defect_chart_rows(kpi.get("defects_by_type"))
        if defect_rows:
            st.bar_chart(
                defect_rows,
                x="Тип дефекта",
                y="Количество",
                horizontal=True,
            )
        else:
            st.info("Данных о физических дефектах пока нет.")
    with right:
        st.subheader("Статус причин")
        st.bar_chart(
            cause_chart_rows(kpi),
            x="Статус причины",
            y="Количество",
            horizontal=True,
        )

    st.subheader("Где обнаруживаются дефекты")
    detection_rows = detection_chart_rows(
        kpi.get("detected_defects_by_line_station") or []
    )
    if detection_rows:
        st.bar_chart(
            detection_rows,
            x="Место обнаружения",
            y="Количество",
            horizontal=True,
        )
        st.caption("Место обнаружения не означает причину возникновения дефекта.")
    else:
        st.info("Данных о местах обнаружения пока нет.")

    st.subheader("Операционные показатели")
    operational = st.columns(5)
    operational[0].metric(
        "Средняя длительность",
        duration_label(kpi.get("operation_duration_avg_seconds")),
    )
    operational[1].metric(
        "Медиана длительности",
        duration_label(kpi.get("operation_duration_median_seconds")),
    )
    operational[2].metric(
        "Длительность P95",
        duration_label(kpi.get("operation_duration_p95_seconds")),
    )
    operational[3].metric(
        "Средняя ширина интервала",
        duration_label(kpi.get("birth_window_width_avg_seconds")),
    )
    operational[4].metric(
        "Средняя задержка обнаружения",
        duration_label(kpi.get("post_operation_detection_delay_avg_seconds")),
    )
    technical_data(kpi, "Технические данные KPI")


def data_health() -> None:
    header("Состояние данных")
    value = request("GET", "/api/v1/analytics/data-health")
    ingestion = value.get("ingestion") or {}
    st.subheader("Приём событий")
    cols = st.columns(3)
    for column, (status, title) in zip(
        cols,
        [
            ("accepted", "Принято"),
            ("duplicate", "Повторные доставки"),
            ("rejected", "Отклонено"),
        ],
    ):
        column.metric(title, ingestion.get(status, 0))
    st.markdown(
        f"**Последнее принятое событие:** {format_timestamp(value.get('last_ingest_at'))}"
    )
    if value.get("errors"):
        st.warning("Есть отклонённые события. Причины доступны в технических данных.")

    st.subheader("Актуальность состояния изделий")
    st.caption(
        "TRACE-Q восстанавливает текущее состояние изделия из истории событий. "
        "Здесь показано, успешно ли рассчитано это состояние."
    )
    projection_rows = [
        {"Состояние": label(status, domain="projection"), "Количество": count}
        for status, count in (value.get("projections") or {}).items()
    ]
    st.dataframe(projection_rows, use_container_width=True, hide_index=True)
    if value.get("problem_items"):
        st.error("Есть изделия, для которых производное состояние требует внимания.")
        st.dataframe(
            [
                {
                    "Изделие": row["item_id"],
                    "Состояние": label(row["status"], domain="projection"),
                    "Последняя успешная перестройка": format_timestamp(row.get("last_rebuild_at")),
                    "Ошибка": row.get("last_error") or "—",
                }
                for row in value["problem_items"]
            ],
            use_container_width=True,
            hide_index=True,
        )

    st.subheader("Очередь отправки во внешние системы")
    st.dataframe(
        [
            {"Состояние": label(status, domain="outbox"), "Количество": count}
            for status, count in (value.get("outbox") or {}).items()
        ],
        use_container_width=True,
        hide_index=True,
    )
    st.subheader("Интеграции")
    st.dataframe(
        [
            {
                "Интеграция": row["integration_id"],
                "Состояние": label(row["status"], domain="integration_health"),
                "Последний успех": format_timestamp(row.get("last_success_at")),
                "Последняя ошибка": format_timestamp(row.get("last_error_at")),
                "Сообщение": row.get("safe_error") or "—",
            }
            for row in value.get("integrations") or []
        ],
        use_container_width=True,
        hide_index=True,
    )
    st.subheader("Фоновые обработчики")
    heartbeats = value.get("worker_heartbeats") or []
    if heartbeats:
        st.dataframe(
            [
                {
                    "Обработчик": row["worker_id"],
                    "Тип": row["worker_type"],
                    "Состояние": label(row["status"], domain="worker"),
                    "Последний сигнал": format_timestamp(row.get("heartbeat_at")),
                }
                for row in heartbeats
            ],
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info("Фоновые обработчики ещё не зарегистрировали heartbeat.")
    technical_data(value)


def route_editor() -> None:
    header("Маршруты")
    routes = request("GET", "/api/v1/routes")
    if routes:
        labels = {}
        for value in routes:
            current = next(
                (
                    row
                    for row in value["revisions"]
                    if row["id"] == value.get("active_revision_id")
                ),
                None,
            )
            labels[
                route_revision_label(
                    value["name"],
                    (current or {}).get("revision"),
                    route_code=value["code"],
                )
            ] = value
        route = labels[st.selectbox("Маршрут", labels)]
        active = next(
            (row for row in route["revisions"] if row["id"] == route.get("active_revision_id")),
            None,
        )
        route_cols = st.columns(2)
        route_cols[0].markdown(
            f"**Действующий маршрут**  \n"
            f"{route_name_label(route['name'], route['code'])}"
        )
        route_cols[1].markdown(
            f"**Версия маршрута**  \n{active['revision'] if active else 'Не назначена'}"
        )
        st.caption(f"Технический код: {route['code']}")
        technical_data(route, "Технические данные маршрута")
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
        if st.button("Клонировать и сохранить новую ревизию"):
            result = request(
                "POST", f"/api/v1/routes/{route['id']}/revisions", json={"steps": json.loads(steps_text)}
            )
            st.success(f"Создана версия маршрута {result['revision']}")
            st.rerun()
        draft_revisions = [
            revision for revision in revisions if revision["status"] == "draft"
        ]
        if draft_revisions:
            draft_options = {
                draft_revision_label(revision): revision["id"]
                for revision in draft_revisions
            }
            draft_label = st.selectbox("Черновая версия", list(draft_options))
            draft_id = draft_options[draft_label]
            activation_reason = st.text_input("Причина активации")
            if st.button("Активировать"):
                request(
                    "POST",
                    f"/api/v1/routes/{route['id']}/activate",
                    params={
                        "revision_id": draft_id,
                        "reason": activation_reason,
                    },
                )
                st.success("Версия маршрута активирована")
                st.rerun()
    with st.expander("Импорт маршрута JSON"):
        payload = st.text_area("JSON маршрута", key="route_import")
        if st.button("Импортировать") and payload:
            result = request("POST", "/api/v1/routes/import", json=json.loads(payload))
            st.success("Маршрут импортирован")
            technical_data(result, "Технический результат импорта")


def admin_panel() -> None:
    header("Администрирование")
    tabs = st.tabs(
        [
            "Пользователи",
            "Источники событий",
            "Интеграции",
            "Аудит",
            "Целостность",
            "События безопасности",
        ]
    )
    with tabs[0]:
        users = request("GET", "/api/v1/admin/users")
        st.dataframe(
            [
                {
                    "Логин": row["username"],
                    "Имя": row["display_name"],
                    "Состояние": "Активен" if row["enabled"] else "Отключён",
                    "Роли": ", ".join(label(role, domain="role") for role in row["roles"]),
                }
                for row in users
            ],
            use_container_width=True,
            hide_index=True,
        )
        if users:
            user_labels = {
                f"{row['username']} · {row['display_name']}": row["id"] for row in users
            }
            selected_user_id = user_labels[
                st.selectbox("Изменить пользователя", user_labels)
            ]
            selected_user = next(
                row
                for row in users
                if row["id"] == selected_user_id
            )
            with st.form("edit_user"):
                edited_name = st.text_input("Отображаемое имя", value=selected_user["display_name"])
                edited_enabled = st.checkbox("Учётная запись активна", value=selected_user["enabled"])
                edited_roles = st.multiselect(
                    "Роли",
                    ["controller", "master", "technologist", "manager", "admin", "simulator_reader"],
                    default=selected_user["roles"],
                    format_func=lambda value: label(value, domain="role"),
                )
                if st.form_submit_button("Сохранить изменения"):
                    request(
                        "PATCH",
                        f"/api/v1/admin/users/{selected_user['id']}",
                        json={
                            "display_name": edited_name,
                            "enabled": edited_enabled,
                            "roles": edited_roles,
                        },
                    )
                    st.success("Пользователь обновлён")
                    st.rerun()
        with st.expander("Создать пользователя"):
            with st.form("create_user"):
                username = st.text_input("Логин")
                display_name = st.text_input("Отображаемое имя")
                password = st.text_input("Пароль", type="password")
                roles = st.multiselect(
                    "Роли",
                    ["controller", "master", "technologist", "manager", "admin", "simulator_reader"],
                    format_func=lambda value: label(value, domain="role"),
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
        st.dataframe(
            [
                {
                    "Источник": row["source_id"],
                    "Тип": row["source_type"],
                    "Состояние": label(row["status"], domain="source_status"),
                    "Включён": "Да" if row["enabled"] else "Нет",
                    "Аутентификация": row["auth_method"],
                    "Разрешённые события": ", ".join(row["allowed_event_types"]),
                }
                for row in sources
            ],
            use_container_width=True,
            hide_index=True,
        )
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
        integrations = request("GET", "/api/v1/integrations")
        st.subheader("Подключения")
        st.dataframe(
            [
                {
                    "Интеграция": row["id"],
                    "Назначение / состояние": label(row["status"], domain="integration_health"),
                }
                for row in integrations["adapters"]
            ],
            use_container_width=True,
            hide_index=True,
        )
        st.subheader("Фактическое состояние")
        st.dataframe(
            [
                {
                    "Интеграция": row["integration_id"],
                    "Состояние": label(row["status"], domain="integration_health"),
                    "Последний успех": format_timestamp(row.get("last_success_at")),
                    "Последняя ошибка": format_timestamp(row.get("last_error_at")),
                    "Сообщение": row.get("safe_error") or "—",
                }
                for row in integrations["health"]
            ],
            use_container_width=True,
            hide_index=True,
        )
        st.subheader("Очередь исходящих сообщений")
        st.dataframe(
            [
                {
                    "Сообщение": row["message_id"],
                    "Получатель": row["destination"],
                    "Состояние": label(row["state"], domain="outbox"),
                    "Попытки": row["attempts"],
                    "Последняя ошибка": row.get("last_error") or "—",
                }
                for row in integrations["outbox"]
            ],
            use_container_width=True,
            hide_index=True,
        )
        if st.button("Синхронизировать ERP"):
            result = request("POST", "/api/v1/integrations/erp/sync")
            st.success(
                f"Получено заданий: {len(result['jobs'])}; новых сопоставлений: "
                f"{result['new_mappings']}"
            )
            technical_data(result, "Технический ответ синхронизации")
    with tabs[3]:
        audit = request("GET", "/api/v1/admin/audit")
        st.dataframe(
            [
                {
                    "Время": format_timestamp(row["timestamp"]),
                    "Действие": row["action"],
                    "Результат": label(row["outcome"]),
                    "Объект": f"{row.get('target_type') or '—'} · {row.get('target_id') or '—'}",
                    "Пользователь": row.get("actor_user_id") or "Система",
                }
                for row in audit
            ],
            use_container_width=True,
            hide_index=True,
        )
        technical_data(audit, "Технические записи аудита")
    with tabs[4]:
        crypto = request("GET", "/api/v1/admin/crypto-profile")
        st.info(
            f"Активный криптографический профиль: {crypto['profile_id']}. "
            "Ключи не хранятся в базе данных."
        )
        technical_data(crypto, "Параметры криптографического профиля")
        if st.button("Проверить целостность", type="primary"):
            result = request("POST", "/api/v1/admin/integrity/verify")
            if result["status"] == "OK":
                st.success("Целостность подтверждена")
            else:
                st.error("Нарушена целостность данных")
            check_cols = st.columns(4)
            check_cols[0].metric("Исходных событий проверено", result["raw_events_checked"])
            check_cols[1].metric(
                "Ошибок исходных событий", len(result.get("raw_failures") or [])
            )
            check_cols[2].metric("Записей аудита проверено", result["audit_entries_checked"])
            check_cols[3].metric(
                "Ошибок аудита", len(result.get("audit_failures") or [])
            )
            st.caption(
                f"Профиль: {result['crypto_profile']} · "
                f"время проверки: {format_timestamp(result['checked_at'])}"
            )
            failures = [
                {
                    "Раздел": "Исходные события",
                    "Объект": row.get("event_id"),
                    "Поток": row.get("stream_id"),
                    "Причина": row.get("reason"),
                    "Важность": "Критическая",
                }
                for row in result.get("raw_failures") or []
            ] + [
                {
                    "Раздел": "Аудит",
                    "Объект": row.get("entry_id"),
                    "Поток": "audit",
                    "Причина": row.get("reason"),
                    "Важность": "Критическая",
                }
                for row in result.get("audit_failures") or []
            ]
            if failures:
                st.dataframe(failures, use_container_width=True, hide_index=True)
            technical_data(result, "Детали проверки")
        item_id = st.text_input("ID изделия для перестройки производного состояния")
        if st.button("Перестроить") and item_id:
            request("POST", f"/api/v1/admin/rebuild/{item_id}")
            st.success(f"Производное состояние {item_id} перестроено")
    with tabs[5]:
        alerts = request("GET", "/api/v1/admin/security-alerts")
        if alerts:
            st.dataframe(
                [
                    {
                        "Время": format_timestamp(row["created_at"]),
                        "Событие": label(row["alert_type"], domain="alert"),
                        "Важность": label(row["severity"], domain="severity"),
                        "Источник": row.get("source_id") or "—",
                        "Объект": row.get("target_id") or "—",
                        "Описание": alert_explanation(row.get("alert_type")),
                        "Состояние": "Закрыто" if row.get("resolved_at") else "Требует внимания",
                    }
                    for row in alerts
                ],
                use_container_width=True,
                hide_index=True,
            )
            technical_data(alerts, "Технические данные оповещений")
        else:
            st.success("Открытых оповещений безопасности нет.")


def blast_radius() -> None:
    header("Риски / радиус влияния")
    permissions = set(st.session_state.profile["permissions"])

    if "RUN_BLAST_RADIUS" in permissions:
        st.subheader(EQUIPMENT_WARNINGS_TITLE)
        issues = request("GET", "/api/v1/risk/equipment-issues")
        if issues:
            for issue in issues[:10]:
                issue_columns = st.columns([4, 1])
                issue_columns[0].warning(
                    f"**⚠ Предупреждение оборудования**  \n"
                    f"Оборудование: {issue['equipment_id']}  \n"
                    f"Событие: {equipment_issue_label(issue.get('code'))}  \n"
                    f"Время: {format_timestamp(issue.get('occurred_at'))}"
                )
                if issue_columns[1].button(
                    "Оценить радиус влияния",
                    key=f"risk-issue-{issue['event_id']}",
                    use_container_width=True,
                ):
                    suggestion = equipment_issue_suggestion(issue)
                    st.session_state.blast_factor_type = suggestion["factor_type"]
                    st.session_state.blast_factor_value = suggestion["factor_value"]
                    st.session_state.blast_from_date = suggestion["affected_from"].date()
                    st.session_state.blast_from_time = suggestion[
                        "affected_from"
                    ].time().replace(tzinfo=None)
                    st.session_state.blast_to_date = suggestion["affected_to"].date()
                    st.session_state.blast_to_time = suggestion["affected_to"].time().replace(
                        tzinfo=None
                    )
                    st.session_state.blast_interval_suggested = True
                    st.rerun()
        else:
            st.info("Недавних предупреждений оборудования пока нет.")
        st.caption(EQUIPMENT_WARNINGS_CAPTION)

        st.subheader("Поиск потенциально затронутых изделий")
        st.info(
            "Расчёт находит изделия по общему фактору и создаёт предложение. "
            "Он не объявляет найденные изделия дефектными и не применяет ограничения "
            "без решения уполномоченного сотрудника."
        )
        now = datetime.now(timezone.utc)
        st.session_state.setdefault("blast_factor_type", "equipment")
        st.session_state.setdefault("blast_factor_value", "")
        st.session_state.setdefault("blast_from_date", (now - timedelta(minutes=30)).date())
        st.session_state.setdefault(
            "blast_from_time", (now - timedelta(minutes=30)).time().replace(tzinfo=None)
        )
        st.session_state.setdefault("blast_to_date", now.date())
        st.session_state.setdefault("blast_to_time", now.time().replace(tzinfo=None))
        with st.form("blast_radius"):
            factor_type = st.selectbox(
                "Общий фактор",
                ["equipment", "tool", "material_lot", "control_device", "component", "time_interval"],
                format_func=lambda value: label(value, domain="risk_factor"),
                key="blast_factor_type",
            )
            factor_value = st.text_input(
                "Оборудование или значение общего фактора",
                key="blast_factor_value",
            )
            if st.session_state.get("blast_interval_suggested"):
                st.caption(
                    "Предложенный интервал: 30 минут до предупреждения. "
                    "При необходимости измените его. Это не доказанный период неисправности."
                )
            period_columns = st.columns(2)
            with period_columns[0]:
                st.markdown("**Начало периода**")
                affected_from_date = st.date_input("Дата начала", key="blast_from_date")
                affected_from_time = st.time_input("Время начала", key="blast_from_time")
            with period_columns[1]:
                st.markdown("**Конец периода**")
                affected_to_date = st.date_input("Дата окончания", key="blast_to_date")
                affected_to_time = st.time_input("Время окончания", key="blast_to_time")
            st.caption("Время указано в UTC.")
            action = st.selectbox(
                "Что сделать с потенциально затронутыми изделиями?",
                ["REVIEW_REQUIRED", "REINSPECTION_REQUIRED", "HOLD"],
                format_func=lambda value: label(value, domain="containment"),
            )
            rationale = st.text_area("Обоснование")
            if st.form_submit_button(
                "Найти потенциально затронутые изделия и создать предложение"
            ):
                affected_from = utc_iso(affected_from_date, affected_from_time)
                affected_to = utc_iso(affected_to_date, affected_to_time)
                validation_error = period_validation_error(affected_from, affected_to)
                if not factor_value.strip():
                    validation_error = "Укажите оборудование или значение общего фактора."
                elif len(rationale.strip()) < 3:
                    validation_error = "Укажите обоснование не короче 3 символов."
                if validation_error:
                    st.error(validation_error)
                else:
                    result = request("POST", "/api/v1/risk/blast-radius", json={
                        "factor_type": factor_type,
                        "factor_value": factor_value,
                        "affected_from": affected_from,
                        "affected_to": affected_to,
                        "proposed_action": action,
                        "rationale": rationale,
                    })
                    st.success(f"Потенциально затронутые изделия: {len(result['affected_items'])}")
                    st.warning(
                        "Ограничения не применены автоматически: предложение ожидает согласования."
                    )
                    if result["affected_items"]:
                        st.dataframe(
                            [
                                {
                                    "Изделие": row["item_id"],
                                    "Предлагаемое действие": label(
                                        row["proposed_action"], domain="containment"
                                    ),
                                }
                                for row in result["affected_items"]
                            ],
                            use_container_width=True,
                            hide_index=True,
                        )
                    technical_data(result, "Технические сведения предложения")

    if "APPROVE_CONTAINMENT" in permissions:
        st.subheader("Предложения, ожидающие согласования")
        approvals = request("GET", "/api/v1/risk/approvals")
        if approvals:
            st.dataframe(
                [
                    {
                        "Фактор": label(row.get("factor_type"), domain="risk_factor"),
                        "Значение": row.get("factor_value") or "—",
                        "Интервал": (
                            f"{format_timestamp(row.get('affected_from'))} — "
                            f"{format_timestamp(row.get('affected_to'))}"
                        ),
                        "Затронуто изделий": row.get("affected_items_count", 0),
                        "Предложение": label(row.get("proposed_action"), domain="containment"),
                        "Обоснование": row.get("rationale") or "—",
                        "Согласования": f"{len(row.get('approvals') or [])}/{row['required_approvals']}",
                    }
                    for row in approvals
                ],
                use_container_width=True,
                hide_index=True,
            )
            labels = {
                f"{label(row.get('factor_type'), domain='risk_factor')} · {row.get('factor_value') or 'интервал'}": row["id"]
                for row in approvals
            }
            approval_id = labels[st.selectbox("Предложение", labels)]
            approval_reason = st.text_area("Обоснование согласования")
            if st.button("Согласовать и применить", type="primary"):
                result = request(
                    "POST",
                    f"/api/v1/risk/approvals/{approval_id}/approve",
                    json={"reason": approval_reason},
                )
                st.success(f"Применено к изделиям: {len(result['applied_items'])}")
                technical_data(result)
                st.rerun()
        else:
            st.info("Нет предложений, ожидающих согласования.")

    if "INVALIDATE_CONTROL_DEVICE" in permissions:
        st.subheader("Отметить результаты контрольного устройства как недостоверные")
        st.info(
            "Используйте этот раздел, если камера или другое средство контроля работало "
            "некорректно. Исходные результаты сохранятся в истории, но TRACE-Q перестанет "
            "использовать их как достоверные доказательства и пересчитает анализ."
        )
        devices = request("GET", "/api/v1/risk/control-devices")
        if not devices:
            st.info("В истории пока нет известных контрольных устройств.")
        else:
            device_labels = {
                (
                    f"{control_device_label(row['device_id'])} · "
                    f"наблюдений: {row['observation_count']}"
                ): row
                for row in devices
            }
            latest_observed = max(
                (
                    datetime.fromisoformat(
                        str(row["last_observed_at"]).replace("Z", "+00:00")
                    )
                    for row in devices
                    if row.get("last_observed_at")
                ),
                default=datetime.now(timezone.utc),
            )
            if latest_observed.tzinfo is None:
                latest_observed = latest_observed.replace(tzinfo=timezone.utc)
            st.session_state.setdefault(
                "invalid_from_date", (latest_observed - timedelta(minutes=30)).date()
            )
            st.session_state.setdefault(
                "invalid_from_time",
                (latest_observed - timedelta(minutes=30)).time().replace(tzinfo=None),
            )
            st.session_state.setdefault("invalid_to_date", latest_observed.date())
            st.session_state.setdefault(
                "invalid_to_time", latest_observed.time().replace(tzinfo=None)
            )
            with st.form("invalidate_device"):
                selected_device_label = st.selectbox(
                    "Контрольное устройство", device_labels
                )
                invalid_period = st.columns(2)
                with invalid_period[0]:
                    st.markdown("**Начало периода**")
                    invalid_from_date = st.date_input(
                        "Дата начала недостоверных результатов",
                        key="invalid_from_date",
                    )
                    invalid_from_time = st.time_input(
                        "Время начала недостоверных результатов",
                        key="invalid_from_time",
                    )
                with invalid_period[1]:
                    st.markdown("**Конец периода**")
                    invalid_to_date = st.date_input(
                        "Дата окончания недостоверных результатов",
                        key="invalid_to_date",
                    )
                    invalid_to_time = st.time_input(
                        "Время окончания недостоверных результатов",
                        key="invalid_to_time",
                    )
                st.caption("Время указано в UTC.")
                invalid_reason = st.text_area("Причина")
                invalid_type = st.selectbox(
                    "Тип проблемы",
                    [
                        "CALIBRATION_FAILURE",
                        "DEVICE_FAILURE",
                        "MISCONFIGURATION",
                        "INCORRECT_CONFIGURATION",
                        "OTHER",
                    ],
                    format_func=lambda value: label(
                        value, domain="invalidation_type"
                    ),
                )
                if st.form_submit_button(
                    "Зафиксировать недостоверность и пересчитать анализ"
                ):
                    invalid_from = utc_iso(invalid_from_date, invalid_from_time)
                    invalid_to = utc_iso(invalid_to_date, invalid_to_time)
                    validation_error = period_validation_error(
                        invalid_from, invalid_to
                    )
                    if len(invalid_reason.strip()) < 3:
                        validation_error = "Укажите причину не короче 3 символов."
                    if validation_error:
                        st.error(validation_error)
                    else:
                        selected_device = device_labels[selected_device_label]
                        payload = control_device_invalidation_payload(
                            device_id=selected_device["device_id"],
                            affected_from_date=invalid_from_date,
                            affected_from_time=invalid_from_time,
                            affected_to_date=invalid_to_date,
                            affected_to_time=invalid_to_time,
                            reason=invalid_reason,
                            invalidation_type=invalid_type,
                        )
                        result = request(
                            "POST",
                            "/api/v1/risk/control-devices/invalidate",
                            json=payload,
                        )
                        st.success(
                            f"Пересчитано изделий: {len(result['affected_items'])}"
                        )
                        technical_data(result, "Технические сведения пересчёта")


@st.fragment(run_every=1.0)
def _simulator_live_status(session_id: str) -> None:
    try:
        session = simulator_request("GET", f"/sessions/{session_id}")
    except APIError as exc:
        st.error(api_error_message(exc.code, exc.message, exc.details))
        return
    status_labels = {
        "created": "Создана",
        "running": "Выполняется",
        "paused": "Приостановлена",
        "waiting_for_controller": "Ожидает решения контролёра",
        "waiting_for_release": "Ожидает проверки доработки",
        "completed": "Завершена",
        "stopped": "Остановлена",
        "error": "Ошибка",
    }
    phase_labels = {
        "register": "Регистрация",
        "operator_action": "Подтверждение задания оператором",
        "operation_start": "Подготовка операции",
        "operation_finish": "Операция выполняется",
        "equipment_warning": "Предупреждение оборудования",
        "inspection": "Контроль качества",
        "wait_controller": "Несоответствие обнаружено",
        "rework_finish": "Выполняется доработка",
        "rework_inspection": "Повторный контроль",
        "wait_release": "Доработка ожидает проверки",
        "complete": "Маршрут завершён",
    }
    completed = sum(1 for item in session["items"] if item["completed"])
    cols = st.columns(4)
    cols[0].metric("Состояние линии", status_labels.get(session["status"], session["status"]))
    cols[1].markdown(
        f"**Действующий маршрут**  \n"
        f"{session['route'].get('route_name') or 'Производственный маршрут'}  \n"
        f"Версия {session['route']['revision']}"
    )
    cols[2].metric("Изделия", len(session["items"]), f"завершено {completed}")
    cols[3].metric("Отправлено событий", session["event_counter"])
    if session.get("last_error"):
        st.error("Симуляция остановлена из-за ошибки доставки. Откройте технические данные.")
    if session["mode"] == "equipment_issue" and any(
        item["equipment_warning_sent"] for item in session["items"]
    ):
        st.warning(
            "Обнаружена проблема оборудования EQ-LATHE-01. Войдите как технолог и "
            "откройте «Риски / радиус влияния». Симулятор не запускает анализ автоматически."
        )

    st.subheader("Изделия")
    rows = []
    for item in session["items"]:
        step_index = min(item["step_index"], len(session["route"]["steps"]) - 1)
        step = session["route"]["steps"][step_index]
        rows.append(
            {
                "Изделие": item["item_id"],
                "Текущий этап": phase_labels.get(item["phase"], item["phase"]),
                "Операция": step["operation_name"],
                "Станция": step["station_id"],
                "Качество": (
                    f"Обнаружено: {defect_label(item['active_defects'][0])}"
                    if item.get("active_defects")
                    else "Обнаружено несоответствие"
                    if item["phase"] == "wait_controller"
                    else "Повторный контроль выполнен"
                    if item["phase"] == "wait_release"
                    else "Без новых отклонений"
                ),
                "Ожидаемое действие": item.get("waiting_reason") or "—",
                "Завершено": "Да" if item["completed"] else "Нет",
            }
        )
    st.dataframe(rows, use_container_width=True, hide_index=True)

    st.subheader("Последние события")
    if session["feed"]:
        st.dataframe(
            [
                {
                    "Время": format_timestamp(row["at"]),
                    "Изделие": row.get("item_id") or "—",
                    "Событие": label(row.get("event_type"), domain="event_type"),
                    "Результат": label(row["status"], domain="ingestion"),
                    "Сообщение": simulator_feed_message(row),
                }
                for row in reversed(session["feed"][-20:])
            ],
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info("События ещё не отправлялись.")
    technical_data(session, "Для демонстратора: состояние симулятора")


def factory_simulator() -> None:
    header("Симуляция производства")
    st.caption(
        "MES, оборудование и VisionQC эмулируются. Все события проходят через штатный "
        "API TRACE-Q. Решения контролёра симулятор не принимает: при дефекте поток ждёт "
        "действия в разделе «Контроль качества»."
    )
    sessions = simulator_request("GET", "/sessions")
    if not sessions:
        st.info("Активных сессий нет. Создайте новую симуляцию.")
    with st.expander("Новая симуляция", expanded=not sessions):
        with st.form("create_simulation"):
            routes = simulator_request("GET", "/routes")
            route_labels = {
                route_revision_label(
                    row["name"], row["revision"], route_code=row["code"]
                ): row["code"]
                for row in routes
            }
            route_code = route_labels[
                st.selectbox("Маршрут", route_labels)
            ] if route_labels else ""
            if route_code:
                st.caption(f"Технический код выбранного маршрута: {route_code}")
            item_count = st.number_input("Количество изделий", min_value=1, max_value=20, value=3)
            mode = st.selectbox(
                "Режим",
                ["normal", "defect_rework", "equipment_issue"],
                format_func=lambda value: {
                    "normal": "Штатное прохождение",
                    "defect_rework": "Дефект и доработка",
                    "equipment_issue": "Предупреждение оборудования",
                }[value],
            )
            speed = st.selectbox(
                "Скорость",
                [1, 5, 20],
                index=1,
                format_func=lambda value: f"{value}x",
            )
            with st.expander("Дополнительно"):
                seed = st.number_input("Seed", min_value=0, value=2026)
            if mode == "equipment_issue" and item_count < 3:
                st.warning("Для режима проблемы оборудования нужно не менее трёх изделий.")
            if st.form_submit_button(
                "Создать сессию",
                type="primary",
                disabled=(not route_code or (mode == "equipment_issue" and item_count < 3)),
            ):
                created = simulator_request(
                    "POST",
                    "/sessions",
                    json={
                        "route_code": route_code,
                        "item_count": int(item_count),
                        "mode": mode,
                        "interval_seconds": {1: 4.0, 5: 0.8, 20: 0.2}[speed],
                        "seed": int(seed),
                    },
                )
                st.session_state.simulator_session_id = created["id"]
                st.rerun()

    if not sessions:
        return
    by_label = {}
    for index, row in enumerate(sessions, start=1):
        route_title = route_revision_label(
            row["route"].get("route_name") or "Маршрут",
            row["route"]["revision"],
            route_code=row["route"]["route_code"],
        )
        by_label[
            f"Сессия {index} · {route_title} · {len(row['items'])} изд."
        ] = row["id"]
    selected_id = st.session_state.get("simulator_session_id")
    selected_label = next(
        (label_text for label_text, value in by_label.items() if value == selected_id),
        next(iter(by_label)),
    )
    chosen = st.selectbox(
        "Сессия",
        by_label,
        index=list(by_label).index(selected_label),
    )
    session_id = by_label[chosen]
    st.session_state.simulator_session_id = session_id
    controls = st.columns(7)
    actions = [
        ("Старт", "start"),
        ("Пауза", "pause"),
        ("Продолжить", "resume"),
        ("Один шаг", "step"),
        ("Остановить", "stop"),
        ("Сбросить", "reset"),
    ]
    for column, (title, action) in zip(controls, actions):
        if column.button(title, key=f"sim-{action}", use_container_width=True):
            simulator_request("POST", f"/sessions/{session_id}/{action}")
            st.rerun()
    if controls[-1].button("Удалить", key="sim-delete", use_container_width=True):
        simulator_request("DELETE", f"/sessions/{session_id}")
        st.session_state.pop("simulator_session_id", None)
        st.rerun()
    _simulator_live_status(session_id)

    st.divider()
    confirm_clear = st.checkbox(
        "Подтверждаю очистку всех демонстрационных событий и производных данных"
    )
    if st.button(
        "Очистить demo-данные",
        type="secondary",
        disabled=not confirm_clear,
    ):
        simulator_request("POST", f"/sessions/{session_id}/reset")
        request("POST", "/api/v1/demo/reset")
        st.success("Демонстрационные данные и выбранная симуляция сброшены")
        st.rerun()


def scenario_runner() -> None:
    header("Приёмочные сценарии")
    scenarios = request("GET", "/api/v1/demo/scenarios")
    if not scenarios:
        st.info("Сценарии не найдены")
        return
    st.dataframe(
        [
            {
                "Сценарий": f"{row['name']} — {scenario_title(row['name'], row.get('title'))}",
                "Что проверяет": scenario_proof(row["name"], row.get("description")),
            }
            for row in scenarios
        ],
        use_container_width=True,
        hide_index=True,
    )
    labels = {
        f"{row['name']} · {scenario_title(row['name'], row.get('title'))}": row
        for row in scenarios
    }
    selected = labels[st.selectbox("Сценарий", labels)]
    st.markdown(
        f"**Что проверяет:** {scenario_proof(selected['name'], selected.get('description'))}"
    )
    st.caption(
        "Это автоматизированные приёмочные проверки, а не симуляция живого производства. "
        "Каждый сценарий подаёт фиксированные входные события и сравнивает рассчитанное "
        "состояние с ожидаемыми бизнес-инвариантами."
    )
    col1, col2 = st.columns(2)
    if col1.button("Запустить", type="primary"):
        result = request("POST", f"/api/v1/demo/scenarios/{selected['name']}/run")
        st.session_state.scenario_result = result
    if col2.button("Сбросить демонстрационные данные"):
        request("POST", "/api/v1/demo/reset")
        st.session_state.pop("scenario_result", None)
        st.success("Демонстрационные данные сброшены")

    result = st.session_state.get("scenario_result")
    if not result or result.get("scenario") != selected["name"]:
        return
    st.header("✅ Выполнено" if result["passed"] else "❌ Есть расхождения")
    (st.success if result["passed"] else st.error)(
        "Сценарий подтвердил ожидаемое поведение."
        if result["passed"]
        else "Сценарий обнаружил расхождения с ожидаемым поведением."
    )
    st.subheader("Что подтвердил сценарий")
    for check in scenario_human_checks(result):
        icon = "✓" if check["passed"] else "✗"
        st.markdown(f"**{icon} {check['name']}**")
    st.subheader("Что это доказывает")
    st.write(scenario_proof(selected["name"], selected.get("description")))
    technical_data(result, "Технические результаты сценария")
