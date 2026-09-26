from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from typing import Protocol

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from backend.app.security.checkpoint_signers import ECDSA_P256_SHA256, ML_DSA_65
from backend.app.settings import Settings


class CheckpointKeyUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class CheckpointKeyMaterial:
    key_id: str
    version: str
    algorithm_id: str
    private_key: bytes | None
    public_key: bytes


class CheckpointKeyProvider(Protocol):
    def get_active_key(self, algorithm_id: str) -> CheckpointKeyMaterial: ...

    def get_key(
        self, algorithm_id: str, key_id: str, version: str | None = None
    ) -> CheckpointKeyMaterial: ...


class MemoryCheckpointKeyProvider:
    def __init__(
        self,
        keys: list[CheckpointKeyMaterial],
        active: dict[str, str],
    ) -> None:
        self._keys = {(key.algorithm_id, key.key_id): key for key in keys}
        self._active = dict(active)

    def get_active_key(self, algorithm_id: str) -> CheckpointKeyMaterial:
        key_id = self._active.get(algorithm_id)
        if not key_id:
            raise CheckpointKeyUnavailable(f"no active key for {algorithm_id}")
        return self.get_key(algorithm_id, key_id)

    def get_key(
        self, algorithm_id: str, key_id: str, version: str | None = None
    ) -> CheckpointKeyMaterial:
        key = self._keys.get((algorithm_id, key_id))
        if key is None or (version is not None and key.version != version):
            raise CheckpointKeyUnavailable(f"checkpoint key {key_id} is unavailable")
        return key


def _decode(value: str, field: str) -> bytes:
    try:
        return base64.b64decode(value, validate=True)
    except Exception as exc:
        raise CheckpointKeyUnavailable(f"invalid base64 in {field}") from exc


def _public_from_classic_private(private_key: bytes) -> bytes:
    key = serialization.load_pem_private_key(private_key, password=None)
    if not isinstance(key, ec.EllipticCurvePrivateKey) or not isinstance(
        key.curve, ec.SECP256R1
    ):
        raise CheckpointKeyUnavailable("classic checkpoint key is not ECDSA P-256")
    return key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )


def _parse_keyring(raw: str, algorithm_id: str) -> tuple[list[CheckpointKeyMaterial], str]:
    try:
        value = json.loads(raw)
        active = str(value["active_key_id"])
        rows = value["keys"]
        if not isinstance(rows, dict) or active not in rows:
            raise ValueError("active key is missing")
    except (TypeError, ValueError, KeyError, json.JSONDecodeError) as exc:
        raise CheckpointKeyUnavailable("checkpoint keyring JSON is invalid") from exc

    keys: list[CheckpointKeyMaterial] = []
    for key_id, row in rows.items():
        if not isinstance(row, dict):
            raise CheckpointKeyUnavailable("checkpoint keyring entry is invalid")
        private = (
            _decode(str(row["private_key_b64"]), "private_key_b64")
            if row.get("private_key_b64")
            else None
        )
        if row.get("public_key_b64"):
            public = _decode(str(row["public_key_b64"]), "public_key_b64")
        elif algorithm_id == ECDSA_P256_SHA256 and private is not None:
            public = _public_from_classic_private(private)
        else:
            raise CheckpointKeyUnavailable("checkpoint public key is unavailable")
        keys.append(
            CheckpointKeyMaterial(
                key_id=str(key_id),
                version=str(row.get("version", "1")),
                algorithm_id=algorithm_id,
                private_key=private,
                public_key=public,
            )
        )
    return keys, active


class EnvCheckpointKeyProvider(MemoryCheckpointKeyProvider):
    def __init__(self, settings: Settings) -> None:
        keys: list[CheckpointKeyMaterial] = []
        active: dict[str, str] = {}
        if settings.checkpoint_classic_keys_json:
            classic, classic_active = _parse_keyring(
                settings.checkpoint_classic_keys_json.get_secret_value(),
                ECDSA_P256_SHA256,
            )
            keys.extend(classic)
            active[ECDSA_P256_SHA256] = classic_active
        elif settings.checkpoint_private_key_pem_b64:
            private = _decode(
                settings.checkpoint_private_key_pem_b64.get_secret_value(),
                "CHECKPOINT_PRIVATE_KEY_PEM_B64",
            )
            keys.append(
                CheckpointKeyMaterial(
                    key_id="legacy-classic-v1",
                    version="1",
                    algorithm_id=ECDSA_P256_SHA256,
                    private_key=private,
                    public_key=_public_from_classic_private(private),
                )
            )
            active[ECDSA_P256_SHA256] = "legacy-classic-v1"
        if settings.checkpoint_pq_keys_json:
            pq, pq_active = _parse_keyring(
                settings.checkpoint_pq_keys_json.get_secret_value(), ML_DSA_65
            )
            keys.extend(pq)
            active[ML_DSA_65] = pq_active
        super().__init__(keys, active)
