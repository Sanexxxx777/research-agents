"""Minimal async TTL cache used by project analysis pipeline."""

from __future__ import annotations

import time
from typing import Any


class Cache:
    """In-memory async cache with optional TTL support."""

    def __init__(self) -> None:
        self._store: dict[str, tuple[float | None, Any]] = {}

    async def get(self, key: str) -> Any:
        row = self._store.get(key)
        if row is None:
            return None
        expires_at, value = row
        if expires_at is not None and expires_at <= time.time():
            self._store.pop(key, None)
            return None
        return value

    async def set(self, key: str, value: Any, ttl: int | None = None) -> None:
        expires_at = None
        if ttl is not None and ttl > 0:
            expires_at = time.time() + ttl
        self._store[key] = (expires_at, value)
