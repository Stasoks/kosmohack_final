# Quality analysis

## Trust

A trusted GOOD/DEFECT boundary must satisfy the versioned control-point policy: allowed observation quality, optional confidence requirement and threshold, optional device validity, optional media, inspection scope, no invalidation, and no unresolved equivalent conflict. Missing media is not a failure unless the policy requires it.

Inspection coverage is evaluated per `(defect_type, component_instance_id)` key. The effective value is the intersection of the control-point capability stored in `RouteStep.inspection_scope`, the scope reported by the observation, and a targeted rework scope when applicable:

- `FULL`: eligible to be a trusted GOOD boundary;
- `PARTIAL`: the observation can remain trusted evidence, but cannot close the left boundary for that key;
- `NONE`: irrelevant to that key;
- `TARGET_ONLY`: may verify only the NCR key linked to the rework run and is never a general historical GOOD boundary.

The compatibility helper `scope_covers(...)` returns true only for `FULL`. An item-level NCR (`component_instance_id=null`) requires explicit item-wide coverage; an empty reported component list is the supported degraded item-level fallback.

`impossible_to_assess` is always `UNASSESSABLE`. A poor or otherwise untrusted defect may open `needs_extra_check`, but it cannot become the trusted right boundary of a Birth Window.

## Defect Birth Window

For the first trusted defect D of a defect occurrence, replay walks earlier capable inspections and selects the latest trusted GOOD G for the same defect/component scope:

```text
G found:   window = (G.occurred_at, D.occurred_at]  → BOUNDED
G absent:  window = (OPEN, D.occurred_at]           → LEFT_OPEN
```

Evidence is relational and typed. Boundaries are `LAST_TRUSTED_GOOD` and `FIRST_TRUSTED_DEFECT`; operations, machine warnings, and operator actions are context; poor/conflicting observations and missing checks are limitations. A warning is never promoted automatically to a root cause.

Late events can change boundaries. Replay appends AnalysisVersion v2 with `reason=late_event_rebuild`; v1 remains available. Human cause confirmation is a separate record and is not produced by this algorithm.

The current KPI endpoint reports the calculation timestamp and explicitly labels station grouping as detection/context rather than causality.

## Conflicts, invalidation, and KPI

A conflict requires the same item, logical inspection session, control point, overlapping component scope, overlapping defect type, equal source priority, and incompatible `no_defect`/`defect_detected` claims. Current P0 sources have equal priority. A logical session uses `capture_session_id`; without it, replay uses `(item, control point, operation run, 60-second bucket)`. Different defects, components, sessions, or priorities do not conflict merely because the top-level results differ.

Conflicted observations cannot create a trusted boundary. Device invalidation changes derived trust, preserves the observation and prior AnalysisVersion, and recalculates the birth window. KPI counts DefectOccurrence rather than observations; duplicates do not change KPI and successful rework does not retroactively restore first-pass yield.
