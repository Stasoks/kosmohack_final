# Scenario suite

Every directory under `scenarios/` is an executable acceptance bundle. The same fixtures feed JSON Schema checks, PostgreSQL pytest, the FastAPI demo endpoint, and the Streamlit Scenario Runner. `events.jsonl` order is delivery order; `occurred_at` remains production time and is never used to reorder delivery.

| Scenario | Main assertion |
|---|---|
| S01 | normal flow, trusted inspections, no NCR |
| S02 | incoming defect gives LEFT_OPEN Birth Window |
| S03 | trusted GOOD → operation → DEFECT gives BOUNDED window; machine warning stays context |
| S04 | poor-quality GOOD is not a trusted boundary |
| S05 | missing required inspection is recorded as `MISSING_CHECK` |
| S06 | duplicate delivery is idempotent and does not double-count |
| S07 | late event rebuild appends AnalysisVersion v2 without rewriting raw history |
| S08 | controller confirms NCR, rework completes, repeat trusted GOOD is verified, item is released |
| S09 | privileged test tamper flips ciphertext and integrity verification fails |
| S10 | opposing equivalent inspections become `CONFLICTED` and do not create trusted boundaries |
| S11 | defect without prior trusted inspection stays LEFT_OPEN with an explicit limitation |
| S12 | two defect types create two occurrences; the same CP-POST-MILL GOOD is FULL for scratch but only PARTIAL for crack |
| S13 | `impossible_to_assess` is `UNASSESSABLE` and does not narrow the window |
| S14 | same event ID with changed content is `EVENT_ID_CONFLICT`; original raw fact remains |
| S15 | out-of-order delivery rebuilds one coherent operation run |
| S16 | failed rework keeps the NCR open and item in `REWORK_REQUIRED` |
| S17 | control-device invalidation invalidates derived trust and creates a wider analysis version |
| S18 | Blast Radius returns potentially affected items and only creates a proposal |
| S19 | controller decision stays committed while ERP retries the same message ID to delivery |
| S20 | unknown source cannot create raw/domain state and raises a security alert |
| S21 | nonce reuse is replay; a fresh nonce with identical event body reaches business duplicate handling |
| S22 | admin cannot issue QC decision; controlled export is denied before and allowed after final controller disposition |
| S23 | missing component structure degrades gracefully to item-level QC |
| S24 | route revision is pinned per item and later activation does not rewrite an older item |
| S25 | occurrence-based KPI distinguishes items, defect occurrences, rework and rejected signals |

## Harness V2

`ScenarioHarness` loads `scenario.json`, `events.jsonl`, `expected.json`, and optional `actions.json`, `requests.json`, `erp_behavior.json`, `tamper_actions.json`, `analysis_request.json`, and `route_change.json`. Actions may be triggered by delivery index, event ID, or a preceding action. Route changes with an activation timestamp are interleaved with delivery rather than applied after the whole file.

The FastAPI demo endpoint now uses this harness through a PostgreSQL-backed runtime adapter. Rework aliases such as `NC-S08` are resolved to the real NCR UUID before later rework events are ingested. Expected documents are subset business invariants, not byte-for-byte database snapshots; annotations such as `note` and `description` are not treated as assertions.

## Review flow

A compact review sequence is:

1. Run S03 and show the item timeline, Birth Window boundaries, machine warning as contextual evidence, and `cause_status=not_established`.
2. Run S08 and show controller decision, rework run, repeat trusted GOOD, controller verification and controlled release.
3. Run S17 and show the preserved v1 analysis beside the wider v2 analysis after device invalidation.
4. Run S18 and show Blast Radius exposures plus the still-unapplied containment proposal.
5. Run S19 and show the same outbox `message_id` across retry states until `DELIVERED`.
6. Run S09 and show ciphertext tamper detection.
7. Run S22 to demonstrate RBAC and the controlled-release gate.

Scenario Runner is an explainable demo surface and the same bundles are also executed automatically in the PostgreSQL CI job.

For a timed 5–7 minute walkthrough, use [demo.md](demo.md).
