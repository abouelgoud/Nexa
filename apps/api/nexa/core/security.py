"""Passwords, JWT tokens and symmetric encryption for secrets."""

import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import bcrypt
from cryptography.fernet import Fernet, InvalidToken
from jose import JWTError, jwt

from nexa.core.config import get_settings


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), password_hash.encode())
    except ValueError:
        return False


def create_access_token(user_id: UUID, extra: dict[str, Any] | None = None) -> str:
    s = get_settings()
    now = datetime.now(UTC)
    payload = {"sub": str(user_id), "iat": now, "exp": now + timedelta(minutes=s.jwt_expires_minutes), "typ": "access"}
    payload.update(extra or {})
    return jwt.encode(payload, s.jwt_secret, algorithm=s.jwt_algorithm)


def decode_access_token(token: str) -> UUID | None:
    s = get_settings()
    try:
        payload = jwt.decode(token, s.jwt_secret, algorithms=[s.jwt_algorithm])
    except JWTError:
        return None
    if payload.get("typ") != "access":
        return None
    try:
        return UUID(payload["sub"])
    except (KeyError, ValueError):
        return None


def _fernet() -> Fernet:
    return Fernet(get_settings().encryption_key.encode())


def encrypt_json(data: dict[str, Any]) -> bytes:
    return _fernet().encrypt(json.dumps(data).encode())


def decrypt_json(token: bytes) -> dict[str, Any]:
    try:
        return json.loads(_fernet().decrypt(token))
    except InvalidToken as exc:  # pragma: no cover - key rotation issue
        raise ValueError("Unable to decrypt credentials (wrong ENCRYPTION_KEY?)") from exc


SENSITIVE_KEYS = {"password", "token", "api_key", "apikey", "secret", "authorization", "dsn", "access_token"}


def redact(value: Any) -> Any:
    """Recursively mask values whose key looks sensitive (for logs/audit)."""
    if isinstance(value, dict):
        return {k: ("***" if k.lower() in SENSITIVE_KEYS else redact(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v) for v in value]
    return value
