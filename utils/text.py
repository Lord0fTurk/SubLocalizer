from __future__ import annotations

from dataclasses import dataclass
from typing import List
from difflib import SequenceMatcher


@dataclass(slots=True)
class DeduplicationResult:
    unique_texts: List[str]
    groups: List[List[int]]  # Each group contains indexes pointing back to the source list


def deduplicate_texts(texts: List[str], *, similarity_threshold: float = 0.985) -> DeduplicationResult:
    unique: List[str] = []
    groups: List[List[int]] = []
    for idx, text in enumerate(texts):
        normalized = text.strip()
        match_index = _find_match(normalized, unique, similarity_threshold)
        if match_index is None:
            unique.append(text)
            groups.append([idx])
        else:
            groups[match_index].append(idx)
    return DeduplicationResult(unique_texts=unique, groups=groups)


def _find_match(candidate: str, pool: List[str], threshold: float) -> int | None:
    for i, other in enumerate(pool):
        if candidate == other:
            return i
        if _sequence_ratio(candidate, other) >= threshold:
            return i
    return None


def _sequence_ratio(a: str, b: str) -> float:
    if not a and not b:
        return 1.0
    return SequenceMatcher(None, a, b).ratio()
