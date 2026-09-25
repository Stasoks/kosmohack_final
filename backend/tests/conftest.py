from __future__ import annotations

import os


os.environ.setdefault("JWT_SIGNING_SECRET", "unit-test-jwt-signing-secret-with-32-characters")
os.environ.setdefault("AES_DATA_KEY_B64", "ZGVtby10cmFjZXEtYWVzLTI1Ni1rZXktMzJieXRlcyE=")
os.environ.setdefault("INTEGRITY_HMAC_KEY_B64", "ZGVtby10cmFjZXEtaG1hYy1rZXktMzJieXRlcyEhISE=")
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://unused:unused@localhost:1/unused")
os.environ.setdefault("DEMO_MODE", "false")
