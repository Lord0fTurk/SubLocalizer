from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Iterable, List, Sequence


@dataclass(slots=True)
class TranslationRequest:
    texts: Sequence[str]
    source_lang: str
    target_lang: str


class BaseTranslator(ABC):
    name: str = "base"
    supports_batching: bool = True
    max_chars_per_request: int = 5000
    concurrency_limit: int = 1

    def __init__(self, *, timeout: float = 20.0, proxy: str | None = None) -> None:
        self.timeout = timeout
        self.proxy = proxy

    @abstractmethod
    async def translate_texts(self, request: TranslationRequest) -> List[str]:
        """Translate a batch of texts and return the translated payloads."""

    def chunk_input(self, texts: Iterable[str]) -> List[str]:
        return list(texts)
