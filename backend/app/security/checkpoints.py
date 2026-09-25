from __future__ import annotations

import base64

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from sqlalchemy.orm import Session

from backend.app.errors import TraceQError
from backend.app.persistence.models import IntegrityCheckpoint, IntegrityStreamState
from backend.app.security.crypto import canonical_json_bytes
from backend.app.settings import Settings


def create_classic_checkpoint(db: Session, stream_id: str, settings: Settings) -> IntegrityCheckpoint:
    state = db.get(IntegrityStreamState, stream_id)
    if not state:
        raise TraceQError("CHECKPOINT_STREAM_NOT_FOUND", "Integrity stream does not exist", 404)
    if not settings.checkpoint_private_key_pem_b64:
        raise TraceQError("KEY_UNAVAILABLE", "Checkpoint signing key is unavailable", 503)
    pem = base64.b64decode(settings.checkpoint_private_key_pem_b64.get_secret_value())
    private_key = serialization.load_pem_private_key(pem, password=None)
    if not isinstance(private_key, ec.EllipticCurvePrivateKey) or not isinstance(private_key.curve, ec.SECP256R1):
        raise TraceQError("UNSUPPORTED_CRYPTO_PROFILE", "Checkpoint key must be ECDSA P-256", 422)
    payload = canonical_json_bytes({"stream_id": stream_id, "sequence": state.last_seq,
                                    "root_mac": base64.b64encode(state.last_mac).decode(),
                                    "profile": "CLASSIC_V1"})
    signature = private_key.sign(payload, ec.ECDSA(hashes.SHA256()))
    checkpoint = IntegrityCheckpoint(stream_type="raw", stream_id=stream_id,
        sequence=state.last_seq, root_mac=state.last_mac, crypto_profile_id="CLASSIC_V1",
        classic_signature=signature, pq_signature=None)
    db.add(checkpoint)
    return checkpoint
