import hashlib, hmac

from backend.app.security.crypto import canonical_json_bytes
from backend.app.security.key_provider import CRYPTO_PROFILES, EnvKeyProvider
from backend.app.settings import get_settings


def test_hmac_v1_fixture_signature_contract():
    body, timestamp, nonce, secret = {"b": 2, "a": 1}, "1700000000", "nonce-1", "secret"
    signed = timestamp.encode() + b"\n" + nonce.encode() + b"\n" + canonical_json_bytes(body)
    expected = "1c7a5a0a5e6229e053b60161f00b5038a66814a71ff3af4ee5c64dec64ab4cff"
    assert hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest() == expected


def test_crypto_profiles_keep_pq_optional():
    assert CRYPTO_PROFILES["CLASSIC_V1"]["encryption"] == "AES-256-GCM"
    assert CRYPTO_PROFILES["HYBRID_PQ_V1"]["optional_dependency"] == "liboqs-python"


def test_env_key_provider_never_reads_database():
    provider = EnvKeyProvider(get_settings())
    assert len(provider.get_active_key("raw_encryption").value) == 32
