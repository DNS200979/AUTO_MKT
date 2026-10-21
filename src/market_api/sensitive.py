from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken


class SensitiveDataError(RuntimeError):
    pass


class DataCipher:
    prefix = "enc:v1:"

    def __init__(self, keys: dict[str, str] | None = None) -> None:
        keys = keys or {}
        self._keys: dict[str, Fernet] = {}
        for key_id, key in keys.items():
            if not key_id or ":" in key_id:
                raise ValueError("encryption key IDs must be non-empty and cannot contain ':'")
            try:
                self._keys[key_id] = Fernet(key.encode())
            except (TypeError, ValueError) as exc:
                raise ValueError(f"invalid encryption key: {key_id}") from exc
        self.active_key_id = next(iter(self._keys), None)

    @property
    def enabled(self) -> bool:
        return self.active_key_id is not None

    def encrypt(self, value: str | None) -> str | None:
        if value is None or not self.enabled:
            return value
        if value.startswith(self.prefix) and not self.needs_rotation(value):
            return value
        plaintext = self.decrypt(value) if value.startswith(self.prefix) else value
        assert self.active_key_id is not None
        token = self._keys[self.active_key_id].encrypt(plaintext.encode()).decode()
        return f"{self.prefix}{self.active_key_id}:{token}"

    def decrypt(self, value: str | None) -> str | None:
        if value is None or not value.startswith(self.prefix):
            return value
        try:
            _, _, key_id, token = value.split(":", 3)
            cipher = self._keys[key_id]
            return cipher.decrypt(token.encode()).decode()
        except (InvalidToken, KeyError, UnicodeDecodeError, ValueError) as exc:
            raise SensitiveDataError("sensitive value cannot be decrypted") from exc

    def needs_rotation(self, value: str) -> bool:
        if not value.startswith(self.prefix):
            return self.enabled
        try:
            key_id = value.split(":", 3)[2]
        except IndexError:
            return True
        return key_id != self.active_key_id

    def key_id(self, value: str | None) -> str:
        if value is None:
            return "none"
        if not value.startswith(self.prefix):
            return "plaintext"
        try:
            key_id = value.split(":", 3)[2]
        except IndexError:
            return "invalid"
        return key_id or "invalid"
