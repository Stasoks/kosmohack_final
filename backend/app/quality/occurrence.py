from __future__ import annotations

from typing import Any


def defect_key(item_id: str, defect_type: str, component_instance_id: str | None) -> tuple[str, str]:
    return (component_instance_id or item_id, defect_type)


def can_link_occurrence(
    occurrence: Any,
    *,
    item_id: str,
    defect_type: str,
    component_instance_id: str | None,
) -> bool:
    if getattr(occurrence, "status", None) != "OPEN":
        return False
    return defect_key(
        getattr(occurrence, "item_id"),
        getattr(occurrence, "defect_type"),
        getattr(occurrence, "component_instance_id", None),
    ) == defect_key(item_id, defect_type, component_instance_id)
