import base64
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import os
import secrets
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
import jwt

from app.core.config import Settings, get_settings


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    iterations = 260_000
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), iterations)
    return f"pbkdf2_sha256${iterations}${salt}${dk.hex()}"


def verify_password(plain_password: str, password_hash: str) -> bool:
    try:
        scheme, iter_str, salt, digest_hex = password_hash.split("$", 3)
        if scheme != "pbkdf2_sha256":
            return False
        iterations = int(iter_str)
        dk = hashlib.pbkdf2_hmac(
            "sha256",
            plain_password.encode("utf-8"),
            salt.encode("utf-8"),
            iterations,
        )
        return hmac.compare_digest(dk.hex(), digest_hex)
    except Exception:
        return False


def create_access_token(
    subject: str,
    settings: Settings | None = None,
    expires_delta: timedelta | None = None,
    extra_claims: dict[str, Any] | None = None,
) -> str:
    cfg = settings or get_settings()
    if not cfg.JWT_SECRET_KEY:
        raise RuntimeError("JWT_SECRET_KEY doit être défini dans .env")
    now = datetime.now(timezone.utc)
    expire = now + (expires_delta or timedelta(minutes=cfg.ACCESS_TOKEN_EXPIRE_MINUTES))
    payload: dict[str, Any] = {"sub": subject, "iat": now, "exp": expire}
    if extra_claims:
        payload.update(extra_claims)
    return jwt.encode(payload, cfg.JWT_SECRET_KEY, algorithm=cfg.JWT_ALGORITHM)


def decode_access_token(token: str, settings: Settings | None = None) -> dict[str, Any]:
    cfg = settings or get_settings()
    if not cfg.JWT_SECRET_KEY:
        raise RuntimeError("JWT_SECRET_KEY doit être défini dans .env")
    return jwt.decode(token, cfg.JWT_SECRET_KEY, algorithms=[cfg.JWT_ALGORITHM])


class EnvelopeCipher:
    """Chiffrement enveloppe AES-256-GCM pour le coffre-fort de documents de voyage."""

    def __init__(self, settings: Settings | None = None) -> None:
        cfg = settings or get_settings()
        if not cfg.VAULT_MASTER_KEY:
            raise RuntimeError("VAULT_MASTER_KEY doit être défini dans .env")
        raw_kek = base64.b64decode(cfg.VAULT_MASTER_KEY)
        if len(raw_kek) != 32:
            raw_kek = hashlib.sha256(cfg.VAULT_MASTER_KEY.encode("utf-8")).digest()
        self._kek = AESGCM(raw_kek)

    def encrypt_document(self, plaintext: bytes) -> dict[str, bytes | str]:
        dek = AESGCM.generate_key(bit_length=256)
        data_iv = os.urandom(12)
        kek_iv = os.urandom(12)
        ciphertext = AESGCM(dek).encrypt(data_iv, plaintext, None)
        encrypted_dek = kek_iv + self._kek.encrypt(kek_iv, dek, None)
        checksum = hashlib.sha256(plaintext).hexdigest()
        return {
            "encrypted_payload": ciphertext,
            "encryption_iv": data_iv,
            "encrypted_dek": encrypted_dek,
            "checksum_sha256": checksum,
        }

    def decrypt_document(self, encrypted_payload: bytes, encryption_iv: bytes, encrypted_dek: bytes) -> bytes:
        kek_iv = encrypted_dek[:12]
        wrapped_dek = encrypted_dek[12:]
        dek = self._kek.decrypt(kek_iv, wrapped_dek, None)
        return AESGCM(dek).decrypt(encryption_iv, encrypted_payload, None)


def get_envelope_cipher(settings: Settings | None = None) -> EnvelopeCipher:
    return EnvelopeCipher(settings)

