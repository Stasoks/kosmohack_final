from __future__ import annotations

import streamlit as st

from streamlit_app.api_client.client import APIError, login
from streamlit_app.ui import views


st.set_page_config(page_title="TRACE-Q", page_icon="🛰️", layout="wide")


def login_page() -> None:
    st.title("TRACE-Q")
    st.caption("Контроль качества и прослеживаемость изделия")
    with st.form("login"):
        username = st.text_input("Пользователь")
        password = st.text_input("Пароль", type="password")
        submitted = st.form_submit_button("Войти", type="primary", use_container_width=True)
    if submitted:
        try:
            login(username, password)
            st.rerun()
        except APIError as exc:
            st.error(f"{exc.code}: {exc.message}")


if "auth" not in st.session_state or "profile" not in st.session_state:
    login_page()
    st.stop()

permissions = set(st.session_state.profile["permissions"])
pages = [st.Page(views.guarded(views.overview), title="Обзор", icon="🏭", default=True)]
if "REVIEW_NONCONFORMANCE" in permissions:
    pages.append(st.Page(views.guarded(views.pending_reviews), title="Решения QC", icon="✅"))
if "VIEW_TIMELINE" in permissions:
    pages.append(st.Page(views.guarded(views.timeline), title="История изделия", icon="🧭"))
if "VIEW_ANALYTICS" in permissions:
    pages.append(st.Page(views.guarded(views.analytics), title="Аналитика", icon="📊"))
if "VIEW_ANALYTICS" in permissions or "MANAGE_INTEGRATIONS" in permissions:
    pages.append(st.Page(views.guarded(views.data_health), title="Data Health", icon="🩺"))
if "MANAGE_ROUTES" in permissions:
    pages.append(st.Page(views.guarded(views.route_editor), title="Маршруты", icon="🛤️"))
if "MANAGE_USERS" in permissions:
    pages.append(st.Page(views.guarded(views.admin_panel), title="Администрирование", icon="🔐"))
if "RUN_DEMO_SCENARIOS" in permissions:
    pages.append(st.Page(views.guarded(views.scenario_runner), title="Scenario Runner", icon="🧪"))

navigation = st.navigation(pages)
navigation.run()
