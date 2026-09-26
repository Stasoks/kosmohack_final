from __future__ import annotations

from streamlit_app.ui import views


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
        views.scenario_runner,
    ]

    guarded_pages = [views.guarded(render) for render in page_functions]

    assert [page.__name__ for page in guarded_pages] == [
        render.__name__ for render in page_functions
    ]
    assert len({page.__name__ for page in guarded_pages}) == len(guarded_pages)
