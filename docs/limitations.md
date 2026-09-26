# Current limitations

- Demo routes, products, thresholds, defect labels, identities, and timings are synthetic.
- VisionQC is an external structured-observation source; no production CV model is included or industrially validated.
- Camera count, 12 MP/global-shutter choice, latency, and 0.2–0.3 mm sampling estimate are project assumptions pending site tests.
- Visual inspection cannot replace required dimensional metrology or NDT for subsurface/weld claims.
- Root cause is never inferred from temporal correlation alone; final NCR disposition and containment require authorized humans.
- Real MES/ERP/KOMPAS endpoints, credentials, mappings, TLS, retention, and network controls remain site-specific integration work.
- PostgreSQL is the supported persistence path; component structure may degrade to item-level QC, but that loses localization precision.
- The runtime event contract is version 1.0 only. The 1.1 schema under `contracts/events/evolution` is a non-runtime evolution proof.
- Demo security profiles and credentials are not production credentials; optional hybrid-PQ support is not a claim of deployment validation.

See the fuller [assumptions](assumptions.md), [security boundary](security.md), and [VisionQC design](vision-control-design.md).
