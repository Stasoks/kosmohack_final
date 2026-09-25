# Integrations

The business core addresses `ProductionSystemAdapter`, not external field names. The working `EmulatorAdapter` receives jobs/references and sends `QualityResult`; fixture transports demonstrate the same port for 1C, Galaktika:ERP, and MES without inventing vendor endpoints. `JsonProductStructureProvider` is represented by immutable structure snapshots.

External identifiers are mapped in `external_identities`; vendor GUIDs never become internal primary keys. The unique boundary is `(external_system, external_entity_type, external_id)`.

Controller decision, `QualityResult`, and `OutboxMessage` are created in one PostgreSQL transaction. The worker retains one message ID across retries:

- timeout, network error, 408, 429, and 5xx → `RETRYING` with bounded exponential delay;
- 400/auth/schema/config error → `FAILED`;
- successful ACK → `DELIVERED` plus append-only `IntegrationMessage`.

ERP modes are `NORMAL`, `TIMEOUT_ONCE`, `ERROR_503`, `REJECT_400`, and `OFFLINE`. The backend health check does not depend on ERP availability.

Target ownership:

| System | Inbound authority | Outbound result | Mapping boundary |
|---|---|---|---|
| 1C / Galaktika | production job and references | QC result/disposition | adapter DTO + external identity |
| MES | execution events | decision/hold notification | canonical event adapter |
| KOMPAS-3D | assembly revision/structure | none in P0 | product-structure provider |

If structure is unavailable, `structure_status=unavailable`; component analysis degrades but item-level QC continues. Same revision with a different content hash must create `REVISION_CONTENT_CHANGED`, never overwrite a snapshot.

## Controlled outbound and KOMPAS fallback

Only `OutboundReleasePolicy` can construct a QualityResult and outbox message. Rework and raw defect signals are not exportable decisions. ACK correlation must match the stable message ID. KOMPAS remains behind `KompasProductStructureProvider`; absence sets `structure_status=degraded` while item-level analysis, NCR, rework, and release remain available.
