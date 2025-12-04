from __future__ import annotations

from typing import Sequence

from langdetect import DetectorFactory, LangDetectException, detect

DetectorFactory.seed = 0


def detect_language(texts: Sequence[str], *, max_chars: int = 2500) -> str | None:
    sample = _build_sample(texts, max_chars=max_chars)
    if not sample.strip():
        return None
    try:
        return detect(sample)
    except LangDetectException:
        return None


def _build_sample(texts: Sequence[str], *, max_chars: int) -> str:
    buffer: list[str] = []
    total = 0
    for text in texts:
        if not text:
            continue
        remaining = max_chars - total
        if remaining <= 0:
            break
        snippet = text.strip()
        if not snippet:
            continue
        if len(snippet) > remaining:
            snippet = snippet[:remaining]
        buffer.append(snippet)
        total += len(snippet)
    return "\n".join(buffer)
