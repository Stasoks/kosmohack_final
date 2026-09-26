from __future__ import annotations

import importlib
from typing import Protocol

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec


ECDSA_P256_SHA256 = "ECDSA-P256-SHA256"
ML_DSA_65 = "ML-DSA-65"


class CheckpointSigner(Protocol):
    algorithm_id: str

    def sign(self, payload: bytes, private_key: bytes) -> bytes: ...

    def verify(
        self, payload: bytes, signature: bytes, public_key: bytes
    ) -> bool: ...


class ECDSAP256Signer:
    algorithm_id = ECDSA_P256_SHA256

    def sign(self, payload: bytes, private_key: bytes) -> bytes:
        key = serialization.load_pem_private_key(private_key, password=None)
        if not isinstance(key, ec.EllipticCurvePrivateKey) or not isinstance(
            key.curve, ec.SECP256R1
        ):
            raise ValueError("checkpoint key must be an ECDSA P-256 private key")
        return key.sign(payload, ec.ECDSA(hashes.SHA256()))

    def verify(self, payload: bytes, signature: bytes, public_key: bytes) -> bool:
        try:
            key = serialization.load_pem_public_key(public_key)
            if not isinstance(key, ec.EllipticCurvePublicKey) or not isinstance(
                key.curve, ec.SECP256R1
            ):
                return False
            key.verify(signature, payload, ec.ECDSA(hashes.SHA256()))
            return True
        except (ValueError, TypeError, InvalidSignature):
            return False


def load_oqs():
    """Load the optional native provider only when PQ functionality is requested."""
    return importlib.import_module("oqs")


def pq_runtime_status() -> dict[str, str | bool]:
    try:
        oqs = load_oqs()
        enabled = oqs.get_enabled_sig_mechanisms()
        available = ML_DSA_65 in enabled
        return {
            "available": available,
            "provider": "liboqs-python",
            "provider_version": str(oqs.oqs_python_version()),
            "native_version": str(oqs.oqs_version()),
            "algorithm": ML_DSA_65,
            "error": "" if available else "ML-DSA-65 is not enabled",
        }
    except (Exception, SystemExit) as exc:
        return {
            "available": False,
            "provider": "liboqs-python",
            "provider_version": "",
            "native_version": "",
            "algorithm": ML_DSA_65,
            "error": type(exc).__name__,
        }


class MLDSA65Signer:
    algorithm_id = ML_DSA_65

    def sign(self, payload: bytes, private_key: bytes) -> bytes:
        oqs = load_oqs()
        if ML_DSA_65 not in oqs.get_enabled_sig_mechanisms():
            raise RuntimeError("ML-DSA-65 is not enabled by the PQ runtime")
        with oqs.Signature(ML_DSA_65, private_key) as signer:
            return signer.sign(payload)

    def verify(self, payload: bytes, signature: bytes, public_key: bytes) -> bool:
        try:
            oqs = load_oqs()
            if ML_DSA_65 not in oqs.get_enabled_sig_mechanisms():
                return False
            with oqs.Signature(ML_DSA_65) as verifier:
                return bool(verifier.verify(payload, signature, public_key))
        except (Exception, SystemExit):
            return False
