"""
DSA utility service for attendance signing and verification.

Educational note:
- DSA in this project is used for digital signatures (sign + verify),
  not for encryption/decryption.
- The backend signs attendance payloads with a private key.
- Anyone with the public key can verify whether a stored record was altered.

This module intentionally keeps all signature operations on the backend.
The private key never leaves the server.
"""

from __future__ import annotations

import base64
from functools import lru_cache

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured


@lru_cache(maxsize=1)
def _load_private_key():
    """
    Load and cache the DSA private key from settings/env-backed value.

    The key content is expected in PEM format (multiline string).
    """
    # Read private key from environment-backed Django settings.
    private_key_pem = getattr(settings, "DSA_PRIVATE_KEY", "")
    if not private_key_pem:
        raise ImproperlyConfigured("DSA_PRIVATE_KEY is not configured.")
    try:
        return serialization.load_pem_private_key(private_key_pem.encode("utf-8"), password=None)
    except (TypeError, ValueError) as exc:
        raise ImproperlyConfigured("DSA_PRIVATE_KEY is not valid PEM content.") from exc


@lru_cache(maxsize=1)
def _load_public_key():
    """
    Load and cache the DSA public key from settings/env-backed value.

    The key content is expected in PEM format (multiline string).
    """
    # Read public key from environment-backed Django settings.
    public_key_pem = getattr(settings, "DSA_PUBLIC_KEY", "")
    if not public_key_pem:
        raise ImproperlyConfigured("DSA_PUBLIC_KEY is not configured.")
    try:
        return serialization.load_pem_public_key(public_key_pem.encode("utf-8"))
    except (TypeError, ValueError) as exc:
        raise ImproperlyConfigured("DSA_PUBLIC_KEY is not valid PEM content.") from exc


def build_attendance_payload(*, user, session, attendance_type, timestamp):
    """
    Build a deterministic payload string for audit readability.

    Important: the payload format and field order must stay consistent.
    Signature verification depends on byte-for-byte equality.
    Even a one-character change should make verification fail.

    Required fields:
    - user_id
    - email
    - full_name
    - session_id
    - attendance_type
    - timestamp
    """
    # Build one canonical text block that is later signed and audited.
    full_name = f"{user.first_name} {user.last_name}".strip()

    # Keep line order stable so the same logical data always yields the same payload text.
    payload_lines = [
        f"user_id={user.id}",
        f"email={user.email}",
        f"full_name={full_name}",
        f"session_id={session.id}",
        f"attendance_type={attendance_type}",
        f"timestamp={timestamp.isoformat()}",
    ]
    return "\n".join(payload_lines)


def sign_payload(payload: str) -> str:
    """
    Sign payload bytes using the backend DSA private key.

    The resulting signature proves:
    - authenticity: it was signed by the holder of the private key
    - integrity: payload changes after signing will invalidate verification

    Signature bytes are base64-encoded for JSON/database storage.
    """
    # DSA signing happens only on the backend using the private key.
    private_key = _load_private_key()
    signature_bytes = private_key.sign(payload.encode("utf-8"), hashes.SHA256())
    return base64.b64encode(signature_bytes).decode("utf-8")


def verify_payload_signature(payload: str, signature_base64: str) -> bool:
    """
    Verify a payload/signature pair using the DSA public key.

    Returns:
    - True: signature matches payload (record has not been tampered with)
    - False: signature is invalid or malformed for this payload
    """
    # Verification uses the public key; this is what detects tampering.
    public_key = _load_public_key()
    try:
        signature_bytes = base64.b64decode(signature_base64.encode("utf-8"))
        public_key.verify(signature_bytes, payload.encode("utf-8"), hashes.SHA256())
        return True
    except (InvalidSignature, ValueError):
        return False
