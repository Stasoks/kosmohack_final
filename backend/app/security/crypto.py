from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
from datetime import datetime, timezone
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def isoformat_utc(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=lambda item: isoformat_utc(item) if isinstance(item, datetime) else str(item),
    ).encode("utf-8")


def sha256_hex(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def token_hash(token: str) -> str:
    return sha256_hex(token.encode("utf-8"))


def build_aad(
    *, event_id: str, event_type: str, source_id: str, schema_version: str, received_at: datetime,
    occurred_at: datetime | None = None, item_id: str | None = None,
    crypto_key_id: str | None = None, profile: str = "CLASSIC_V1",
) -> bytes:
    value = {
            "event_id": event_id,
            "event_type": event_type,
            "received_at": isoformat_utc(received_at),
            "schema_version": schema_version,
            "source_id": source_id,
    }
    if profile.upper().replace("-", "_") != "CLASSIC_V1":
        value.update({
            "occurred_at": isoformat_utc(occurred_at) if occurred_at else None,
            "item_id": item_id,
            "crypto_key_id": crypto_key_id,
            "crypto_profile": profile,
        })
    return canonical_json_bytes(value)


def encrypt_event(plaintext: bytes, key: bytes, aad: bytes) -> tuple[bytes, bytes]:
    nonce = os.urandom(12)
    return AESGCM(key).encrypt(nonce, plaintext, aad), nonce


def decrypt_event(ciphertext: bytes, nonce: bytes, key: bytes, aad: bytes) -> bytes:
    return AESGCM(key).decrypt(nonce, ciphertext, aad)


def integrity_metadata(
    *,
    event_id: str,
    event_type: str,
    schema_version: str,
    source_id: str,
    occurred_at: datetime,
    received_at: datetime,
    integrity_stream_id: str,
    integrity_seq: int,
) -> bytes:
    return canonical_json_bytes(
        {
            "event_id": event_id,
            "event_type": event_type,
            "integrity_seq": integrity_seq,
            "integrity_stream_id": integrity_stream_id,
            "occurred_at": isoformat_utc(occurred_at),
            "received_at": isoformat_utc(received_at),
            "schema_version": schema_version,
            "source_id": source_id,
        }
    )


def compute_integrity_mac(
    secret: bytes,
    prev_mac: bytes,
    immutable_metadata: bytes,
    ciphertext: bytes,
    nonce: bytes,
    key_id: str,
) -> bytes:
    framed = b"".join(
        (
            len(prev_mac).to_bytes(4, "big"),
            prev_mac,
            len(immutable_metadata).to_bytes(4, "big"),
            immutable_metadata,
            len(ciphertext).to_bytes(8, "big"),
            ciphertext,
            len(nonce).to_bytes(4, "big"),
            nonce,
            key_id.encode("utf-8"),
        )
    )
    return hmac.new(secret, framed, hashlib.sha256).digest()


def constant_time_b64(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")
