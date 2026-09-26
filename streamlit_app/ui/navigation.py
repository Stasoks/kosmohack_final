from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PageSpec:
    view_name: str
    title: str
    icon: str
    permission_any: frozenset[str] = frozenset()


PAGE_SPECS = (
    PageSpec("overview", "Обзор", "🏭"),
    PageSpec("pending_reviews", "Решения QC", "✅", frozenset({"REVIEW_NONCONFORMANCE"})),
    PageSpec("timeline", "История изделия", "🧭", frozenset({"VIEW_TIMELINE"})),
    PageSpec("analytics", "Аналитика", "📊", frozenset({"VIEW_ANALYTICS"})),
    PageSpec(
        "data_health",
        "Data Health",
        "🩺",
        frozenset({"VIEW_ANALYTICS", "MANAGE_INTEGRATIONS"}),
    ),
    PageSpec("route_editor", "Маршруты", "🛤️", frozenset({"MANAGE_ROUTES"})),
    PageSpec(
        "blast_radius",
        "Risk / Blast Radius",
        "🎯",
        frozenset(
            {"RUN_BLAST_RADIUS", "APPROVE_CONTAINMENT", "INVALIDATE_CONTROL_DEVICE"}
        ),
    ),
    PageSpec("admin_panel", "Администрирование", "🔐", frozenset({"MANAGE_USERS"})),
    PageSpec(
        "scenario_runner",
        "Scenario Runner",
        "🧪",
        frozenset({"RUN_DEMO_SCENARIOS"}),
    ),
)


def authorized_page_specs(profile: dict | None) -> list[PageSpec]:
    if not profile:
        return []
    permissions = set(profile.get("permissions") or [])
    return [
        spec
        for spec in PAGE_SPECS
        if not spec.permission_any or permissions.intersection(spec.permission_any)
    ]
