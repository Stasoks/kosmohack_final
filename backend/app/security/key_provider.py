from __future__ import annotations

import base64
from dataclasses import dataclass
from typing import Protocol

from backend.app.errors import TraceQError
from backend.app.settings import Settings


@dataclass(frozen=True)
class KeyMaterial:
    key_id: str
    value: bytes


class KeyProvider(Protocol):
    def get_active_key(self, purpose: str) -> KeyMaterial: ...
    def get_key(self, key_id: str) -> KeyMaterial: ...
    def rotate(self, purpose: str) -> KeyMaterial: ...


class EnvKeyProvider:
    """Baseline provider. Rotation means deploying a new env-backed key and key id."""
    def __init__(self, settings: Settings):
        self.settings = settings

    def get_active_key(self, purpose: str) -> KeyMaterial:
        if purpose == "raw_encryption":
            return KeyMaterial(self.settings.aes_key_id, self.settings.aes_key())
        if purpose in {"raw_integrity", "audit_integrity"}:
            return KeyMaterial(self.settings.integrity_key_id, self.settings.integrity_key())
        raise TraceQError("KEY_UNAVAILABLE", "Requested key purpose is unavailable", 503)

    def get_key(self, key_id: str) -> KeyMaterial:
        for purpose in ("raw_encryption", "raw_integrity"):
            material = self.get_active_key(purpose)
            if material.key_id == key_id:
                return material
        raise TraceQError("KEY_UNAVAILABLE", "Requested key ID is unavailable", 503)

    def rotate(self, purpose: str) -> KeyMaterial:
        raise TraceQError("EXTERNAL_ROTATION_REQUIRED", "Rotate the environment secret and deploy a new key ID", 409)


CRYPTO_PROFILES = {
    "CLASSIC_V1": {"encryption": "AES-256-GCM", "integrity": "HMAC-SHA256", "checkpoint": "ECDSA-P256"},
    "HYBRID_PQ_V1": {"encryption": "AES-256-GCM", "integrity": "HMAC-SHA256", "checkpoint": "ECDSA-P256+ML-DSA-65", "optional_dependency": "liboqs-python"},
}
