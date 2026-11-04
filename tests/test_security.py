import pytest
from cryptography.fernet import Fernet

from app.core.exceptions import ConfigurationError
from app.core.security import decrypt_secret, encrypt_secret


def test_encrypt_decrypt_roundtrip() -> None:
    secret_key = Fernet.generate_key().decode()

    ciphertext = encrypt_secret("sk-test-secret", secret_key)

    assert ciphertext != "sk-test-secret"
    assert decrypt_secret(ciphertext, secret_key) == "sk-test-secret"


def test_decrypt_with_wrong_key_fails() -> None:
    ciphertext = encrypt_secret("sk-test-secret", Fernet.generate_key().decode())

    with pytest.raises(ConfigurationError):
        decrypt_secret(ciphertext, Fernet.generate_key().decode())


def test_invalid_secret_key_fails() -> None:
    with pytest.raises(ConfigurationError):
        encrypt_secret("sk-test-secret", "not-a-fernet-key")
