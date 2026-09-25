# Domain model

The model deliberately separates four kinds of truth:

| Layer | Examples | Mutation rule |
|---|---|---|
| Source record | `RawEvent`, `IngestAttempt` | accepted raw events are append-only and encrypted |
| Rebuildable state | `Item`, `OperationRun`, `Observation` | deterministically replaced by replay |
| Versioned analysis | `AnalysisVersion`, `AnalysisEvidence` | append a new version; never overwrite history |
| Human/integration record | `ControllerDecision`, `QualityResult`, `IntegrationMessage` | append-only business history |

An `Observation` is the immutable meaning projected from one accepted inspection event. Its derived trust is `TRUSTED`, `UNTRUSTED`, `UNASSESSABLE`, `CONFLICTED`, or `INVALIDATED`.

Multiple observations of the same physical defect link to an open `DefectOccurrence` by `(component_instance_id, defect_type)`, or by `(item_id, defect_type)` if the component is unknown. A new occurrence is created after the previous one is closed.

`Nonconformance` independently stores:

- verdict: `pending_review`, `needs_extra_check`, `confirmed`, or `rejected`;
- cause: `not_established`, `candidate`, or `confirmed_by_human`;
- disposition: `IN_PROCESS`, `REWORK_REQUIRED`, `RELEASED`, `SCRAPPED`, or `USE_AS_IS`;
- containment: `NONE`, `HOLD`, `REINSPECTION_REQUIRED`, or `REVIEW_REQUIRED`.

Rework is a new `OperationRun` with `run_reason=rework`, `previous_operation_run_id`, and `rework_for_nonconformance_id`. It never erases the original NCR. Release requires a controller decision; a new defect type creates a new occurrence/NCR.
