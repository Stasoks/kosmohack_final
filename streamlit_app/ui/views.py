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
        st.dataframe(request("GET", "/api/v1/admin/users"), use_container_width=True, hide_index=True)
    with tabs[1]:
        st.dataframe(request("GET", "/api/v1/admin/sources"), use_container_width=True, hide_index=True)
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
    header("Blast Radius и containment proposal")
    with st.form("blast_radius"):
        factor_type = st.selectbox("Фактор", ["equipment", "tool", "material_lot", "control_device", "component", "time_interval"])
        factor_value = st.text_input("ID / значение")
        affected_from = st.text_input("Начало ISO-8601")
        affected_to = st.text_input("Конец ISO-8601")
        action = st.selectbox("Предложение", ["REVIEW_REQUIRED", "REINSPECTION_REQUIRED", "HOLD"])
        rationale = st.text_area("Обоснование")
        if st.form_submit_button("Рассчитать и создать proposal"):
            result = request("POST", "/api/v1/risk/blast-radius", json={"factor_type": factor_type,
                "factor_value": factor_value, "affected_from": affected_from, "affected_to": affected_to,
                "proposed_action": action, "rationale": rationale})
            st.warning("Расчёт сам по себе не создаёт дефект и не применяет HOLD.")
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
