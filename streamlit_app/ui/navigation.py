from __future__ import annotations

from dataclasses import dataclass
import os


@dataclass(frozen=True)
class PageSpec:
    view_name: str
    title: str
    icon: str
    permission_any: frozenset[str] = frozenset()
    demo_only: bool = False


PAGE_SPECS = (
    PageSpec("overview", "Обзор", "🏭"),
    PageSpec("timeline", "История изделия", "🧭", frozenset({"VIEW_TIMELINE"})),
    PageSpec("pending_reviews", "Контроль качества", "✅", frozenset({"REVIEW_NONCONFORMANCE"})),
    PageSpec("analytics", "Аналитика", "📊", frozenset({"VIEW_ANALYTICS"})),
    PageSpec(
        "data_health",
        "Состояние данных",
        "🩺",
        frozenset({"VIEW_ANALYTICS", "MANAGE_INTEGRATIONS"}),
    ),
    PageSpec("route_editor", "Маршруты", "🛤️", frozenset({"MANAGE_ROUTES"})),
    PageSpec(
        "blast_radius",
        "Риски / радиус влияния",
        "🎯",
        frozenset(
            {"RUN_BLAST_RADIUS", "APPROVE_CONTAINMENT", "INVALIDATE_CONTROL_DEVICE"}
        ),
    ),
    PageSpec("admin_panel", "Администрирование", "🔐", frozenset({"MANAGE_USERS"})),
    PageSpec(
        "scenario_runner",
        "Приёмочные сценарии",
        "🧪",
        frozenset({"RUN_DEMO_SCENARIOS"}),
        True,
    ),
    PageSpec("factory_simulator", "Симуляция производства", "🏗️", demo_only=True),
)


def authorized_page_specs(
    profile: dict | None, demo_mode: bool | None = None
) -> list[PageSpec]:
    if not profile:
        return []
    permissions = set(profile.get("permissions") or [])
    if demo_mode is None:
        demo_mode = os.getenv("DEMO_MODE", "false").lower() in {"1", "true", "yes"}
    return [
        spec
        for spec in PAGE_SPECS
        if (not spec.demo_only or demo_mode)
        and (not spec.permission_any or permissions.intersection(spec.permission_any))
    ]
