import base64
import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

import jwt
from cryptography.fernet import Fernet, InvalidToken
from pwdlib import PasswordHash


class InvalidEncryptedValueError(ValueError):
    pass


class PasswordService:
    def __init__(self) -> None:
        self._password_hash = PasswordHash.recommended()

    def hash(self, password: str) -> str:
        return self._password_hash.hash(password)

    def verify(self, password: str, password_hash: str) -> bool:
        return self._password_hash.verify(password, password_hash)


class ApiKeyCipher:
    def __init__(self, secret: str) -> None:
        if not secret:
            raise ValueError("Key encryption secret is required")
        key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode("utf-8")).digest())
        self._fernet = Fernet(key)

    def encrypt(self, value: str) -> bytes:
        return self._fernet.encrypt(value.encode("utf-8"))

    def decrypt(self, encrypted_value: bytes) -> str:
        try:
            return self._fernet.decrypt(encrypted_value).decode("utf-8")
        except (InvalidToken, UnicodeDecodeError) as exc:
            raise InvalidEncryptedValueError("Stored API key cannot be decrypted") from exc

    @staticmethod
    def mask(value: str) -> str:
        if len(value) <= 8:
            return "*" * len(value)
        return f"{value[:3]}{'*' * 8}{value[-4:]}"


@dataclass(frozen=True)
class AccessTokenClaims:
    member_id: UUID


class JwtService:
    def __init__(self, secret: str, lifetime: timedelta = timedelta(hours=12)) -> None:
        self._secret = secret
        self._lifetime = lifetime

    def issue(self, member_id: UUID) -> str:
        now = datetime.now(UTC)
        return jwt.encode(
            {"sub": str(member_id), "iat": now, "exp": now + self._lifetime},
            self._secret,
            algorithm="HS256",
        )

    def decode(self, token: str) -> AccessTokenClaims:
        try:
            payload = jwt.decode(token, self._secret, algorithms=["HS256"])
            return AccessTokenClaims(member_id=UUID(payload["sub"]))
        except (jwt.PyJWTError, KeyError, TypeError, ValueError) as exc:
            raise ValueError("Invalid or expired access token") from exc
