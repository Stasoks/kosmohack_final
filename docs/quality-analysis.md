# Quality analysis

## Trust

A trusted GOOD/DEFECT boundary must satisfy the versioned control-point policy: allowed observation quality, optional confidence requirement and threshold, optional device validity, optional media, inspection scope, no invalidation, and no unresolved equivalent conflict. Missing media is not a failure unless the policy requires it.

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

Conflicts group by `capture_session_id`, falling back to a bounded five-minute control-point session. Opposing eligible GOOD/DEFECT observations become CONFLICTED and cannot create a trusted boundary. Device invalidation changes derived trust, preserves the observation and prior AnalysisVersion, and recalculates the birth window. KPI counts DefectOccurrence rather than observations; duplicates do not change KPI and successful rework does not retroactively restore first-pass yield.
