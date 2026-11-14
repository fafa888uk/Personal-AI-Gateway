"""Client-key and admin-key auth.

Client keys are stored ONLY as irreversible SHA-256 hex digests.
The admin key (env GATEWAY_ADMIN_KEY) must never double as a client key:
client auth explicitly rejects it, and admin auth never accepts a
client key.

Stage E adds the admin console auth: one AdminAccount whose password is
stored only as an Argon2id hash, plus opaque AdminSession tokens stored
only as SHA-256 digests. Plaintext passwords, session tokens and raw
client keys are never logged or stored.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

from .models import ClientKey

KEY_PREFIX = "pag_sk_"

_admin_hasher = PasswordHasher()  # defaults: Argon2id, the current OWASP recommendation


def hash_admin_password(plaintext: str) -> str:
    return _admin_hasher.hash(plaintext)


def verify_admin_password(plaintext: str, stored_hash: str) -> bool:
    try:
        return _admin_hasher.verify(stored_hash, plaintext)
    except (VerifyMismatchError, Exception):
        return False


def generate_session_token() -> str:
    return secrets.token_urlsafe(32)


def hash_session_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def generate_csrf_token() -> str:
    return secrets.token_urlsafe(32)


def generate_client_key() -> str:
    return KEY_PREFIX + secrets.token_urlsafe(32)


def hash_client_key(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def verify_client_key(raw: str, stored_hash: str) -> bool:
    return hmac.compare_digest(hash_client_key(raw), stored_hash)


def verify_admin_key(raw: str, admin_key: str) -> bool:
    if not admin_key:
        return False
    return hmac.compare_digest(raw, admin_key)


def client_may_call_model(client: ClientKey, canonical_name: str) -> bool:
    allowed = client.allowed_models or []
    if "*" in allowed:
        return True
    return canonical_name in allowed
