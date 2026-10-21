from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol


class SecretProviderError(RuntimeError):
    pass


class SecretProvider(Protocol):
    def load(self) -> dict[str, object]: ...


class JsonFileSecretProvider:
    """Reads an atomic JSON secret mounted by an orchestrator or secret agent."""

    max_bytes = 64 * 1024

    def __init__(self, path: str) -> None:
        self.path = Path(path)

    def load(self) -> dict[str, object]:
        try:
            if not self.path.is_file():
                raise SecretProviderError("secrets file is not a regular file")
            if self.path.stat().st_size > self.max_bytes:
                raise SecretProviderError("secrets file exceeds the size limit")
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except SecretProviderError:
            raise
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise SecretProviderError("secrets file cannot be loaded") from exc
        if not isinstance(payload, dict):
            raise SecretProviderError("secrets file must contain a JSON object")
        return payload
