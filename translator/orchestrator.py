from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass
from typing import Awaitable, Callable, List, Sequence

from config import SETTINGS, RetryPolicy
from utils.cache import TranslationMemory, SessionCache, make_cache_key
from utils.text import deduplicate_texts

from .base import BaseTranslator, TranslationRequest


ProgressCallback = Callable[[int, int], None]
LogCallback = Callable[[str], None]


@dataclass(slots=True)
class PendingEntry:
    text: str
    indexes: List[int]
    cache_key: str


class TranslationOrchestrator:
    def __init__(
        self,
        translator: BaseTranslator,
        memory: TranslationMemory,
        session_cache: SessionCache,
        retry_policy: RetryPolicy | None = None,
        *,
        batch_char_limit: int | None = None,
        batch_size: int | None = None,
    ) -> None:
        self.translator = translator
        self.memory = memory
        self.session_cache = session_cache
        self.retry_policy = retry_policy or SETTINGS.retry
        self.batch_char_limit = batch_char_limit or SETTINGS.translator.batch_char_limit
        self.batch_size = batch_size or SETTINGS.translator.batch_size

    async def translate(
        self,
        *,
        texts: Sequence[str],
        source_lang: str,
        target_lang: str,
        progress_cb: ProgressCallback | None = None,
        log_cb: LogCallback | None = None,
    ) -> List[str]:
        total = len(texts)
        resolved: List[str | None] = [None] * total
        dedup = deduplicate_texts(list(texts))

        pending: List[PendingEntry] = []
        for unique_text, indexes in zip(dedup.unique_texts, dedup.groups):
            key = make_cache_key(unique_text, source_lang, target_lang)
            cached = self.session_cache.get(key) or self.memory.get(key)
            if cached:
                for idx in indexes:
                    resolved[idx] = cached
                continue
            pending.append(PendingEntry(text=unique_text, indexes=list(indexes), cache_key=key))

        completed = sum(1 for item in resolved if item is not None)
        if progress_cb:
            progress_cb(completed, total)

        if pending:
            await self._translate_pending(
                pending=pending,
                resolved=resolved,
                source_lang=source_lang,
                target_lang=target_lang,
                progress_cb=progress_cb,
                log_cb=log_cb,
            )

        missing = [idx for idx, value in enumerate(resolved) if value is None]
        if missing:
            raise RuntimeError(f"Missing translations for indexes: {missing}")
        return [text or "" for text in resolved]

    async def _translate_pending(
        self,
        *,
        pending: Sequence[PendingEntry],
        resolved: List[str | None],
        source_lang: str,
        target_lang: str,
        progress_cb: ProgressCallback | None,
        log_cb: LogCallback | None,
    ) -> None:
        entries = list(pending)
        batches = self._build_batches(entries)
        total = len(resolved)
        completed = sum(1 for item in resolved if item is not None)

        for batch in batches:
            texts = [entry.text for entry in batch]

            async def action() -> List[str]:
                request = TranslationRequest(texts=texts, source_lang=source_lang, target_lang=target_lang)
                return await self.translator.translate_texts(request)

            translations = await self._retry(action, log_cb=log_cb)
            if len(translations) != len(batch):
                raise RuntimeError("Translator returned mismatched batch size")
            for entry, translated in zip(batch, translations):
                self.session_cache.set(entry.cache_key, translated)
                self.memory.set(entry.cache_key, translated)
                for idx in entry.indexes:
                    resolved[idx] = translated
                    completed += 1
                    if progress_cb:
                        progress_cb(completed, total)

    def _build_batches(self, entries: Sequence[PendingEntry]) -> List[List[PendingEntry]]:
        batches: List[List[PendingEntry]] = []
        current: List[PendingEntry] = []
        char_count = 0
        for entry in entries:
            entry_len = len(entry.text)
            if current and (char_count + entry_len > self.batch_char_limit or len(current) >= self.batch_size):
                batches.append(current)
                current = []
                char_count = 0
            current.append(entry)
            char_count += entry_len
        if current:
            batches.append(current)
        return batches

    async def _retry(self, action: Callable[[], Awaitable[List[str]]], log_cb: LogCallback | None) -> List[str]:
        attempt = 0
        delay = 1.0
        while True:
            attempt += 1
            try:
                return await action()
            except Exception as exc:  # noqa: BLE001
                if log_cb:
                    log_cb(f"Translation attempt {attempt} failed: {exc}")
                if attempt >= self.retry_policy.max_attempts:
                    raise
                jitter = random.uniform(0, self.retry_policy.backoff_jitter)
                await asyncio.sleep(delay + jitter)
                delay *= self.retry_policy.backoff_factor
