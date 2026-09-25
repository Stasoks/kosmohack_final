from __future__ import annotations

from typing import Any

from backend.app.quality.trust import scope_covers


def repeat_good_covers_nonconformance(
    observation: Any,
    *,
    defect_type: str,
    component_instance_id: str | None,
) -> bool:
    """Return True only when a trusted repeat GOOD actually covers the NCR defect scope."""
    if getattr(observation, "inspection_result", None) != "no_defect":
        return False
    if getattr(observation, "trust_status", None) != "TRUSTED":
        return False

    observation_component = getattr(observation, "component_instance_id", None)
    if component_instance_id is None:
        # An item-level/unknown-component NCR must not be cleared by a GOOD
        # that only identifies one particular component.
        if observation_component is not None:
            return False
    elif observation_component not in (None, component_instance_id):
        return False

    return scope_covers(
        getattr(observation, "inspection_scope", None),
        defect_type,
        component_instance_id,
    )
