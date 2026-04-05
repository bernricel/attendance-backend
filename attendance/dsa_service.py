"""
DSA utility service for attendance signing and verification.

This module intentionally keeps all cryptographic operations on the backend.
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
    configured_path = getattr(settings, "DSA_PRIVATE_KEY_PATH", "")
    if configured_path:
        return Path(configured_path)
    return settings.BASE_DIR / "secure_keys" / "attendance_dsa_private.pem"


def _get_public_key_path() -> Path:
    configured_path = getattr(settings, "DSA_PUBLIC_KEY_PATH", "")
    if configured_path:
        return Path(configured_path)
    return settings.BASE_DIR / "secure_keys" / "attendance_dsa_public.pem"


def ensure_dsa_key_pair():
    """
    Create a DSA keypair if it does not exist yet.

    - Private key: used only for signing on the server.
    - Public key: used for signature verification.
    """
    private_key_path = _get_private_key_path()
    public_key_path = _get_public_key_path()
    private_key_path.parent.mkdir(parents=True, exist_ok=True)

    if private_key_path.exists() and public_key_path.exists():
        return

    private_key = dsa.generate_private_key(key_size=2048)
    public_key = private_key.public_key()

    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
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
    ensure_dsa_key_pair()
    private_key_bytes = _get_private_key_path().read_bytes()
    return serialization.load_pem_private_key(private_key_bytes, password=None)


@lru_cache(maxsize=1)
def _load_public_key():
    ensure_dsa_key_pair()
    public_key_bytes = _get_public_key_path().read_bytes()
    return serialization.load_pem_public_key(public_key_bytes)


def build_attendance_payload(*, user, session, attendance_type, timestamp):
    """
    Build a deterministic payload string for academic/audit readability.

    Required fields:
    - user_id
    - email
    - full_name
    - department
    - session_id
    - attendance_type
    - timestamp
    """
    full_name = f"{user.first_name} {user.last_name}".strip()

    payload_lines = [
        f"user_id={user.id}",
        f"email={user.email}",
        f"full_name={full_name}",
        f"department={session.department.name}",
        f"session_id={session.id}",
        f"attendance_type={attendance_type}",
        f"timestamp={timestamp.isoformat()}",
    ]
    return "\n".join(payload_lines)


def sign_payload(payload: str) -> str:
    """
    Sign the payload with the backend DSA private key.
    Return a base64 string so it is safe to store and transmit in JSON.
    """
    private_key = _load_private_key()
    signature_bytes = private_key.sign(payload.encode("utf-8"), hashes.SHA256())
    return base64.b64encode(signature_bytes).decode("utf-8")


def verify_payload_signature(payload: str, signature_base64: str) -> bool:
    """
    Verify a payload/signature pair using the DSA public key.
    Returns True for valid signatures and False for invalid signatures.
    """
    public_key = _load_public_key()
    try:
        signature_bytes = base64.b64decode(signature_base64.encode("utf-8"))
        public_key.verify(signature_bytes, payload.encode("utf-8"), hashes.SHA256())
        return True
    except (InvalidSignature, ValueError):
        return False
