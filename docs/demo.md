# TRACE-Q demo: 5–7 minutes

This sequence is designed for the Scenario Runner and uses only named acceptance bundles. Keep the item timeline and evidence panel visible; the point is explainability, not how fast JSON can scroll.

1. **S03 — Birth Window (about 75 seconds).** Show the trusted `scratch_or_gouge` GOOD at CP-POST-MILL, grinding operation, machine warning, and trusted defect at CP-POST-GRIND. Point out the bounded interval and that the warning is `CONTEXT`, while `cause_status` remains `not_established`.
2. **S12 — coverage semantics (about 35 seconds).** One CP-POST-MILL GOOD covers scratch as `FULL` and crack as `PARTIAL`. The later observation creates two occurrences: scratch is bounded, crack remains left-open. Trust and boundary eligibility are separate decisions.
3. **S08 — controller to release (about 70 seconds).** Show controller confirmation, linked rework run, repeat trusted GOOD, verification, and release. The original occurrence remains in history.
4. **S19 — ERP offline and recovery (about 40 seconds).** The controller decision remains committed during the failure; the outbox retries the same `message_id` and reaches `DELIVERED` after the ERP ACK.
5. **S22, then S09 — security (about 55 seconds).** In S22, an unauthorized admin QC decision is denied and outbound export remains gated. In S09, a demo-only privileged ciphertext mutation is detected by integrity verification.
6. **S17 — evidence invalidation (about 40 seconds).** Invalidate CAM-02 evidence and show that v1 remains preserved while v2 widens the window; the source observation is not deleted.
7. **S18 — Blast Radius (about 50 seconds).** Show A/B/C as potentially affected and D excluded. The analysis creates neither a new NCR nor a containment application; it creates a proposal. If demonstrating approval separately, show immutable applications only after an authorized, separated approval.

Close with the boundary: TRACE-Q correlates evidence and controls decisions; it does not claim an automatic root cause, industrial CV validation, or vendor integration that has not been commissioned.
