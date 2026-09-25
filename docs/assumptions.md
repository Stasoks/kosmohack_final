# Assumptions and limitations

- All demo products, thresholds, routes, equipment, durations, and defect examples are synthetic.
- Source timestamps are timezone-aware UTC. TRACE-Q records receive time but does not yet estimate per-source clock drift.
- A missing inspection produces a limitation, not a fabricated negative observation.
- Default trust accepts only `observation_quality=good`; confidence and media are optional unless a versioned policy requires them.
- Equivalent opposing observations at the same time/control point/component become `CONFLICTED`.
- Machine state and operator action are context. Only a human can confirm a cause.
- Component structure may be unavailable. Item-level registration, NCR, and disposition still work.
- Fixture adapters are not claims of compatibility with an unknown customer installation; real endpoints, auth, schemas, and TLS roots must be supplied during site integration.
- The demo profile exposes localhost API/ERP/PostgreSQL debug ports. Production-like Compose keeps the DB internal and requires an HTTPS boundary.
- Evidence invalidation and Blast Radius are implemented in the MVP, but Blast Radius remains proposal-first: it does not create defects or apply containment until the explicit approval workflow completes.
- The HMAC_V1 demo transport is not an mTLS replacement.
- Vendor KOMPAS/ERP/MES transports remain site-specific adapters because the case does not provide production endpoint/authentication specifications.
- `HYBRID_PQ_V1` remains an optional profile boundary. The default tested path is classical AES-256-GCM/HMAC-SHA256 with ECDSA-P256 checkpoint support; ML-DSA-65 must not be claimed as runtime-verified unless the optional library and keys are actually installed and exercised.

## Verification status

CI executes deterministic contract generation checks, 133 contract fixtures, unit/security tests, PostgreSQL integration tests, S01-S25 through the real demo API, Python compilation, and a bounded Docker Compose demo smoke job. A green workflow is the evidence for a tested revision; documentation alone is not treated as proof.
