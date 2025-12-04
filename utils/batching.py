from __future__ import annotations

from typing import Iterable, List, Sequence


def chunk_by_char_limit(items: Sequence[str], *, max_chars: int, max_items: int) -> List[List[str]]:
    batches: List[List[str]] = []
    current: List[str] = []
    char_count = 0
    for item in items:
        item_len = len(item)
        if current and (char_count + item_len > max_chars or len(current) >= max_items):
            batches.append(current)
            current = []
            char_count = 0
        current.append(item)
        char_count += item_len
    if current:
        batches.append(current)
    return batches
