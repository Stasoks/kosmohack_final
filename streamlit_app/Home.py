from __future__ import annotations

import os

import streamlit as st

from streamlit_app.api_client.client import APIError, login
from streamlit_app.ui.navigation import authorized_page_specs
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
    # Calling navigation again with a hidden, login-only page clears the page
    # registry left by the previous authorized run. Rendering the form directly
    # leaves the old sidebar visible until another login.
    st.navigation(
        [st.Page(login_page, title="Вход", icon="🔑", default=True)],
        position="hidden",
    ).run()
    st.stop()

pages = [
    st.Page(
        views.guarded(getattr(views, spec.view_name)),
        title=spec.title,
        icon=spec.icon,
        default=spec.view_name == "overview",
    )
    for spec in authorized_page_specs(
        st.session_state.profile,
        demo_mode=os.getenv("DEMO_MODE", "false").lower() in {"1", "true", "yes"},
    )
]

navigation = st.navigation(pages)
navigation.run()
