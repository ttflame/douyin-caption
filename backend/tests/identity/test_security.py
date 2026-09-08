from datetime import timedelta
from uuid import uuid4

import pytest

from app.modules.identity.security import (
    ApiKeyCipher,
    InvalidEncryptedValueError,
    JwtService,
    PasswordService,
)


def test_password_hash_is_not_plaintext_and_verifies() -> None:
    service = PasswordService()
    hashed = service.hash("correct horse battery staple")

    assert hashed != "correct horse battery staple"
    assert service.verify("correct horse battery staple", hashed)
    assert not service.verify("wrong password", hashed)


def test_jwt_round_trip() -> None:
    member_id = uuid4()
    service = JwtService("a" * 32, timedelta(minutes=5))

    assert service.decode(service.issue(member_id)).member_id == member_id


def test_jwt_rejects_other_signing_key() -> None:
    token = JwtService("a" * 32).issue(uuid4())

    with pytest.raises(ValueError, match="Invalid or expired"):
        JwtService("b" * 32).decode(token)


def test_api_key_cipher_encrypts_masks_and_rejects_wrong_key() -> None:
    cipher = ApiKeyCipher("deployment secret")
    encrypted = cipher.encrypt("sk-1234567890abcdef")

    assert b"sk-1234567890abcdef" not in encrypted
    assert cipher.decrypt(encrypted) == "sk-1234567890abcdef"
    assert cipher.mask("sk-1234567890abcdef") == "sk-********cdef"

    with pytest.raises(InvalidEncryptedValueError):
        ApiKeyCipher("different secret").decrypt(encrypted)
