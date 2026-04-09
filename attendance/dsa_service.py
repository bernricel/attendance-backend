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
import os
from functools import lru_cache
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import dsa
from django.conf import settings


def _get_private_key_path() -> Path:
    """Resolve the private key location from settings, then fallback path."""
    configured_path = getattr(settings, "DSA_PRIVATE_KEY_PATH", "")
    if configured_path:
        return Path(configured_path)
    return settings.BASE_DIR / "secure_keys" / "attendance_dsa_private.pem"


def _get_public_key_path() -> Path:
    """Resolve the public key location from settings, then fallback path."""
    configured_path = getattr(settings, "DSA_PUBLIC_KEY_PATH", "")
    if configured_path:
        return Path(configured_path)
    return settings.BASE_DIR / "secure_keys" / "attendance_dsa_public.pem"


def ensure_dsa_key_pair():
    """
    Create a DSA keypair if it does not exist yet.

    - Private key: used only for signing on the server and must remain secret.
    - Public key: shared/used for verification and can be exposed safely.

    Keys are generated once and stored on disk. Future calls reuse existing keys,
    which keeps verification consistent across server restarts.
    """
    private_key_path = _get_private_key_path()
    public_key_path = _get_public_key_path()
    private_key_path.parent.mkdir(parents=True, exist_ok=True)

    if private_key_path.exists() and public_key_path.exists():
        return

    # Generate a new DSA private key (2048-bit), then derive its public key.
    private_key = dsa.generate_private_key(key_size=2048)
    public_key = private_key.public_key()

    # Store keys in PEM text format for easy loading in later requests.
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        # No passphrase is used here because key access is controlled by server/file permissions.
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_pem = public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )

    private_key_path.write_bytes(private_pem)
    public_key_path.write_bytes(public_pem)

    # Best-effort lock-down for private key file permissions.
    try:
        os.chmod(private_key_path, 0o600)
    except OSError:
        pass


@lru_cache(maxsize=1)
def _load_private_key():
    """Load and cache the private key to avoid disk I/O on every signature call."""
    ensure_dsa_key_pair()
    private_key_bytes = _get_private_key_path().read_bytes()
    return serialization.load_pem_private_key(private_key_bytes, password=None)


@lru_cache(maxsize=1)
def _load_public_key():
    """Load and cache the public key for fast repeated verification."""
    ensure_dsa_key_pair()
    public_key_bytes = _get_public_key_path().read_bytes()
    return serialization.load_pem_public_key(public_key_bytes)


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
    public_key = _load_public_key()
    try:
        signature_bytes = base64.b64decode(signature_base64.encode("utf-8"))
        public_key.verify(signature_bytes, payload.encode("utf-8"), hashes.SHA256())
        return True
    except (InvalidSignature, ValueError):
        return False
