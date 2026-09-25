from __future__ import annotations

from datetime import datetime, timezone

import pytest
from cryptography.exceptions import InvalidTag

from backend.app.security.crypto import (
    build_aad,
    canonical_json_bytes,
    compute_integrity_mac,
    decrypt_event,
    encrypt_event,
    integrity_metadata,
)
from backend.app.security.passwords import hash_password, verify_password
from backend.app.security.permissions import ROLE_PERMISSIONS


KEY = b"0123456789abcdef0123456789abcdef"
NOW = datetime(2026, 9, 25, 10, 0, tzinfo=timezone.utc)


def test_argon2_password_hash_is_not_plaintext() -> None:
    encoded = hash_password("safe-test-password")
    assert "safe-test-password" not in encoded
    assert encoded.startswith("$argon2id$")
    assert verify_password(encoded, "safe-test-password")
    assert not verify_password(encoded, "wrong")


def test_aes_gcm_roundtrip_and_tamper_failure() -> None:
    aad = build_aad(
        event_id="E1", event_type="item.registered", source_id="S1", schema_version="1.0", received_at=NOW
    )
    ciphertext, nonce = encrypt_event(b"secret raw event", KEY, aad)
    assert b"secret raw event" not in ciphertext
    assert decrypt_event(ciphertext, nonce, KEY, aad) == b"secret raw event"
    altered = bytes([ciphertext[0] ^ 1]) + ciphertext[1:]
    with pytest.raises(InvalidTag):
        decrypt_event(altered, nonce, KEY, aad)


def test_integrity_mac_changes_with_ciphertext() -> None:
    metadata = integrity_metadata(
        event_id="E1",
        event_type="item.registered",
        schema_version="1.0",
        source_id="S1",
        occurred_at=NOW,
        received_at=NOW,
        integrity_stream_id="source:S1",
        integrity_seq=1,
    )
    left = compute_integrity_mac(KEY, b"", metadata, b"cipher-a", b"123456789012", "k1")
    right = compute_integrity_mac(KEY, b"", metadata, b"cipher-b", b"123456789012", "k1")
    assert left != right


def test_permission_separation_of_duties() -> None:
    assert "ISSUE_QC_DECISION" in ROLE_PERMISSIONS["controller"]
    assert "ISSUE_QC_DECISION" not in ROLE_PERMISSIONS["admin"]
    assert "ISSUE_QC_DECISION" not in ROLE_PERMISSIONS["technologist"]
    assert "APPROVE_CONTAINMENT" in ROLE_PERMISSIONS["controller"]
    assert "APPROVE_CONTAINMENT" not in ROLE_PERMISSIONS["technologist"]
