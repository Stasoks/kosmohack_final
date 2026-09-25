# Security

## Identity and authorization

Human passwords use Argon2id. Access JWTs contain only subject/user/session timestamps and expire after about 15 minutes. Opaque refresh tokens expire after about eight hours, are stored only as SHA-256 hashes, rotate on use, and can be revoked. Five failures lock the account for about 15 minutes.

Endpoints check effective permissions, not role strings. In particular, `admin` cannot issue a QC decision, and `technologist` cannot approve containment. Source authentication is a separate identity plane and grants no human permission.

## Raw confidentiality and integrity

Canonical plaintext events are encrypted with AES-256-GCM using a unique 96-bit nonce. AAD binds event ID/type, source, schema version, and server receive time. The database stores ciphertext, nonce, crypto profile, key ID, and key version; the key comes from environment/Docker secrets and is not stored in Git, the DB, or the image.

Each stable source stream carries an HMAC-SHA-256 chain over the previous MAC, immutable metadata, ciphertext, nonce, and key ID. Audit entries use a separate serialized HMAC chain over their immutable audit payload. The HMAC secret is distinct from the AES key and outside the DB. Integrity verification checks both raw-event and audit chains, raises security alerts on mismatch, and raw-stream failure blocks new decisions using affected evidence; old decisions remain historical facts.

The runtime DB role has no UPDATE/DELETE grant on raw events, controller decisions, audit, integration history, or analysis versions/evidence. Owner-level PostgreSQL triggers provide a second append-only guard. The demo-only privileged endpoint is registered only when `DEMO_MODE=true` and deliberately flips a ciphertext bit so verification can demonstrate detection.

## Secrets and logs

Production-like mode rejects known demo JWT/source secrets. Set DB passwords, JWT signing secret, AES key, HMAC key, source tokens, and integration credentials through an external secret mechanism. Structured request logs contain request/user/source IDs, endpoint, status, and duration, but never authorization headers, passwords, refresh/source tokens, crypto keys, or plaintext raw payloads.

## Network boundary

PostgreSQL and the worker are internal-only in `compose.yaml`; debug ports exist only in `compose.demo.yaml`. Production places an HTTPS reverse proxy in front of FastAPI/Streamlit. External adapters must verify TLS certificates; Basic authentication, if a site-specific transport needs it, is permitted only over verified TLS.

Threat boundaries and residual risks include privileged host/owner compromise, secret theft, source-clock manipulation, denial of service, and legitimate-but-false source observations. Encryption, authentication, immutable history, and integrity are separate controls; none alone solves all four.

## Transport, sessions, and profiles

HMAC_V1 signs `timestamp + "\\n" + nonce + "\\n" + canonical_json(body)` with an environment-provided source secret. Nonces are durable replay facts; a duplicate event with a fresh nonce reaches business idempotency, while nonce reuse is a transport replay. Critical actions require an active, fresh server-side session, permission, valid state and a reason. CLASSIC_V1/V2 use AES-256-GCM plus HMAC-SHA256; checkpoint metadata supports ECDSA P-256. HYBRID_PQ_V1 is optional and must use a vetted ML-DSA-65 library.
