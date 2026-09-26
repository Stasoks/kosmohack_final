from __future__ import annotations

import hashlib

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from backend.app.errors import TraceQError
from backend.app.persistence.models import IntegrityCheckpoint
from backend.app.security.checkpoint_keys import (
    CheckpointKeyMaterial,
    MemoryCheckpointKeyProvider,
)
from backend.app.security.checkpoint_signers import (
    ECDSA_P256_SHA256,
    ML_DSA_65,
    ECDSAP256Signer,
)
from backend.app.security.checkpoints import (
    CHECKPOINT_FORMAT_VERSION,
    checkpoint_payload,
    require_profile_ready,
    sign_checkpoint_payload,
    verify_checkpoint,
)


def _classic_key(key_id: str, version: str = "1") -> CheckpointKeyMaterial:
    private = ec.generate_private_key(ec.SECP256R1())
    private_bytes = private.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    public_bytes = private.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return CheckpointKeyMaterial(
        key_id=key_id,
        version=version,
        algorithm_id=ECDSA_P256_SHA256,
        private_key=private_bytes,
        public_key=public_bytes,
    )


def _provider(*keys: CheckpointKeyMaterial, active: dict[str, str] | None = None):
    return MemoryCheckpointKeyProvider(
        list(keys),
        active
        or {
            key.algorithm_id: key.key_id
            for key in keys
        },
    )


def _checkpoint(
    profile: str,
    payload: bytes,
    bundle,
) -> IntegrityCheckpoint:
    return IntegrityCheckpoint(
        stream_type="raw",
        stream_id="source:TEST",
        sequence=7,
        root_mac=b"root-mac",
        crypto_profile_id=profile,
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


def _payload(profile: str) -> bytes:
    return checkpoint_payload(
        stream_type="raw",
        stream_id="source:TEST",
        sequence=7,
        root_mac=b"root-mac",
        profile_id=profile,
    )


def test_classic_checkpoint_signer_roundtrip_and_tamper() -> None:
    key = _classic_key("classic-v1")
    payload = _payload("CLASSIC_V1")
    signer = ECDSAP256Signer()
    signature = signer.sign(payload, key.private_key or b"")

    assert signer.verify(payload, signature, key.public_key)
    assert not signer.verify(payload + b"tamper", signature, key.public_key)


def test_classic_checkpoint_rotation_verifies_old_key_and_reports_missing_key() -> None:
    old = _classic_key("classic-v1", "1")
    new = _classic_key("classic-v2", "2")
    signing_provider = _provider(old)
    payload = _payload("CLASSIC_V1")
    row = _checkpoint(
        "CLASSIC_V1",
        payload,
        sign_checkpoint_payload(payload, "CLASSIC_V1", signing_provider),
    )
    rotated = _provider(
        old,
        new,
        active={ECDSA_P256_SHA256: new.key_id},
    )

    assert verify_checkpoint(row, rotated).overall == "VERIFIED"
    assert verify_checkpoint(row, _provider(new)).overall == "UNVERIFIABLE"


def test_hybrid_never_falls_back_when_pq_key_is_missing() -> None:
    classic = _classic_key("classic-v1")

    with pytest.raises(TraceQError) as raised:
        sign_checkpoint_payload(
            _payload("HYBRID_PQ_V1"), "HYBRID_PQ_V1", _provider(classic)
        )

    assert raised.value.code == "KEY_UNAVAILABLE"


def test_hybrid_activation_is_rejected_when_runtime_is_unavailable(monkeypatch) -> None:
    from backend.app.security import checkpoints

    classic = _classic_key("classic-v1")
    monkeypatch.setattr(
        checkpoints,
        "pq_runtime_status",
        lambda: {
            "available": False,
            "provider": "liboqs-python",
            "provider_version": "",
            "native_version": "",
        },
    )

    with pytest.raises(TraceQError) as raised:
        require_profile_ready("HYBRID_PQ_V1", _provider(classic))

    assert raised.value.code == "PQ_RUNTIME_UNAVAILABLE"


@pytest.fixture(scope="module")
def pq_key() -> CheckpointKeyMaterial:
    oqs = pytest.importorskip("oqs")
    if ML_DSA_65 not in oqs.get_enabled_sig_mechanisms():
        pytest.skip("ML-DSA-65 is not enabled")
    with oqs.Signature(ML_DSA_65) as generator:
        public_key = generator.generate_keypair()
        private_key = generator.export_secret_key()
    return CheckpointKeyMaterial(
        key_id="pq-v1",
        version="1",
        algorithm_id=ML_DSA_65,
        private_key=private_key,
        public_key=public_key,
    )


@pytest.mark.pq
def test_real_mldsa65_both_signatures_are_required(
    pq_key: CheckpointKeyMaterial,
) -> None:
    classic = _classic_key("classic-v1")
    provider = _provider(classic, pq_key)
    payload = _payload("HYBRID_PQ_V1")
    bundle = sign_checkpoint_payload(payload, "HYBRID_PQ_V1", provider)
    row = _checkpoint("HYBRID_PQ_V1", payload, bundle)

    assert bundle.pq_signature is not None
    assert verify_checkpoint(row, provider).overall == "VERIFIED"

    original_pq = row.pq_signature
    row.pq_signature = bytes([original_pq[0] ^ 1]) + original_pq[1:]
    assert verify_checkpoint(row, provider).overall == "FAILED"
    row.pq_signature = original_pq

    original_classic = row.classic_signature
    row.classic_signature = bytes([original_classic[0] ^ 1]) + original_classic[1:]
    result = verify_checkpoint(row, provider)
    assert result.overall == "FAILED"
    assert result.pq_status == "VERIFIED"


@pytest.mark.pq
def test_mldsa65_rotation_keeps_old_checkpoint_verifiable(
    pq_key: CheckpointKeyMaterial,
) -> None:
    oqs = pytest.importorskip("oqs")
    with oqs.Signature(ML_DSA_65) as generator:
        new_public = generator.generate_keypair()
        new_private = generator.export_secret_key()
    new_pq = CheckpointKeyMaterial(
        key_id="pq-v2",
        version="2",
        algorithm_id=ML_DSA_65,
        private_key=new_private,
        public_key=new_public,
    )
    classic = _classic_key("classic-v1")
    payload = _payload("HYBRID_PQ_V1")
    row = _checkpoint(
        "HYBRID_PQ_V1",
        payload,
        sign_checkpoint_payload(
            payload, "HYBRID_PQ_V1", _provider(classic, pq_key)
        ),
    )
    rotated = _provider(
        classic,
        pq_key,
        new_pq,
        active={ECDSA_P256_SHA256: classic.key_id, ML_DSA_65: new_pq.key_id},
    )

    assert verify_checkpoint(row, rotated).overall == "VERIFIED"
    assert verify_checkpoint(row, _provider(classic, new_pq)).overall == "UNVERIFIABLE"
