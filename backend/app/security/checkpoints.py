from __future__ import annotations

import base64
import hashlib
from dataclasses import asdict, dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.errors import TraceQError
from backend.app.persistence.models import (
    CryptoProfile,
    IntegrityCheckpoint,
    IntegrityStreamState,
)
from backend.app.security.checkpoint_keys import (
    CheckpointKeyMaterial,
    CheckpointKeyProvider,
    CheckpointKeyUnavailable,
    EnvCheckpointKeyProvider,
)
from backend.app.security.checkpoint_signers import (
    ECDSA_P256_SHA256,
    ML_DSA_65,
    ECDSAP256Signer,
    MLDSA65Signer,
    pq_runtime_status,
)
from backend.app.security.crypto import canonical_json_bytes
from backend.app.security.key_provider import CRYPTO_PROFILES
from backend.app.settings import Settings


CHECKPOINT_FORMAT_VERSION = "2"


@dataclass(frozen=True)
class CheckpointSignatureBundle:
    classic_signature: bytes
    classic_key: CheckpointKeyMaterial
    pq_signature: bytes | None
    pq_key: CheckpointKeyMaterial | None


@dataclass(frozen=True)
class CheckpointVerification:
    checkpoint_id: str | None
    profile_id: str
    overall: str
    classic_status: str
    pq_status: str
    reason: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def active_profile_id(db: Session) -> str:
    active = db.scalar(
        select(CryptoProfile.profile_id).where(CryptoProfile.status == "ACTIVE")
    )
    return active or "CLASSIC_V1"


def checkpoint_payload(
    *,
    stream_type: str,
    stream_id: str,
    sequence: int,
    root_mac: bytes,
    profile_id: str,
) -> bytes:
    return canonical_json_bytes(
        {
            "format_version": CHECKPOINT_FORMAT_VERSION,
            "stream_type": stream_type,
            "stream_id": stream_id,
            "sequence": sequence,
            "root_mac": base64.b64encode(root_mac).decode("ascii"),
            "crypto_profile_id": profile_id,
        }
    )


def _historical_payload(checkpoint: IntegrityCheckpoint) -> bytes:
    return canonical_json_bytes(
        {
            "stream_id": checkpoint.stream_id,
            "sequence": checkpoint.sequence,
            "root_mac": base64.b64encode(checkpoint.root_mac).decode("ascii"),
            "profile": checkpoint.crypto_profile_id,
        }
    )


def payload_for_checkpoint(checkpoint: IntegrityCheckpoint) -> bytes:
    if checkpoint.format_version in (None, "1"):
        return _historical_payload(checkpoint)
    return checkpoint_payload(
        stream_type=checkpoint.stream_type,
        stream_id=checkpoint.stream_id,
        sequence=checkpoint.sequence,
        root_mac=checkpoint.root_mac,
        profile_id=checkpoint.crypto_profile_id,
    )


def _active_signing_key(
    provider: CheckpointKeyProvider, algorithm_id: str
) -> CheckpointKeyMaterial:
    key = provider.get_active_key(algorithm_id)
    if key.private_key is None:
        raise CheckpointKeyUnavailable(f"private key for {algorithm_id} is unavailable")
    return key


def sign_checkpoint_payload(
    payload: bytes,
    profile_id: str,
    provider: CheckpointKeyProvider,
) -> CheckpointSignatureBundle:
    if profile_id not in CRYPTO_PROFILES:
        raise TraceQError("UNSUPPORTED_CRYPTO_PROFILE", "Crypto profile is unsupported", 422)
    try:
        classic_key = _active_signing_key(provider, ECDSA_P256_SHA256)
        pq_key = (
            _active_signing_key(provider, ML_DSA_65)
            if profile_id == "HYBRID_PQ_V1"
            else None
        )
    except CheckpointKeyUnavailable as exc:
        raise TraceQError("KEY_UNAVAILABLE", str(exc), 503) from exc

    classic_signer = ECDSAP256Signer()
    classic_signature = classic_signer.sign(payload, classic_key.private_key or b"")
    if not classic_signer.verify(payload, classic_signature, classic_key.public_key):
        raise TraceQError("CHECKPOINT_SELF_TEST_FAILED", "ECDSA checkpoint self-test failed", 503)

    pq_signature = None
    if profile_id == "HYBRID_PQ_V1":
        runtime = pq_runtime_status()
        if not runtime["available"]:
            raise TraceQError(
                "PQ_RUNTIME_UNAVAILABLE", "ML-DSA-65 runtime is unavailable", 503
            )
        pq_signer = MLDSA65Signer()
        try:
            pq_signature = pq_signer.sign(payload, (pq_key and pq_key.private_key) or b"")
        except (Exception, SystemExit) as exc:
            raise TraceQError(
                "PQ_SIGNING_FAILED", "ML-DSA-65 checkpoint signing failed", 503
            ) from exc
        if not pq_key or not pq_signer.verify(payload, pq_signature, pq_key.public_key):
            raise TraceQError(
                "CHECKPOINT_SELF_TEST_FAILED", "ML-DSA-65 checkpoint self-test failed", 503
            )
    return CheckpointSignatureBundle(
        classic_signature=classic_signature,
        classic_key=classic_key,
        pq_signature=pq_signature,
        pq_key=pq_key,
    )


def _verification_key(
    provider: CheckpointKeyProvider,
    algorithm_id: str,
    key_id: str | None,
    version: str | None,
) -> CheckpointKeyMaterial:
    return (
        provider.get_key(algorithm_id, key_id, version)
        if key_id
        else provider.get_active_key(algorithm_id)
    )


def verify_checkpoint(
    checkpoint: IntegrityCheckpoint,
    provider: CheckpointKeyProvider,
) -> CheckpointVerification:
    payload = payload_for_checkpoint(checkpoint)
    if checkpoint.payload_hash and hashlib.sha256(payload).hexdigest() != checkpoint.payload_hash:
        return CheckpointVerification(
            str(checkpoint.id) if checkpoint.id else None,
            checkpoint.crypto_profile_id,
            "FAILED",
            "FAILED",
            "FAILED" if checkpoint.crypto_profile_id == "HYBRID_PQ_V1" else "NOT_REQUIRED",
            "PAYLOAD_HASH_MISMATCH",
        )
    try:
        classic_key = _verification_key(
            provider,
            checkpoint.classic_algorithm or ECDSA_P256_SHA256,
            checkpoint.classic_key_id,
            checkpoint.classic_key_version,
        )
        pq_key = (
            _verification_key(
                provider,
                checkpoint.pq_algorithm or ML_DSA_65,
                checkpoint.pq_key_id,
                checkpoint.pq_key_version,
            )
            if checkpoint.crypto_profile_id == "HYBRID_PQ_V1"
            else None
        )
    except CheckpointKeyUnavailable:
        return CheckpointVerification(
            str(checkpoint.id) if checkpoint.id else None,
            checkpoint.crypto_profile_id,
            "UNVERIFIABLE",
            "KEY_UNAVAILABLE",
            "KEY_UNAVAILABLE" if checkpoint.crypto_profile_id == "HYBRID_PQ_V1" else "NOT_REQUIRED",
            "KEY_UNAVAILABLE",
        )

    classic_valid = ECDSAP256Signer().verify(
        payload, checkpoint.classic_signature, classic_key.public_key
    )
    if checkpoint.crypto_profile_id != "HYBRID_PQ_V1":
        return CheckpointVerification(
            str(checkpoint.id) if checkpoint.id else None,
            checkpoint.crypto_profile_id,
            "VERIFIED" if classic_valid else "FAILED",
            "VERIFIED" if classic_valid else "FAILED",
            "NOT_REQUIRED",
            None if classic_valid else "CLASSIC_SIGNATURE_INVALID",
        )

    if checkpoint.pq_signature is None or pq_key is None:
        return CheckpointVerification(
            str(checkpoint.id) if checkpoint.id else None,
            checkpoint.crypto_profile_id,
            "FAILED",
            "VERIFIED" if classic_valid else "FAILED",
            "FAILED",
            "PQ_SIGNATURE_MISSING",
        )
    pq_valid = MLDSA65Signer().verify(payload, checkpoint.pq_signature, pq_key.public_key)
    overall = "VERIFIED" if classic_valid and pq_valid else "FAILED"
    return CheckpointVerification(
        str(checkpoint.id) if checkpoint.id else None,
        checkpoint.crypto_profile_id,
        overall,
        "VERIFIED" if classic_valid else "FAILED",
        "VERIFIED" if pq_valid else "FAILED",
        None if overall == "VERIFIED" else "HYBRID_SIGNATURE_INVALID",
    )


def profile_readiness(
    profile_id: str,
    provider: CheckpointKeyProvider,
) -> dict[str, Any]:
    payload = b"TRACE-Q checkpoint profile activation self-test"
    runtime = pq_runtime_status()
    result: dict[str, Any] = {
        "profile_id": profile_id,
        "classic": {
            "algorithm": ECDSA_P256_SHA256,
            "runtime_available": True,
            "key_available": False,
            "self_test": "NOT_RUN",
            "key_id": None,
            "key_version": None,
        },
        "pq": {
            "algorithm": ML_DSA_65,
            "runtime_available": bool(runtime["available"]),
            "provider": runtime["provider"],
            "provider_version": runtime["provider_version"],
            "native_version": runtime["native_version"],
            "key_available": False,
            "self_test": "NOT_REQUIRED" if profile_id != "HYBRID_PQ_V1" else "NOT_RUN",
            "key_id": None,
            "key_version": None,
        },
        "ready": False,
    }
    try:
        classic_key = _active_signing_key(provider, ECDSA_P256_SHA256)
        result["classic"].update(
            key_available=True,
            key_id=classic_key.key_id,
            key_version=classic_key.version,
        )
        signer = ECDSAP256Signer()
        signature = signer.sign(payload, classic_key.private_key or b"")
        classic_ok = signer.verify(payload, signature, classic_key.public_key)
        result["classic"]["self_test"] = "PASS" if classic_ok else "FAIL"
    except (Exception, SystemExit):
        classic_ok = False
        result["classic"]["self_test"] = "FAIL"

    pq_ok = profile_id != "HYBRID_PQ_V1"
    if profile_id == "HYBRID_PQ_V1" and runtime["available"]:
        try:
            pq_key = _active_signing_key(provider, ML_DSA_65)
            result["pq"].update(
                key_available=True,
                key_id=pq_key.key_id,
                key_version=pq_key.version,
            )
            signer = MLDSA65Signer()
            signature = signer.sign(payload, pq_key.private_key or b"")
            pq_ok = signer.verify(payload, signature, pq_key.public_key)
            result["pq"]["self_test"] = "PASS" if pq_ok else "FAIL"
        except (Exception, SystemExit):
            pq_ok = False
            result["pq"]["self_test"] = "FAIL"
    result["ready"] = bool(classic_ok and pq_ok)
    return result


def require_profile_ready(
    profile_id: str,
    provider: CheckpointKeyProvider,
) -> dict[str, Any]:
    if profile_id not in CRYPTO_PROFILES:
        raise TraceQError("UNSUPPORTED_CRYPTO_PROFILE", "Crypto profile is unsupported", 422)
    readiness = profile_readiness(profile_id, provider)
    if not readiness["ready"]:
        code = (
            "PQ_RUNTIME_UNAVAILABLE"
            if profile_id == "HYBRID_PQ_V1"
            and not readiness["pq"]["runtime_available"]
            else "CRYPTO_PROFILE_NOT_READY"
        )
        raise TraceQError(code, "Crypto profile runtime or keys are not ready", 409)
    return readiness


def create_checkpoint(
    db: Session,
    stream_id: str,
    settings: Settings,
    *,
    provider: CheckpointKeyProvider | None = None,
) -> IntegrityCheckpoint:
    state = db.get(IntegrityStreamState, stream_id)
    if not state:
        raise TraceQError("CHECKPOINT_STREAM_NOT_FOUND", "Integrity stream does not exist", 404)
    profile_id = active_profile_id(db)
    payload = checkpoint_payload(
        stream_type="raw",
        stream_id=stream_id,
        sequence=state.last_seq,
        root_mac=state.last_mac,
        profile_id=profile_id,
    )
    key_provider = provider or EnvCheckpointKeyProvider(settings)
    bundle = sign_checkpoint_payload(payload, profile_id, key_provider)
    checkpoint = IntegrityCheckpoint(
        stream_type="raw",
        stream_id=stream_id,
        sequence=state.last_seq,
        root_mac=state.last_mac,
        crypto_profile_id=profile_id,
        classic_signature=bundle.classic_signature,
        pq_signature=bundle.pq_signature,
        format_version=CHECKPOINT_FORMAT_VERSION,
        classic_key_id=bundle.classic_key.key_id,
        classic_key_version=bundle.classic_key.version,
        classic_algorithm=bundle.classic_key.algorithm_id,
        pq_key_id=bundle.pq_key.key_id if bundle.pq_key else None,
        pq_key_version=bundle.pq_key.version if bundle.pq_key else None,
        pq_algorithm=bundle.pq_key.algorithm_id if bundle.pq_key else None,
        payload_hash=hashlib.sha256(payload).hexdigest(),
    )
    # Persist only after every signature and self-check has succeeded.
    db.add(checkpoint)
    return checkpoint


def create_classic_checkpoint(
    db: Session, stream_id: str, settings: Settings
) -> IntegrityCheckpoint:
    """Backward-compatible entry point; the active profile controls creation."""
    return create_checkpoint(db, stream_id, settings)
