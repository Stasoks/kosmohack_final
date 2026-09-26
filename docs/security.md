# Security

## Identity and authorization

Human passwords use Argon2id. Access JWTs contain only subject/user/session timestamps and expire after about 15 minutes. Opaque refresh tokens expire after about eight hours, are stored only as SHA-256 hashes, rotate on use, and can be revoked. Five failures lock the account for about 15 minutes.

Endpoints check effective permissions from `RolePermission` in PostgreSQL on every request, not role strings or permissions cached in the access token. A permission edit therefore affects an already-issued access token on its next request. In particular, `admin` cannot issue a QC decision, and `technologist` cannot approve containment. Source authentication is a separate identity plane and grants no human permission.

An administrator with a fresh session and `MANAGE_USERS` can edit ordinary role capabilities in **Администрирование → Роли и права**. Every change records before/after/added/removed sets and the required reason in audit. `simulator_reader` is system-locked, and role/user changes are rejected if they would leave no enabled human user with effective `MANAGE_USERS`. Seed creates defaults only for a new role and does not silently restore a capability removed later by an administrator.

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

HMAC_V1 signs `timestamp + "\\n" + nonce + "\\n" + canonical_json(body)` with an environment-provided source secret. Nonces are durable replay facts; a duplicate event with a fresh nonce reaches business idempotency, while nonce reuse is a transport replay. Critical actions require an active, fresh server-side session, permission, valid state and a reason. CLASSIC_V1/V2 use AES-256-GCM plus HMAC-SHA256; classic integrity checkpoints use ECDSA P-256 with SHA-256.

`HYBRID_PQ_V1` is an optional checkpoint-signing runtime implemented with `liboqs-python` and ML-DSA-65. ECDSA and ML-DSA sign the same versioned canonical payload. Hybrid verification is `VERIFIED` only when both signatures verify; a missing signature or tamper is `FAILED`, while a historical key that is no longer available is reported as `UNVERIFIABLE`. Activation runs both algorithm/key self-tests and is rejected when the optional runtime or a required key is unavailable—there is no silent downgrade to classic.

Checkpoint keyrings come from `CHECKPOINT_CLASSIC_KEYS_JSON` and `CHECKPOINT_PQ_KEYS_JSON`; key IDs and versions are stored with a checkpoint, while private keys remain outside PostgreSQL. Old public keys must remain in the external keyring for historical verification. The default install and Compose stack do not require the PQ extra or activate hybrid mode. A real optional proof is run with:

```bash
uv sync --extra pq
python scripts/pq_smoke.py
python scripts/verify_final_improvements.py --pq
```

This proves the repository's signing and verification behavior; it is not certification of a production deployment, HSM, or key ceremony.
