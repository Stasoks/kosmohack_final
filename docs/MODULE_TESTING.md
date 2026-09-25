# TRACE-Q module testing guide

This document is for manual verification after the stack is running. For startup commands see `docs/LOCAL_RUNBOOK.md`.

The fastest test surface is Streamlit -> **Scenario Runner**. Every S01-S25 bundle is also executed automatically by the PostgreSQL CI suite, but the UI lets you inspect the resulting state and explain it during the demo.

## 1. Basic health and login

Run:

```bash
bash scripts/local_smoke.sh
```

Then open http://localhost:8501 and log in as `controller / controller-demo`.

Expected:

- UI opens without a backend error;
- Overview is visible;
- Scenario Runner is available;
- logout removes the active session and returns to the login page.

Useful RBAC check: log in as `admin`. The administrator can manage users/integrations and inspect security, but does not receive the QC decision permission.

## 2. Normal QC path

Run **S01**.

Expected result: PASS.

Inspect:

- Overview -> `ITEM-S01`;
- Item history;
- three trusted observations;
- no NCR;
- item remains `IN_PROCESS`.

This checks the ordinary path where quality observations do not create a nonconformance.

## 3. Defect Birth Window

### Bounded window

Run **S03**.

Expected:

- one NCR for `surface_crack`;
- Birth Window status `BOUNDED`;
- last trusted GOOD = `EV-S03-004`;
- first trusted DEFECT = `EV-S03-008`;
- `RUN-S03-GRIND` is inside the interval;
- machine warning is shown as contextual evidence;
- `cause_status=not_established`.

The important demo statement is: TRACE-Q localizes the interval in which the defect could have appeared. A machine warning inside the interval is context, not proof that the machine caused the defect.

### No trusted observation before the defect

Run **S02** or **S11**.

Expected:

- Birth Window is `LEFT_OPEN`;
- no fabricated GOOD boundary;
- S11 includes `NO_PREVIOUS_TRUSTED_INSPECTION`.

## 4. Observation trust and uncertainty

Run the following scenarios:

| Scenario | What to inspect |
|---|---|
| S04 | poor-quality GOOD becomes `UNTRUSTED` and does not narrow the Birth Window |
| S10 | contradictory equivalent observations become `CONFLICTED` |
| S13 | `impossible_to_assess` becomes `UNASSESSABLE` |

For S10, neither conflicting observation may become a trusted GOOD or trusted DEFECT boundary.

## 5. Required checks and route gaps

Run **S05**.

Expected:

- Birth Window remains explainable;
- limitation includes `MISSING_CHECK`;
- missing control point is `CP-POST-MILL`.

A missing inspection is represented as missing evidence. TRACE-Q must not silently invent a successful inspection.

## 6. Duplicate, conflict and delivery ordering

### Legitimate duplicate

Run **S06**.

Expected:

- 5 deliveries;
- 4 unique raw events;
- 1 duplicate;
- KPI/domain counts do not increase twice.

### Same event ID with changed content

Run **S14**.

Expected:

- first delivery accepted;
- second delivery -> `409 EVENT_ID_CONFLICT`;
- original stored revision remains unchanged.

### Out-of-order production events

Run **S15**.

Expected:

- one coherent `RUN-S15-MILL`;
- correct production start and finish times;
- no projection failure.

## 7. Late events and reproducible analysis versions

Run **S07**.

Expected:

- AnalysisVersion v1 is preserved;
- late evidence produces v2;
- raw history is not rewritten;
- v2 can have a narrower or otherwise changed Birth Window based on the newly available historical fact.

Run **S17** for a stronger version of this behavior.

Expected:

- an older trusted observation becomes `INVALIDATED`;
- v1 remains stored;
- v2 is created;
- the Birth Window widens after invalidation.

## 8. Rework lifecycle

### Successful rework

Run **S08**.

Expected:

- controller confirms the NCR;
- rework operation is linked to that NCR;
- repeat trusted GOOD covers the original defect/component scope;
- controller verifies the rework;
- NCR is closed with `resolution_type=rework`;
- item disposition becomes `RELEASED`;
- original defect occurrence remains in history.

### Failed rework

Run **S16**.

Expected:

- same physical defect occurrence remains;
- verification is `FAILED`;
- NCR stays open;
- item remains `REWORK_REQUIRED`.

The repeat inspection logic is defect-scope aware. A GOOD restricted to another defect or another component must not clear the NCR.

## 9. Multiple defect types and KPI identity

Run **S12**.

Expected:

- two defect occurrences for one item;
- one `surface_crack`;
- one `scratch_or_gouge`;
- item count and defect occurrence count remain different concepts.

Run **S25**.

Expected:

- population = 6 items;
- inspected = 6;
- assessable = 5;
- 3 items with confirmed nonconformities;
- 4 confirmed physical defect occurrences;
- 1 rework item.

This is the scenario to show that TRACE-Q does not count every observation as a new physical defect.

## 10. Evidence integrity and tamper detection

Run **S09**.

Expected:

- integrity verification before mutation = `OK`;
- the demo-only privileged mutation changes encrypted raw storage;
- verification after mutation = `INTEGRITY_FAILED`.

The mutation endpoint exists only in demo mode. Raw history is append-only for the normal runtime database role.

In Administration -> **Целостность**, use **Verify Integrity** to inspect both raw-event and audit integrity status.

## 11. Source authentication, replay and unknown sources

Run:

| Scenario | Expected |
|---|---|
| S20 | unknown source rejected, no raw/domain fact created, security alert generated |
| S21 | first signed request accepted, nonce reuse rejected as replay, fresh nonce + identical event handled as business duplicate |

This demonstrates the distinction between transport replay and idempotent retry.

## 12. Blast Radius and containment approval

Run **S18** as a role with Scenario Runner permission.

Expected from the scenario:

- potentially affected: `ITEM-S18-A`, `ITEM-S18-B`, `ITEM-S18-C`;
- `ITEM-S18-D` is outside the radius;
- no defect is assigned automatically;
- containment is still only a proposal.

For the human approval path:

1. Log in as `controller`.
2. Open **Risk / Blast Radius**.
3. Open pending approvals.
4. Approve the proposal with a reason.

Expected:

- proposal becomes approved;
- immutable `ContainmentApplication` facts are created for the affected items;
- human approval is required before application;
- the requester cannot approve their own proposal.

The PostgreSQL integration suite separately checks that S18 creates zero applications before approval and three after controller approval.

## 13. Control-device invalidation

The scenario path is **S17**.

For the manual UI path:

1. Log in as `controller`.
2. Open **Risk / Blast Radius**.
3. Use **Инвалидация контрольного устройства**.
4. Enter device ID, affected interval and reason.

Expected:

- an immutable invalidation fact is stored;
- affected observations are not deleted;
- derived trust becomes `INVALIDATED`;
- affected item projections are rebuilt;
- a new analysis version can widen the Birth Window.

## 14. Controlled release and ERP outbox

### Policy gate

Run **S22**.

Expected:

- admin QC decision attempt -> DENIED;
- export before valid controller disposition -> DENIED;
- controller disposition -> ALLOWED;
- export after valid disposition -> ALLOWED;
- audit records are present.

### Retry and stable message ID

Run **S19**.

Expected:

- controller decision remains committed;
- outbox reaches `DELIVERED`;
- retry uses the same `message_id`;
- ERP failure never rolls back the human decision.

The PostgreSQL test suite also calls the real `worker.process_one()` path: a simulated network outage moves the message to `RETRYING` and integration health to `UNHEALTHY`; the next ACK moves the same message to `DELIVERED` and health back to `HEALTHY`.

You can watch the real worker:

```bash
docker compose -f compose.yaml -f compose.demo.yaml logs -f worker erp-emulator
```

## 15. ERP emulator and adapter boundary

Open Administration -> **Интеграции** and run ERP synchronization.

Expected:

- jobs and references are fetched from the emulator;
- external job identity is mapped through `ExternalIdentity`;
- integration health becomes `HEALTHY`.

The emulator supports:

- `NORMAL`
- `TIMEOUT_ONCE`
- `ERROR_503`
- `REJECT_400`
- `OFFLINE`

1C, Galaktika and MES are fixture transport boundaries because the case does not provide a real customer endpoint/auth/schema. Do not describe these fixture adapters as completed production integrations.

## 16. Product structure and KOMPAS fallback

Run **S23**.

Expected:

- component structure is unavailable/degraded;
- item-level QC continues;
- NCR and Birth Window still work;
- defect identity falls back to item level.

The working MVP provider is JSON/snapshot based. The Windows/KOMPAS bridge remains an external vendor-specific boundary.

## 17. Route revisions

Run **S24**.

Expected:

- old item remains pinned to route revision v1;
- new item uses v2;
- activating a new revision does not rewrite the old item's route history.

For manual testing, log in as `technologist` and open **Маршруты**. Create a new draft revision, edit steps and activate it with a reason. Route activation is a critical action and requires a fresh authenticated session.

Route JSON import is also treated as a critical route-management action. If imported with `activate=true`, the previous active revision is superseded rather than leaving two active revisions.

## 18. Contracts and code generation

With Python 3.12 + uv:

```bash
uv sync --all-groups
./scripts/run_tests.sh contracts
```

Expected:

- generated Pydantic event models match the canonical JSON Schema;
- registry is deterministic;
- all contract fixtures validate;
- drift causes the check to fail.

The canonical source is:

```text
contracts/events/canonical-event.schema.json
```

Generated artifacts are:

```text
shared_contracts/generated/events.py
shared_contracts/generated/registry.json
```

## 19. Load tooling

Generate a small JSONL set:

```bash
uv run python scripts/generate_load.py --profile configs/load_profile.json --output /tmp/traceq-load.jsonl
```

Or generate/send a synthetic registration stream:

```bash
uv run python scripts/generate_events.py \
  --sources 2 \
  --items 20 \
  --events-per-second 5 \
  --duplicate-rate 0.05 \
  --late-rate 0.05
```

The generator now emits the canonical envelope without duplicating `item_id` in the payload. Demo seed registers `LOAD-MES-01` through `LOAD-MES-10` when the demo source token is configured.

Avoid running a large benchmark immediately before the presentation. It adds noise without proving more than the deterministic scenario suite.

## 20. Recommended presentation sequence

If there is only a few minutes, use this order:

1. **S03**: Birth Window and non-causal machine warning.
2. **S08**: controller decision, rework, repeat inspection, release.
3. **S17**: evidence invalidation and AnalysisVersion v2.
4. **S18**: Blast Radius proposal, then human approval.
5. **S19**: outbox retry and stable message ID.
6. **S09**: tamper detection.
7. **S22**: RBAC and controlled outbound release.

That sequence covers most of the technically interesting parts without making the jury watch 25 folders of JSON achieve sentience.
