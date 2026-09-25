from __future__ import annotations

import json
from typing import Callable

import streamlit as st

from streamlit_app.api_client.client import APIError, logout, request


def guarded(render: Callable[[], None]) -> Callable[[], None]:
    def wrapped() -> None:
        try:
            render()
        except APIError as exc:
            st.error(f"{exc.code}: {exc.message}")
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


def overview() -> None:
    header("TRACE-Q · Обзор")
    permissions = set(st.session_state.profile["permissions"])
    if "VIEW_PRODUCT" in permissions:
        items = request("GET", "/api/v1/items")
        st.subheader("Изделия")
        st.dataframe(items, use_container_width=True, hide_index=True)
    if "VIEW_NONCONFORMANCE" in permissions:
        ncrs = request("GET", "/api/v1/nonconformances")
        st.subheader("Несоответствия")
        st.dataframe(ncrs, use_container_width=True, hide_index=True)
    if "MANAGE_USERS" in permissions:
        users = request("GET", "/api/v1/admin/users")
        st.subheader("Пользователи")
        st.dataframe(users, use_container_width=True, hide_index=True)


def pending_reviews() -> None:
    header("Ожидают решения")
    rows = request("GET", "/api/v1/nonconformances")
    pending = [row for row in rows if row["verdict"] in {"pending_review", "needs_extra_check"} or row.get("verification_status") == "PENDING"]
    st.dataframe(pending, use_container_width=True, hide_index=True)
    if not pending:
        st.info("Нет несоответствий, ожидающих решения.")
        return
    labels = {f"{row['item_id']} · {row['defect_type']} · {row['id']}": row["id"] for row in pending}
    selected = labels[st.selectbox("Карточка", labels)]
    card = request("GET", f"/api/v1/nonconformances/{selected}")
    st.json(card, expanded=False)
    with st.form("decision"):
        verdict = st.selectbox("Вердикт", ["confirmed", "rejected"])
        disposition = st.selectbox(
            "Решение по изделию", ["IN_PROCESS", "REWORK_REQUIRED", "RELEASED", "USE_AS_IS", "SCRAPPED"]
        )
        containment = st.selectbox(
            "Локализация", ["REVIEW_REQUIRED", "HOLD", "REINSPECTION_REQUIRED", "NONE"]
        )
        reason = st.text_area("Обоснование")
        submitted = st.form_submit_button("Сохранить решение")
        if submitted:
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
            st.success(f"Решение сохранено; outbox {result['message_id']}")
            st.rerun()
    with st.expander("Запросить дополнительный контроль"):
        extra_reason = st.text_input("Причина", key="extra_reason")
        control_point = st.text_input("Контрольная точка", key="extra_cp")
        if st.button("Запросить"):
            request(
                "POST",
                f"/api/v1/nonconformances/{selected}/request-inspection",
                json={"reason": extra_reason, "control_point_id": control_point or None},
            )
            st.success("Дополнительный контроль запрошен")
    if card.get("verification_status") == "PENDING":
        with st.form("verify_rework"):
            passed = st.checkbox("Повторный контроль подтверждает устранение дефекта")
            verification_reason = st.text_area("Обоснование верификации")
            if st.form_submit_button("Зафиксировать верификацию"):
                st.json(request("POST", f"/api/v1/nonconformances/{selected}/verify-rework",
                                json={"passed": passed, "reason": verification_reason}))


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
    st.json(item, expanded=False)
    st.subheader("События")
    st.dataframe(timeline_value["events"], use_container_width=True, hide_index=True)
    st.subheader("Defect Birth Window")
    if not analyses:
        st.info("Для изделия нет анализа несоответствий.")
    for analysis in analyses:
        with st.expander(f"{analysis['defect_type']} · причина: {analysis['cause_status']}", expanded=True):
            for version in analysis["versions"]:
                st.markdown(f"**Analysis v{version['version']} · {version['status']}**")
                st.write(
                    {"left": version["left_boundary_at"], "right": version["right_boundary_at"], "why_changed": version["reason"]}
                )
                st.dataframe(version["evidence"], use_container_width=True, hide_index=True)


def analytics() -> None:
    header("Производственная аналитика")
    kpi = request("GET", "/api/v1/analytics/kpi")
    cols = st.columns(4)
    cols[0].metric("Проверено изделий", kpi["inspected_items"])
    cols[1].metric("Подтверждённые НС", kpi["items_with_confirmed_nc"])
    cols[2].metric("Физические дефекты", kpi["number_of_unique_defects"])
    fpy = kpi.get("first_pass_yield")
    cols[3].metric("First Pass Yield", "—" if fpy is None else f"{fpy:.1%}")
    st.json(kpi, expanded=True)


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
    st.write("Ожидается", selected.get("expected"))
    col1, col2 = st.columns(2)
    if col1.button("Run", type="primary"):
        result = request("POST", f"/api/v1/demo/scenarios/{selected['name']}/run")
        (st.success if result["passed"] else st.error)("PASS" if result["passed"] else "FAIL")
        st.json(result)
    if col2.button("Reset demo data"):
        request("POST", "/api/v1/demo/reset")
        st.success("Демонстрационные данные сброшены")
