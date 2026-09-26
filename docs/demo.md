# TRACE-Q demo: 5–7 minutes

This sequence is designed for the Scenario Runner and uses only named acceptance bundles. After each run, distinguish **Рассчитанное состояние системы** from the acceptance checklist, then open the human item timeline; raw events and JSON remain available only in technical expanders.

1. **S03 — Birth Window (about 75 seconds).** Show **Интервал возникновения локализован**, its last trusted GOOD, first trusted defect and operations inside the window. The machine warning is explicitly **Контекст, не доказанная причина**, while the cause remains **Причина не установлена**.
2. **S12 — coverage semantics (about 35 seconds).** One CP-POST-MILL GOOD shows **Полное покрытие** for scratch and **Частичное покрытие** for crack, including the explanation that PARTIAL cannot become a GOOD boundary. The later observation creates two occurrences: scratch is bounded, crack remains left-open.
3. **S08 — controller to release (about 70 seconds).** In the activity timeline show controller confirmation, linked rework start/finish, repeat trusted GOOD, verification, and release. Then open **Решения QC → Все несоответствия** and show the completed NCR read-only. The original occurrence remains in history.
4. **S19 — ERP offline and recovery (about 40 seconds).** The controller decision remains committed during the failure; the outbox retries the same `message_id` and reaches `DELIVERED` after the ERP ACK.
5. **S22, then S09 — security (about 55 seconds).** In S22, an unauthorized admin QC decision is denied and outbound export remains gated. In S09, a demo-only privileged ciphertext mutation is detected by integrity verification.
6. **S17 — evidence invalidation (about 40 seconds).** Invalidate CAM-02 evidence and show the preserved observation as **Инвалидировано**, followed by the explained Analysis v1 → v2 transition and widened window; the source observation is not deleted.
7. **S18 — Blast Radius (about 50 seconds).** Show A/B/C as potentially affected and D excluded. The analysis creates neither a new NCR nor a containment application; it creates a proposal. If demonstrating approval separately, show immutable applications only after an authorized, separated approval.

Close with the boundary: TRACE-Q correlates evidence and controls decisions; it does not claim an automatic root cause, industrial CV validation, or vendor integration that has not been commissioned.
