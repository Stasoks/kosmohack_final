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
- Evidence invalidation and blast-radius automation are planned score-boost extensions after the stable P0 path; their event/model boundaries are documented in the master plan but are not misrepresented as completed industrial functions.

## Prepared, not executed

The implementation includes migrations, unit/PostgreSQL/security/scenario tests, Compose profiles, CI and benchmark tools. They were intentionally not executed by the implementation agent. The HMAC_V1 demo transport is not an mTLS replacement; PQ checkpoint support is optional; vendor KOMPAS/ERP bridges remain site-specific adapters.
