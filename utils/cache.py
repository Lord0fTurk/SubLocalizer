from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Dict
import json
import threading


def make_cache_key(text: str, source: str, target: str) -> str:
    return f"{source}::{target}::{text}"


class TranslationMemory:
    def __init__(self, path: Path, *, auto_flush: bool = True) -> None:
        self.path = path
        self.auto_flush = auto_flush
        self._lock = threading.Lock()
        self._data: Dict[str, str] = {}
        self._dirty = False
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text("{}", encoding="utf-8")
        try:
            with self.path.open("r", encoding="utf-8") as handle:
                self._data = json.load(handle)
        except json.JSONDecodeError:
            self._data = {}

    def get(self, key: str) -> str | None:
        with self._lock:
            return self._data.get(key)

    def set(self, key: str, value: str) -> None:
        with self._lock:
            self._data[key] = value
            self._dirty = True
        if self.auto_flush:
            self.flush()

    def flush(self) -> None:
        with self._lock:
            if not self._dirty:
                return
            with self.path.open("w", encoding="utf-8") as handle:
                json.dump(self._data, handle, ensure_ascii=False, indent=2)
            self._dirty = False


class SessionCache:
    def __init__(self, *, maxsize: int = 2048) -> None:
        self._store: Dict[str, str] = {}
        self._fetch_cached = lru_cache(maxsize=maxsize)(self._fetch)

    def _fetch(self, key: str) -> str | None:
        return self._store.get(key)

    def get(self, key: str) -> str | None:
        return self._fetch_cached(key)

    def set(self, key: str, value: str) -> None:
        self._store[key] = value
        self._fetch_cached.cache_clear()

    def __contains__(self, key: str) -> bool:
        return self._store.get(key) is not None
