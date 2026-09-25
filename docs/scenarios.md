# Scenario suite

Every directory under `scenarios/` contains `events.jsonl` and `expected.json`. The same fixtures feed JSON Schema checks, pytest, seed/demo tooling, and the Streamlit Scenario Runner.

| Scenario | Main assertion |
|---|---|
| S01 normal | coherent history and no NCR |
| S02 incoming defect | left-open window before operations; no operator attribution |
| S03 new defect | GOOD → operation → DEFECT gives bounded window |
| S04 uncertainty | poor/impossible observations do not create trusted boundaries |
| S05 machine event | warning is contextual evidence, not root cause |
| S06 duplicate | second delivery changes no domain count |
| S07 late/out-of-order | deterministic replay appends AnalysisVersion v2 |
| S08 user decision | prepares an NCR for the controller append-only workflow |
| S09 tamper | privileged demo mutation causes integrity failure |

## Full defense demo

1. Reset demo data and run S03 as controller.
2. Open `ITEM-S03`: show trusted GOOD, OP-TURN, trusted DEFECT, boundaries, evidence, limitations, and `cause_status=not_established`.
3. Set ERP behavior to `TIMEOUT_ONCE` or `OFFLINE` through its API.
4. Confirm the NCR with `REWORK_REQUIRED` and `HOLD`. The decision stays committed while outbox becomes `RETRYING`.
5. Return ERP to `NORMAL`; show the same message ID becomes `DELIVERED` and the emulator exposes its ACK.
6. Run S07 after reset; show analysis v1 and v2 and the changed left boundary.
7. Run S09 after reset as admin; `Verify Integrity` reports failure. Attempting a new controller decision based on that item is blocked.

Scenario Runner is an explainable demo surface, not a replacement for automated tests.

## Harness V2

S01-S25 are discoverable acceptance bundles. The harness reads `scenario.json`, `events.jsonl`, `expected.json`, and optional actions/requests/ERP/tamper/analysis/route files. File order is delivery order; `occurred_at` is production time and is never used to reorder delivery. Expected documents are subset business invariants rather than database snapshots.
